"""Sentence-embedding layer: tokenizer, ONNX runtime path, index, and how search uses it."""

import json

import numpy as np
import pytest

import search
from app import app, meta
from ml import semantic
from tests import semantic_stub as stub

M = meta()


# ---------------------------------------------------------------------------
# Tokenizer (BERT uncased WordPiece)
# ---------------------------------------------------------------------------

VOCAB = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "un", "##aff", "##able", "hello", ",", "world", "!", "cafe",
         "fast", "wi", "##fi", "'", "s", "日", "本"]


def test_wordpiece_matches_bert_rules():
    tok = semantic.WordPiece(VOCAB)
    ids = tok.encode("Unaffable, HÉLLO world! café")
    words = [VOCAB[i] for i in ids]
    assert words == ["[CLS]", "un", "##aff", "##able", ",", "hello", "world", "!", "cafe", "[SEP]"]


def test_wordpiece_unknowns_punctuation_and_cjk():
    tok = semantic.WordPiece(VOCAB)
    words = [VOCAB[i] for i in tok.encode("fast wifi, it's 日本 zzz")]
    assert words == ["[CLS]", "fast", "wi", "##fi", ",", "[UNK]", "'", "s", "日", "本", "[UNK]", "[SEP]"]


def test_wordpiece_truncates_like_sentence_transformers():
    tok = semantic.WordPiece(VOCAB)
    ids = tok.encode("hello " * 500, max_tokens=10)
    assert len(ids) == 10 and ids[0] == tok.cls and ids[-1] == tok.sep


# ---------------------------------------------------------------------------
# ONNX runtime path, with a real (tiny) ONNX model
# ---------------------------------------------------------------------------

@pytest.fixture()
def tiny_model(tmp_path):
    rng = np.random.default_rng(0)
    table = rng.normal(size=(len(VOCAB), 6)).astype(np.float32)
    (tmp_path / "model.onnx").write_bytes(stub.gather_model(table))
    (tmp_path / "vocab.txt").write_text("\n".join(VOCAB), encoding="utf-8")
    return tmp_path, table


def test_onnx_encoder_mean_pools_and_normalises(tiny_model):
    pytest.importorskip("onnxruntime")
    path, table = tiny_model
    enc = semantic.OnnxEncoder(path / "model.onnx", path / "vocab.txt")
    v = enc.embed(["hello world"])[0]
    ids = [VOCAB.index(t) for t in ("[CLS]", "hello", "world", "[SEP]")]
    expected = table[ids].mean(axis=0)
    assert np.allclose(v, expected / np.linalg.norm(expected), atol=1e-6)


def test_padding_does_not_change_embeddings(tiny_model):
    pytest.importorskip("onnxruntime")
    path, _ = tiny_model
    enc = semantic.OnnxEncoder(path / "model.onnx", path / "vocab.txt")
    alone = enc.embed(["hello"])[0]
    batched = enc.embed(["hello", "unaffable hello world fast wifi"])[0]   # padded to the longer one
    assert np.allclose(alone, batched, atol=1e-6)


