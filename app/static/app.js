"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const CODE_CHARS = { 0: "" };
"ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").forEach((c, i) => (CODE_CHARS[i + 1] = c));
"1234567890".split("").forEach((c, i) => (CODE_CHARS[i + 27] = c));
Object.assign(CODE_CHARS, {
  37: "!", 38: "@", 39: "#", 40: "$", 41: "(", 42: ")", 44: "-", 46: "+", 47: "&", 48: "=",
  49: ";", 50: ":", 52: "'", 53: '"', 54: "%", 55: ",", 56: ".", 59: "/", 60: "?", 62: "°",
});

let settings = null;
let lastStatus = null;
let map, homeMarker, radiusCircle;
const planeMarkers = new Map();
let mapCentered = false;

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    let msg = body.detail || resp.statusText;
    if (Array.isArray(msg)) msg = msg.map((e) => `${e.field}: ${e.message}`).join("; ");
    throw new Error(msg);
  }
  return body;
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), 3500);
}

function ago(ts) {
  if (!ts) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/* ---------- Settings form ---------- */

function fillForm(s) {
  const form = $("#settings-form");
  for (const [key, value] of Object.entries(s)) {
    const el = form.elements.namedItem(key);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!value;
    else el.value = value ?? "";
  }
  updateModeFields();
}

function readForm() {
  const form = $("#settings-form");
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.type === "number") out[el.name] = el.value === "" ? null : Number(el.value);
    else out[el.name] = el.value;
  }
  return out;
}

function updateModeFields() {
  const mode = $("[name=vestaboard_mode]").value;
  $$("[data-mode]").forEach((el) => (el.hidden = el.dataset.mode !== mode));
}

async function saveSettings(changes) {
  settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(changes) });
  fillForm(settings);
  renderManualInputs();
  updateMapLocation();
  setTimeout(refreshStatus, 1500);
  return settings;
}

$("#settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const status = $("#save-status");
  status.textContent = "Saving…";
  try {
    await saveSettings(readForm());
    status.textContent = "";
    toast("Settings saved");
  } catch (err) {
    status.textContent = "";
    toast(`Could not save: ${err.message}`);
  }
});

$("[name=vestaboard_mode]").addEventListener("change", updateModeFields);
$("[name=board_model]").addEventListener("change", renderManualInputs);

$$("[data-test]").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const service = btn.dataset.test;
    const out = $(`[data-result=${service}]`);
    btn.disabled = true;
    out.className = "test-result";
    out.textContent = "Saving settings and testing…";
    try {
      await saveSettings(readForm());
      const result = await api(`/api/test/${service}`, { method: "POST" });
      out.className = `test-result ${result.ok ? "ok" : "err"}`;
      out.textContent = result.message;
    } catch (err) {
      out.className = "test-result err";
      out.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  })
);

/* ---------- Location helpers ---------- */

function setLocation(lat, lon, name) {
  const form = $("#settings-form");
  form.elements.latitude.value = lat.toFixed(5);
  form.elements.longitude.value = lon.toFixed(5);
  if (name !== undefined) form.elements.location_name.value = name;
  if (map) {
    map.setView([lat, lon], map.getZoom());
    drawHome(lat, lon);
  }
  toast("Location updated — remember to save");
}

$("#btn-geocode").addEventListener("click", async () => {
  const q = $("#geo-query").value.trim();
  const list = $("#geo-results");
  list.innerHTML = "";
  if (!q) return;
  try {
    const results = await api(`/api/geocode?q=${encodeURIComponent(q)}`);
    if (!results.length) list.innerHTML = "<li>No results</li>";
    for (const r of results) {
      const li = document.createElement("li");
      li.textContent = r.name;
      li.addEventListener("click", () => {
        setLocation(r.latitude, r.longitude, r.name.split(",")[0]);
        list.innerHTML = "";
      });
      list.appendChild(li);
    }
  } catch (err) {
    toast(err.message);
  }
});
$("#geo-query").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    ev.preventDefault();
    $("#btn-geocode").click();
  }
});

$("#btn-mylocation").addEventListener("click", () => {
  if (!navigator.geolocation) return toast("Geolocation is not available in this browser");
  navigator.geolocation.getCurrentPosition(
    (pos) => setLocation(pos.coords.latitude, pos.coords.longitude),
    (err) => toast(`Could not get location: ${err.message} (browsers only allow this over HTTPS or localhost)`)
  );
});

/* ---------- Map ---------- */

