/* =============================================================
   semantic_port.js — Sentence embeddings in the browser (static demo).

   Same model as the Flask app (all-MiniLM-L6-v2), run by transformers.js
   from a CDN. The corpus vectors (concept prototypes + every visa) were
   computed by Python and ship inside RELOC_DATA.semantic_index; only the
   user's prompt is embedded here. If the library or model can't load
   (offline, blocked CDN), search quietly falls back to keywords + rules
   and says so.
   ============================================================= */
(function (root) {
  "use strict";

  const D = root.RELOC_DATA || {};
  const IDX = D.semantic_index, CFG = D.semantic_config;
  const LIB = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3";
  const MODEL = "Xenova/all-MiniLM-L6-v2";
  const TIMEOUT_MS = 25000;

  let vectors = null, extractor = null, failed = null;

  function decode() {
    if (vectors) return vectors;
    const bin = atob(IDX.vectors.int8);
    const dim = IDX.vectors.dim, n = IDX.items.length;
    vectors = [];
    for (let i = 0; i < n; i++) {
      const v = new Float32Array(dim);
      let norm = 0;
      for (let j = 0; j < dim; j++) {
        let b = bin.charCodeAt(i * dim + j);
        if (b > 127) b -= 256;                       // int8
        v[j] = b * IDX.vectors.scales[i];
        norm += v[j] * v[j];
      }
      norm = Math.sqrt(norm) || 1;
      for (let j = 0; j < dim; j++) v[j] /= norm;
      vectors.push(v);
    }
    return vectors;
  }

  const enabled = () => !!(IDX && CFG && failed === null &&
    (CFG.factor_threshold != null || CFG.visa_type_threshold != null || CFG.retrieval_threshold != null));

  function withTimeout(p, ms) {
    return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timed out")), ms))]);
  }

  async function getExtractor() {
    if (!extractor) {
      extractor = withTimeout((async () => {
        const lib = await import(LIB);
        lib.env.allowLocalModels = false;
        return lib.pipeline("feature-extraction", MODEL);
      })(), TIMEOUT_MS).catch(err => { failed = err; extractor = null; throw err; });
    }
    return extractor;
  }

  async function embed(texts) {
    const ex = await getExtractor();
    const out = await withTimeout(ex(texts, { pooling: "mean", normalize: true }), TIMEOUT_MS);
    return out.tolist();
  }

  const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };

  // Map(clause → {"factor|safety": [similarity, prototype], …}) like ml.semantic.concept_scores
  function conceptScores(clauses, vecs) {
    const V = decode();
    const out = new Map();
    clauses.forEach((c, r) => {
      const best = {};
      IDX.items.forEach((it, j) => {
        if (it.kind !== "factor" && it.kind !== "visa_type") return;
        const s = dot(vecs[r], V[j]);
        const key = `${it.kind}|${it.key}`;
        if (!(key in best) || s > best[key][0]) best[key] = [s, it.text];
      });
      out.set(c, best);
    });
    return out;
  }

  function visaSims(vec) {
    const V = decode();
    const out = new Map();
    IDX.items.forEach((it, j) => { if (it.kind === "visa") out.set(`${it.country}|${it.name}`, dot(vec, V[j])); });
    return out;
  }

  root.RelocSemantic = { enabled, embed, conceptScores, visaSims, config: () => CFG, error: () => failed };
})(typeof globalThis !== "undefined" ? globalThis : this);
