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
