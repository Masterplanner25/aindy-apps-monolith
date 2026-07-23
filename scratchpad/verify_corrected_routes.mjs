// Verify the CORRECTED route map (client/src/api/_routes.js) against the live backend.
// Functions are probed with a dummy arg so parameterized routes are shape-checked too.
import { ROUTES } from "../client/src/api/_routes.js";

const spec = await (await fetch("http://localhost:8000/openapi.json")).json();
const norm = (p) => p.replace(/\{[^}]+\}/g, "{}").replace(/\/$/, "") || "/";
const backend = new Set(Object.keys(spec.paths).map(norm));

const resolved = [];
for (const [domain, group] of Object.entries(ROUTES)) {
  for (const [key, value] of Object.entries(group)) {
    let path;
    if (typeof value === "string") path = value;
    else if (typeof value === "function") {
      try { path = value("X"); } catch { continue; }
    } else continue;
    if (typeof path !== "string" || !path.startsWith("/")) continue;
    resolved.push({ id: `${domain}.${key}`, path });
  }
}

const shape = (p) => norm(p.replace(/\/X(?=\/|$)/g, "/{}"));
const ok = [], bad = [];
for (const r of resolved) (backend.has(shape(r.path)) ? ok : bad).push(r);

console.log(`resolved client routes : ${resolved.length}`);
console.log(`  match backend        : ${ok.length}`);
console.log(`  still unmatched      : ${bad.length}`);
if (bad.length) {
  console.log("\n--- unmatched ---");
  for (const b of bad) console.log(`  ${b.id.padEnd(34)} ${b.path}`);
}
