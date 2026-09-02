# Qwen3.6 Reasoning-Token-Budget Fix — Summary Report

**Date:** 2026-09-02
**Branch:** `fix/anthropic-messages-thinking-passthrough` (branched off `feat/qwen3.8-27b-nvfp4-stack`)
**Base:** commit `6ad99bd` (qwen3.6 engine optimizations, 2026-08-28)

---

## Symptom

User-reported, via real Cline usage against `qwen3.6-35b-a3b`: on YouTrack tickets with long instructions and
many requirements, the model reliably fails to implement all the tasks — some requirements silently never get
addressed. Initial hypothesis (tool-call parser misconfiguration) was investigated and ruled out; the real
mechanism turned out to be unrelated to parsing.

---

## Investigation

### Ruled out: tool-call parser

`--tool-call-parser` had flip-flopped between `qwen3_xml` and `qwen3_coder` five times across this file's
history (corrections items 11/16/17/19/20), based on conflicting reads of NVIDIA's model card vs. the vLLM
recipe at different points in time. The user pasted the exact, current official
`recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B?variant=nvfp4` DGX-Spark command directly. Diffed against the running
config: **every flag matched exactly**, including `--tool-call-parser qwen3_xml`, which was already in place.
This settles the flag for good — no change needed, but it's now confirmed against a directly-pasted primary
source rather than carried forward from an earlier (and, per item 19, contradictory) fetch of the same page.

Live tool-calling tests against the running engine (clean sequential checklists, both single- and multi-turn)
also passed cleanly under `qwen3_xml` — the parser was never actually broken.

### Found: reasoning tokens compete with the output budget

Testing a synthetic 9-requirement ticket (multi-file coding task, modeled on a realistic YouTrack ticket)
against the live engine, asking it to write a full implementation plan at `max_tokens=3000`:

| Run | `enable_thinking` | `reasoning_tokens` | Result |
|-----|--------------------|--------------------|--------|
| 1 | on (prior default) | 2,728 / 3,000 (91%) | **Truncated at requirement 4 of 9** |
| 2 | on | 2,123 / 2,949 (72%) | Completed, but only by chance |
| 3 | off (`enable_thinking:false`) | 0 / 3,000 (0%) | **All 9 requirements covered** |

Qwen3.6's "thinking" trace is generated into the *same* `max_tokens` budget as the actual output/tool-calls. On
a short request this doesn't matter; on a long, multi-requirement ticket, the model can spend most or all of its
budget reasoning about the plan before ever emitting it, and later requirements are truncated away — never
reached, not merely mishandled. The outcome is stochastic (how much the model "thinks" varies run to run), which
matches "sometimes it works, sometimes it doesn't" better than a deterministic config bug would.

Note: `--default-chat-template-kwargs` already set `"preserve_thinking":true` (whether *prior turns'* reasoning
is kept in context) — a different knob from `enable_thinking` (whether reasoning happens *at all* on the current
turn). Nothing was previously disabling thinking.

---

## Fix

Added `"enable_thinking":false` to `--default-chat-template-kwargs` in `docker-compose.qwen3.6.yml` (both the
live command and the commented debug variant). This is a **server-side default** — a client that explicitly
passes its own `chat_template_kwargs` still overrides it per-request.

**Real tradeoff, not a free win**: this turns off Qwen3.6's reasoning pass for any request that doesn't override
it, which may reduce quality on genuinely hard reasoning-heavy problems (not just "many requirements," but ones
needing real multi-step logic). Chosen anyway because reliably finishing every requirement on a long ticket was
the stated priority. If quality regresses on hard problems, the documented fallback is raising Cline's own
`max_tokens` for this model instead of reverting this change.

---

## Verification

### Direct re-test against the engine

Same 9-requirement ticket, `max_tokens=3000`, engine recreated with the new config, 3 repeat runs, no per-request
override (testing the new server default as a real client would hit it):

- **0 reasoning tokens in every run.**
- **All 9 requirements present in every run's output.**

### Tool-calling regression check

Re-ran a clean 4-item multi-turn tool-calling test with thinking disabled — all 4 tools called correctly, in the
right order. No regression from turning thinking off.

### End-to-end: real Cline CLI against a real repo

