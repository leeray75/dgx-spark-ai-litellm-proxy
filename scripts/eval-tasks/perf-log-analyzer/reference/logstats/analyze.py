"""Access-log statistics (reference solution: one pass per call, dict-based)."""
import math


def parse(line):
    """Return (method, path, status, latency_ms) for one log line."""
    _ts, method, path, status, latency = line.split()
    return method, path, int(status), int(latency[:-2])


def normalize(path):
    return "/".join(":id" if seg.isdigit() else seg for seg in path.split("/"))


def _grouped(lines):
    cache, groups = {}, {}
    for line in lines:
        _ts, _method, path, status, latency = line.split()
        norm = cache.get(path)
        if norm is None:
            norm = cache[path] = normalize(path)
        groups.setdefault(norm, []).append((int(status), int(latency[:-2])))
    return groups


def top_paths(lines, k):
    """The k most requested normalised paths as (path, count), by count descending then path ascending."""
    counts = {p: len(v) for p, v in _grouped(lines).items()}
    return sorted(counts.items(), key=lambda pc: (-pc[1], pc[0]))[:k]


def p95_by_path(lines):
    """{normalised path: 95th-percentile latency}, nearest-rank: sorted latencies, element ceil(0.95 * n) - 1."""
    result = {}
    for path, rows in sorted(_grouped(lines).items()):
        latencies = sorted(lat for _s, lat in rows)
        result[path] = latencies[math.ceil(0.95 * len(latencies)) - 1]
    return result


def error_rate_by_path(lines):
    """{normalised path: share of requests with status >= 500, rounded to 4 decimals}."""
    return {path: round(sum(1 for s, _l in rows if s >= 500) / len(rows), 4)
            for path, rows in sorted(_grouped(lines).items())}
