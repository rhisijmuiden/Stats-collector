// Checks that English and Dutch have exactly the same keys and that every static t("…") key exists.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const load = (l) => JSON.parse(readFileSync(new URL(`../src/locales/${l}.json`, import.meta.url)));
const flatten = (o, p = "") =>
  Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? flatten(v, `${p}${k}.`) : [`${p}${k}`]));

const en = new Set(flatten(load("en")));
const nl = new Set(flatten(load("nl")));

test("en and nl have the same keys", () => {
  assert.deepEqual([...en].filter((k) => !nl.has(k)), [], "missing in nl");
  assert.deepEqual([...nl].filter((k) => !en.has(k)), [], "missing in en");
});

function* files(dir) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) yield* files(p);
    else if (/\.tsx?$/.test(f)) yield p;
  }
}

test("every static translation key exists", () => {
  const missing = [];
  for (const file of files(new URL("../src", import.meta.url).pathname)) {
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(/\bt\(["']([a-zA-Z0-9_.]+)["']/g)) if (!en.has(m[1]) && !en.has(`${m[1]}_other`)) missing.push(`${file}: ${m[1]}`);
    // template keys like t(`roles.${r}`): check the prefix exists
    for (const m of src.matchAll(/\bt\(`([a-zA-Z0-9_.]+)\$\{/g)) {
      const prefix = m[1];
      if (![...en].some((k) => k.startsWith(prefix))) missing.push(`${file}: ${prefix}*`);
    }
  }
  assert.deepEqual(missing, []);
});
