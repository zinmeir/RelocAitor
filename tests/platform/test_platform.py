"""Phases 2-8: requirements, pathways, finance, career, agents, dimensions, accounts, security."""

import json

import pytest

from relocaitor import agents
from relocaitor import career
from relocaitor.ranking import dimensions
from relocaitor import finance
from relocaitor import planner
from relocaitor.career import jobs
from relocaitor.visas.eligibility import Profile, evaluate_visa
from relocaitor.visas import catalog as V


def _visa(code, name):
    return next(v for v in V._load()[code]["visas"] if v["name"] == name)


# --- Phase 2: education, experience, language -------------------------------------
def test_language_education_and_experience_rules():
    uk = _visa("GBR", "Skilled Worker Visa")
    assert evaluate_visa(uk, Profile(english="B1", monthly_income=9000))["status"] == "ineligible"
    assert evaluate_visa(uk, Profile(english="B2", monthly_income=9000))["status"] != "ineligible"
    assert "Add your level" in " ".join(evaluate_visa(uk, Profile(monthly_income=9000))["reasons"])
    de = _visa("DEU", "EU Blue Card")
    assert evaluate_visa(de, Profile(education="diploma", monthly_income=9000))["status"] == "ineligible"
    assert evaluate_visa(de, Profile(education="master", monthly_income=9000))["status"] == "eligible"
    ca = _visa("CAN", "Express Entry (FSW)")
    out = evaluate_visa(ca, Profile(english="C1", experience_years=0.5))
    assert out["status"] == "ineligible" and any("can't be compared" in r for r in out["reasons"])   # CLB isn't CEFR


def test_profile_validation_for_new_fields(client):
    for bad in ({"education": "phd"}, {"english": "B3"}, {"experience_years": -1}, {"experience_years": 99}):
        assert client.post("/api/score", json={"profile": bad}).status_code == 400


# --- Phase 3: pathways ----------------------------------------------------------
P = Profile(nationality="IND", monthly_income=5000, education="master", english="C1", german="B1", experience_years=3)


def test_multi_stage_pathways_and_honest_unknowns():
    res = planner.plan(P, countries=["CAN", "GBR", "DEU"])
    by = {p["id"]: p for p in res["pathways"]}
    de = by["DEU-blue-card-settlement"]
    assert de["years_to_pr"] == {"min": 1.75, "max": 1.75, "unknown": []}               # 21 months with B1 German
    a1 = {p["id"]: p for p in planner.plan(Profile(education="master", monthly_income=9000, german="A1"),
                                             countries=["DEU"])["pathways"]}["DEU-blue-card-settlement"]
    assert a1["years_to_pr"]["min"] == 2.25
    none = {p["id"]: p for p in planner.plan(Profile(education="master", monthly_income=9000), countries=["DEU"])["pathways"]}
    assert none["DEU-blue-card-settlement"]["years_to_pr"]["unknown"]                     # no German: no timeline given
    ca = by["CAN-study-pgwp-cec"]
    assert ca["years_to_pr"]["unknown"]                                                   # programme length unknown
    with_study = {p["id"]: p for p in planner.plan(P, countries=["CAN"], study_years=2)["pathways"]}["CAN-study-pgwp-cec"]
    assert with_study["years_to_pr"]["min"] == 3.0 and any("competitive" in x for x in with_study["limits"])
    assert res["comparison"]["text"].startswith(res["pathways"][0]["title"])


def test_unchecked_routes_do_not_outrank_checked_ones():
    res = planner.plan(Profile(nationality="PAK", english="B1", monthly_income=6000), countries=["CAN"])["pathways"]
    startup = next(p for p in res if p["id"] == "direct:CAN-start-up-visa-program")
    fsw = next(p for p in res if p["id"] == "direct:CAN-express-entry-fsw")
    assert len(startup["unchecked"]) == 3 and res.index(fsw) < res.index(startup)


