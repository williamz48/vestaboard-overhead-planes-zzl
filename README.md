# Vestaboard Overhead Planes

Shows the flight passing overhead on your Vestaboard Note (or Flagship):

```
     UA1234
   SFO - JFK
  B737-8 MAX
```

1. **Flight number** (IATA, e.g. `UA1234`)
2. **Origin - destination** (IATA airport codes)
3. **Aircraft model**, with the manufacturer when it fits (`AIRBUS A350-900`,
   `BOEING 787-9`, `EMBRAER E175`), otherwise the compact form (`B737-8 MAX`,
   `A350-1000`, `DHC-8-400`)

Positions come from the [OpenSky Network](https://opensky-network.org) and each
flight is enriched with route and aircraft type from
[FlightAware AeroAPI](https://www.flightaware.com/aeroapi/portal). When no
planes are nearby, the board can show the local time, date and weather (from
[Open-Meteo](https://open-meteo.com), no key needed). Everything is configured
from a web dashboard, and the app runs in Docker.

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

## Deploy on Railway

The repo deploys to [Railway](https://railway.com) as-is from its Dockerfile.

1. In Railway, choose **New Project → Deploy from GitHub repo** and pick this
   repository. If the code isn't on your default branch yet, open the service's
   **Settings → Source** and pick the branch.
2. **Add a volume** to the service (right-click the service, or ⌘K → *Add Volume*)
   with mount path **`/data`**. This is where your settings are saved; without it,
   every redeploy wipes them.
3. Under **Variables**, add `DASHBOARD_PASSWORD` (and optionally
   `DASHBOARD_USERNAME`, which defaults to `admin`). Railway URLs are public, so
   don't skip this. Don't set `PORT`; Railway provides it.
4. Under **Settings → Networking**, click **Generate Domain**, then open the URL
   and fill in your settings as usual.
5. Optional: under **Settings → Deploy**, set the healthcheck path to `/healthz`.

Railway notes:

- Use the Vestaboard **Cloud API**. The Local API can't work from Railway,
  because Railway can't reach a board on your home network.
- Keep the service at **one replica**. Each replica would run its own tracker and
  send duplicate board updates.
- Railway mounts volumes as root. The container fixes ownership of `/data` at
  startup and then drops to an unprivileged user, so you don't need
  `RAILWAY_RUN_UID`.

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

- **Only looks up the flight going on the board,** not every plane in range.
- **Keeps the whole schedule from each lookup.** One call returns every leg flown
  under that callsign up to 2 days ahead. When the same flight passes over again,
  later today or on tomorrow's daily run, it comes from the cache for free.
- **Saves the cache to disk** (`/data/flightaware_cache.json`), so restarts and
  upgrades don't throw it away.
- **Remembers misses and errors** for a while instead of retrying every poll.
- **Can skip private aircraft:** untick *Also look up private aircraft* to skip
  tail-number callsigns like `N123AB`, which often have no route anyway.

The map card shows how many paid calls were made and how many were saved by the
cache since the app started.

If the aircraft row shows the registration, a cached leg that was fetched
before the plane was assigned is looked up again once. That happens at most once
every 30 minutes, so the tail number is filled in.

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
| Text alignment (Vestaboard section) | **Centered** (default) or **Left** |
| Which flight to show | **Closest flight**, or **Rotate** through every flight in range |
| Minimum time on board | A flight stays up at least this long before another replaces it (also the rotate interval) |
| When no flights are nearby | Show the time, date and weather (default), show an idle message, or keep the last flight up |
| Switch after | How long the last flight stays up after it leaves range before the message or time/date/weather appears (immediately up to 30 minutes). A new flight in range is shown straight away |
| Time format | 12-hour (`3:45 PM`) or 24-hour (`15:45`) |
| Temperature | Fahrenheit, Celsius, or both |
| Include weather | Add the current temperature and condition to the time and date |
| Refresh weather every | How often to ask Open-Meteo for new conditions: 5 minutes to 2 hours (default 15 minutes, which is how often Open-Meteo updates) |
| Idle message | One row per line. `{63}`–`{70}` insert color tiles (red, orange, yellow, green, blue, violet, white, black) |
| Min/max altitude | Ignore aircraft outside this altitude band |
| Airline flights only | Skip private aircraft whose callsign is a tail number |
| Aircraft row | **Model** (`A350-900`), **ICAO type + registration** (`A359 N501DN`), or **Model + registration** (`A350-900 N501DN`, falling back to the ICAO type when the model is too long to fit) |
| Show the manufacturer | Prefix the model with its maker when the row has room (`AIRBUS A350-900`); otherwise use the compact name |
| Aircraft name overrides | Rename aircraft: `ICAO_TYPE=NAME` or `REGISTRATION=NAME`, one per line |
| Airline color tiles | Put the airline's color in the first and last tile of the flight number row |
| Airline color overrides | `AIRLINE=COLOR`, one per line, keyed by ICAO (`UAL`) or IATA (`UA`) code. Colors: `RED`, `ORANGE`, `YELLOW`, `GREEN`, `BLUE`, `VIOLET`, `WHITE`, `BLACK`, or `NONE` |

### Do not disturb

Turn on **Do not disturb** (top bar button, or the section at the top of the
settings) to stop all flight lookups. While it's on, the app makes no OpenSky or
FlightAware requests and the board shows either:

- **Time, date & weather**, using the settings in the *Time, date & weather* section, or
- **A custom message**, one line per row (`{63}`–`{70}` for color tiles).

Turn it off and tracking resumes straight away. To stop the board updating
altogether, use **Pause** instead.

**Scheduling:** tick **Also every day on a schedule** and set the **From** and
**Until** times to have do not disturb turn itself on and off every day.
- **Overnight windows:** a window can run past midnight (e.g. 22:00 to 07:00).
- **Time zone:** times are local to the tracked location, using the time zone
  Open-Meteo reports for it, so a server in another time zone still switches at
  the right moment.
- **Ending a window early:** during a scheduled window, the top bar button
  reads **End do not disturb**. Clicking it resumes tracking until the next
  scheduled start.
- **Turning it on by hand:** ticking **Do not disturb now** keeps it on outside
  the schedule too.

### Even centering

A row can only be centered exactly when its length leaves an even number of
blank tiles (on a 15-tile Note, rows of odd length). With centered text, rows
that would be one tile off get an extra space at a natural break instead:

| Row | Without | With |
|---|---|---|
| Flight number | `UA1234` | `UA 1234` |
| Route | `KSFO - JFK` | `KSFO -  JFK` (the dash stays in the middle) |
| Manufacturer + model | `AIRBUS A321NEO` | `AIRBUS  A321NEO` |
| Model + registration | `B787-9 N27901` | `B787-9  N27901` |
| Date | `TUESDAY OCT 27` | `TUESDAY  OCT 27` |

Rows without a natural break (`A320-200`, a tail number like `N123AB`) are left
as they are. Custom and idle messages are sent exactly as you type them.

### Time, date and weather

When no planes are in range, the board shows the time and date at the tracked
location and the current weather from Open-Meteo, updating every minute:

```
    3:45 PM                     15:45
 MONDAY OCT 26          MONDAY  OCTOBER 26
 22C/72F  RAIN              6°C 43°F CLEAR
                         H 20°C/69°F L 5°C/41°F
  (Note, both units)      (Flagship, 24-hour, both units)
```

- **Time zone:** the time is local to the location you set, using the time zone
  Open-Meteo reports for it, not the server's time zone.
- **Date:** the day of the week is spelled out when it fits (`THURSDAY OCT 29`).
  On a Note, Wednesdays with a two-digit date don't fit (`WEDNESDAY OCT 28` is 16
  tiles), so a 4-letter abbreviation is used: `WEDS OCT 28` (also `TUES`, `THUR`).
  The Flagship always has room for the full day and month.
- **Conditions:** one word each: `CLEAR`, `FAIR`, `CLOUDY`, `OVERCAST`, `FOG`,
  `DRIZZLE`, `RAIN`, `SHOWERS`, `SLEET`, `SNOW`, `STORM`. If a word doesn't fit
  next to both temperatures, a shorter synonym is used (e.g. `OVERCAST` → `CLOUDY`).
- **Note vs Flagship:** the Flagship also shows today's high and low and uses
  degree signs. The Note has no degree sign (that tile is a heart), so it shows
  `72F`.
- **If Open-Meteo is unreachable:** the board still shows the time and date, and
  the dashboard shows the error.

### Airline colors

With airline colors on, the flight number row looks like this, with the tiles in
the airline's color (`█`):

```
█    UA123    █
   SFO - JFK
  B737-8 MAX
```

Vestaboard has eight tile colors, so each airline gets the closest match to its
brand color (United → blue, Delta → red, Cathay Pacific → green, Air China → red,
China Eastern → blue, Spirit → yellow, …). The table is `AIRLINE_COLORS` in
`app/airlines.py`. Regional flights take their mainline's color (see below).
Airlines not in the table get no tiles. Add an override for those, or to change
a color you disagree with:

```
SKW=BLUE
AAL=RED
```

### Regional airlines

Regional airlines and brands that fly under a mainline airline's flight numbers
are shown as that airline, with its code and color:

| Callsign | Operator | Board |
|---|---|---|
| `QLK1567` | QantasLink | `QF1567` |
| `ENY3456` | Envoy (American Eagle) | `AA3456` |
| `EDV5034` | Endeavor (Delta Connection) | `DL5034` |
| `JZA8123` | Jazz (Air Canada Express) | `AC8123` |
| `KLC1234` | KLM Cityhopper | `KL1234` |

The full list is `REGIONAL_MAINLINE` in `app/airlines.py`. It covers the
regionals of American, Delta, United, Alaska, Air Canada, WestJet, Aeromexico,
LATAM, Avianca, Copa, British Airways, Lufthansa, KLM, Air France, Iberia, SAS,
Qantas, Air New Zealand, JAL, ANA and Air China.

When FlightAware lists the mainline flight number (as the flight's own number or
as a codeshare), that number is used. Carriers that fly for several airlines
(SkyWest, Republic, Air Wisconsin) are shown as the airline FlightAware's
codeshares name. If FlightAware doesn't say, they keep their own code
(e.g. `OO5432`).

### Aircraft names

FlightAware reports ICAO type designators, which `app/aircraft.py` maps to short
names (`B38M` → `B737-8 MAX`, `A320` → `A320-200`, `DH8D` → `DHC-8-400`,
`B77W` → `B777-300ER`, …). Unknown types fall back to the raw designator.

With **Show the manufacturer** on, the maker is added when the whole name fits
on the row (15 tiles on a Note, 22 on a Flagship):

| Type | Note | Flagship |
|---|---|---|
| `A359` | `AIRBUS A350-900` | `AIRBUS A350-900` |
| `A35K` | `A350-1000` | `AIRBUS A350-1000` |
| `B789` | `BOEING 787-9` | `BOEING 787-9` |
| `B38M` | `B737-8 MAX` | `BOEING 737-8 MAX` |
| `DH8D` | `DHC-8-400` | `DE HAVILLAND DHC-8-400` |

The **Aircraft row** setting can show the registration (tail number) from
FlightAware instead of, or next to, the model:

| Setting | Note | Flagship |
|---|---|---|
| ICAO type + registration | `A359 N501DN` | `A359 N501DN` |
| Model + registration (A350-900) | `A350-900 N501DN` | `AIRBUS A350-900 N501DN` |
| Model + registration (737-8 MAX) | `B38M VH-8IA` | `B737-8 MAX VH-8IA` |

If FlightAware has no registration for a flight, the row shows the type alone.

Boeing, Beechcraft and Cessna drop their one-letter prefix after the maker name
(`BOEING 787-9`, not `BOEING B787-9`). Overrides keep the maker from the type
code, so `A21N=A321XLR` shows as `AIRBUS A321XLR`.

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
  airlines.py     ICAO → IATA airline codes (fallback) and airline colors
  weather.py      Open-Meteo client and time/date/weather board lines
  config.py       settings model + JSON persistence
  static/         dashboard (HTML/CSS/JS, Leaflet map)
tests/
```
