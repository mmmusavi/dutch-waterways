// Place autocomplete: locks and bridges from the network, plus Dutch places,
// streets, addresses and postcodes from PDOK's Locatieserver (Kadaster's
// open geocoder, made for search-as-you-type; no key needed).

const PDOK = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest";
const MIN_CHARS = 2;
const DEBOUNCE_MS = 150;

// Lower comes first; within a type, PDOK's own score decides.
const TYPE_ORDER = { woonplaats: 0, weg: 1, adres: 2, postcode: 3 };
const TYPE_LABEL = { woonplaats: "place", weg: "street", adres: "address", postcode: "postcode" };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** Places from PDOK, best first: [{label, sub, lonlat}]. */
export async function placeSearch(q, signal) {
  const params = new URLSearchParams({
    q, rows: "10", fl: "id,weergavenaam,type,centroide_ll,score",
    fq: "type:(woonplaats OR weg OR adres OR postcode)",
  });
  const res = await fetch(`${PDOK}?${params}`, { signal });
  if (!res.ok) throw new Error(`place search failed (${res.status})`);
  const docs = (await res.json()).response?.docs ?? [];
  return docs
    .map((d) => {
      const m = /POINT\(([-\d.]+) ([-\d.]+)\)/.exec(d.centroide_ll ?? "");
      if (!m) return null;
      const [name, ...rest] = d.weergavenaam.split(", ");
      return {
        order: TYPE_ORDER[d.type] ?? 9,
        score: d.score ?? 0,
        label: name,
        sub: [...rest, TYPE_LABEL[d.type]].filter(Boolean).join(" · "),
        lonlat: [Number(m[1]), Number(m[2])],
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.order - b.order || b.score - a.score)
    .slice(0, 6);
}

/** Towns first, then locks and bridges on the network, then streets and the rest. */
function merge(remote, local) {
  const towns = remote.filter((r) => r.order === 0).slice(0, 3);
  const rest = remote.filter((r) => r.order !== 0);
  return [...towns, ...local.slice(0, 3), ...rest].slice(0, 8);
}

/**
 * Turn an input into a combobox with suggestions.
 *  local(q)        -> [{label, sub, lonlat}] found without the network
 *  onSelect(item)  -> called with the chosen item
 * Returns {choose()} to pick the best match for the current text.
 */
export function autocomplete(input, list, { local = () => [], onSelect, onError = () => {} }) {
  let items = [];
  let active = -1;
  let timer;
  let ctrl;
  let seq = 0;

  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", list.id);
  input.setAttribute("aria-expanded", "false");
  list.setAttribute("role", "listbox");

  const close = () => {
    list.hidden = true;
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  };

  const render = () => {
    if (!items.length) return close();
    list.innerHTML = items.map((it, i) => `
      <li role="option" id="${list.id}-${i}" data-i="${i}" aria-selected="${i === active}"
          class="${it.local ? "local" : ""}">
        <span class="label">${esc(it.label)}</span>
        ${it.sub ? `<span class="sub">${esc(it.sub)}</span>` : ""}
      </li>`).join("");
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    if (active >= 0) input.setAttribute("aria-activedescendant", `${list.id}-${active}`);
    else input.removeAttribute("aria-activedescendant");
  };

  const pick = (it) => {
    close();
    input.value = it.label;
    onSelect(it);
  };

  const search = async (q) => {
    ctrl?.abort();
    ctrl = new AbortController();
    const mine = ++seq;
    try {
      const remote = await placeSearch(q, ctrl.signal);
      if (mine !== seq) return null;
      items = merge(remote, local(q));
      active = -1;
      if (document.activeElement === input) render();
      return items;
    } catch (err) {
      if (err.name !== "AbortError") onError(err);
      return null;
    }
  };

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < MIN_CHARS) {
      seq++;
      items = [];
      return close();
    }
    items = local(q).slice(0, 3);
    active = -1;
    render();
    timer = setTimeout(() => search(q), DEBOUNCE_MS);
  });

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!items.length) return;
      ev.preventDefault();
      const step = ev.key === "ArrowDown" ? 1 : -1;
      active = (active + step + items.length) % items.length;
      render();
      list.children[active]?.scrollIntoView({ block: "nearest" });
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      choose();
    } else if (ev.key === "Escape") {
      close();
    }
  });

  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("focus", () => { if (items.length && input.value.trim().length >= MIN_CHARS) render(); });
  list.addEventListener("mousedown", (ev) => ev.preventDefault()); // keep focus in the input
  list.addEventListener("click", (ev) => {
    const li = ev.target.closest("li[data-i]");
    if (li) pick(items[Number(li.dataset.i)]);
  });

  /** Pick the highlighted suggestion, else the best one, searching if needed. */
  async function choose() {
    const q = input.value.trim();
    if (!q) return;
    if (active >= 0 && items[active]) return pick(items[active]);
    clearTimeout(timer);
    const found = items.length && !list.hidden ? items : await search(q);
    if (found?.length) pick(found[0]);
    else if (found) onError(new Error(`No place found for “${q}”.`));
  }

  return { choose, close };
}

/** A local search over named network objects: [{label, sub, lonlat, local: true}]. */
export function localIndex(entries) {
  // entries: [{name, kind, city, lonlat}]; one per name and place, locks before bridges.
  const byName = new Map();
  for (const e of entries) {
    const key = `${e.name.toLowerCase()}|${(e.city ?? "").toLowerCase()}`;
    if (!byName.has(key) || (e.kind === "lock" && byName.get(key).kind !== "lock")) byName.set(key, e);
  }
  const all = [...byName.values()];
  return (q) => {
    const needle = q.toLowerCase();
    return all
      .map((e) => {
        const name = e.name.toLowerCase();
        const at = name.indexOf(needle);
        if (at < 0) return null;
        const wordStart = at === 0 || /[\s\-('’]/.test(name[at - 1]);
        return { e, score: (wordStart ? 0 : 10) + (e.kind === "lock" ? 0 : 5) + name.length / 100 };
      })
      .filter(Boolean)
      .sort((a, b) => a.score - b.score)
      .map(({ e }) => ({
        label: e.name,
        sub: [e.kind, e.city && !e.name.toLowerCase().includes(e.city.toLowerCase()) ? e.city : null]
          .filter(Boolean).join(" · "),
        lonlat: e.lonlat,
        local: true,
      }));
  };
}
