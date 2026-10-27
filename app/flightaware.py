"""FlightAware AeroAPI (v4) client used to enrich ADS-B callsigns.

Docs: https://www.flightaware.com/aeroapi/portal/documentation

AeroAPI is billed per request, so calls are kept to a minimum:

* One ``/flights/{ident}`` call returns every leg flown under that callsign from
  about 11 days ago to 2 days ahead. The whole schedule is kept, so when the
  same callsign is seen again (later today, or tomorrow's run of a daily flight)
  the leg in the air is found in the cache instead of being bought again.
* The cache is saved to disk, so restarts and upgrades don't throw it away.
* Misses and errors are remembered briefly so they aren't retried every poll.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

API_URL = "https://aeroapi.flightaware.com/aeroapi"

MISS_TTL = 30 * 60
ERROR_TTL = 5 * 60
SCHEDULE_TTL = 3 * 24 * 3600  # a lookup covers up to 2 days ahead
LEG_MARGIN = 30 * 60  # slack around a leg's departure/arrival times when reusing it
MAX_LEG_SECONDS = 20 * 3600  # assumed flight length when no arrival time is known

_LEG_KEYS = (
    "ident", "ident_iata", "codeshares_iata", "operator", "operator_iata", "flight_number",
    "registration", "aircraft_type", "status", "cancelled",
    "actual_out", "scheduled_out", "actual_off", "estimated_off", "scheduled_off",
    "actual_on", "estimated_on", "scheduled_on", "estimated_in", "scheduled_in",
)
_AIRPORT_KEYS = ("code", "code_iata", "code_icao", "code_lid", "city", "name")


class FlightAwareError(Exception):
    pass


@dataclass
class FlightInfo:
    ident: str
    ident_iata: str | None
    codeshares_iata: list[str]
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
        codeshares_iata=list(flight.get("codeshares_iata") or []),
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


def _trim(flight: dict) -> dict:
    """Keep only the fields we use, so the on-disk cache stays small."""
    leg = {k: flight[k] for k in _LEG_KEYS if flight.get(k) is not None}
    for side in ("origin", "destination"):
        if flight.get(side):
            leg[side] = {k: flight[side][k] for k in _AIRPORT_KEYS if flight[side].get(k)}
    return leg


def _leg_window(flight: dict) -> tuple[float, float] | None:
    """When a leg is in the air: (departure, arrival) as timestamps."""
    off = _departure_time(flight)
    if off is None:
        return None
    for key in ("actual_on", "estimated_on", "scheduled_on", "estimated_in", "scheduled_in"):
        on = _parse_time(flight.get(key))
        if on is not None:
            return off, on
    return off, off + MAX_LEG_SECONDS


def covering_leg(flights: list[dict], now: float) -> dict | None:
    """The leg of a cached schedule that should be in the air at ``now``, if any."""
    exact, near = [], []
    for flight in flights:
        if flight.get("cancelled") or (window := _leg_window(flight)) is None:
            continue
        off, on = window
        if off <= now <= on:
            exact.append((off, flight))
        elif off - LEG_MARGIN <= now <= on + LEG_MARGIN:
            near.append((min(abs(now - off), abs(now - on)), flight))
    if exact:
        # Prefer a leg known to be airborne, then the one that departed last.
        return max(exact, key=lambda p: (bool(p[1].get("actual_off") and not p[1].get("actual_on")), p[0]))[1]
    if near:
        return min(near, key=lambda p: p[0])[1]
    return None


class FlightAwareClient:
    def __init__(self, http: httpx.AsyncClient, cache_path: Path | None = None):
        self._http = http
        self._cache_path = cache_path
        # callsign -> {"fetched": timestamp, "legs": [trimmed AeroAPI flights]}
        self._schedules: dict[str, dict] = {}
        # Short-lived answers: misses, errors and best guesses when no leg covers now.
        self._recent: dict[str, tuple[float, FlightInfo | None]] = {}
        self.requests_made = 0
        self.cache_hits = 0  # legs shown from the cache that would otherwise have been a call
        self._served: set[tuple[str, float | None]] = set()
        self._load()

    def _load(self) -> None:
        if not self._cache_path or not self._cache_path.exists():
            return
        try:
            self._schedules = json.loads(self._cache_path.read_text()).get("schedules", {})
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Ignoring unreadable FlightAware cache: %s", exc)
            self._schedules = {}

    def _save(self) -> None:
        cutoff = time.time() - SCHEDULE_TTL
        self._schedules = {k: v for k, v in self._schedules.items() if v["fetched"] > cutoff}
        if not self._cache_path:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"schedules": self._schedules}))
            os.replace(tmp, self._cache_path)
        except OSError as exc:
            log.warning("Could not save FlightAware cache: %s", exc)

    def _cached_leg(self, callsign: str, now: float, need_registration: bool) -> dict | None:
        entry = self._schedules.get(callsign)
        if not entry:
            return None
        leg = covering_leg(entry["legs"], now)
        if leg is None:
            return None
        # Registrations are assigned close to departure. If the schedule was fetched
        # before this leg left and the board needs the registration, fetch it again
        # (at most every MISS_TTL, in case FlightAware never learns it).
        if need_registration and not leg.get("registration"):
            departure = _departure_time(leg)
            stale = departure is not None and entry["fetched"] < departure
            if stale and now - entry["fetched"] > MISS_TTL:
                return None
        return leg

    def peek(self, callsign: str) -> FlightInfo | None:
        """Return a cached result without making a (billable) request."""
        now = time.time()
        leg = self._cached_leg(callsign, now, need_registration=False)
        if leg is not None:
            return to_flight_info(leg)
        recent = self._recent.get(callsign)
        return recent[1] if recent and recent[0] > now else None

    def clear_cache(self) -> None:
        self._schedules.clear()
        self._recent.clear()
        self._served.clear()
        self._save()

    async def lookup(
        self, callsign: str, api_key: str, need_registration: bool = False
    ) -> FlightInfo | None:
        if not callsign or not api_key:
            return None
        now = time.time()
        leg = self._cached_leg(callsign, now, need_registration)
        if leg is not None:
            served = (callsign, _departure_time(leg))
            if served not in self._served:  # count each leg once, not every poll
                self._served.add(served)
                self.cache_hits += 1
            return to_flight_info(leg)
        recent = self._recent.get(callsign)
        if recent and recent[0] > now:
            return recent[1]

        try:
            self.requests_made += 1
            resp = await self._http.get(
                f"{API_URL}/flights/{callsign}",
                params={"max_pages": 1},
                headers={"x-apikey": api_key, "Accept": "application/json"},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            self._recent[callsign] = (now + ERROR_TTL, None)
            raise FlightAwareError(f"FlightAware request failed: {exc}") from exc

        if resp.status_code in (400, 404):
            self._recent[callsign] = (now + MISS_TTL, None)
            return None
        if resp.status_code != 200:
            self._recent[callsign] = (now + ERROR_TTL, None)
            if resp.status_code in (401, 403):
                raise FlightAwareError("FlightAware rejected the API key")
            raise FlightAwareError(f"FlightAware returned HTTP {resp.status_code}")

        legs = [_trim(f) for f in (resp.json() or {}).get("flights") or []]
        self._schedules[callsign] = {"fetched": now, "legs": legs}
        self._save()
        leg = covering_leg(legs, now)
        if leg is not None:
            self._served.add((callsign, _departure_time(leg)))  # paid for, not a saving
            return to_flight_info(leg)
        # Nothing matches the current time exactly; use the best guess for a while.
        best = pick_current_flight(legs, now)
        info = to_flight_info(best) if best is not None else None
        self._recent[callsign] = (now + MISS_TTL, info)
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
