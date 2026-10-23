import threading


class _Load:
    def __init__(self):
        self.done = threading.Event()
        self.value = None
        self.error = None


class Memo:
    """Thread-safe memoizing cache in front of a slow ``loader(key) -> value`` (reference solution)."""

    def __init__(self, loader):
        self.loader = loader
        self.data = {}
        self.inflight = {}
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
            load = self.inflight.get(key)
            owner = load is None
            if owner:
                load = self.inflight[key] = _Load()
                self.loads += 1
        if not owner:
            load.done.wait()
            if load.error is not None:
                raise load.error
            return load.value
        try:
            load.value = self.loader(key)
        except BaseException as e:
            load.error = e
            raise
        finally:
            with self.lock:
                if load.error is None:
                    self.data[key] = load.value
                del self.inflight[key]
            load.done.set()
        return load.value

    def stats(self):
        with self.lock:
            return {"hits": self.hits, "misses": self.misses, "loads": self.loads}
