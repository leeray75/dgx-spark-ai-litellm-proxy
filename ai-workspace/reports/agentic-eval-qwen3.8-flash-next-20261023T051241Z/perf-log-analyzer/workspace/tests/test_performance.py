"""Performance: each report must handle a day of logs (200k lines) in well under 2s."""
import time

import pytest

from logstats.analyze import error_rate_by_path, normalize, p95_by_path, top_paths
from logstats.gen_logs import generate

N_LINES = 200_000
LIMIT_SECONDS = 2.0


def _distinct_path_lines(n):
    """Worst case for path memoisation: every line has its own raw path."""
    return [f"2026-10-23T00:00:00Z GET /api/v1/res{i}x/keep 200 {i % 977 + 1}ms" for i in range(n)]


@pytest.fixture(scope="module")
def lines():
    return generate(N_LINES, seed=1)


@pytest.fixture(scope="module")
def unique_lines():
    return _distinct_path_lines(N_LINES)


def _elapsed(fn, *args):
    normalize.cache_clear()  # measure the cold-cache worst case, not a warmed run
    start = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - start, result


@pytest.mark.parametrize("dataset", ("lines", "unique_lines"))
def test_top_paths_is_fast(dataset, request):
    lines = request.getfixturevalue(dataset)
    elapsed, result = _elapsed(top_paths, lines, 10)
    assert elapsed < LIMIT_SECONDS, f"top_paths took {elapsed:.3f}s for {N_LINES} lines"
    assert len(result) == 10


@pytest.mark.parametrize("dataset", ("lines", "unique_lines"))
def test_p95_by_path_is_fast(dataset, request):
    lines = request.getfixturevalue(dataset)
    elapsed, result = _elapsed(p95_by_path, lines)
    assert elapsed < LIMIT_SECONDS, f"p95_by_path took {elapsed:.3f}s for {N_LINES} lines"
    assert len(result) > 100


@pytest.mark.parametrize("dataset", ("lines", "unique_lines"))
def test_error_rate_by_path_is_fast(dataset, request):
    lines = request.getfixturevalue(dataset)
    elapsed, result = _elapsed(error_rate_by_path, lines)
    assert elapsed < LIMIT_SECONDS, f"error_rate_by_path took {elapsed:.3f}s for {N_LINES} lines"
    assert len(result) > 100
