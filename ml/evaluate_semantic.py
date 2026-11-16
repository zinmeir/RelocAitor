"""
evaluate_semantic.py — Tune and evaluate the sentence-embedding layer.

    python -m ml.evaluate_semantic          # needs the model: python -m ml.build_semantic_index --download

Two jobs, both tuned on development data and scored on held-out test data:

1. Prompt understanding (ml/data/prompts.py): which factors and which visa
   route a prompt asks for. Thresholds are tuned on TRAIN with the rules alone
   (the classifier was trained on TRAIN, so including it there would be
   optimistic). A part is switched on only if it beats the rules by MIN_GAIN
   there. TEST compares: rules, rules + classifier (before), and rules +
   classifier + embeddings (shipped).

2. Visa retrieval (ml/data/visa_queries.py): keyword vs embedding-only vs
   hybrid (keyword hits first, meaning fills the rest). The threshold is tuned on DEV
   (MRR minus a penalty for returning hits on prompts that aren't visa
   searches); TEST is only scored.

Writes ml/semantic_eval.json, whose "config" block is what the app uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import search                                                        # noqa: E402
from factors import FACTOR_KEYS                                      # noqa: E402
from ml import semantic                                              # noqa: E402
from ml.data import visa_queries as VQ                               # noqa: E402
from ml.data.prompts import TEST as P_TEST, TRAIN as P_TRAIN         # noqa: E402

GRID = [round(0.30 + 0.025 * i, 3) for i in range(17)]     # 0.30 … 0.70
MIN_GAIN = 0.01
NULL_PENALTY = 0.5
TOP_K = 5


# ---------------------------------------------------------------------------
# Prompt understanding
# ---------------------------------------------------------------------------

def _predict(text, meta, use_model, use_semantic):
    r = search.interpret_rules(text, meta, use_model=use_model, use_semantic=use_semantic)
    wanted = {c["key"] for c in r["chips"] if "key" in c and c["kind"] in ("factor", "learned", "semantic")
              and "not important" not in c["label"] and "opposite" not in c["label"]}
    return wanted, r["profile"].get("visa_type") or "none"


def _prompt_scores(preds, data) -> dict:
    tp = fp = fn = 0
    for (wanted, _), (_, gold, _) in zip(preds, data):
        gold = set(gold)
        tp += len(wanted & gold)
        fp += len(wanted - gold)
        fn += len(gold - wanted)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    acc = float(np.mean([v == gold for (_, v), (_, _, gold) in zip(preds, data)]))
    return {"factor_precision": round(p, 3), "factor_recall": round(r, 3), "factor_f1": round(f1, 3),
            "visa_accuracy": round(acc, 3)}


def _with_config(**cfg):
    semantic._CONFIG_OVERRIDE = {**semantic.DEFAULT_CONFIG, **cfg}


def tune_prompts(meta) -> dict:
    texts = [t for t, _, _ in P_TRAIN]
    base = _prompt_scores([_predict(t, meta, False, False) for t in texts], P_TRAIN)
    f_scores, v_scores = {}, {}
    for th in GRID:
        _with_config(factor_threshold=th)
        f_scores[th] = _prompt_scores([_predict(t, meta, False, True) for t in texts], P_TRAIN)["factor_f1"]
        _with_config(visa_type_threshold=th)
        v_scores[th] = _prompt_scores([_predict(t, meta, False, True) for t in texts], P_TRAIN)["visa_accuracy"]
    best_f = max(GRID, key=lambda t: (f_scores[t], t))      # ties → stricter threshold
    best_v = max(GRID, key=lambda t: (v_scores[t], t))
    return {
        "rules_only_train": base,
        "factor_f1_by_threshold": f_scores, "visa_accuracy_by_threshold": v_scores,
        "factor_threshold": best_f if f_scores[best_f] - base["factor_f1"] >= MIN_GAIN else None,
        "visa_type_threshold": best_v if v_scores[best_v] - base["visa_accuracy"] >= MIN_GAIN else None,
    }


def evaluate_prompts(meta, cfg) -> dict:
    texts = [t for t, _, _ in P_TEST]
    _with_config(**cfg)
    out = {
        "test_prompts": len(P_TEST),
        "rules_only": _prompt_scores([_predict(t, meta, False, False) for t in texts], P_TEST),
        "rules_plus_classifier": _prompt_scores([_predict(t, meta, True, False) for t in texts], P_TEST),
        "rules_plus_classifier_plus_embeddings": _prompt_scores([_predict(t, meta, True, True) for t in texts], P_TEST),
    }
    return out


# ---------------------------------------------------------------------------
# Visa retrieval
# ---------------------------------------------------------------------------

def _relevant(types, countries) -> set:
    from visas import _load
    out = set()
    for code, entry in _load().items():
        if countries and code not in countries:
            continue
        for v in entry["visas"]:
            if v["type"] in types:
                out.add((code, v["name"]))
    return out


def _scope(q, meta):
    interp = search.interpret_rules(q, meta, use_model=False, use_semantic=False)
    codes = {n["name"]: n["code"] for n in meta["nationalities"]}
    return interp.get("region"), [codes[c] for c in interp.get("countries") or []]


def _keys(hits) -> list:
    code = {n: c for c, n in _country_names().items()}
    return list(dict.fromkeys((code[h["country"]], h["name"]) for h in hits))


def _country_names():
    from data import load_countries
    return dict(load_countries()[["country_code", "country_name"]].itertuples(index=False))


def _semantic_only(q, region, countries, th):
    docs = {(d["code"], d["visa"]["name"]): d for d in search._visa_index()[0]}
    sims = semantic.visa_similarities(search.semantic_query(q))
    ranked = sorted(((s, k) for k, s in sims.items() if s >= th and k in docs
                     and (not region or docs[k]["region"] == region) and (not countries or k[0] in countries)),
                    key=lambda x: (-x[0], x[1]))
    return [k for _, k in ranked][:TOP_K]


def _run(system, q, meta, th):
    region, countries = _scope(q, meta)
    if system == "keyword":
        return _keys(search.keyword_search(q, region, limit=TOP_K, countries=countries))
    if system == "semantic":
        return _semantic_only(q, region, countries, th)
    _with_config(retrieval_threshold=th)
    return _keys(search.visa_search(q, region, limit=TOP_K, countries=countries))


def _retrieval_scores(system, queries, nulls, meta, th) -> dict:
    hit, prec, rr = [], [], []
    for q, types, countries in queries:
        got = _run(system, q, meta, th)
        rel = _relevant(types, countries)
        flags = [k in rel for k in got]
        hit.append(1.0 if any(flags) else 0.0)
        prec.append(sum(flags) / len(got) if got else 0.0)
        rr.append(next((1.0 / (i + 1) for i, f in enumerate(flags) if f), 0.0))
    false_hits = [1.0 if _run(system, q, meta, th) else 0.0 for q in nulls]
    return {"hit_at_5": round(float(np.mean(hit)), 3), "precision_at_5": round(float(np.mean(prec)), 3),
            "mrr": round(float(np.mean(rr)), 3), "false_hit_rate": round(float(np.mean(false_hits)), 3),
            "queries": len(queries), "null_queries": len(nulls)}


def _objective(s):
    return s["mrr"] - NULL_PENALTY * s["false_hit_rate"]


def tune_retrieval(meta) -> dict:
    keyword = _retrieval_scores("keyword", VQ.DEV, VQ.NULL_DEV, meta, None)
    by_th = {th: _retrieval_scores("hybrid", VQ.DEV, VQ.NULL_DEV, meta, th) for th in GRID}
    best = max(GRID, key=lambda t: (_objective(by_th[t]), t))
    return {"keyword_dev": keyword, "hybrid_dev_by_threshold": by_th,
            "retrieval_threshold": best if _objective(by_th[best]) - _objective(keyword) >= MIN_GAIN else None,
            "best_threshold": best}


def evaluate_retrieval(meta, th_used, th_best) -> dict:
    th = th_used if th_used is not None else th_best
    return {"keyword": _retrieval_scores("keyword", VQ.TEST, VQ.NULL_TEST, meta, None),
            "semantic_only": _retrieval_scores("semantic", VQ.TEST, VQ.NULL_TEST, meta, th),
            "hybrid": _retrieval_scores("hybrid", VQ.TEST, VQ.NULL_TEST, meta, th),
            "threshold": th}


def main() -> dict:
    from app import meta
    if not semantic.available():
        raise SystemExit("Embedding model or index missing. Run: python -m ml.build_semantic_index --download")
    m = meta()
    try:
        pt = tune_prompts(m)
        rt = tune_retrieval(m)
        cfg = {"factor_threshold": pt["factor_threshold"], "visa_type_threshold": pt["visa_type_threshold"],
               "retrieval_threshold": rt["retrieval_threshold"], "max_factors_per_clause": 2}
        report = {
            "model": semantic.MODEL_NAME,
            "config": cfg,
            "prompt_understanding": {"tuning": pt, "test": evaluate_prompts(m, cfg)},
            "visa_retrieval": {"tuning": rt, "test": evaluate_retrieval(m, rt["retrieval_threshold"], rt["best_threshold"])},
        }
    finally:
        semantic._CONFIG_OVERRIDE = None
    semantic.EVAL_PATH.write_text(json.dumps(report, indent=1), encoding="utf-8")
    semantic.reset_caches()
    return report


def markdown(report: dict) -> str:
    """The README tables for this report."""
    p = report["prompt_understanding"]["test"]
    rows = [("Rules only", p["rules_only"]), ("Rules + classifier", p["rules_plus_classifier"]),
            ("**Rules + classifier + embeddings**", p["rules_plus_classifier_plus_embeddings"])]
    out = ["| Prompt understanding (test) | Factor precision | Factor recall | Factor F1 | Visa-route accuracy |",
           "|---|---|---|---|---|"]
    out += [f"| {n} | {r['factor_precision']} | {r['factor_recall']} | {r['factor_f1']} | {r['visa_accuracy']} |"
            for n, r in rows]
    t = report["visa_retrieval"]["test"]
    out += ["", "| Visa retrieval (test) | Hit@5 | Precision@5 | MRR | False hits on non-visa prompts |",
            "|---|---|---|---|---|"]
    out += [f"| {n} | {t[k]['hit_at_5']} | {t[k]['precision_at_5']} | {t[k]['mrr']} | {t[k]['false_hit_rate']} |"
            for n, k in (("Keyword (BM25-style)", "keyword"), ("Embeddings only", "semantic_only"),
                         ("**Hybrid (shipped)**", "hybrid"))]
    c = report["config"]
    out += ["", f"Shipped thresholds: factor {c['factor_threshold']}, visa route {c['visa_type_threshold']}, "
                f"retrieval {c['retrieval_threshold']} (null = switched off: no gain on dev data)."]
    return "\n".join(out)


if __name__ == "__main__":
    print(markdown(main()))