function initMap() {
  if (typeof L === "undefined") {
    $("#map").innerHTML = '<p class="empty">Map unavailable (could not load Leaflet).</p>';
    return;
  }
  map = L.map("map", { zoomControl: true }).setView([39.8, -98.6], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  map.on("click", (ev) => setLocation(ev.latlng.lat, ev.latlng.lng));
}

function drawHome(lat, lon) {
  if (!map) return;
  const unit = $("[name=radius_unit]").value;
  const radius = Number($("[name=radius]").value) || 0;
  const meters = radius * (unit === "mi" ? 1609.344 : 1000);
  if (!homeMarker) {
    homeMarker = L.circleMarker([lat, lon], { radius: 6, color: "#2563eb", fillOpacity: 1 }).addTo(map);
    radiusCircle = L.circle([lat, lon], { radius: meters, color: "#2563eb", weight: 1, fillOpacity: 0.06 }).addTo(map);
  } else {
    homeMarker.setLatLng([lat, lon]);
    radiusCircle.setLatLng([lat, lon]).setRadius(meters);
  }
}

function updateMapLocation() {
  if (!map || !settings || settings.latitude == null) return;
  drawHome(settings.latitude, settings.longitude);
  if (!mapCentered) {
    map.fitBounds(radiusCircle.getBounds(), { padding: [20, 20] });
    mapCentered = true;
  }
}
["radius", "radius_unit"].forEach((n) =>
  $(`[name=${n}]`).addEventListener("input", () => {
    const lat = Number($("[name=latitude]").value), lon = Number($("[name=longitude]").value);
    if (homeMarker && !Number.isNaN(lat)) drawHome(lat, lon);
  })
);

function planeIcon(heading, isCurrent) {
  return L.divIcon({
    className: `plane-icon${isCurrent ? " current" : ""}`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    html: `<svg viewBox="0 0 24 24" style="transform: rotate(${heading || 0}deg)"><path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/></svg>`,
  });
}

function updatePlanes(status) {
  if (!map) return;
  const seen = new Set();
  for (const f of status.nearby) {
    seen.add(f.icao24);
    const isCurrent = f.icao24 === status.current_icao24;
    const label = `<b>${esc(f.flight || f.callsign)}</b><br>${esc(f.origin || "?")} → ${esc(f.destination || "?")}<br>${esc(f.aircraft || "")}<br>${f.altitude_ft != null ? f.altitude_ft.toLocaleString() + " ft" : ""}`;
    let marker = planeMarkers.get(f.icao24);
    if (!marker) {
      marker = L.marker([f.latitude, f.longitude]).addTo(map);
      planeMarkers.set(f.icao24, marker);
    }
    marker.setLatLng([f.latitude, f.longitude]);
    marker.setIcon(planeIcon(f.heading, isCurrent));
    marker.bindTooltip(label);
  }
  for (const [id, marker] of planeMarkers) {
    if (!seen.has(id)) {
      marker.remove();
      planeMarkers.delete(id);
    }
  }
}

/* ---------- Board + status ---------- */

function renderBoard(board) {
  const el = $("#board");
  el.className = `board ${board.rows === 6 ? "flagship" : "note"}`;
  el.style.gridTemplateColumns = `repeat(${board.cols}, 1fr)`;
  const grid = board.grid || Array.from({ length: board.rows }, () => Array(board.cols).fill(0));
  el.innerHTML = grid
    .flat()
    .map((c) => (c >= 63 && c <= 70 ? `<div class="tile c${c}"></div>` : `<div class="tile">${esc(CODE_CHARS[c] ?? "")}</div>`))
    .join("");
  const where = { disabled: "preview only", cloud: "Cloud API", local: "Local API", rw: "Read/Write API" }[board.mode];
  $("#board-meta").textContent = board.sent_at ? `Updated ${ago(board.sent_at)} · ${where}` : where;
}

function renderCurrent(status) {
  const el = $("#current");
  if (status.manual_until && status.manual_until > Date.now() / 1000) {
    const mins = Math.ceil((status.manual_until - Date.now() / 1000) / 60);
    el.innerHTML = `<p class="muted">Showing a custom message; flight updates resume in ~${mins} min.</p>`;
    return;
  }
  const f = status.nearby.find((x) => x.icao24 === status.current_icao24);
  if (!f) {
    el.innerHTML = `<p class="muted">${status.nearby.length ? "" : "No flights in range right now."}</p>`;
    return;
  }
  const unit = status.location.unit;
  el.innerHTML = `<dl>
    <dt>Flight</dt><dd>${esc(f.flight)} <span class="muted">(${esc(f.callsign)}${f.airline ? " · " + esc(f.airline) : ""})</span></dd>
    <dt>Route</dt><dd>${esc(f.origin_name || f.origin || "?")} → ${esc(f.destination_name || f.destination || "?")}</dd>
    <dt>Aircraft</dt><dd>${esc(f.aircraft || "unknown")}${f.registration ? ` <span class="muted">${esc(f.registration)}</span>` : ""}</dd>
    <dt>Position</dt><dd>${f.distance} ${unit} ${esc(f.bearing)} · ${f.altitude_ft != null ? f.altitude_ft.toLocaleString() + " ft" : "alt ?"} · ${f.speed_kt ?? "?"} kt</dd>
  </dl>`;
}

function renderNearby(status) {
  const tbody = $("#nearby tbody");
  const unit = status.location.unit;
  $("#nearby-count").textContent = `${status.nearby.length} in range`;
  if (!status.nearby.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">${status.status === "needs location" ? "Set a location below to start tracking." : "No aircraft in range."}</td></tr>`;
    return;
  }
  tbody.innerHTML = status.nearby
    .map((f) => {
      const route = f.origin || f.destination ? `${esc(f.origin || "?")} – ${esc(f.destination || "?")}` : '<span class="sub">—</span>';
      return `<tr class="${f.icao24 === status.current_icao24 ? "current" : ""}">
        <td>${f.color ? `<span class="swatch c${f.color}"></span>` : ""}<b>${esc(f.flight || f.callsign)}</b></td>
        <td>${esc(f.callsign)}</td>
        <td>${route}</td>
        <td>${f.aircraft ? esc(f.aircraft) : '<span class="sub">—</span>'}</td>
        <td class="num">${f.on_ground ? "ground" : f.altitude_ft != null ? f.altitude_ft.toLocaleString() + " ft" : "—"}</td>
        <td class="num">${f.speed_kt != null ? f.speed_kt + " kt" : "—"}</td>
        <td class="num">${f.distance} ${unit} ${esc(f.bearing)}</td>
      </tr>`;
    })
    .join("");
}

function isPrivateHost(host) {
  return (
    host === "localhost" ||
    host.endsWith(".local") ||
    !host.includes(".") ||
    /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$)/.test(host)
  );
}

