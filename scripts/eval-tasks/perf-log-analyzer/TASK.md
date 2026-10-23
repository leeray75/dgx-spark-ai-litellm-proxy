# Performance: the access-log report takes forever

Ops runs `logstats.analyze` on a day of access logs (about 200,000 lines) and it never finishes.
Make `top_paths`, `p95_by_path` and `error_rate_by_path` fast: **each must finish in under 2 seconds
on 200,000 lines** (2 CPUs).

Their results must stay **exactly** the same as today for every input, including tie ordering,
the percentile definition and rounding (the docstrings describe them; the current code is the
ground truth). Function names and signatures must not change.

`logstats/gen_logs.py` generates realistic test data (`generate(n, seed)` returns a list of lines).
Keep the existing tests passing; add a performance test if you like.
