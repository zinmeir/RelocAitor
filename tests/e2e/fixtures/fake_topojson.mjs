export function feature(topology, obj) {
  return { type: "FeatureCollection", features: obj.geometries.map(g => ({ type: "Feature", id: g.id, properties: g.properties, geometry: { type: "Polygon", coordinates: g.coordinates } })) };
}
