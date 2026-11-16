"""Trained prompt classifier: inference, integration with the rules, and held-out quality."""

import json
from pathlib import Path

import pytest

import search
from app import meta
from ml import prompt_model as pm

ROOT = Path(__file__).resolve().parent.parent
EVAL = json.loads((ROOT / "ml/prompt_eval.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def M():
    return meta()


def test_model_file_and_thresholds():
    m = pm.load()
    assert m is not None, "run: python -m ml.train_prompt_model"
    assert len(m["vocab"]) == len(m["idf"])
    assert set(m["visa"]) == {"none", "skilled", "nomad", "study", "investor", "startup", "family", "passive"}
    th = m["thresholds"]
    for head in ("factor", "visa"):
        assert th[head] is None or 0.5 <= th[head] < 1


def test_features_are_robust_to_typos():
    a, b = pm.featurize("digital nomad visa"), pm.featurize("digitl nomd visa")
    shared = set(a) & set(b)
    assert any(f.startswith("c:") for f in shared)


def test_prediction_is_deterministic_and_normalised():
    p1, p2 = pm.predict("I work remotely for clients abroad"), pm.predict("I work remotely for clients abroad")
    assert p1 == p2
    assert abs(sum(p1["visa"].values()) - 1) < 1e-9
    assert all(0 <= v <= 1 for v in p1["factors"].values())


def test_model_fills_a_visa_gap_the_rules_miss(M):
    text = "I code for American clients from my laptop"
    assert search.interpret_rules(text, M, use_model=False)["profile"].get("visa_type") is None
    r = search.interpret_rules(text, M)
    assert r["profile"]["visa_type"] == "nomad"
    assert any(c["kind"] == "learned" for c in r["chips"])


def test_rules_win_over_the_model(M):
    # The rules found an explicit visa intent: the model must not override it.
    r = search.interpret_rules("I want a golden visa, I code from my laptop", M)
    assert r["profile"]["visa_type"] == "investor"
    assert not any(c["kind"] == "learned" and "visas" in c.get("detail", "") for c in r["chips"])


def test_negated_route_is_never_learned(M):
    for text in ["I don't want to study, I just want somewhere cheap",
                 "not as a student, somewhere safe and sunny"]:
        assert search.interpret_rules(text, M)["profile"].get("visa_type") != "study"


def test_model_never_sets_hard_filters(M):
    for text in ["somewhere I could stay for good", "I code for American clients from my laptop"]:
        r = search.interpret_rules(text, M)
        if any(c["kind"] == "learned" and c.get("key") == "pr" for c in r["chips"]):
            assert not r["profile"].get("require_pr")


def test_held_out_evaluation_is_an_improvement():
    rules, combo = EVAL["rules_only"], EVAL["rules_plus_model"]
    assert EVAL["test_prompts"] >= 50
    assert combo["visa_accuracy"] >= rules["visa_accuracy"]
    assert combo["factor_f1"] >= rules["factor_f1"] - 1e-9
    assert combo["factor_recall"] >= rules["factor_recall"] - 1e-9


def test_eval_file_matches_current_model(M):
    """prompt_eval.json must describe the model that is actually shipped."""
    from ml.train_prompt_model import evaluate
    fresh = evaluate(M)
    for k in ("rules_only", "rules_plus_model", "model_only"):
        assert fresh[k] == EVAL[k]


def test_train_and_test_prompts_do_not_overlap():
    from ml.data.prompts import TEST, TRAIN
    norm = lambda t: " ".join(t.lower().split())
    assert not {norm(t) for t, _, _ in TRAIN} & {norm(t) for t, _, _ in TEST}
