# Changelog 

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

- **`docker-compose.qwen3.6.yml`: added `--mm-encoder-tp-mode data`, changed `--tool-call-parser qwen3_coder` →
  `qwen3_xml`, added `--reasoning-parser qwen3` (2026-08-28).** Three engine optimizations:
  - `--mm-encoder-tp-mode data`: Switches multi-modal encoder from weight-splitting tensor parallelism to
    data-parallel mode (each GPU holds full weights, splits batch across GPUs). This improves throughput
    when the encoder is compute-bound rather than memory-bound. Source: vLLM's `MMEncoderTPMode` config type.
  - `--tool-call-parser qwen3_xml`: Changed from `qwen3_coder` to align with the official vLLM recipe at
    `recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B`. Previously verified that `qwen3_coder` worked correctly in tool-calling
    tests; this change is evidence-based (official recipe) rather than empirically verified against current traffic.
  - `--reasoning-parser qwen3`: New explicit parser for Qwen3-family models to ensure proper extraction of
    chain-of-thought reasoning traces.
  - Full details in `ai-workspace/summary-reports/qwen3.6-engine-optimizations-2026-08-28.md`.

- **`litellm-callbacks/anthropic_input_text_fix.py`: found and fixed the actual root cause of the skills-listing
  gap — `role: "system"` messages injected mid-conversation were silently dropped whole** (2026-08-28). The two
  fixes above narrowed the problem but didn't close it: real-world retesting from the Windows Claude Code client
  still showed only 1 of 10 skills after both were live. Captured the actual raw request Claude Code sends
  (temporary `async_pre_call_hook` logging on the proxy, removed after use) and found the full 10-skill listing
  present verbatim — not in the top-level `system` field, but in `messages[1]`, a discrete message with
  `"role": "system"` injected mid-conversation (Claude Code's own convention, alongside similar messages for the
  available-agent-types listing and a token-budget reminder — likely kept out of the main cached system block so
  that block stays stable across turns for prompt-caching purposes). Anthropic's real Messages API only defines
  `"user"`/`"assistant"` roles for the `messages` array; `translate_anthropic_messages_to_openai()` in
  `litellm/llms/anthropic/experimental_pass_through/adapters/transformation.py` has no branch for any other role,
  so the entire message — all 10 skill descriptions, verbatim — was silently discarded before ever reaching the
  backend model, no error, no log. This is why the earlier synthetic reproductions (block-type substitution in
  `system`) never caught it: the real bug isn't in content-block typing at all, it's an entire message shape
  litellm's translator was never written to expect.
  - **Fix**: extended the existing `async_pre_call_hook` callback to fold any `role: "system"` messages into the
    top-level `system` field (as `"text"` blocks, preserving order) before litellm's translator runs, removing
    them from `messages` so the remaining user/assistant turn alternation stays valid.
  - **Verified two ways**: (1) replayed the exact captured real request (5 messages, including both `role:
    "system"` messages) directly against the fixed proxy — the streamed response correctly listed all 10 skills,
    verbatim, unprompted; (2) independently, the user re-ran the same "list your skills" query from the real
    Windows Claude Code client under the `local` profile and got the identical, correct 10-skill table, now
    matching the `vllm` (direct) profile's output exactly.
  - This fully explains the original investigation's symptom (Claude Code enumerating a skill/tool listing
    correctly via direct vLLM but not via LiteLLM) — the `container`/skills field on `anthropic_messages_handler()`
    was checked and ruled out (it's read into a local variable and never used anywhere downstream in either
    routing path, but this is Anthropic's separate server-side code-execution Skills API, not how Claude Code CLI
    delivers its local skill manifest — confirmed by capturing the real request, which never populated it).

