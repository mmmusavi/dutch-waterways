// The route planner page: map, inputs and results around router.js.

import { Router, NoRouteError, CLASSES } from "./router.js";
import { autocomplete, localIndex } from "./search.js";

const RD = "+proj=sterea +lat_0=52.15616055555555 +lon_0=5.38763888888889 +k=0.9999079 " +
  "+x_0=155000 +y_0=463000 +ellps=bessel +towgs84=565.417,50.3319,465.552,-0.398957,0.343988,-1.8774,4.0725 +units=m +no_defs";
const toRD = (lonlat) => proj4("EPSG:4326", RD, lonlat);
const toLonLat = (xy) => proj4(RD, "EPSG:4326", xy);

const CLASS_LABEL = { _0: "0", V_A: "Va", V_B: "Vb", VI_A: "VIa", VI_B: "VIb", VI_C: "VIc" };
const label = (c) => (c === null ? "unknown" : CLASS_LABEL[c] ?? c);
// Fairways by class: light to dark, unknown grey.
const CLASS_COLORS = ["#d3ece8", "#a9dad2", "#a9dad2", "#7fc6ba", "#52b0a1", "#2a9a8a", "#2a9a8a", "#1b7d70", "#1b7d70", "#0e5c52"];
const UNKNOWN_COLOR = "#b8bcc2";
const COLORS = { route: "#1f6feb", below: "#d97706", access: "#6b7280", lock: "#7c3aed", fixed: "#1c2430", movable: "#059669" };
const DIMS = ["length", "beam", "draught", "airDraught"];
const DIM_LABEL = { length: "length", beam: "beam", draught: "draught", airDraught: "air draught" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (m, digits = 1) => (m / 1000).toFixed(digits);

const state = { from: null, to: null }; // {lonlat, name}
let router, last = null;
let localSearch = () => []; // locks and bridges by name, once the network is in
const markers = {};

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.6, "raster-opacity": 0.9 } }],
  },
  center: [5.3, 52.2],
  zoom: 7,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
window.dwMap = map; // for debugging and page tests
if (window.matchMedia("(max-width: 640px)").matches) $("vessel").open = false;
document.body.dataset.state = "loading";

const emptyFC = { type: "FeatureCollection", features: [] };

function networkGeoJSON(data) {
  const e = data.edges;
  return {
    type: "FeatureCollection",
    features: e.coords.map((c, i) => {
      const pts = [];
      for (let k = 0; k < c.length; k += 2) pts.push(toLonLat([c[k], c[k + 1]]));
      const color = e.cemt[i] < 0 ? UNKNOWN_COLOR : CLASS_COLORS[e.cemt[i]];
      return { type: "Feature", properties: { color }, geometry: { type: "LineString", coordinates: pts } };
    }),
  };
}

function legend() {
  const groups = [["unknown", UNKNOWN_COLOR], ["0", CLASS_COLORS[0]], ["I–II", CLASS_COLORS[1]], ["III", CLASS_COLORS[3]],
    ["IV", CLASS_COLORS[4]], ["Va–Vb", CLASS_COLORS[5]], ["VIa–VIb", CLASS_COLORS[7]], ["VIc", CLASS_COLORS[9]]];
  $("legend").innerHTML = groups.map(([name, color]) => `<span><i style="background:${color}"></i>${name}</span>`).join("");
}

map.on("load", async () => {
  const res = await fetch("data/network.json");
  const data = await res.json();
  router = new Router(data);
  localSearch = localIndex(router.structures.map((st) => ({ name: st.name, kind: st.kind, city: st.city, lonlat: toLonLat([st.x, st.y]) })));
  $("built").textContent = `Network exported ${data.exported.slice(0, 10)}.`;

  map.addSource("network", { type: "geojson", data: networkGeoJSON(data) });
  map.addLayer({
    id: "network", type: "line", source: "network",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": ["get", "color"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 6, 1, 10, 2, 14, 4],
      "line-opacity": 0.9,
    },
  });
  for (const id of ["access", "pieces", "structures"]) map.addSource(id, { type: "geojson", data: emptyFC });
  map.addLayer({
    id: "access", type: "line", source: "access",
    paint: { "line-color": COLORS.access, "line-width": 2, "line-dasharray": [2, 2] },
  });
  map.addLayer({
    id: "route-casing", type: "line", source: "pieces",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 6, 6, 14, 12] },
  });
  map.addLayer({
    id: "route", type: "line", source: "pieces",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": ["case", ["get", "below"], COLORS.below, COLORS.route],
      "line-width": ["interpolate", ["linear"], ["zoom"], 6, 3.5, 14, 8],
    },
  });
  map.addLayer({
    id: "structures", type: "circle", source: "structures",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, ["case", ["==", ["get", "kind"], "lock"], 4, 2.5], 13, 7],
      "circle-color": ["case", ["==", ["get", "kind"], "lock"], COLORS.lock, ["get", "movable"], COLORS.movable, COLORS.fixed],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.2,
    },
  });
  map.on("click", "structures", (ev) => {
    ev.preventDefault();
    const f = ev.features[0];
    structurePopup(last.structures[f.properties.i], f.geometry.coordinates);
  });
  map.on("mouseenter", "structures", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "structures", () => (map.getCanvas().style.cursor = ""));
  map.on("click", (ev) => {
    if (ev.defaultPrevented) return;
    const lonlat = [ev.lngLat.lng, ev.lngLat.lat];
    setPlace(!state.from ? "from" : "to", { lonlat, name: null });
  });

  legend();
  readHash();
  update();
  document.body.dataset.state = last ? "route" : "ready";
});

