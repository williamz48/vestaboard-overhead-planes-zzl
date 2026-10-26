from app import aircraft, airlines, vestaboard
from app.tracker import TrackedFlight, aircraft_line, board_lines, route_line


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


def test_chinese_airlines():
    assert airlines.iata_flight_number("CHH7981") == "HU7981"
    assert airlines.iata_flight_number("CSC8633") == "3U8633"
    assert airlines.iata_flight_number("CQH8501") == "9C8501"
    assert airlines.iata_flight_number("CRK621") == "HX621"
    assert airlines.iata_flight_number("CPA880") == "CX880"


def test_airline_colors():
    assert airlines.airline_color("UAL1") == 67
    assert airlines.airline_color("DAL1") == 63
    assert airlines.airline_color("CPA880") == 66
    assert airlines.airline_color("N123AB") is None
    overrides = aircraft.parse_overrides("AA=red\nSWA=none")
    assert airlines.airline_color("AAL1", "AA1", overrides) == 63
    assert airlines.airline_color("SWA1", "WN1", overrides) is None
    # IATA override for an airline that isn't in the ICAO table
    assert airlines.airline_color("XYZ1", "XY1", aircraft.parse_overrides("XY=GREEN")) == 66
    for code in airlines.AIRLINE_COLORS.values():
        assert code in airlines.COLOR_CODES


def test_edge_tiles():
    row = vestaboard.with_edge_tiles("UA1234", 67, 15)
    grid = vestaboard.layout([row, "SFO - JFK", "B737-8 MAX"], "note", "center")
    assert grid[0][0] == grid[0][14] == 67
    assert vestaboard.grid_to_text(grid)[0] == "*   UA1234    *"
    # text stays where it would be without the tiles
    plain = vestaboard.layout(["UA1234"], "note", "center")
    assert vestaboard.grid_to_text(plain)[1] == "    UA1234     "
    left = vestaboard.layout([vestaboard.with_edge_tiles("UA1", 63, 15, "left")], "note", "left")
    assert vestaboard.grid_to_text(left)[1] == "* UA1         *"
    flagship = vestaboard.layout([vestaboard.with_edge_tiles("DL1", 63, 22)], "flagship")
    assert flagship[2][0] == flagship[2][21] == 63


def test_board_lines_with_color():
    f = _flight(flight="UA123", origin="SFO", destination="JFK", aircraft="B737-8 MAX", color=67)
    assert board_lines(f, 15)[0] == "{67}    UA123    {67}"
    assert board_lines(f, 15, colors=False)[0] == "UA123"


def test_long_names():
    long = lambda code: aircraft.long_name(code, aircraft.short_name(code))  # noqa: E731
    assert long("A359") == "AIRBUS A350-900"
    assert long("B789") == "BOEING 787-9"
    assert long("B38M") == "BOEING 737-8 MAX"
    assert long("E75L") == "EMBRAER E175"
    assert long("DH8D") == "DE HAVILLAND DHC-8-400"
    assert long("C172") == "CESSNA 172"
    assert long("B190") == "BEECHCRAFT 1900D"
    assert long("AT76") == ""  # "ATR72-600" already names the maker
    assert long("ZZZZ") == ""
    # overrides keep the maker from the type code
    assert aircraft.long_name("A21N", "A321XLR") == "AIRBUS A321XLR"
    for code in aircraft.MANUFACTURERS:
        name = long(code)
        assert len(vestaboard.encode_text(name)) == len(name)
        assert all(c != 0 or ch == " " for c, ch in zip(vestaboard.encode_text(name), name)), name


def test_board_lines_manufacturer_when_it_fits():
    fits = _flight(aircraft="A350-900", aircraft_long="AIRBUS A350-900")
    assert board_lines(fits, 15)[2] == "AIRBUS A350-900"
    assert board_lines(fits, 15, manufacturer=False)[2] == "A350-900"
    too_long = _flight(aircraft="B737-8 MAX", aircraft_long="BOEING 737-8 MAX")
    assert board_lines(too_long, 15)[2] == "B737-8 MAX"
    assert board_lines(too_long, 22)[2] == "BOEING 737-8 MAX"  # Flagship has room
    unknown_maker = _flight(aircraft="ATR72-600")
    assert board_lines(unknown_maker, 15)[2] == "ATR72-600"


