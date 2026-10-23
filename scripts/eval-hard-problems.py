#!/usr/bin/env python3
"""
Hard-Problem Evaluation — coding, engineering, algorithms, data structures, logic
================================================================================
Sends a fixed set of difficult problems to a served model through agentgateway
(OpenAI-compatible /v1/chat/completions on :4100) and stores every response,
with its reasoning, token usage and timings, in a JSON document for grading.

The JSON is rewritten after every answer (meta.complete is false until the
last one), so an interrupted run keeps what it finished; --resume FILE picks
it up again, re-running only missing and errored problems.

The script does NOT grade. Each problem carries a `reference` (expected answer
or key points) and a `rubric` so a separate grader (human or agent) can score
the saved responses. Coding problems ask for one ```python block defining a
fixed function signature, so a grader can run the code against its own tests.

Requests stream (SSE) so long reasoning runs don't sit idle on one socket, and
run with limited concurrency (default 2) so per-request decode speed stays
reasonable on the single-GPU engine (--max-num-seqs 8) and a full-budget answer
finishes inside agentgateway's 1500 s timeout.

Usage:
    python3 scripts/eval-hard-problems.py [--base-url URL] [--api-key KEY] [--model MODEL]
                                          [--output FILE] [--max-tokens N] [--concurrency N]
                                          [--only ID[,ID...]] [--resume FILE [--rerun-truncated]]

Examples:
    # default: qwen3.8-flash-next through agentgateway, all problems
    python3 scripts/eval-hard-problems.py
    # two problems only, the hard-problem budget
    python3 scripts/eval-hard-problems.py --only algo-median-two-arrays,logic-12-coins --max-tokens 38912 --concurrency 1
    # continue an interrupted run (or retry its errors)
    python3 scripts/eval-hard-problems.py --resume ai-workspace/reports/hard-eval-qwen3.8-flash-next-<UTC>.json
    # re-run answers that hit max_tokens with a bigger budget (old answers kept under previous_attempts)
    python3 scripts/eval-hard-problems.py --resume <same file> --rerun-truncated --max-tokens 38912 --concurrency 1
"""

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE_URL = "http://localhost:4100/v1"   # agentgateway
DEFAULT_MODEL = "qwen3.8-flash-next"
# Reasoning tokens count toward max_tokens. Qwen's model cards recommend 32,768 for
# most queries and 38,912 for hard math/programming-competition problems
# (https://huggingface.co/Qwen/Qwen3-235B-A22B); 16,384 truncated 2 of the first 5
# answers here. The real ceiling is agentgateway's 1500 s LLM route timeout: at
# ~27 tok/s per request (2 concurrent) 32,768 tokens take ~1,215 s; 38,912 needs
# --concurrency 1 (~43 tok/s, ~905 s).
DEFAULT_MAX_TOKENS = 32768
HARD_MAX_TOKENS = 38912   # suggested for --rerun-truncated, with --concurrency 1
REQUEST_TIMEOUT = 1800  # seconds; above agentgateway's 1500 s, so the gateway's limit is the binding one

SYSTEM_PROMPT = (
    "You are an expert software engineer and computer scientist. Solve the problem completely and "
    "correctly. When code is requested, give exactly one fenced ```python block containing the full "
    "solution with the requested function signature, using only the Python standard library, followed "
    "by a short explanation and the time/space complexity. When an exact answer is requested, state it "
    "clearly on a final line of the form `ANSWER: <value>`."
)

# =============================================================================
# Problem set. `reference` and `rubric` are for the grader, never sent to the model.
# =============================================================================

