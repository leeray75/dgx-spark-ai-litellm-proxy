# LiteLLM `/v1/messages` Thinking-Block Passthrough Fix — Summary Report

**Date:** 2026-08-28
**Branch:** `fix/anthropic-messages-thinking-passthrough` (branched off `feat/qwen3.8-27b-nvfp4-stack`)
**Base:** current working tree, following commit `d15d632`

---

## Symptom

A downstream client (Claude Code, talking Anthropic Messages protocol) could correctly enumerate a large
skill/tool listing embedded in its system prompt when pointed directly at vLLM (`http://<host>:8301`), but failed
to do so when pointed at the same model through LiteLLM (`http://<host>:4000`). Both endpoints returned `200 OK`
and the same final answer at small prompt sizes — the failure only showed up when the response was truncated
mid-reasoning by `max_tokens`.

## Investigation

Reproduced directly against both endpoints (not inferred):

- **Small prompt, no truncation**: direct vLLM returned `content: [{"type":"thinking",...}, {"type":"text",...}]`;
  LiteLLM returned only the `text` block — the `thinking` block was missing entirely, silently.
- **Realistic prompt (~1900 input tokens) with constrained `max_tokens`**, forcing truncation mid-reasoning:
  direct vLLM still returned a partial `thinking` block (1572 chars, containing the correct answer, since this
  model reasons by listing items early); LiteLLM returned `content: []` — completely empty, same `stop_reason`,
  same `usage.output_tokens`.

Read LiteLLM's actual source inside the running `litellm-proxy` container (`ghcr.io/berriai/litellm:main-latest`,
resolves to **litellm 1.82.6**, image built 2026-08-26 — current, not stale) rather than guessing from docs:

1. `litellm/llms/anthropic/experimental_pass_through/messages/handler.py` routes any `openai/`-prefixed model
   through LiteLLM's OpenAI **Responses API** translation bridge by default, not chat/completions:
   ```python
   _RESPONSES_API_PROVIDERS = frozenset({"openai"})
   def _should_route_to_responses_api(custom_llm_provider):
       if litellm.use_chat_completions_url_for_anthropic_messages:
           return False
       return custom_llm_provider in _RESPONSES_API_PROVIDERS
   ```
   Since `qwen3.6-35b-a3b` is registered as `openai/qwen3.6-35b-a3b`, every `/v1/messages` request took this path
   — a different code path from the one the original investigation assumed (chat-completions↔Anthropic
   conversion).

2. Called vLLM's native `/v1/responses` directly to see the real response shape:
   ```json
   { "type": "reasoning", "summary": [], "content": [{"type": "reasoning_text", "text": "Here's a thinking process:..."}] }
   ```
   vLLM puts the raw chain-of-thought under `output[].content[].text`, and leaves `output[].summary` **always
   empty** — populating `summary` is OpenAI's own proprietary reasoning-summarizer step, which vLLM doesn't
   implement.

3. `litellm/llms/anthropic/experimental_pass_through/responses_adapters/transformation.py::translate_response()`
   only reads `item.summary` for a `ResponseReasoningItem`, never `item.content`:
   ```python
   if isinstance(item, ResponseReasoningItem):
       for summary in item.summary:        # always [] for vLLM
           ...append thinking block...
   ```
   So the `thinking` block is dropped **on every request**, deterministically — not a truncation-size artifact.
   It's invisible when a `message` item also exists (final text still comes through) and total when truncation
   stops the response before a message item is emitted, which is exactly what both tests showed.

The chat/completions adapter (`adapters/transformation.py`) was checked and found to already handle this
correctly — an explicit fallback from `choice.message.reasoning_content` to a `thinking` block
(`adapters/transformation.py`, ~line 1225) — confirming that path was never the problem; the Responses-API bridge
specifically was.

`drop_params` / `drop_unsupported_params` / `modify_params` were checked and are not implicated at all.

## Corroboration

Web search surfaced two relevant open upstream issues:

