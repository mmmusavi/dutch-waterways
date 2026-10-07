// Run the browser router on cases from a JSON file and print the results.
// Usage: node run_routes.mjs network.json cases.json
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve, dirname } from "node:path";

const here = dirname(new URL(import.meta.url).pathname);
const { Router, NoRouteError } = await import(pathToFileURL(resolve(here, "../../web/router.js")));

const [network, cases] = process.argv.slice(2).map((p) => JSON.parse(readFileSync(p, "utf8")));
const router = new Router(network);
const out = cases.map((c) => {
  try {
    const r = router.route(c.a, c.b, c.vessel ?? {}, { access: c.access ?? "snap", maxAccess: c.maxAccess ?? null });
    return {
      lengthM: r.lengthM,
      belowClassM: r.belowClassM,
      accessM: r.accessM,
      smallestClass: r.smallestClass,
      sections: r.edges.map((e) => network.edges.sectionId[e]),
      structures: r.structures.map((s) => s.name),
      atKm: r.structures.map((s) => s.atKm),
      limits: r.limits,
      start: r.coords[0],
      end: r.coords[r.coords.length - 1],
    };
  } catch (e) {
    if (e instanceof NoRouteError) return { error: e.constructor.name };
    throw e;
  }
});
console.log(JSON.stringify(out));