- **New `litellm-callbacks/anthropic_input_text_fix.py`: fixed `/v1/messages` silently dropping non-`"text"`
  content blocks (`"input_text"`/`"output_text"`) from the system prompt and message history** (2026-08-28),
  found via real-world reproduction on a second machine: a Claude Code v2.1.241 session on Windows, talking to
  this same `qwen3.6-35b-a3b` model, correctly listed all 10 configured skills when using the
  `claude-provider-switch` skill's `vllm` (direct) profile, but the identical question via the `litellm` profile
  got a generic non-answer claiming no skills existed — the exact symptom the earlier thinking-block investigation
  set out to explain, now reproduced against a real Claude Code client rather than a synthetic request. This is a
  **separate bug from the thinking-block fix below**: that one was response-side (model reasoning stripped on the
  way out); this one is request-side (part of the system prompt stripped on the way in, before vLLM ever sees it).
  - **Reproduced directly**: sent an Anthropic-format request with `system` containing one `"text"` block and one
    `"input_text"` block (the type upstream issue
    [#23841](https://github.com/BerriAI/litellm/issues/23841) names as the culprit for Claude Code CLI) to both
    endpoints. Direct vLLM (`:8301`) **rejected it outright** with a `400` (`input_text` is not a valid Anthropic
    content-block type per vLLM's own strict validator: only `text`, `image`, `tool_use`, `tool_result`,
    `tool_reference`, `thinking`, `redacted_thinking` are accepted). Via LiteLLM (`:4000`), the request returned
    `200 OK` but the model's own reasoning gave it away: *"I don't have a predefined list of 'skill names' in my
    system prompt"* — the `input_text` block's content never reached it. Root cause confirmed in source:
    `_add_system_message_to_messages()` in
    `litellm/llms/anthropic/experimental_pass_through/adapters/transformation.py` only forwards blocks where
    `block.get("type") == "text"`; anything else is silently skipped, no error, no log. The same narrow-type
    filtering exists in the user-message content-block loop (`translate_anthropic_messages_to_openai()`) and,
    per #23841, in three spots in the Responses API adapter too — so this is **not fixable by the
    `use_chat_completions_url_for_anthropic_messages` flag** used for the thinking-block fix; both translation
    paths share the flaw.
  - **Why a pass-through bypass wasn't used here**: LiteLLM's `SafeRouteAdder` (in
    `litellm/proxy/pass_through_endpoints/pass_through_endpoints.py`) only registers a `pass_through_endpoints`
    route if the exact path+method isn't already registered — and `/v1/messages` is already claimed by litellm's
    own (buggy) built-in handler, so a same-path bypass silently no-ops. A different path would need Claude
    Code's `claude-provider-switch litellm` profile reconfigured client-side, out of scope without touching the
    Windows machine.
  - **Fix**: a `CustomLogger.async_pre_call_hook` callback (`litellm-callbacks/anthropic_input_text_fix.py`,
    registered via `litellm_settings.callbacks`) that normalizes `type: "input_text"`/`"output_text"` blocks to
    `type: "text"` on the raw request body — before any of litellm's lossy translation code runs, and independent
    of which routing path (chat/completions vs. Responses API) is active. Chosen over patching litellm's own
    source files directly: `async_pre_call_hook` is a documented, stable extension point, whereas the vendor
    files live inside a mutable `:main-latest` image and would silently rot (or need re-syncing) on every image
    pull. Mounted into all four compose files' `litellm-proxy` service (each defines it independently, per
    `litellm-config.yaml`'s own header comment on the shared-config design) at `/app/anthropic_input_text_fix.py`,
    since litellm resolves `callbacks:` module paths relative to the mounted config file's directory (`/app`).
  - **Verified**: recreated `litellm-proxy` (a plain restart doesn't pick up new volume mounts), re-sent the same
    `input_text`-containing request through `:4000/v1/messages` — `usage.input_tokens` went from `45` (block
    dropped) to `63` (block forwarded, matching the added content's token count), and the model's reasoning now
    correctly reproduces both skill names from the previously-invisible block.
  - Full investigation and reproduction detail (both fixes) is in
    `ai-workspace/summary-reports/anthropic-messages-thinking-passthrough-fix-2026-08-28.md`.

- **`litellm-config.yaml`: fixed `/v1/messages` silently dropping `thinking` content blocks for the `openai/`-
  prefixed vLLM backends** (2026-08-28), found while investigating why Claude Code could enumerate a large
  skill/tool listing when pointed directly at vLLM (`:8301`) but not through LiteLLM (`:4000`). Root cause,
  confirmed by reading LiteLLM 1.82.6's actual source inside the running `litellm-proxy` container (not inferred):
  LiteLLM's `/v1/messages` handler routes any `openai/`-prefixed model through its OpenAI **Responses API**
  translation bridge by default (`_should_route_to_responses_api()` in
  `litellm/llms/anthropic/experimental_pass_through/messages/handler.py`), not through chat/completions. vLLM's
  native `/v1/responses` (confirmed working — `nightly` build does implement it) puts the actual reasoning trace
  under `output[].content[].text` (`type: "reasoning_text"`) and leaves `output[].summary: []` permanently empty,
  since populating `summary` requires OpenAI's own proprietary reasoning-summarizer step, which vLLM doesn't
  replicate. LiteLLM's `responses_adapters/transformation.py::translate_response()` only reads `item.summary` for
  `ResponseReasoningItem` — never `item.content` — so the `thinking` block was dropped on **every** request
  through this backend, deterministically, not as a truncation-size artifact. It was invisible in normal use
  (final `text` block still arrived intact) and only became destructive when a response was truncated mid-
  reasoning by `max_tokens`: direct vLLM still returned the partial reasoning trace (usually containing the
  answer); LiteLLM returned `content: []`, nothing at all.
  - **Fix**: `use_chat_completions_url_for_anthropic_messages: true` added to `litellm_settings`. Verified correct
    for our exact `custom_llm_provider == "openai"` code path in 1.82.6 — flips `_should_route_to_responses_api()`
    to `False`, routing through the chat/completions adapter instead, which already has an explicit
    `reasoning_content` → `thinking`-block fallback (`adapters/transformation.py`, ~line 1225) that the Responses
    path lacks. Zero blast radius on this config: no `model_list` entry here is a real OpenAI-API model, only
    `openai/`-prefixed vLLM backends.
  - Corroborated by upstream LiteLLM issues
    [#29518](https://github.com/BerriAI/litellm/issues/29518) (reasoning_content dropped for OpenAI-compatible
    chat-completions backends) and [#23841](https://github.com/BerriAI/litellm/issues/23841) (multiple bugs in
    this same experimental `/v1/messages`→OpenAI pass-through) — separately checked that #23841's "opt-out env
    var ignored" bugs live in a different function (`responses_api_bridge_check` in `main.py`, used elsewhere)
    and do not undermine this fix's routing check.
  - **Verified**: restarted `litellm-proxy`, re-sent the original Anthropic-format request through
    `POST :4000/v1/messages` — `thinking` block now present and populated (including on a `max_tokens`-truncated
    response, where it previously came back as `content: []`).
  - Full investigation and reproduction detail:
    `ai-workspace/summary-reports/anthropic-messages-thinking-passthrough-fix-2026-08-28.md`.

- **`docker-compose.qwen3.6.yml` aligned against the official vLLM recipe** for this exact checkpoint/hardware
  (`https://recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B?hardware=dgx_spark_gb10&variant=nvfp4`), fetched and diffed
  directly against the running config (2026-08-27). Most flags already matched (`kv-cache-dtype fp8`,
  `moe-backend marlin`, `max-model-len 262144`, `max-num-batched-tokens 8192`, `load-format fastsafetensors`,
  `reasoning-parser qwen3`, `enable-prefix-caching`, the speculative-config's `num_speculative_tokens 3` +
  `moe_backend triton`). Three real discrepancies found and applied:
  - **`--tool-call-parser qwen3_xml` → `qwen3_coder`** (corrections item 19). This flag had already flip-flopped
    three times in this file's own history (items 11/16/17) based on reasoning/analogy from an NVIDIA model-card
    claim — this change is different: a direct fetch of an independent, apparently-current primary source that
    disagrees with that claim. **Verified afterward** with a real tool-calling test (see below) — not shipped on
    faith the way earlier flip-flops were.
  - **`--gpu-memory-utilization 0.6 → 0.5`** (item 20, explicit request). Real boot measured 12.45 GiB KV cache
    available — close to a pre-boot estimate (~10-11 GiB) extrapolated from this file's own `0.4`-crashed /
    `0.6`-worked data points, and positive/working, just with less margin than `0.6` had.
  - **`--max-num-seqs 4 → 8`** (item 20). Required also densifying `--compilation-config`'s
    `cudagraph_capture_sizes` from covering 1-16 to 1-32 (the effective MTP decode-batch ceiling scales with
    `max-num-seqs * (1 + num_speculative_tokens)`) — changing `max-num-seqs` alone would have silently
    reintroduced the mid-inference Triton JIT warmup-gap issue that capture-size list was added to fix.
  - **Real tool-calling verification** (first in this project's history — every prior test was throughput
    benchmarks or plain chat completions): built a 5-tool coding-agent palette (`search_code`, `read_file`,
    `write_file`, `execute_command`, `invoke_skill`) and tested single-turn and multi-turn (with synthetic
    tool-result history) tool selection against the live API. All 5 tools correctly selected with well-formed
    JSON arguments, including correctly inferring an argument from a prior turn's tool result and correctly
    invoking a skill-style tool with real diff content. One caveat: low `max_tokens` (400) on a write-heavy call
    returned empty `{}` arguments instead of erroring (fixed by raising to 900, reproducible at temp 0.6 and 0.0)
    — not expected to matter in real Cline/Claude Code use, which sets much larger budgets.

- **`docker-compose.qwen3.8.yml`: checkpoint swapped `unsloth/Qwen3.8-27B-NVFP4` → `Inferact/Qwen3.8-27B-NVFP4`
  (2026-08-26), user-suggested via a pasted analysis citing recipes.vllm.ai. Verified directly (raw `config.json`
  fetch): this checkpoint uses NVIDIA ModelOpt quantization (`quant_method: "modelopt"`, `quant_algo: "NVFP4"`,
  W4A4, group size 16) — the same scheme qwen3.6 uses successfully via Marlin — and does NOT quantize `lm_head`
  (unlike the retired Unsloth checkpoint, whose quantized `lm_head` caused the Marlin-FP8 crash documented in the
  prior throughput investigation). Genuinely evidence-based reason to try it, not just a vendor swap.
  - **Real result (tested on this hardware): did not fix the throughput problem.** Clean boot (weights 24.97 GiB,
    24.74 GiB KV cache at `--gpu-memory-utilization 0.6`, no crash), but vLLM auto-selected the same NATIVE
    `FlashInferCutlassNvFp4LinearKernel` as the retired Unsloth checkpoint — NOT Marlin, despite
    `VLLM_NVFP4_GEMM_BACKEND=marlin` being set and despite qwen3.6 using Marlin for this identical quant_method on
    the same hardware/vLLM build (reason for the discrepancy unconfirmed). Real generation throughput: 700 tokens
    in 39.95s = **17.52 tok/s**, with the same 96% GPU utilization / ~34W power draw signature as the retired
    checkpoint's ~20 tok/s. The recipe's own benchmark claims (0.897 MTP acceptance, etc.) were measured on 2x
    RTX 5090 and did not translate here. A same-prompt, same-length (700 tokens) direct comparison against
    qwen3.6 immediately after switching back made the diagnosis cleaner than any earlier test: qwen3.6 hit
    83.25 tok/s at 96% GPU utilization / ~34.5W — essentially identical utilization and power draw to qwen3.8's
    17.52 tok/s, but 4.75x the throughput. Confirms the GPU isn't simply "busier" on qwen3.6; its kernel path
    does far more useful work per unit of that same occupancy/power.
  - The pasted analysis that prompted this swap had real red flags (malformed citation markup consistent with an
    unverified secondary AI summary, numbers that didn't match this session's own direct fetches of the same
    pages) — worth noting as a pattern: this project's own research already treats unsourced specific benchmark
    claims about this model family with suspicion (see the original qwen3.8 addition's PROVENANCE header), and
    this incident is another data point for that caution, not an exception to it.
  - **Follow-up test: forced the same Marlin kernel qwen3.6 uses, to test whether kernel choice was the
    bottleneck.** Added `--linear-backend marlin` to `docker-compose.qwen3.8.yml`. This time kernel selection
    *did* change (log-confirmed `MarlinNvFp4LinearKernel`, unlike the no-op env var above) and the boot was
    clean — no crash, even more KV cache headroom (29.32 GiB vs. 24.74 GiB), consistent with this checkpoint's
    unquantized `lm_head` avoiding the crash the same flag caused on the retired Unsloth checkpoint. **Result:
    18.55 tok/s — only ~6% higher than the native-kernel run, within noise, still nowhere near qwen3.6's
    83.25 tok/s on the identical prompt.** This rules out kernel choice as the primary bottleneck empirically,
    not just theoretically: forcing the exact kernel that makes qwen3.6 fast barely moved the number.
  - **Revised root-cause theory**: the earlier "immature SM121 kernel support, may improve with a newer vLLM
    build" framing from the original Unsloth investigation is likely wrong, or at best a minor factor. The
    dominant difference is now believed to be architectural — qwen3.6 is MoE (~3B of 35B params active per
    token); both Qwen3.8 checkpoints are dense (all 27B active every token), meaning roughly 9x more weight
    streamed through memory per generated token regardless of kernel efficiency. Unlike a kernel-maturity gap,
    this is not fixable by a future vLLM/CUTLASS release or driver update — it would require a sparse/MoE
    variant of this model class from its base-model authors (the Qwen team, not NVIDIA — NVIDIA/Unsloth/Inferact
    only quantize whichever architecture already exists).
  - **qwen3.6 remains the only proven-fast option (~83.7 tok/s) and the default.** Neither qwen3.8 checkpoint is
    recommended for Cline/Claude Code use today. Full detail (including the archived Unsloth investigation) is in
    `docker-compose.qwen3.8.yml`'s header.

- **Qwen3.6 is the default/primary model again, Qwen3.8 is now experimental** (2026-08-24, reverting the
  2026-08-23 attempt to make qwen3.8 the default). Driven by two findings: qwen3.8's throughput investigation
  (below) found no working fix for its ~20 tok/s vs. qwen3.6's ~40-84 tok/s, and qwen3.8's `--tool-call-parser
  qwen3_xml` remains unverified against a real Cline/Claude Code tool-calling session. Flipped default/rollback
  labeling across `README.md`, `CLAUDE.md`, all of `docs/*.md`, `scripts/restart.sh` and `model-switch.sh`
  (no-arg default now starts qwen3.6), and `litellm-config.yaml` (`default_fallbacks` back to
  `qwen3.6-35b-a3b`, model_list reordered). `docker-compose.qwen3.8.yml` is unchanged and still fully
  buildable — nothing about qwen3.8 was removed, only which one starts by default.
  - Also fixed, while touching `scripts/model-switch.sh`: a second stale-label bug (independent of the earlier
    stale-container-name bug fixed 2026-08-23) — several strings still said "Qwen3.6-27B-FP8" instead of
    "Qwen3.6-35B-A3B-NVFP4", left over from before that model was renamed.

- **`docker-compose.qwen3.6.yml`: `--gpu-memory-utilization` 0.4 → 0.6 (real incident, 2026-08-24).**
  Root cause was *not* this file — it was collateral damage from the qwen3.8 throughput investigation below,
  which ran `docker pull vllm/vllm-openai:nightly` to test a newer build. Since both `docker-compose.qwen3.6.yml`
  and `docker-compose.qwen3.8.yml` reference the **mutable** `:nightly` tag rather than a pinned digest, that
  pull silently upgraded qwen3.6's engine too on its next restart — to vLLM `0.26.1rc1.dev1102+ge9d1398d9`, a
  build this file's `0.4` value was never validated against. Reproduced the exact same
  `ValueError: No available memory for the cache blocks` crash qwen3.8 hit, for the identical reason (CUDA-graph
  memory profiling leaving zero real KV cache headroom at the old value on the new build). Fixed the same way,
  for parity: `0.6`, confirmed working with 24.54 GiB KV cache available at boot. Documented as corrections-
  history item 18 in the compose file itself, and as a new troubleshooting entry (§4b) with the exact error
  text. **Neither compose file is pinned to a digest yet** — that's the real fix still outstanding; both remain
  vulnerable to this exact class of regression from any future `:nightly` pull for either stack.
  - Real measured throughput post-fix: two independent wall-clock tests (700 tokens/8.4s and 1800 tokens/21.5s)
    both landed at ~83.7-83.74 tok/s — reproducible, not noise, and higher than the ~40 tok/s originally
    reported. The engine's own internal log-based average was noisier (35.6 tok/s median over 5 samples,
    likely including a partial post-boot ramp-up window).

### Investigated (not fixed — no working fix currently exists)

- **Qwen3.8 generation throughput ~20 tok/s vs. qwen3.6's ~40 tok/s.** Measured: median 19.5-20.1 tok/s over
  real (non-cached) generations, with 96% GPU utilization but only ~34W power draw — the GPU stays busy without
  doing much real compute per unit time, not a saturated/well-fed GPU. Root cause: vLLM auto-selects
  `FlashInferCutlassNvFp4LinearKernel` (NVFP4) and `CutlassFP8ScaledMMLinearKernel` + a vendored/fallback
  DeepGEMM (FP8) for this checkpoint's compressed-tensors quantization — likely immature/untuned for GB10's
  SM121 (consumer/workstation Blackwell), the same category of issue qwen3.6's file already documented for its
  own (different) ModelOpt NVFP4 scheme.
  - Tried `VLLM_NVFP4_GEMM_BACKEND=marlin` alone (qwen3.6's fix for the analogous issue): **no effect**. Confirmed
    via kernel-selection log (identical before/after) and a real re-measurement (still 20.1 tok/s). This env var
    is ModelOpt-scheme-specific, not read by the compressed-tensors scheme qwen3.8 uses.
  - Tried `--linear-backend marlin` + the undocumented `VLLM_TEST_FORCE_FP8_MARLIN=1` (forces both NVFP4 and FP8
    layers through Marlin — confirmed via log that kernel selection *did* change this time): **crashed on every
    boot** with `AttributeError: 'ParallelLMHead' object has no attribute 'output_size_per_partition'` in vLLM's
    `prepare_fp8_layer_for_marlin()`. Root cause: this checkpoint's `lm_head` is itself FP8-quantized (per the HF
    model card), and vLLM's Marlin FP8 weight-prep path doesn't handle the `ParallelLMHead` layer type — a real
    vLLM bug for this specific model, not a config problem. Reverted immediately (container was crash-looping);
    confirmed back to the working ~20 tok/s baseline via kernel-selection log and a health check.
  - **Conclusion**: no working lever currently exists in this vLLM build to change kernel selection for this
    checkpoint. This is a software/kernel-library maturity gap (vLLM/CUTLASS SM121 support for compressed-tensors
    NVFP4+FP8), **not a hardware limitation** — does not require a new NVIDIA driver/firmware release. Re-test
    after pulling a newer `vllm/vllm-openai:nightly`; full findings are in `docker-compose.qwen3.8.yml`'s env
    block comments.

### Added

- **New default model: `unsloth/Qwen3.8-27B-NVFP4`** (`docker-compose.qwen3.8.yml`). Dense (not MoE) hybrid
  Gated-DeltaNet + Gated-Attention model with a vision encoder, compressed-tensors NVFP4/FP8 quantization — a
  different quantization scheme from qwen3.6's NVIDIA ModelOpt checkpoint. Mirrors qwen3.6's full stack structure
  (Langfuse observability, embedding engine, same ports) so it's a drop-in replacement as the primary model for
  Cline/Claude Code. `docker-compose.qwen3.6.yml` is kept, unmodified, as a rollback path — `./scripts/restart.sh
  qwen3.6` or `./scripts/model-switch.sh qwen3.6` switches back with no file edits needed. `litellm-config.yaml`
  keeps both `qwen3.8-27b` (new default) and `qwen3.6-35b-a3b` (rollback) routes; `default_fallbacks` now points at
  `qwen3.8-27b`. Added a matching `qwen3.8-27b` pricing entry in the Langfuse "dgx-spark" project (same per-token
  rates as qwen3.6: `$0.000000015`/`$0.000000035`) via the Langfuse Models API — this is runtime state, not tracked
  in this repo.
  - `docker-compose.qwen3.8.yml` carries an unusually detailed header (PROVENANCE + CORRECTIONS HISTORY) documenting
    exactly which flags are verified against primary sources (HF `config.json`, Unsloth's own docs, live vLLM
    registry introspection) vs. carried over from qwen3.6 by architectural analogy vs. genuinely unverified — read
    it before changing that file. `--tool-call-parser qwen3_xml` in particular is carried-by-analogy, not confirmed
    for this model.
  - Pulled a fresh `vllm/vllm-openai:nightly` (digest `sha256:95bed119…`, vLLM `0.26.1rc1.dev1102+ge9d1398d9`) and
    confirmed via live registry introspection that it registers `Qwen3_5ForConditionalGeneration` — the exact
    architecture class in the checkpoint's `config.json` — before writing any flags.
  - **Real first-boot finding**: `--gpu-memory-utilization 0.4`, carried over from qwen3.6 as an unverified
    assumption, crashed with `ValueError: No available memory for the cache blocks`. vLLM's own log explained why:
    CUDA-graph memory profiling made the effective utilization lower than the nominal value, and this model's
    memory-profiling pass (which includes the vision encoder/multimodal path qwen3.6's text-only checkpoint never
    had to account for) left zero room for KV cache. Corrected to `0.6` — verified working (13.96 GiB KV cache
    available on the fixed boot) but not yet a measured optimum.
  - **Real first-boot confirmation**: compressed-tensors NVFP4 auto-selected native `FlashInferCutlassNvFp4LinearKernel`
    and `CutlassFP8ScaledMMLinearKernel` kernels with no Marlin fallback needed — different from qwen3.6's
    ModelOpt-scheme experience, where SM121 forced a Marlin fallback. The MTP drafter resolved cleanly as
    `Qwen3_5MTP` with no MoE-backend workaround needed, confirming the file's dense-model assumption.
  - Verified end-to-end with a real request through LiteLLM → vLLM → back, confirming `reasoning_content` is
    correctly separated from `content` by `--reasoning-parser qwen3`.

### Fixed

- **`scripts/model-switch.sh` `show_status` checked a stale container name**: looked for `qwen3-6-27b-engine`, but
  the actual qwen3.6 container (since the 35B-A3B rename) is `qwen3-6-35b-nvfp4-engine` — meaning `./scripts/
  model-switch.sh status` always reported Qwen3.6 as stopped even when it was running. Fixed while adding the
  qwen3.8 status check alongside it.

### Known issue (not fixed, deferred)

- **`LITELLM_MASTER_KEY` in `.env` is still the sample placeholder** (`sk-change-me-in-production`). Discovered
  while verifying the qwen3.8 stack end-to-end. Since LiteLLM binds `0.0.0.0:4000` (not just localhost) and
  `LANGFUSE_HOST` is a Tailscale hostname — implying port 4000 is meant to be tailnet-reachable — anyone on the
  tailnet can currently authenticate with this well-known default, including the `anthropic/*` passthrough route
  (billed to the real Anthropic key). Left for the user to rotate (`openssl rand -hex 32`) since `.env` is a
  secrets file this project deliberately avoids editing automatically.

- **Qwen3.6 Triton JIT cache was never actually persisted**: `docs/architecture.md` and the v1.3.0 CHANGELOG entry
  both claimed a `vllm-triton-cache` volume existed alongside `vllm-compile-cache`/`vllm-flashinfer-cache`, but it
  was never declared or mounted on `qwen3-6-35b-nvfp4-engine` — only documented. This meant Triton's own on-disk JIT
  cache (`@triton.jit`/`@triton.autotune`-compiled kernels — `fused_moe_kernel`, `batch_memcpy_kernel`, the
  `causal_conv1d`/mamba/`eagle_*` kernels) lived at the default in-container path `/root/.triton/cache`, which is
  wiped every time the container is recreated. `scripts/restart.sh` recreates the container on every run (it only
  `down`s/`up`s — it does not `docker volume rm` anything), so the "cache-clearing ritual" was re-paying the full
  Triton JIT compilation tax every restart even though the two *other* vLLM caches were already correctly
  persisted. This is the most likely explanation for `WARNING [jit_monitor.py:135] Triton kernel JIT compilation
  during inference: fused_moe_kernel` (and friends) recurring — added `vllm-triton-cache:/root/.triton/cache`
  (volume + explicit `TRITON_CACHE_DIR` env var) to close the gap, matching the pattern already used for the other
  two caches.

### Added

- **Widened Qwen3.6 CUDA-graph capture-size list**: added `--compilation-config '{"cudagraph_capture_sizes": [...]}'`
  with a dense list covering 1-16 (then the same wider spacing up to the existing 256 ceiling). Rationale: single
  concurrent-sequence chat traffic ranges 1-4 (`--max-num-seqs 4`), and MTP speculative verification steps have a
  per-sequence query length of `1 + num_speculative_tokens`, so the effective decode-batch dimension actually seen
  in production ranges up to `4 × 4 = 16` — a range vLLM's default inferred capture-size list apparently doesn't
  densely cover, based on the `jit_monitor.py` warnings showing these kernels compiling mid-inference rather than
  only once during startup warmup. `--max-cudagraph-capture-size 256` is left unchanged as a safety ceiling. If this
  causes startup issues, the fix is to delete the `--compilation-config` line — everything else is unaffected.
- **`QWEN36_NUM_SPECULATIVE_TOKENS` env var** (`.env`/`.env.sample`, default `3` — **no behavior change** by
  default): an explicit A/B toggle for the MTP speculative decoding lookahead depth, referenced from
  `docker-compose.qwen3.6.yml`'s `--speculative-config` as `${QWEN36_NUM_SPECULATIVE_TOKENS:-3}`. Motivation: across
  observed samples, per-position draft acceptance rate consistently drops off by the 3rd speculative position (e.g.
  0.895 → 0.745 → 0.600 in good windows, 0.731 → 0.423 → 0.239 in weaker ones), and average draft acceptance sits in
  the mid-50s%. Reducing lookahead from 3 → 2 tokens trades away the (already low-probability) 3rd-position hits in
  exchange for not spending decode compute drafting/verifying a token that's frequently rejected — worth testing,
  but not applied as a silent default change since it lowers the ceiling in the good windows too.
  - **Note**: v1.4.0 briefly ran with `num_speculative_tokens=2` before v1.4.1 reverted it — but that change was
    bundled with a full checkpoint/quantization-backend revert (unsloth/compressed-tensors → nvidia/ModelOpt), so it
    isn't a clean prior A/B result for this specific parameter.
  - **To benchmark**: run baseline traffic, capture
    `docker compose -f docker-compose.qwen3.6.yml logs qwen3-6-35b-nvfp4-engine | grep -E "Avg generation throughput|SpecDecoding metrics"`,
    then set `QWEN36_NUM_SPECULATIVE_TOKENS=2` in `.env`, recreate just that service
    (`docker compose -f docker-compose.qwen3.6.yml up -d --force-recreate qwen3-6-35b-nvfp4-engine`), and repeat
    against comparable traffic.

## [1.5.1] - 2026-07-19

### Fixed

- **Embedding 400 error**: LiteLLM was forwarding `encoding_format: null` on every `/v1/embeddings` call that didn't explicitly set it (the default for any OpenAI-compatible client that doesn't pass it). vLLM's embeddings endpoint has a strict validator that rejects `null` (`"float"`/`"base64"`/`"bytes"`/`"bytes_only"` only), causing every such request to fail with `litellm.BadRequestError: ... encoding_format ... Input should be 'float', 'base64', 'bytes' or 'bytes_only'`. Pinned `encoding_format: "float"` as a static param on the `nemotron-3-embed-1b-nvfp4` entry in `litellm-config.yaml` so a valid value is always forwarded. Verified against the live proxy with both a short string and a full document (`CLAUDE.md`, 3,263 tokens).
- **Stale Nemotron-3-Super-120B context length**: the real `--max-model-len` in `docker-compose.nemotron.yml` is `262144`, but that file's own header comment said "128K context", `CLAUDE.md` said "32K context", and `docs/models.md`/`docs/architecture.md` said "128K tokens" in four places — all now corrected to 262K.
- **Stale embedding model name** in `litellm-config.yaml`'s file-header comment — still referenced the replaced `llama-nemotron-embed-vl-1b-v2` model, missed in the v1.5.0 swap.

### Known issue (not fixed, deferred)

- `litellm-config.yaml` is missing `model_list` entries for `qwen3-coder-next` and `nemotron-super` — accidentally dropped as a side effect of the v1.4.1-era commit `875c226` ("Fix litellm config: use openai/ prefix and update token limits"), which did not mention removing them. `CLAUDE.md`/`README.md`/`docs/models.md` still document both as LiteLLM proxy aliases, but only `qwen3.6-35b-a3b` and the embedding model are currently routable through port 4000; the other two engines are only reachable directly on their vLLM ports (8300/8200). Restoring the two entries was deliberately left for a separate change.

## [1.5.0] - 2026-07-18

### Changed

- **Embedding model swap**: Replaced `nvidia/llama-nemotron-embed-vl-1b-v2` (multimodal, ~1.7B params) with `nvidia/Nemotron-3-Embed-1B-NVFP4` (text-only, 1.14B params, NVFP4 quantized) in `docker-compose.qwen3.6.yml`.
  - Service/container renamed `nemotron-embed-vl-engine` → `nemotron-embed-engine`
  - `--served-model-name` / LiteLLM alias: `llama-nemotron-embed-vl-1b-v2` → `nemotron-3-embed-1b-nvfp4`
  - `--max-model-len` 10240 → 4096 (matches NVIDIA's official deployment example); added `--max-num-batched-tokens 4096` and `--max-cudagraph-capture-size 4096`
  - Removed `--trust-remote-code` (not required by this checkpoint)
  - **Breaking**: drops image/multimodal embedding support — the new model is text-only
  - **Breaking**: callers must now manually prefix input with `"query:"` or `"passage:"` (asymmetric embedding); the old model needed no prefix
  - Requires vLLM 0.25.0+ (0.23.x/0.24.x are explicitly broken per the model card); the `:nightly` image already in use satisfies this
  - Updated `litellm-config.yaml`, `CLAUDE.md`, `README.md`, and `docs/{setup,troubleshooting,architecture,agents,models}.md` to match

## [1.4.1] - 2026-07-17

### Changed

- **Qwen3.6 checkpoint reverted**: rolled back the v1.4.0 unsloth/compressed-tensors experiment. `qwen3-6-35b-nvfp4-engine` serves `nvidia/Qwen3.6-35B-A3B-NVFP4` (ModelOpt, Marlin backend) again.
  - `--quantization compressed-tensors` → `modelopt`
  - `--moe-backend flashinfer_b12x` → `marlin`
  - `--speculative-config num_speculative_tokens` 2 → 3, restored `moe_backend: triton`
  - Restored `VLLM_NVFP4_GEMM_BACKEND`, `VLLM_USE_FLASHINFER_MOE_FP4`, `VLLM_FP8_MOE_BACKEND` env vars
  - The unsloth/compressed-tensors config as it stood right before the revert (including its own crash-loop fix) is preserved in `docker-compose.qwen3.6.yml.unsloth-nvfp4-fast.bak` (untracked, `.gitignore`'d) for reference
- **Tool call parser round-trip**: briefly changed `qwen3_xml` → `qwen3_coder` and back to `qwen3_xml` — net no-op, kept at the official-NVIDIA-spec value

### Fixed

- **docs/models.md**: model ID and config example were left pointing at the reverted `unsloth/Qwen3.6-35B-A3B-NVFP4-Fast` checkpoint after v1.4.0's revert — updated back to `nvidia/Qwen3.6-35B-A3B-NVFP4` / ModelOpt / Marlin to match the actual running config

## [1.4.0] - 2026-07-15

### Changed

- **Qwen3.6 checkpoint swap**: Replaced `nvidia/Qwen3.6-35B-A3B-NVFP4` (NVIDIA ModelOpt, Marlin backend) with `unsloth/Qwen3.6-35B-A3B-NVFP4-Fast` (compressed-tensors, FlashInfer b12x backend)
  - `--quantization modelopt` → `compressed-tensors`
  - `--moe-backend marlin` → `flashinfer_b12x` (native FlashInfer FP4 for SM121)
  - `--speculative-config num_speculative_tokens` 3 → 2
  - Removed old ModelOpt+Marlin env vars (`VLLM_NVFP4_GEMM_BACKEND`, `VLLM_USE_FLASHINFER_MOE_FP4`, `VLLM_FP8_MOE_BACKEND`)
  - `--linear-backend` deliberately left UNSET (defaults to `auto`)

### Added

- **CLAUDE.md documentation**: Cross-file dependencies, startup timing and cache behavior, vLLM image versions, memory budget, engine health checks, model-switch.sh cache note
- **docs/models.md**: Updated Qwen3.6 config example with new checkpoint, quantization, and backend flags

### Fixed

- **docs/models.md**: Updated stale model ID and vLLM configuration example to reflect unsloth checkpoint swap
- **docs/architecture.md**: Corrected vLLM image versions — Nemotron (`v0.18.1-cu130`), Qwen3-Coder (`v0.19.1-cu130`), only Qwen3.6 uses `nightly`
- **docs/setup.md**: Updated startup timing to match CLAUDE.md (~10-35 min first boot, ~5-15 min cache-hit)

## [1.3.0] - 2026-07-13

### Added

- **Qwen3.6-35B-A3B-NVFP4 as new default model** — replaces Qwen3.6-27B-FP8; 35B MoE (3B activated), NVFP4 quantized, text-only
- **Multimodal embedding model** — `nvidia/llama-nemotron-embed-vl-1b-v2` (~1.7B params, 2048-dim output) runs concurrently with chat engine on port 8302
- **Persistent cache volumes** — `vllm-compile-cache` (torch.compile + FlashInfer autotune configs), `vllm-flashinfer-cache` (FlashInfer JIT kernel workspace), `vllm-triton-cache` (Triton kernel cache)
- **Debug command variant** — commented-out `--enforce-eager` command block for diagnosing FlashInfer autotune hangs

### Changed

- **vLLM image**: `v0.19.1-cu130` → `nightly` (required for FlashInfer persistent autotune cache, PR #44071+)
- **GPU memory utilization**: 0.60 → 0.4 (matches official NVIDIA spec; reduces swap pressure on 128GB unified memory)
- **Max num sequences**: 20 → 4 (memory headroom for observability stack)
- **Max batched tokens**: 32768 → 8192 (matches official NVIDIA spec; may need reverting based on observed Cline latency)
- **Tool call parser**: `qwen3_coder` → `qwen3_xml` (matches official NVIDIA spec)
- **Load format**: added `--load-format fastsafetensors` (reduces weight-loading time)
- **Speculative config**: `qwen3_next_mtp/2` → `mtp/3` with `moe_backend: triton` (matches official DGX-Spark command)
- **LiteLLM dependency**: `qwen3-6-27b-engine` → `qwen3-6-35b-nvfp4-engine` with `service_healthy` condition
- **LiteLLM memory limit**: added 1G hard limit
- **Langfuse memory limits**: raised to 1.5G with `NODE_OPTIONS=--max-old-space-size=1024` (prevents V8 heap OOM under real traffic)
- **Restart script**: container name updated to `qwen3-6-35b-nvfp4-engine`

### Removed

- **Claude Code proxy aliases** — `claude-sonnet-4-6` and `claude-haiku-4-6` removed (no longer mapped in LiteLLM config)
- **Vision support** — Qwen3.6-35B-A3B-NVFP4 is text-only; `supports_vision: false`
- **`--language-model-only` flag** — not applicable to this model architecture
- **`--max-cudagraph-capture-size 128`** — reverted to 256 (matching earlier deliberate decision)

### Fixed

- **FlashInfer autotune persistent cache** — nightly image > 2026-05-31 enables cache persistence; first boot re-tunes once (~10-60 min), subsequent boots load cache (fast restart)
- **LiteLLM startup timing** — changed vLLM dependency from `service_started` to `service_healthy` (3600s start_period); prevents LiteLLM forwarding requests before vLLM is ready
- **FlashInfer version check** — added `FLASHINFER_DISABLE_VERSION_CHECK=1` and `CUTE_DSL_ARCH=sm_121a` for GB10 Blackwell SM121a architecture

## [1.2.1] - 2026-05-04

### Changed

- **Qwen3.6 GPU memory utilization** reduced from 0.85 to 0.60 — provides headroom for large context windows and speculative decoding, reducing OOM risk under peak load
- **Qwen3.6 max sequences** reduced from 32 to 20 — matches lower memory budget, improves per-request latency consistency

### Removed

- **`--language-model-only` flag** from Qwen3.6 vLLM args — no longer needed/compatible with current vLLM version

## [1.2.0] - 2026-05-03

### Added

- Qwen3.6-27B-FP8 support (new default model)
- Vision support in LiteLLM for Qwen3.6 (image analysis)
- `qwen3_reasoning_parser.py` script for proper reasoning token handling
- `qwen3.6` model option in `model-switch.sh` and `restart.sh` scripts

### Changed

- **Default model**: Qwen3.6-27B-FP8 now serves as the default model
- **Claude Code aliases**: Updated to `claude-sonnet-4-6` and `claude-haiku-4-6`
- **LiteLLM config**: Added `qwen3.6-27b` model entry with vision support

### Improvements

- Full 262K context window support for Qwen3.6-27B-FP8
- Better token efficiency with native reasoning parser
- Optimized GPU memory utilization (~111GB for Qwen3.6 vs ~118GB for Coder-Next)

### Configuration

- New compose file: `docker-compose.qwen3.6.yml` - standalone stack with Qwen3.6 as default
- LiteLLM config updated with vision-enabled model entries
- `--reasoning-parser qwen3` added to prevent thinking token leakage in output
- `--default-chat-template-kwargs '{"preserve_thinking":true}'` for proper reasoning

### Architecture

- **Langfuse Services**: Web UI, Worker, PostgreSQL, ClickHouse, Redis, MinIO
- **Inference Engines**: 
  - vLLM for Qwen3.6-27B-FP8 (port 8301) - DEFAULT
  - vLLM for Qwen3-Coder-Next-FP8 (port 8300)
  - vLLM for Nemotron-3-Super-120B (port 8200)
- **Proxy Layer**: LiteLLM with OTEL tracing to Langfuse

### Breaking Changes

- None - all changes are additive and backwards compatible

## [1.1.1] - 2026-05-02

### Fixed

- AI agent documentation now uses correct native model names (`qwen3-coder-next`, `nemotron-super`) instead of Claude model names
- Updated `README.md` and `docs/agents.md` to reflect correct model mappings for all AI agents

### Changed

- Documentation consistency: All AI agent configurations now reference native backend models

### Performance

- Qwen3 engine memory utilization increased from 0.88 to 0.92
- Max sequences increased from 16 to 32
- Max batched tokens increased from 16384 to 32768
- Added scheduler-delay-factor (0.3) for improved decode throughput
- Added Redis exact-match prompt caching for 100% identical requests
- Added 16GB shared memory and ulimits for vLLM container stability
- PostgreSQL tuned with shared_buffers=512MB, work_mem=16MB, WAL compression
- ClickHouse memory capped to 30% of RAM
- LiteLLM log level reduced to warning

### Configuration

- Updated LiteLLM model token limits to match vLLM `--max-model-len` (262K input, 16K output)
- Added LiteLLM stream_timeout (300s) for better stalled stream detection
- Redis cache configuration moved to litellm-config.yaml for explicit configuration
- Disabled Redis RDB snapshots and AOF for pure queue/cache workload

## [1.1.0] - 2026-05-02

### Added

- Claude Code support with `claude-sonnet-4-5` and `claude-haiku-4-5` model names
- LiteLLM configuration updates for better model routing and compatibility

## [1.0.0] - 2025-05-01

### Added

- Initial release of AI LLM Proxy project
- Support for Qwen3-Coder-Next-FP8 (80B, FP8 quantization)
- Support for Nemotron-3-Super-120B-A12B-NVFP4 (NVFP4 quantization)
- Langfuse v3 observability with ClickHouse backend
- LiteLLM OpenAI-compatible proxy
- Dual-model switching via `model-switch.sh` script
- Docker Compose configuration for both models
- Comprehensive documentation in `docs/` folder
- Example environment file (`.env.sample`)
- PostgreSQL initialization script for LiteLLM database
- MinIO S3-compatible blob storage for Langfuse
- Redis event queue for Langfuse async processing

### Architecture

- **Langfuse Services**: Web UI, Worker, PostgreSQL, ClickHouse, Redis, MinIO
- **Inference Engines**: vLLM for Qwen3-Coder-Next-FP8 and Nemotron-3-Super-120B
- **Proxy Layer**: LiteLLM with OTEL tracing to Langfuse

### Known Issues

- Initial model loading may take ~10 minutes on first start
- Requires NVIDIA GPU with at least 80GB VRAM for Nemotron-3-Super
- DGX Spark (GB10) with 128GB unified memory recommended

## [Unreleased] - Planned

### Planned Features

- [ ] Kubernetes deployment configuration
- [ ] Helm charts for Langfuse integration
- [ ] Prometheus/Grafana monitoring stack
- [ ] Auto-scaling configuration
- [ ] Multi-node deployment support
- [ ] Model versioning and rollback support
- [ ] API rate limiting per user/key
- [ ] Cost allocation by project/team

### Documentation

- [ ] API reference documentation
- [ ] Model comparison guide
- [ ] Performance benchmarks
- [ ] Security best practices
- [ ] Backup and disaster recovery guide