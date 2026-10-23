import threading


class _Load:
    """Bookkeeping for a single in-flight ``loader(key)`` call.

    A ``_Load`` is created by the first ``get(key)`` that misses; it is removed
    from ``Memo._inflight`` (under the memo lock) as soon as the loader finishes,
    and ``done`` is set right afterwards.  Every field is written before ``done``
    is set and only read after ``done`` was waited on, so no extra lock is needed
    to read ``value``/``exc``.
    """

    __slots__ = ("owner", "value", "exc", "done", "waiters")

    def __init__(self):
        # Thread that runs ``loader``; used to turn a re-entrant same-key get()
        # into an error instead of a self-inflicted deadlock.
        self.owner = threading.get_ident()
        self.value = None
        self.exc = None
        self.done = threading.Event()
        # Number of get() calls parked on this load (diagnostics/tests).
        self.waiters = 0


class Memo:
    """Thread-safe memoizing cache in front of a slow ``loader(key) -> value``.

    Guarantees:

    * ``loader(key)`` runs at most once at a time per key: concurrent ``get(key)``
      calls for a key that is being loaded wait for that load and return its value.
    * Different keys load in parallel: no lock shared between keys is held while
      ``loader`` runs, so ``loader`` may itself call ``get`` for other keys.
    * Successful values are cached forever.
    * If ``loader`` raises, every caller waiting on that load gets the same
      exception, nothing is cached, and a later ``get`` calls ``loader`` again.
    * ``stats()`` returns ``{"hits": h, "misses": m, "loads": n}``, exact under any
      concurrency: a *hit* is a ``get`` answered from the cache without waiting,
      every other ``get`` is a *miss*, and ``loads`` counts ``loader`` calls.
    """

    def __init__(self, loader):
        self.loader = loader
        self.data = {}
        self.hits = 0
        self.misses = 0
        self.loads = 0
        # Guards self.data, self._inflight and the counters.  It is *never* held
        # while loader() runs, so keys never block each other and loader() may
        # call back into get()/stats().
        self.lock = threading.Lock()
        self._inflight = {}

    def get(self, key):
        with self.lock:
            if key in self.data:
                # Answered from the cache without waiting: a hit.
                self.hits += 1
                return self.data[key]

            load = self._inflight.get(key)
            if load is not None:
                if load.owner == threading.get_ident():
                    # loader(key) is already running in *this* thread: waiting on
                    # it would hang forever.  Fail loudly instead.
                    raise RuntimeError(
                        "recursive Memo.get(%r) from inside its own loader" % (key,)
                    )
                # Somebody else is loading this key: count the miss, then wait.
                self.misses += 1
                load.waiters += 1
                owner = False
            else:
                self.misses += 1
                self.loads += 1
                load = _Load(key)
                self._inflight[key] = load
                owner = True

        if not owner:
            load.done.wait()
            if load.exc is not None:
                raise load.exc
            return load.value

        try:
            value = self.loader(key)
        except BaseException as exc:
            # Publish the failure and unblock everybody waiting on this key.
            # Nothing is cached, so a later get() calls loader() again.
            with self.lock:
                if self._inflight.get(key) is load:
                    del self._inflight[key]
                load.exc = exc
            load.done.set()
            raise

        with self.lock:
            self.data[key] = value
            if self._inflight.get(key) is load:
                del self._inflight[key]
            load.value = value
        load.done.set()
        return value

    def stats(self):
        with self.lock:
            return {"hits": self.hits, "misses": self.misses, "loads": self.loads}
