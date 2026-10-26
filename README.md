# Vestaboard Overhead Planes

Shows the flight passing overhead on your Vestaboard Note (or Flagship):

```
     UA1234
   SFO - JFK
  B737-8 MAX
```

1. **Flight number** (IATA, e.g. `UA1234`)
2. **Origin - destination** (IATA airport codes)
3. **Aircraft model** in short form (`B737-8 MAX`, `A320-200`, `A321neo`, `DHC-8-400`, `E175`…)

Positions come from the [OpenSky Network](https://opensky-network.org) and each
flight is enriched with route and aircraft type from
[FlightAware AeroAPI](https://www.flightaware.com/aeroapi/portal). Everything is
configured from a web dashboard, and the app runs in Docker.

## Quick start (Docker)

```bash
docker compose up -d --build
```

Open **http://<your-host>:8080** and fill in:

- **Location**: search an address, click the map, or type a latitude/longitude, then set the radius.
- **OpenSky Network**: client ID and secret (optional but recommended).
- **FlightAware AeroAPI**: API key.
- **Vestaboard**: connection type and key, and which board you have (Note 3×15 or Flagship 6×22).

Click **Save settings**. Each service has a **Test** button. Settings live in
`/data/settings.json` inside the `planes-data` Docker volume, so they survive
upgrades (`docker compose up -d --build`).

Without Docker:

```bash
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Getting API keys

### OpenSky Network
Log in at opensky-network.org, go to **Account → API Client**, create a client and
copy the client ID and secret. (OpenSky stopped accepting username/password for
the API in March 2026; this app uses the OAuth2 client-credentials flow.)

OpenSky charges "credits" per request. Any radius up to about 150 mi (at mid-latitudes) costs
1 credit per poll:

| Account | Credits/day | Fastest sensible poll interval |
|---|---|---|
| Anonymous (no credentials) | 400 | ~240 s |
| Registered | 4,000 | ~25 s |
| Feeder (you run an ADS-B receiver) | 8,000 | ~12 s |

The dashboard shows the credits remaining. If you run out, the app backs off
until OpenSky says it can retry.

### FlightAware AeroAPI
Sign up at the [AeroAPI portal](https://www.flightaware.com/aeroapi/portal) and
create an API key. AeroAPI bills per request, so the app:

- only looks up the flight that is actually going on the board (not every plane in range);
- caches each result until the flight is due to land (up to 6 hours);
- caches "not found" results for 30 minutes.

Without a FlightAware key the board still shows the flight number (converted from
the ADS-B callsign, e.g. `UAL123` → `UA123`), but no route or aircraft.

### Vestaboard
Choose one connection in the dashboard:

- **Cloud API** (easiest): create a token in the Developer section of
  [web.vestaboard.com](https://web.vestaboard.com).
- **Local API** (fastest, no internet needed): request a Local API enablement
  token from Vestaboard, then exchange it for a key:
  ```bash
  curl -X POST http://vestaboard.local:7000/local-api/enablement \
       -H "X-Vestaboard-Local-Api-Enablement-Token: <enablement token>"
  ```
  Enter the returned `apiKey` and the board's hostname or IP. The container has
  to be able to reach the board on your LAN; if `vestaboard.local` doesn't resolve
  inside Docker, use the IP address.
- **Read/Write API**: the older cloud API key, for existing setups.
- **Disabled**: preview only. The dashboard shows what would be sent.

Vestaboard rate-limits boards to about one message every 15 seconds. The app only
sends when the text changes and never sends more often than that.

## Display options

| Setting | What it does |
|---|---|
| Which flight to show | **Closest flight**, or **Rotate** through every flight in range |
| Minimum time on board | A flight stays up at least this long before another replaces it (also the rotate interval) |
| When no flights are nearby | Show an idle message, or keep the last flight up |
| Idle message | One row per line. `{63}`–`{70}` insert color tiles (red, orange, yellow, green, blue, violet, white, black) |
| Min/max altitude | Ignore aircraft outside this altitude band |
| Airline flights only | Skip private aircraft whose callsign is a tail number |
| Aircraft name overrides | Rename aircraft: `ICAO_TYPE=NAME` or `REGISTRATION=NAME`, one per line |

### Aircraft names

FlightAware reports ICAO type designators, which `app/aircraft.py` maps to short
names (`B38M` → `B737-8 MAX`, `A320` → `A320-200`, `DH8D` → `DHC-8-400`,
`B77W` → `B777-300ER`, …). Unknown types fall back to the raw designator.

Some variants share a designator. For example, the A321neo, A321LR and A321XLR
all file as `A21N`. If you know which tail numbers fly the XLR, add overrides like:

```
N123AB=A321XLR
```

Or rename a whole type with `A21N=A321XLR`.

You can also use the dashboard's **Send a custom message** box to put any text on
the board for a set number of minutes, after which flight tracking takes over again.

## Securing the dashboard

The dashboard shows your settings and can change them. Secrets are never sent
back to the browser, but anyone who can open the page can change settings. If the
dashboard is reachable beyond your home network, set a password:

```yaml
environment:
  DASHBOARD_USERNAME: admin
  DASHBOARD_PASSWORD: something-long
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `DATA_DIR` | `/data` | Where `settings.json` is stored |
| `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` | – | Enable HTTP basic auth |
| `LOG_LEVEL` | `INFO` | Python log level |
| `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`, `FLIGHTAWARE_API_KEY`, `VESTABOARD_MODE`, `VESTABOARD_CLOUD_TOKEN`, `VESTABOARD_RW_KEY`, `VESTABOARD_LOCAL_HOST`, `VESTABOARD_LOCAL_KEY`, `VESTABOARD_BOARD`, `LATITUDE`, `LONGITUDE`, `RADIUS`, `RADIUS_UNIT` | – | Seed the settings on first start only; after that the dashboard is the source of truth |

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

Project layout:

```
app/
  main.py         FastAPI app: dashboard + JSON API
  tracker.py      background loop: poll → pick flight → enrich → send to board
  opensky.py      OpenSky client (OAuth2, rate-limit handling)
  flightaware.py  AeroAPI client with caching
  vestaboard.py   character codes, layout, Cloud/Local/RW clients
  aircraft.py     ICAO type → short model names
  airlines.py     ICAO → IATA airline codes (fallback)
  config.py       settings model + JSON persistence
  static/         dashboard (HTML/CSS/JS, Leaflet map)
tests/
```
