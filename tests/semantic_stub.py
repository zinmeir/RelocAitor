"""Test doubles for the embedding layer: a tiny ONNX model and a deterministic concept encoder."""

from __future__ import annotations

import json
import re

import numpy as np


# ---------------------------------------------------------------------------
# A real ONNX file, written by hand in protobuf wire format (no `onnx` package needed):
#   last_hidden_state = Gather(embedding_table, input_ids)     shape: batch × tokens × dim
# Same input/output names as the sentence-transformers export, so OnnxEncoder runs unchanged.
# ---------------------------------------------------------------------------

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _key(field, wire):
    return _varint(field << 3 | wire)


def _int(field, n):
    return _key(field, 0) + _varint(n)


def _bytes(field, payload: bytes):
    return _key(field, 2) + _varint(len(payload)) + payload


def _str(field, s: str):
    return _bytes(field, s.encode())


def _value_info(name, elem_type, dims):
    shape = b"".join(_bytes(1, _int(1, d) if isinstance(d, int) else _str(2, d)) for d in dims)
    tensor_type = _int(1, elem_type) + _bytes(2, shape)
    return _str(1, name) + _bytes(2, _bytes(1, tensor_type))


def gather_model(table: np.ndarray) -> bytes:
    V, D = table.shape
    tensor = (_int(1, V) + _int(1, D) + _int(2, 1) + _str(8, "embedding_table")
              + _bytes(9, np.asarray(table, dtype="<f4").tobytes()))
    node = _str(1, "embedding_table") + _str(1, "input_ids") + _str(2, "last_hidden_state") \
        + _str(3, "gather") + _str(4, "Gather")
    graph = (_bytes(1, node) + _str(2, "stub") + _bytes(5, tensor)
             + _bytes(11, _value_info("input_ids", 7, ["batch", "tokens"]))
             + _bytes(11, _value_info("attention_mask", 7, ["batch", "tokens"]))
             + _bytes(11, _value_info("token_type_ids", 7, ["batch", "tokens"]))
             + _bytes(12, _value_info("last_hidden_state", 1, ["batch", "tokens", D])))
    opset = _str(1, "") + _int(2, 13)
    return _int(1, 8) + _str(2, "relocaitor-tests") + _bytes(7, graph) + _bytes(8, opset)


# ---------------------------------------------------------------------------
# Concept encoder: words → concept dimensions (+ a small hashed part for everything else)
# ---------------------------------------------------------------------------

GROUPS = {
    "salary": "salary salaries pay paid paycheck earn earning income wages money",
    "cost": "cheap affordable inexpensive cost rent groceries afford budget further",
    "pr": "permanent permanently residency citizen citizenship settle stay roots",
    "job": "jobs job hiring employment career openings vacancies work",
    "climate": "warm sunny sun sunshine weather climate tropical beaches cold winters",
    "safety": "safe safety crime secure peaceful violence danger worrying kids children night",
    "healthcare": "healthcare hospitals doctors medical health clinics treatment",
    "english": "english language communicate speak",
    "internet": "internet wifi broadband connection fibre connectivity calls online",
    "nomad": "remote remotely laptop anywhere freelancer freelance clients online location nomad",
    "study": "study university degree student students college master phd enrol",
    "passive": "retire retired retirement pension passive savings golden years",
    "investor": "invest investment investing property real estate buy buying golden house",
    "startup": "startup company founder founders entrepreneur business launch",
    "family": "spouse wife husband partner family reunite join",
    "skilled": "skilled employer offer sponsor sponsored nurses engineer doctor professional",
}
DIMS = list(GROUPS)
HASH_DIMS = 16


def concept_vector(text: str) -> np.ndarray:
    v = np.zeros(len(DIMS) + HASH_DIMS, dtype=np.float32)
    for w in re.findall(r"[a-z]+", text.lower()):
        hit = False
        for i, g in enumerate(DIMS):
            if w in GROUPS[g].split():
                v[i] += 1.0
                hit = True
        if not hit:
            v[len(DIMS) + sum(map(ord, w)) % HASH_DIMS] += 0.35
    n = np.linalg.norm(v)
    return v / n if n else v


class ConceptEncoder:
    def embed(self, texts):
        return np.vstack([concept_vector(t) for t in texts]).astype(np.float32)


def install(monkeypatch, factor=0.55, visa_type=0.55, retrieval=0.6):
    """Turn on the semantic layer with the concept encoder and an index built from the real corpus."""
    from ml import semantic
    from ml.build_semantic_index import corpus
    enc = ConceptEncoder()
    items = corpus()
    raw = {"model": "stub", "corpus_hash": "stub", "items": items,
           "vectors": semantic.quantize(enc.embed([i["text"] for i in items]))}
    monkeypatch.setattr(semantic, "_ENCODER_OVERRIDE", enc)
    monkeypatch.setattr(semantic, "_INDEX_OVERRIDE", semantic._prepare_index(raw))
    monkeypatch.setattr(semantic, "_CONFIG_OVERRIDE", {**semantic.DEFAULT_CONFIG, "factor_threshold": factor,
                                                       "visa_type_threshold": visa_type,
                                                       "retrieval_threshold": retrieval})
    return enc


def transformers_js_module() -> str:
    """A fake @huggingface/transformers ES module with the same concept encoder, for browser tests."""
    return """
const GROUPS = %s; const DIMS = Object.keys(GROUPS); const HASH = %d;
function vec(text) {
  const v = new Array(DIMS.length + HASH).fill(0);
  for (const w of (text.toLowerCase().match(/[a-z]+/g) || [])) {
    let hit = false;
    DIMS.forEach((g, i) => { if (GROUPS[g].split(" ").includes(w)) { v[i] += 1; hit = true; } });
    if (!hit) v[DIMS.length + [...w].reduce((s, c) => s + c.charCodeAt(0), 0) %% HASH] += 0.35;
  }
  const n = Math.sqrt(v.reduce((s, x) => s + x * x, 0)) || 1;
  return v.map(x => x / n);
}
export const env = {};
export async function pipeline() {
  return async (texts) => ({ tolist: () => texts.map(vec) });
}
""" % (json.dumps(GROUPS), HASH_DIMS)


def payload(factor=0.55, visa_type=0.55, retrieval=0.6) -> dict:
    """RELOC_DATA semantic block built with the concept encoder (for static-build tests)."""
    from ml import semantic
    from ml.build_semantic_index import corpus
    items = corpus()
    return {"semantic_index": {"items": items, "vectors": semantic.quantize(ConceptEncoder().embed([i["text"] for i in items]))},
            "semantic_config": {**semantic.DEFAULT_CONFIG, "factor_threshold": factor,
                                "visa_type_threshold": visa_type, "retrieval_threshold": retrieval}}
