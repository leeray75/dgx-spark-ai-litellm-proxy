# Claude Code → LiteLLM Proxy Configuration Report — 17 July 2026

## Summary
Claude Code on this machine does not talk to Anthropic's public API directly. It is configured, via `~/.claude/settings.json`, to send all requests to the local LiteLLM proxy on port 4000, which then routes each request either to the real Anthropic API (for `claude-*`/`anthropic/*` model IDs) or to a local vLLM engine (for the Qwen/Nemotron aliases), depending on `litellm-config.yaml`.

---

## 1. Redirect Mechanism

Claude Code's HTTP client honors two environment variables at process start:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_BASE_URL` | Overrides the API host (default `https://api.anthropic.com`) |
| `ANTHROPIC_AUTH_TOKEN` (or `ANTHROPIC_API_KEY`) | Bearer token sent with every request |

Once `ANTHROPIC_BASE_URL` is set, Anthropic's real endpoint is never contacted by the client — every call goes to the configured host instead.

---

## 2. Where It's Set

`~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:4000",
    "ANTHROPIC_AUTH_TOKEN": "sk-REDACTED",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"
  },
  "model": "sonnet"
}
```

Claude Code loads the `env` block on every launch and injects it into its own process environment — confirmed by inspecting the live process env, which shows `ANTHROPIC_BASE_URL=http://localhost:4000` and `ANTHROPIC_AUTH_TOKEN` set accordingly. No shell profile (`.bashrc`/`.zshrc`/`.profile`) references these variables — `settings.json` is the sole source.

`"model": "sonnet"` only sets the default model alias requested; it has no effect on routing.

---

## 3. What's Listening on :4000

A LiteLLM proxy process:

```
/usr/bin/litellm --config /app/config.yaml --port 4000 --drop_params
```

Run via `docker compose` from this repo (`ai-litellm-proxy`), backed by a Postgres container. `curl localhost:4000/health` returns `401` unauthenticated, confirming the proxy enforces bearer-token auth — `ANTHROPIC_AUTH_TOKEN` must match a key LiteLLM recognizes (master key or virtual key).

---

## 4. Routing Table (`litellm-config.yaml`)

| `model_name` | Backend | Notes |
|---|---|---|
| `anthropic/*` (wildcard) | Real Anthropic API | Forwards any `claude-*`/`anthropic/*` ID verbatim, authenticated server-side with LiteLLM's own `ANTHROPIC_API_KEY` |
| `qwen3.6-35b-a3b` | Local vLLM, `qwen3-6-35b-nvfp4-engine:8000` | 131K context |
| `qwen3-coder-next` | Local vLLM, `qwen3-coder-next-engine:8000` | 262K context |
| `nemotron-super` | Local vLLM, `nemotron-engine:8000` | 32K context |
| `llama-nemotron-embed-vl-1b-v2` | Local vLLM, `nemotron-embed-vl-engine:8000` | Embeddings only |

Claude/Anthropic requests are a **two-hop relay**: Claude Code → LiteLLM (authenticated with `ANTHROPIC_AUTH_TOKEN`, local) → Anthropic (authenticated with LiteLLM's own `ANTHROPIC_API_KEY`, real). The client-facing token and the upstream Anthropic key are distinct secrets — only the proxy holds the real one.

Non-Anthropic model aliases bypass Anthropic entirely and hit local GPU inference.

`default_fallbacks: ["qwen3.6-35b-a3b"]` means if the `anthropic/*` passthrough fails after retries (e.g., real API down/rate-limited), LiteLLM retries against the local Qwen3.6 engine instead of surfacing the failure.

> Note (from `ai-litellm-proxy/CLAUDE.md`): dedicated Claude Code proxy aliases (`claude-sonnet-4-6`, `claude-haiku-4-6`) were removed in v1.3.0 — there is no local-model alias masquerading under a `claude-*` name anymore. Local models are addressed by their own names (`qwen3.6-35b-a3b`, etc.).

---

## 5. Model Discovery in the `/model` Picker

`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` lets Claude Code query the proxy for its available model list and populate the `/model` picker. Only IDs prefixed `claude*`/`anthropic*` are surfaced automatically by this discovery filter — the local vLLM aliases (`qwen3.6-35b-a3b`, `qwen3-coder-next`, `nemotron-super`) do **not** appear there and must be typed manually, or given a `claude-`-prefixed alias in `litellm-config.yaml` if picker visibility is wanted.

---

## 6. Open Item

`ANTHROPIC_AUTH_TOKEN` in `~/.claude/settings.json` was found to be an unrotated placeholder-looking value rather than a generated secret (redacted above). It works (LiteLLM's `401` disappears with it set), so it presumably matches `LITELLM_MASTER_KEY` or a seeded virtual key in the proxy's `.env`. Exposure risk is low since the proxy only binds to `localhost`, but it's worth rotating to a generated key if this config is ever exposed beyond loopback.
