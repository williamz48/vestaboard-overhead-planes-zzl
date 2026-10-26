"""Daily time windows (used for scheduled do not disturb)."""

from __future__ import annotations

from datetime import datetime, time, timedelta


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def in_window(now: datetime, start: str, end: str) -> bool:
    """True if ``now`` (local wall time) is inside the daily ``start``-``end`` window.

    Windows may cross midnight ("22:00"-"07:00"). Equal start and end is an empty window.
    """
    start_t, end_t, now_t = parse_hhmm(start), parse_hhmm(end), now.time().replace(tzinfo=None)
    if start_t == end_t:
        return False
    if start_t < end_t:
        return start_t <= now_t < end_t
    return now_t >= start_t or now_t < end_t


def next_occurrence(now: datetime, hhmm: str) -> datetime:
    """The next time the wall clock reads ``hhmm`` after ``now`` (same time zone)."""
    target = datetime.combine(now.date(), parse_hhmm(hhmm), tzinfo=now.tzinfo)
    if target <= now:
        target = datetime.combine(now.date() + timedelta(days=1), parse_hhmm(hhmm), tzinfo=now.tzinfo)
    return target


def seconds_until(now: datetime, hhmm: str) -> float:
    # Compare as timestamps so a daylight-saving change in between is counted correctly.
    return next_occurrence(now, hhmm).timestamp() - now.timestamp()