def test_int8_index_round_trip():
    rng = np.random.default_rng(1)
    v = rng.normal(size=(20, 384)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    back = semantic.dequantize(semantic.quantize(v))
    assert np.min(np.sum(v * back, axis=1)) > 0.999          # cosine similarity after int8


def test_layer_is_off_without_a_model():
    assert not semantic.available()                 # tests run with RELOC_SEMANTIC=0
    r = search.interpret_rules("my kids can grow up without worrying", M)
    assert not any(c["kind"] == "semantic" for c in r["chips"])
    assert all(h["match"] == "keyword" for h in search.visa_search("blue card germany"))


# ---------------------------------------------------------------------------
# How search uses embeddings (deterministic concept encoder)
# ---------------------------------------------------------------------------

def test_embeddings_fill_gaps_the_rules_leave(monkeypatch):
    stub.install(monkeypatch)
    text = "I want to walk home at night without worrying"
    assert not search.interpret_rules(text, M, use_semantic=False)["weights"]
    r = search.interpret_rules(text, M)
    chip = next(c for c in r["chips"] if c["kind"] == "semantic")
    assert chip["key"] == "safety" and "≈" in chip["detail"]
    assert r["weights"]["safety"] >= 0.8
    assert "worrying" not in r["unmatched"]           # the clause was understood


def test_rules_keep_priority(monkeypatch):
    stub.install(monkeypatch)
    r = search.interpret_rules("I don't care about safety, I want sunshine", M)
    assert r["weights"]["safety"] <= 0.1              # the rule's "don't care" wins
    assert not any(c["kind"] == "semantic" and c.get("key") == "safety" for c in r["chips"])


def test_negated_clauses_are_not_embedded(monkeypatch):
    stub.install(monkeypatch)
    r = search.interpret_rules("I hate working remotely from a laptop", M)
    assert r["profile"].get("visa_type") != "nomad"


def test_semantic_visa_route_and_no_hard_filters(monkeypatch):
    stub.install(monkeypatch)
    r = search.interpret_rules("I'll spend my golden years by the sea", M, use_model=False)
    assert r["profile"].get("visa_type") == "passive"
    r = search.interpret_rules("put down roots and become a citizen", M)
    assert any(c["kind"] == "semantic" and c.get("key") == "pr" for c in r["chips"])
    assert not r["profile"].get("require_pr")          # a similarity guess never sets a hard filter


def test_hybrid_search_finds_visas_without_shared_keywords(monkeypatch):
    stub.install(monkeypatch)
    q = "I can work from my laptop for clients anywhere"
    assert search.keyword_search(q) == []
    hits = search.visa_search(q)
    assert hits and all(h["type"] == "nomad" for h in hits[:3])
    assert all(h["match"] == "meaning" and h["similarity"] >= 0.6 for h in hits)


def test_exact_keyword_matches_stay_on_top(monkeypatch):
    stub.install(monkeypatch)
    keyword = search.keyword_search("blue card germany")
    hits = search.visa_search("blue card germany")
    assert [h["name"] for h in hits[:len(keyword)]] == [h["name"] for h in keyword]
    assert hits[0]["name"] == "EU Blue Card" and hits[0]["match"] in ("keyword", "both")


def test_hybrid_search_respects_region_and_returns_nothing_for_chit_chat(monkeypatch):
    stub.install(monkeypatch)
    hits = search.visa_search("work remotely from my laptop", region="Asia")
    regions = {c["country_name"]: c["region"] for c in app.test_client().post("/api/score", json={}).get_json()["all"]}
    assert hits and all(regions[h["country"]] == "Asia" for h in hits)
    assert search.visa_search("good morning") == []


def test_search_api_reports_match_type(monkeypatch):
    stub.install(monkeypatch)
    d = app.test_client().post("/api/search", json={"prompt": "retiring on my pension somewhere warm"}).get_json()
    assert d["visa_hits"] and {h["match"] for h in d["visa_hits"]} <= {"keyword", "meaning", "both"}


def test_evaluation_pipeline_runs_end_to_end(monkeypatch, tmp_path):
    """The real evaluation needs the model; here it runs on the stub to prove the pipeline works."""
    from ml import evaluate_semantic as ev
    stub.install(monkeypatch)
    monkeypatch.setattr(ev, "GRID", [0.45, 0.6])
    monkeypatch.setattr(semantic, "EVAL_PATH", tmp_path / "semantic_eval.json")
    monkeypatch.setattr(semantic, "available", lambda: True)
    report = ev.main()
    t = report["visa_retrieval"]["test"]
    for system in ("keyword", "semantic_only", "hybrid"):
        assert 0 <= t[system]["mrr"] <= 1 and 0 <= t[system]["false_hit_rate"] <= 1
    assert set(report["config"]) >= {"factor_threshold", "visa_type_threshold", "retrieval_threshold"}
    assert json.loads((tmp_path / "semantic_eval.json").read_text())["config"] == report["config"]


def test_index_check_detects_a_stale_corpus(monkeypatch, tmp_path):
    from ml import build_semantic_index as b
    idx = tmp_path / "semantic_index.json"
    idx.write_text(json.dumps({"corpus_hash": b.corpus_hash(b.corpus())}))
    monkeypatch.setattr(semantic, "INDEX_PATH", idx)
    assert b.main(["--check"]) == 0
    idx.write_text(json.dumps({"corpus_hash": "something-else"}))
    assert b.main(["--check"]) == 1


# ---------------------------------------------------------------------------
# The real model (only when downloaded: python -m ml.build_semantic_index --download)
# ---------------------------------------------------------------------------

REAL = semantic.model_files()[0].exists() and semantic.INDEX_PATH.exists()


@pytest.mark.skipif(not REAL, reason="embedding model not downloaded")
def test_real_model_understands_paraphrases(monkeypatch):
    model, vocab = semantic.model_files()
    monkeypatch.setattr(semantic, "_ENCODER_OVERRIDE", semantic.OnnxEncoder(model, vocab))
    best = semantic.concept_scores(["my children should be able to play outside without danger"])[0]
    factors = {k: v[0] for (kind, k), v in best.items() if kind == "factor"}
    assert max(factors, key=factors.get) == "safety"
    v = semantic.embed(["I work for clients online from my laptop", "digital nomad visa", "golden visa by investment"])
    assert v[0] @ v[1] > v[0] @ v[2]


@pytest.mark.skipif(not semantic.EVAL_PATH.exists(), reason="semantic evaluation not run yet")
def test_shipped_config_matches_the_evaluation():
    report = json.loads(semantic.EVAL_PATH.read_text())
    t = report["visa_retrieval"]["test"]
    if report["config"]["retrieval_threshold"] is not None:
        assert t["hybrid"]["mrr"] >= t["keyword"]["mrr"]
    p = report["prompt_understanding"]["test"]
    assert p["rules_plus_classifier_plus_embeddings"]["factor_f1"] >= p["rules_only"]["factor_f1"] - 0.05
