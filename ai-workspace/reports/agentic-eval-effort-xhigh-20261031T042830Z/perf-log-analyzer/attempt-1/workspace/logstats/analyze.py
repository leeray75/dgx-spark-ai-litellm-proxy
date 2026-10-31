"""Access-log statistics.

A log line looks like::

    2026-10-23T04:05:06Z GET /api/v2/orders/1234/items 200 123ms

fields: timestamp, method, path, status, latency in ms (with the ``ms`` suffix).
Paths are normalised by replacing every all-digit segment with ``:id``, so the
line above counts towards ``/api/v2/orders/:id/items``.
"""
import math


def parse(line):
    """Return (method, path, status, latency_ms) for one log line."""
    _ts, method, path, status, latency = line.split()
    return method, path, int(status), int(latency[:-2])


def normalize(path):
    return "/".join(":id" if seg.isdigit() else seg for seg in path.split("/"))


def _normalizer():
    """Return a memoised normalize() callable (raw paths repeat heavily in logs)."""
    cache = {}

    def fast(path):
        try:
            return cache[path]
        except KeyError:
            cache[path] = norm = normalize(path)
            return norm

    return fast


def top_paths(lines, k):
    """The k most requested normalised paths as (path, count), by count descending then path ascending."""
    fast = _normalizer()
    counts = {}
    for line in lines:
        path = fast(parse(line)[1])
        counts[path] = counts.get(path, 0) + 1
    return sorted(counts.items(), key=lambda pc: (-pc[1], pc[0]))[:k]


def p95_by_path(lines):
    """{normalised path: 95th-percentile latency}, nearest-rank: sorted latencies, element ceil(0.95 * n) - 1."""
    fast = _normalizer()
    latencies = {}
    for line in lines:
        path, latency = parse(line)[1], parse(line)[3]
        latencies.setdefault(fast(path), []).append(latency)
    result = {}
    for path in sorted(latencies):
        values = sorted(latencies[path])
        result[path] = values[math.ceil(0.95 * len(values)) - 1]
    return result


def error_rate_by_path(lines):
    """{normalised path: share of requests with status >= 500, rounded to 4 decimals}."""
    fast = _normalizer()
    errors, totals = {}, {}
    for line in lines:
        _, raw, status, _ = parse(line)
        path = fast(raw)
        try:
            totals[path] += 1
        except KeyError:
            errors[path] = 0
            totals[path] = 1
        if status >= 500:
            errors[path] += 1
    return {path: round(errors[path] / totals[path], 4) for path in sorted(totals)}
