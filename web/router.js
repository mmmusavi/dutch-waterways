// Routing over the network exported by `dutch-waterways export-web`.
//
// A port of dutch_waterways.network: same snapping, access modes, vessel
// checks and shortest paths. Works in RD New metres (EPSG:28992). No DOM, so
// it runs in the browser and in Node.

export const CLASSES = ["_0", "I", "II", "III", "IV", "V_A", "V_B", "VI_A", "VI_B", "VI_C", "VII"];
export const BELOW_CLASS_PENALTY = 1000;
const ALIASES = { "0": "_0", VA: "V_A", VB: "V_B", VIA: "VI_A", VIB: "VI_B", VIC: "VI_C" };
const DIMS = ["length", "beam", "draught", "airDraught"];
const LIMIT_KEYS = { length: "maxLength", beam: "maxBeam", draught: "maxDraught", airDraught: "maxAirDraught" };
const CELL = 2000; // snapping grid, metres

export class NoRouteError extends Error {}
export class TooFarError extends NoRouteError {}

/** Rank of a CEMT class ("Va", "V_A", "iv", 4, ...); null stays null. */
export function classRank(cls) {
  if (cls === null || cls === undefined || cls === "") return null;
  if (typeof cls === "number") {
    if (cls < 0 || cls >= CLASSES.length) throw new Error(`unknown CEMT rank: ${cls}`);
    return cls;
  }
  const key = String(cls).trim().toUpperCase().replace(/[ _]/g, "");
  const code = ALIASES[key] ?? key;
  const rank = CLASSES.indexOf(code);
  if (rank < 0) throw new Error(`unknown CEMT class: ${cls}`);
  return rank;
}

class Heap {
  constructor() { this.items = []; }
  get size() { return this.items.length; }
  push(cost, node) {
    const a = this.items;
    a.push([cost, node]);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p][0] <= a[i][0]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop() {
    const a = this.items;
    const top = a[0];
    const last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }
}

function project(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const x = ax + t * dx, y = ay + t * dy;
  return { t, x, y, d: Math.hypot(px - x, py - y) };
}

export class Router {
  constructor(data) {
    const e = data.edges;
    this.data = data;
    this.n = e.source.length;
    this.nodeCount = data.nodes;
    this.source = e.source;
    this.target = e.target;
    this.length = e.length;
    this.rank = e.cemt;
    this.limits = Object.fromEntries(DIMS.map((d) => [d, e[LIMIT_KEYS[d]]]));
    this.coords = e.coords;

    // Cumulative distance along each (simplified) line, and the factor that
    // turns it into true metres.
    this.cum = this.coords.map((c) => {
      const out = [0];
      for (let i = 2; i < c.length; i += 2) out.push(out[out.length - 1] + Math.hypot(c[i] - c[i - 2], c[i + 1] - c[i - 1]));
      return out;
    });
    this.scale = this.cum.map((c, i) => (c[c.length - 1] > 0 ? this.length[i] / c[c.length - 1] : 1));

    this.adj = Array.from({ length: this.nodeCount }, () => []);
    for (let i = 0; i < this.n; i++) {
      this.adj[this.source[i]].push(i);
      this.adj[this.target[i]].push(i);
    }

    const s = data.structures;
    this.structures = s.edge.map((edge, i) => ({
      index: i, edge, kind: s.kind[i], name: s.name[i], city: s.city?.[i] ?? null, offset: s.offset[i],
      movable: s.movable[i], x: s.x[i], y: s.y[i], passages: s.passages[i],
    }));
    this.onEdge = new Map();
    for (const st of this.structures) {
      if (!this.onEdge.has(st.edge)) this.onEdge.set(st.edge, []);
      this.onEdge.get(st.edge).push(st);
    }

    this.grid = new Map();
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    this.coords.forEach((c, edge) => {
      for (let k = 0; k + 3 < c.length; k += 2) {
        const [ax, ay, bx, by] = [c[k], c[k + 1], c[k + 2], c[k + 3]];
        minX = Math.min(minX, ax, bx); maxX = Math.max(maxX, ax, bx);
        minY = Math.min(minY, ay, by); maxY = Math.max(maxY, ay, by);
        for (let gx = Math.floor(Math.min(ax, bx) / CELL); gx <= Math.floor(Math.max(ax, bx) / CELL); gx++) {
          for (let gy = Math.floor(Math.min(ay, by) / CELL); gy <= Math.floor(Math.max(ay, by) / CELL); gy++) {
            const key = `${gx},${gy}`;
            if (!this.grid.has(key)) this.grid.set(key, []);
            this.grid.get(key).push(edge, k >> 1);
          }
        }
      }
    });
    this.bounds = { minX, minY, maxX, maxY };
    this.blockedCache = new Map();
  }

  /** Normalised vessel: {cemt: rank|null, length, beam, draught, airDraught}. */
  vessel(v = {}) {
    const out = { cemt: classRank(v.cemt ?? null) };
    for (const d of DIMS) out[d] = v[d] === undefined || v[d] === "" || v[d] === null ? null : Number(v[d]);
    return out;
  }

