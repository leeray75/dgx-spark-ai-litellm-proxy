#!/usr/bin/env python3
"""Check which reasoning effort the Flash-Next engine applies, and how much it thinks.

The checkpoint's chat template (nvidia/Qwen3.8-Flash-Next-FP4-Local) takes a
`reasoning_effort` template kwarg: xhigh (template default), medium or low;
anything else raises. xhigh injects "validate key assumptions, consider
plausible alternatives" into the system prompt, low injects "keep your
thinking brief", medium injects nothing. The engine's server-wide default
comes from --default-chat-template-kwargs in docker-compose.qwen3.8-flash-next.yml.

Two checks:
  1. template  - renders prompts through the engine's /tokenize endpoint (no
                 generation) and reports which effort instruction is injected,
                 for the server default and for per-request overrides.
  2. behavior  - sends an agentic-coding prompt with a stated requirement
                 (Twitch OAuth callback must be https) through LiteLLM and
                 reports reasoning length, latency and whether the answer
                 kept https. LiteLLM's Redis cache is bypassed (no-cache plus
                 a per-request nonce).

    ./scripts/test-reasoning-effort.py                       # both checks
    ./scripts/test-reasoning-effort.py --skip-behavior       # template only
    ./scripts/test-reasoning-effort.py --expect-default medium --trials 3
    ./scripts/test-reasoning-effort.py --json-out /path/run.json

Exit code 1 if --expect-default is given and the server default differs, or
if any behavior request fails.
"""
import argparse
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
ENGINE_MODEL = "qwen3.8-flash-next"

# First words of each instruction the template injects (chat_template.jinja).
EFFORT_MARKERS = {
    "xhigh": "Reasoning effort is set to xhigh.",
    "low": "Reasoning effort is set to low.",
}

BEHAVIOR_SYSTEM = (
    "You are a coding agent working in a Node.js/Express project. "
    "Follow the user's stated requirements exactly."
)
BEHAVIOR_PROMPT = (
    "Add Twitch OAuth login to our Express app. Requirement from me (the project "
    "owner): the OAuth callback / redirect URL MUST use https, not http - use "
    "https://localhost:3000/auth/twitch/callback. Write the route code and the "
    "config constant for the redirect URI. Output only the code."
)


def load_env_key(name):
    if os.environ.get(name):
        return os.environ[name]
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                value = line.split("=", 1)[1].split(" #", 1)[0]  # drop inline comment
                return value.strip().strip('"').strip("'")
    return None


def post_json(url, body, headers=None, timeout=900):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def detect_effort(rendered):
    if "<think>\n\n</think>" in rendered:
        return "off"
    for effort, marker in EFFORT_MARKERS.items():
        if marker in rendered:
            return effort
    return "medium"  # thinking on, no instruction injected


def render(engine, kwargs=None, reasoning_effort=None):
    body = {
        "model": ENGINE_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "add_generation_prompt": True,
    }
    if kwargs is not None:
        body["chat_template_kwargs"] = kwargs
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    tokens = post_json(f"{engine}/tokenize", body)["tokens"]
    return post_json(f"{engine}/detokenize", {"model": ENGINE_MODEL, "tokens": tokens})["prompt"]


def check_template(engine):
    cases = [
        ("server default (no kwargs)", None, None),
        ("chat_template_kwargs effort=low", {"reasoning_effort": "low"}, None),
        ("chat_template_kwargs effort=medium", {"reasoning_effort": "medium"}, None),
        ("chat_template_kwargs effort=xhigh", {"reasoning_effort": "xhigh"}, None),
        ("enable_thinking=false (-nothink)", {"enable_thinking": False}, None),
        ("top-level reasoning_effort=low", None, "low"),
    ]
    results = {}
    print("== Template check (engine /tokenize, no generation)")
    for label, kwargs, top in cases:
        try:
            effort = detect_effort(render(engine, kwargs, top))
        except urllib.error.HTTPError as e:
            effort = f"ERROR {e.code}"
        results[label] = effort
        print(f"  {label:<38} -> {effort}")
    return results


