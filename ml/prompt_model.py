"""
prompt_model.py — Inference for the trained prompt classifier (no scikit-learn needed).

Two heads trained on labelled prompts (ml/data/prompts.py) by ml/train_prompt_model.py:
  factors: 9 independent logistic regressions ("does this prompt ask for safety?", …)
  visa:    one multinomial logistic regression over skilled/nomad/study/investor/startup/family/passive/none

Features (identical in the JavaScript port): word stems, stem bigrams and
character 3–4-grams of each word (robust to typos), weighted by sublinear TF ×
IDF and L2-normalised.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / "prompt_model.json"
CHAR_NS = (3, 4)


def _stem(w: str) -> str:
    from relocaitor.nlp.search import stem
    return stem(w)


def featurize(text: str) -> dict:
    """Raw feature counts for a prompt."""
    t = (text or "").replace("’", "'").replace("'", "").lower()
    words = re.findall(r"[a-z0-9]+", t)
    stems = [_stem(w) for w in words]
    feats = {}

    def add(f):
        feats[f] = feats.get(f, 0) + 1

    for s in stems:
        add("w:" + s)
    for a, b in zip(stems, stems[1:]):
        add("b:" + a + "_" + b)
    for w in words:
        if len(w) < 3:
            continue
        padded = " " + w + " "
        for n in CHAR_NS:
            for i in range(len(padded) - n + 1):
                add("c:" + padded[i:i + n])
    return feats


def vectorize(feats: dict, index: dict, idf: list) -> dict:
    """Sparse TF-IDF vector {feature index: value}, L2-normalised."""
    vec = {}
    for f in sorted(feats):
        i = index.get(f)
        if i is not None:
            vec[i] = (1.0 + math.log(feats[f])) * idf[i]
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm > 0:
        vec = {i: v / norm for i, v in vec.items()}
    return vec


@lru_cache(maxsize=1)
def load():
    if not MODEL_PATH.exists():
        return None
    m = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    m["index"] = {f: i for i, f in enumerate(m["vocab"])}
    return m


def _linear(vec: dict, weights: dict, bias: float) -> float:
    z = bias
    for i in sorted(vec):
        w = weights.get(str(i))
        if w is not None:
            z += vec[i] * w
    return z


def predict(text: str) -> dict:
    """{"factors": {key: prob}, "visa": {class: prob}, "thresholds": {...}} or {} if no model file."""
    m = load()
    if not m:
        return {}
    vec = vectorize(featurize(text), m["index"], m["idf"])
    factors = {}
    for key, head in m["factors"].items():
        z = _linear(vec, head["w"], head["b"])
        factors[key] = 1.0 / (1.0 + math.exp(-z))
    logits = {c: _linear(vec, head["w"], head["b"]) for c, head in m["visa"].items()}
    mx = max(logits.values())
    exps = {c: math.exp(v - mx) for c, v in logits.items()}
    total = sum(exps.values())
    th = m.get("thresholds", {})
    return {"factors": factors, "visa": {c: e / total for c, e in exps.items()},
            "thresholds": {"factor": th.get("factor"), "visa": th.get("visa")}}   # None = head switched off


def serving_payload():
    """The model as shipped to the browser: only what inference needs, minus switched-off heads."""
    m = load()
    if not m:
        return None
    th = m.get("thresholds", {})
    out = {"vocab": m["vocab"], "idf": m["idf"], "visa": m["visa"], "thresholds": th}
    if th.get("factor") is not None:
        out["factors"] = m["factors"]
    return out
