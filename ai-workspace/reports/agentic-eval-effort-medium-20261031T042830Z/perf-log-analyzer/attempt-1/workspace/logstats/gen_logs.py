"""Generate synthetic access-log lines: generate(n, seed) -> list[str]."""
import random

METHODS = ["GET", "GET", "GET", "POST", "PUT", "DELETE"]
STATUSES = [200] * 90 + [201, 204, 301, 400, 401, 404, 404, 500, 502, 503]


def generate(n, seed=0, resources=1500):
    rng = random.Random(seed)
    lines = []
    for i in range(n):
        r = int(rng.paretovariate(1.2)) % resources
        path = f"/api/v{rng.randint(1, 2)}/res{r}/{rng.randint(1, 99999)}"
        if rng.random() < 0.3:
            path += f"/items/{rng.randint(1, 500)}"
        ts = f"2026-10-23T{i // 3600 % 24:02d}:{i // 60 % 60:02d}:{i % 60:02d}Z"
        lines.append(f"{ts} {rng.choice(METHODS)} {path} {rng.choice(STATUSES)} {int(rng.expovariate(1 / 80)) + 1}ms")
    return lines
