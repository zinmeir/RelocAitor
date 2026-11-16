"""
train_prompt_model.py — Train and evaluate the prompt classifier.

    python -m ml.train_prompt_model      # writes ml/prompt_model.json and ml/prompt_eval.json

Steps:
1. Build the vocabulary from the training prompts (features seen in ≥ MIN_DF prompts).
2. TF-IDF vectors (same code as inference, so training and serving can't drift).
3. Choose the regularisation strength C by 5-fold cross-validation on the training set.
4. Fit 9 binary logistic regressions (factors) + 1 multinomial (visa route).
5. Tune the gap-filling confidence thresholds on out-of-fold training
   predictions (never on TEST): the lowest threshold whose combined
   rules + model F1 / accuracy is best. A head that doesn't beat the rules alone
   by MIN_GAIN out-of-fold is switched off (threshold null) — decided on TRAIN only.
6. Evaluate on the separately written TEST prompts: rules only, model only, and
   rules + model (what the app does: the model only fills gaps the rules leave).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from relocaitor.ranking.factors import FACTOR_KEYS                  # noqa: E402
from ml import prompt_model as pm                # noqa: E402
from ml.data.prompts import TEST, TRAIN          # noqa: E402

HERE = Path(__file__).resolve().parent
VISA_CLASSES = ["none", "skilled", "nomad", "study", "investor", "startup", "family", "passive"]
MIN_DF = 2
C_GRID = [1.0, 3.0, 10.0, 30.0]
SEED = 0
MIN_GAIN = 0.01   # a head is switched on only if it beats the rules by ≥ 1 point out-of-fold
THRESHOLD_GRID = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]


def build_vocab(texts):
    df = {}
    for t in texts:
        for f in pm.featurize(t):
            df[f] = df.get(f, 0) + 1
    vocab = sorted(f for f, c in df.items() if c >= MIN_DF)
    n = len(texts)
    idf = [math.log((1 + n) / (1 + df[f])) + 1.0 for f in vocab]
    return vocab, idf


def matrix(texts, vocab, idf):
    from scipy.sparse import lil_matrix
    index = {f: i for i, f in enumerate(vocab)}
    X = lil_matrix((len(texts), len(vocab)))
    for r, t in enumerate(texts):
        for i, v in pm.vectorize(pm.featurize(t), index, idf).items():
            X[r, i] = v
    return X.tocsr()


def labels(data):
    Y = np.array([[1 if k in fs else 0 for k in FACTOR_KEYS] for _, fs, _ in data])
    v = np.array([VISA_CLASSES.index(c) for _, _, c in data])
    return Y, v


def _fit_factor(X, y, C):
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(X, y)


def _fit_visa(X, y, C):
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(C=C, max_iter=4000, class_weight="balanced").fit(X, y)


def choose_c(texts, Y, v):
    """5-fold CV on the training set: pick C maximising factor micro-F1 + visa accuracy."""
    from sklearn.metrics import f1_score
    from sklearn.model_selection import KFold
    folds = list(KFold(5, shuffle=True, random_state=SEED).split(texts))
    scores = {}
    for C in C_GRID:
        f1s, accs = [], []
        for tr, te in folds:
            vocab, idf = build_vocab([texts[i] for i in tr])
            Xtr, Xte = matrix([texts[i] for i in tr], vocab, idf), matrix([texts[i] for i in te], vocab, idf)
            pred = np.zeros((len(te), len(FACTOR_KEYS)), dtype=int)
            for k in range(len(FACTOR_KEYS)):
                if Y[tr, k].sum() == 0:
                    continue
                pred[:, k] = _fit_factor(Xtr, Y[tr, k], C).predict(Xte)
            f1s.append(f1_score(Y[te], pred, average="micro", zero_division=0))
            accs.append(float((_fit_visa(Xtr, v[tr], C).predict(Xte) == v[te]).mean()))
        scores[C] = round(float(np.mean(f1s) + np.mean(accs)), 4)
    return max(scores, key=scores.get), scores


def _rules_sets(text, meta):
    """What the rules alone say: factors wanted, factors mentioned at all, visa route."""
    from relocaitor.nlp import search
    r = search.interpret_rules(text, meta, use_model=False, use_semantic=False)
    mentioned = {c["key"] for c in r["chips"] if c.get("kind") == "factor"}
    wanted = {c["key"] for c in r["chips"] if c.get("kind") == "factor"
              and "not important" not in c["label"] and "opposite" not in c["label"]}
    return wanted, mentioned, r["profile"].get("visa_type")


def choose_thresholds(texts, Y, v, C, meta):
    """Out-of-fold model probabilities on TRAIN, merged with the rules exactly as the app does."""
    from sklearn.metrics import f1_score
    from sklearn.model_selection import KFold
    n = len(texts)
    P = np.zeros((n, len(FACTOR_KEYS)))
    V = np.zeros((n, len(VISA_CLASSES)))
    for tr, te in KFold(5, shuffle=True, random_state=SEED).split(texts):
        vocab, idf = build_vocab([texts[i] for i in tr])
        Xtr, Xte = matrix([texts[i] for i in tr], vocab, idf), matrix([texts[i] for i in te], vocab, idf)
        for k in range(len(FACTOR_KEYS)):
            if Y[tr, k].sum() > 0:
                P[te, k] = _fit_factor(Xtr, Y[tr, k], C).predict_proba(Xte)[:, 1]
        vm = _fit_visa(Xtr, v[tr], C)
        V[np.ix_(te, vm.classes_)] = vm.predict_proba(Xte)
    rules = [_rules_sets(t, meta) for t in texts]

    def factor_f1(t):
        pred = np.array([[1 if (k in w or (k not in m and P[i, j] >= t)) else 0
                          for j, k in enumerate(FACTOR_KEYS)] for i, (w, m, _) in enumerate(rules)])
        return f1_score(Y, pred, average="micro", zero_division=0)

    def visa_acc(t):
        hits = 0
        for i, (_, _, rv) in enumerate(rules):
            guess = rv
            if not rv:
                c = int(np.argmax(V[i]))
                guess = VISA_CLASSES[c] if c != 0 and V[i, c] >= t else None
            hits += (guess or "none") == VISA_CLASSES[v[i]]
        return hits / n

    fs = {t: round(float(factor_f1(t)), 4) for t in THRESHOLD_GRID}
    vs = {t: round(float(visa_acc(t)), 4) for t in THRESHOLD_GRID}
    rules_f1 = round(float(f1_score(Y, np.array([[1 if k in w else 0 for k in FACTOR_KEYS] for w, _, _ in rules]),
                                    average="micro", zero_division=0)), 4)
    rules_acc = round(float(visa_acc(2.0)), 4)       # threshold > 1: the model never fills in
    best_f = max(THRESHOLD_GRID, key=lambda t: (fs[t], -t))
    best_v = max(THRESHOLD_GRID, key=lambda t: (vs[t], -t))
    return {"factor": best_f if fs[best_f] - rules_f1 >= MIN_GAIN else None,
            "visa": best_v if vs[best_v] - rules_acc >= MIN_GAIN else None,
            "oof_factor_f1": fs, "oof_rules_only_factor_f1": rules_f1,
            "oof_visa_accuracy": vs, "oof_rules_only_visa_accuracy": rules_acc}


def export(vocab, idf, factor_models, visa_model, C):
    def sparse(coefs):
        return {str(i): round(float(c), 4) for i, c in enumerate(coefs) if abs(c) >= 5e-3}
    used = set()
    factors = {}
    for k, m in factor_models.items():
        factors[k] = {"w": sparse(m.coef_[0]), "b": round(float(m.intercept_[0]), 5)}
        used |= set(factors[k]["w"])
    visa = {}
    for ci, cls in enumerate(visa_model.classes_):
        name = VISA_CLASSES[cls]
        visa[name] = {"w": sparse(visa_model.coef_[ci]), "b": round(float(visa_model.intercept_[ci]), 5)}
        used |= set(visa[name]["w"])
    # Drop features no head uses, re-indexing everything.
    keep = sorted(int(i) for i in used)
    remap = {old: new for new, old in enumerate(keep)}

    def re_index(head):
        return {"w": {str(remap[int(i)]): c for i, c in head["w"].items()}, "b": head["b"]}
    return {
        "about": "TF-IDF (stems, stem bigrams, char 3-4-grams) + logistic regression; see ml/train_prompt_model.py",
        "C": C,
        "vocab": [vocab[i] for i in keep],
        "idf": [round(idf[i], 6) for i in keep],
        "factors": {k: re_index(h) for k, h in factors.items()},
        "visa": {c: re_index(h) for c, h in visa.items()},
    }


# ---------------------------------------------------------------------------
# Evaluation on the held-out TEST set
# ---------------------------------------------------------------------------

def _rules_prediction(text, meta, use_model):
    from relocaitor.nlp import search
    r = search.interpret_rules(text, meta, use_model=use_model, use_semantic=False)
    explicit = {c["key"] for c in r["chips"] if "key" in c and c.get("kind") in ("factor", "learned") and "not important" not in c["label"]
                and "opposite" not in c["label"]}
    return explicit, r["profile"].get("visa_type") or "none"


def _model_prediction(text):
    p = pm.predict(text)
    fac = {k for k, v in p["factors"].items() if v >= 0.5}
    visa = max(p["visa"], key=p["visa"].get)
    return fac, visa


def _scores(preds, data):
    from sklearn.metrics import f1_score, precision_score, recall_score
    Y = np.array([[1 if k in fs else 0 for k in FACTOR_KEYS] for _, fs, _ in data])
    P = np.array([[1 if k in f else 0 for k in FACTOR_KEYS] for f, _ in preds])
    visa_acc = float(np.mean([p == c for (_, p), (_, _, c) in zip(preds, data)]))
    return {
        "factor_precision": round(float(precision_score(Y, P, average="micro", zero_division=0)), 3),
        "factor_recall": round(float(recall_score(Y, P, average="micro", zero_division=0)), 3),
        "factor_f1": round(float(f1_score(Y, P, average="micro", zero_division=0)), 3),
        "visa_accuracy": round(visa_acc, 3),
    }


def evaluate(meta) -> dict:
    pm.load.cache_clear()
    return {
        "test_prompts": len(TEST), "train_prompts": len(TRAIN),
        "rules_only": _scores([_rules_prediction(t, meta, False) for t, _, _ in TEST], TEST),
        "model_only": _scores([_model_prediction(t) for t, _, _ in TEST], TEST),
        "rules_plus_model": _scores([_rules_prediction(t, meta, True) for t, _, _ in TEST], TEST),
    }


def train(meta) -> dict:
    texts = [t for t, _, _ in TRAIN]
    Y, v = labels(TRAIN)
    C, cv = choose_c(texts, Y, v)
    tuning = choose_thresholds(texts, Y, v, C, meta)
    vocab, idf = build_vocab(texts)
    X = matrix(texts, vocab, idf)
    factor_models = {k: _fit_factor(X, Y[:, i], C) for i, k in enumerate(FACTOR_KEYS)}
    visa_model = _fit_visa(X, v, C)
    model = export(vocab, idf, factor_models, visa_model, C)
    model["cv_scores"] = cv
    model["thresholds"] = {"factor": tuning["factor"], "visa": tuning["visa"]}
    model["threshold_tuning"] = tuning
    return model


if __name__ == "__main__":
    from relocaitor.web.app import meta
    pm.load.cache_clear()
    model = train(meta())
    pm.MODEL_PATH.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {pm.MODEL_PATH.name}: {len(model['vocab'])} features, C={model['C']} (CV: {model['cv_scores']})")
    print("Thresholds:", model["thresholds"], json.dumps(model["threshold_tuning"]))
    report = evaluate(meta())
    report["C"] = model["C"]
    report["thresholds"] = model["thresholds"]
    (HERE / "prompt_eval.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
