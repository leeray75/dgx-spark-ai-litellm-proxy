#!/usr/bin/env python3
"""Sync agentgateway's model cost overlay from the Langfuse project's model prices.

Langfuse (project dgx-spark) is the source of truth for prices: the
llm-power-cost skill re-derives qwen's electricity cost and writes it there.
This script copies the project's custom (non-Langfuse-managed) model
definitions into agentgateway/costs/langfuse-overlay.json, which
agentgateway/config.yaml loads via config.modelCatalog. agentgateway watches
catalog files and reloads them on change, so no restart is needed:

    ./scripts/agentgateway-sync-costs.py

Mapping:
  - agentgateway looks prices up by (provider id, model name). For the vLLM
    models the provider id is the llm.providers[].name from config.yaml
    (e.g. vllm-qwen38), so each Langfuse model is matched against the
    llm.models[] entries in config.yaml: by `name`, and by `params.model`
    for aliases (qwen3.8-27b-nothink -> qwen3.8-27b), priced under both names.
  - Langfuse claude-* models map to provider `anthropic`.
  - Langfuse models with no agentgateway route (e.g. qwen3-coder-next) are
    skipped and listed.
  - Units: Langfuse stores USD per token, agentgateway wants USD per 1M
    tokens as decimal strings.
  - Langfuse's 1h cache-write price has no agentgateway field; the 5m price
    is used for cacheWrite.
  - Pricing tiers: a Langfuse tier with a single `input ... gt N` condition
    (the "Large Context" shape, e.g. claude-haiku-5-5 over 100K) becomes an
    agentgateway tier with contextOver N. Other tier conditions can't be
    expressed and are skipped with a warning (the default tier still applies).

Reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY from .env. Langfuse URL
defaults to http://localhost:3000 (override with LANGFUSE_URL).
"""
import base64
import json
import os
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "agentgateway" / "config.yaml"
OUT = ROOT / "agentgateway" / "costs" / "langfuse-overlay.json"

# Langfuse price key -> agentgateway rate field (first match wins).
RATE_KEYS = {
    "input": ["input", "input_tokens"],
    "output": ["output", "output_tokens"],
    "cacheRead": ["input_cache_read", "input_cached_tokens", "cache_read_input_tokens"],
    "cacheWrite": ["input_cache_creation_5m", "input_cache_creation", "cache_creation_input_tokens"],
}


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def fetch_custom_models(url, auth):
    models, page = [], 1
    while True:
        req = urllib.request.Request(
            f"{url}/api/public/models?limit=100&page={page}",
            headers={"Authorization": f"Basic {auth}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        models += [m for m in body["data"] if not m.get("isLangfuseManaged")]
        if page >= body["meta"]["totalPages"]:
            return models
        page += 1


def route_targets(config):
    """Map upstream model name -> [(provider id, model name)] from config.yaml."""
    targets = {}
    for m in config.get("llm", {}).get("models", []):
        provider = m.get("provider")
        if not isinstance(provider, dict) or "reference" not in provider:
            continue
        pid = provider["reference"]
        upstream = (m.get("params") or {}).get("model", m["name"])
        for name in {m["name"], upstream}:
            targets.setdefault(upstream, set()).add((pid, name))
    return targets


def per_million(price):
    # agentgateway rejects rates with more than 6 fractional digits, so float
    # noise from Langfuse (e.g. 1.9999999999999998e-05) must not leak through.
    rate = (Decimal(str(price)) * 1_000_000).quantize(Decimal("0.000001"))
    return format(rate.normalize(), "f")


def rates_from(prices):
    rates = {}
    for field, keys in RATE_KEYS.items():
        for k in keys:
            if prices.get(k) is not None:
                rates[field] = per_million(prices[k])
                break
    return rates


def entry_for(model, warnings):
    """Build an agentgateway catalog entry ({rates, tiers?}) for a Langfuse model."""
    tiers = model.get("pricingTiers") or []
    default = next((t for t in tiers if t.get("isDefault")), None)
    if default:
        rates = rates_from(default["prices"])
    else:
        rates = rates_from({k: v["price"] for k, v in (model.get("prices") or {}).items()})
    entry = {"rates": rates}

    extra = []
    for t in tiers:
        if t.get("isDefault"):
            continue
        conds = t.get("conditions") or []
        c = conds[0] if len(conds) == 1 else {}
        if c.get("operator") == "gt" and c.get("usageDetailPattern", "").startswith("input"):
            extra.append({"contextOver": int(c["value"]), "rates": rates_from(t["prices"])})
        else:
            warnings.append(f"{model['modelName']}: tier {t.get('name')!r} has conditions agentgateway can't express")
    if extra:
        entry["tiers"] = sorted(extra, key=lambda t: t["contextOver"])
    return entry


def main():
    env = load_env()
    url = os.environ.get("LANGFUSE_URL", "http://localhost:3000")
    auth = base64.b64encode(
        f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()
    targets = route_targets(yaml.safe_load(CONFIG.read_text()))

    providers, skipped, warnings = {}, [], []
    for m in fetch_custom_models(url, auth):
        name = m["modelName"]
        entry = entry_for(m, warnings)
        if not entry["rates"]:
            skipped.append(f"{name} (no token prices)")
            continue
        if name.startswith("claude-"):
            dests = {("anthropic", name)}
        else:
            dests = targets.get(name)
        if not dests:
            skipped.append(f"{name} (no agentgateway route)")
            continue
        for pid, model_name in sorted(dests):
            providers.setdefault(pid, {"models": {}})["models"][model_name] = entry

    # No "metadata" key: agentgateway applies this file as an overlay on top of
    # its built-in catalog instead of treating it as a (possibly stale) base.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"providers": providers}, indent=2, sort_keys=True) + "\n")

    print(f"wrote {OUT.relative_to(ROOT)}")
    for pid, p in sorted(providers.items()):
        for model_name, entry in sorted(p["models"].items()):
            tiers = "".join(f"  >{t['contextOver']}: {t['rates']}" for t in entry.get("tiers", []))
            print(f"  {pid}/{model_name}: {entry['rates']}{tiers}")
    if skipped:
        print("skipped: " + ", ".join(skipped))
    for w in warnings:
        print("warning: " + w)


if __name__ == "__main__":
    sys.exit(main())
