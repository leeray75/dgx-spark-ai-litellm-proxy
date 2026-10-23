import threading
import time

import pytest

from fetcher.memo import Memo


def test_caches_value():
    calls = []
    memo = Memo(lambda k: calls.append(k) or k * 2)
    assert memo.get(3) == 6
    assert memo.get(3) == 6
    assert calls == [3]
    assert memo.stats() == {"hits": 1, "misses": 1, "loads": 1}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

TIMEOUT = 10.0


class Rendezvous:
    """Like ``threading.Barrier`` but never blocks forever when a member dies."""

    def __init__(self, n):
        self._left = n
        self._cond = threading.Condition()

    def wait(self, timeout=TIMEOUT):
        with self._cond:
            self._left -= 1
            if self._left == 0:
                self._cond.notify_all()
            return self._cond.wait_for(lambda: self._left == 0, timeout)


def wait_until(predicate, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return False


def parked_waiters(memo, key):
    """How many get() calls are currently waiting on the in-flight load of key."""
    with memo.lock:
        load = memo._inflight.get(key)
        return load.waiters if load is not None else 0


class Workers:
    """Run ``fn(i)`` in n threads that all start at the same instant."""

    def __init__(self, n, fn):
        self.n = n
        self.results = [None] * n
        self.errors = [None] * n
        self._gate = Rendezvous(n)
        self._threads = [
            threading.Thread(target=self._run, args=(i, fn), name="worker-%d" % i)
            for i in range(n)
        ]

    def _run(self, i, fn):
        try:
            assert self._gate.wait(), "a worker never reached the start line"
            self.results[i] = fn(i)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            self.errors[i] = exc

    def start(self):
        for t in self._threads:
            t.start()
        return self

    def join(self, timeout=30.0):
        for t in self._threads:
            t.join(timeout)
        alive = [t.name for t in self._threads if t.is_alive()]
        assert not alive, "worker thread(s) hung: %s" % alive


def run_threads(n, fn):
    workers = Workers(n, fn).start()
    workers.join()
    return workers.results, workers.errors


# ---------------------------------------------------------------------------
# single-threaded semantics
# ---------------------------------------------------------------------------


def test_stats_are_exact_for_plain_use():
    calls = []
    memo = Memo(lambda k: calls.append(k) or k + 1)
    assert [memo.get(k) for k in (1, 2, 3)] == [2, 3, 4]
    assert [memo.get(k) for k in (1, 2, 1)] == [2, 3, 2]
    assert memo.stats() == {"hits": 3, "misses": 3, "loads": 3}
    assert calls == [1, 2, 3]


def test_falsy_values_are_cached_like_any_other_value():
    calls = []
    memo = Memo(lambda k: calls.append(k) or 0)
    assert memo.get("a") == 0
    assert memo.get("a") == 0
    memo.get("a")
    assert calls == ["a"], "a cached falsy value was reloaded"
    assert memo.stats() == {"hits": 2, "misses": 1, "loads": 1}

    memo2 = Memo(lambda k: None)
    assert [memo2.get("x") for _ in range(3)] == [None, None, None]
    assert memo2.stats() == {"hits": 2, "misses": 1, "loads": 1}


def test_loader_exception_propagates_and_is_not_cached():
    calls = []

    def loader(key):
        calls.append(key)
        raise ValueError("boom %s" % key)

    memo = Memo(loader)
    for _ in range(3):
        with pytest.raises(ValueError) as info:
            memo.get("a")
        assert str(info.value) == "boom a"
    assert calls == ["a", "a", "a"]
    assert memo.stats() == {"hits": 0, "misses": 3, "loads": 3}


def test_recursive_same_key_get_raises_instead_of_deadlocking():
    def loader(key):
        return memo.get(key)  # would wait forever on its own load

    memo = Memo(loader)
    with pytest.raises(RuntimeError):
        memo.get("a")
    # The abandoned load must not stay in flight: a later get() retries normally.
    memo.loader = lambda key: "ok"
    assert memo.get("a") == "ok"
    with memo.lock:
        assert memo._inflight == {}


# ---------------------------------------------------------------------------
# concurrency: one loader call per key, everyone else waits
# ---------------------------------------------------------------------------


def test_concurrent_gets_on_one_key_load_once_and_all_waiters_share_result():
    calls = []
    loader_started = threading.Event()
    release = threading.Event()
    n_threads = 12

    def loader(key):
        calls.append(key)
        loader_started.set()
        assert release.wait(TIMEOUT), "loader was never released"
        return "value-%s" % key

    memo = Memo(loader)

    # Watchdog: keep the load open until every other thread has parked on it, so
    # none can slip through and be served from the (still empty) cache.
    problems = []

    def observe():
        try:
            if not loader_started.wait(TIMEOUT):
                problems.append("loader never started")
                return
            if not wait_until(lambda: parked_waiters(memo, "k") == n_threads - 1):
                problems.append(
                    "only %d of %d threads joined the in-flight load"
                    % (parked_waiters(memo, "k"), n_threads - 1)
                )
        finally:
            release.set()

    watcher = threading.Thread(target=observe, name="watchdog")
    watcher.start()
    workers = Workers(n_threads, lambda i: memo.get("k")).start()
    workers.join()
    watcher.join(30)

    assert not watcher.is_alive(), "watchdog hung"
    assert problems == []
    assert workers.errors == [None] * n_threads
    assert len(calls) == 1, "loader ran %d times for one key" % len(calls)
    assert workers.results == ["value-k"] * n_threads
    # The 11 waiters are misses, not hits: they were not answered from the cache.
    assert memo.stats() == {"hits": 0, "misses": n_threads, "loads": 1}
    # ... and once cached, it is a plain hit.
    assert memo.get("k") == "value-k"
    assert memo.stats() == {"hits": 1, "misses": n_threads, "loads": 1}


def test_get_during_a_load_joins_that_load_instead_of_refetching():
    first_started = threading.Event()
    keep_loading = threading.Event()
    calls = []
    box = []

    def loader(key):
        calls.append(key)
        first_started.set()
        assert keep_loading.wait(TIMEOUT), "loader was never released"
        return object()

    memo = Memo(loader)
    leader = threading.Thread(target=lambda: box.append(memo.get("k")), name="leader")
    leader.start()
    assert first_started.wait(TIMEOUT), "loader never started"

    workers = Workers(4, lambda i: memo.get("k")).start()
    assert wait_until(lambda: parked_waiters(memo, "k") == 4), "waiters never parked"
    assert calls == ["k"], "a second loader call slipped in while one was running"

    keep_loading.set()
    workers.join()
    leader.join(30)
    assert not leader.is_alive(), "leader hung"

    value = box[0]
    assert value is not None
    assert workers.errors == [None] * 4
    assert all(result is value for result in workers.results)
    assert memo.stats() == {"hits": 0, "misses": 5, "loads": 1}


def test_stats_is_exact_and_never_blocks_while_a_load_is_in_flight():
    loader_started = threading.Event()
    release = threading.Event()

    def loader(key):
        loader_started.set()
        assert release.wait(TIMEOUT), "loader was never released"
        return "v"

    memo = Memo(loader)
    leader = threading.Thread(target=lambda: memo.get("k"), name="leader")
    leader.start()
    assert loader_started.wait(TIMEOUT), "loader never started"

    # stats() must not block on the running loader (no lock shared with it) and
    # must already account for the load that is under way.
    observed = []

    def poll_stats():
        observed.append(memo.stats())

    poller = threading.Thread(target=poll_stats, name="poller")
    poller.start()
    poller.join(5)
    assert not poller.is_alive(), "stats() blocked while loader() was running"
    assert observed == [{"hits": 0, "misses": 1, "loads": 1}]

    release.set()
    leader.join(30)
    assert not leader.is_alive(), "leader hung"
    assert memo.stats() == {"hits": 0, "misses": 1, "loads": 1}


def test_distinct_keys_load_in_parallel():
    n_keys = 8
    gate = Rendezvous(n_keys)
    reached = []
    memo = None

    def loader(key):
        reached.append(key)
        # Passes only if all loaders are inside loader() at the same time, i.e.
        # no lock shared between keys is held while loader runs.
        assert gate.wait(), "loaders serialised: %s" % (sorted(reached),)
        return key * 10

    memo = Memo(loader)
    results, errors = run_threads(n_keys, lambda i: memo.get(i))

    assert errors == [None] * n_keys
    assert results == [i * 10 for i in range(n_keys)]
    assert sorted(reached) == list(range(n_keys))
    assert memo.stats() == {"hits": 0, "misses": n_keys, "loads": n_keys}


def test_loader_can_get_other_keys_without_deadlocking():
    keys = ["a", "b", "c", "d", "e", "f"]
    loaded = []
    memo = None

    def loader(key):
        i = keys.index(key)
        if i + 1 < len(keys):
            # Nested get() for a *different* key while this load is in flight.
            assert memo.get(keys[i + 1]) == keys[i + 1].upper()
        loaded.append(key)
        return key.upper()

    memo = Memo(loader)
    results, errors = run_threads(len(keys), lambda i: memo.get(keys[i]))

    assert errors == [None] * len(keys)
    assert results == [k.upper() for k in keys]
    assert sorted(loaded) == keys
    # Each key is loaded exactly once even though the loaders triggered each other.
    assert memo.stats()["loads"] == len(keys)


def test_concurrent_failure_shares_the_exception_and_caches_nothing():
    calls = []
    n_threads = 10
    loader_started = threading.Event()
    release = threading.Event()
    boom = RuntimeError("upstream 503")

    def loader(key):
        calls.append(key)
        loader_started.set()
        assert release.wait(TIMEOUT), "loader was never released"
        raise boom

    memo = Memo(loader)

    problems = []

    def observe():
        try:
            if not loader_started.wait(TIMEOUT):
                problems.append("loader never started")
                return
            if not wait_until(lambda: parked_waiters(memo, "k") == n_threads - 1):
                problems.append(
                    "only %d of %d threads joined the failing load"
                    % (parked_waiters(memo, "k"), n_threads - 1)
                )
        finally:
            release.set()

    watcher = threading.Thread(target=observe, name="watchdog")
    watcher.start()
    workers = Workers(n_threads, lambda i: memo.get("k")).start()
    workers.join()
    watcher.join(30)
    assert not watcher.is_alive(), "watchdog hung"
    assert problems == []

    assert workers.results == [None] * n_threads
    assert len(workers.errors) == n_threads
    assert all(exc is boom for exc in workers.errors), "waiters got a different error"
    assert len(calls) == 1, "loader ran %d times for one key" % len(calls)
    assert memo.stats() == {"hits": 0, "misses": n_threads, "loads": 1}
    with memo.lock:
        assert memo._inflight == {}, "failed load stayed in flight"
        assert memo.data == {}, "a failure was cached"

    # Nothing was cached and nothing stayed in flight: the next get() retries.
    memo.loader = lambda key: "recovered"
    results, errors = run_threads(n_threads, lambda i: memo.get("k"))
    assert errors == [None] * n_threads
    assert results == ["recovered"] * n_threads
    stats = memo.stats()
    assert stats["loads"] == 2, "the failed load was not retried"
    assert stats["hits"] + stats["misses"] == 2 * n_threads, "get() miscounted"
    # The 10 failed gets were misses; of the retrying 10, at least the one that
    # started the load is a miss and the rest may be served from the cache.
    assert n_threads + 1 <= stats["misses"] <= 2 * n_threads


def test_failed_load_and_late_arrival_do_not_publish_a_stale_value():
    calls = []
    first_started = threading.Event()
    hold = threading.Event()

    def loader(key):
        calls.append(key)
        if len(calls) == 1:
            first_started.set()
            assert hold.wait(TIMEOUT), "loader was never released"
            raise ValueError("nope")
        return "fresh"

    memo = Memo(loader)
    outcomes = []

    def call_get():
        try:
            outcomes.append(("value", memo.get("k")))
        except BaseException as exc:  # noqa: BLE001 - inspected below
            outcomes.append(("error", exc))

    leader = threading.Thread(target=call_get, name="leader")
    leader.start()
    assert first_started.wait(TIMEOUT), "loader never started"

    joiner = threading.Thread(target=call_get, name="joiner")
    joiner.start()
    assert wait_until(lambda: parked_waiters(memo, "k") == 1), "joiner never parked"

    hold.set()
    for thread in (leader, joiner):
        thread.join(30)
        assert not thread.is_alive(), "%s hung" % thread.name

    assert [kind for kind, _ in outcomes] == ["error", "error"]
    assert all(isinstance(outcome, ValueError) for _, outcome in outcomes)
    assert memo.get("k") == "fresh"  # no stale value, and the load was retried
    assert calls == ["k", "k"]
    assert memo.stats() == {"hits": 0, "misses": 3, "loads": 2}


def test_mixed_keys_and_repeated_access_keep_stats_exact():
    keys = list(range(12))
    n_threads = 48
    gate = Rendezvous(n_threads)

    def loader(key):
        return key * key if isinstance(key, int) else key[1]

    memo = Memo(loader)

    def worker(i):
        key = keys[i % len(keys)]
        assert gate.wait(), "threads did not overlap"
        value = memo.get(key)
        for _ in range(3):  # hammer the cache to accumulate hits
            assert memo.get(key) == value
        assert memo.get(("uncached", i)) == i
        return value

    results, errors = run_threads(n_threads, worker)

    assert errors == [None] * n_threads
    assert results == [keys[i % len(keys)] ** 2 for i in range(n_threads)]
    stats = memo.stats()
    # Each of the 12 shared keys and of the 48 per-thread keys is loaded once.
    assert stats["loads"] == len(keys) + n_threads
    # Every get() (4 shared + 1 unique per thread) is counted exactly once.
    assert stats["hits"] + stats["misses"] == 5 * n_threads
    # Once a get() has returned a value it is cached forever, so each thread's
    # last three gets of its shared key are hits; the first one is a hit only if
    # another thread had already published it.  The unique keys are always misses.
    assert 3 * n_threads <= stats["hits"] <= 4 * n_threads
    assert stats["misses"] == 5 * n_threads - stats["hits"]
    assert stats["misses"] >= stats["loads"], "a load must be caused by a miss"
