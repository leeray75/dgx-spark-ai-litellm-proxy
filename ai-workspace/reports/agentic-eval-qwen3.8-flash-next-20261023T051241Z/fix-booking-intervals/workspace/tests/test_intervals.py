from scheduling.intervals import free_slots, merge_intervals, total_busy


def test_merge_overlapping_sorted():
    assert merge_intervals([(1, 4), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_free_slots_basic():
    assert free_slots([(540, 600), (660, 720)], 480, 1020) == [(480, 540), (600, 660), (720, 1020)]


def test_total_busy_inside_window():
    assert total_busy([(540, 600), (660, 720)], 480, 1020) == 120


# --- merge_intervals -------------------------------------------------------


def test_merge_touching_intervals_become_one():
    # (1, 3) and (3, 5) touch and must merge: no 0-minute gap may survive.
    assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]


def test_merge_back_to_back_bookings():
    assert merge_intervals([(540, 570), (570, 600)]) == [(540, 600)]


def test_merge_is_sorted_for_unsorted_input():
    assert merge_intervals([(8, 10), (1, 4), (2, 6)]) == [(1, 6), (8, 10)]


def test_merge_unsorted_disjoint_intervals():
    assert merge_intervals([(700, 720), (480, 540), (600, 660)]) == [
        (480, 540),
        (600, 660),
        (700, 720),
    ]


def test_merge_contained_interval_does_not_shrink_run():
    # A booking fully inside an earlier, longer one must not shorten it.
    assert merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]
    assert merge_intervals([(2, 3), (1, 10)]) == [(1, 10)]


def test_merge_handles_lists_and_generators():
    assert merge_intervals([[1, 3], [3, 5]]) == [(1, 5)]
    assert merge_intervals(iter([(3, 5), (1, 3)])) == [(1, 5)]


def test_merge_empty_input():
    assert merge_intervals([]) == []


def test_merge_does_not_modify_input():
    original = [(5, 9), (1, 3), (3, 4)]
    snapshot = [tuple(iv) for iv in original]
    merge_intervals(original)
    assert original == snapshot


# --- free_slots ------------------------------------------------------------


def test_free_slots_no_zero_length_gap_between_touching_bookings():
    # Room 4: 09:00-09:30 and 09:30-10:00 must not offer a 0-minute gap at 09:30.
    assert free_slots([(540, 570), (570, 600)], 480, 660) == [(480, 540), (600, 660)]


def test_free_slots_overlapping_bookings_do_not_leak_free_time():
    # Booked 08:00-12:00 *and* 09:00-09:30: free only before 08:00 / after 12:00.
    assert free_slots([(480, 720), (540, 570)], 480, 780) == [(720, 780)]


def test_free_slots_out_of_order_bookings():
    assert free_slots([(660, 720), (480, 540), (540, 600)], 480, 1020) == [
        (600, 660),
        (720, 1020),
    ]


def test_free_slots_ignores_busy_outside_window():
    # (0, 500) blocks the window up to 08:20; (1000, 2000) blocks from 16:40.
    assert free_slots([(0, 500), (1000, 2000)], 480, 1020) == [(500, 1000)]


def test_free_slots_busy_entirely_outside_window():
    assert free_slots([(60, 120)], 480, 1020) == [(480, 1020)]
    assert free_slots([(1200, 1440)], 480, 1020) == [(480, 1020)]


def test_free_slots_busy_covers_whole_window():
    assert free_slots([(400, 1100)], 480, 1020) == []


def test_free_slots_empty_day():
    assert free_slots([], 480, 1020) == [(480, 1020)]


def test_free_slots_min_length_keeps_exact_match():
    # A free slot of exactly min_length must be kept (09:30-10:00 == 30 min).
    assert free_slots([(540, 570), (600, 720)], 480, 720, min_length=30) == [
        (480, 540),
        (570, 600),
    ]


def test_free_slots_min_length_drops_shorter_slots():
    # Gap 09:30-09:45 is only 15 minutes, so it is dropped; 08:00-09:00 survives.
    assert free_slots([(540, 570), (585, 720)], 480, 720, min_length=30) == [(480, 540)]


def test_free_slots_min_length_default_keeps_one_minute_gaps():
    assert free_slots([(480, 540), (541, 600)], 480, 600) == [(540, 541)]


def test_free_slots_gaps_are_maximal_and_sorted():
    busy = [(700, 720), (500, 540), (540, 560), (560, 600), (500, 510)]
    assert free_slots(busy, 480, 780) == [(480, 500), (600, 700), (720, 780)]


def test_free_slots_accepts_generator():
    assert free_slots(iter([(660, 720), (480, 540)]), 480, 1020) == [(540, 660), (720, 1020)]


def test_free_slots_empty_window():
    assert free_slots([], 480, 480) == []


# --- total_busy ------------------------------------------------------------


def test_total_busy_clamps_booking_starting_before_day():
    # Booking 06:00-09:00 with a day starting 08:00 counts 60, not 180 (or less).
    assert total_busy([(360, 540)], 480, 1020) == 60


def test_total_busy_clamps_booking_ending_after_day():
    assert total_busy([(960, 1440)], 480, 1020) == 60


def test_total_busy_never_negative_for_outside_bookings():
    assert total_busy([(0, 60)], 480, 1020) == 0
    assert total_busy([(1200, 1440)], 480, 1020) == 0
    assert total_busy([(0, 60), (1200, 1440)], 480, 1020) == 0


def test_total_busy_counts_overlap_once():
    # 08:00-12:00 plus 09:00-09:30 covers 240 minutes, not 300.
    assert total_busy([(480, 720), (540, 570)], 480, 1020) == 240


def test_total_busy_merges_touching_bookings():
    assert total_busy([(540, 570), (570, 600)], 480, 1020) == 60


def test_total_busy_unsorted_input():
    assert total_busy([(660, 720), (480, 720), (540, 570)], 480, 1020) == 240


def test_total_busy_clamps_both_ends():
    assert total_busy([(0, 1440)], 480, 1020) == 540


def test_total_busy_empty():
    assert total_busy([], 480, 1020) == 0
