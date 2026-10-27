from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.flightaware import API_URL, FlightAwareClient, airport_code, covering_leg, pick_current_flight

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def leg(off=None, on=None, sched_off=None, **kw):
    return {"actual_off": off and iso(off), "actual_on": on and iso(on),
            "scheduled_off": sched_off and iso(sched_off), **kw}


def test_pick_airborne_leg():
    flights = [
        leg(sched_off=NOW + timedelta(hours=20), ident="next"),
        leg(off=NOW - timedelta(hours=1), ident="live"),
        leg(off=NOW - timedelta(hours=26), on=NOW - timedelta(hours=22), ident="yesterday"),
    ]
    assert pick_current_flight(flights, NOW.timestamp())["ident"] == "live"


def test_pick_nearest_when_none_airborne():
    flights = [
        leg(sched_off=NOW + timedelta(hours=20), ident="tomorrow"),
        leg(sched_off=NOW - timedelta(minutes=10), ident="now"),
        leg(sched_off=NOW - timedelta(minutes=5), ident="cx", cancelled=True),
    ]
    assert pick_current_flight(flights, NOW.timestamp())["ident"] == "now"


def test_airport_code_prefers_iata():
    assert airport_code({"code": "KSFO", "code_iata": "SFO", "code_icao": "KSFO"}) == "SFO"
    assert airport_code({"code": "0S9", "code_lid": "0S9", "code_iata": None}) == "0S9"
    assert airport_code(None) is None


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def clock(monkeypatch):
    """A controllable clock for the FlightAware client, starting at NOW."""
    state = {"now": NOW.timestamp()}
    monkeypatch.setattr("app.flightaware.time.time", lambda: state["now"])

    def set_to(dt):
        state["now"] = dt.timestamp()

    return set_to


def daily(day_offset, reg=None, airborne=False):
    """One leg of a daily UA123 SFO-JFK departing 17:00 UTC, arriving 22:00 UTC."""
    off = NOW.replace(hour=17) + timedelta(days=day_offset)
    flight = {"ident": "UAL123", "ident_iata": "UA123", "aircraft_type": "B38M",
              "origin": {"code_iata": "SFO", "code_icao": "KSFO", "city": "San Francisco", "timezone": "x"},
              "destination": {"code_iata": "JFK", "city": "New York"},
              "scheduled_off": iso(off), "scheduled_on": iso(off + timedelta(hours=5)),
              "registration": reg, "baggage_claim": "7"}
    if airborne:
        flight["actual_off"] = iso(off)
    return flight


SCHEDULE = {"flights": [daily(2), daily(1), daily(0, reg="N37502", airborne=True), daily(-1, reg="N37510")]}


@pytest.mark.anyio
@respx.mock
async def test_lookup_is_cached(clock):
    route = respx.get(f"{API_URL}/flights/UAL123").mock(return_value=httpx.Response(200, json=SCHEDULE))
    async with httpx.AsyncClient() as http:
        client = FlightAwareClient(http)
        info = await client.lookup("UAL123", "key")
        again = await client.lookup("UAL123", "key")
    assert info.ident_iata == "UA123" and info.origin == "SFO" and info.destination == "JFK"
    assert info.registration == "N37502"
    assert again == info
    assert info.codeshares_iata == []
    assert route.call_count == 1
    assert route.calls[0].request.headers["x-apikey"] == "key"


@pytest.mark.anyio
@respx.mock
async def test_tomorrows_flight_comes_from_the_cache(clock, tmp_path):
    route = respx.get(f"{API_URL}/flights/UAL123").mock(return_value=httpx.Response(200, json=SCHEDULE))
    path = tmp_path / "fa.json"
    async with httpx.AsyncClient() as http:
        client = FlightAwareClient(http, path)
        await client.lookup("UAL123", "key")  # today, 18:00 UTC: one paid call

        clock(NOW + timedelta(days=1))  # same flight passes over again tomorrow
        tomorrow = await client.lookup("UAL123", "key")
        assert tomorrow.origin == "SFO" and tomorrow.registration is None
        assert route.call_count == 1 and client.cache_hits == 1
        await client.lookup("UAL123", "key")  # later polls of the same leg aren't double counted
        assert client.cache_hits == 1

        # A restart keeps the cache: the day after tomorrow is still free
        restarted = FlightAwareClient(http, path)
        clock(NOW + timedelta(days=2))
        assert (await restarted.lookup("UAL123", "key")).destination == "JFK"
        assert route.call_count == 1

        # Outside the cached schedule's window, it's looked up again
        clock(NOW + timedelta(days=3))
        await restarted.lookup("UAL123", "key")
        assert route.call_count == 2
    cached = path.read_text()
    assert "baggage_claim" not in cached and '"timezone"' not in cached  # unused fields aren't stored


@pytest.mark.anyio
@respx.mock
async def test_refreshes_once_for_a_missing_registration(clock):
    route = respx.get(f"{API_URL}/flights/UAL123").mock(return_value=httpx.Response(200, json=SCHEDULE))
    async with httpx.AsyncClient() as http:
        client = FlightAwareClient(http)
        await client.lookup("UAL123", "key")
        clock(NOW + timedelta(days=1))
        # Tomorrow's leg had no registration when cached; the board wants one, so refetch...
        await client.lookup("UAL123", "key", need_registration=True)
        assert route.call_count == 2
        # ...but only once, even though FlightAware (here) still doesn't know it
        await client.lookup("UAL123", "key", need_registration=True)
        assert route.call_count == 2


def test_covering_leg_picks_the_leg_in_the_air():
    legs = SCHEDULE["flights"]
    at = lambda dt: covering_leg(legs, dt.timestamp())  # noqa: E731
    assert at(NOW)["registration"] == "N37502"  # today's leg, 17:00-22:00
    assert at(NOW + timedelta(days=-1))["registration"] == "N37510"
    assert at(NOW.replace(hour=22, minute=20)) is not None  # just landed: within the margin
    assert at(NOW.replace(hour=23, minute=30)) is None  # long gone
    assert at(NOW.replace(hour=12)) is None  # hours before departure
    # Two legs under one callsign (A-B, then B-C): the one in the air wins
    multi = [
        {"ident": "SWA1", "scheduled_off": iso(NOW.replace(hour=10)), "scheduled_on": iso(NOW.replace(hour=12)),
         "destination": {"code_iata": "MDW"}},
        {"ident": "SWA1", "scheduled_off": iso(NOW.replace(hour=13)), "scheduled_on": iso(NOW.replace(hour=15)),
         "destination": {"code_iata": "DEN"}},
    ]
    assert covering_leg(multi, NOW.replace(hour=11).timestamp())["destination"]["code_iata"] == "MDW"
    assert covering_leg(multi, NOW.replace(hour=12, minute=50).timestamp())["destination"]["code_iata"] == "DEN"
    assert covering_leg(multi, NOW.replace(hour=14).timestamp())["destination"]["code_iata"] == "DEN"
