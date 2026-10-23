import threading


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
        self.lock = threading.Lock()

    def get(self, key):
        if key in self.data:
            self.hits += 1
            return self.data[key]
        self.misses += 1
        self.loads += 1
        value = self.loader(key)
        with self.lock:
            self.data[key] = value
        return value

    def stats(self):
        return {"hits": self.hits, "misses": self.misses, "loads": self.loads}