def run_behavior(litellm, key, alias, trials, max_tokens):
    rows = []
    for i in range(trials):
        nonce = uuid.uuid4().hex[:8]
        body = {
            "model": alias,
            "messages": [
                {"role": "system", "content": f"{BEHAVIOR_SYSTEM} (run {nonce})"},
                {"role": "user", "content": BEHAVIOR_PROMPT},
            ],
            "max_tokens": max_tokens,
            "cache": {"no-cache": True},
        }
        t0 = time.monotonic()
        try:
            resp = post_json(
                f"{litellm}/v1/chat/completions", body, {"authorization": f"Bearer {key}"}
            )
        except urllib.error.HTTPError as e:
            rows.append({"alias": alias, "error": f"HTTP {e.code}: {e.read()[:200]!r}"})
            print(f"  {alias} #{i + 1}: HTTP {e.code}")
            continue
        elapsed = time.monotonic() - t0
        msg = resp["choices"][0]["message"]
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        content = msg.get("content") or ""
        usage = resp.get("usage") or {}
        row = {
            "alias": alias,
            "seconds": round(elapsed, 1),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_chars": len(reasoning),
            "content_chars": len(content),
            "finish_reason": resp["choices"][0].get("finish_reason"),
            "uses_https_callback": "https://localhost:3000/auth/twitch/callback" in content,
            "has_http_callback": "http://localhost:3000/auth/twitch/callback" in content,
        }
        rows.append(row)
        print(
            f"  {alias} #{i + 1}: {row['seconds']:>6}s  completion_tokens={row['completion_tokens']}"
            f"  reasoning_chars={row['reasoning_chars']}  https={row['uses_https_callback']}"
            f"  http={row['has_http_callback']}  finish={row['finish_reason']}"
        )
    return rows


def summarize(rows):
    ok = [r for r in rows if "error" not in r]
    if not ok:
        return {}
    return {
        "n": len(ok),
        "median_seconds": statistics.median(r["seconds"] for r in ok),
        "median_completion_tokens": statistics.median(r["completion_tokens"] or 0 for r in ok),
        "median_reasoning_chars": statistics.median(r["reasoning_chars"] for r in ok),
        "https_ok": sum(r["uses_https_callback"] and not r["has_http_callback"] for r in ok),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default="http://localhost:8301")
    ap.add_argument("--litellm", default="http://localhost:4000")
    ap.add_argument("--aliases", default="qwen3.8-flash-next,qwen3.8-flash-next-nothink")
    ap.add_argument("--trials", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=16384)
    ap.add_argument("--expect-default", choices=["xhigh", "medium", "low", "off"])
    ap.add_argument("--skip-behavior", action="store_true")
    ap.add_argument("--json-out")
    args = ap.parse_args()

    failed = False
    out = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out["template"] = check_template(args.engine)
    default = out["template"]["server default (no kwargs)"]
    if args.expect_default:
        match = default == args.expect_default
        failed |= not match
        print(f"  expected server default {args.expect_default}: {'PASS' if match else 'FAIL'}")

    if not args.skip_behavior:
        key = load_env_key("LITELLM_MASTER_KEY")
        if not key:
            sys.exit("LITELLM_MASTER_KEY not set and not found in .env")
        print(f"\n== Behavior check via LiteLLM ({args.trials} trial(s) per alias)")
        out["behavior"] = {}
        for alias in args.aliases.split(","):
            rows = run_behavior(args.litellm, key, alias, args.trials, args.max_tokens)
            failed |= any("error" in r for r in rows)
            out["behavior"][alias] = {"rows": rows, "summary": summarize(rows)}
        print("\n== Summary (medians)")
        for alias, data in out["behavior"].items():
            print(f"  {alias:<32} {data['summary']}")

    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json_out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
