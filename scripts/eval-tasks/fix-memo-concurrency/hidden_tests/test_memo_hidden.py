import sys
import threading
import time

import pytest

from fetcher.memo import Memo


def run_threads(n, target):
    results, errors = [None] * n, [None] * n
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        try:
            results[i] = target(i)
        except BaseException as e:  # noqa: BLE001
            errors[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
        assert not t.is_alive(), "thread hung"
    return results, errors


# Races can pass by luck on a broken implementation, so the race tests repeat.
@pytest.mark.parametrize("round_", range(3))
def test_single_load_for_concurrent_callers(round_):
    calls = []
    lock = threading.Lock()

    def loader(key):
        with lock:
            calls.append(key)
        time.sleep(0.2)
        return f"value-{key}"

    memo = Memo(loader)
    results, errors = run_threads(32, lambda i: memo.get("k"))
    assert errors == [None] * 32
    assert results == ["value-k"] * 32
    assert calls == ["k"]
    s = memo.stats()
    assert s["loads"] == 1 and s["hits"] + s["misses"] == 32 and s["misses"] >= 1


def test_different_keys_load_in_parallel():
    memo = Memo(lambda key: time.sleep(0.4) or key)
    start = time.perf_counter()
    results, errors = run_threads(8, lambda i: memo.get(i))
    elapsed = time.perf_counter() - start
    assert errors == [None] * 8 and results == list(range(8))
    assert elapsed < 1.5, f"keys did not load in parallel ({elapsed:.2f}s)"


def test_loader_may_call_get_for_other_keys():
    memo = None

    def loader(key):
        return 1 if key == 0 else memo.get(key - 1) + 1

    memo = Memo(loader)
    results, errors = run_threads(1, lambda i: memo.get(5))
    assert errors == [None] and results == [6]


def test_exception_shared_not_cached_then_retried():
    attempts = []
    lock = threading.Lock()

    def loader(key):
        with lock:
            attempts.append(key)
            n = len(attempts)
        time.sleep(0.2)
        if n == 1:
            raise ValueError("upstream down")
        return "ok"

    memo = Memo(loader)
    results, errors = run_threads(16, lambda i: memo.get("x"))
    assert all(isinstance(e, ValueError) for e in errors), errors
    assert len(attempts) == 1
    assert memo.get("x") == "ok"
    assert len(attempts) == 2
    assert memo.stats()["loads"] == 2


def test_stats_exact_under_contention():
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for _ in range(5):
            memo = Memo(lambda k: k)
            memo.get("hot")
            run_threads(16, lambda i: [memo.get("hot") for _ in range(2000)])
            assert memo.stats() == {"hits": 32000, "misses": 1, "loads": 1}
            # misses/loads race too: many threads miss the same cold key at once
            cold = Memo(lambda k: time.sleep(0.05) or k)
            run_threads(16, lambda i: [cold.get(j) for j in range(20)])
            s = cold.stats()
            assert s["loads"] == 20 and s["hits"] + s["misses"] == 320, s
    finally:
        sys.setswitchinterval(old)


def test_many_keys_mixed_load():
    calls = {}
    lock = threading.Lock()

    def loader(key):
        with lock:
            calls[key] = calls.get(key, 0) + 1
        time.sleep(0.01)
        return key * key

    memo = Memo(loader)
    results, errors = run_threads(24, lambda i: [memo.get(j % 10) for j in range(i, i + 50)])
    assert errors == [None] * 24
    assert all(r == [(j % 10) ** 2 for j in range(i, i + 50)] for i, r in enumerate(results))
    assert calls == {k: 1 for k in range(10)}
    s = memo.stats()
    assert s["loads"] == 10 and s["hits"] + s["misses"] == 24 * 50
