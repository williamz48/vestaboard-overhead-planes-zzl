"""Small geodesy helpers: distances, bearings and bounding boxes."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088
KM_PER_MILE = 1.609344
FEET_PER_METER = 3.28084
KNOTS_PER_MS = 1.943844

_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def to_km(value: float, unit: str) -> float:
    return value * KM_PER_MILE if unit == "mi" else value


def from_km(value_km: float, unit: str) -> float:
    return value_km / KM_PER_MILE if unit == "mi" else value_km


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass_point(degrees: float) -> str:
    return _COMPASS[int((degrees % 360) / 45 + 0.5) % 8]


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return ``(lamin, lomin, lamax, lomax)`` enclosing a circle of ``radius_km``."""
    dlat = math.degrees(radius_km / EARTH_RADIUS_KM)
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    dlon = min(180.0, math.degrees(radius_km / (EARTH_RADIUS_KM * cos_lat)))
    return (
        max(-90.0, lat - dlat),
        max(-180.0, lon - dlon),
        min(90.0, lat + dlat),
        min(180.0, lon + dlon),
    )
