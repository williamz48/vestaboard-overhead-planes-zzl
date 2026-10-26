from app import aircraft, airlines, vestaboard
from app.tracker import TrackedFlight, board_lines, route_line


def test_all_aircraft_names_fit_on_a_note():
    for code, name in aircraft.TYPE_NAMES.items():
        assert len(name) <= 15, (code, name)
        assert len(vestaboard.encode_text(name)) == len(name)
        assert all(c != 0 or ch == " " for c, ch in zip(vestaboard.encode_text(name), name)), name


def test_short_names():
    assert aircraft.short_name("B38M") == "B737-8 MAX"
    assert aircraft.short_name("B738") == "B737-800"
    assert aircraft.short_name("A320") == "A320-200"
    assert aircraft.short_name("DH8D") == "DHC-8-400"
    assert aircraft.short_name("ZZZZ") == "ZZZZ"
    assert aircraft.short_name(None) == ""


def test_overrides():
    overrides = aircraft.parse_overrides("A21N=A321XLR\n# comment\nn123ab = A321LR\nbad line")
    assert overrides == {"A21N": "A321XLR", "N123AB": "A321LR"}
    assert aircraft.short_name("A21N", None, overrides) == "A321XLR"
    assert aircraft.short_name("A21N", "N123AB", overrides) == "A321LR"


def test_iata_flight_numbers():
    assert airlines.iata_flight_number("UAL123") == "UA123"
    assert airlines.iata_flight_number("DAL0042 ") == "DL42"
    assert airlines.iata_flight_number("SWA4AB") == "WN4AB"
    assert airlines.iata_flight_number("N123AB") == "N123AB"
    assert airlines.iata_flight_number("XYZ123") == "XYZ123"
    assert airlines.is_airline_callsign("JBU1")
    assert not airlines.is_airline_callsign("N123AB")


def test_encode_and_layout():
    assert vestaboard.encode_text("Ab1-0") == [1, 2, 27, 44, 36]
    assert vestaboard.encode_text("{63}X~") == [63, 24, 0]
    grid = vestaboard.layout(["UA123", "SFO - JFK", "B737-8 MAX"], "note", "center")
    assert len(grid) == 3 and all(len(r) == 15 for r in grid)
    assert vestaboard.grid_to_text(grid) == ["     UA123     ", "   SFO - JFK   ", "  B737-8 MAX   "]
    flagship = vestaboard.layout(["A", "B", "C"], "flagship", "left")
    assert len(flagship) == 6 and len(flagship[0]) == 22
    assert vestaboard.grid_to_text(flagship)[1].startswith("A")


def test_local_base_url():
    assert vestaboard.local_base_url("192.168.1.5") == "http://192.168.1.5:7000"
    assert vestaboard.local_base_url("http://vb.local:8000/") == "http://vb.local:8000"


def _flight(**kw):
    base = dict(icao24="abc", callsign="UAL123", latitude=0, longitude=0, altitude_ft=1000,
                speed_kt=200, heading=0, on_ground=False, distance_km=1, bearing="N")
    base.update(kw)
    return TrackedFlight(**base)


def test_board_lines():
    f = _flight(flight="UA123", origin="SFO", destination="JFK", aircraft="B737-8 MAX")
    assert board_lines(f, 15) == ["UA123", "SFO - JFK", "B737-8 MAX"]
    assert route_line("KSFO", None, 15) == "KSFO - ???"
    assert route_line(None, None, 15) == ""
    assert route_line("ABCDEFG", "HIJKLMN", 15) == "ABCDEFG-HIJKLMN"