  /** Per edge: true when the vessel's dimensions do not fit it. */
  blocked(v) {
    const key = DIMS.map((d) => v[d]).join("|");
    if (this.blockedCache.has(key)) return this.blockedCache.get(key);
    const out = new Uint8Array(this.n);
    for (const d of DIMS) {
      const need = v[d];
      if (need === null) continue;
      const lim = this.limits[d];
      for (let i = 0; i < this.n; i++) if (lim[i] !== null && lim[i] < need) out[i] = 1;
    }
    if (DIMS.some((d) => v[d] !== null && d !== "draught")) {
      for (const st of this.structures) if (!this.passable(st, v)) out[st.edge] = 1;
    }
    this.blockedCache.set(key, out);
    return out;
  }

  /** Whether one passage of a structure fits the vessel (unknown fits). */
  passable(st, v) {
    if (!st.passages.length) return true;
    return st.passages.some(([w, l, c]) =>
      (v.beam === null || w === null || w >= v.beam) &&
      (v.length === null || l === null || l >= v.length) &&
      (v.airDraught === null || c === null || c >= v.airDraught));
  }

  usableMask(v, withClass) {
    const blocked = this.blocked(v);
    const out = new Uint8Array(this.n);
    for (let i = 0; i < this.n; i++) {
      out[i] = !blocked[i] && (!withClass || v.cemt === null || this.rank[i] >= v.cemt) ? 1 : 0;
    }
    return out;
  }

  /** Nearest usable edge to (x, y), in RD metres. */
  snap(x, y, usable) {
    let best = null;
    const consider = (edge, seg) => {
      if (!usable[edge]) return;
      const c = this.coords[edge];
      const p = project(x, y, c[2 * seg], c[2 * seg + 1], c[2 * seg + 2], c[2 * seg + 3]);
      if (!best || p.d < best.distance) {
        const along = this.cum[edge][seg] + p.t * (this.cum[edge][seg + 1] - this.cum[edge][seg]);
        best = { edge, offset: along * this.scale[edge], distance: p.d, point: [p.x, p.y] };
      }
    };
    const gx = Math.floor(x / CELL), gy = Math.floor(y / CELL);
    const maxRing = Math.ceil(Math.max(
      Math.abs(x - this.bounds.minX), Math.abs(x - this.bounds.maxX),
      Math.abs(y - this.bounds.minY), Math.abs(y - this.bounds.maxY)) / CELL) + 1;
    for (let r = 0; r <= maxRing; r++) {
      for (let i = gx - r; i <= gx + r; i++) {
        for (let j = gy - r; j <= gy + r; j++) {
          if (Math.max(Math.abs(i - gx), Math.abs(j - gy)) !== r) continue;
          const cell = this.grid.get(`${i},${j}`);
          if (!cell) continue;
          for (let k = 0; k < cell.length; k += 2) consider(cell[k], cell[k + 1]);
        }
      }
      // Anything in a further ring is at least r * CELL away.
      if (best && best.distance <= r * CELL) break;
    }
    if (!best) throw new NoRouteError("no sections fit this vessel");
    return best;
  }

  /**
   * Shortest route from a to b ([x, y] in RD metres) for a vessel.
   * options: {access: "snap" | "network", maxAccess: metres | null}
   */
  route(a, b, vesselSpec = {}, { access = "snap", maxAccess = null } = {}) {
    if (access !== "snap" && access !== "network") throw new Error(`bad access mode: ${access}`);
    const v = this.vessel(vesselSpec);
    const usable = this.usableMask(v, access === "snap");
    const snaps = [this.snap(a[0], a[1], usable), this.snap(b[0], b[1], usable)];
    snaps.forEach((s, k) => {
      if (maxAccess !== null && s.distance > maxAccess) {
        throw new TooFarError(`${k ? "destination" : "origin"} is ${Math.round(s.distance)} m from the nearest usable fairway`);
      }
    });
    const factor = (e) => (v.cemt !== null && this.rank[e] < v.cemt ? BELOW_CLASS_PENALTY : 1);

    // Splice the query points into their edges as nodes N and N + 1.
    const N = this.nodeCount;
    const extra = new Map();
    const link = (u, w, l) => {
      if (!extra.has(u)) extra.set(u, []);
      extra.get(u).push({ ...l, to: w });
    };
    const spliced = new Set(snaps.map((s) => s.edge));
    for (const edge of spliced) {
      const pts = snaps.map((s, k) => [s.offset, N + k]).filter((_, k) => snaps[k].edge === edge);
      const chain = [[0, this.source[edge]], ...pts.sort((p, q) => p[0] - q[0]), [this.length[edge], this.target[edge]]];
      for (let i = 0; i + 1 < chain.length; i++) {
        const [o1, n1] = chain[i], [o2, n2] = chain[i + 1];
        const len = o2 - o1, cost = len * factor(edge);
        link(n1, n2, { edge, length: len, cost, from: o1, until: o2 });
        link(n2, n1, { edge, length: len, cost, from: o2, until: o1 });
      }
    }

    const dist = new Map([[N, 0]]);
    const prev = new Map();
    const heap = new Heap();
    heap.push(0, N);
    const done = new Set();
    while (heap.size) {
      const [d, u] = heap.pop();
      if (done.has(u)) continue;
      done.add(u);
      if (u === N + 1) break;
      const relax = (w, l) => {
        const nd = d + l.cost;
        if (nd < (dist.get(w) ?? Infinity)) {
          dist.set(w, nd);
          prev.set(w, { ...l, at: u });
          heap.push(nd, w);
        }
      };
      if (u < N) {
        for (const e of this.adj[u]) {
          if (!usable[e] || spliced.has(e)) continue;
          const w = this.source[e] === u ? this.target[e] : this.source[e];
          const forward = this.source[e] === u;
          relax(w, {
            edge: e, length: this.length[e], cost: this.length[e] * factor(e),
            from: forward ? 0 : this.length[e], until: forward ? this.length[e] : 0,
          });
        }
      }
      for (const l of extra.get(u) ?? []) relax(l.to, l);
    }
    if (!done.has(N + 1)) throw new NoRouteError("no route for this vessel between these places");

    const legs = [];
    for (let node = N + 1; node !== N; node = prev.get(node).at) legs.push(prev.get(node));
    legs.reverse();
    return this.result(legs.filter((l) => l.length > 0), snaps, v);
  }

