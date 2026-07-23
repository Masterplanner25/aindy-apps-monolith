// Audit every route the client can call against the live backend's openapi.
//
// The ui-kit builds app routes as `${g}/...` where g === "" — so they carry no /apps prefix.
// Some backend routers also register an unprefixed legacy alias, so SOME work and some 404.
// This finds exactly which are broken and whether an /apps-prefixed variant exists.
import { readFileSync } from "fs";

const bundle = readFileSync("client/node_modules/@aindy/ui-kit/dist/index.js", "utf-8");

// Pull ROUTES literals: `${g}/foo/bar` and plain "/foo/bar" inside the ROUTES map.
const tmpl = [...bundle.matchAll(/`\$\{g\}(\/[a-zA-Z0-9/_-]*)/g)].map((m) => m[1]);
const routes = [...new Set(tmpl)].sort();

const spec = await (await fetch("http://localhost:8000/openapi.json")).json();
const paths = new Set(Object.keys(spec.paths));

// normalize openapi's {param} templating to compare shapes
const norm = (p) => p.replace(/\{[^}]+\}/g, "{}");
const normPaths = new Set([...paths].map(norm));

const broken = [];
const ok = [];
for (const r of routes) {
  const exists = normPaths.has(norm(r));
  const appsVariant = normPaths.has(norm("/apps" + r));
  if (exists) ok.push(r);
  else broken.push({ route: r, appsVariant });
}

console.log(`ui-kit app routes checked: ${routes.length}`);
console.log(`  resolve OK as-is : ${ok.length}`);
console.log(`  BROKEN (404)     : ${broken.length}`);
console.log("");
const fixable = broken.filter((b) => b.appsVariant);
const unknown = broken.filter((b) => !b.appsVariant);
console.log(`--- BROKEN, but /apps${"{route}"} exists (needs prefix): ${fixable.length} ---`);
for (const b of fixable) console.log(`  ${b.route}   ->   /apps${b.route}`);
console.log("");
console.log(`--- BROKEN, no /apps variant either (route genuinely absent): ${unknown.length} ---`);
for (const b of unknown) console.log(`  ${b.route}`);
