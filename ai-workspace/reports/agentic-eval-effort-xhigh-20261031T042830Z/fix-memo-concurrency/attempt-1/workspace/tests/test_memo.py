"""Tests for :class:`fetcher.memo.Memo`, in particular its threading guarantees."""
import inspect
import sys
import threading
import time

import pytest

from fetcher.memo import Memo

MEMO_FILE = inspect.getsourcefile(Memo)


def test_caches_value():
    calls = []
    memo = Memo(lambda k: calls.append(k) or k * 2)
    assert memo.get(3) == 6
    assert memo.get(3) == 6
    assert calls == [3]
    assert memo.stats() == {"hits": 1, "misses": 1, "loads": 1}


# ---------------------------------------------------------------- helpers


class Runner:
    """Run ``target()`` in N threads; surface worker exceptions on join()."""

    def __init__(self, n, target, daemon=True):
        self.errors = []
        self._lock = threading.Lock()
        self.threads = [
            threading.Thread(target=self._run, args=(target, i), daemon=daemon)
            for i in range(n)
        ]

    def _run(self, target, index):
        try:
            target(index)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the main thread
            with self._lock:
                self.errors.append(exc)

    def start(self):
        for t in self.threads:
            t.start()
        return self

    def join(self, timeout=10):
        for t in self.threads:
            t.join(timeout)
            assert not t.is_alive(), "a worker thread is still blocked"
        if self.errors:
            raise self.errors[0]


class Barrier:
    """Rendez-vous for a known number of threads (Condition-based)."""

    def __init__(self, parties, timeout=10):
        self.parties = parties
        self.timeout = timeout
        self.count = 0
        self.generation = 0
        self.cond = threading.Condition()

    def wait(self):
        with self.cond:
            self.count += 1
            generation = self.generation
            if self.count >= self.parties:
                self.generation += 1
                self.count = 0
                self.cond.notify_all()
            else:
                assert self.cond.wait_for(
                    lambda: self.generation != generation, self.timeout
                ), "barrier timed out: not all loaders ran at once"


def inside_get(threads):
    """How many threads are currently parked inside ``Memo.get`` (best effort).

    Used to make sure the threads under test really pile onto an in-flight load
    instead of arriving after it finished.
    """
    idents = {t.ident for t in threads}
    frames = sys._current_frames()
    parked = 0
    for ident in idents:
        frame = frames.get(ident)
        while frame is not None:
            if (
                frame.f_code.co_filename == MEMO_FILE
                and frame.f_code.co_name == "get"
            ):
                parked += 1
                break
            frame = frame.f_back
    return parked


