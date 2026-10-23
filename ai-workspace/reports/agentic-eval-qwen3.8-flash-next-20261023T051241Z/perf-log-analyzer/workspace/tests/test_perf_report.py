"""Print the report timings for a day of logs (run with ``pytest -s``).

Handy when checking that the reports still scale linearly; the hard budget is
asserted in tests/test_performance.py.
"""
import time

from logstats.analyze import error_rate_by_path, normalize, p95_by_path, top_paths
from logstats.gen_logs import generate

N_LINES = 200_000


def test_report_timings(capsys):
    lines = generate(N_LINES, seed=1)
    unique = [f"2026-10-23T00:00:00Z GET /api/v1/res{i}x/keep 200 {i % 977 + 1}ms" for i in range(N_LINES)]
    rows = []
    for fn, args in ((top_paths, (10,)), (p95_by_path, ()), (error_rate_by_path, ())):
        for label, data in (("realistic", lines), ("all-unique-paths", unique)):
            normalize.cache_clear()  # measure the cold-cache worst case
            start = time.perf_counter()
            fn(data, *args)
            rows.append(f"{fn.__name__:>20} [{label:>15}]: {time.perf_counter() - start:6.3f}s")
    print(f"\n{N_LINES} log lines, cold caches")
    print("\n".join(rows))
