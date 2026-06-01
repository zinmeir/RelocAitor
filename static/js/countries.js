/* =============================================================
   countries.js
   Loads real world map GeoJSON from a public CDN, projects it to
   our SVG viewBox (1000x500), and exposes country paths by ISO-3.
   Includes M49 -> ISO-3 mapping for all 65 dataset countries.
   ============================================================= */

const WORLD_ATLAS_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

// Numeric M49 (used by world-atlas) -> ISO-3 code
const M49_TO_ISO3 = {
  // North America
  "840": "USA", "124": "CAN", "484": "MEX", "188": "CRI", "591": "PAN",
  // South America
  "076": "BRA", "032": "ARG", "152": "CHL", "858": "URY", "170": "COL", "604": "PER",
  // Europe
  "826": "GBR", "372": "IRL", "276": "DEU", "250": "FRA", "528": "NLD",
  "056": "BEL", "752": "SWE", "578": "NOR", "208": "DNK", "246": "FIN",
  "352": "ISL", "756": "CHE", "040": "AUT", "724": "ESP", "620": "PRT",
  "380": "ITA", "300": "GRC", "203": "CZE", "616": "POL", "348": "HUN",
  "233": "EST", "642": "ROU", "191": "HRV", "705": "SVN", "643": "RUS",
  "268": "GEO", "196": "CYP",
  // Oceania
  "036": "AUS", "554": "NZL",
  // Asia
  "392": "JPN", "410": "KOR", "702": "SGP", "158": "TWN", "344": "HKG",
  "156": "CHN", "704": "VNM", "356": "IND", "360": "IDN", "608": "PHL",
  "458": "MYS", "764": "THA", "144": "LKA",
  // Middle East
  "784": "ARE", "634": "QAT", "682": "SAU", "376": "ISR", "792": "TUR", "048": "BHR",
  // Africa
  "710": "ZAF", "818": "EGY", "504": "MAR", "404": "KEN", "566": "NGA",
  "288": "GHA", "480": "MUS",
};


/**
 * Fetch world map data and return SVG path objects with iso3 metadata.
 */
async function loadWorldPaths() {
  const [topojsonLib, d3geo] = await Promise.all([
    import("https://cdn.jsdelivr.net/npm/topojson-client@3/+esm"),
    import("https://cdn.jsdelivr.net/npm/d3-geo@3/+esm"),
  ]);

  const res = await fetch(WORLD_ATLAS_URL);
  if (!res.ok) throw new Error(`Failed to load world atlas: ${res.status}`);
  const topology = await res.json();

  const features = topojsonLib.feature(topology, topology.objects.countries).features;

  const projection = d3geo.geoNaturalEarth1()
    .fitSize([1000, 500], { type: "FeatureCollection", features });
  const pathGen = d3geo.geoPath(projection);

  return features.map(f => {
    const idStr = String(f.id).padStart(3, "0");
    const iso3 = M49_TO_ISO3[idStr] || null;
    return {
      iso3,
      pathD: pathGen(f),
      name: f.properties?.name || "",
    };
  }).filter(c => c.pathD);
}

window.loadWorldPaths = loadWorldPaths;