def wait_for_inside_get(threads, count, timeout=10):
    """Wait until at least ``count`` of ``threads`` are inside ``Memo.get``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if inside_get(threads) >= count:
            return True
        time.sleep(0.005)
    return False


# ------------------------------------------------- one load per key at a time


def test_concurrent_gets_for_one_key_load_once():
    """Concurrent get(key) calls share a single loader run for that key."""
    n = 8
    inside_loader = threading.Event()
    release = threading.Event()
    calls = []
    calls_lock = threading.Lock()
    results = {}
    results_lock = threading.Lock()

    def loader(key):
        with calls_lock:
            calls.append(key)
        inside_loader.set()
        release.wait(10)  # hold the load open while everyone else arrives
        return key * 2

    memo = Memo(loader)

    def worker(i):
        value = memo.get(7)
        with results_lock:
            results[i] = value

    runner = Runner(n, worker).start()
    assert inside_loader.wait(10), "loader never ran"
    # While the load is still in flight, every other caller must be waiting in
    # get() - it may not start a second loader run for the same key.
    assert wait_for_inside_get(runner.threads, n)
    assert calls == [7]
    release.set()
    runner.join()

    assert set(results) == set(range(n))
    assert set(results.values()) == {14}
    assert calls == [7]  # loader ran exactly once
    # The seven callers that had to wait are misses, not hits: a hit is only a
    # get answered from the cache without waiting.
    assert memo.stats() == {"hits": 0, "misses": n, "loads": 1}

    # Values are cached forever: later gets are pure hits.
    assert memo.get(7) == 14
    assert memo.stats() == {"hits": 1, "misses": n, "loads": 1}


def test_cache_hits_and_other_keys_never_wait_for_an_inflight_load():
    """A get() answered from the cache - and a get() for a different key -
    return immediately while another key is still loading."""
    entered = threading.Event()
    release = threading.Event()

    def loader(key):
        if key == "blocked":
            entered.set()
            release.wait(10)
            return "blocked!"
        return key * 2

    memo = Memo(loader)
    assert memo.get(2) == 4  # pre-warm the cache (1 miss, 1 load)

    slow = Runner(1, lambda i: memo.get("blocked")).start()
    assert entered.wait(10)  # "blocked" is still loading

    # Threads that hit the cache, and threads loading another key, must not be
    # held up by the in-flight load of "blocked": the join() timeouts below
    # would fire if get() waited for an unrelated load.
    hot = Runner(3, lambda i: check_get(memo, 2, 4)).start()
    other = Runner(2, lambda i: check_get(memo, 5, 10)).start()
    hot.join(timeout=5)
    other.join(timeout=5)

    release.set()
    slow.join()

    stats = memo.stats()
    # 1 pre-warm + 1 blocked + 3 cache hits + 2 gets for key 5 (which may each
    # be a miss+load, or a hit if they arrive after key 5 was cached).
    assert stats["hits"] + stats["misses"] == 7
    assert stats["hits"] >= 3  # the cached gets answered without waiting
    assert 3 <= stats["loads"] <= 4  # key 5 loaded once or twice, never more
    assert stats["loads"] <= stats["misses"]


def check_get(memo, key, expected):
    """get(key) and verify the value (raises inside the worker if wrong)."""
    value = memo.get(key)
    assert value == expected, (key, value, expected)


def test_stats_do_not_block_while_a_key_is_loading():
    """stats() must not wait for an in-flight loader: the bookkeeping lock is
    never held while loader runs."""
    entered = threading.Event()
    release = threading.Event()

    def loader(key):
        entered.set()
        release.wait(10)
        return key

    memo = Memo(loader)
    loading = Runner(1, lambda i: memo.get("slow")).start()
    assert entered.wait(10)

    seen = {}
    reader = Runner(1, lambda i: seen.update(memo.stats())).start()
    reader.join(timeout=5)  # would time out if the lock were held by loader()
    assert seen == {"hits": 0, "misses": 1, "loads": 1}

    release.set()
    loading.join()
    assert memo.stats() == {"hits": 0, "misses": 1, "loads": 1}


def test_different_keys_load_in_parallel():
    """No lock shared between keys is held while loader runs."""
    n = 4
    in_loader = Barrier(n)  # passes only if all n loaders are inside loader()
    release = threading.Event()
    results = {}
    results_lock = threading.Lock()

    def loader(key):
        in_loader.wait()
        release.wait(10)
        return key * 10

    memo = Memo(loader)

    def worker(key):
        value = memo.get(key)
        with results_lock:
            results[key] = value

    runner = Runner(n, worker).start()
    release.set()
    runner.join()

    assert results == {k: k * 10 for k in range(n)}
    assert memo.stats() == {"hits": 0, "misses": n, "loads": n}


def test_loader_can_recurse_for_other_keys():
    """loader may itself call get() for a different key (nested load)."""

    def loader(key):
        if key == "a":
            return memo.get("b") + 1
        return 10

    memo = Memo(loader)
    assert memo.get("a") == 11
    assert memo.stats() == {"hits": 0, "misses": 2, "loads": 2}
    assert memo.get("a") == 11
    assert memo.get("b") == 10
    assert memo.stats() == {"hits": 2, "misses": 2, "loads": 2}


# ------------------------------------------------------------- error handling


def test_error_is_shared_and_not_cached():
    """Every caller of a failing load gets the very same exception object."""
    n = 5
    calls = []
    entered = threading.Event()
    release = threading.Event()
    boom = RuntimeError("upstream 500")
    errors = []
    errors_lock = threading.Lock()

    def loader(key):
        calls.append(key)
        entered.set()
        release.wait(10)
        raise boom

    memo = Memo(loader)

    def worker():
        try:
            memo.get("k")
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            with errors_lock:
                errors.append(exc)

    runner = Runner(n, lambda i: worker()).start()
    assert entered.wait(10)
    release.set()
    runner.join()

    assert calls == ["k"]  # loader ran once, its failure fanned out to all
    assert len(errors) == n
    assert all(exc is boom for exc in errors)
    assert memo.stats() == {"hits": 0, "misses": n, "loads": 1}


def test_waiters_on_a_failed_load_are_woken():
    """Callers that joined a load which then fails do not hang."""
    entered = threading.Event()
    release = threading.Event()
    loads = []
    loads_lock = threading.Lock()
    woken = []
    woken_lock = threading.Lock()

    def loader(key):
        with loads_lock:
            loads.append(key)
        entered.set()
        release.wait(10)
        raise ValueError("boom")

    memo = Memo(loader)

    def worker():
        try:
            memo.get("k")
        except ValueError:
            with woken_lock:
                woken.append(1)

    first = Runner(1, lambda i: worker()).start()
    assert entered.wait(10)
    late = Runner(3, lambda i: worker()).start()
    assert wait_for_inside_get(late.threads, 3)  # they are waiting on the load
    assert memo.stats()["loads"] == 1  # ... and did not call loader themselves
    release.set()
    first.join()
    late.join()

    assert loads == ["k"]
    assert len(woken) == 4
    assert memo.stats() == {"hits": 0, "misses": 4, "loads": 1}


def test_retry_after_error_calls_loader_again():
    """After a failure nothing is cached; a later get() reloads and succeeds."""
    attempts = []
    boom = RuntimeError("upstream down")

    def loader(key):
        attempts.append(key)
        if len(attempts) == 1:
            raise boom
        return key * 2

    memo = Memo(loader)
    with pytest.raises(RuntimeError) as excinfo:
        memo.get(21)
    assert excinfo.value is boom

    assert memo.get(21) == 42
    assert memo.get(21) == 42
    assert attempts == [21, 21]
    assert memo.stats() == {"hits": 1, "misses": 2, "loads": 2}


def test_no_stale_inflight_marker_after_error():
    """A failed load leaves the key free for the next caller to load."""
    state = {"fail": True}
    calls = []
    calls_lock = threading.Lock()
    gates = [threading.Event(), threading.Event()]  # hold each load open
    inside_loader = threading.Event()
    results = []
    errors = []
    lock = threading.Lock()

    def loader(key):
        with calls_lock:
            calls.append(key)
            failing = state["fail"]
            gate = gates[len(calls) - 1]
        inside_loader.set()
        gate.wait(10)  # keep the load in flight while the others arrive
        if failing:
            raise RuntimeError("nope")
        return key * 2

    memo = Memo(loader)

    def worker():
        try:
            results.append(memo.get(4))
        except RuntimeError:
            with lock:
                errors.append(1)

    failing = Runner(4, lambda i: worker()).start()
    assert inside_loader.wait(10)
    assert wait_for_inside_get(failing.threads, 4)  # all joined the one load
    gates[0].set()
    failing.join()
    assert len(errors) == 4
    assert calls == [4]  # coalesced into a single failing load
    assert memo.stats() == {"hits": 0, "misses": 4, "loads": 1}

    state["fail"] = False
    inside_loader.clear()
    retry = Runner(6, lambda i: worker()).start()
    assert inside_loader.wait(10)
    assert wait_for_inside_get(retry.threads, 6)  # one load, five waiters
    gates[1].set()
    retry.join()
    assert results == [8] * 6
    assert calls == [4, 4]
    assert memo.stats() == {"hits": 0, "misses": 10, "loads": 2}


# ------------------------------------------------------- stats exactness


def test_stats_are_exact_under_contention():
    """hits + misses == number of gets; loads == loader runs; no double loads."""
    keys = 6
    per_key = 10
    total = keys * per_key
    loaded = []
    loaded_lock = threading.Lock()

    def loader(key):
        with loaded_lock:
            loaded.append(key)
        time.sleep(0.005)  # widen the window so callers pile onto one load
        return key * 3

    memo = Memo(loader)
    outcomes = []
    outcomes_lock = threading.Lock()

    def worker(i):
        key = i % keys
        assert memo.get(key) == key * 3
        with outcomes_lock:
            outcomes.append(key)

    Runner(total, worker).start().join()

    stats = memo.stats()
    assert len(outcomes) == total
    assert stats["hits"] + stats["misses"] == total
    assert stats["loads"] == len(loaded)  # only loader() runs are counted
    assert len(set(loaded)) == keys  # every key was loaded
    assert stats["loads"] <= stats["misses"] <= total

    # Now everything is cached: total gets produce exactly total more hits.
    before = memo.stats()
    for i in range(total):
        assert memo.get(i % keys) == (i % keys) * 3
    after = memo.stats()
    assert after["loads"] == before["loads"]
    assert after["misses"] == before["misses"]
    assert after["hits"] == before["hits"] + total
