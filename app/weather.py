"""Current weather from Open-Meteo (free, no API key) and time/date/weather board lines.

Docs: https://open-meteo.com/en/docs
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from . import vestaboard

API_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_REFRESH_SECONDS = 15 * 60  # Open-Meteo's "current" values update every 15 minutes
ERROR_RETRY_SECONDS = 5 * 60

# WMO weather interpretation codes -> one-word condition.
CONDITIONS: dict[int, str] = {
    0: "CLEAR", 1: "FAIR", 2: "CLOUDY", 3: "OVERCAST",
    45: "FOG", 48: "FOG",
    51: "DRIZZLE", 53: "DRIZZLE", 55: "DRIZZLE", 56: "SLEET", 57: "SLEET",
    61: "RAIN", 63: "RAIN", 65: "RAIN", 66: "SLEET", 67: "SLEET",
    71: "SNOW", 73: "SNOW", 75: "SNOW", 77: "SNOW",
    80: "SHOWERS", 81: "SHOWERS", 82: "SHOWERS", 85: "SNOW", 86: "SNOW",
    95: "STORM", 96: "STORM", 99: "STORM",
}
# Shorter synonyms used when a line would not otherwise fit.
SHORTER = {"OVERCAST": "CLOUDY", "DRIZZLE": "RAIN", "SHOWERS": "RAIN"}


class WeatherError(Exception):
    pass


@dataclass
class Weather:
    temperature_c: float
    weather_code: int
    high_c: float | None
    low_c: float | None
    timezone: str | None
    utc_offset_seconds: int

    @property
    def condition(self) -> str:
        return CONDITIONS.get(self.weather_code, "")

    def tz(self) -> tzinfo:
        if self.timezone:
            try:
                return ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return timezone(timedelta(seconds=self.utc_offset_seconds))


class WeatherClient:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http
        self._cache: tuple[tuple[float, float], float, Weather] | None = None
        self._retry_after = 0.0
        self.last: Weather | None = None

    async def get(self, lat: float, lon: float, max_age: float = DEFAULT_REFRESH_SECONDS) -> Weather:
        key = (round(lat, 3), round(lon, 3))
        now = time.monotonic()
        if self._cache and self._cache[0] == key and now - self._cache[1] < max_age:
            return self._cache[2]
        if self._cache and self._cache[0] == key and now < self._retry_after:
            return self._cache[2]  # stale but better than nothing while Open-Meteo is failing
        try:
            resp = await self._http.get(
                API_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            current, daily = data["current"], data.get("daily") or {}
            weather = Weather(
                temperature_c=float(current["temperature_2m"]),
                weather_code=int(current["weather_code"]),
                high_c=(daily.get("temperature_2m_max") or [None])[0],
                low_c=(daily.get("temperature_2m_min") or [None])[0],
                timezone=data.get("timezone"),
                utc_offset_seconds=int(data.get("utc_offset_seconds") or 0),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            self._retry_after = now + ERROR_RETRY_SECONDS
            reason = str(exc) or type(exc).__name__  # timeouts have an empty message
            raise WeatherError(f"Open-Meteo weather lookup failed: {reason}") from exc
        self._cache = (key, now, weather)
        self.last = weather
        return weather


def format_temp(celsius: float, unit: str, degree: bool) -> str:
    """``22C``, ``72F`` or ``22C 72F``; with ``degree`` (Flagship only): ``22°C``."""
    deg = "°" if degree else ""
    c = f"{round(celsius)}{deg}C"
    f = f"{round(celsius * 9 / 5 + 32)}{deg}F"
    return {"C": c, "F": f}.get(unit, f"{c} {f}")


def weather_line(weather: Weather, unit: str, width: int, degree: bool) -> str:
    temps = format_temp(weather.temperature_c, unit, degree)
    if not degree:
        temps = temps.replace(" ", "/")  # Note: "22C/72F" reads as one reading, not two
    condition = weather.condition
    for word in (condition, SHORTER.get(condition, condition)):
        line = f"{temps} {word}".strip()
        if len(line) <= width:
            return line
    return vestaboard.fit(temps, width)


def high_low_line(weather: Weather, unit: str, width: int, degree: bool) -> str:
    if weather.high_c is None or weather.low_c is None:
        return ""
    for deg in dict.fromkeys((degree, False)):  # drop degree signs if that's what it takes to fit
        high = format_temp(weather.high_c, unit, deg).replace(" ", "/")
        low = format_temp(weather.low_c, unit, deg).replace(" ", "/")
        for gap in ("  ", " "):
            line = f"H {high}{gap}L {low}"
            if len(line) <= width:
                return line
    return ""


def format_time(now: datetime, time_format: str) -> str:
    if time_format == "24h":
        return now.strftime("%H:%M")
    return f"{now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


def format_date(now: datetime, width: int) -> str:
    """``MON OCT 26`` on a Note, ``MONDAY OCTOBER 26`` on a Flagship (when it fits)."""
    long = f"{now.strftime('%A')} {now.strftime('%B')} {now.day}".upper()
    return long if width > 15 and len(long) <= width else f"{now.strftime('%a %b')} {now.day}".upper()


def clock_lines(
    now: datetime,
    weather: Weather | None,
    *,
    board: str,
    time_format: str,
    unit: str,
    show_weather: bool,
) -> list[str]:
    """Time, date and (optionally) current weather, sized for the board."""
    rows, width = vestaboard.BOARD_SIZES[board]
    flagship = board == "flagship"  # code 62 is a degree sign on Flagship, a heart on Note
    lines = [format_time(now, time_format), format_date(now, width)]
    if show_weather and weather is not None:
        lines.append(weather_line(weather, unit, width, degree=flagship))
        if flagship:
            high_low = high_low_line(weather, unit, width, degree=True)
            if high_low:
                lines.append(high_low)
    return lines[:rows]