function renderStatus(status) {
  lastStatus = status;
  const pill = $("#status-pill");
  pill.textContent = status.status;
  pill.className = "pill " + ({ tracking: "ok", paused: "warn", "needs location": "warn" }[status.status] || (status.status.includes("error") ? "err" : ""));
  $("#btn-toggle").textContent = status.enabled ? "Pause" : "Resume";

  const labels = { opensky: "OpenSky", flightaware: "FlightAware", vestaboard: "Vestaboard" };
  $("#errors").innerHTML =
    (!status.auth_enabled && !isPrivateHost(location.hostname)
      ? '<div class="error"><b>Dashboard is public:</b> anyone with this URL can change your settings. Set the DASHBOARD_PASSWORD environment variable.</div>'
      : "") +
    Object.entries(status.errors)
      .filter(([, msg]) => msg)
      .map(([k, msg]) => `<div class="error"><b>${labels[k]}:</b> ${esc(msg)}</div>`)
      .join("");

  const credits = status.opensky_credits_remaining != null ? ` · ${status.opensky_credits_remaining} OpenSky credits left` : "";
  $("#poll-meta").textContent = `Polled ${ago(status.last_poll)}${credits} · ${status.flightaware_requests} FlightAware lookups`;

  renderBoard(status.board);
  renderCurrent(status);
  renderNearby(status);
  updatePlanes(status);
}

async function refreshStatus() {
  try {
    renderStatus(await api("/api/status"));
  } catch (err) {
    $("#status-pill").textContent = "offline";
    $("#status-pill").className = "pill err";
  }
}

$("#btn-refresh").addEventListener("click", async () => {
  await api("/api/refresh", { method: "POST" });
  toast("Refreshing…");
  setTimeout(refreshStatus, 2500);
});

$("#btn-toggle").addEventListener("click", async () => {
  const enabled = !(lastStatus && lastStatus.enabled);
  await saveSettings({ enabled });
  toast(enabled ? "Tracking resumed" : "Tracking paused");
});

/* ---------- Manual message ---------- */

function renderManualInputs() {
  const flagship = $("[name=board_model]").value === "flagship";
  const rows = flagship ? 6 : 3, cols = flagship ? 22 : 15;
  const wrap = $("#manual-lines");
  const existing = $$("input", wrap).map((i) => i.value);
  wrap.innerHTML = "";
  for (let i = 0; i < rows; i++) {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "line-input";
    input.placeholder = `Row ${i + 1} (${cols} characters)`;
    input.value = existing[i] || "";
    wrap.appendChild(input);
  }
}

$("#manual-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const lines = $$("#manual-lines input").map((i) => i.value);
  const hold = Number(ev.target.elements.hold.value) || 0;
  try {
    await api("/api/board/message", { method: "POST", body: JSON.stringify({ lines, hold_minutes: hold }) });
    toast("Message sent");
    refreshStatus();
  } catch (err) {
    toast(`Could not send: ${err.message}`);
  }
});

$("#btn-resume").addEventListener("click", async () => {
  await api("/api/board/resume", { method: "POST" });
  toast("Resuming flight updates");
  setTimeout(refreshStatus, 1500);
});

/* ---------- Boot ---------- */

(async function boot() {
  initMap();
  try {
    settings = await api("/api/settings");
    fillForm(settings);
    renderManualInputs();
    updateMapLocation();
  } catch (err) {
    toast(`Could not load settings: ${err.message}`);
  }
  await refreshStatus();
  setInterval(refreshStatus, 5000);
})();
