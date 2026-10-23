"""Interval helpers used by the meeting-room booking service.

An interval is a half-open ``(start, end)`` pair of integer minutes since
midnight with ``start < end``. Inputs may be tuples or lists, in any order,
and may overlap.
"""


def _canonical(intervals):
    """Return ``intervals`` as a new list of valid ``(start, end)`` tuples.

    Accepts any iterable of two-element sequences (tuples, lists, ...),
    drops degenerate entries (``start >= end``) and sorts by ``(start, end)``.
    The input itself is never modified.
    """
    canonical = []
    for interval in intervals:
        start, end = interval
        if start < end:
            canonical.append((start, end))
    canonical.sort()
    return canonical


def merge_intervals(intervals):
    """Merge overlapping or touching intervals.

    Returns a list of ``(start, end)`` tuples sorted by start, where no two
    intervals overlap or touch (``(1, 3)`` and ``(3, 5)`` merge into ``(1, 5)``).
    The input is not modified.
    """
    merged = []
    for start, end in _canonical(intervals):
        if merged and start <= merged[-1][1]:
            last_start, last_end = merged[-1]
            # Keep the widest end: an interval fully inside the previous one
            # must not shrink it.
            merged[-1] = (last_start, max(last_end, end))
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
    required = max(1, min_length)
    slots = []
    cursor = day_start
    for start, end in merge_intervals(busy):
        if end <= day_start:
            continue  # entirely before the window
        if start >= day_end:
            break  # entirely after the window
        gap_start = max(cursor, day_start)
        gap_end = min(start, day_end)
        if gap_end - gap_start >= required:
            slots.append((gap_start, gap_end))
        cursor = max(cursor, end)
        if cursor >= day_end:
            break
    if day_end - cursor >= required:
        slots.append((max(cursor, day_start), day_end))
    return slots


def total_busy(busy, day_start, day_end):
    """Number of minutes inside ``[day_start, day_end)`` covered by at least one busy interval."""
    total = 0
    for start, end in merge_intervals(busy):
        covered = min(end, day_end) - max(start, day_start)
        if covered > 0:
            total += covered
    return total
