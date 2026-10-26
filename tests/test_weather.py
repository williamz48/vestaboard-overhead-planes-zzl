from datetime import datetime

from app import vestaboard
from app.weather import (
    CONDITIONS, Weather, clock_lines, format_date, format_temp, format_time, weather_line,
)


def wx(temp_c=22.0, code=0, high=None, low=None):
    return Weather(temperature_c=temp_c, weather_code=code, high_c=high, low_c=low,
                   timezone="America/New_York", utc_offset_seconds=-14400)


def test_time_formats():
    assert format_time(datetime(2026, 10, 26, 0, 5), "12h") == "12:05 AM"
    assert format_time(datetime(2026, 10, 26, 12, 0), "12h") == "12:00 PM"
    assert format_time(datetime(2026, 10, 26, 15, 45), "12h") == "3:45 PM"
    assert format_time(datetime(2026, 10, 26, 15, 45), "24h") == "15:45"
    assert format_time(datetime(2026, 10, 26, 7, 5), "24h") == "07:05"


def test_dates():
    wed = datetime(2026, 10, 28)
    assert format_date(wed, 15) == "WED OCT 28"
    assert format_date(wed, 22) == "WEDNESDAY OCTOBER 28"
    assert format_date(datetime(2026, 9, 30), 22) == "WEDNESDAY SEPTEMBER 30"


def test_temperatures():
    assert format_temp(22.4, "C", False) == "22C"
    assert format_temp(22.4, "F", False) == "72F"
    assert format_temp(-12, "both", False) == "-12C 10F"
    assert format_temp(22.4, "F", True) == "72°F"


def test_weather_line_fits_a_note():
    assert weather_line(wx(code=0), "F", 15, False) == "72F CLEAR"
    assert weather_line(wx(code=95), "both", 15, False) == "22C/72F STORM"
    assert weather_line(wx(code=45), "C", 15, False) == "22C FOG"
    # "OVERCAST" doesn't fit next to both temperatures, so a shorter word is used
    assert weather_line(wx(code=3), "both", 15, False) == "22C/72F CLOUDY"
    assert weather_line(wx(temp_c=-25, code=3), "both", 15, False) == "-25C/-13F"
    for code in CONDITIONS:
        line = weather_line(wx(temp_c=-40, code=code), "both", 15, False)
        assert len(line) <= 15


def test_clock_lines():
    now = datetime(2026, 10, 26, 15, 45)
    note = clock_lines(now, wx(code=61), board="note", time_format="12h", unit="F", show_weather=True)
    assert note == ["3:45 PM", "MON OCT 26", "72F RAIN"]
    assert all("°" not in line for line in note)  # code 62 is a heart on the Note
    flagship = clock_lines(now, wx(code=2, high=25, low=15), board="flagship", time_format="24h",
                           unit="both", show_weather=True)
    assert flagship == ["15:45", "MONDAY OCTOBER 26", "22°C 72°F CLOUDY", "H 25C/77F  L 15C/59F"]
    single = clock_lines(now, wx(high=25, low=15), board="flagship", time_format="12h", unit="F",
                         show_weather=True)
    assert single[3] == "H 77°F  L 59°F"
    grid = vestaboard.layout(flagship, "flagship")
    assert all(len(row) == 22 for row in grid)
    no_wx = clock_lines(now, wx(), board="note", time_format="12h", unit="F", show_weather=False)
    assert no_wx == ["3:45 PM", "MON OCT 26"]


async def _two_lookups(max_age, age):
    import httpx
    import respx

    from app.weather import API_URL, WeatherClient

    payload = {"timezone": "UTC", "utc_offset_seconds": 0,
               "current": {"temperature_2m": 10, "weather_code": 0}, "daily": {}}
    with respx.mock:
        route = respx.get(API_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as http:
            client = WeatherClient(http)
            await client.get(1.0, 2.0, max_age=max_age)
            key, fetched, cached = client._cache
            client._cache = (key, fetched - age, cached)  # pretend the lookup was `age` seconds ago
            await client.get(1.0, 2.0, max_age=max_age)
        return route.call_count


def test_weather_refresh_interval():
    import asyncio

    assert asyncio.run(_two_lookups(max_age=30 * 60, age=20 * 60)) == 1  # still fresh
    assert asyncio.run(_two_lookups(max_age=10 * 60, age=20 * 60)) == 2  # refreshed
