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


def large():
    global LARGE
    if LARGE is None:
        LARGE = generate(200_000, seed=42)
    return LARGE


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - start


def test_top_paths_fast_and_correct():
    lines = large()
    result, seconds = timed(analyze.top_paths, lines, 25)
    assert [tuple(x) for x in result] == ref_top(lines, 25)
    assert seconds < 3.0, f"top_paths took {seconds:.2f}s"


def test_p95_fast_and_correct():
    lines = large()
    result, seconds = timed(analyze.p95_by_path, lines)
    assert result == ref_all(lines)[1]
    assert seconds < 3.0, f"p95_by_path took {seconds:.2f}s"


def test_error_rate_fast_and_correct():
    lines = large()
    result, seconds = timed(analyze.error_rate_by_path, lines)
    assert result == ref_all(lines)[2]
    assert seconds < 3.0, f"error_rate_by_path took {seconds:.2f}s"
