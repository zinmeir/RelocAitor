import assistant


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"world-map" in r.data


def test_health_and_meta(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}
    meta = client.get("/api/meta").get_json()
    assert meta["country_count"] == 66
    assert "nomad" in meta["presets"]
    assert any(v["key"] == "family" for v in meta["visa_types"])


def test_score_basic(client, weights):
    r = client.post("/api/score", json={"weights": weights, "top_n": 3})
    d = r.get_json()
    assert r.status_code == 200
    assert len(d["top"]) == 3 and len(d["all"]) == 66
    assert d["top"][0]["rank"] == 1
    assert "contributions" in d["top"][0]
    assert d["flip"]["text"]


def test_score_accepts_legacy_flat_weights(client, weights):
    r = client.post("/api/score", json=weights)
    assert r.status_code == 200


def test_score_with_profile_filters(client, weights):
    body = {"weights": weights,
            "profile": {"nationality": "PAK", "monthly_income": 1500, "only_qualifying": True}}
    d = client.post("/api/score", json=body).get_json()
    assert 0 < len(d["all"]) < 66
    assert d["counts"]["hidden_by_filters"] == 66 - len(d["all"])


def test_validation_errors(client):
    assert client.post("/api/score", json={"top_n": "abc"}).status_code == 400
    assert client.post("/api/score", json={"weights": {"salary": "high"}}).status_code == 400
    assert client.post("/api/score", json={"region": "Mars"}).status_code == 400
    assert client.post("/api/score", json={"profile": {"nationality": "XXX"}}).status_code == 400
    assert client.post("/api/score", json={"profile": {"monthly_income": -5}}).status_code == 400
    assert client.post("/api/score", json=[1, 2]).status_code == 400


def test_weights_are_clamped(client):
    r = client.post("/api/score", json={"weights": {"salary": 5}})
    assert r.status_code == 200


def test_insights(client, weights):
    d = client.post("/api/insights", json={"country": "Germany", "weights": weights,
                                           "profile": {"nationality": "FRA"}}).get_json()
    assert d["country"]["rank"] >= 1
    assert d["visas"][0]["type"] == "free"
    assert d["official_url"].startswith("https://")
    assert len(d["similar"]) == 3


def test_insights_for_hidden_country(client, weights):
    d = client.post("/api/insights", json={"country": "Japan", "weights": weights,
                                           "region": "Europe"}).get_json()
    assert d["country"]["hidden_by_filters"] is True
    assert d["what_if"] == []


def test_insights_unknown_country(client):
    assert client.post("/api/insights", json={"country": "Atlantis"}).status_code == 404
    assert client.post("/api/insights", json={}).status_code == 400


def test_compare(client, weights):
    d = client.post("/api/compare", json={"countries": ["Germany", "Canada"], "weights": weights}).get_json()
    assert [i["country_name"] for i in d["items"]] == ["Germany", "Canada"]
    too_many = {"countries": ["Germany", "Canada", "Spain", "Italy"]}
    assert client.post("/api/compare", json=too_many).status_code == 400


def test_ask_rules_mode(client, weights, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = client.post("/api/ask", json={"country": "Canada", "question": "Can I bring my spouse?",
                                      "weights": weights}).get_json()
    assert d["source"] == "rules"
    assert "Spousal" in d["answer"]


def test_ask_falls_back_when_llm_fails(client, weights, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(*a, **k):
        raise assistant.urllib.error.URLError("offline")

    monkeypatch.setattr(assistant, "ask_llm", boom)
    d = client.post("/api/ask", json={"country": "Canada", "question": "How much is rent?"}).get_json()
    assert d["source"] == "rules" and "warning" in d
    assert "$" in d["answer"]


def test_ask_uses_llm_when_available(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(assistant, "ask_llm", lambda q, ctx, timeout=20: f"LLM says hi about {ctx['country']}")
    d = client.post("/api/ask", json={"country": "Japan", "question": "Is it safe?"}).get_json()
    assert d == {"answer": "LLM says hi about Japan", "source": "llm", "country": "Japan"}


def test_visas_endpoint(client):
    d = client.post("/api/visas", json={"country_code": "USA", "type": "study"}).get_json()
    assert all(v["type"] == "study" for v in d["visas"])
    assert client.post("/api/visas", json={"country_code": "ZZZ"}).status_code == 404
