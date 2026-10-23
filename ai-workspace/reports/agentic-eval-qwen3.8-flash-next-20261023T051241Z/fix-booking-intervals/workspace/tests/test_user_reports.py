"""Regression tests reproducing the exact reports from booking-service users.

Each test mirrors one report against ``scheduling/intervals.py``; day window is
08:00-17:00 (480..1020 minutes since midnight).
"""

from scheduling.intervals import free_slots, merge_intervals, total_busy

DAY_START, DAY_END = 480, 1020


def test_report_room4_no_zero_minute_gap_at_0930():
    """'Room 4 had bookings 09:00-09:30 and 09:30-10:00 but the page offered a
    0-minute gap at 09:30.'"""
    busy = [(540, 570), (570, 600)]

    assert merge_intervals(busy) == [(540, 600)]
    slots = free_slots(busy, DAY_START, DAY_END)

    assert (570, 570) not in slots
    assert all(end > start for start, end in slots)
    assert slots == [(480, 540), (600, 1020)]


def test_report_overlapping_booking_not_shown_as_free():
    """'A room booked 08:00-12:00 and 09:00-09:30 showed as free from 09:30 to 12:00.'"""
    busy = [(480, 720), (540, 570)]

    assert merge_intervals(busy) == [(480, 720)]
    slots = free_slots(busy, DAY_START, DAY_END)

    assert not any(start < 720 < end for start, end in slots)
    assert slots == [(720, 1020)]
    assert total_busy(busy, DAY_START, DAY_END) == 240


def test_report_out_of_order_bookings():
    """'Bookings that were entered out of order produced garbage availability.'"""
    in_order = [(480, 540), (540, 600), (660, 720)]
    scrambled = [(660, 720), (540, 600), (480, 540)]
    shuffled = [(540, 600), (480, 540), (660, 720)]

    expected = [(600, 660), (720, 1020)]
    for busy in (in_order, scrambled, shuffled):
        assert free_slots(busy, DAY_START, DAY_END) == expected
        assert total_busy(busy, DAY_START, DAY_END) == 180


def test_report_30_minute_slot_was_hidden():
    """'Asking for slots of at least 30 minutes hid a free slot that was exactly
    30 minutes long.'"""
    # Free: 08:00-09:00, 09:30-10:00 (exactly 30 min), 12:00-17:00.
    busy = [(540, 570), (600, 720)]

    assert (570, 600) in free_slots(busy, DAY_START, DAY_END, min_length=30)
    assert free_slots(busy, DAY_START, DAY_END, min_length=30) == [
        (480, 540),
        (570, 600),
        (720, 1020),
    ]
    # A slot one minute shorter is still rejected.
    assert (570, 599) not in free_slots([(540, 570), (599, 720)], DAY_START, DAY_END, min_length=30)


def test_report_negative_busy_minutes_on_dashboard():
    """'The busy minutes figure is sometimes negative when a booking starts before
    the business day or ends after it.'"""
    cases = [
        [(300, 540)],            # starts before the day (05:00-09:00)
        [(960, 1500)],           # ends after the day (16:00-25:00)
        [(300, 1500)],           # spans the whole day
        [(0, 60)],               # entirely before the day
        [(1200, 1440)],          # entirely after the day
        [(0, 60), (1200, 1440)],  # both outside
    ]
    for busy in cases:
        minutes = total_busy(busy, DAY_START, DAY_END)
        assert minutes >= 0, busy

    assert total_busy([(300, 540)], DAY_START, DAY_END) == 60
    assert total_busy([(960, 1500)], DAY_START, DAY_END) == 60
    assert total_busy([(300, 1500)], DAY_START, DAY_END) == 540
    assert total_busy([(0, 60), (1200, 1440)], DAY_START, DAY_END) == 0
