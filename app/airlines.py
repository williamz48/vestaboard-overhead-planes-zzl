"""ICAO airline designators -> IATA codes.

ADS-B callsigns use the 3-letter ICAO airline code (``UAL123``). FlightAware
normally gives us the IATA flight number directly; this table is the fallback
when FlightAware is not configured or doesn't know the flight.
"""

from __future__ import annotations

import re

ICAO_TO_IATA: dict[str, str] = {
    # United States
    "AAL": "AA", "UAL": "UA", "DAL": "DL", "SWA": "WN", "ASA": "AS",
    "JBU": "B6", "NKS": "NK", "FFT": "F9", "HAL": "HA", "AAY": "G4",
    "SCX": "SY", "MXY": "MX", "VXP": "XP", "SKW": "OO", "RPA": "YX",
    "ENY": "MQ", "EDV": "9E", "ASH": "YV", "PDT": "PT", "JIA": "OH",
    "GJS": "G7", "QXE": "QX", "AWI": "ZW", "UCA": "C5", "SIL": "3M",
    "FDX": "FX", "UPS": "5X", "GTI": "5Y", "ABX": "GB",
    "ATN": "8C", "CKS": "K4", "PAC": "PO", "SOO": "9S", "AJT": "M6",
    # Canada / Mexico / Latin America
    "ACA": "AC", "JZA": "QK", "ROU": "RV", "WJA": "WS", "WEN": "WR",
    "POE": "PD", "FLE": "F8", "TSC": "TS", "AMX": "AM", "VOI": "Y4",
    "VIV": "VB", "CMP": "CM", "AVA": "AV", "LAN": "LA", "TAM": "JJ",
    "GLO": "G3", "AZU": "AD", "ARG": "AR", "JAT": "JA", "BWA": "BW", "LRC": "LR",
    # Europe
    "BAW": "BA", "VIR": "VS", "DLH": "LH", "AFR": "AF", "KLM": "KL",
    "IBE": "IB", "ITY": "AZ", "SAS": "SK", "FIN": "AY", "EIN": "EI",
    "RYR": "FR", "EZY": "U2", "EJU": "EC", "WZZ": "W6", "SWR": "LX",
    "AUA": "OS", "TAP": "TP", "ICE": "FI", "CFG": "DE", "EWG": "EW",
    "BEL": "SN", "LOT": "LO", "AEA": "UX", "VLG": "VY", "NAX": "DY",
    "NOZ": "DY", "TRA": "HV", "TVF": "TO", "SHT": "BA", "CLX": "CV",
    "THY": "TK", "PGT": "PC", "AEE": "A3", "LOG": "LM", "EXS": "LS",
    # Middle East / Africa
    "UAE": "EK", "QTR": "QR", "ETD": "EY", "SVA": "SV", "ELY": "LY",
    "GFA": "GF", "OMA": "WY", "RJA": "RJ", "MSR": "MS", "ETH": "ET", "AIZ": "IZ",
    "KQA": "KQ", "RAM": "AT", "SAA": "SA", "FDB": "FZ",
    # Asia / Pacific
    "SIA": "SQ", "JAL": "JL", "ANA": "NH", "KAL": "KE",
    "AAR": "OZ", "QFA": "QF", "ANZ": "NZ",
    "VOZ": "VA", "JST": "JQ", "AIC": "AI", "IGO": "6E", "PAL": "PR",
    "CEB": "5J", "HVN": "VN", "THA": "TG", "MAS": "MH", "GIA": "GA",
    "AXM": "AK", "SCO": "TR", "ZIP": "ZG", "DHK": "D0", "BCS": "QY",
    "VJC": "VJ", "KXP": "KR", "BOX": "3S",
    # Mainland China
    "CCA": "CA", "CES": "MU", "CSN": "CZ", "CHH": "HU", "CSZ": "ZH",
    "CSC": "3U", "CXA": "MF", "CDG": "SC", "CSH": "FM", "CQH": "9C",
    "DKH": "HO", "GCR": "GS", "CBJ": "JD", "LKE": "8L", "CHB": "PN",
    "UEA": "EU", "KNA": "KY", "CDC": "GJ", "QDA": "QW", "HBH": "NS",
    "CQN": "OQ", "HXA": "G5", "TBA": "TV", "CUA": "KN", "OKA": "BK",
    "JYH": "AQ", "RLH": "DR", "CJX": "RY", "CBG": "GX", "FZA": "FU",
    "CUH": "UQ", "CGZ": "GY", "JOY": "JR", "EPA": "DZ", "CGN": "9H",
    "CGH": "GT", "CCD": "CA", "CNM": "CA", "CKK": "CK", "CAO": "CA",
    "CSS": "O3", "YZR": "Y8", "CYZ": "CF",
    # Hong Kong / Macau / Taiwan
    "CPA": "CX", "HKE": "UO", "CRK": "HX", "HGB": "HB", "AHK": "LD",
    "AMU": "NX", "CAL": "CI", "EVA": "BR", "SJX": "JX", "TTW": "IT",
    "MDA": "AE", "UIA": "B7", "FEA": "FE",
}

_CALLSIGN_RE = re.compile(r"^([A-Z]{3})0*(\d[0-9A-Z]*)$")


def iata_flight_number(callsign: str | None) -> str:
    """Best-effort conversion of an ICAO callsign to an IATA flight number.

    ``UAL0123`` -> ``UA123``. Unknown airlines and registrations (``N123AB``)
    are returned unchanged.
    """
    cs = (callsign or "").strip().upper()
    match = _CALLSIGN_RE.match(cs)
    if match and match.group(1) in ICAO_TO_IATA:
        return ICAO_TO_IATA[match.group(1)] + match.group(2)
    return cs


