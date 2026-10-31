import threading


class _Load:
    """State of a single in-flight ``loader(key)`` call.

    Written once by the owning thread (the one that runs ``loader``) before it
    sets ``event``; only read by waiting threads after ``event`` is set, so the
    value/exception are published safely without further synchronisation.
    """

    __slots__ = ("event", "value", "exc")

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.exc = None


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
        # All four fields below are only ever touched while ``lock`` is held.
        self.data = {}
        self._inflight = {}  # key -> _Load, while loader(key) is running
        self.hits = 0
        self.misses = 0
        self.loads = 0
        # Fast lock guarding the bookkeeping above; never held while loader runs.
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.data:
                self.hits += 1
                return self.data[key]
            self.misses += 1
            load = self._inflight.get(key)
            if load is None:
                # We are the first caller for this key: we own the load.
                load = _Load()
                self._inflight[key] = load
                self.loads += 1
                owner = True
            else:
                # Someone else is already loading it; wait for their result.
                owner = False

        if not owner:
            load.event.wait()
            if load.exc is not None:
                raise load.exc
            return load.value

        try:
            value = self.loader(key)
        except BaseException as exc:
            # Publish the failure: drop the in-flight marker first (under the
            # lock, so any get() that arrives afterwards starts a fresh load),
            # then wake the waiters with the very same exception object.
            with self.lock:
                if self._inflight.get(key) is load:
                    del self._inflight[key]
            load.exc = exc
            load.event.set()
            raise

        with self.lock:
            # Cache and unmark atomically: a get() either sees the cached value
            # (hit) or joins this load, never a gap between the two.
            self.data[key] = value
            if self._inflight.get(key) is load:
                del self._inflight[key]
        load.value = value
        load.event.set()
        return value

    def stats(self):
        with self.lock:
            return {"hits": self.hits, "misses": self.misses, "loads": self.loads}
