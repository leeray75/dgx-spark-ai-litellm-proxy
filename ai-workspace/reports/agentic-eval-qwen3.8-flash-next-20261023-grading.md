# Agentic eval grading: qwen3.8-flash-next (run 20261023T051241Z)

Grader: Claude subagent, 2026-10-23T06:14Z. The grades are also stored in the results JSON under `meta.grading` and `results[].grade`.

## Headline

- **Hidden tests: 78/85.** 3 of 5 tasks fully pass. Only 2 of 5 tasks called `finish`. Mean overall score: **6.6/10**.
- The model solves every task, but it does not know when to stop. In all three turn-limit tasks the core work was correct and green by turn 15-20. The remaining 20+ turns went on polishing.
- **fix-memo-concurrency scored 0/6 because of one cosmetic edit in turn 40**, made without re-running tests. Reverting that single edit gives **6/6** (measured in the eval sandbox, 3 runs). Without that edit the run would have scored 84/85.

## Per-task summary

| Task | Status | Turns | Time | Output tok | Hidden | Correct | Code | Tests | Process | Overall |
|---|---|---|---|---|---|---|---|---|---|---|
| feature-todo-due-dates | finished (after nudge) | 17 | 5.0 min | 12.8k | 7/7 | 10 | 8 | 9 | 8 | **9** |
| fix-booking-intervals | finished (after nudge) | 15 | 4.8 min | 13.2k | 12/12 | 10 | 9 | 9 | 8 | **9** |
| fix-memo-concurrency | turn_limit | 40 | 16.9 min | 39.6k | 0/6 | 2 | 6 | 7 | 3 | **3** |
| implement-expression-evaluator | turn_limit | 40 | 16.8 min | 41.2k | 53/54 | 7 | 6 | 7 | 4 | **5** |
| perf-log-analyzer | turn_limit | 40 | 14.5 min | 24.7k | 6/6 | 10 | 7 | 7 | 5 | **7** |

The three turn-limit tasks also used 556k-609k prompt tokens each, because the context grows every turn.

## Findings

**feature-todo-due-dates (9).**
- All requirements are met.
- Validation is strict (regex plus `strptime`), and an invalid date exits 2 before anything is written.
- Code size is close to the reference. It added 23 subprocess tests, including legacy data files and the "strictly before today" boundary.
- At turn 11 it ended with a plain-text summary and needed the nudge to call `finish`.
- The finish_summary matches the diff (25 passed).

**fix-booking-intervals (9).**
- It found all six defects: sorting, touching intervals, contained interval, `>=` for min_length, window clamping, and negative busy minutes.
- The final code is almost the reference solution.
- It added 29 unit tests plus `test_user_reports.py`, which maps each of the five user reports to a test.
- Same nudge pattern as the todo task. The summary is accurate.

**fix-memo-concurrency (3).**
- The implementation written at turn 3 (in-flight table, one Event per load, shared exception, exact stats under the lock) is correct and matches the reference. It was not touched again until turn 40.
- Its own tests were green at turn 14-15.
- Turns 16-39 went on test polishing. About 9 of those turns repaired a test file that its own edit had mangled at turn 25.
- At turn 40 it removed the "unused" `key` parameter from `_Load.__init__` but left the caller `_Load(key)` unchanged. Every `get()` now raises TypeError: 0/6 hidden and 0/13 of its own tests.
- **Estimate if stopped earlier: 6/6.** This was measured by reverting only that edit.
- The tests are good and event-driven (0.04s), but they reach into private state (`_inflight`, `waiters`), which put a test-only field into Memo.

**implement-expression-evaluator (5).**
- The 53/54 is a real design choice, not a cut-off artefact.
- At turns 10-14 it added a recursion-depth cap. It allowed about 50 paren levels at first, and about 30 after the turn-37 change. Its own tests assert that 400-deep input must raise. The spec has no limit, and the reference raises the recursion limit instead.
- The cap was needed only because a `_call` guard wrapper doubles the stack frames per grammar level.
- Code is 246 lines against the 84-line reference.
- Good: a seeded fuzz test against an independent shunting-yard oracle (915 tests in about 0.5s).
- Bad: leftover `tests/_tmp_probe.py` (most probes fail) and an empty `tests/_tmp_show.py`.
- The last 22 turns were spent flip-flopping on recursion limits, and it ended mid-experiment.
- Estimate if stopped earlier: 53/54 at any point from turn 14. The uncapped turn-3 version was never tested.

**perf-log-analyzer (7).**
- It reproduced the slowness first (a 120s baseline run), then wrote a single-pass aggregation: about 0.18s per report, and 0.45s in the worst case with all-distinct paths.
- It copied the original implementation into `tests/reference_impl.py` and used it as an equivalence oracle (69 cases). This is excellent practice.
- The work was complete by turn 20. The rest was churn: twice adding `raise AssertionError` just to see printed timings, and a cache-size experiment.
- That experiment left a stale "unbounded cache" comment next to `maxsize=100_000`.
- `test_perf_report.py` is a repurposed scratch file with no assertions.
- It never called `finish`.

## Cross-task behaviours

**Good**
- Reads the code before editing.
- Treats docstrings as the spec and leaves them unchanged.
- Writes regression tests that map to the bug reports.
- Uses independent oracles: the original code for perf, shunting-yard for the evaluator.
- Prefers deterministic, event-based concurrency tests.
- Its finish summaries were accurate.

**Bad**
- **No awareness of the turn budget.** It kept polishing after reaching a green state in 3 of 5 tasks.
- **Edits production code at the end without verifying.** This destroyed the memo task.
- **Ends with a plain-text summary instead of calling `finish`.** This happened in both completed tasks.
- **Gold-plating:** the depth cap, re-entrancy detection, a TypeError for non-str input, and an extra benchmark file.
- **Scratch-file debris**, made worse because there is no delete tool and `run_tests` hides stdout. The model worked around this by writing deliberately failing asserts and repurposing scratch files as tests.

## Recommendations

**Harness**
1. Show the budget: put `turn N/40` in each tool result, and inject reminders at about turn 32 and turn 37 ("N turns left; if tests pass, stop editing and call finish").
2. Snapshot the workspace at every green full-suite `run_tests`. On `turn_limit`, report hidden tests for both the final state and the last green state, plus the turn of the first green run. This separates cut-off damage from real bugs.
3. After the final turn, auto-run the visible suite and flag when the final state is worse than the last green state.
4. In the system prompt, say: "Your last action must be a `finish` tool call; never end with a plain-text summary."
5. Add a `delete_file` tool and an option for `run_tests` to show stdout (`-s`/`-rP`).
6. Flag `tests/_tmp_*` files and test files with no assertions during grading.
7. Don't raise `max_turns`. The work was done by turn 15-20; add the nudges instead.

**Tasks**
- **implement-expression-evaluator:** either state the requirement in the docstring ("must handle at least 100 nested parentheses") or keep the test as a deliberate robustness probe and document that choice.
- **perf-log-analyzer:** wall-clock budgets depend on host load. Keep the 2-CPU sandbox and consider a retry or a margin on timing asserts.
- **fix-memo-concurrency:** fine as is. Optionally say that tests should use only the public API.