def is_airline_callsign(callsign: str | None) -> bool:
    """True for scheduled/charter style callsigns (``DAL1234``), not tail numbers."""
    return bool(_CALLSIGN_RE.match((callsign or "").strip().upper()))


# Vestaboard color tiles: closest match to each airline's brand color.
COLOR_CODES = {
    "RED": 63, "ORANGE": 64, "YELLOW": 65, "GREEN": 66,
    "BLUE": 67, "VIOLET": 68, "PURPLE": 68, "WHITE": 69, "BLACK": 70,
}

AIRLINE_COLORS: dict[str, str] = {
    # United States (regionals flying a single brand take that brand's color)
    "AAL": "BLUE", "ENY": "BLUE", "PDT": "BLUE", "JIA": "BLUE",
    "UAL": "BLUE", "GJS": "BLUE", "UCA": "BLUE", "ASH": "BLUE", "AWI": "BLUE",
    "DAL": "RED", "EDV": "RED",
    "SWA": "BLUE", "ASA": "BLUE", "QXE": "BLUE", "JBU": "BLUE", "MXY": "BLUE",
    "NKS": "YELLOW", "FFT": "GREEN", "HAL": "VIOLET", "AAY": "ORANGE",
    "SCX": "ORANGE", "VXP": "VIOLET", "FDX": "VIOLET", "UPS": "YELLOW",
    "CKS": "RED", "DHK": "YELLOW", "BCS": "YELLOW",
    # Canada / Mexico / Latin America
    "ACA": "RED", "JZA": "RED", "ROU": "RED", "WJA": "BLUE", "WEN": "BLUE",
    "POE": "BLUE", "FLE": "VIOLET", "TSC": "BLUE", "AMX": "BLUE",
    "VOI": "VIOLET", "VIV": "GREEN", "CMP": "BLUE", "AVA": "RED", "LRC": "RED",
    "LAN": "RED", "TAM": "RED", "GLO": "ORANGE", "AZU": "BLUE", "ARG": "BLUE",
    # Europe
    "BAW": "BLUE", "SHT": "BLUE", "VIR": "RED", "DLH": "YELLOW", "AFR": "BLUE",
    "KLM": "BLUE", "IBE": "RED", "ITY": "BLUE", "SAS": "BLUE", "FIN": "BLUE",
    "EIN": "GREEN", "RYR": "BLUE", "EZY": "ORANGE", "EJU": "ORANGE",
    "WZZ": "VIOLET", "SWR": "RED", "AUA": "RED", "TAP": "GREEN", "ICE": "BLUE",
    "CFG": "YELLOW", "EWG": "VIOLET", "BEL": "RED", "LOT": "BLUE", "AEA": "BLUE",
    "VLG": "YELLOW", "NAX": "RED", "NOZ": "RED", "TRA": "GREEN", "TVF": "GREEN",
    "THY": "RED", "PGT": "YELLOW", "AEE": "BLUE", "EXS": "RED",
    # Middle East / Africa
    "UAE": "RED", "QTR": "VIOLET", "ETD": "YELLOW", "SVA": "GREEN", "ELY": "BLUE",
    "GFA": "RED", "OMA": "GREEN", "RJA": "RED", "MSR": "BLUE", "ETH": "GREEN",
    "KQA": "RED", "RAM": "RED", "FDB": "ORANGE",
    # Asia / Pacific
    "SIA": "YELLOW", "JAL": "RED", "ANA": "BLUE", "KAL": "BLUE", "AAR": "RED",
    "QFA": "RED", "ANZ": "BLUE", "VOZ": "RED", "JST": "ORANGE", "AIC": "RED",
    "IGO": "BLUE", "PAL": "BLUE", "CEB": "YELLOW", "HVN": "BLUE", "THA": "VIOLET",
    "MAS": "RED", "GIA": "BLUE", "AXM": "RED", "SCO": "YELLOW", "VJC": "RED",
    # China / Hong Kong / Macau / Taiwan
    "CCA": "RED", "CCD": "RED", "CNM": "RED", "CES": "BLUE", "CSN": "BLUE",
    "CHH": "RED", "CSZ": "RED", "CSC": "RED", "CXA": "BLUE", "CSH": "RED",
    "CQH": "GREEN", "DKH": "RED", "CHB": "ORANGE", "CPA": "GREEN",
    "HKE": "VIOLET", "CRK": "RED", "AMU": "RED", "CAL": "VIOLET",
    "EVA": "GREEN", "SJX": "YELLOW", "TTW": "ORANGE",
}


def airline_color(
    callsign: str | None,
    flight_number: str | None = None,
    overrides: dict[str, str] | None = None,
) -> int | None:
    """Vestaboard color code for the airline flying ``callsign``, if known.

    ``overrides`` (from the dashboard) may be keyed by ICAO or IATA airline code
    and win over the built-in table. ``NONE`` disables the color for an airline.
    """
    match = _CALLSIGN_RE.match((callsign or "").strip().upper())
    icao = match.group(1) if match else None
    iata = ICAO_TO_IATA.get(icao or "")
    if not iata and flight_number and len(flight_number) > 2 and flight_number[2:3].isdigit():
        iata = flight_number[:2].upper()
    overrides = overrides or {}
    for key in (icao, iata):
        if key and key in overrides:
            return COLOR_CODES.get(overrides[key].strip().upper())
    return COLOR_CODES.get(AIRLINE_COLORS.get(icao or "", ""))
