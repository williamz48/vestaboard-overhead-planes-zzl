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
    "SIA": "SQ", "CPA": "CX", "JAL": "JL", "ANA": "NH", "KAL": "KE",
    "AAR": "OZ", "CCA": "CA", "CES": "MU", "CSN": "CZ", "HDA": "HX",
    "EVA": "BR", "CAL": "CI", "SJX": "JX", "QFA": "QF", "ANZ": "NZ",
    "VOZ": "VA", "JST": "JQ", "AIC": "AI", "IGO": "6E", "PAL": "PR",
    "CEB": "5J", "HVN": "VN", "THA": "TG", "MAS": "MH", "GIA": "GA",
    "AXM": "AK", "SCO": "TR", "ZIP": "ZG",
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
