"""OpenSky Network client for live aircraft positions.

Docs: https://openskynetwork.github.io/opensky-api/rest.html

Authentication uses the OAuth2 client-credentials flow (basic auth was retired
in March 2026). Without credentials requests are anonymous, which works but has
a much smaller daily credit allowance.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import httpx

API_URL = "https://opensky-network.org/api"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)


class OpenSkyError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Aircraft:
    icao24: str
    callsign: str
    origin_country: str
    latitude: float
    longitude: float
    altitude_m: float | None
    on_ground: bool
    velocity_ms: float | None
    heading: float | None
    vertical_rate_ms: float | None
    squawk: str | None
    last_contact: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_state(row: list) -> Aircraft | None:
    """Convert one OpenSky state vector into an :class:`Aircraft`.

    Returns ``None`` for rows without a position.
    """
    if len(row) < 17 or row[5] is None or row[6] is None:
        return None
    baro, geo = row[7], row[13]
    return Aircraft(
        icao24=str(row[0] or "").lower(),
        callsign=str(row[1] or "").strip().upper(),
        origin_country=row[2] or "",
        latitude=float(row[6]),
        longitude=float(row[5]),
        altitude_m=baro if baro is not None else geo,
        on_ground=bool(row[8]),
        velocity_ms=row[9],
        heading=row[10],
        vertical_rate_ms=row[11],
        squawk=row[14],
        last_contact=row[4],
    )


class OpenSkyClient:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_client_id: str | None = None
        self.credits_remaining: int | None = None

    async def _get_token(self, client_id: str, client_secret: str, force: bool = False) -> str:
        if (
            not force
            and self._token
            and self._token_client_id == client_id
            and time.monotonic() < self._token_expires
        ):
            return self._token
        try:
            resp = await self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise OpenSkyError(f"OpenSky auth request failed: {exc}") from exc
        if resp.status_code != 200:
            raise OpenSkyError(
                f"OpenSky auth failed (HTTP {resp.status_code}). Check the client ID and secret."
            )
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_client_id = client_id
        # Refresh a minute early; tokens are documented to last 30 minutes.
        self._token_expires = time.monotonic() + max(60, int(payload.get("expires_in", 1800)) - 60)
        return self._token

    async def get_states(
        self,
        bbox: tuple[float, float, float, float],
        client_id: str = "",
        client_secret: str = "",
    ) -> list[Aircraft]:
        lamin, lomin, lamax, lomax = bbox
        params = {"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax}
        authed = bool(client_id and client_secret)

        for attempt in range(2):
            headers = {}
            if authed:
                token = await self._get_token(client_id, client_secret, force=attempt > 0)
                headers["Authorization"] = f"Bearer {token}"
            try:
                resp = await self._http.get(
                    f"{API_URL}/states/all", params=params, headers=headers, timeout=20
                )
            except httpx.HTTPError as exc:
                raise OpenSkyError(f"OpenSky request failed: {exc}") from exc

            remaining = resp.headers.get("X-Rate-Limit-Remaining")
            if remaining is not None and remaining.lstrip("-").isdigit():
                self.credits_remaining = int(remaining)

            if resp.status_code == 401 and authed and attempt == 0:
                continue  # token expired early; fetch a new one and retry once
            if resp.status_code == 429:
                retry = resp.headers.get("X-Rate-Limit-Retry-After-Seconds")
                retry_after = float(retry) if retry and retry.replace(".", "", 1).isdigit() else 300
                raise OpenSkyError(
                    f"OpenSky rate limit reached; retrying in {int(retry_after)}s", retry_after
                )
            if resp.status_code != 200:
                raise OpenSkyError(f"OpenSky returned HTTP {resp.status_code}")
            break

        states = (resp.json() or {}).get("states") or []
        return [a for a in (parse_state(row) for row in states) if a is not None]

    async def test(self, client_id: str, client_secret: str) -> str:
        if not (client_id and client_secret):
            return "No credentials set; OpenSky will be used anonymously (400 credits/day)."
        await self._get_token(client_id, client_secret, force=True)
        return "Authenticated with OpenSky successfully."
