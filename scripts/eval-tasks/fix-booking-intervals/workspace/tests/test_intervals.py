from scheduling.intervals import free_slots, merge_intervals, total_busy


def test_merge_overlapping_sorted():
    assert merge_intervals([(1, 4), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_free_slots_basic():
    assert free_slots([(540, 600), (660, 720)], 480, 1020) == [(480, 540), (600, 660), (720, 1020)]


def test_total_busy_inside_window():
    assert total_busy([(540, 600), (660, 720)], 480, 1020) == 120
