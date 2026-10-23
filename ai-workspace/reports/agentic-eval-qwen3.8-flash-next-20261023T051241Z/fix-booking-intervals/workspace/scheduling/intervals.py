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
    # Work on a sorted copy so the caller's iterable (list, generator, ...)
    # is never mutated or reordered.
    pending = sorted((tuple(interval) for interval in intervals), key=lambda iv: (iv[0], iv[1]))

    merged = []
    for start, end in pending:
        if merged and start <= merged[-1][1]:
            # Overlapping or touching the current run: extend it only if that
            # actually makes the run longer (handles contained intervals such
            # as (1, 10) followed by (2, 3)).
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
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
            # Entirely before the window.
            continue
        if start >= day_end:
            # Entirely after the window; later intervals are too (sorted).
            break
        start = max(start, day_start)
        if start - cursor >= min_length:
            slots.append((cursor, start))
        cursor = max(cursor, min(end, day_end))
    if day_end - cursor >= min_length:
        slots.append((cursor, day_end))
    return slots


def total_busy(busy, day_start, day_end):
    """Number of minutes inside ``[day_start, day_end)`` covered by at least one busy interval."""
    total = 0
    for start, end in merge_intervals(busy):
        # Clamp to the window; intervals that fall completely outside it
        # contribute 0 (never a negative amount).
        covered = min(end, day_end) - max(start, day_start)
        if covered > 0:
            total += covered
    return total
