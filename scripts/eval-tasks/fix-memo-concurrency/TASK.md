# Bug: duplicate upstream calls and wrong stats from the memo cache

`fetcher/memo.py` puts a cache in front of a slow, rate-limited upstream API. In production,
with many worker threads, we see:

- the same key fetched from upstream several times at once (we get rate-limited);
- `stats()` numbers that don't add up;
- after an upstream error, some callers hang or get a stale result.

Fix `Memo` so it meets **every guarantee in its class docstring** (that docstring is the
specification; don't change it). Keep the public API (`Memo(loader)`, `get(key)`, `stats()`).
Keep existing tests passing and add tests for the concurrency behaviour.
