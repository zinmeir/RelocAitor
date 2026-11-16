export function geoNaturalEarth1() {
  const p = ([lon, lat]) => [(lon + 180) / 360 * 1000, (90 - lat) / 180 * 500];
  p.fitSize = () => p;
  return p;
}
export function geoPath(proj) {
  return f => f.geometry.coordinates.map(ring => "M" + ring.map(c => proj(c).map(v => v.toFixed(1)).join(",")).join("L") + "Z").join("");
}
