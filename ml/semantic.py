"""
semantic.py — Sentence embeddings for meaning-based search.

Model: sentence-transformers/all-MiniLM-L6-v2 (384-dim, ~90 MB ONNX), run with
onnxruntime and a small built-in WordPiece tokenizer, so the app needs neither
PyTorch nor the transformers library.

    python -m ml.build_semantic_index --download   # fetch the model, embed the corpus
    python -m ml.evaluate_semantic                 # tune thresholds on dev data, score on test data

At runtime this module is optional: if onnxruntime, the model files or the
index are missing, `available()` is False and search falls back to keywords
and rules, exactly as before.

What gets embedded (see ml/build_semantic_index.py):
  - concept prototypes (ml/data/semantic_concepts.py): a few sentences per
    factor and per visa route;
  - every visa pathway in data/visas.json ("EU Blue Card. Skilled worker visa
    in Germany. …").
Vectors are L2-normalised, so cosine similarity is a dot product. The index
stores them as int8 with one scale per vector (4x smaller, < 0.5% error).
"""

from __future__ import annotations

import base64
import json
import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

HERE = Path(__file__).resolve().parent
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DIR = HERE / "models" / "all-MiniLM-L6-v2"
INDEX_PATH = HERE / "semantic_index.json"
EVAL_PATH = HERE / "semantic_eval.json"
MAX_TOKENS = 256          # what sentence-transformers uses for this model


# ---------------------------------------------------------------------------
# WordPiece tokenizer (BERT uncased), equivalent to HuggingFace BertTokenizer
# ---------------------------------------------------------------------------

def _is_punct(ch: str) -> bool:
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp: int) -> bool:
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF
            or 0x2A700 <= cp <= 0x2B73F or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF
            or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


class WordPiece:
    def __init__(self, vocab: list):
        self.vocab = {tok: i for i, tok in enumerate(vocab)}
        self.unk, self.cls, self.sep = (self.vocab[t] for t in ("[UNK]", "[CLS]", "[SEP]"))
        self.pad = self.vocab.get("[PAD]", 0)

    @classmethod
    def from_file(cls, path: Path) -> "WordPiece":
        return cls(path.read_text(encoding="utf-8").splitlines())

    def basic_tokens(self, text: str) -> list:
        out = []
        for ch in text:
            cp = ord(ch)
            if cp == 0 or cp == 0xFFFD or (unicodedata.category(ch).startswith("C") and ch not in "\t\n\r"):
                continue
            out.append(f" {ch} " if _is_cjk(cp) else (" " if ch.isspace() else ch))
        text = "".join(out).lower()
        text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
        tokens = []
        for word in text.split():
            cur = ""
            for ch in word:
                if _is_punct(ch):
                    if cur:
                        tokens.append(cur)
                        cur = ""
                    tokens.append(ch)
                else:
                    cur += ch
            if cur:
                tokens.append(cur)
        return tokens

    def wordpiece(self, word: str) -> list:
        if len(word) > 100:
            return [self.unk]
        ids, start = [], 0
        while start < len(word):
            end, found = len(word), None
            while start < end:
                piece = word[start:end] if start == 0 else "##" + word[start:end]
                if piece in self.vocab:
                    found = self.vocab[piece]
                    break
                end -= 1
            if found is None:
                return [self.unk]
            ids.append(found)
            start = end
        return ids

    def encode(self, text: str, max_tokens: int = MAX_TOKENS) -> list:
        ids = [i for w in self.basic_tokens(text) for i in self.wordpiece(w)]
        return [self.cls] + ids[:max_tokens - 2] + [self.sep]


# ---------------------------------------------------------------------------
# ONNX encoder with mean pooling
# ---------------------------------------------------------------------------

class OnnxEncoder:
    """all-MiniLM-L6-v2 (or any BERT-style ONNX export with a token-embedding output)."""

    def __init__(self, model_path: Path, vocab_path: Path):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tokenizer = WordPiece.from_file(vocab_path)

    def embed(self, texts: list) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        encoded = [self.tokenizer.encode(t) for t in texts]
        width = max(len(e) for e in encoded)
        ids = np.full((len(encoded), width), self.tokenizer.pad, dtype=np.int64)
        mask = np.zeros((len(encoded), width), dtype=np.int64)
        for r, e in enumerate(encoded):
            ids[r, :len(e)] = e
            mask[r, :len(e)] = 1
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        out = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})
        hidden = next(o for o in out if o.ndim == 3)                       # batch × tokens × dim
        m = mask[:, :, None].astype(np.float32)
        pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        return (pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)).astype(np.float32)


def model_files(model_dir: Path = MODEL_DIR) -> tuple:
    return model_dir / "model.onnx", model_dir / "vocab.txt"


_ENCODER_OVERRIDE = None   # tests inject a stub encoder here


