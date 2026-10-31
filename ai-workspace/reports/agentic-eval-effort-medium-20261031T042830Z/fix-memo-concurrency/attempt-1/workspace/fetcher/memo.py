import threading


class _Load:
    """State of a single in-flight ``loader(key)`` call, shared with waiters."""

    __slots__ = ("event", "value", "error")

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.error = None


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
        self._inflight = {}
        self.hits = 0
        self.misses = 0
        self.loads = 0
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.data:
                self.hits += 1
                return self.data[key]
            self.misses += 1
            load = self._inflight.get(key)
            owner = load is None
            if owner:
                load = _Load()
                self._inflight[key] = load
                self.loads += 1
        if not owner:
            # Another thread is loading this key: wait for its outcome.
            load.event.wait()
            if load.error is not None:
                raise load.error
            return load.value
        try:
            value = self.loader(key)
        except BaseException as exc:
            with self.lock:
                self._inflight.pop(key, None)
                load.error = exc
            load.event.set()
            raise
        with self.lock:
            self.data[key] = value
            self._inflight.pop(key, None)
            load.value = value
        load.event.set()
        return value

    def stats(self):
        with self.lock:
            return {"hits": self.hits, "misses": self.misses, "loads": self.loads}
