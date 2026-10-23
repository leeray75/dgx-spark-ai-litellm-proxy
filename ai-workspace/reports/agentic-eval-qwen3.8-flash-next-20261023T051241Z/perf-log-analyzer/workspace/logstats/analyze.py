"""Access-log statistics.

A log line looks like::

    2026-10-23T04:05:06Z GET /api/v2/orders/1234/items 200 123ms

fields: timestamp, method, path, status, latency in ms (with the ``ms`` suffix).
Paths are normalised by replacing every all-digit segment with ``:id``, so the
line above counts towards ``/api/v2/orders/:id/items``.

All three reports read the log exactly once: every line is split and
normalised a single time and the per-path aggregates (request count, status
histogram, latency list) are accumulated in dictionaries, so their cost is
linear in the number of lines.  ``p95_by_path`` sorts each path's latencies
once instead of rescanning the whole log once per path.
"""
import math
from functools import lru_cache


def normalize(path):
    """Collapse every all-digit path segment to ``:id``."""
    return "/".join(":id" if seg.isdigit() else seg for seg in path.split("/"))


# Normalisation is pure and each raw path recurs thousands of times, so
# memoising it removes most of the per-line work.  Keys are raw paths built
# from a whitespace-free token, so they stay short and the unbounded cache
# cannot blow up.
normalize = lru_cache(maxsize=100_000)(normalize)


def parse(line):
    """Return (method, path, status, latency_ms) for one log line."""
    _ts, method, path, status, latency = line.split()
    return method, path, int(status), int(latency[:-2])


def _aggregate(lines):
    """One pass over ``lines`` -> {normalised path: [count, {status: n}, [latencies]]}.

    Each line is split and normalised exactly once.  Insertion order of the
    result is order of first appearance.
    """
    buckets = {}
    get = buckets.get
    for line in lines:
        # timestamp method path status latency_ms -- same fields as parse()
        _ts, _method, path, status, latency = line.split()
        path = normalize(path)
        status = int(status)
        bucket = get(path)
        if bucket is None:
            buckets[path] = [1, {status: 1}, [int(latency[:-2])]]
        else:
            bucket[0] += 1
            seen = bucket[1]
            seen[status] = seen.get(status, 0) + 1
            bucket[2].append(int(latency[:-2]))
    return buckets


def top_paths(lines, k):
    """The k most requested normalised paths as (path, count), by count descending then path ascending."""
    counts = [(path, count) for path, (count, _statuses, _latencies) in _aggregate(lines).items()]
    return sorted(counts, key=lambda pc: (-pc[1], pc[0]))[:k]


def p95_by_path(lines):
    """{normalised path: 95th-percentile latency}, nearest-rank: sorted latencies, element ceil(0.95 * n) - 1."""
    result = {}
    for path, (_count, _statuses, latencies) in sorted(_aggregate(lines).items()):
        latencies.sort()
        result[path] = latencies[math.ceil(0.95 * len(latencies)) - 1]
    return result


def error_rate_by_path(lines):
    """{normalised path: share of requests with status >= 500, rounded to 4 decimals}."""
    result = {}
    for path, (count, statuses, _latencies) in sorted(_aggregate(lines).items()):
        errors = sum(n for status, n in statuses.items() if status >= 500)
        result[path] = round(errors / count, 4)
    return result
