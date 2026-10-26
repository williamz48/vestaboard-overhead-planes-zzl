import httpx
import pytest
import respx

from app.config import SECRET_MASK, Settings, SettingsStore
from app.flightaware import API_URL as FA_URL, FlightAwareClient
from app.opensky import API_URL as OS_URL, TOKEN_URL, OpenSkyClient
from app.tracker import Tracker
from app.vestaboard import CLOUD_URL, VestaboardClient, grid_to_text


def state(icao, callsign, lat, lon, alt_m=1500.0, ground=False):
    return [icao, callsign.ljust(8), "United States", 0, 0, lon, lat, alt_m, ground, 120.0, 90.0,
            0.0, None, alt_m, "1200", False, 0]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store(tmp_path):
    s = SettingsStore(tmp_path / "settings.json")
    s.update({
        "latitude": 40.0, "longitude": -75.0, "radius": 10, "radius_unit": "mi",
        "opensky_client_id": "id", "opensky_client_secret": "secret",
        "flightaware_api_key": "fa-key", "vestaboard_mode": "cloud", "vestaboard_cloud_token": "tok",
    })
    return s


def test_secrets_are_masked_and_preserved(store):
    masked = store.get().masked()
    assert masked["flightaware_api_key"] == SECRET_MASK
    store.update({"flightaware_api_key": SECRET_MASK, "radius": 3})
    assert store.get().flightaware_api_key == "fa-key"
    assert store.get().radius == 3


def test_env_seeding(tmp_path, monkeypatch):
    monkeypatch.setenv("LATITUDE", "51.47")
    monkeypatch.setenv("VESTABOARD_MODE", "local")
    s = SettingsStore(tmp_path / "seeded.json").get()
    assert s.latitude == 51.47 and s.vestaboard_mode == "local"


@pytest.mark.anyio
@respx.mock
async def test_end_to_end(store):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "abc", "expires_in": 1800}))
    states = respx.get(f"{OS_URL}/states/all").mock(return_value=httpx.Response(
        200,
        headers={"X-Rate-Limit-Remaining": "3999"},
        json={"time": 0, "states": [
            state("a1", "DAL42", 40.05, -75.0),          # ~3.5 mi
            state("a2", "UAL123", 40.01, -75.0),         # ~0.7 mi - closest
            state("a3", "N123AB", 40.0, -75.01, ground=True),
            state("a4", "AAL1", 41.0, -75.0),            # ~69 mi, outside radius
        ]},
    ))
    fa = respx.get(f"{FA_URL}/flights/UAL123").mock(return_value=httpx.Response(200, json={"flights": [{
        "ident": "UAL123", "ident_iata": "UA123", "aircraft_type": "B38M", "registration": "N37502",
        "actual_off": "2026-10-26T17:00:00Z", "actual_on": None,
        "origin": {"code_iata": "EWR", "code_icao": "KEWR"}, "destination": {"code_iata": "SFO"},
    }]}))
    board = respx.post(CLOUD_URL).mock(return_value=httpx.Response(200, json={}))

    async with httpx.AsyncClient() as http:
        tracker = Tracker(store, OpenSkyClient(http), FlightAwareClient(http), VestaboardClient(http))
        await tracker.step()

        assert states.calls[0].request.headers["Authorization"] == "Bearer abc"
        assert [f.callsign for f in tracker.state.nearby] == ["UAL123", "DAL42"]
        assert tracker.opensky.credits_remaining == 3999
        assert fa.call_count == 1
        assert board.call_count == 1
        sent = board.calls[0].request
        assert sent.headers["X-Vestaboard-Token"] == "tok"
        assert grid_to_text(httpx.Response(200, content=sent.content).json()) == [
            "*    UA123    *", "   EWR - SFO   ", "  B737-8 MAX   ",
        ]
        grid = httpx.Response(200, content=sent.content).json()
        assert grid[0][0] == grid[0][14] == 67  # United blue

        # A second step with identical data must not re-send to the board or re-query FlightAware.
        await tracker.step()
        assert board.call_count == 1
        assert fa.call_count == 1
        snap = tracker.snapshot()
        assert snap["current_icao24"] == "a2"
        assert snap["nearby"][0]["flight"] == "UA123"


@pytest.mark.anyio
@respx.mock
async def test_idle_message(store):
    store.update({"opensky_client_id": "", "opensky_client_secret": "", "idle_message": "NO PLANES\n{66}"})
    respx.get(f"{OS_URL}/states/all").mock(return_value=httpx.Response(200, json={"time": 0, "states": None}))
    board = respx.post(CLOUD_URL).mock(return_value=httpx.Response(200, json={}))
    async with httpx.AsyncClient() as http:
        tracker = Tracker(store, OpenSkyClient(http), FlightAwareClient(http), VestaboardClient(http))
        await tracker.step()
    assert board.call_count == 1
    assert grid_to_text(httpx.Response(200, content=board.calls[0].request.content).json())[:2] == [
        "   NO PLANES   ", "       *       ",
    ]


@pytest.mark.anyio
@respx.mock
async def test_opensky_429(store):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "abc"}))
    respx.get(f"{OS_URL}/states/all").mock(return_value=httpx.Response(
        429, headers={"X-Rate-Limit-Retry-After-Seconds": "900"}))
    board = respx.post(CLOUD_URL).mock(return_value=httpx.Response(200, json={}))
    async with httpx.AsyncClient() as http:
        tracker = Tracker(store, OpenSkyClient(http), FlightAwareClient(http), VestaboardClient(http))
        delay = await tracker.step()
    assert "rate limit" in tracker.state.opensky_error
    assert delay > 800
    assert board.call_count == 0  # don't replace the board with the idle message on errors
