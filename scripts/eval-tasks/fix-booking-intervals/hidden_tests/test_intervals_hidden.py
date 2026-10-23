import random

from scheduling.intervals import free_slots, merge_intervals, total_busy


def norm(result):
    return [tuple(x) for x in result]


def test_merge_unsorted():
    assert norm(merge_intervals([(5, 8), (1, 3)])) == [(1, 3), (5, 8)]


def test_merge_touching():
    assert norm(merge_intervals([(1, 3), (3, 5)])) == [(1, 5)]


def test_merge_nested_keeps_outer_end():
    assert norm(merge_intervals([(1, 10), (2, 3)])) == [(1, 10)]


def test_merge_lists_and_empty():
    assert norm(merge_intervals([[4, 6], [1, 2]])) == [(1, 2), (4, 6)]
    assert norm(merge_intervals([])) == []


def test_merge_does_not_modify_input():
    data = [(5, 8), (1, 3), (2, 6)]
    merge_intervals(data)
    assert data == [(5, 8), (1, 3), (2, 6)]


def test_free_slots_touching_bookings_leave_no_gap():
    assert norm(free_slots([(540, 570), (570, 600)], 480, 660)) == [(480, 540), (600, 660)]


def test_free_slots_min_length_inclusive():
    assert norm(free_slots([(500, 530)], 480, 560, min_length=20)) == [(480, 500), (530, 560)]
    assert norm(free_slots([(500, 530)], 480, 560, min_length=21)) == [(530, 560)]


def test_free_slots_busy_outside_window():
    assert norm(free_slots([(400, 500), (1000, 1100)], 480, 1020)) == [(500, 1000)]
    assert norm(free_slots([(1100, 1200)], 480, 1020)) == [(480, 1020)]
    assert norm(free_slots([(0, 100)], 480, 1020)) == [(480, 1020)]


def test_free_slots_nested_and_unsorted():
    assert norm(free_slots([(570, 600), (480, 720), (540, 570)], 480, 780)) == [(720, 780)]


def test_free_slots_fully_booked():
    assert norm(free_slots([(400, 1100)], 480, 1020)) == []


def test_total_busy_clips_to_window():
    assert total_busy([(400, 500), (490, 520), (1000, 1100)], 480, 1020) == 60
    assert total_busy([(0, 100)], 480, 1020) == 0
    assert total_busy([(1, 3), (3, 5)], 0, 10) == 4


def brute(busy, lo, hi):
    covered = set()
    for s, e in busy:
        covered.update(range(max(s, lo), min(e, hi)))
    return covered


def brute_free(busy, lo, hi, min_length):
    covered = brute(busy, lo, hi)
    slots, start = [], None
    for m in range(lo, hi + 1):
        free = m < hi and m not in covered
        if free and start is None:
            start = m
        elif not free and start is not None:
            if m - start >= min_length:
                slots.append((start, m))
            start = None
    return slots


def test_randomized_against_brute_force():
    rng = random.Random(1234)
    for _ in range(400):
        busy = []
        for _ in range(rng.randint(0, 8)):
            s = rng.randint(0, 190)
            busy.append((s, s + rng.randint(1, 40)))
        lo = rng.randint(0, 100)
        hi = lo + rng.randint(1, 120)
        min_length = rng.randint(1, 15)
        assert total_busy(busy, lo, hi) == len(brute(busy, lo, hi)), (busy, lo, hi)
        assert norm(free_slots(busy, lo, hi, min_length)) == brute_free(busy, lo, hi, min_length), (busy, lo, hi, min_length)
        merged = norm(merge_intervals(busy))
        assert set().union(*[set(range(s, e)) for s, e in merged]) == brute(busy, -10**6, 10**6)
        assert all(a[1] < b[0] for a, b in zip(merged, merged[1:]))
