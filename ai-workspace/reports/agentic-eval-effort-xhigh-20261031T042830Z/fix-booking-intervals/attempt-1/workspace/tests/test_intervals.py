from scheduling.intervals import free_slots, merge_intervals, total_busy


def test_merge_overlapping_sorted():
    assert merge_intervals([(1, 4), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_free_slots_basic():
    assert free_slots([(540, 600), (660, 720)], 480, 1020) == [(480, 540), (600, 660), (720, 1020)]


def test_total_busy_inside_window():
    assert total_busy([(540, 600), (660, 720)], 480, 1020) == 120


def test_merge_touching_intervals_merge():
    # A 09:00-09:30 and B 09:30-10:00 must not leave a zero-minute gap.
    assert merge_intervals([(540, 570), (570, 600)]) == [(540, 600)]


def test_merge_unsorted_input():
    assert merge_intervals([(8, 10), (1, 4), (2, 6)]) == [(1, 6), (8, 10)]


def test_merge_contained_interval_does_not_shrink_run():
    # A booking fully inside an earlier one must not truncate the merged run.
    assert merge_intervals([(1, 10), (3, 5)]) == [(1, 10)]
    assert merge_intervals([(480, 720), (540, 570)]) == [(480, 720)]


def test_merge_accepts_lists_without_modifying_input():
    busy = [[8, 10], [1, 4]]
    assert merge_intervals(busy) == [(1, 4), (8, 10)]
    assert busy == [[8, 10], [1, 4]]


def test_merge_empty():
    assert merge_intervals([]) == []


def test_free_slots_no_gap_between_touching_bookings():
    assert free_slots([(540, 570), (570, 600)], 480, 1020) == [(480, 540), (600, 1020)]


def test_free_slots_contained_booking():
    # Booked 08:00-12:00 and 09:00-09:30: busy from 08:00 to 12:00.
    assert free_slots([(480, 720), (540, 570)], 480, 1020) == [(720, 1020)]


def test_free_slots_unsorted_input():
    assert free_slots([(660, 720), (540, 600)], 480, 1020) == [
        (480, 540),
        (600, 660),
        (720, 1020),
    ]


def test_free_slots_min_length_is_inclusive():
    # A gap of exactly min_length is kept.
    assert free_slots([(480, 540), (570, 1020)], 480, 1020, min_length=30) == [(540, 570)]
    # One minute shorter is dropped.
    assert free_slots([(480, 540), (569, 1020)], 480, 1020, min_length=30) == []


def test_free_slots_min_length_default_keeps_one_minute_gaps():
    assert free_slots([(480, 540), (541, 1020)], 480, 1020) == [(540, 541)]


def test_free_slots_ignores_busy_outside_window():
    assert free_slots([(0, 500), (1000, 2000)], 480, 1020) == [(500, 1000)]
    assert free_slots([(-60, 480), (1020, 1440)], 480, 1020) == [(480, 1020)]


def test_free_slots_whole_window_busy():
    assert free_slots([(0, 1440)], 480, 1020) == []


def test_free_slots_empty_day():
    assert free_slots([], 480, 1020) == [(480, 1020)]


def test_total_busy_clips_to_window():
    # Never negative even when bookings spill over both ends of the day.
    assert total_busy([(0, 480), (1020, 1440)], 480, 1020) == 0
    assert total_busy([(400, 500), (1000, 1200)], 480, 1020) == 40
    assert total_busy([(0, 1440)], 480, 1020) == 540


def test_total_busy_counts_overlap_once():
    assert total_busy([(480, 720), (540, 570)], 480, 1020) == 240


def test_total_busy_unsorted_input():
    assert total_busy([(660, 720), (540, 600)], 480, 1020) == 120


def test_total_busy_empty():
    assert total_busy([], 480, 1020) == 0