@lru_cache(maxsize=1)
def _default_encoder():
    if os.environ.get("RELOC_SEMANTIC", "1") == "0":
        return None
    model, vocab = model_files()
    if not (model.exists() and vocab.exists()):
        return None
    try:
        return OnnxEncoder(model, vocab)
    except Exception:          # onnxruntime missing or a corrupt file: run without semantics
        return None


def encoder():
    return _ENCODER_OVERRIDE if _ENCODER_OVERRIDE is not None else _default_encoder()


# ---------------------------------------------------------------------------
# Index (precomputed corpus vectors) and tuned configuration
# ---------------------------------------------------------------------------

def quantize(vectors: np.ndarray) -> dict:
    scale = np.abs(vectors).max(axis=1) / 127.0
    scale[scale == 0] = 1.0
    q = np.round(vectors / scale[:, None]).astype(np.int8)
    return {"dim": int(vectors.shape[1]), "scales": [float(s) for s in scale],
            "int8": base64.b64encode(q.tobytes()).decode("ascii")}


def dequantize(blob: dict) -> np.ndarray:
    q = np.frombuffer(base64.b64decode(blob["int8"]), dtype=np.int8).reshape(-1, blob["dim"])
    v = q.astype(np.float32) * np.asarray(blob["scales"], dtype=np.float32)[:, None]
    return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-12, None)


_INDEX_OVERRIDE = None


@lru_cache(maxsize=1)
def _default_index():
    if not INDEX_PATH.exists():
        return None
    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return _prepare_index(raw)


def _prepare_index(raw: dict) -> dict:
    vectors = dequantize(raw["vectors"])
    items = raw["items"]
    concepts = [i for i, it in enumerate(items) if it["kind"] in ("factor", "visa_type")]
    visas = [i for i, it in enumerate(items) if it["kind"] == "visa"]
    return {"raw": raw, "items": items, "vectors": vectors, "concepts": concepts, "visas": visas}


def index():
    return _INDEX_OVERRIDE if _INDEX_OVERRIDE is not None else _default_index()


DEFAULT_CONFIG = {"factor_threshold": None, "visa_type_threshold": None, "retrieval_threshold": None,
                  "max_factors_per_clause": 2}


@lru_cache(maxsize=1)
def _default_config() -> dict:
    if not EVAL_PATH.exists():
        return dict(DEFAULT_CONFIG)
    return {**DEFAULT_CONFIG, **json.loads(EVAL_PATH.read_text(encoding="utf-8")).get("config", {})}


_CONFIG_OVERRIDE = None


def config() -> dict:
    return _CONFIG_OVERRIDE if _CONFIG_OVERRIDE is not None else _default_config()


def available() -> bool:
    return encoder() is not None and index() is not None


def reset_caches():
    for f in (_default_encoder, _default_index, _default_config):
        f.cache_clear()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def embed(texts: list) -> Optional[np.ndarray]:
    """Embeddings for texts (cached per encoder, so repeated clauses cost nothing)."""
    enc = encoder()
    if enc is None or not texts:
        return None
    cache = enc.__dict__.setdefault("_cache", {})
    missing = list(dict.fromkeys(t for t in texts if t not in cache))
    if missing:
        if len(cache) > 5000:
            cache.clear()
        for t, v in zip(missing, enc.embed(missing)):
            cache[t] = v
    return np.vstack([cache[t] for t in texts])


def concept_scores(texts: list) -> list:
    """For each text: {concept key: (best similarity, best prototype text)} over factors and visa routes."""
    idx = index()
    vecs = embed(texts)
    if idx is None or vecs is None:
        return [{} for _ in texts]
    C = idx["vectors"][idx["concepts"]]
    sims = vecs @ C.T
    out = []
    for row in sims:
        best = {}
        for j, s in zip(idx["concepts"], row):
            it = idx["items"][j]
            key = (it["kind"], it["key"])
            if key not in best or s > best[key][0]:
                best[key] = (float(s), it["text"])
        out.append(best)
    return out


def visa_similarities(text: str) -> dict:
    """{(country_code, visa name): cosine similarity} for every indexed visa."""
    idx = index()
    v = embed([text])
    if idx is None or v is None:
        return {}
    sims = idx["vectors"][idx["visas"]] @ v[0]
    return {(idx["items"][j]["country"], idx["items"][j]["name"]): float(s) for j, s in zip(idx["visas"], sims)}


def semantic_payload() -> dict:
    """What the static build ships: the corpus vectors + tuned config, or nothing if not built/evaluated."""
    if not INDEX_PATH.exists() or not EVAL_PATH.exists():
        return {}
    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    cfg = _default_config()
    if all(cfg.get(k) is None for k in ("factor_threshold", "visa_type_threshold", "retrieval_threshold")):
        return {}
    return {"semantic_index": {"items": raw["items"], "vectors": raw["vectors"]}, "semantic_config": cfg}


def model_status() -> dict:
    idx = index()
    return {"available": available(), "model": (idx or {}).get("raw", {}).get("model", MODEL_NAME),
            "config": config()}
