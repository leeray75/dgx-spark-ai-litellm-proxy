# LiteLLM `/v1/messages` Thinking-Block Passthrough Fix — Summary Report

**Date:** 2026-08-28
**Branch:** `fix/anthropic-messages-thinking-passthrough` (branched off `feat/qwen3.8-27b-nvfp4-stack`)
**Base:** current working tree, following commit `d15d632`

Two related but distinct bugs in LiteLLM's Anthropic `/v1/messages` translation for `openai/`-prefixed backends
were found and fixed in this session: **Part 1** (response-side — `thinking` blocks dropped) and **Part 2**
(request-side — `input_text`/`output_text` system/message blocks dropped), the latter found via real-world
reproduction on a second machine after Part 1 was already fixed and deployed.

---

## Part 1: Response-side — `thinking` blocks dropped

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

---

## Part 2: Request-side — `input_text`/`output_text` blocks dropped

### Symptom (real-world reproduction, after Part 1 was already deployed)

On a second machine (Windows, Claude Code v2.1.241, using the `claude-provider-switch` skill to toggle between
provider profiles): asking "list your skills" through the `litellm` profile got a generic non-answer claiming no
skills were configured; the identical question through the `vllm` (direct) profile correctly listed all 10
configured skills in a formatted table. Same model (`qwen3.6-35b-a3b`), same underlying skill configuration —
this is the exact symptom the original investigation set out to explain, now reproduced against a real Claude
Code client (not a synthetic request) and confirmed to persist even after Part 1's fix was live on the proxy —
proving it's a separate bug.

### Investigation

Reproduced with a synthetic Anthropic-format request whose `system` field mixes block types — one `"text"` block,
one `"input_text"` block (the type [upstream issue #23841](https://github.com/BerriAI/litellm/issues/23841)
names as what Claude Code CLI sends for parts of its system prompt and user messages):

- **Direct vLLM (`:8301`)**: rejected the request outright with a `400` — `input_text` is not a valid Anthropic
  content-block type per vLLM's own strict validator (only `text`, `image`, `tool_use`, `tool_result`,
  `tool_reference`, `thinking`, `redacted_thinking` accepted).
- **Via LiteLLM (`:4000`)**: returned `200 OK`, but the model's own reasoning gave it away — *"I don't have a
  predefined list of 'skill names' in my system prompt."* The `input_text` block's content never reached the
  model at all.

Confirmed in source: `_add_system_message_to_messages()` in
`litellm/llms/anthropic/experimental_pass_through/adapters/transformation.py` only forwards blocks where
`block.get("type") == "text"`:

```python
for block in system_content:
    if isinstance(block, dict) and block.get("type") == "text":
        ...append...
    # no else — anything not "text" is silently discarded, no error, no log
```

The same narrow-type filtering exists in the user-message content-block loop
(`translate_anthropic_messages_to_openai()`, same file) and, per issue #23841, in three separate spots in the
Responses API adapter (`responses_adapters/transformation.py`) as well. This means **Part 1's fix doesn't help
here** — switching between the chat/completions and Responses API routing paths doesn't matter, since both share
this exact flaw.

### Why a pass-through bypass wasn't used

Considered routing `/v1/messages` straight to vLLM's native endpoint via `pass_through_endpoints` (as floated as
an alternative for Part 1). Checked `SafeRouteAdder` in
`litellm/proxy/pass_through_endpoints/pass_through_endpoints.py`: it only registers a pass-through route if the
exact path+method isn't already registered on the app — and `/v1/messages` is already claimed by litellm's own
built-in (buggy) handler, so a same-path bypass would silently no-op. A different path would require
reconfiguring Claude Code's `claude-provider-switch litellm` profile client-side, which is out of scope without
touching the Windows machine directly. Also worth noting: vLLM's strict validator rejects `input_text` outright
(400), so a bypass wouldn't necessarily be a strict improvement anyway — it trades silent data loss for a hard
failure on any non-conformant block, unless Claude Code's real request never actually contains one when talking
to that profile (unconfirmed either way, since the real raw request wasn't captured).

### Fix

New `litellm-callbacks/anthropic_input_text_fix.py` — a `CustomLogger.async_pre_call_hook` callback (litellm's
documented custom-callback extension point) that normalizes `type: "input_text"`/`"output_text"` blocks to
`type: "text"` on the raw request body, before any of litellm's translation code runs:

```yaml
litellm_settings:
  callbacks: ["langfuse_otel", "anthropic_input_text_fix.proxy_handler_instance"]
```

Chosen over patching litellm's own vendor files directly (which was the other option — e.g. loosening the
`== "text"` check in `_add_system_message_to_messages`): `async_pre_call_hook` is a documented, stable API
(https://docs.litellm.ai/docs/observability/custom_callback), whereas the vendor source lives inside a mutable
`:main-latest` image and any direct edit would need re-applying (and re-verifying line-for-line) on every image
pull. The hook operates on `data["system"]` and every message's `data["messages"][i]["content"]` at the raw-JSON
level — before litellm splits `system` off into a separate function parameter — which is also why this couldn't
be done via the *other* documented hook already used for the responses-API-vs-thinking distinction
(`async_pre_request_hook`): that hook's call site in
`litellm/llms/anthropic/experimental_pass_through/messages/handler.py` only exposes `messages`, not `system`, to
registered callbacks (confirmed by reading the exact `**kwargs` spread — `system` is an explicit named parameter
of `anthropic_messages()`, so it's never part of the kwargs dict handed to that hook).

Mounted into all four compose files' independently-defined `litellm-proxy` service (`docker-compose.qwen3.6.yml`,
`docker-compose.qwen3.8.yml`, `docker-compose.yml`, `docker-compose.nemotron.yml`) at
`/app/anthropic_input_text_fix.py` — litellm resolves `callbacks:` module paths relative to the mounted config
file's own directory (`/app`, since the config is mounted at `/app/config.yaml`), confirmed by reading
`get_instance_fn()` in `litellm/proxy/types_utils/utils.py`.

### Testing performed

1. Recreated `litellm-proxy` via `docker compose -f docker-compose.qwen3.6.yml up -d --no-deps litellm` — a plain
   `docker restart` does not pick up new volume mounts, only `up -d`/recreate does.
2. Polled `/health/liveliness` until `200 OK`; checked full startup logs for import/callback-load errors — none
   found.
3. Re-sent the exact `input_text`-containing reproduction request through `POST :4000/v1/messages`:
   `usage.input_tokens` went from `45` (block dropped) to `63` (block forwarded, matching the added content's
   token count), and the model's reasoning now correctly reproduces both skill names (`zeta-skill`,
   `omega-skill`) from the previously-invisible block.

### Not yet done

- Not verified against the real Windows Claude Code client — only reproduced with a synthetic request matching
  the block type issue #23841 documents. The exact block type(s) and structure Claude Code v2.1.241 actually
  sends for its system-reminder/skill-listing content were never captured directly; if it turns out to differ
  from `input_text`/`output_text`, this fix would need extending.
- No equivalent fix/verification was done for the same drop pattern potentially present in assistant-message
  `tool_use`/`thinking` block translation, or for streaming requests — only non-streaming `system` + user-message
  content blocks were exercised.
- The callback is global (`litellm_settings.callbacks` applies proxy-wide), not scoped to `anthropic_messages`
  call type specifically — deliberate, since `input_text`/`output_text` block types don't collide with any
  existing OpenAI chat-completions content-block type, making the no-op case for other call types safe, but
  this wasn't stress-tested against every other route this proxy serves (embeddings, plain chat completions,
  the `anthropic/*` passthrough).
