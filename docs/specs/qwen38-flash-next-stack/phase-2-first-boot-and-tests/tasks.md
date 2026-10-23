# Qwen3.8-Flash-Next stack · Phase 2 — Tasks

Ordered. `→` marks a dependency. Every task obeys NFR-P2-01 – 04. The **⛔** marks the human checkpoint.

## Stage A — Prepare (no disruption)
- [x] **T001** Pull the engine image by digest. *(FR-P2-01)*
- [x] **T002** Create the scratch venv and download the checkpoint in the background; verify it is complete. *(FR-P2-02, AS-1)*
- [x] **T003** Add the `qwen3.8-flash-next` entry to `litellm-config.yaml`; check the diff is additive only. *(FR-P2-03)*
- [x] **T004** Extend `scripts/test-agentic-capabilities.py` with the vision test, the throughput test, neutral WARN text and the docstring. *(FR-P2-04)*
- [x] **T005** Add `--base-url` / `--api-key` and the docstring examples to the LangGraph script. *(FR-P2-05)*
- [x] **T006** → T004, T005. Run `py_compile` and `--help` on both scripts. *(FR-P2-06, AS-2)*

## Stage B/C — Shutdown
- [x] **T007** → T001 – T006. Check the 27B engine is idle and record the baselines. *(FR-P2-07)*
- [x] **T008** → T007. Stop image-gen, then bring down the standalone agentgateway and the 27B stack, in that order; check volumes. *(FR-P2-08, AS-3)*
- [x] **T009** ⛔ → T008. Memory checkpoint. If MemFree < 105 GiB, hand back to the caller for the user's cache drop. *(FR-P2-09)*

## Stage D — Boot
- [x] **T010** → T009. `up -d` the Flash-Next stack and wait for healthy (60-minute limit, watching for failures). *(FR-P2-10, 11)*
- [x] **T011** → T010. Record boot facts, the service states and `/v1/models` on the engine and LiteLLM. *(FR-P2-12, 13, AS-4 – AS-6)*

## Stage E — Tests
- [x] **T012** → T011. Run the stdlib test directly against the engine and through LiteLLM; save the reports. *(FR-P2-14, AS-7)*
- [x] **T013** → T011. Run the LangGraph test through LiteLLM; save the report. *(FR-P2-15, AS-8)*
- [x] **T014** → T012. Record throughput both ways and compare with the 27B. *(FR-P2-16, AS-9)*
- [x] **T015** → T012 – T014. Secret grep of the reports; `git status` matches NFR-P2-03. *(AS-10)*

## Stage F — Rollback (conditional)
- [x] **T016** *(not applicable: no FR-P2-17 trigger occurred)* Only on an FR-P2-17 trigger: save logs, then restore the 27B stack, agentgateway and image-gen. *(AS-11)*

## Close-out
- [x] **T017** Update the traceability table in `spec.md`, the Phases table in `../SPECS.md`, and the boot facts in `../research.md` as a new `R-12 (P2)` entry. Report to the caller.

## Review loop
- [x] **R001** An independent reviewer checks the code changes, the reports, the running state, and that the evidence matches what was claimed.
- [x] **R002** The implementer fixes the confirmed findings.
