import threading

from fetcher.memo import Memo


def test_caches_value():
    calls = []
    memo = Memo(lambda k: calls.append(k) or k * 2)
    assert memo.get(3) == 6
    assert memo.get(3) == 6
    assert calls == [3]
    assert memo.stats() == {"hits": 1, "misses": 1, "loads": 1}


def _start_owner(memo, key, slot, load_entered=None):
    """Start one thread calling memo.get(key); if load_entered is given,
    wait until the loader is actually running before returning."""
    def owner():
        try:
            slot["result"] = memo.get(key)
        except BaseException as exc:  # noqa: BLE001 - checked in main thread
            slot["error"] = exc

    t = threading.Thread(target=owner)
    t.start()
    if load_entered is not None:
        assert load_entered.wait(10), "loader never started"
    return t


def _start_waiters(memo, key, n, slots):
    """Start n threads all calling memo.get(key). By the time _start_owner
    returned with load_entered set, the load is registered in-flight, so
    every one of these threads must become a waiter."""
    threads = []
    for i in range(n):
        def waiter(i=i):
            try:
                slots[i]["result"] = memo.get(key)
            except BaseException as exc:  # noqa: BLE001 - checked in main thread
                slots[i]["error"] = exc

        t = threading.Thread(target=waiter)
        threads.append(t)
        t.start()
    return threads


def _join(threads, timeout=10):
    for t in threads:
        t.join(timeout)
    assert not any(t.is_alive() for t in threads), "thread hung / deadlock"


def test_concurrent_gets_load_key_once():
    """While a key is being loaded, concurrent get() calls for that key wait
    for the in-flight load: the loader runs exactly once, every caller gets
    the value, and stats add up."""
    calls = []
    release = threading.Event()
    load_entered = threading.Event()

    def loader(key):
        calls.append(key)
        load_entered.set()
        release.wait(10)  # hold the load while waiters pile up
        return key * 2

    memo = Memo(loader)
    n = 12
    owner_slot = {}
    owner = _start_owner(memo, 5, owner_slot, load_entered)
    slots = [{} for _ in range(n)]
    waiters = _start_waiters(memo, 5, n, slots)
    release.set()
    _join([owner] + waiters)

    assert "error" not in owner_slot
    assert owner_slot["result"] == 10
    assert all(s.get("result") == 10 and "error" not in s for s in slots)
    assert calls == [5]  # loader ran exactly once
    st = memo.stats()
    assert st == {"hits": 0, "misses": n + 1, "loads": 1}
    # after completion, subsequent gets are hits, loader is not called again
    assert memo.get(5) == 10
    assert memo.stats() == {"hits": 1, "misses": n + 1, "loads": 1}


def test_concurrent_error_shared_by_all_waiters():
    """A failing loader: the owner and every waiter get the same exception
    object, nothing is cached, and a later get retries the loader."""
    calls = []
    release = threading.Event()
    load_entered = threading.Event()

    class Boom(Exception):
        pass

    def loader(key):
        calls.append(key)
        load_entered.set()
        release.wait(10)
        raise Boom(key)

    memo = Memo(loader)
    n = 8
    owner_slot = {}
    owner = _start_owner(memo, "x", owner_slot, load_entered)
    slots = [{} for _ in range(n)]
    waiters = _start_waiters(memo, "x", n, slots)
    release.set()
    _join([owner] + waiters)

    assert isinstance(owner_slot.get("error"), Boom)
    errors = [s.get("error") for s in slots]
    assert all(isinstance(e, Boom) for e in errors)
    # every caller gets *the same* exception object
    assert all(e is owner_slot["error"] for e in errors)
    assert calls == ["x"]  # loader ran exactly once
    assert memo.stats() == {"hits": 0, "misses": n + 1, "loads": 1}
    assert "x" not in memo.data  # nothing cached on failure

    # a later get calls the loader again (and succeeds this time)
    memo.loader = lambda k: "ok"
    assert memo.get("x") == "ok"
    assert memo.stats() == {"hits": 0, "misses": n + 2, "loads": 2}


def test_different_keys_load_in_parallel():
    """No lock shared between keys is held while loader runs: key "a"'s loader
    can wait for key "b"'s loader to be running without deadlocking."""
    in_a = threading.Event()
    in_b = threading.Event()

    def loader(key):
        if key == "a":
            in_a.set()
            assert in_b.wait(10), "b did not load while a was loading"
        else:
            in_b.set()
            assert in_a.wait(10), "a did not load while b was loading"
        return key.upper()

    memo = Memo(loader)
    slots = [{}, {}]
    threads = []
    for i, key in enumerate(("a", "b")):
        def worker(i=i, key=key):
            try:
                slots[i]["result"] = memo.get(key)
            except BaseException as exc:  # noqa: BLE001
                slots[i]["error"] = exc

        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    _join(threads)

    assert slots[0].get("result") == "A" and "error" not in slots[0]
    assert slots[1].get("result") == "B" and "error" not in slots[1]


def test_loader_can_get_other_keys():
    """Re-entrancy: loader may itself call get() for other keys."""

    def loader(key):
        if key == "a":
            return memo.get("b") + 1
        return 1

    memo = Memo(loader)
    assert memo.get("a") == 2
    assert memo.stats() == {"hits": 0, "misses": 2, "loads": 2}
    assert memo.get("a") == 2
    assert memo.get("b") == 1
    assert memo.stats() == {"hits": 2, "misses": 2, "loads": 2}


def test_stats_exact_under_mixed_workload():
    """Under concurrent hits/misses/loads stats stay exact:
    hits + misses == total gets, and loads == actual loader invocations."""
    n_threads, n_ops, n_keys = 8, 50, 4
    loaded = []
    loaded_lock = threading.Lock()

    def loader(key):
        with loaded_lock:
            loaded.append(key)
        return key * 3

    memo = Memo(loader)

    def worker(seed):
        for i in range(n_ops):
            key = (seed + i) % n_keys
            assert memo.get(key) == key * 3

    slots = [{} for _ in range(n_threads)]
    threads = []
    for i in range(n_threads):
        def worker_i(i=i):
            try:
                worker(i)
            except BaseException as exc:  # noqa: BLE001
                slots[i]["error"] = exc

        t = threading.Thread(target=worker_i)
        threads.append(t)
        t.start()
    _join(threads)
    assert all("error" not in s for s in slots)
    st = memo.stats()
    assert st["hits"] + st["misses"] == n_threads * n_ops
    assert st["loads"] == len(set(loaded)) == n_keys
