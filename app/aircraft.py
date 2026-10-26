"""ICAO aircraft type designators -> short, board-friendly model names.

FlightAware reports aircraft as ICAO type designators (e.g. ``B38M``). These are
mapped to the abbreviated names people actually use (``B737-8 MAX``). Every
name must fit on a single 15-character Vestaboard Note row.

ICAO designators can't distinguish every variant (an A321XLR files as ``A21N``),
so users can add their own overrides keyed by type designator or by tail
number/registration from the dashboard.
"""

from __future__ import annotations

import re

TYPE_NAMES: dict[str, str] = {
    # --- Airbus narrowbody ---
    "A318": "A318-100",
    "A319": "A319-100",
    "A320": "A320-200",
    "A321": "A321-200",
    "A19N": "A319neo",
    "A20N": "A320neo",
    "A21N": "A321neo",
    "BCS1": "A220-100",
    "BCS3": "A220-300",
    # --- Airbus widebody ---
    "A306": "A300-600",
    "A30B": "A300B4",
    "A310": "A310-300",
    "A332": "A330-200",
    "A333": "A330-300",
    "A337": "A330 BELUGAXL",
    "A338": "A330-800neo",
    "A339": "A330-900neo",
    "A342": "A340-200",
    "A343": "A340-300",
    "A345": "A340-500",
    "A346": "A340-600",
    "A359": "A350-900",
    "A35K": "A350-1000",
    "A388": "A380-800",
    "A3ST": "A300 BELUGA",
    # --- Boeing narrowbody ---
    "B712": "B717-200",
    "B721": "B727-100",
    "B722": "B727-200",
    "B732": "B737-200",
    "B733": "B737-300",
    "B734": "B737-400",
    "B735": "B737-500",
    "B736": "B737-600",
    "B737": "B737-700",
    "B738": "B737-800",
    "B739": "B737-900",
    "B37M": "B737-7 MAX",
    "B38M": "B737-8 MAX",
    "B39M": "B737-9 MAX",
    "B3XM": "B737-10 MAX",
    "B752": "B757-200",
    "B753": "B757-300",
    # --- Boeing widebody ---
    "B742": "B747-200",
    "B743": "B747-300",
    "B744": "B747-400",
    "B748": "B747-8",
    "B74S": "B747SP",
    "B762": "B767-200",
    "B763": "B767-300",
    "B764": "B767-400",
    "B772": "B777-200",
    "B77L": "B777-200LR",
    "B773": "B777-300",
    "B77W": "B777-300ER",
    "B778": "B777-8",
    "B779": "B777-9",
    "B788": "B787-8",
    "B789": "B787-9",
    "B78X": "B787-10",
    # --- McDonnell Douglas ---
    "DC10": "DC-10",
    "DC93": "DC-9-30",
    "DC95": "DC-9-50",
    "MD11": "MD-11",
    "MD81": "MD-81",
    "MD82": "MD-82",
    "MD83": "MD-83",
    "MD87": "MD-87",
    "MD88": "MD-88",
    "MD90": "MD-90",
    # --- Embraer ---
    "E135": "ERJ-135",
    "E145": "ERJ-145",
    "E45X": "ERJ-145XR",
    "E170": "E170",
    "E75L": "E175",
    "E75S": "E175",
    "E190": "E190",
    "E195": "E195",
    "E290": "E190-E2",
    "E295": "E195-E2",
    "E35L": "LEGACY 600",
    "E50P": "PHENOM 100",
    "E55P": "PHENOM 300",
    "E545": "PRAETOR 500",
    "E550": "PRAETOR 600",
    # --- Bombardier / De Havilland Canada ---
    "CRJ1": "CRJ-100",
    "CRJ2": "CRJ-200",
    "CRJ7": "CRJ-700",
    "CRJ9": "CRJ-900",
    "CRJX": "CRJ-1000",
    "DH8A": "DHC-8-100",
    "DH8B": "DHC-8-200",
    "DH8C": "DHC-8-300",
    "DH8D": "DHC-8-400",
    "DHC6": "DHC-6",
    "DHC7": "DHC-7",
    "CL30": "CL-300",
    "CL35": "CL-350",
    "CL60": "CL-600",
    "GLEX": "GLOBAL 6000",
    "GL5T": "GLOBAL 5000",
    "GL7T": "GLOBAL 7500",
    # --- ATR / Saab / other regional ---
    "AT43": "ATR42-300",
    "AT45": "ATR42-500",
    "AT46": "ATR42-600",
    "AT72": "ATR72-200",
    "AT75": "ATR72-500",
    "AT76": "ATR72-600",
    "SF34": "SAAB 340",
    "SB20": "SAAB 2000",
    "B190": "B1900D",
    "JS41": "JETSTREAM 41",
    "D328": "DO328",
    "J328": "DO328JET",
    "SU95": "SSJ100",
    "C919": "C919",
    "AJ27": "ARJ21",
    "F70": "FOKKER 70",
    "F100": "FOKKER 100",
    "RJ85": "AVRO RJ85",
    "RJ1H": "AVRO RJ100",
    # --- Business jets ---
    "C25A": "CJ2",
    "C25B": "CJ3",
    "C25C": "CJ4",
    "C25M": "CJ3+",
    "C510": "MUSTANG",
    "C525": "CJ1",
    "C550": "CITATION II",
    "C560": "CITATION V",
    "C56X": "CITATION XLS",
    "C650": "CITATION III",
    "C680": "CITATION SOV",
    "C68A": "LATITUDE",
    "C700": "LONGITUDE",
    "C750": "CITATION X",
    "GLF4": "G-IV",
    "GLF5": "G-V",
    "GLF6": "G650",
    "G150": "G150",
    "G280": "G280",
    "GA5C": "G500",
    "GA6C": "G600",
    "GA7C": "G700",
    "GA8C": "G800",
    "F2TH": "FALCON 2000",
    "F900": "FALCON 900",
    "FA7X": "FALCON 7X",
    "FA8X": "FALCON 8X",
    "FA6X": "FALCON 6X",
    "FA50": "FALCON 50",
    "LJ35": "LEARJET 35",
    "LJ45": "LEARJET 45",
    "LJ60": "LEARJET 60",
    "LJ75": "LEARJET 75",
    "H25B": "HAWKER 800",
    "HA4T": "HAWKER 4000",
    "HDJT": "HONDAJET",
    "PC12": "PC-12",
    "PC24": "PC-24",
    "SF50": "VISION JET",
    "TBM7": "TBM 700",
    "TBM8": "TBM 850",
    "TBM9": "TBM 900",
    "BE20": "KING AIR 200",
    "BE30": "KING AIR 300",
    "BE35": "BONANZA 35",
    "BE36": "BONANZA 36",
    "BE58": "BARON 58",
    "BE9L": "KING AIR 90",
    "B350": "KING AIR 350",
    # --- Light aircraft ---
    "C150": "C150",
    "C152": "C152",
    "C172": "C172",
    "C182": "C182",
    "C206": "C206",
    "C208": "C208 CARAVAN",
    "C210": "C210",
    "C310": "C310",
    "C337": "C337",
    "P28A": "PA-28",
    "P28R": "PA-28R",
    "P32R": "PA-32R",
    "PA34": "PA-34",
    "PA44": "PA-44",
    "PA46": "PA-46",
    "SR20": "SR20",
    "SR22": "SR22",
    "DA40": "DA40",
    "DA42": "DA42",
    "DA62": "DA62",
    "M20P": "M20",
    "M20T": "M20",
    # --- Military / cargo / special ---
    "C130": "C-130",
    "C30J": "C-130J",
    "C17": "C-17",
    "C5M": "C-5M",
    "K35R": "KC-135R",
    "KC46": "KC-46",
    "P8": "P-8A",
    "E3TF": "E-3",
    "A400": "A400M",
    "A124": "AN-124",
    "IL76": "IL-76",
    "B52": "B-52",
    "F16": "F-16",
    "F18S": "F/A-18",
    "F35": "F-35",
    "T38": "T-38",
    "V22": "V-22",
    # --- Helicopters ---
    "A109": "AW109",
    "A119": "AW119",
    "A139": "AW139",
    "A169": "AW169",
    "AS50": "AS350",
    "AS55": "AS355",
    "AS65": "AS365",
    "B06": "BELL 206",
    "B407": "BELL 407",
    "B412": "BELL 412",
    "B429": "BELL 429",
    "B505": "BELL 505",
    "EC20": "EC120",
    "EC30": "EC130",
    "EC35": "EC135",
    "EC45": "EC145",
    "EC55": "EC155",
    "EC75": "EC175",
    "H60": "UH-60",
    "R22": "R22",
    "R44": "R44",
    "R66": "R66",
    "S76": "S-76",
    "S92": "S-92",
}


