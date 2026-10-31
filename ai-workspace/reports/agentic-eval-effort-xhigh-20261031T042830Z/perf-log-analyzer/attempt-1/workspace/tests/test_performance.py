import time

from logstats.analyze import error_rate_by_path, p95_by_path, top_paths
from logstats.gen_logs import generate

N = 200_000
LIMIT = 2.0  # seconds per function on 200,000 lines


def _timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - start, result


def test_top_paths_fast():
    lines = generate(N, seed=42)
    elapsed, result = _timed(top_paths, lines, 20)
    assert elapsed < LIMIT, f"top_paths took {elapsed:.2f}s"
    assert len(result) == 20


def test_p95_by_path_fast():
    lines = generate(N, seed=42)
    elapsed, result = _timed(p95_by_path, lines)
    assert elapsed < LIMIT, f"p95_by_path took {elapsed:.2f}s"
    assert result  # non-empty


def test_error_rate_by_path_fast():
    lines = generate(N, seed=42)
    elapsed, result = _timed(error_rate_by_path, lines)
    assert elapsed < LIMIT, f"error_rate_by_path took {elapsed:.2f}s"
    assert result and all(0.0 <= v <= 1.0 for v in result.values())
