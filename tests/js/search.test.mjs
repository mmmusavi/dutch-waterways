// node --test tests/js
import { test } from "node:test";
import assert from "node:assert/strict";
import { placeSearch, localIndex } from "../../web/search.js";

const doc = (type, weergavenaam, score, lon = 5, lat = 52) =>
  ({ type, weergavenaam, score, centroide_ll: `POINT(${lon} ${lat})` });

test("placeSearch puts towns first and splits the label", async () => {
  globalThis.fetch = async (url) => {
    assert.match(String(url), /suggest\?q=volen&/);
    return {
      ok: true,
      json: async () => ({ response: { docs: [
        doc("weg", "Volen, Heide", 10.3),
        doc("woonplaats", "Beets, Edam-Volendam, Noord-Holland", 7.7),
        doc("woonplaats", "Volendam, Edam-Volendam, Noord-Holland", 8.1, 5.07, 52.5),
        doc("gemeente", "Gemeente Edam-Volendam", 9.1),
      ] } }),
    };
  };
  const out = await placeSearch("volen");
  assert.deepEqual(out.map((r) => r.label), ["Volendam", "Beets", "Volen", "Gemeente Edam-Volendam"]);
  assert.equal(out[0].sub, "Edam-Volendam · Noord-Holland · place");
  assert.deepEqual(out[0].lonlat, [5.07, 52.5]);
  assert.equal(out[2].sub, "Heide · street");
});

test("placeSearch reports HTTP errors", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 503 });
  await assert.rejects(placeSearch("x"), /503/);
});

test("localIndex prefers word starts and locks, and adds the town", () => {
  const search = localIndex([
    { name: "Brug over Beatrixsluis", kind: "bridge", city: "Vreeswijk", lonlat: [0, 0] },
    { name: "Beatrixsluis", kind: "lock", city: "Almere", lonlat: [1, 1] },
    { name: "Prinses Beatrixsluizen", kind: "lock", city: "Vreeswijk", lonlat: [2, 2] },
    { name: "Hogebrug Rotterdam", kind: "bridge", city: "Rotterdam", lonlat: [3, 3] },
  ]);
  const out = search("beatrixsl");
  assert.deepEqual(out.map((r) => r.label), ["Beatrixsluis", "Prinses Beatrixsluizen", "Brug over Beatrixsluis"]);
  assert.equal(out[0].sub, "lock · Almere");
  assert.ok(out.every((r) => r.local));
  // The town is not repeated when the name already says it.
  assert.equal(search("hogebrug")[0].sub, "bridge");
});