# Manufacturer for each type, used for the long form ("AIRBUS A350-900") when it
# fits on the board. Types whose short name already includes the maker (ATR,
# SAAB, BELL, LEARJET, ...) or whose maker name is too long to ever fit
# (McDonnell Douglas) are left out.
_MAKERS: dict[str, tuple[str, ...]] = {
    "AIRBUS": (
        "A318", "A319", "A320", "A321", "A19N", "A20N", "A21N", "BCS1", "BCS3",
        "A306", "A30B", "A310", "A332", "A333", "A337", "A338", "A339", "A342",
        "A343", "A345", "A346", "A359", "A35K", "A388", "A3ST", "A400",
    ),
    "BOEING": (
        "B712", "B721", "B722", "B732", "B733", "B734", "B735", "B736", "B737",
        "B738", "B739", "B37M", "B38M", "B39M", "B3XM", "B752", "B753", "B742",
        "B743", "B744", "B748", "B74S", "B762", "B763", "B764", "B772", "B77L",
        "B773", "B77W", "B778", "B779", "B788", "B789", "B78X", "C17", "K35R",
        "KC46", "P8", "E3TF", "B52", "F18S",
    ),
    "EMBRAER": (
        "E135", "E145", "E45X", "E170", "E75L", "E75S", "E190", "E195", "E290",
        "E295", "E35L", "E50P", "E55P", "E545", "E550",
    ),
    "BOMBARDIER": (
        "CRJ1", "CRJ2", "CRJ7", "CRJ9", "CRJX", "CL30", "CL35", "CL60", "GLEX",
        "GL5T", "GL7T",
    ),
    "DE HAVILLAND": ("DH8A", "DH8B", "DH8C", "DH8D", "DHC6", "DHC7"),
    "BEECHCRAFT": ("B190", "BE20", "BE30", "BE35", "BE36", "BE58", "BE9L", "B350"),
    "CESSNA": (
        "C25A", "C25B", "C25C", "C25M", "C510", "C525", "C550", "C560", "C56X",
        "C650", "C680", "C68A", "C700", "C750", "C150", "C152", "C172", "C182",
        "C206", "C208", "C210", "C310", "C337",
    ),
    "GULFSTREAM": ("GLF4", "GLF5", "GLF6", "G150", "G280", "GA5C", "GA6C", "GA7C", "GA8C"),
    "DASSAULT": ("F2TH", "F900", "FA7X", "FA8X", "FA6X", "FA50"),
    "BAE": ("JS41",),
    "DORNIER": ("D328", "J328"),
    "SUKHOI": ("SU95",),
    "COMAC": ("C919", "AJ27"),
    "PILATUS": ("PC12", "PC24"),
    "CIRRUS": ("SR20", "SR22", "SF50"),
    "DAHER": ("TBM7", "TBM8", "TBM9"),
    "PIPER": ("P28A", "P28R", "P32R", "PA34", "PA44", "PA46"),
    "DIAMOND": ("DA40", "DA42", "DA62"),
    "MOONEY": ("M20P", "M20T"),
    "LOCKHEED": ("C130", "C30J", "C5M", "F16", "F35"),
    "ANTONOV": ("A124",),
    "ILYUSHIN": ("IL76",),
    "LEONARDO": ("A109", "A119", "A139", "A169"),
    "EUROCOPTER": ("AS50", "AS55", "AS65", "EC20", "EC30", "EC35", "EC45", "EC55", "EC75"),
    "SIKORSKY": ("H60", "S76", "S92"),
    "ROBINSON": ("R22", "R44", "R66"),
}
MANUFACTURERS: dict[str, str] = {code: maker for maker, codes in _MAKERS.items() for code in codes}