- [BerriAI/litellm#29518](https://github.com/BerriAI/litellm/issues/29518) — `/v1/messages` adapter drops
  `reasoning_content` → `thinking` blocks for OpenAI-compatible chat-completions backends (streaming). Same family
  of bug, different code path (chat-completions/streaming vs. our Responses-API/non-streaming case).
- [BerriAI/litellm#23841](https://github.com/BerriAI/litellm/issues/23841) — multiple bugs in this same
  experimental `/v1/messages`→OpenAI pass-through, including that the `use_chat_completions_url_for_anthropic_messages`
  opt-out is ignored in some code paths. Specifically checked whether that undermines this fix: the ignored checks
  live in `responses_api_bridge_check()` in `litellm/main.py`, a different function used for a different feature
  (bridging `litellm.completion()` calls for reasoning models like gpt-5). The routing check our fix relies on —
  `_should_route_to_responses_api()` in `messages/handler.py` — was read directly and correctly short-circuits on
  the flag with no other override in that file.

## Fix

Added one line to `litellm_settings` in `litellm-config.yaml`:

```yaml
litellm_settings:
  use_chat_completions_url_for_anthropic_messages: true
```

This hits a generic `setattr(litellm, key, value)` fallback in `proxy_server.py` for unrecognized
`litellm_settings` keys, confirmed by reading that loop directly — so it correctly sets
`litellm.use_chat_completions_url_for_anthropic_messages = True` at startup. That flips
`_should_route_to_responses_api()` to `False` for `openai/*`-registered models, routing `/v1/messages` through the
chat/completions adapter, which already maps `reasoning_content` into `thinking` blocks correctly.

Blast radius: zero on this config. No `model_list` entry is a real OpenAI-API model — only `openai/`-prefixed vLLM
backends (`qwen3.6-35b-a3b`, `qwen3.8-27b`, and the embedding model, which doesn't use this route) — so nothing
else changes behavior.

## Alternatives considered, not taken

- **Pass-through bypass** — route `/v1/messages` straight to vLLM's own native endpoint via
  `pass_through_endpoints`, skipping LiteLLM's translation for this route entirely. Confirmed vLLM implements
  `/v1/messages` natively (400, not 404, on an empty POST). Works, but loses LiteLLM's key mgmt/caching/Langfuse
  tracing on this specific route for no benefit over the config-flag fix. Not worth it unless the flag fix
  regresses something later.
- **Just raise `max_tokens`/thinking budget** — masks the symptom in the truncation case but doesn't fix the
  underlying bug (the block is dropped unconditionally, not just when truncated); rejected as the actual fix.

## Testing performed

1. Restarted `litellm-proxy` after the config change; confirmed clean startup and all four models registered
   (`anthropic/*`, `qwen3.6-35b-a3b`, `qwen3.8-27b`, `nemotron-3-embed-1b-nvfp4`).
2. Polled `/health/liveliness` until `200 OK`.
3. Re-sent the small-prompt Anthropic-format request through `POST :4000/v1/messages`: `thinking` block now
   present and populated, including on a run that happened to hit `stop_reason: max_tokens` mid-thought — the
   partial reasoning trace came through instead of `content: []`.

## Not yet done

- Did not re-run the original ~1900-token/constrained-`max_tokens` reproduction case verbatim through LiteLLM post-fix
  (a smaller ad hoc request was used instead, which incidentally also truncated mid-thought and still showed the
  fix working) — worth an exact re-run of the original Test 2 for a clean before/after comparison if this needs to
  be demonstrated precisely.
- No corresponding fix/verification was done for streaming requests (`stream: true`) — issue #29518 specifically
  calls out a streaming-path variant of this bug family; this session only exercised non-streaming requests.
- Neither `docker-compose.qwen3.6.yml`'s nor `docker-compose.qwen3.8.yml`'s vLLM image digest pinning (flagged as
  outstanding in the 2026-08-24 report) was addressed in this session — unrelated to this fix, still open.
