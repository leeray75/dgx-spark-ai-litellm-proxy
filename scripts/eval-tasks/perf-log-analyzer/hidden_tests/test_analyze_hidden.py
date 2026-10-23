import math
import random
import time

from logstats import analyze
from logstats.gen_logs import generate


# Ground truth: the original implementation's semantics, written efficiently.
def _norm(path):
    return "/".join(":id" if s.isdigit() else s for s in path.split("/"))


def ref_all(lines):
    counts, lat, err = {}, {}, {}
    for line in lines:
        _ts, _m, path, status, latency = line.split()
        p = _norm(path)
        counts[p] = counts.get(p, 0) + 1
        lat.setdefault(p, []).append(int(latency[:-2]))
        err[p] = err.get(p, 0) + (int(status) >= 500)
    p95 = {p: sorted(v)[math.ceil(0.95 * len(v)) - 1] for p, v in sorted(lat.items())}
    rate = {p: round(err[p] / counts[p], 4) for p in sorted(counts)}
    return counts, p95, rate


def ref_top(lines, k):
    counts = ref_all(lines)[0]
    return sorted(counts.items(), key=lambda pc: (-pc[1], pc[0]))[:k]


def test_small_inputs_match_ground_truth():
    rng = random.Random(5)
    for trial in range(60):
        lines = generate(rng.randint(1, 300), seed=trial, resources=rng.choice([1, 3, 20]))
        counts, p95, rate = ref_all(lines)
        for k in (1, 3, 1000):
            assert [tuple(x) for x in analyze.top_paths(lines, k)] == ref_top(lines, k)
        assert analyze.p95_by_path(lines) == p95
        assert analyze.error_rate_by_path(lines) == rate


def test_tie_ordering_and_percentile_edges():
    lines = [f"2026-10-23T00:00:00Z GET /b/{i} 200 {i}ms" for i in range(1, 21)]
    lines += [f"2026-10-23T00:00:00Z GET /a/{i} 503 {i}ms" for i in range(1, 22)]
    lines += ["2026-10-23T00:00:00Z GET /c 200 7ms"]
    lines += [f"2026-10-23T00:00:00Z GET /d/{i} 200 5ms" for i in range(20)]
    assert [tuple(x) for x in analyze.top_paths(lines, 3)] == [("/a/:id", 21), ("/b/:id", 20), ("/d/:id", 20)]
    assert analyze.p95_by_path(lines) == {"/a/:id": 20, "/b/:id": 19, "/c": 7, "/d/:id": 5}
    assert analyze.error_rate_by_path(lines)["/a/:id"] == 1.0


def test_empty_input():
    assert list(analyze.top_paths([], 5)) == []
    assert analyze.p95_by_path([]) == {}
    assert analyze.error_rate_by_path([]) == {}


LARGE = None
UNIFORM = None


def large():
    """Realistic, skewed traffic (a few hot paths)."""
    global LARGE
    if LARGE is None:
        LARGE = generate(200_000, seed=42)
    return LARGE


def uniform():
    """200k lines spread evenly over 3,000 normalised paths: no hot paths for a linear scan to get lucky on."""
    global UNIFORM
    if UNIFORM is None:
        rng = random.Random(99)
        UNIFORM = [f"2026-10-23T00:00:00Z GET /svc{i % 3000}/item/{rng.randint(1, 10**6)} "
                   f"{rng.choice((200, 200, 200, 404, 500))} {rng.randint(1, 900)}ms" for i in range(200_000)]
        rng.shuffle(UNIFORM)
    return UNIFORM


def best_of_3(fn, *args):
    """Best wall time of up to 3 runs (stops early once under the limit), so a busy machine doesn't fail a fast solution."""
    best, result = None, None
    for _ in range(3):
        start = time.perf_counter()
        result = fn(*args)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
        if best < 3.0:
            break
    return result, best


def check(fn, expected, *args):
    result, seconds = best_of_3(fn, *args)
    if isinstance(expected, list):
        result = [tuple(x) for x in result]
    assert result == expected
    assert seconds < 3.0, f"{fn.__name__} took {seconds:.2f}s"


def test_top_paths_fast_and_correct():
    check(analyze.top_paths, ref_top(large(), 25), large(), 25)


def test_top_paths_fast_on_uniform_traffic():
    check(analyze.top_paths, ref_top(uniform(), 25), uniform(), 25)


def test_p95_fast_and_correct():
    check(analyze.p95_by_path, ref_all(large())[1], large())


def test_p95_fast_on_uniform_traffic():
    check(analyze.p95_by_path, ref_all(uniform())[1], uniform())


def test_error_rate_fast_and_correct():
    check(analyze.error_rate_by_path, ref_all(large())[2], large())