# Makers whose short names carry a one-letter prefix that reads oddly after the
# maker name: "B737-800" -> "BOEING 737-800", "C172" -> "CESSNA 172".
_MAKER_PREFIX = {"BOEING": "B", "BEECHCRAFT": "B", "CESSNA": "C"}


def parse_overrides(text: str) -> dict[str, str]:
    """Parse ``KEY=NAME`` lines (blank lines and ``#`` comments ignored)."""
    overrides: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, name = line.split("=", 1)
        key, name = key.strip().upper(), name.strip()
        if key and name:
            overrides[key] = name
    return overrides


def short_name(
    icao_type: str | None,
    registration: str | None = None,
    overrides: dict[str, str] | None = None,
) -> str:
    """Return the short model name for an aircraft.

    Lookup order: registration override, type override, built-in table, then the
    raw ICAO designator so the board always shows *something*.
    """
    overrides = overrides or {}
    reg = (registration or "").strip().upper()
    if reg and reg in overrides:
        return overrides[reg]
    code = (icao_type or "").strip().upper()
    if not code:
        return ""
    return overrides.get(code) or TYPE_NAMES.get(code) or code


def long_name(icao_type: str | None, short: str) -> str:
    """The model with its manufacturer ("AIRBUS A350-900"), or "" if unknown.

    ``short`` is the result of :func:`short_name`, so overrides are respected.
    """
    maker = MANUFACTURERS.get((icao_type or "").strip().upper())
    if not maker or not short:
        return ""
    if short.upper().startswith(maker.split()[0]):
        return short
    prefix = _MAKER_PREFIX.get(maker)
    model = short[1:] if prefix and re.match(rf"{prefix}\d", short) else short
    return f"{maker} {model}"
