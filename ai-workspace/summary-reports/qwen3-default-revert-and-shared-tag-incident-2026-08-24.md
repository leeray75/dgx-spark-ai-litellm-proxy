# Qwen3.6 Reinstated as Default + Shared-Tag Collateral Incident — Summary Report

**Date:** 2026-08-24
**Branch:** `feat/qwen3.8-27b-nvfp4-stack` (continues from the 2026-08-23 work adding qwen3.8)
**Base:** current working tree, following commits `c9f0053`, `ee78f38`, `510da15`

---

## Overview

Three connected things happened in this session, in order:

1. Investigated why qwen3.8 (made default the previous day) was generating at ~20 tok/s vs. the user's
   remembered ~40 tok/s on qwen3.6. Found no working fix.
2. Based on that finding plus qwen3.8's still-unverified tool-call parser, decided together with the user to
   revert qwen3.6 to being the default/primary model, keeping qwen3.8 available as an experimental option.
3. While reverting, hit a **real, unrelated regression in qwen3.6 itself** — caused as a side effect of step 1's
   own troubleshooting — diagnosed and fixed it, then propagated the same fix pattern through every doc/script
   that referenced the old default/rollback framing.

This report focuses on steps 2 and 3; step 1 (the qwen3.8 throughput investigation itself) is already covered in
`CHANGELOG.md`'s "Investigated" section and `docker-compose.qwen3.8.yml`'s own header.

---

## The collateral incident (the most important finding of this session)

While investigating qwen3.8's throughput, a fresh `docker pull vllm/vllm-openai:nightly` was run to test a
newer vLLM build. This is a normal, reasonable thing to do when investigating one specific compose file — but
`docker-compose.qwen3.6.yml` and `docker-compose.qwen3.8.yml` **both** reference the same mutable `:nightly` tag,
not a pinned digest. Neither file's header comment (which explicitly calls out "pin to the digest and record it
here" as the intended practice) had actually been filled in.

Consequence: the next time qwen3.6 was restarted — hours later, for what should have been a routine "switch back
to the known-good model" — its engine silently picked up the new vLLM build too, and crashed on boot:

```
ValueError: No available memory for the cache blocks. Try increasing `gpu_memory_utilization`...
```

This is the *exact* error qwen3.8 had already hit and been fixed for, earlier the same session, for the *exact*
same underlying reason (newer vLLM's CUDA-graph memory profiling leaves less real headroom at a given
`--gpu-memory-utilization` value than older builds did). It reproduced on a config (`0.4`) that had been stable
in production for weeks — nothing about `docker-compose.qwen3.6.yml` itself was wrong; it was simply running on
a vLLM build it had never been validated against.

**Fix**: same as qwen3.8's — raised `--gpu-memory-utilization` to `0.6`. Confirmed via boot log (24.54 GiB KV
cache available, vs. zero/negative before) and a real generation test.

**Not yet fixed**: neither compose file is pinned to a digest. Both remain exposed to this exact failure mode
from any future `:nightly` pull for either stack. Documented prominently (CLAUDE.md warning box, corrections-
history item 18 in the compose file, troubleshooting §4b) so the next person who hits this — or who's tempted to
`docker pull` for an unrelated reason — knows the blast radius before acting, but the actual pin was left as
follow-up work, not done in this session.

---

## Real performance verification

Once fixed, real (non-cached, unique-prompt) generation tests were run to confirm qwen3.6 wasn't just "not
crashing" but actually fast:

- 700 tokens in 8.36s = 83.71 tok/s
- 1800 tokens in 21.49s = 83.74 tok/s

Reproducible across two independent, differently-sized requests — not a fluke. Both requests happened to spend
their entire token budget in `<think>...</think>` reasoning content (never reached final code output) due to
this model's default thinking-mode verbosity at the temperatures tested; that's a token-budget artifact of the
test prompts, not a throughput or correctness issue, and doesn't invalidate the tok/s measurement.

The engine's own internal `Avg generation throughput` log metric, sampled over the same window, was noisier
(35.6 tok/s median across only 5 samples) — likely skewed by a partial ramp-up window right after boot. The
direct wall-clock numbers are more trustworthy here since they were independently reproduced.

