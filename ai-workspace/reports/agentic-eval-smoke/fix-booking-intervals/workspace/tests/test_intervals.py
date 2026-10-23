from scheduling.intervals import free_slots, merge_intervals, total_busy


def test_merge_overlapping_sorted():
    assert merge_intervals([(1, 4), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_free_slots_basic():
    assert free_slots([(540, 600), (660, 720)], 480, 1020) == [(480, 540), (600, 660), (720, 1020)]


def test_total_busy_inside_window():
    assert total_busy([(540, 600), (660, 720)], 480, 1020) == 120


# --- merge_intervals -------------------------------------------------------


def test_merge_touching_intervals_merge_together():
    # (1, 3) and (3, 5) touch and must become one interval, not a 0-minute gap.
    assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]


def test_merge_back_to_back_bookings():
    assert merge_intervals([(540, 570), (570, 600)]) == [(540, 600)]


def test_merge_unsorted_input():
    assert merge_intervals([(8, 10), (1, 4), (2, 6)]) == [(1, 6), (8, 10)]


def test_merge_nested_interval_does_not_shrink_container():
    # 08:00-12:00 plus 09:00-09:30 must stay busy until 12:00.
    assert merge_intervals([(480, 720), (540, 570)]) == [(480, 720)]
    assert merge_intervals([(540, 570), (480, 720)]) == [(480, 720)]


def test_merge_accepts_lists_and_does_not_modify_input():
    busy = [[5, 8], (0, 2), [2, 3]]
    assert merge_intervals(busy) == [(0, 3), (5, 8)]
    assert busy == [[5, 8], (0, 2), [2, 3]]
    # The returned intervals are tuples, even though some inputs were lists.
    assert all(isinstance(item, tuple) for item in merge_intervals(busy))


def test_merge_empty_input():
    assert merge_intervals([]) == []


def test_merge_chained():
    assert merge_intervals([(1, 2), (2, 3), (3, 4), (9, 10)]) == [(1, 4), (9, 10)]


# --- free_slots ------------------------------------------------------------


def test_free_slots_no_zero_length_gap_between_touching_bookings():
    # Room booked 09:00-09:30 and 09:30-10:00 offers no gap at 09:30.
    assert free_slots([(540, 570), (570, 600)], 480, 660) == [(480, 540), (600, 660)]


def test_free_slots_ignores_nested_shorter_booking():
    # Room booked 08:00-12:00 *and* 09:00-09:30 is not free 09:30-12:00.
    assert free_slots([(480, 720), (540, 570)], 480, 720) == []


def test_free_slots_unsorted_busy_input():
    assert free_slots([(660, 720), (480, 540), (540, 600)], 480, 1020) == [
        (600, 660),
        (720, 1020),
    ]


def test_free_slots_min_length_is_inclusive():
    # A gap of exactly 30 minutes qualifies for min_length=30.
    assert free_slots([(540, 600)], 480, 630, min_length=30) == [(480, 540), (600, 630)]
    # ... and a 29-minute gap does not.
    assert free_slots([(540, 600)], 480, 629, min_length=30) == [(480, 540)]


def test_free_slots_min_length_default_is_one():
    assert free_slots([(540, 570)], 540, 571) == [(570, 571)]
    assert free_slots([(540, 570)], 540, 570) == []


def test_free_slots_clips_busy_intervals_outside_window():
    # Booking spanning the whole window leaves nothing free.
    assert free_slots([(0, 1440)], 480, 1020) == []
    # Booking ending before the window is ignored.
    assert free_slots([(0, 480)], 480, 1020) == [(480, 1020)]
    # Booking starting after the window is ignored.
    assert free_slots([(1020, 1440)], 480, 1020) == [(480, 1020)]
    # Partial overlaps on both sides.
    assert free_slots([(0, 540), (960, 1440)], 480, 1020) == [(540, 960)]


def test_free_slots_no_busy_intervals():
    assert free_slots([], 480, 1020) == [(480, 1020)]


def test_free_slots_accepts_any_iterable():
    assert free_slots([[540, 600], (660, 720)], 480, 1020) == [
        (480, 540),
        (600, 660),
        (720, 1020),
    ]


def test_free_slots_empty_window():
    assert free_slots([], 480, 480) == []


# --- total_busy ------------------------------------------------------------


def test_total_busy_never_negative_for_booking_before_day():
    assert total_busy([(0, 540)], 480, 1020) == 60


def test_total_busy_never_negative_for_booking_after_day():
    assert total_busy([(960, 1440)], 480, 1020) == 60


def test_total_busy_clips_both_sides():
    assert total_busy([(0, 1440)], 480, 1020) == 540


def test_total_busy_ignores_intervals_outside_window():
    assert total_busy([(0, 480), (1020, 1440)], 480, 1020) == 0


def test_total_busy_counts_overlaps_once():
    assert total_busy([(480, 720), (540, 570)], 480, 1020) == 240


def test_total_busy_unsorted_input():
    assert total_busy([(660, 720), (540, 600)], 480, 1020) == 120


def test_total_busy_touching_bookings():
    assert total_busy([(540, 570), (570, 600)], 480, 1020) == 60
