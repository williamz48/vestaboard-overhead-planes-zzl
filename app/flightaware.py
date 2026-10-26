"""FlightAware AeroAPI (v4) client used to enrich ADS-B callsigns.

Docs: https://www.flightaware.com/aeroapi/portal/documentation

AeroAPI is billed per request, so results are cached per callsign until the
flight is expected to land (bounded to a few hours) and misses are cached too.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import httpx

API_URL = "https://aeroapi.flightaware.com/aeroapi"

MISS_TTL = 30 * 60
DEFAULT_TTL = 60 * 60
MAX_TTL = 6 * 60 * 60
ERROR_TTL = 5 * 60


class FlightAwareError(Exception):
    pass


@dataclass
class FlightInfo:
    ident: str
    ident_iata: str | None
    operator: str | None
    operator_iata: str | None
    flight_number: str | None
    registration: str | None
    aircraft_type: str | None
    origin: str | None
    origin_name: str | None
    destination: str | None
    destination_name: str | None
    status: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def airport_code(airport: dict | None) -> str | None:
    """Prefer IATA, then FAA LID, then ICAO for an AeroAPI airport object."""
    if not airport:
        return None
    for key in ("code_iata", "code_lid", "code_icao", "code"):
        if airport.get(key):
            return str(airport[key]).upper()
    return None


def _departure_time(flight: dict) -> float | None:
    for key in ("actual_off", "estimated_off", "scheduled_off", "actual_out", "scheduled_out"):
        t = _parse_time(flight.get(key))
        if t is not None:
            return t
    return None


def pick_current_flight(flights: list[dict], now: float | None = None) -> dict | None:
    """Pick the leg that is in the air right now from an AeroAPI ``flights`` list.

    The list covers several days of past and scheduled legs for the ident.
    """
    now = time.time() if now is None else now
    live = [f for f in flights if not f.get("cancelled")]
    airborne = [f for f in live if f.get("actual_off") and not f.get("actual_on")]
    if airborne:
        return max(airborne, key=lambda f: _parse_time(f.get("actual_off")) or 0)
    timed = [(abs(t - now), f) for f in live if (t := _departure_time(f)) is not None]
    if timed:
        return min(timed, key=lambda pair: pair[0])[1]
    return live[0] if live else None


def to_flight_info(flight: dict) -> FlightInfo:
    origin, dest = flight.get("origin") or {}, flight.get("destination") or {}
    return FlightInfo(
        ident=flight.get("ident") or "",
        ident_iata=flight.get("ident_iata"),
        operator=flight.get("operator"),
        operator_iata=flight.get("operator_iata"),
        flight_number=flight.get("flight_number"),
        registration=flight.get("registration"),
        aircraft_type=flight.get("aircraft_type"),
        origin=airport_code(origin),
        origin_name=origin.get("city") or origin.get("name"),
        destination=airport_code(dest),
        destination_name=dest.get("city") or dest.get("name"),
        status=flight.get("status"),
    )


def _cache_ttl(flight: dict, now: float) -> float:
    arrival = None
    for key in ("estimated_on", "scheduled_on", "estimated_in", "scheduled_in"):
        arrival = _parse_time(flight.get(key))
        if arrival is not None:
            break
    if arrival is None:
        return DEFAULT_TTL
    return min(MAX_TTL, max(10 * 60, arrival - now + 30 * 60))


class FlightAwareClient:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http
        self._cache: dict[str, tuple[float, FlightInfo | None]] = {}
        self.requests_made = 0

    def peek(self, callsign: str) -> FlightInfo | None:
        """Return a cached result without making a (billable) request."""
        entry = self._cache.get(callsign)
        if entry and entry[0] > time.time():
            return entry[1]
        return None

    def clear_cache(self) -> None:
        self._cache.clear()

    async def lookup(self, callsign: str, api_key: str) -> FlightInfo | None:
        if not callsign or not api_key:
            return None
        now = time.time()
        entry = self._cache.get(callsign)
        if entry and entry[0] > now:
            return entry[1]

        try:
            self.requests_made += 1
            resp = await self._http.get(
                f"{API_URL}/flights/{callsign}",
                params={"max_pages": 1},
                headers={"x-apikey": api_key, "Accept": "application/json"},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            self._cache[callsign] = (now + ERROR_TTL, None)
            raise FlightAwareError(f"FlightAware request failed: {exc}") from exc

        if resp.status_code in (400, 404):
            self._cache[callsign] = (now + MISS_TTL, None)
            return None
        if resp.status_code != 200:
            self._cache[callsign] = (now + ERROR_TTL, None)
            if resp.status_code in (401, 403):
                raise FlightAwareError("FlightAware rejected the API key")
            raise FlightAwareError(f"FlightAware returned HTTP {resp.status_code}")

        flight = pick_current_flight((resp.json() or {}).get("flights") or [], now)
        if flight is None:
            self._cache[callsign] = (now + MISS_TTL, None)
            return None
        info = to_flight_info(flight)
        self._cache[callsign] = (now + _cache_ttl(flight, now), info)
        return info

    async def test(self, api_key: str) -> str:
        if not api_key:
            raise FlightAwareError("No FlightAware API key set")
        try:
            resp = await self._http.get(
                f"{API_URL}/account/usage",
                headers={"x-apikey": api_key, "Accept": "application/json"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise FlightAwareError(f"FlightAware request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise FlightAwareError("FlightAware rejected the API key")
        if resp.status_code != 200:
            raise FlightAwareError(f"FlightAware returned HTTP {resp.status_code}")
        cost = (resp.json() or {}).get("total_cost")
        suffix = f" Usage this period: ${cost:.2f}." if isinstance(cost, (int, float)) else ""
        return "FlightAware API key is valid." + suffix
