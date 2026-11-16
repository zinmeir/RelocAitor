// Usage: node preview/parity.js <data.json> <cases.json>
// Runs every case through the JavaScript port and prints JSON {total, failures: [...]}.
const fs = require("fs");
const path = require("path");
globalThis.RELOC_DATA = JSON.parse(fs.readFileSync(process.argv[2]));
require(path.join(__dirname, "search_port.js"));
require(path.join(__dirname, "mock_api.js"));
const cases = JSON.parse(fs.readFileSync(process.argv[3]));
const IGNORE = new Set(["global_rank"]);   // internal tie-break field, never shown
function diff(a, b, p) {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-3 ? [] : [`${p}: py=${a} js=${b}`];
  if (a === null || b === null || typeof a !== "object") return a === b ? [] : [`${p}: py=${JSON.stringify(a)} js=${JSON.stringify(b)}`];
  let out = [];
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    if (IGNORE.has(k)) continue;
    if (!(k in a) || !(k in b)) { out.push(`${p}.${k}: missing in ${k in a ? "js" : "py"}`); continue; }
    out = out.concat(diff(a[k], b[k], `${p}.${k}`));
  }
  return out;
}
const failures = [];
for (const c of cases) {
  const r = RelocMockAPI.handle(c.path, c.body);
  let d = r.status !== c.status ? [`status py=${c.status} js=${r.status}`] : [];
  if (c.status === 200) d = d.concat(diff(c.json, r.json, ""));
  if (d.length) failures.push({ path: c.path, body: c.body, diff: d.slice(0, 5) });
}
console.log(JSON.stringify({ total: cases.length, failures }));
