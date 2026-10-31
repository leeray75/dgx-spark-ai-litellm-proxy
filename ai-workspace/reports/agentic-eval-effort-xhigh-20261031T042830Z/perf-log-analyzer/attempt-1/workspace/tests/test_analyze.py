from logstats.analyze import error_rate_by_path, p95_by_path, top_paths

LINES = [
    "2026-10-23T00:00:00Z GET /api/v1/res1/10 200 100ms",
    "2026-10-23T00:00:01Z GET /api/v1/res1/11 500 300ms",
    "2026-10-23T00:00:02Z GET /api/v1/res2/12 200 50ms",
]


def test_top_paths():
    assert top_paths(LINES, 5) == [("/api/v1/res1/:id", 2), ("/api/v1/res2/:id", 1)]


def test_p95():
    assert p95_by_path(LINES) == {"/api/v1/res1/:id": 300, "/api/v1/res2/:id": 50}


def test_error_rate():
    assert error_rate_by_path(LINES) == {"/api/v1/res1/:id": 0.5, "/api/v1/res2/:id": 0.0}


def test_tie_ordering_and_edge_cases():
    lines = [
        "2026-10-23T00:00:00Z GET /a/1 500 10ms",
        "2026-10-23T00:00:01Z GET /b/2 200 20ms",
    ]
    # equal counts -> path ascending
    assert top_paths(lines, 5) == [("/a/:id", 1), ("/b/:id", 1)]
    # k larger than the number of paths, k == 0, empty input
    assert top_paths(lines, 10)[1] == ("/b/:id", 1)
    assert top_paths(lines, 0) == []
    assert top_paths([], 3) == []
    assert p95_by_path([]) == {}
    assert error_rate_by_path([]) == {}
    # keys are returned in sorted order
    assert list(error_rate_by_path(lines)) == ["/a/:id", "/b/:id"]
    assert list(p95_by_path(lines)) == ["/a/:id", "/b/:id"]
