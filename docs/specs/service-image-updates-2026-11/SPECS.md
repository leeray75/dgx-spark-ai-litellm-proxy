# Service image updates (2026-11) — Specifications

Spec-driven development (SDD) for updating the stack's **shared service images** to their current releases. These are the services every compose file runs alongside the chat engine: LiteLLM, Langfuse (web and worker), Postgres, Redis, ClickHouse and agentgateway. The chat and embedding engines are **out of scope**. The Flash-Next engine was updated separately in [`qwen38-flash-next-stack` Phase 4](../qwen38-flash-next-stack/phase-4-engine-image-update/spec.md).

These are container updates, not OS, driver or firmware updates. The DGX Spark bricking risks in `~/.claude/CLAUDE.md` don't apply. Its `sudo` rule and its rule about restart policies do.

## Phases

| Phase | Folder | Scope | Status |
|---|---|---|---|
| **1** | [phase-1-update-and-verify/](phase-1-update-and-verify/spec.md) | Back up, pin and pull. Recreate each service individually; the engines are never restarted. Verify against a baseline taken just before, roll back per service on failure, and update the docs. | ✅ Implemented and reviewed 2026-11-14 (2 review rounds; R001 findings F1–F6 and R002 finding N1 fixed). All 7 services kept on their new versions; no rollback |

## Documents

| Document | Scope |
|---|---|
| [research.md](research.md) | Shared facts: versions running and available, release-note actions checked against this repo's config, and the procedure from the 2026-10-27 update. Cited as `research.md R-n`. |
| `phase-N-*/spec.md`, `plan.md`, `tasks.md` | WHAT and WHY, HOW, and ordered tasks plus the review loop |

Pipeline: `spec.md` → `research.md` → `plan.md` → `tasks.md` → implementation → independent review (up to 5 rounds) → fixes → summary report → commit.

## Conventions

These are the same as [`qwen38-flash-next-stack/SPECS.md`](../qwen38-flash-next-stack/SPECS.md#conventions):

- Requirement IDs carry the phase: `FR-P1-nn` and `NFR-P1-nn`.
- `AS-n`, `D-n` and `U-n` are numbered within a phase.
- `R-n` research IDs are global and are never renumbered.
- Requirement keywords follow RFC 2119.
- Status markers: ✅ met · ⚠️ partially met · ❌ not met · ⏳ not yet verified.

Project-wide constraints come from the repo's `CLAUDE.md` and `~/.claude/CLAUDE.md`.

## Deliverables

| Artifact | Phase |
|---|---|
| Six compose files: LiteLLM `v1.109.1`, ClickHouse `26.8.37.168`, agentgateway `v1.7.0` (pins) | 1 |
| `CLAUDE.md`, `docs/architecture.md`, `CHANGELOG.md` (current versions and a per-service update variant) | 1 |
| `research.md` R-6: the versions after the update and the baseline/after battery | 1 |
| Summary report `ai-workspace/summary-reports/service-image-updates-2026-11-14.md` (FR-P1-18) | 1 |

## Open items

| Item | From | Planned in |
|---|---|---|
| The `LITELLM_MASTER_KEY` value appears once in the committed `CHANGELOG.md`, in the 2026-08-23 entry (commit `ee78f38`, a historical record; the same value is also in `ai-workspace/summary-reports/qwen3.8-27b-nvfp4-stack-2026-08-23.md` from that commit). Found by the NFR-P1-02 check. Not from this phase, and not changed here. The user owns the rotation and any history scrub | Phase 1, T016 | User decision (separate task, as the Phase 4 leak note) |
| agentgateway 1.7.0 has no session key (`failed to write generated session key ... Read-only file system`; MCP session IDs are unencrypted). R-3 assumed the key would be stored in the DB. `/mcp/image-gen` is off while Flash-Next runs | Phase 1, R-6 | Future change: set `config.session.key` or `SESSION_KEY` |