def test_what_if_reruns_the_rules():
    w = planner.what_if(Profile(nationality="PAK", english="B1", monthly_income=6000), {"english": "B2"})
    assert any(x["route"] == "GBR-skilled-worker-visa" and x["after"] == "eligible" for x in w["opened"])
    with pytest.raises(ValueError):
        planner.what_if(P, {"nationality": "USA"})


# --- Phase 4: finance -----------------------------------------------------------
def test_tax_is_oecd_sourced_and_projection_arithmetic_is_exact():
    r = finance.simulate({"country": "DEU", "gross_monthly_usd": 5000, "other_spend_usd": 1000, "rent_usd": 1200,
                          "flights_usd": 800, "visa_fee_usd": 100})
    tax = r["monthly"]["lines"][1]
    assert tax["status"] == "sourced" and tax["pct"] == 38.7 and tax["usd"] == pytest.approx(1935)
    assert r["monthly"]["savings_usd"] == pytest.approx(5000 - 1935 - 1200 - 1000)
    assert r["one_off"]["upfront_usd"] == pytest.approx(2 * 1200 + 100 + 800)
    y1 = r["projections"]["baseline"]["years"][0]["cumulative_savings_usd"]
    assert y1 == pytest.approx(12 * (5000 - 1935) - 12 * 2200 - 3300)
    pess = r["projections"]["pessimistic"]["years"][-1]["cumulative_savings_usd"]
    assert pess < r["projections"]["baseline"]["years"][-1]["cumulative_savings_usd"] < \
        r["projections"]["optimistic"]["years"][-1]["cumulative_savings_usd"]


def test_finance_never_invents_tax_or_costs():
    r = finance.simulate({"country": "ARE", "gross_monthly_usd": 6000})        # not in the OECD table
    assert r["monthly"]["lines"][1]["status"] == "unknown" and "income tax" in r["unknown"]
    assert "other living costs" in r["unknown"]
    r2 = finance.simulate({"country": "PRT"})                                  # typical net salary: no tax applied
    assert r2["monthly"]["lines"][0]["status"] == "editorial" and r2["monthly"]["lines"][1]["usd"] == 0
    with pytest.raises(ValueError):
        finance.simulate({"country": "DEU", "gross_monthly_usd": -5})
    assert len(finance.compare({"countries": ["DEU", "FRA"], "gross_monthly_usd": 3000})["results"]) == 2


def test_price_level_scaling_uses_world_bank_levels():
    pd_, ph = finance.price_level("DEU"), finance.price_level("POL")
    r = finance.simulate({"country": "DEU", "home_country": "POL", "home_spend_usd": 500})
    assert r["monthly"]["lines"][3]["usd"] == pytest.approx(round(500 * pd_ / ph, 2))


# --- Phase 5: career ------------------------------------------------------------
def test_career_uses_official_lists_and_marks_what_is_missing():
    rep = career.career_report(Profile(occupation="healthcare", english="B1", monthly_income=6000), ["CAN", "GBR"])
    can, gbr = rep["countries"]
    assert can["shortage_list"]["field_listed"] is True and can["shortage_list"]["source"].startswith("https://")
    assert gbr["shortage_list"] is None and "salary ranges for your occupation" in gbr["not_available"]
    acts = [s["action"] for s in rep["skills_gap"]["roadmap"]]
    assert "Reach English B2 (CEFR)" in acts and "Reach English C1 (CEFR)" not in acts   # the smaller step is enough


