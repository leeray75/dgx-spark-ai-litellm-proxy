from fetcher.memo import Memo


def test_caches_value():
    calls = []
    memo = Memo(lambda k: calls.append(k) or k * 2)
    assert memo.get(3) == 6
    assert memo.get(3) == 6
    assert calls == [3]
    assert memo.stats() == {"hits": 1, "misses": 1, "loads": 1}
