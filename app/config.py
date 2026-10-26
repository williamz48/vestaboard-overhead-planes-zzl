"""Persistent settings stored as JSON in the data directory.

Environment variables (see ``ENV_SEEDS``) provide initial values the first time
the app starts; after that the dashboard is the source of truth.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SECRET_FIELDS = (
    "opensky_client_secret",
    "flightaware_api_key",
    "vestaboard_cloud_token",
    "vestaboard_rw_key",
    "vestaboard_local_key",
)
SECRET_MASK = "••••••••"

ENV_SEEDS = {
    "OPENSKY_CLIENT_ID": "opensky_client_id",
    "OPENSKY_CLIENT_SECRET": "opensky_client_secret",
    "FLIGHTAWARE_API_KEY": "flightaware_api_key",
    "VESTABOARD_MODE": "vestaboard_mode",
    "VESTABOARD_CLOUD_TOKEN": "vestaboard_cloud_token",
    "VESTABOARD_RW_KEY": "vestaboard_rw_key",
    "VESTABOARD_LOCAL_HOST": "vestaboard_local_host",
    "VESTABOARD_LOCAL_KEY": "vestaboard_local_key",
    "VESTABOARD_BOARD": "board_model",
    "LATITUDE": "latitude",
    "LONGITUDE": "longitude",
    "RADIUS": "radius",
    "RADIUS_UNIT": "radius_unit",
}


class Settings(BaseModel):
    enabled: bool = True

    # Location
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_name: str = ""
    radius: float = Field(default=5.0, gt=0, le=250)
    radius_unit: Literal["mi", "km"] = "mi"
    min_altitude_ft: int = Field(default=0, ge=0)
    max_altitude_ft: int = Field(default=0, ge=0)  # 0 = no limit
    include_ground: bool = False

    # OpenSky Network
    opensky_client_id: str = ""
    opensky_client_secret: str = ""
    poll_interval: int = Field(default=60, ge=10, le=3600)

    # FlightAware AeroAPI
    flightaware_api_key: str = ""

    # Vestaboard
    vestaboard_mode: Literal["disabled", "cloud", "rw", "local"] = "disabled"
    vestaboard_cloud_token: str = ""
    vestaboard_rw_key: str = ""
    vestaboard_local_host: str = "vestaboard.local"
    vestaboard_local_key: str = ""
    board_model: Literal["note", "flagship"] = "note"
    align: Literal["center", "left"] = "center"

    # Display behaviour
    display_mode: Literal["closest", "rotate"] = "closest"
    min_display_seconds: int = Field(default=60, ge=15, le=3600)
    idle_action: Literal["clock", "message", "keep"] = "clock"
    idle_message: str = "CLEAR SKIES"
    time_format: Literal["12h", "24h"] = "12h"
    temperature_unit: Literal["F", "C", "both"] = "F"
    clock_show_weather: bool = True
    airlines_only: bool = False  # skip private/GA aircraft (callsign isn't an airline flight)
    aircraft_overrides: str = ""
    show_manufacturer: bool = True  # "AIRBUS A350-900" when it fits, else "A350-900"
    aircraft_display: Literal["model", "icao_registration", "model_registration"] = "model"
    airline_colors: bool = True  # color tiles at both ends of the flight number row
    airline_color_overrides: str = ""

    @field_validator(
        "opensky_client_id", "opensky_client_secret", "flightaware_api_key",
        "vestaboard_cloud_token", "vestaboard_rw_key", "vestaboard_local_host",
        "vestaboard_local_key", "location_name",
    )
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def masked(self) -> dict:
        data = self.model_dump()
        for key in SECRET_FIELDS:
            data[key] = SECRET_MASK if data[key] else ""
        return data


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if self.path.exists():
            try:
                return Settings.model_validate(json.loads(self.path.read_text()))
            except (OSError, ValueError):
                backup = self.path.with_suffix(".invalid.json")
                self.path.replace(backup)
        seeded = {
            field: os.environ[env]
            for env, field in ENV_SEEDS.items()
            if os.environ.get(env, "").strip()
        }
        settings = Settings.model_validate(seeded)
        self._write(settings)
        return settings

    def _write(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.model_dump(), indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def get(self) -> Settings:
        return self._settings

    def update(self, changes: dict) -> Settings:
        """Apply a partial update. Masked secrets are left unchanged."""
        with self._lock:
            data = self._settings.model_dump()
            for key, value in changes.items():
                if key not in data:
                    continue
                if key in SECRET_FIELDS and value == SECRET_MASK:
                    continue
                data[key] = value
            settings = Settings.model_validate(data)
            self._write(settings)
            self._settings = settings
            return settings
