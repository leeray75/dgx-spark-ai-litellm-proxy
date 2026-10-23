# Qwen3.8-Flash-Next stack · Phase 1 — Tasks

Ordered. `→` marks a dependency. Every task obeys NFR-P1-01: no `up`, `down`, `start`, `stop`, `restart`, `rm`, `kill`, `pull`, `create`, `run`, `build` and no `sudo`. It also obeys NFR-P1-02: never print rendered config values.

- [x] **T001** Record a baseline: `docker ps -a --format '{{.Names}}\t{{.State}}'` and `git status --short` into the scratchpad. *(AS-7)*
- [x] **T002** → T001. Create `docker-compose.qwen3.8-flash-next.yml` from `docker-compose.qwen3.8.yml` lines 576–1104 (the `services:` block to the end of the file). *(FR-P1-01, 04, 06)*
- [x] **T003** → T002. Replace the `qwen3-8-27b-nvfp4-engine` service, including its section comment and flag-rationale comment block, with the engine definition in plan.md. *(FR-P1-08 – 18)*
- [x] **T004** → T002. Point `litellm.depends_on` at `qwen3-8-flash-next-fp4-engine`. *(FR-P1-05)*
- [x] **T005** → T002. Add the `agentgateway` service per plan.md. Don't copy the top-level `name:` or the external network. *(FR-P1-19, 20)*
- [x] **T006** → T003. Update the top-level `volumes:` block. *(FR-P1-07, 13)*
- [x] **T007** → T003–T006. Write the header comment from the plan.md outline. Keep the section-divider comments. *(FR-P1-21, 22)*
- [x] **T008** → T007. Write the static validator in the scratchpad and run it. All of AS-1 to AS-6 must pass. Fix and re-run until they do. *(NFR-P1-03)*
- [x] **T009** → T008. Re-run T001's commands and confirm that only the expected files changed and the container names and states are unchanged. *(AS-7)*
- [x] **T010** → T009. Update the traceability table in `spec.md` (⏳ → ✅ for statically verified rows; runtime rows stay ⏳). Set the status in `docs/specs/qwen38-flash-next-stack/SPECS.md` to "Phase 1 implemented". Report the AS results to the caller.

## Review loop

- [x] **R001** An independent reviewer checks the file against spec.md, research.md and plan.md, re-runs the validator independently, and reports findings with requirement IDs.
- [x] **R002** The implementer fixes every confirmed finding and re-runs T008 and T009.
