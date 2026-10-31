"""Interval helpers used by the meeting-room booking service.

An interval is a half-open ``(start, end)`` pair of integer minutes since
midnight with ``start < end``. Inputs may be tuples or lists, in any order,
and may overlap.
"""


def merge_intervals(intervals):
    """Merge overlapping or touching intervals.

    Returns a list of ``(start, end)`` tuples sorted by start, where no two
    intervals overlap or touch (``(1, 3)`` and ``(3, 5)`` merge into ``(1, 5)``).
    The input is not modified.
    """
    merged = []
    for start, end in sorted((tuple(iv) for iv in intervals), key=lambda iv: (iv[0], iv[1])):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def free_slots(busy, day_start, day_end, min_length=1):
    """Free gaps inside the window ``[day_start, day_end)``.

    ``busy`` is any iterable of intervals; parts of busy intervals outside the
    window are ignored. Returns the maximal free ``(start, end)`` tuples inside
    the window, sorted by start, keeping only those whose length
    ``end - start`` is at least ``min_length`` (``min_length >= 1``).
    """
    slots = []
    cursor = day_start
    for start, end in merge_intervals(busy):
        if end <= day_start:
            continue
        if start >= day_end:
            break
        start = max(start, day_start)
        if start > cursor and start - cursor >= min_length:
            slots.append((cursor, start))
        cursor = max(cursor, min(end, day_end))
    if day_end - cursor >= min_length:
        slots.append((cursor, day_end))
    return slots


def total_busy(busy, day_start, day_end):
    """Number of minutes inside ``[day_start, day_end)`` covered by at least one busy interval."""
    total = 0
    for start, end in merge_intervals(busy):
        start = max(start, day_start)
        end = min(end, day_end)
        if end > start:
            total += end - start
    return total
