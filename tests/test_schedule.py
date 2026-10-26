from datetime import datetime
from zoneinfo import ZoneInfo

from app.schedule import in_window, next_occurrence, seconds_until


def at(hhmm, day=26, tz=None):
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=tz)


def test_daytime_window():
    assert in_window(at("09:00"), "09:00", "17:00")
    assert in_window(at("16:59"), "09:00", "17:00")
    assert not in_window(at("17:00"), "09:00", "17:00")
    assert not in_window(at("08:59"), "09:00", "17:00")


def test_overnight_window():
    assert in_window(at("22:00"), "22:00", "07:00")
    assert in_window(at("23:59"), "22:00", "07:00")
    assert in_window(at("00:00"), "22:00", "07:00")
    assert in_window(at("06:59"), "22:00", "07:00")
    assert not in_window(at("07:00"), "22:00", "07:00")
    assert not in_window(at("12:00"), "22:00", "07:00")


def test_equal_times_is_an_empty_window():
    assert not in_window(at("10:00"), "10:00", "10:00")


def test_seconds_until():
    assert seconds_until(at("21:00"), "22:00") == 3600
    assert seconds_until(at("23:00"), "07:00") == 8 * 3600
    assert seconds_until(at("22:00"), "22:00") == 24 * 3600  # next day, not now
    assert next_occurrence(at("23:00"), "07:00").day == 27


def test_seconds_until_across_daylight_saving_change():
    # US clocks go back an hour at 2am on 2026-11-01, so 22:00 -> 07:00 is 10 real hours.
    ny = ZoneInfo("America/New_York")
    assert seconds_until(datetime(2026, 10, 31, 22, 0, tzinfo=ny), "07:00") == 10 * 3600
