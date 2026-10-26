"""Background loop: poll OpenSky, pick a flight, enrich it, push it to the board."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field

from . import aircraft, airlines, geo, vestaboard
from .config import Settings, SettingsStore
from .flightaware import FlightAwareClient, FlightAwareError, FlightInfo
from .opensky import Aircraft, OpenSkyClient, OpenSkyError
from .vestaboard import VestaboardClient, VestaboardError

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
        if info.ident_iata:
            flight.flight = info.ident_iata.upper()
        flight.origin = info.origin
        flight.destination = info.destination
        flight.origin_name = info.origin_name
        flight.destination_name = info.destination_name
        flight.aircraft_type = info.aircraft_type
        flight.registration = info.registration
        flight.airline = info.operator
    flight.aircraft = aircraft.short_name(flight.aircraft_type, flight.registration, overrides)
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


def route_line(origin: str | None, destination: str | None, width: int) -> str:
    if not origin and not destination:
        return ""
    o, d = origin or "???", destination or "???"
    text = f"{o} - {d}"
    return text if len(text) <= width else vestaboard.fit(f"{o}-{d}", width)


def board_lines(
    flight: TrackedFlight, width: int, colors: bool = True, align: str = "center"
) -> list[str]:
    """Line 1: flight number, line 2: ORIGIN - DESTINATION, line 3: aircraft model.

    With ``colors``, the flight number row gets the airline's color at both ends.
    """
    number = flight.flight or flight.callsign
    first = (
        vestaboard.with_edge_tiles(number, flight.color, width, align)
        if colors and flight.color is not None
        else vestaboard.fit(number, width)
    )
    return [
        first,
        route_line(flight.origin, flight.destination, width),
        vestaboard.fit(flight.aircraft, width),
    ]


@dataclass
class TrackerState:
    status: str = "starting"
    last_poll: float | None = None
    next_poll: float | None = None
    opensky_error: str | None = None
    flightaware_error: str | None = None
    vestaboard_error: str | None = None
    nearby: list[TrackedFlight] = field(default_factory=list)
    current_icao24: str | None = None
    current_since: float | None = None
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
    ):
        self.store = store
        self.opensky = opensky
        self.flightaware = flightaware
        self.board = board
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
        return max(1.0, min(waits))

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
            self.state.current_icao24 = None
            self.state.current_since = None
            if s.idle_action == "message" and s.idle_message.strip():
                lines = s.idle_message.upper().splitlines()[:rows]
                await self.show(lines, s, source="idle")
            return

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

        lines = board_lines(target, cols, s.airline_colors, s.align)
        await self.show(lines, s, source=target.icao24)

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
            },
            "opensky_credits_remaining": self.opensky.credits_remaining,
            "flightaware_requests": self.flightaware.requests_made,
            "nearby": [f.to_dict(s.radius_unit) for f in st.nearby],
            "current_icao24": st.current_icao24,
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