PROBLEMS = [
    {
        "id": "algo-median-two-arrays",
        "category": "algorithm",
        "difficulty": "hard",
        "prompt": (
            "Write `def find_median(a: list[int], b: list[int]) -> float` returning the median of the "
            "union of two sorted arrays (either may be empty, but not both). It must run in "
            "O(log(min(m, n))) time and O(1) extra space; merging or sorting is not acceptable."
        ),
        "reference": "Binary search on the partition of the shorter array; compare max-left/min-right "
                     "with ±inf sentinels; average the two middle values when the total length is even.",
        "rubric": ["Correct on empty/one-element/odd/even/duplicate inputs",
                   "Truly O(log(min(m,n))) — binary searches the shorter array",
                   "Handles partition edges without index errors"],
    },
    {
        "id": "algo-count-smaller-after-self",
        "category": "algorithm",
        "difficulty": "hard",
        "prompt": (
            "Write `def count_smaller(nums: list[int]) -> list[int]` where result[i] is the number of "
            "elements to the right of nums[i] that are strictly smaller than nums[i]. n can be 10^5 and "
            "values can be any 32-bit integers (including negatives and duplicates). Must be O(n log n)."
        ),
        "reference": "Merge sort on indices counting right-side elements moved before each left element, "
                     "or a Fenwick tree over coordinate-compressed values scanned right to left. "
                     "Example: [5,2,6,1] -> [2,1,1,0].",
        "rubric": ["Correct output including duplicates (strictly smaller)",
                   "O(n log n); no O(n^2) fallback",
                   "Handles negatives (coordinate compression or merge-sort)"],
    },
    {
        "id": "algo-edit-distance-ops",
        "category": "algorithm",
        "difficulty": "medium-hard",
        "prompt": (
            "Write `def edit_script(s: str, t: str) -> tuple[int, list[str]]` returning the Levenshtein "
            "distance (insert, delete, substitute, each cost 1) and one optimal sequence of operations "
            "that turns s into t, as strings like 'insert x at 3', 'delete y at 0', "
            "'substitute a->b at 2' (indices refer to the string as it is when the operation applies)."
        ),
        "reference": "DP table plus backtracking. distance('kitten','sitting') = 3; "
                     "distance('', 'abc') = 3; distance('intention','execution') = 5.",
        "rubric": ["Distance correct", "Operation list has exactly `distance` entries",
                   "Applying the operations in order actually yields t (index bookkeeping correct)"],
    },
    {
        "id": "algo-domino-tromino-count",
        "category": "algorithm/math",
        "difficulty": "hard",
        "prompt": (
            "In how many ways can a 2 x 10 board be completely tiled using 2x1 dominoes (either "
            "orientation) and L-shaped trominoes (any rotation)? Derive a recurrence, show the values "
            "for n = 1..10, and give the exact count for n = 10."
        ),
        "reference": "f(n) = 2 f(n-1) + f(n-3), f(0)=1, f(1)=1, f(2)=2 -> 1, 2, 5, 11, 24, 53, 117, 258, "
                     "569, 1255. ANSWER: 1255.",
        "rubric": ["Final answer exactly 1255", "Valid recurrence/derivation",
                   "Intermediate values consistent"],
    },
    {
        "id": "ds-lru-ttl-cache",
        "category": "data structure",
        "difficulty": "hard",
        "prompt": (
            "Implement `class LRUCache` with `__init__(self, capacity: int, clock=time.monotonic)`, "
            "`get(self, key) -> value or None`, and `put(self, key, value, ttl: float | None = None)`. "
            "Entries with a ttl expire ttl seconds after their last put (get does NOT refresh ttl). "
            "Expired entries must never be returned and must not count toward capacity when deciding "
            "evictions. get and put must be O(1) amortized. Do not use functools.lru_cache. The clock "
            "argument lets tests inject a fake time source."
        ),
        "reference": "Hash map + doubly linked list (or OrderedDict) for recency, plus a min-heap of "
                     "(expiry, key, version) with lazy deletion so expired entries are purged before "
                     "LRU eviction; get checks expiry.",
        "rubric": ["get never returns expired values",
                   "Expired entries purged before evicting a live LRU entry",
                   "Re-put of a key updates value, recency and ttl correctly (stale heap entries ignored)",
                   "O(1) amortized operations; uses injected clock"],
    },
    {
        "id": "ds-randomized-multiset",
        "category": "data structure",
        "difficulty": "hard",
        "prompt": (
            "Implement `class RandomizedMultiset` with `insert(val) -> bool` (True if val was not "
            "already present), `remove(val) -> bool` (removes ONE occurrence; True if one existed), and "
            "`get_random()` returning an element with probability proportional to its count. All "
            "operations must be O(1) average time. Duplicates are allowed."
        ),
        "reference": "List of values + dict val -> set of indices; remove swaps the target index with "
                     "the last element and fixes the moved element's index set (careful when the "
                     "removed index is the last one).",
        "rubric": ["Correct swap-with-last bookkeeping, including when idx is the last position",
                   "get_random uniform over occurrences", "O(1) average for all ops"],
    },
    {
        "id": "ds-skyline",
        "category": "data structure/algorithm",
        "difficulty": "hard",
        "prompt": (
            "Write `def skyline(buildings: list[list[int]]) -> list[list[int]]` for the classic skyline "
            "problem: each building is [left, right, height], return the key points [x, height] where "
            "the outline's height changes, sorted by x, with no consecutive equal heights. Must be "
            "O(n log n)."
        ),
        "reference": "Sweep line over edge events with a max-heap and lazy removal (or sorted multiset). "
                     "[[2,9,10],[3,7,15],[5,12,12],[15,20,10],[19,24,8]] -> "
                     "[[2,10],[3,15],[7,12],[12,0],[15,10],[20,8],[24,0]].",
        "rubric": ["Correct on the reference example", "Handles equal x / equal heights without duplicate points",
                   "O(n log n)"],
    },
    {
        "id": "eng-expression-evaluator",
        "category": "development",
        "difficulty": "medium-hard",
        "prompt": (
            "Write `def evaluate(expr: str) -> float` that evaluates arithmetic expressions with +, -, *, "
            "/, ^ (exponent, right-associative, binds tighter than unary minus so -2^2 = -4), unary "
            "minus, parentheses, decimal numbers and arbitrary whitespace. Do not use eval, exec, ast or "
            "any parsing library. Raise ValueError with a helpful message on malformed input "
            "(e.g. '2 +', '(1', '1 2', '')."
        ),
        "reference": "Recursive descent or precedence climbing. evaluate('2^3^2') = 512; "
                     "evaluate('-2^2') = -4; evaluate('(1+2)*-3') = -9; evaluate('2*(3+4)/7') = 2.",
        "rubric": ["Correct precedence and right-associative ^", "Unary minus semantics as specified",
                   "Raises ValueError on all malformed examples", "No eval/ast"],
    },
    {
        "id": "eng-race-condition-fix",
        "category": "engineering/concurrency",
        "difficulty": "hard",
        "prompt": (
            "This cache is used by many threads. Find every concurrency bug, explain the failure each "
            "causes, and give a corrected version that never computes the same key twice concurrently "
            "and does not hold a global lock while `loader` runs:\n\n"
            "```python\nimport threading\n\nclass Memo:\n    def __init__(self, loader):\n"
            "        self.loader = loader\n        self.data = {}\n        self.hits = 0\n"
            "        self.lock = threading.Lock()\n\n    def get(self, key):\n"
            "        if key in self.data:\n            self.hits += 1\n            return self.data[key]\n"
            "        value = self.loader(key)          # slow, may raise\n"
            "        with self.lock:\n            self.data[key] = value\n        return value\n```"
        ),
        "reference": "Check-then-act lets several threads call loader for the same key; hits += 1 is a "
                     "non-atomic read-modify-write. Fix: per-key in-flight futures/events created under "
                     "the lock, loader run outside the lock, waiters block on the future, exceptions "
                     "propagated to waiters and the in-flight entry removed so a later call can retry.",
        "rubric": ["Identifies duplicate computation (check-then-act)", "Identifies non-atomic hits counter",
                   "Fix uses per-key in-flight tracking without holding the global lock during load",
                   "Handles loader exceptions (no permanent poisoning / no hang for waiters)"],
    },
    {
        "id": "eng-bounded-blocking-queue",
        "category": "engineering/concurrency",
        "difficulty": "medium-hard",
        "prompt": (
            "Implement `class BoundedQueue` with `__init__(self, capacity: int)`, `put(self, item, "
            "timeout: float | None = None)` and `get(self, timeout: float | None = None)` using only "
            "threading.Lock/Condition (not queue.Queue). put blocks while full, get blocks while empty; "
            "on timeout raise TimeoutError. Also add `close()`: after close, put raises RuntimeError, get "
            "drains remaining items and then raises RuntimeError instead of blocking forever. Explain "
            "how your design avoids lost wakeups and spurious-wakeup bugs."
        ),
        "reference": "Two Conditions (not_full/not_empty) sharing one lock, predicates checked in while "
                     "loops with deadline-adjusted remaining timeout, notify on state change, close() "
                     "notify_all on both.",
        "rubric": ["while-loop predicate checks (spurious wakeups)", "Timeouts computed from a deadline",
                   "close() wakes all waiters; get drains then raises", "No queue.Queue"],
    },
    {
        "id": "eng-tcp-40ms-latency",
        "category": "engineering/systems",
        "difficulty": "hard",
        "prompt": (
            "A Linux RPC client sends each request as two write() calls (a 12-byte header, then a 200-byte "
            "body) over a persistent TCP connection. The server replies only after reading the full "
            "request. Median latency on a LAN is ~40 ms, but sending the request with a single write() "
            "drops it to ~0.2 ms. Explain precisely what is happening, which side's behaviour causes "
            "each part of the delay, and give at least three fixes with their trade-offs."
        ),
        "reference": "Nagle's algorithm on the client holds the second small segment until the first is "
                     "ACKed; the server's delayed-ACK timer (~40 ms on Linux) holds the ACK because it has "
                     "no response to piggyback until it has the full request. Fixes: single write / "
                     "writev / buffering, TCP_NODELAY, TCP_CORK/MSG_MORE, TCP_QUICKACK on server.",
        "rubric": ["Names Nagle (client) and delayed ACK (server) and their interaction",
                   "Explains why one write avoids it", "At least three valid fixes with trade-offs"],
    },
    {
        "id": "eng-sql-top3-salaries",
        "category": "development/sql",
        "difficulty": "medium",
        "prompt": (
            "Tables: employee(id, name, salary, department_id), department(id, name). Write one "
            "standard SQL query returning, for every department, the employees whose salary is among "
            "the top three DISTINCT salary values in that department (so ties are all included and a "
            "department may return more than three rows). Output department name, employee name, "
            "salary, ordered by department name then salary descending. Explain why ROW_NUMBER or "
            "RANK would be wrong."
        ),
        "reference": "DENSE_RANK() OVER (PARTITION BY department_id ORDER BY salary DESC) <= 3, joined "
                     "to department. ROW_NUMBER drops ties; RANK skips values after ties, so fewer than "
                     "three distinct salaries may be returned.",
        "rubric": ["Uses DENSE_RANK (or an equivalent correlated count of distinct higher salaries)",
                   "Correct join and ordering", "Correct explanation of ROW_NUMBER vs RANK"],
    },
    {
        "id": "logic-12-coins",
        "category": "logic",
        "difficulty": "hard",
        "prompt": (
            "You have 12 coins; exactly one is counterfeit and is either heavier or lighter than the "
            "others (you don't know which). Using a balance scale exactly three times, give a complete "
            "strategy (every branch of every weighing) that always identifies the counterfeit coin AND "
            "whether it is heavier or lighter. Label coins 1-12."
        ),
        "reference": "Classic: weigh 1-4 vs 5-8; branch on balance/tilt with mixed re-weighings (e.g. "
                     "1,2,5 vs 3,6,9 style). Every one of the 24 outcomes (12 coins x heavy/light) must "
                     "map to a distinct leaf.",
        "rubric": ["All branches specified (no 'similarly' hand-waving for distinct cases)",
                   "Every one of 24 possibilities identified with direction",
                   "Never uses more than 3 weighings"],
    },
    {
        "id": "logic-dice-two-sixes",
        "category": "logic/probability",
        "difficulty": "medium-hard",
        "prompt": (
            "A fair six-sided die is rolled repeatedly until two sixes appear on consecutive rolls. "
            "What is the expected number of rolls? Derive it with a Markov-chain/state argument, then "
            "give the expected number of rolls until the sequence 6 then 5 appears (consecutively) and "
            "explain intuitively why the two answers differ."
        ),
        "reference": "Two consecutive sixes: 42. Six then five: 36. The 6-6 pattern overlaps itself, so a "
                     "failure after the first 6 (rolling non-6) loses progress, whereas after 6-then-non-5 "
                     "a 6 keeps progress.",
        "rubric": ["42 for 6-6", "36 for 6-5", "Correct state equations",
                   "Correct intuition (self-overlap / progress retention)"],
    },
    {
        "id": "logic-bit-single-number",
        "category": "algorithm/bit manipulation",
        "difficulty": "medium-hard",
        "prompt": (
            "Write `def single_number(nums: list[int]) -> int`: every element appears exactly three "
            "times except one, which appears exactly once. Values are 32-bit signed integers (may be "
            "negative). Use O(n) time and O(1) extra space (no hash maps, no sorting). Explain why it "
            "works."
        ),
        "reference": "Bit counting mod 3 or the ones/twos state machine; convert the 32-bit result back "
                     "to a negative Python int when bit 31 is set. [-2,-2,1,1,-3,1,-3,-3,-4,-2] -> -4.",
        "rubric": ["Correct for negatives (sign handling in Python)", "O(1) extra space",
                   "Valid explanation"],
    },
]


