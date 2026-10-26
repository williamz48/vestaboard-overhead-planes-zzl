from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.flightaware import API_URL, FlightAwareClient, airport_code, pick_current_flight

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


@pytest.mark.anyio
@respx.mock
async def test_lookup_is_cached():
    route = respx.get(f"{API_URL}/flights/UAL123").mock(return_value=httpx.Response(200, json={"flights": [
        {"ident": "UAL123", "ident_iata": "UA123", "aircraft_type": "B38M", "actual_off": "2026-10-26T17:00:00Z",
         "actual_on": None, "origin": {"code_iata": "SFO"}, "destination": {"code_iata": "JFK"}},
    ]}))
    async with httpx.AsyncClient() as http:
        client = FlightAwareClient(http)
        info = await client.lookup("UAL123", "key")
        again = await client.lookup("UAL123", "key")
    assert info.ident_iata == "UA123" and info.origin == "SFO" and info.destination == "JFK"
    assert again is info
    assert info.codeshares_iata == []
    assert route.call_count == 1
    assert route.calls[0].request.headers["x-apikey"] == "key"


@pytest.fixture
def anyio_backend():
    return "asyncio"