def test_regionals_merge_into_mainline():
    for regional, mainlines in airlines.REGIONAL_MAINLINE.items():
        assert all(m in airlines.ICAO_TO_IATA for m in mainlines), regional
    # Single-brand regionals always show as the mainline
    assert airlines.iata_flight_number("QLK1567") == "QF1567"
    assert airlines.iata_flight_number("ENY3456") == "AA3456"
    assert airlines.iata_flight_number("EDV5034") == "DL5034"
    assert airlines.iata_flight_number("JZA8123") == "AC8123"
    assert airlines.iata_flight_number("KLC1234") == "KL1234"
    # FlightAware's number wins when it names the mainline, or is re-prefixed when it doesn't
    assert airlines.iata_flight_number("QLK117D", "QF2117") == "QF2117"
    assert airlines.iata_flight_number("ENY3456", "MQ3456") == "AA3456"
    assert airlines.iata_flight_number("QLK117D", None, ["QF2117"]) == "QF2117"
    # Multi-brand regionals need FlightAware to say which mainline they fly for
    assert airlines.iata_flight_number("SKW5432") == "OO5432"
    assert airlines.iata_flight_number("SKW5432", "OO5432") == "OO5432"
    assert airlines.iata_flight_number("SKW5432", "OO5432", ["AC5555", "UA5432"]) == "UA5432"
    assert airlines.iata_flight_number("SKW3901", "DL3901") == "DL3901"
    # Mainline and unknown airlines are unaffected
    assert airlines.iata_flight_number("BAW12A", "BA112") == "BA112"
    assert airlines.iata_flight_number("XYZ123") == "XYZ123"


def test_regionals_take_mainline_color():
    assert airlines.airline_color("QLK1567", "QF1567") == 63  # Qantas red
    assert airlines.airline_color("ENY3456", "AA3456") == 67  # American blue
    assert airlines.airline_color("SKW3901", "DL3901") == 63  # Delta red
    assert airlines.airline_color("SKW5432", "OO5432") is None  # brand unknown
    assert airlines.airline_color("QLK1567", "QF1567", aircraft.parse_overrides("QLK=GREEN")) == 66


def test_aircraft_row_modes():
    a350 = _flight(aircraft="A350-900", aircraft_long="AIRBUS A350-900", aircraft_type="A359",
                   registration="N501DN")
    assert aircraft_line(a350, 15) == "AIRBUS A350-900"
    assert aircraft_line(a350, 15, "icao_registration") == "A359 N501DN"
    assert aircraft_line(a350, 15, "model_registration") == "A350-900 N501DN"
    assert aircraft_line(a350, 22, "model_registration") == "AIRBUS A350-900 N501DN"
    assert aircraft_line(a350, 22, "model_registration", manufacturer=False) == "A350-900 N501DN"

    max8 = _flight(aircraft="B737-8 MAX", aircraft_long="BOEING 737-8 MAX", aircraft_type="B38M",
                   registration="VH-8IA")
    # "B737-8 MAX VH-8IA" is 17 characters, so the ICAO designator stands in for the model
    assert aircraft_line(max8, 15, "model_registration") == "B38M VH-8IA"
    assert aircraft_line(max8, 22, "model_registration") == "B737-8 MAX VH-8IA"

    no_reg = _flight(aircraft="E175", aircraft_type="E75L")
    assert aircraft_line(no_reg, 15, "icao_registration") == "E75L"
    assert aircraft_line(no_reg, 15, "model_registration") == "E175"
    assert aircraft_line(_flight(), 15, "icao_registration") == ""

    assert board_lines(a350, 15, aircraft_mode="icao_registration")[2] == "A359 N501DN"