function setPlace(which, place) {
  state[which] = place;
  if (markers[which]) markers[which].remove();
  markers[which] = null;
  $(which).value = place ? place.name ?? place.lonlat.map((v) => v.toFixed(4)).reverse().join(", ") : "";
  if (place) {
    const el = document.createElement("div");
    el.className = `pin ${which === "from" ? "a" : "b"}`;
    el.textContent = which === "from" ? "A" : "B";
    markers[which] = new maplibregl.Marker({ element: el, draggable: true }).setLngLat(place.lonlat).addTo(map);
    markers[which].on("dragend", () => {
      const ll = markers[which].getLngLat();
      setPlace(which, { lonlat: [ll.lng, ll.lat], name: null });
    });
  }
  update();
}

/** "lat, lon" (or "lon, lat") typed into a place box, as [lon, lat]; else null. */
function parseCoords(q) {
  const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (!m) return null;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a > 45 ? [b, a] : [a, b]; // NL latitudes are > 45, longitudes < 8
}

function vessel() {
  const v = { cemt: $("cemt").value || null };
  for (const d of DIMS) {
    const x = parseFloat($(d).value);
    if (x > 0) v[d] = x;
  }
  return v;
}

const access = () => document.querySelector('input[name="access"]:checked').value;

function update() {
  writeHash();
  if (!router) return;
  if (!state.from || !state.to) {
    last = null;
    draw(null);
    $("result").innerHTML = `<p class="hint">${state.from ? "Now choose a destination." : "Choose two places to plan a route."}</p>`;
    return;
  }
  try {
    last = router.route(toRD(state.from.lonlat), toRD(state.to.lonlat), vessel(), { access: access() });
    draw(last);
    render(last);
    document.body.dataset.state = "route";
  } catch (err) {
    last = null;
    draw(null);
    const msg = err instanceof NoRouteError
      ? "No route for this vessel between these places. Try a smaller class or dimensions, or “Over smaller fairways”."
      : `Something went wrong: ${err.message}`;
    $("result").innerHTML = `<p class="error">${esc(msg)}</p>`;
    if (!(err instanceof NoRouteError)) console.error(err);
  }
}

function draw(r) {
  if (!map.getSource("pieces")) return;
  if (!r) {
    for (const id of ["access", "pieces", "structures"]) map.getSource(id).setData(emptyFC);
    return;
  }
  const line = (coords, props = {}) => ({
    type: "Feature", properties: props, geometry: { type: "LineString", coordinates: coords.map(toLonLat) },
  });
  map.getSource("pieces").setData({ type: "FeatureCollection", features: r.pieces.map((p) => line(p.coords, { below: p.below })) });
  const legs = [];
  if (r.origin.distance > 1) legs.push(line([toRD(state.from.lonlat), r.origin.point]));
  if (r.destination.distance > 1) legs.push(line([r.destination.point, toRD(state.to.lonlat)]));
  map.getSource("access").setData({ type: "FeatureCollection", features: legs });
  map.getSource("structures").setData({
    type: "FeatureCollection",
    features: r.structures.map((s, i) => ({
      type: "Feature",
      properties: { i, kind: s.kind, movable: s.movable },
      geometry: { type: "Point", coordinates: toLonLat([s.x, s.y]) },
    })),
  });
}

function kindOf(s) {
  return s.kind === "lock" ? "lock" : s.movable ? "movable bridge" : "fixed bridge";
}

function render(r) {
  const movable = r.bridges.filter((b) => b.movable).length;
  const limits = DIMS.filter((d) => r.limits[d] !== null).map((d) => `${DIM_LABEL[d]} ${r.limits[d]} m`);
  const rows = [
    ["Access legs", `${fmt(r.origin.distance, 2)} + ${fmt(r.destination.distance, 2)} km <small>(straight line, not counted)</small>`],
    ["Smallest class", esc(label(r.smallestClass))],
  ];
  if (r.minClass !== null && r.belowClassM > 0) {
    rows.push(["Below class", `<span class="below">${fmt(r.belowClassM)} km below ${esc(label(r.minClass))}</span>`]);
  }
  rows.push(["Bridges", `${r.bridges.length}${r.bridges.length ? ` (${movable} movable)` : ""}`], ["Locks", `${r.locks.length}`]);
  const list = r.structures.map((s, i) => `
    <li data-i="${i}"><span class="km">km ${s.atKm.toFixed(1)}</span>
      <span class="dot ${s.kind === "lock" ? "lock" : s.movable ? "movable" : "fixed"}" title="${kindOf(s)}"></span>
      <span>${esc(s.name)}</span></li>`).join("");
  $("result").innerHTML = `
    <div class="distance">${fmt(r.lengthM)} <small>km along the fairways</small></div>
    <dl class="facts">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    ${limits.length ? `<div class="limits"><b>This route takes at most</b>${limits.join(" · ")}</div>` : ""}
    ${list ? `<ol class="structures">${list}</ol>` : ""}`;
  $("result").querySelectorAll("ol.structures li").forEach((li) => {
    li.addEventListener("click", () => {
      const s = r.structures[Number(li.dataset.i)];
      const ll = toLonLat([s.x, s.y]);
      map.flyTo({ center: ll, zoom: Math.max(map.getZoom(), 14) });
      structurePopup(s, ll);
    });
  });
}

