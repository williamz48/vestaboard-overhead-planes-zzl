"""Vestaboard character encoding, layout and API clients.

Supported transports:

* ``cloud``  - Vestaboard Cloud API (``https://cloud.vestaboard.com``, token from
  the Developer section of web.vestaboard.com)
* ``rw``     - legacy Read/Write API (``https://rw.vestaboard.com``)
* ``local``  - Local API on the board itself (``http://<board>:7000``)
"""

from __future__ import annotations

import re

import httpx

BOARD_SIZES = {"note": (3, 15), "flagship": (6, 22)}

CLOUD_URL = "https://cloud.vestaboard.com/"
RW_URL = "https://rw.vestaboard.com/"

_CHAR_CODES: dict[str, int] = {" ": 0}
_CHAR_CODES.update({chr(ord("A") + i): i + 1 for i in range(26)})
_CHAR_CODES.update({str(d): 27 + (d - 1) for d in range(1, 10)})
_CHAR_CODES["0"] = 36
_CHAR_CODES.update(
    {
        "!": 37, "@": 38, "#": 39, "$": 40, "(": 41, ")": 42, "-": 44, "+": 46,
        "&": 47, "=": 48, ";": 49, ":": 50, "'": 52, '"': 53, "%": 54, ",": 55,
        ".": 56, "/": 59, "?": 60, "°": 62,
    }
)
_CODE_CHARS = {v: k for k, v in _CHAR_CODES.items()}
COLOR_CODES = {63: "red", 64: "orange", 65: "yellow", 66: "green", 67: "blue", 68: "violet", 69: "white", 70: "black"}

# "{63}" inserts a raw character code (handy for color tiles in idle messages).
_TOKEN_RE = re.compile(r"\{(\d{1,2})\}|(.)", re.DOTALL)


class VestaboardError(Exception):
    pass


def encode_text(text: str) -> list[int]:
    """Encode a line of text into Vestaboard character codes.

    Letters are upper-cased; unsupported characters become blanks.
    """
    codes: list[int] = []
    for match in _TOKEN_RE.finditer(text or ""):
        if match.group(1) is not None:
            code = int(match.group(1))
            codes.append(code if 0 <= code <= 71 else 0)
        else:
            codes.append(_CHAR_CODES.get(match.group(2).upper(), 0))
    return codes


def visible_length(text: str) -> int:
    return len(encode_text(text))


def fit(text: str, width: int) -> str:
    """Truncate plain text so it fits in ``width`` tiles."""
    text = (text or "").strip()
    return text if len(text) <= width else text[:width].rstrip()


def with_edge_tiles(text: str, code: int, width: int, align: str = "center") -> str:
    """A full-width row with a color tile in the first and last columns.

    The text keeps the same position it would have without the tiles, and at
    least one blank separates it from each tile.
    """
    inner = width - 2
    text = fit(text, inner - 2)
    if align == "center":
        left = (inner - len(text)) // 2
        body = " " * left + text + " " * (inner - left - len(text))
    else:
        body = (" " + text).ljust(inner)
    return f"{{{code}}}{body}{{{code}}}"


def layout(lines: list[str], board: str = "note", align: str = "center") -> list[list[int]]:
    """Lay out text lines onto a blank board grid, vertically centered."""
    rows, cols = BOARD_SIZES[board]
    lines = list(lines)[:rows]
    grid = [[0] * cols for _ in range(rows)]
    top = (rows - len(lines)) // 2
    for i, line in enumerate(lines):
        codes = encode_text(line.strip())[:cols]
        left = (cols - len(codes)) // 2 if align == "center" else 0
        grid[top + i][left : left + len(codes)] = codes
    return grid


def grid_to_text(grid: list[list[int]]) -> list[str]:
    """Render a grid back to text (color tiles become ``*``) for logs/previews."""
    return ["".join(_CODE_CHARS.get(c, "*") for c in row) for row in grid]


def is_blank(grid: list[list[int]]) -> bool:
    return all(c == 0 for row in grid for c in row)


def local_base_url(host: str) -> str:
    host = (host or "").strip().rstrip("/")
    if not host:
        raise VestaboardError("No Vestaboard local host/IP set")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    if not re.search(r":\d+$", host.split("//", 1)[1]):
        host = f"{host}:7000"
    return host


class VestaboardClient:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    @staticmethod
    def _endpoint(settings) -> tuple[str, dict[str, str]]:
        mode = settings.vestaboard_mode
        if mode == "cloud":
            if not settings.vestaboard_cloud_token:
                raise VestaboardError("No Vestaboard Cloud API token set")
            return CLOUD_URL, {"X-Vestaboard-Token": settings.vestaboard_cloud_token}
        if mode == "rw":
            if not settings.vestaboard_rw_key:
                raise VestaboardError("No Vestaboard Read/Write key set")
            return RW_URL, {"X-Vestaboard-Read-Write-Key": settings.vestaboard_rw_key}
        if mode == "local":
            if not settings.vestaboard_local_key:
                raise VestaboardError("No Vestaboard Local API key set")
            url = f"{local_base_url(settings.vestaboard_local_host)}/local-api/message"
            return url, {"X-Vestaboard-Local-Api-Key": settings.vestaboard_local_key}
        raise VestaboardError("Vestaboard output is disabled")

    async def send(self, grid: list[list[int]], settings) -> None:
        if is_blank(grid) and settings.vestaboard_mode != "local":
            raise VestaboardError("The Vestaboard cloud APIs do not accept blank messages")
        url, headers = self._endpoint(settings)
        try:
            resp = await self._http.post(url, json=grid, headers=headers, timeout=20)
        except httpx.HTTPError as exc:
            raise VestaboardError(f"Vestaboard request failed: {exc}") from exc
        if resp.status_code == 423:
            raise VestaboardError("Vestaboard is muted / in quiet hours (HTTP 423)")
        if resp.status_code in (401, 403):
            raise VestaboardError("Vestaboard rejected the API key")
        if resp.status_code == 409:
            return  # identical to what is already on the board
        if resp.status_code >= 300:
            raise VestaboardError(f"Vestaboard returned HTTP {resp.status_code}: {resp.text[:200]}")

    async def test(self, settings) -> str:
        url, headers = self._endpoint(settings)
        try:
            resp = await self._http.get(url, headers=headers, timeout=15)
        except httpx.HTTPError as exc:
            raise VestaboardError(f"Could not reach Vestaboard: {exc}") from exc
        if resp.status_code in (401, 403):
            raise VestaboardError("Vestaboard rejected the API key")
        if resp.status_code >= 300:
            raise VestaboardError(f"Vestaboard returned HTTP {resp.status_code}")
        return "Connected to Vestaboard successfully."
