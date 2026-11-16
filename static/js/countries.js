/* =============================================================
   countries.js
   Loads real world map GeoJSON from a public CDN, projects it to
   our SVG viewBox (1000x500), and exposes country paths by ISO-3.
   Includes the M49 -> ISO-3 mapping for every country in data/world.csv.

   The 110m world-atlas leaves out very small countries (Singapore,
   Hong Kong, Bahrain, Mauritius…). Those get a dot marker instead,
   so every country in the dataset can still be hovered and clicked.
   ============================================================= */

const WORLD_ATLAS_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

// Numeric M49 (used by world-atlas) -> ISO-3 code, for every country in data/world.csv
const M49_TO_ISO3 = {
  // North America
  "028": "ATG", "044": "BHS", "084": "BLZ", "052": "BRB", "124": "CAN", "188": "CRI", "192": "CUB",
  "212": "DMA", "214": "DOM", "308": "GRD", "320": "GTM", "340": "HND", "332": "HTI", "388": "JAM",
  "659": "KNA", "662": "LCA", "484": "MEX", "558": "NIC", "591": "PAN", "222": "SLV", "780": "TTO",
  "840": "USA", "670": "VCT",
  // South America
  "032": "ARG", "068": "BOL", "076": "BRA", "152": "CHL", "170": "COL", "218": "ECU", "328": "GUY",
  "604": "PER", "600": "PRY", "740": "SUR", "858": "URY", "862": "VEN",
  // Europe
  "008": "ALB", "020": "AND", "051": "ARM", "040": "AUT", "031": "AZE", "056": "BEL", "100": "BGR",
  "070": "BIH", "112": "BLR", "756": "CHE", "196": "CYP", "203": "CZE", "276": "DEU", "208": "DNK",
  "724": "ESP", "233": "EST", "246": "FIN", "250": "FRA", "826": "GBR", "268": "GEO", "300": "GRC",
  "191": "HRV", "348": "HUN", "372": "IRL", "352": "ISL", "380": "ITA", "438": "LIE", "440": "LTU",
  "442": "LUX", "428": "LVA", "492": "MCO", "498": "MDA", "807": "MKD", "470": "MLT", "499": "MNE",
  "528": "NLD", "578": "NOR", "616": "POL", "620": "PRT", "642": "ROU", "643": "RUS", "674": "SMR",
  "688": "SRB", "703": "SVK", "705": "SVN", "752": "SWE", "804": "UKR",
  // Oceania
  "036": "AUS", "242": "FJI", "583": "FSM", "296": "KIR", "584": "MHL", "520": "NRU", "554": "NZL",
  "585": "PLW", "598": "PNG", "090": "SLB", "776": "TON", "798": "TUV", "548": "VUT", "882": "WSM",
  // Asia
  "004": "AFG", "050": "BGD", "096": "BRN", "064": "BTN", "156": "CHN", "344": "HKG", "360": "IDN",
  "356": "IND", "392": "JPN", "398": "KAZ", "417": "KGZ", "116": "KHM", "410": "KOR", "418": "LAO",
  "144": "LKA", "462": "MDV", "104": "MMR", "496": "MNG", "458": "MYS", "524": "NPL", "586": "PAK",
  "608": "PHL", "408": "PRK", "702": "SGP", "764": "THA", "762": "TJK", "795": "TKM", "626": "TLS",
  "158": "TWN", "860": "UZB", "704": "VNM",
  // Middle East
  "784": "ARE", "048": "BHR", "364": "IRN", "368": "IRQ", "376": "ISR", "400": "JOR", "414": "KWT",
  "422": "LBN", "512": "OMN", "275": "PSE", "634": "QAT", "682": "SAU", "760": "SYR", "792": "TUR",
  "887": "YEM",
  // Africa
  "024": "AGO", "108": "BDI", "204": "BEN", "854": "BFA", "072": "BWA", "140": "CAF", "384": "CIV",
  "120": "CMR", "180": "COD", "178": "COG", "174": "COM", "132": "CPV", "262": "DJI", "012": "DZA",
  "818": "EGY", "232": "ERI", "231": "ETH", "266": "GAB", "288": "GHA", "324": "GIN", "270": "GMB",
  "624": "GNB", "226": "GNQ", "404": "KEN", "430": "LBR", "434": "LBY", "426": "LSO", "504": "MAR",
  "450": "MDG", "466": "MLI", "508": "MOZ", "478": "MRT", "480": "MUS", "454": "MWI", "516": "NAM",
  "562": "NER", "566": "NGA", "646": "RWA", "729": "SDN", "686": "SEN", "694": "SLE", "706": "SOM",
  "728": "SSD", "678": "STP", "748": "SWZ", "690": "SYC", "148": "TCD", "768": "TGO", "788": "TUN",
  "834": "TZA", "800": "UGA", "710": "ZAF", "894": "ZMB", "716": "ZWE",
};


// [longitude, latitude] for dataset countries that may be missing from the 110m map.
// [longitude, latitude] for ranked countries too small for the map's outlines. The page passes the
// list for the current dataset (data/world.csv); the built-in list covers older pages.
const MARKER_COORDS = window.RELOC_MARKERS || {
  SGP: [103.82, 1.35],  HKG: [114.17, 22.32], BHR: [50.56, 26.07],
  MUS: [57.55, -20.35], QAT: [51.18, 25.35],  CYP: [33.2, 35.0],
};

/**
 * Fetch world map data and return SVG path objects with iso3 metadata.
 * Returns { paths: [{iso3, pathD, name}], markers: [{iso3, cx, cy}] }.
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

  const paths = features.map(f => {
    const idStr = String(f.id).padStart(3, "0");
    const iso3 = M49_TO_ISO3[idStr] || null;
    return {
      iso3,
      pathD: pathGen(f),
      name: f.properties?.name || "",
    };
  }).filter(c => c.pathD);

  const drawn = new Set(paths.map(p => p.iso3).filter(Boolean));
  const markers = Object.entries(MARKER_COORDS)
    .filter(([iso3]) => !drawn.has(iso3))
    .map(([iso3, lonLat]) => {
      const [cx, cy] = projection(lonLat);
      return { iso3, cx, cy };
    });

  return { paths, markers };
}

window.loadWorldPaths = loadWorldPaths;
