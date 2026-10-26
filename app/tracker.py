"""Background loop: poll OpenSky, pick a flight, enrich it, push it to the board."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from . import aircraft, airlines, geo, vestaboard, weather
from .config import Settings, SettingsStore
from .flightaware import FlightAwareClient, FlightAwareError, FlightInfo
from .opensky import Aircraft, OpenSkyClient, OpenSkyError
from .vestaboard import VestaboardClient, VestaboardError
from .weather import WeatherClient, WeatherError

log = logging.getLogger(__name__)

# Vestaboard drops messages sent more often than once every 15 seconds.
BOARD_MIN_GAP = 16


@dataclass
class TrackedFlight:
    icao24: str
    callsign: str
    latitude: float
    longitude: float
    altitude_ft: int | None
    speed_kt: int | None
    heading: float | None
    on_ground: bool
    distance_km: float
    bearing: str
    flight: str = ""
    origin: str | None = None
    destination: str | None = None
    origin_name: str | None = None
    destination_name: str | None = None
    aircraft: str = ""
    aircraft_long: str = ""
    aircraft_type: str | None = None
    registration: str | None = None
    airline: str | None = None
    color: int | None = None
    enriched: bool = False

    def to_dict(self, unit: str) -> dict:
        data = asdict(self)
        data["distance"] = round(geo.from_km(self.distance_km, unit), 1)
        return data


def to_tracked(a: Aircraft, lat: float, lon: float) -> TrackedFlight:
    return TrackedFlight(
        icao24=a.icao24,
        callsign=a.callsign,
        latitude=a.latitude,
        longitude=a.longitude,
        altitude_ft=round(a.altitude_m * geo.FEET_PER_METER) if a.altitude_m is not None else None,
        speed_kt=round(a.velocity_ms * geo.KNOTS_PER_MS) if a.velocity_ms is not None else None,
        heading=a.heading,
        on_ground=a.on_ground,
        distance_km=geo.haversine_km(lat, lon, a.latitude, a.longitude),
        bearing=geo.compass_point(geo.bearing_deg(lat, lon, a.latitude, a.longitude)),
        flight=airlines.iata_flight_number(a.callsign),
    )


def apply_enrichment(
    flight: TrackedFlight,
    info: FlightInfo | None,
    overrides: dict[str, str],
    color_overrides: dict[str, str] | None = None,
) -> None:
    if info is not None:
        flight.enriched = True
        flight.flight = airlines.iata_flight_number(
            flight.callsign, info.ident_iata, info.codeshares_iata
        )
        flight.origin = info.origin
        flight.destination = info.destination
        flight.origin_name = info.origin_name
        flight.destination_name = info.destination_name
        flight.aircraft_type = info.aircraft_type
        flight.registration = info.registration
        flight.airline = info.operator
    flight.aircraft = aircraft.short_name(flight.aircraft_type, flight.registration, overrides)
    flight.aircraft_long = aircraft.long_name(flight.aircraft_type, flight.aircraft)
    flight.color = airlines.airline_color(flight.callsign, flight.flight, color_overrides)


def filter_flights(planes: list[Aircraft], s: Settings) -> list[TrackedFlight]:
    radius_km = geo.to_km(s.radius, s.radius_unit)
    result = []
    for a in planes:
        if a.on_ground and not s.include_ground:
            continue
        if not a.callsign:
            continue
        if s.airlines_only and not airlines.is_airline_callsign(a.callsign):
            continue
        alt_ft = a.altitude_m * geo.FEET_PER_METER if a.altitude_m is not None else None
        if s.min_altitude_ft and (alt_ft is None or alt_ft < s.min_altitude_ft):
            continue
        if s.max_altitude_ft and alt_ft is not None and alt_ft > s.max_altitude_ft:
            continue
        flight = to_tracked(a, s.latitude, s.longitude)
        if flight.distance_km <= radius_km:
            result.append(flight)
    result.sort(key=lambda f: f.distance_km)
    return result


def route_line(
    origin: str | None, destination: str | None, width: int, balanced: bool = False
) -> str:
    if not origin and not destination:
        return ""
    o, d = origin or "???", destination or "???"
    text = f"{o} - {d}"
    if len(text) > width:
        return vestaboard.fit(f"{o}-{d}", width)
    if balanced:
        # Put the extra space beside the shorter code so the dash sits in the middle:
        # "KSFO -  JFK", "JFK  - KSFO".
        text = vestaboard.balance(text, width, split=len(o) + 2 if len(o) > len(d) else len(o))
    return text


def number_split(flight: TrackedFlight, number: str) -> int | None:
    """Where to add a space in a flight number: between the airline and the digits."""
    if not airlines.is_airline_callsign(flight.callsign):
        return None  # a tail number such as N123AB has no airline part
    if number != flight.callsign and re.match(r"^[A-Z0-9]{2}\d", number):
        return 2  # IATA: "UA 1234", "9E 5034"
    if re.match(r"^[A-Z]{3}\d", number):
        return 3  # unconverted ICAO callsign: "XYZ 1234"
    return None


def aircraft_line(
    flight: TrackedFlight,
    width: int,
    mode: str = "model",
    manufacturer: bool = True,
    balanced: bool = False,
) -> str:
    """The aircraft row.

    ``model``: "AIRBUS A350-900" when it fits (with ``manufacturer``), else "A350-900".
    ``icao_registration``: ICAO type designator and registration, "A359 N501DN".
    ``model_registration``: the model plus registration, "A350-900 N501DN", using
    the ICAO designator instead of the model when that's what it takes to fit.
    Missing parts are left out. With ``balanced``, an extra space goes between the
    manufacturer and model, or the model and registration, to center the row.
    """
    # Each candidate is (text, where to add a space if the row needs balancing).
    maker = aircraft.MANUFACTURERS.get((flight.aircraft_type or "").upper(), "")
    models: list[tuple[str, int | None]] = []
    if manufacturer and flight.aircraft_long:
        long_split = len(maker) if flight.aircraft_long.startswith(f"{maker} ") else None
        models.append((flight.aircraft_long, long_split))  # "AIRBUS  A321NEO"
    models.append((flight.aircraft, None))
    icao, reg = flight.aircraft_type or "", flight.registration or ""

    def with_reg(text: str) -> tuple[str, int | None]:
        if text and reg:
            return f"{text} {reg}", len(text)  # "A350-900  N501DN"
        return text or reg, None

    if mode == "icao_registration":
        candidates = [with_reg(icao)]
    elif mode == "model_registration":
        candidates = [with_reg(m) for m, _ in models] + [with_reg(icao)]
    else:
        candidates = models
    candidates = [(t.upper(), split) for t, split in candidates if t]
    if not candidates:
        return ""
    text, split = next(((t, sp) for t, sp in candidates if len(t) <= width), candidates[-1])
    if len(text) > width:
        return vestaboard.fit(text, width)
    return vestaboard.balance(text, width, split) if balanced else text


def board_lines(
    flight: TrackedFlight,
    width: int,
    colors: bool = True,
    align: str = "center",
    manufacturer: bool = True,
    aircraft_mode: str = "model",
) -> list[str]:
    """Line 1: flight number, line 2: ORIGIN - DESTINATION, line 3: aircraft.

    With ``colors``, the flight number row gets the airline's color at both ends.
    See :func:`aircraft_line` for ``manufacturer`` and ``aircraft_mode``. When
    centered, rows that can't be centered exactly get one extra space at a natural
    break ("UA 1234") so the blank tiles on each side match.
    """
    balanced = align == "center"
    number = vestaboard.fit(flight.flight or flight.callsign, width)
    edge = colors and flight.color is not None
    if balanced:
        # Edge tiles leave width - 4 tiles for the number (tile and blank on each side).
        max_len = width - 4 if edge else width
        number = vestaboard.balance(number, width, number_split(flight, number), max_len)
    first = vestaboard.with_edge_tiles(number, flight.color, width, align) if edge else number
    return [
        first,
        route_line(flight.origin, flight.destination, width, balanced),
        aircraft_line(flight, width, aircraft_mode, manufacturer, balanced),
    ]


@dataclass
class TrackerState:
    status: str = "starting"
    last_poll: float | None = None
    next_poll: float | None = None
    opensky_error: str | None = None
    flightaware_error: str | None = None
    vestaboard_error: str | None = None
    weather_error: str | None = None
    nearby: list[TrackedFlight] = field(default_factory=list)
    current_icao24: str | None = None
    current_since: float | None = None
    flight_last_seen: float | None = None  # last time the flight on the board was in range
    board_lines: list[str] | None = None
    board_grid: list[list[int]] | None = None
    board_sent_at: float | None = None
    board_source: str | None = None
    manual_until: float | None = None


class Tracker:
    def __init__(
        self,
        store: SettingsStore,
        opensky: OpenSkyClient,
        flightaware: FlightAwareClient,
        board: VestaboardClient,
        weather_client: WeatherClient | None = None,
    ):
        self.store = store
        self.opensky = opensky
        self.flightaware = flightaware
        self.board = board
        self.weather = weather_client
        self._clock_showing = False
        self.state = TrackerState()
        self._wake = asyncio.Event()
        self._poll_now = False
        self._next_poll_mono = 0.0
        self._pending: tuple[list[str], str] | None = None
        self._lock = asyncio.Lock()

    # ---- control -------------------------------------------------------
    def wake(self, poll: bool = False) -> None:
        if poll:
            self._poll_now = True
        self._wake.set()

    def settings_changed(self) -> None:
        self.state.board_lines = None  # force a redraw with the new layout/settings
        self.wake(poll=True)

    async def run(self) -> None:
        while True:
            try:
                delay = await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let the loop die
                log.exception("Tracker step failed")
                self.state.status = "error"
                delay = 30
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(1.0, delay))
            except asyncio.TimeoutError:
                pass

    # ---- one iteration -------------------------------------------------
    async def step(self) -> float:
        s = self.store.get()
        if not s.enabled:
            self.state.status = "paused"
            return 60
        if not s.has_location:
            self.state.status = "needs location"
            return 60

        now = time.monotonic()
        if self._poll_now or now >= self._next_poll_mono:
            self._poll_now = False
            await self.poll(s)
        if self.state.opensky_error is None:  # don't act on stale/missing data
            await self.update_display(s)
        elif self._clock_showing and not self.state.manual_until:
            await self.show_clock(s)  # keep the clock ticking while OpenSky is down

        # Sleep until the next poll unless something else needs attention sooner:
        # a held flight that may hand over to another one, a rate-limited board
        # update, or the end of a manual message hold.
        waits = [self._next_poll_mono - time.monotonic()]
        if self.state.current_since is not None and len(self.state.nearby) > 1:
            hold_left = s.min_display_seconds - (time.time() - self.state.current_since)
            if hold_left > 0:
                waits.append(hold_left)
        if self._pending and self.state.board_sent_at:
            waits.append(BOARD_MIN_GAP - (time.time() - self.state.board_sent_at))
        if self.state.manual_until:
            waits.append(self.state.manual_until - time.time())
        if self._clock_showing and not self.state.manual_until:
            waits.append(60.5 - time.time() % 60)  # just after the next minute ticks over
        if not self.state.nearby and self.idle_delay_left(s) > 0:
            waits.append(self.idle_delay_left(s))
        return max(1.0, min(waits))

    def idle_delay_left(self, s: Settings) -> float:
        """Seconds the last flight stays up after leaving range before the idle screen."""
        if s.idle_action == "keep" or self.state.current_icao24 is None:
            return 0.0
        if self.state.flight_last_seen is None:
            return 0.0
        return max(0.0, s.idle_delay_seconds - (time.time() - self.state.flight_last_seen))

    async def poll(self, s: Settings) -> None:
        bbox = geo.bounding_box(s.latitude, s.longitude, geo.to_km(s.radius, s.radius_unit))
        self._next_poll_mono = time.monotonic() + s.poll_interval
        try:
            planes = await self.opensky.get_states(bbox, s.opensky_client_id, s.opensky_client_secret)
        except OpenSkyError as exc:
            self.state.opensky_error = str(exc)
            self.state.status = "opensky error"
            if exc.retry_after:
                self._next_poll_mono = time.monotonic() + max(s.poll_interval, exc.retry_after)
            log.warning("%s", exc)
            return
        self.state.opensky_error = None
        overrides = aircraft.parse_overrides(s.aircraft_overrides)
        color_overrides = aircraft.parse_overrides(s.airline_color_overrides)
        flights = filter_flights(planes, s)
        for f in flights:
            apply_enrichment(f, self.flightaware.peek(f.callsign), overrides, color_overrides)
        self.state.nearby = flights
        self.state.last_poll = time.time()
        self.state.next_poll = self.state.last_poll + (self._next_poll_mono - time.monotonic())
        self.state.status = "tracking"

    def _choose(self, s: Settings) -> TrackedFlight | None:
        flights = self.state.nearby
        if not flights:
            return None
        by_id = {f.icao24: f for f in flights}
        current = by_id.get(self.state.current_icao24 or "")
        held = (
            current is not None
            and self.state.current_since is not None
            and time.time() - self.state.current_since < s.min_display_seconds
        )
        if held:
            return current
        if s.display_mode == "rotate" and current is not None:
            ids = [f.icao24 for f in flights]
            return flights[(ids.index(current.icao24) + 1) % len(flights)]
        return flights[0]

    async def update_display(self, s: Settings) -> None:
        if self.state.manual_until:
            if time.time() < self.state.manual_until:
                return
            self.state.manual_until = None
        rows, cols = vestaboard.BOARD_SIZES[s.board_model]
        target = self._choose(s)
        if target is None:
            if self.idle_delay_left(s) > 0:
                return  # leave the last flight up until the idle delay runs out
            self.state.current_icao24 = None
            self.state.current_since = None
            if s.idle_action == "clock":
                await self.show_clock(s)
                return
            self._clock_showing = False
            if s.idle_action == "message" and s.idle_message.strip():
                lines = s.idle_message.upper().splitlines()[:rows]
                await self.show(lines, s, source="idle")
            return
        self._clock_showing = False
        self.state.flight_last_seen = time.time()

        if target.icao24 != self.state.current_icao24:
            self.state.current_icao24 = target.icao24
            self.state.current_since = time.time()

        if s.flightaware_api_key and not target.enriched:
            try:
                info = await self.flightaware.lookup(target.callsign, s.flightaware_api_key)
                self.state.flightaware_error = None
            except FlightAwareError as exc:
                info = None
                self.state.flightaware_error = str(exc)
                log.warning("%s", exc)
            apply_enrichment(
                target,
                info,
                aircraft.parse_overrides(s.aircraft_overrides),
                aircraft.parse_overrides(s.airline_color_overrides),
            )

        lines = board_lines(
            target, cols, s.airline_colors, s.align, s.show_manufacturer, s.aircraft_display
        )
        await self.show(lines, s, source=target.icao24)

    async def show_clock(self, s: Settings) -> None:
        """Show the time, date and current weather for the configured location."""
        self._clock_showing = True
        current = None
        if self.weather is not None:
            try:
                current = await self.weather.get(s.latitude, s.longitude)
                self.state.weather_error = None
            except WeatherError as exc:
                self.state.weather_error = str(exc)
                log.warning("%s", exc)
                current = self.weather.last
        # Local time at the tracked location (Open-Meteo reports its time zone);
        # fall back to the container's clock until the first weather lookup works.
        now = datetime.now(current.tz()) if current else datetime.now().astimezone()
        lines = weather.clock_lines(
            now,
            current,
            board=s.board_model,
            time_format=s.time_format,
            unit=s.temperature_unit,
            show_weather=s.clock_show_weather,
        )
        if s.align == "center":
            cols = vestaboard.BOARD_SIZES[s.board_model][1]
            lines = [vestaboard.balance(line, cols) for line in lines]
        await self.show(lines, s, source="clock")

    async def show(self, lines: list[str], s: Settings, source: str, force: bool = False) -> bool:
        """Send lines to the board if they changed, respecting the board's rate limit."""
        async with self._lock:
            lines = [line.strip() for line in lines]
            if not force and lines == self.state.board_lines:
                self._pending = None
                return False
            if s.vestaboard_mode == "disabled":
                self._set_board(lines, s, source)
                self.state.vestaboard_error = None
                return True
            if (
                not force
                and self.state.board_sent_at
                and time.time() - self.state.board_sent_at < BOARD_MIN_GAP
            ):
                self._pending = (lines, source)  # retried on the next step
                return False
            grid = vestaboard.layout(lines, s.board_model, s.align)
            try:
                await self.board.send(grid, s)
            except VestaboardError as exc:
                self.state.vestaboard_error = str(exc)
                log.warning("%s", exc)
                return False
            self.state.vestaboard_error = None
            self._pending = None
            self._set_board(lines, s, source)
            log.info("Board updated: %s", " | ".join(lines))
            return True

    async def show_manual(self, lines: list[str], hold_minutes: float) -> None:
        """Show a custom message, pausing flight updates for ``hold_minutes``."""
        s = self.store.get()
        sent = await self.show(lines, s, source="manual", force=True)
        if not sent:
            raise VestaboardError(self.state.vestaboard_error or "Message was not sent")
        self.state.manual_until = time.time() + hold_minutes * 60 if hold_minutes > 0 else None
        self.wake()

    def resume(self) -> None:
        self.state.manual_until = None
        self.state.board_lines = None
        self.wake()

    def _set_board(self, lines: list[str], s: Settings, source: str) -> None:
        self.state.board_lines = lines
        self.state.board_grid = vestaboard.layout(lines, s.board_model, s.align)
        self.state.board_sent_at = time.time()
        self.state.board_source = source

    # ---- dashboard -----------------------------------------------------
    def snapshot(self) -> dict:
        s = self.store.get()
        st = self.state
        rows, cols = vestaboard.BOARD_SIZES[s.board_model]
        return {
            "status": st.status,
            "enabled": s.enabled,
            "last_poll": st.last_poll,
            "next_poll": st.next_poll,
            "errors": {
                "opensky": st.opensky_error,
                "flightaware": st.flightaware_error,
                "vestaboard": st.vestaboard_error,
                "weather": st.weather_error,
            },
            "opensky_credits_remaining": self.opensky.credits_remaining,
            "flightaware_requests": self.flightaware.requests_made,
            "nearby": [f.to_dict(s.radius_unit) for f in st.nearby],
            "current_icao24": st.current_icao24,
            "idle_in": round(self.idle_delay_left(s)) if not st.nearby else 0,
            "manual_until": st.manual_until,
            "board": {
                "rows": rows,
                "cols": cols,
                "lines": st.board_lines,
                "grid": st.board_grid,
                "sent_at": st.board_sent_at,
                "source": st.board_source,
                "mode": s.vestaboard_mode,
            },
            "location": {
                "latitude": s.latitude,
                "longitude": s.longitude,
                "radius_km": geo.to_km(s.radius, s.radius_unit),
                "unit": s.radius_unit,
            },
        }