  result(legs, snaps, v) {
    let lengthM = 0, belowClassM = 0, done = 0;
    const coords = [];
    const passed = [];
    const pieces = []; // [{coords, below}] runs of legs below / within the class
    for (const l of legs) {
      lengthM += l.length;
      const below = v.cemt !== null && this.rank[l.edge] < v.cemt;
      if (below) belowClassM += l.length;
      const pts = this.piece(l);
      const run = pieces[pieces.length - 1];
      if (run && run.below === below) run.coords.push(...pts.slice(1));
      else pieces.push({ below, coords: pts });
      for (const p of pts) {
        const last = coords[coords.length - 1];
        if (!last || last[0] !== p[0] || last[1] !== p[1]) coords.push(p);
      }
      const lo = Math.min(l.from, l.until), hi = Math.max(l.from, l.until);
      for (const st of this.onEdge.get(l.edge) ?? []) {
        if (st.offset >= lo - 1e-6 && st.offset <= hi + 1e-6) {
          passed.push({ ...st, atKm: (done + Math.abs(st.offset - l.from)) / 1000 });
        }
      }
      done += l.length;
    }
    passed.sort((p, q) => p.atKm - q.atKm);
    if (coords.length === 0) coords.push(snaps[0].point);
    if (coords.length === 1) coords.push(coords[0]);

    const edges = legs.map((l) => l.edge);
    const ranks = edges.map((e) => this.rank[e]).filter((r) => r >= 0);
    return {
      lengthM, belowClassM, coords, pieces, edges,
      origin: snaps[0], destination: snaps[1],
      accessM: snaps[0].distance + snaps[1].distance,
      minClass: v.cemt === null ? null : CLASSES[v.cemt],
      smallestClass: ranks.length ? CLASSES[Math.min(...ranks)] : null,
      structures: passed,
      locks: passed.filter((s) => s.kind === "lock"),
      bridges: passed.filter((s) => s.kind === "bridge"),
      limits: this.routeLimits(edges, passed),
    };
  }

  /** The largest vessel the route takes, dimension by dimension (null = no limit known). */
  routeLimits(edges, passed) {
    const out = {};
    DIMS.forEach((d, i) => {
      const values = edges.map((e) => this.limits[d][e]).filter((x) => x !== null);
      const slot = { length: 1, beam: 0, airDraught: 2 }[d];
      if (slot !== undefined) {
        for (const st of passed) {
          const p = st.passages.map((q) => q[slot]);
          if (p.length && p.every((x) => x !== null)) values.push(Math.max(...p));
        }
      }
      out[d] = values.length ? Math.round(Math.min(...values) * 100) / 100 : null;
    });
    return out;
  }

  /** Coordinates of a leg, from l.from to l.until (true metres along its edge). */
  piece(l) {
    const c = this.coords[l.edge], cum = this.cum[l.edge], s = this.scale[l.edge];
    const a = l.from / s, b = l.until / s;
    const lo = Math.min(a, b), hi = Math.max(a, b);
    const at = (t) => {
      let k = 0;
      while (k + 1 < cum.length - 1 && cum[k + 1] < t) k++;
      const seg = cum[k + 1] - cum[k];
      const f = seg ? (t - cum[k]) / seg : 0;
      return [c[2 * k] + f * (c[2 * k + 2] - c[2 * k]), c[2 * k + 1] + f * (c[2 * k + 3] - c[2 * k + 1])];
    };
    const pts = [at(lo)];
    for (let k = 0; k < cum.length; k++) if (cum[k] > lo && cum[k] < hi) pts.push([c[2 * k], c[2 * k + 1]]);
    pts.push(at(hi));
    return a <= b ? pts : pts.reverse();
  }
}
