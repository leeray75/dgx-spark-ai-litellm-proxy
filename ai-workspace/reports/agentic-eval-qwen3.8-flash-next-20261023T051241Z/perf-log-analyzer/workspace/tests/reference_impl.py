"""Ground truth: the original, unoptimised implementation (kept as reference).

Used only by tests/test_equivalence.py to check that the fast version in
``logstats.analyze`` returns exactly the same values.
"""
import math


def parse(line):
    """Return (method, path, status, latency_ms) for one log line."""
    _ts, method, path, status, latency = line.split()
    return method, path, int(status), int(latency[:-2])


def normalize(path):
    return "/".join(":id" if seg.isdigit() else seg for seg in path.split("/"))


def top_paths(lines, k):
    """The k most requested normalised paths as (path, count), by count descending then path ascending."""
    counts = []
    for line in lines:
        path = normalize(parse(line)[1])
        for i, (seen, count) in enumerate(counts):
            if seen == path:
                counts[i] = (seen, count + 1)
                break
        else:
            counts.append((path, 1))
    return sorted(counts, key=lambda pc: (-pc[1], pc[0]))[:k]


def p95_by_path(lines):
    """{normalised path: 95th-percentile latency}, nearest-rank: sorted latencies, element ceil(0.95 * n) - 1."""
    result = {}
    paths = sorted({normalize(parse(line)[1]) for line in lines})
    for path in paths:
        latencies = sorted(parse(line)[3] for line in lines if normalize(parse(line)[1]) == path)
        result[path] = latencies[math.ceil(0.95 * len(latencies)) - 1]
    return result


def error_rate_by_path(lines):
    """{normalised path: share of requests with status >= 500, rounded to 4 decimals}."""
    result = {}
    for path in sorted({normalize(parse(line)[1]) for line in lines}):
        statuses = [parse(line)[2] for line in lines if normalize(parse(line)[1]) == path]
        result[path] = round(sum(1 for s in statuses if s >= 500) / len(statuses), 4)
    return result
