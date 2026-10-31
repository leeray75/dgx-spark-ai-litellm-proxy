"""Access-log statistics.

A log line looks like::

    2026-10-23T04:05:06Z GET /api/v2/orders/1234/items 200 123ms

fields: timestamp, method, path, status, latency in ms (with the ``ms`` suffix).
Paths are normalised by replacing every all-digit segment with ``:id``, so the
line above counts towards ``/api/v2/orders/:id/items``.
"""
import math
from functools import lru_cache


def parse(line):
    """Return (method, path, status, latency_ms) for one log line."""
    _ts, method, path, status, latency = line.split()
    return method, path, int(status), int(latency[:-2])


@lru_cache(maxsize=None)
def normalize(path):
    return "/".join(":id" if seg.isdigit() else seg for seg in path.split("/"))


def top_paths(lines, k):
    """The k most requested normalised paths as (path, count), by count descending then path ascending."""
    counts = {}
    for line in lines:
        path = normalize(parse(line)[1])
        counts[path] = counts.get(path, 0) + 1
    return sorted(counts.items(), key=lambda pc: (-pc[1], pc[0]))[:k]


def p95_by_path(lines):
    """{normalised path: 95th-percentile latency}, nearest-rank: sorted latencies, element ceil(0.95 * n) - 1."""
    latencies = {}
    for line in lines:
        _, path, _, latency = parse(line)
        latencies.setdefault(normalize(path), []).append(latency)
    return {
        path: sorted(vals)[math.ceil(0.95 * len(vals)) - 1]
        for path, vals in sorted(latencies.items())
    }


def error_rate_by_path(lines):
    """{normalised path: share of requests with status >= 500, rounded to 4 decimals}."""
    totals = {}
    errors = {}
    for line in lines:
        _, path, status, _ = parse(line)
        path = normalize(path)
        totals[path] = totals.get(path, 0) + 1
        if status >= 500:
            errors[path] = errors.get(path, 0) + 1
    return {path: round(errors.get(path, 0) / totals[path], 4) for path in sorted(totals)}