def test_vacancies_are_off_without_keys_and_mapped_with_them(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    assert jobs.search("GBR", "tech")["enabled"] is False
    monkeypatch.setenv("ADZUNA_APP_ID", "x")
    monkeypatch.setenv("ADZUNA_APP_KEY", "y")
    fake = {"results": [{"title": "Nurse", "company": {"display_name": "NHS"}, "location": {"display_name": "Leeds"},
                         "redirect_url": "https://example.org/j/1", "created": "2026-11-10"}]}
    out = jobs.search("GBR", "healthcare", fetch=lambda url: fake)
    assert out["vacancies"][0]["company"] == "NHS" and out["provider"] == "Adzuna"
    assert jobs.search("PAK", "tech", fetch=lambda url: fake)["vacancies"] == []


# --- Phase 6: agents --------------------------------------------------------------
def test_orchestrator_routes_and_answers_from_tools():
    p = Profile(nationality="PAK", occupation="healthcare", english="B1", monthly_income=6000)
    r = agents.run("Which visas can I get?", "GBR", p)
    assert r["agents"] == ["immigration"] and "Skilled Worker" in r["answer"] and r["mode"] == "rules"
    assert all(s["ok"] for s in r["steps"]) and r["warnings"]
    assert agents.run("How expensive is rent?", "GBR", p)["agents"] == ["financial"]
    with pytest.raises(ValueError):
        agents.run("hi", "XXX", p)


def test_agents_respect_tool_permissions_and_profile_access():
    run = agents.Run()
    with pytest.raises(PermissionError):
        agents.call_tool(agents.AGENTS["financial"], "visas", run, country="GBR", profile=Profile())
    seen = {}
    a = agents.Agent("probe", ("x",), {"t": lambda country, profile: seen.setdefault("p", profile)}, profile_access=False)
    agents.call_tool(a, "t", run, country="GBR", profile=Profile(nationality="PAK"))
    assert seen["p"].nationality is None                        # this agent never sees personal data


def test_llm_text_is_used_only_when_its_numbers_come_from_tools():
    p = Profile(nationality="PAK", english="B1", monthly_income=6000)
    good = agents.run("How expensive is rent?", "GBR", p, share_with_llm=True, llm=lambda s, u: "Rent is about $1,500 a month.")
    assert good["mode"] == "llm"
    bad = agents.run("How expensive is rent?", "GBR", p, share_with_llm=True, llm=lambda s, u: "Rent is about $730 a month.")
    assert bad["mode"] == "rules" and any("number not found" in w for w in bad["warnings"])
    no_consent = agents.run("How expensive is rent?", "GBR", p, share_with_llm=False, llm=lambda s, u: "x")
    assert no_consent["mode"] == "rules"


# --- Phase 8: dimensions ----------------------------------------------------------
def test_six_dimensions_stay_separate():
    d = dimensions.dimensions("CAN", Profile(nationality="PAK", occupation="healthcare", partner=True, children=2), {})
    assert set(d["dimensions"]) == {"lifestyle", "immigration", "financial", "career", "settlement", "family"}
    assert "score" not in d and all("basis" in v for v in d["dimensions"].values())
    assert dimensions.dimensions("CAN", Profile(), {})["dimensions"]["family"]["score"] is None


def test_new_endpoints_validate_input(client):
    assert client.post("/api/plan", json={"countries": ["XXX"]}).status_code == 404
    assert client.post("/api/plan", json={"study_years": 20}).status_code == 400
    assert client.post("/api/plan/whatif", json={"changes": {}}).status_code == 400
    assert client.post("/api/finance/simulate", json={"country": "DEU", "gross_monthly_usd": "x"}).status_code == 400
    assert client.post("/api/career", json={"countries": []}).status_code == 400
    assert client.post("/api/assistant", json={"question": "", "country": "GBR"}).status_code == 400
    assert client.post("/api/assistant", json={"question": "Is it safe?", "country": "GBR"}).get_json()["agents"] == ["lifestyle"]
    assert client.post("/api/dimensions", json={"country": "DEU"}).status_code == 200
    assert client.get("/api/career/jobs?country=GBR").get_json()["enabled"] is False


# --- Phase 7: accounts, isolation, encryption, CSRF ------------------------------
@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("RELOC_DB", str(tmp_path / "ws.db"))
    monkeypatch.setenv("RELOC_RATE_LIMIT", "0")
    from relocaitor.web.app import app
    return app


def _signup(app, email):
    c = app.test_client()
    r = c.post("/api/me/register", json={"email": email, "password": "correct horse battery"})
    assert r.status_code == 201
    return c, r.get_json()["csrf"]


def test_workspace_needs_a_session_and_csrf(ws):
    c = ws.test_client()
    assert c.get("/api/me/shortlist").status_code == 401
    c, csrf = _signup(ws, "a@example.org")
    assert c.post("/api/me/shortlist", json={"country": "DEU"}).status_code == 403            # no CSRF header
    assert c.post("/api/me/shortlist", json={"country": "DEU"}, headers={"X-CSRF-Token": csrf}).status_code == 200
    assert ws.test_client().post("/api/me/register", json={"email": "a@example.org", "password": "x" * 12}).status_code == 409
    assert ws.test_client().post("/api/me/login", json={"email": "a@example.org", "password": "wrong password"}).status_code == 401
    assert ws.test_client().post("/api/me/register", json={"email": "b@example.org", "password": "short"}).status_code == 400


def test_users_only_see_their_own_data_and_profiles_are_encrypted(ws):
    from relocaitor.workspace import db
    a, ta = _signup(ws, "a@example.org")
    b, tb = _signup(ws, "b@example.org")
    h = lambda t: {"X-CSRF-Token": t}   # noqa: E731
    a.put("/api/me/profile", json={"profile": {"nationality": "PAK", "monthly_income": 4000}}, headers=h(ta))
    a.post("/api/me/shortlist", json={"country": "CAN"}, headers=h(ta))
    a.post("/api/me/checklist", json={"route": "GBR-skilled-worker-visa"}, headers=h(ta))
    item = a.get("/api/me/checklist").get_json()["items"][0]
    assert b.get("/api/me/profile").get_json()["profile"] == {}
    assert b.get("/api/me/shortlist").get_json()["shortlist"] == []
    b.patch("/api/me/checklist", json={"id": item["id"], "done": True}, headers=h(tb))         # someone else's row
    assert a.get("/api/me/checklist").get_json()["items"][0]["done"] == 0
    raw = db.conn().execute("SELECT data FROM profiles").fetchone()["data"]
    assert b"PAK" not in raw and b"4000" not in raw                                           # encrypted at rest
    assert any("English test result at B2" in i["item"] for i in a.get("/api/me/checklist").get_json()["items"])


def test_pathways_timeline_alerts_export_and_delete(ws):
    a, t = _signup(ws, "c@example.org")
    h = {"X-CSRF-Token": t}
    a.put("/api/me/profile", json={"profile": {"nationality": "IND", "education": "master", "german": "B1", "monthly_income": 6000}}, headers=h)
    a.post("/api/me/pathways", json={"pathway": "DEU-blue-card-settlement"}, headers=h)
    tl = a.get("/api/me/timeline?start=2027-01-01").get_json()["timelines"][0]
    pr = next(m for m in tl["milestones"] if m["pr"])
    assert pr == {"label": "Settlement permit", "pr": True, "date": "2028-10-01"}             # 21 months with B1 German
    a.post("/api/me/applications", json={"route": "DEU-eu-blue-card", "status": "preparing"}, headers=h)
    assert a.post("/api/me/applications", json={"route": "x", "status": "maybe"}, headers=h).status_code == 400
    assert isinstance(a.get("/api/me/alerts").get_json()["alerts"], list)
    exp = a.get("/api/me/export").get_json()
    assert exp["profile"]["nationality"] == "IND" and exp["applications"][0]["status"] == "preparing"
    assert a.delete("/api/me", json={"password": "nope"}, headers=h).status_code == 403
    assert a.delete("/api/me", json={"password": "correct horse battery"}, headers=h).get_json() == {"deleted": True}
    from relocaitor.workspace import db
    assert db.conn().execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0           # cascaded
    assert a.get("/api/me").status_code == 401


def test_rate_limit_and_security_headers(ws, monkeypatch):
    monkeypatch.setenv("RELOC_RATE_LIMIT", "3")
    from relocaitor.web import security
    security.limiter.hits.clear()
    c = ws.test_client()
    codes = [c.post("/api/score", json={}).status_code for _ in range(4)]
    assert codes[-1] == 429
    r = c.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.status_code == 200
    security.limiter.hits.clear()