# =============================================================================
# HTTP (stdlib only, streaming)
# =============================================================================

def stream_completion(base_url, api_key, model, messages, max_tokens):
    """Stream one chat completion; returns content, reasoning, usage, finish_reason and timings."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    start = time.time()
    first_token_at = None
    content, reasoning = [], []
    usage, finish_reason, response_model = None, None, None
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            response_model = chunk.get("model") or response_model
            if chunk.get("usage"):
                usage = chunk["usage"]
            # agentgateway ends a stream with a usage-only chunk whose choices is []
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            piece_r = delta.get("reasoning_content") or delta.get("reasoning")
            piece_c = delta.get("content")
            if (piece_r or piece_c) and first_token_at is None:
                first_token_at = time.time()
            if piece_r:
                reasoning.append(piece_r)
            if piece_c:
                content.append(piece_c)
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    end = time.time()
    completion_tokens = (usage or {}).get("completion_tokens")
    decode_seconds = end - first_token_at if first_token_at else None
    return {
        "content": "".join(content),
        "reasoning": "".join(reasoning),
        "finish_reason": finish_reason,
        "response_model": response_model,
        "usage": usage,
        "timing": {
            "total_seconds": round(end - start, 2),
            "time_to_first_token_seconds": round(first_token_at - start, 2) if first_token_at else None,
            "decode_tokens_per_second": round(completion_tokens / decode_seconds, 1)
            if completion_tokens and decode_seconds else None,
        },
    }


def run_problem(problem, args, api_key, print_lock):
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": problem["prompt"]}]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {k: problem[k] for k in ("id", "category", "difficulty", "prompt", "reference", "rubric")}
    record["started_at"] = started
    record["max_tokens"] = args.max_tokens
    try:
        record["response"] = stream_completion(args.base_url, api_key, args.model, messages, args.max_tokens)
        record["error"] = None
    except urllib.error.HTTPError as e:
        record["response"] = None
        record["error"] = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}"
    except Exception as e:  # network errors, timeouts, bad JSON
        record["response"] = None
        record["error"] = f"{type(e).__name__}: {e}"
    with print_lock:
        r = record["response"]
        if r:
            u = r["usage"] or {}
            print(f"  done  {problem['id']:<32} finish={r['finish_reason']:<7} "
                  f"out={u.get('completion_tokens', '?'):>6} tok  {r['timing']['total_seconds']:>7.1f}s  "
                  f"{r['timing']['decode_tokens_per_second'] or '?'} tok/s")
        else:
            print(f"  ERROR {problem['id']:<32} {record['error']}")
    return record


def load_api_key_from_env_file(project_dir):
    env_path = Path(project_dir) / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("LITELLM_MASTER_KEY="):
            value = line.split("=", 1)[1]
            value = value.split("#", 1)[0]  # strip inline comment
            return value.strip().strip('"').strip("'")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=os.environ.get("LITELLM_MASTER_KEY"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help="Per-problem budget, reasoning included (default %(default)s)")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--only", help="Comma-separated problem ids to run")
    parser.add_argument("--output", help="JSON output path (default ai-workspace/reports/hard-eval-<model>-<UTC>.json)")
    parser.add_argument("--resume", metavar="FILE",
                        help="Continue an earlier run: keep its answered problems, re-run missing/errored ones, "
                             "save into the same file")
    parser.add_argument("--rerun-truncated", action="store_true",
                        help="With --resume: also re-run problems whose answer hit max_tokens (use a larger "
                             "--max-tokens); the cut-off answer is kept under previous_attempts")
    args = parser.parse_args()
    if args.resume and args.output:
        parser.error("--resume saves into FILE; don't combine it with --output")
    if args.rerun_truncated and not args.resume:
        parser.error("--rerun-truncated needs --resume FILE")

    project_dir = Path(__file__).resolve().parent.parent
    api_key = args.api_key or load_api_key_from_env_file(project_dir)
    if not api_key:
        print("ERROR: no API key found. Pass --api-key, set LITELLM_MASTER_KEY, "
              "or run this from a checkout with a populated .env file.", file=sys.stderr)
        sys.exit(1)

    problems = PROBLEMS
    if args.only:
        wanted = {p.strip() for p in args.only.split(",")}
        unknown = wanted - {p["id"] for p in PROBLEMS}
        if unknown:
            sys.exit(f"ERROR: unknown problem id(s): {', '.join(sorted(unknown))}")
        problems = [p for p in PROBLEMS if p["id"] in wanted]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.output) if args.output else \
        project_dir / "ai-workspace" / "reports" / f"hard-eval-{args.model}-{stamp}.json"

    # --resume: keep answered problems from an earlier run's file, re-run the
    # missing and errored ones (plus, with --rerun-truncated, the ones that hit
    # max_tokens), and keep saving into that same file. Results outside --only
    # are carried over untouched.
    kept, superseded, prior_wall = [], {}, 0.0
    if args.resume:
        output = Path(args.resume)
        previous = json.loads(output.read_text())
        if previous["meta"]["model"] != args.model:
            sys.exit(f"ERROR: {output} is for model {previous['meta']['model']!r}, not {args.model!r}")
        prior_wall = previous["meta"].get("wall_seconds") or 0.0
        prior_max_tokens = previous["meta"].get("max_tokens")
        by_id = {r["id"]: r for r in previous["results"]}

        def needs_run(pid):
            r = by_id.get(pid)
            if r is None or not r["response"]:
                return True
            return args.rerun_truncated and r["response"]["finish_reason"] == "length"

        rerun_ids = {p["id"] for p in problems if needs_run(p["id"])}
        kept = [r for r in previous["results"] if r["id"] not in rerun_ids]
        # A truncated answer being re-run is kept under previous_attempts of the new result.
        for pid in rerun_ids:
            r = by_id.get(pid)
            if r and r["response"]:
                r.setdefault("max_tokens", prior_max_tokens)
                superseded[pid] = r
        problems = [p for p in problems if p["id"] in rerun_ids]
        print(f"Resuming {output}: keeping {len(kept)}, running {len(problems)} "
              f"({len(superseded)} truncated re-run at max_tokens={args.max_tokens})")

    order = {p["id"]: i for i, p in enumerate(PROBLEMS)}
    run_start = time.time()

    def save(records, complete):
        """Write the whole document atomically (temp file + rename) so a crash never leaves half a file."""
        ok = [r for r in records if r["response"]]
        document = {
            "meta": {
                "model": args.model,
                "base_url": args.base_url,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "complete": complete,
                "max_tokens": args.max_tokens,
                "concurrency": args.concurrency,
                "system_prompt": SYSTEM_PROMPT,
                "wall_seconds": round(prior_wall + time.time() - run_start, 1),
                "problems": len(records),
                "errors": len(records) - len(ok),
                "truncated": sum(1 for r in ok if r["response"]["finish_reason"] == "length"),
                "total_completion_tokens": sum((r["response"]["usage"] or {}).get("completion_tokens", 0) for r in ok),
                "grading": None,  # filled in by the grader
            },
            "results": sorted(records, key=lambda r: order[r["id"]]),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(output.suffix + ".tmp")
        tmp.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, output)
        return document["meta"]

    print(f"Evaluating model={args.model!r} via {args.base_url}: {len(problems)} problems, "
          f"max_tokens={args.max_tokens}, concurrency={args.concurrency}")
    print(f"Saving after each answer to: {output}\n")
    print_lock = threading.Lock()
    records = list(kept)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(run_problem, p, args, api_key, print_lock) for p in problems]
        for f in as_completed(futures):
            record = f.result()
            old = superseded.get(record["id"])
            if old:
                attempt = {k: old.get(k) for k in ("started_at", "max_tokens", "response", "error")}
                record["previous_attempts"] = old.get("previous_attempts", []) + [attempt]
            records.append(record)
            save(records, complete=False)
    m = save(records, complete=True)

    print(f"\n{m['problems']} problems, {m['errors']} errors, {m['truncated']} hit max_tokens, "
          f"{m['total_completion_tokens']} completion tokens, {m['wall_seconds']}s")
    print(f"Saved: {output}")
    if m["errors"]:
        print(f"Re-run the errored problems with: --resume {output}")
    if m["truncated"]:
        print(f"Re-run the truncated ones with a larger budget: --resume {output} --rerun-truncated "
              f"--max-tokens {HARD_MAX_TOKENS} --concurrency 1")
    sys.exit(1 if m["errors"] else 0)


if __name__ == "__main__":
    main()