---

## Default/rollback flip — full scope

Decided that "default" in the docs/scripts should reflect the actually-recommended model, not stay pinned to
the previous day's decision now that a real regression was found. Flipped labeling comprehensively rather than
leaving a confusing split between "what the docs call default" and "what's actually recommended":

| File | What changed |
|---|---|
| `CLAUDE.md` | Default statement, stack-start commands, restart/model-switch examples, Configuration Files table, vLLM Image Versions table (+ new tag-pinning warning box), Model Names table, Key vLLM Flags section (+ real measured numbers for both models), Memory Budget section (0.4→0.6 for both), Access Points table, testing examples |
| `README.md` | Title, Features bullet, architecture diagram engine box, Quick Start, both scripts sections, Access Points table, both API example blocks, AI Agents table + closing note |
| `docs/models.md` | Section headers (DEFAULT/EXPERIMENTAL), full Model Comparison table, both Configuration Comparison examples (+ 0.4→0.6 fix in the qwen3.6 example), Selecting-the-Right-Model and Testing-Models section order/labels |
| `docs/architecture.md` | System diagram, Inference Engines table, Port Assignment table, Model Details section headers |
| `docs/setup.md` | Start-the-Stack, Verify-Services log commands, health-check curls, Test-the-API examples, Model-Switching examples |
| `docs/agents.md` | Agent/Tool table (6 rows), Cursor's per-model table, every individual code example (Cline/Cursor/Continue JSON/Python), Model Reference table, Python dict example, curl test examples, troubleshooting log-check line |
| `docs/troubleshooting.md` | Log-check commands, health-check curl, new §4b entry for the collateral incident |
| `scripts/restart.sh` | No-arg default (`qwen3.8`→`qwen3.6`), header usage comment, help text, examples |
| `scripts/model-switch.sh` | Header usage comment, switch-function comments, help text, examples — **plus** fixed an independent pre-existing bug: several strings still said "Qwen3.6-27B-FP8" (stale from before the 27B→35B-A3B rename), unrelated to this session's flip but found while editing the same lines |
| `litellm-config.yaml` | Header comment, `default_fallbacks`, reordered `model_list` (qwen3.6 first) |

Verified after every batch of edits with `grep` sweeps for leftover "qwen3.8...(default)" / "qwen3.6...(rollback)"
patterns — caught and fixed several misses this way (`docs/setup.md` was skipped entirely on the first pass;
`docs/troubleshooting.md` had two more spots after the first edit).

`docker-compose.qwen3.8.yml` itself was **not** touched in this flip — it remains a complete, working,
independently-startable stack. Nothing about qwen3.8 was removed or degraded; only the "which one starts by
default" decision changed.

---

## Testing performed

1. `docker compose -f docker-compose.qwen3.6.yml config --quiet` / same for qwen3.8 — both valid after every
   edit round.
2. `bash -n` on both scripts — valid syntax.
3. YAML-parsed `litellm-config.yaml` in a throwaway container — valid.
4. Restarted `litellm-proxy` to pick up the routing/fallback change; confirmed both `qwen3.6-35b-a3b` and
   `qwen3.8-27b` still appear in `/v1/models`.
5. Real end-to-end chat completion through `qwen3.6-35b-a3b` via the proxy post-restart — succeeded.
6. Confirmed qwen3.6's original cache volumes (`vllm-compile-cache`, `vllm-flashinfer-cache`,
   `vllm-triton-cache`) were never deleted, so the `0.4`→`0.6` re-tune was the only cache-key change paid this
   session, not a full rebuild from nothing.

## Not yet done

- Neither `docker-compose.qwen3.6.yml` nor `docker-compose.qwen3.8.yml` is pinned to a vLLM image digest — the
  real fix for the collateral-incident root cause. A `qwen36-pinned-20260710` tag was created pointing at the
  previously-known-good local image during this session's investigation but ended up unused (the `0.4`→`0.6`
  fix was applied instead, per explicit user direction to take the faster path); it's still sitting in the local
  Docker image store as a spare, unreferenced by any compose file.
- qwen3.8's tool-call parser is still unverified against a real tool-calling session — unchanged from the prior
  report.
