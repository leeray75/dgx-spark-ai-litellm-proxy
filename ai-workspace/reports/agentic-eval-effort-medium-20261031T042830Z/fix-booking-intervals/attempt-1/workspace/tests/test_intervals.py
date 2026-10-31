from scheduling.intervals import free_slots, merge_intervals, total_busy


def test_merge_overlapping_sorted():
    assert merge_intervals([(1, 4), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_free_slots_basic():
    assert free_slots([(540, 600), (660, 720)], 480, 1020) == [(480, 540), (600, 660), (720, 1020)]


def test_total_busy_inside_window():
    assert total_busy([(540, 600), (660, 720)], 480, 1020) == 120


def test_merge_touching_intervals():
    # (1, 3) and (3, 5) touch and must merge into (1, 5).
    assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]


def test_merge_unsorted_input():
    assert merge_intervals([(8, 10), (2, 6), (1, 4)]) == [(1, 6), (8, 10)]


def test_merge_contained_interval_does_not_truncate():
    assert merge_intervals([(1, 10), (3, 4)]) == [(1, 10)]


def test_merge_does_not_modify_input():
    intervals = [(5, 7), (1, 3)]
    merge_intervals(intervals)
    assert intervals == [(5, 7), (1, 3)]


def test_free_slots_adjacent_bookings_no_zero_gap():
    # Room 4 booked 09:00-09:30 and 09:30-10:00 must not offer a 0-minute gap.
    assert free_slots([(540, 570), (570, 600)], 480, 600) == [(480, 540)]


def test_free_slots_overlapping_bookings():
    # Booked 08:00-12:00 and 09:00-09:30: the room is busy the whole day.
    assert free_slots([(480, 720), (540, 570)], 480, 720) == []


def test_free_slots_unsorted_busy():
    assert free_slots([(660, 720), (540, 600)], 480, 1020) == [
        (480, 540),
        (600, 660),
        (720, 1020),
    ]


def test_free_slots_min_length_inclusive():
    # A free slot exactly min_length long must be kept.
    assert free_slots([(540, 570)], 480, 600, min_length=30) == [(480, 540), (570, 600)]
    assert free_slots([(540, 571)], 480, 600, min_length=30) == [(480, 540)]


def test_free_slots_clips_busy_intervals_to_window():
    # Busy intervals outside the window are ignored; no slots past day_end.
    assert free_slots([(0, 540), (1000, 2000)], 480, 1020) == [(540, 1000)]
    assert free_slots([(0, 400)], 480, 1020) == [(480, 1020)]


def test_total_busy_never_negative():
    # Booking entirely before the day and entirely after it contribute 0.
    assert total_busy([(0, 400), (1100, 1440)], 480, 1020) == 0
    # Partial overlap is clamped to the window.
    assert total_busy([(420, 600), (960, 1200)], 480, 1020) == 180


def test_total_busy_counts_overlap_once():
    assert total_busy([(480, 720), (540, 570)], 480, 720) == 240
