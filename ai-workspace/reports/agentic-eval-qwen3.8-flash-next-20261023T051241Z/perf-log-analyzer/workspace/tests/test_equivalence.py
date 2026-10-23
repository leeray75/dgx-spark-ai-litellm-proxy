"""The optimised functions must agree with the original implementation exactly."""
import importlib.util
import math
import os

import pytest

import logstats.analyze as fast
from logstats.gen_logs import generate


def _load_reference():
    """Load tests/reference_impl.py (the pre-optimisation ground truth) by path."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference_impl.py")
    spec = importlib.util.spec_from_file_location("reference_impl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_reference = _load_reference()
ref_top_paths = _reference.top_paths
ref_p95 = _reference.p95_by_path
ref_error_rate = _reference.error_rate_by_path

SMOKE = [
    "2026-10-23T00:00:00Z GET /api/v1/res1/10 200 100ms",
    "2026-10-23T00:00:01Z GET /api/v1/res1/11 500 300ms",
    "2026-10-23T00:00:02Z GET /api/v2/res2/12 200 50ms",
    "2026-10-23T00:00:03Z POST /api/v1/res1/13 503 7ms",
    "2026-10-23T00:00:04Z PUT /health 404 1ms",
    "2026-10-23T00:00:05Z DELETE /health 200 1ms",
    "2026-10-23T00:00:06Z GET /Health/ 204 1000ms",
]


def _all_inputs():
    yield "empty", []
    yield "single", SMOKE[:1]
    yield "smoke", SMOKE
    # (n, resources): tiny resource counts force heavy path collisions, large
    # ones produce many distinct paths (both stress tie-breaking).
    for seed in (0, 1, 12345):
        for n, resources in ((1, 5), (2, 5), (50, 3), (200, 1), (2000, 40), (6000, 500)):
            key = f"gen(seed={seed},n={n},resources={resources})"
            yield key, generate(n, seed=seed, resources=resources)


@pytest.mark.parametrize("name,lines", list(_all_inputs()))
def test_top_paths_matches_reference(name, lines):
    for k in (0, 1, 3, 10, 1000, len(lines) + 5):
        assert fast.top_paths(lines, k) == ref_top_paths(lines, k), (name, k)


@pytest.mark.parametrize("name,lines", list(_all_inputs()))
def test_p95_matches_reference(name, lines):
    assert fast.p95_by_path(lines) == ref_p95(lines), name


@pytest.mark.parametrize("name,lines", list(_all_inputs()))
def test_error_rate_matches_reference(name, lines):
    assert fast.error_rate_by_path(lines) == ref_error_rate(lines), name


def test_dict_key_order_matches_reference():
    """The original built both dicts by iterating sorted(paths); keep that order."""
    lines = generate(2000, seed=3, resources=60)
    expected_order = sorted({fast.normalize(line.split()[2]) for line in lines})
    assert list(fast.p95_by_path(lines)) == expected_order
    assert list(fast.error_rate_by_path(lines)) == expected_order


def test_p95_nearest_rank_definition():
    """p95 picks sorted latencies[ceil(0.95 * n) - 1]."""
    lines = [f"2026-10-23T00:00:00Z GET /x/{i} 200 {i}ms" for i in range(1, 41)]
    expected = {p: sorted(range(1, 41))[math.ceil(0.95 * 40) - 1] for p in {"/x/:id"}}
    assert fast.p95_by_path(lines) == expected


def test_top_paths_tie_ordering():
    """Equal counts sort by path ascending, and ties beyond k are cut by that order."""
    lines = [
        "2026-10-23T00:00:00Z GET /b/1 200 1ms",
        "2026-10-23T00:00:01Z GET /a/1 200 1ms",
        "2026-10-23T00:00:02Z GET /c/1 200 1ms",
        "2026-10-23T00:00:03Z GET /a/2 200 1ms",
    ]
    assert fast.top_paths(lines, 2) == [("/a/:id", 2), ("/b/:id", 1)]
    assert fast.top_paths(lines, 4) == [("/a/:id", 2), ("/b/:id", 1), ("/c/:id", 1)]


def test_status_threshold_is_inclusive_of_500():
    lines = [
        "2026-10-23T00:00:00Z GET /x/1 499 1ms",
        "2026-10-23T00:00:01Z GET /x/2 500 1ms",
        "2026-10-23T00:00:02Z GET /x/3 502 1ms",
        "2026-10-23T00:00:03Z GET /x/4 404 1ms",
    ]
    assert fast.error_rate_by_path(lines) == {"/x/:id": 0.5}


def test_normalize_is_unchanged():
    assert fast.normalize("/api/v2/orders/1234/items") == "/api/v2/orders/:id/items"
    assert fast.normalize("/a/007/b/1c/") == "/a/:id/b/1c/"


def test_results_do_not_depend_on_memo_state():
    """Normalisation is memoised; results must be identical warm or cold."""
    lines = generate(1500, seed=11, resources=45)
    warm = (fast.top_paths(lines, 20), fast.p95_by_path(lines), fast.error_rate_by_path(lines))
    fast.normalize.cache_clear()
    cold = (fast.top_paths(lines, 20), fast.p95_by_path(lines), fast.error_rate_by_path(lines))
    assert warm == cold


def test_signatures_unchanged():
    import inspect

    assert list(inspect.signature(fast.top_paths).parameters) == ["lines", "k"]
    assert list(inspect.signature(fast.p95_by_path).parameters) == ["lines"]
    assert list(inspect.signature(fast.error_rate_by_path).parameters) == ["lines"]
    assert list(inspect.signature(fast.parse).parameters) == ["line"]
    assert list(inspect.signature(fast.normalize).parameters) == ["path"]
    assert fast.parse(SMOKE[1]) == ("GET", "/api/v1/res1/11", 500, 300)