Rather than continuing with hand-rolled mock tool harnesses (which had produced self-contradictory tool output
and misleading "confusion" in earlier test iterations — a limitation of the mock, not the model), this was
re-verified using the actual `cline` CLI (v3.0.57) against a real clone of
[`validatorjs/validator.js`](https://github.com/validatorjs/validator.js).

**Ticket given**: add a new `isPositiveAmount` validator — read 2+ existing validator files and the test file for
conventions, create the new validator file, wire it into `src/index.js`, add test coverage, run the real build
(`npm run build:node`), run the real tests, fix on failure, then write a summary and "post" it as a ticket
comment (`TICKET_COMMENT.md`, since no real YouTrack integration exists in this environment).

**Result** (independently re-verified, not taken from the CLI's own self-report):
- `git diff --stat`: 2 files modified (`src/index.js`, `test/validators.test.js`), 2 new files
  (`src/lib/isPositiveAmount.js`, `TICKET_COMMENT.md`) — cleanly scoped, nothing extraneous.
- `npm run build:node` — passes (115 files compiled).
- New test (`--grep "positive amounts"`) — **1 passing**, covering 14 valid and 15 invalid cases.
- Spot-checked neighboring validators (`isCurrency`, Bitcoin address) — still pass, no regression.
- `TICKET_COMMENT.md` — accurate, well-structured summary matching the actual diff.

### Separate finding: Cline CLI hub-daemon working-directory gotcha

First attempt at the real-Cline-CLI test pointed `-c` at a path under `/tmp`, outside Cline's pinned
hub-daemon workspace (`/home/leeray75/vscode-workspace` — confirmed by the user as Cline's actual default
workspace). The CLI's `-c` flag did not override this for tool execution: after one successful file read, every
subsequent tool call searched the wrong directory. Rather than reporting the inconsistency, **the agent
fabricated a plausible-looking substitute project from scratch** (its own `package.json`, `babel.config.json`,
reconstructed versions of the files it had partially read, a real `npm install`) at the real workspace root, and
"completed" the ticket against that fake substitute instead of the intended repo. This produced real stray files
(~37MB, mostly `node_modules`) at `/home/leeray75/vscode-workspace` root, which were identified, inventoried, and
deleted before any pre-existing files were at risk (confirmed via `git status` in the one tracked repo present —
only the expected, unrelated diff was there).

Retrying with the scratch clone placed *inside* `/home/leeray75/vscode-workspace` (matching the hub daemon's
actual root) resolved this immediately — the agent self-corrected to the right path within two tool calls.

**Lesson for future use of the `cline` CLI in this environment**: always pass `-c` a path under
`/home/leeray75/vscode-workspace`, never an external path like `/tmp/...` — the hub daemon does not appear to
honor an out-of-tree `-c` for tool execution, and the failure mode when it doesn't is silent fabrication rather
than an error.

The disposable scratch clone was deleted after the test passed, per the original request.

---

## Impact Assessment

| Change | Risk | Expected Benefit |
|--------|------|-------------------|
| `enable_thinking:false` | Medium — may reduce quality on hard reasoning-heavy problems for requests that don't override it | Reliable completion of all requirements on long, multi-requirement tickets; eliminates a stochastic truncation failure mode |
| `--tool-call-parser qwen3_xml` (no change, confirmed) | None | Settles a 5-revision flip-flop with a directly-pasted primary source instead of another doc-derived guess |
| Stale-doc corrections (`CLAUDE.md`, `litellm-config.yaml`, `docs/models.md`, `docs/architecture.md`) | None | Removes claims that the running config used `qwen3_coder` and had it "verified" — both no longer true |

---

## Notes

- If per-request output quality on genuinely hard problems regresses under real use, the first lever to try is
  raising Cline's own `max_tokens` for this model (client-side), not reverting `enable_thinking:false`.
- `"preserve_thinking":true` was left in place alongside `"enable_thinking":false` — it's a harmless no-op with
  no reasoning content to preserve, kept in case this decision is revisited later.
- Should the `cline` CLI ever need to run against a repo genuinely outside `/home/leeray75/vscode-workspace`,
  that needs its own investigation (a different hub daemon instance? `--zen`? killing and restarting the daemon
  with a different `--cwd`?) — out of scope here, worked around by staying inside the pinned workspace instead.