function structurePopup(s, lonlat) {
  const passages = s.passages.map(([w, l, c]) => {
    const parts = [];
    if (w !== null) parts.push(`width ${w} m`);
    if (l !== null) parts.push(`length ${l} m`);
    if (c !== null) parts.push(`clearance ${c} m`);
    else if (s.kind === "bridge") parts.push("opens");
    return parts.join(", ");
  }).filter(Boolean);
  new maplibregl.Popup({ maxWidth: "280px" })
    .setLngLat(lonlat)
    .setHTML(`<b>${esc(s.name)}</b><br>${kindOf(s)}, km ${s.atKm.toFixed(1)}` +
      (passages.length ? `<br>${passages.map(esc).join("<br>")}` : "<br>no dimensions in FIS"))
    .addTo(map);
}

function fit() {
  const pts = [state.from, state.to].filter(Boolean).map((p) => p.lonlat);
  if (!pts.length) return;
  if (pts.length === 1) return map.flyTo({ center: pts[0], zoom: Math.max(map.getZoom(), 10) });
  const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
  pts.forEach((p) => b.extend(p));
  if (last) last.coords.forEach((c) => b.extend(toLonLat(c)));
  const wide = window.innerWidth > 640;
  map.fitBounds(b, { padding: wide ? { top: 40, bottom: 40, left: 400, right: 40 } : { top: 40, bottom: window.innerHeight * 0.55, left: 30, right: 30 }, maxZoom: 13 });
}

// --- URL hash: shareable routes -------------------------------------------

function writeHash() {
  const p = new URLSearchParams();
  for (const which of ["from", "to"]) {
    const s = state[which];
    if (!s) continue;
    p.set(which, s.lonlat.map((v) => v.toFixed(5)).join(","));
    if (s.name) p.set(`${which}Name`, s.name);
  }
  const v = vessel();
  if (v.cemt) p.set("class", v.cemt);
  for (const d of DIMS) if (v[d]) p.set(d, v[d]);
  if (access() !== "snap") p.set("access", access());
  const hash = p.toString();
  history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.get("class")) $("cemt").value = p.get("class");
  for (const d of DIMS) if (p.get(d)) $(d).value = p.get(d);
  if (p.get("access")) document.querySelector(`input[name="access"][value="${p.get("access")}"]`).checked = true;
  for (const which of ["from", "to"]) {
    const ll = p.get(which)?.split(",").map(Number);
    if (ll?.length === 2 && ll.every(Number.isFinite)) {
      state[which] = null;
      setPlace(which, { lonlat: ll, name: p.get(`${which}Name`) });
    }
  }
  fit();
}

// --- inputs ------------------------------------------------------------------

for (const which of ["from", "to"]) {
  const input = $(which);
  // Typed coordinates win over suggestions (capture phase, before autocomplete).
  input.addEventListener("keydown", (ev) => {
    const ll = ev.key === "Enter" && parseCoords(input.value);
    if (!ll) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    setPlace(which, { lonlat: ll, name: null });
    fit();
  }, true);
  autocomplete(input, $(`${which}-list`), {
    local: (q) => (parseCoords(q) ? [] : localSearch(q)),
    onSelect: (item) => {
      setPlace(which, { lonlat: item.lonlat, name: item.label });
      fit();
    },
    onError: (err) => { $("result").innerHTML = `<p class="error">${esc(err.message)}</p>`; },
  });
  input.addEventListener("search", () => { if (!input.value) setPlace(which, null); });
}
$("places").addEventListener("submit", (ev) => ev.preventDefault());
$("swap").addEventListener("click", () => {
  const [a, b] = [state.from, state.to];
  state.from = state.to = null;
  setPlace("from", b);
  setPlace("to", a);
});
$("clear").addEventListener("click", () => {
  setPlace("from", null);
  setPlace("to", null);
});
let timer;
for (const id of ["cemt", ...DIMS]) {
  $(id).addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(update, 250);
  });
}
document.querySelectorAll('input[name="access"]').forEach((el) => el.addEventListener("change", update));
$("showNetwork").addEventListener("change", (ev) => {
  map.setLayoutProperty("network", "visibility", ev.target.checked ? "visible" : "none");
  $("legend").hidden = !ev.target.checked;
});
