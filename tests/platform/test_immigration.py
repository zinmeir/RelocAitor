"""Immigration intelligence: statuses, versions, change detection, the approval workflow, monitoring, impact."""

import copy
import json
from datetime import date

import pytest

from relocaitor.visas.eligibility import Profile
from relocaitor.immigration import impact as I, monitor, records as R, store, workflow
from relocaitor.immigration.catalogue import BY_NAME, FIELDS

VISAS = store.load_visas()
UK_SKILLED = "GBR-skilled-worker-visa"


def _uk_skilled_name():
    return next(v["name"] for v in VISAS["GBR"]["visas"] if R.route_id("GBR", v["name"]) == UK_SKILLED)


@pytest.fixture
def imm(tmp_path):
    """An empty immigration store plus a private copy of visas.json."""
    d = tmp_path / "immigration"
    (d / "proposals").mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir()
    (data / "visas.json").write_text(json.dumps(VISAS))
    for n in ("updates", "verifications", "changes", "sources"):
        store.save(n, [], d)
    store.build(today="2026-11-16", data_dir=data, d=d)
    return d, data


def _propose(d, name="p1.json", **kw):
    prop = {"route": UK_SKILLED, "changes": {"min_income": 4000}, "sources": ["https://www.gov.uk/skilled-worker-visa"],
            "checked": "2026-11-20", "evidence": "You must usually be paid at least £41,700 per year.",
            "proposed_by": "research run 7"}
    prop.update(kw)
    (d / "proposals" / name).write_text(json.dumps(prop))
    return prop


def _merge_updates(d, data, monkeypatch):
    """What `python -m pipeline.visa_details` does with approved updates."""
    from pipeline import visa_details
    monkeypatch.setattr(visa_details, "UPDATES", d / "updates.json")
    v = json.loads((data / "visas.json").read_text())
    visa_details._apply_updates(v)
    (data / "visas.json").write_text(json.dumps(v))


# --- the data model ----------------------------------------------------------
def test_catalogue_covers_the_brief():
    names = {f.name for f in FIELDS}
    assert names >= {"nationality_restrictions", "min_income", "min_savings", "investment", "education",
                     "work_experience", "language", "age", "sponsorship", "dependants", "spouse_work_rights",
                     "healthcare", "fees", "processing_time", "duration", "renewal", "residence_requirements",
                     "pr_pathway", "citizenship_pathway", "tax", "documents", "application_url"}


def test_every_route_reports_every_field_and_unknown_means_no_value():
    recs = R.build_records(VISAS)
    assert len(recs) == sum(len(e["visas"]) for e in VISAS.values())
    for rec in recs.values():
        assert set(rec["fields"]) == {f.name for f in FIELDS}
        for f in rec["fields"].values():
            assert (f["status"] == "unknown") == (f["value"] is None)


def test_nothing_is_verified_without_a_human_sign_off():
    recs = R.build_records(VISAS)
    statuses = {f["status"] for r in recs.values() for f in r["fields"].values()}
    assert "verified" not in statuses
    uk = recs[UK_SKILLED]["fields"]
    assert uk["fees"]["status"] == "sourced" and uk["fees"]["sources"][0].startswith("https://")   # AI-read official page
    assert uk["min_income"]["status"] == "estimated"                                               # curated, no source
    assert uk["citizenship_pathway"]["status"] == "third_party"                                    # Wikipedia
    assert uk["difficulty"]["note"] == "Editorial rating"


def test_values_go_out_of_date():
    f = {"status": "sourced", "checked": "2026-01-01"}
    assert R.status_on(f, "processing_time", date(2026, 6, 1)) == "sourced"
    assert R.status_on(f, "processing_time", date(2026, 8, 1)) == "outdated"     # 180-day window
    assert R.status_on(f, "duration", date(2026, 8, 1)) == "sourced"             # 730-day window
    assert R.status_on({"status": "estimated"}, "fees", date(2030, 1, 1)) == "estimated"


def test_shipped_records_are_current_and_every_logged_change_bumped_its_version():
    assert store.is_up_to_date()
    routes = store.load("records", {})["routes"]
    changed = {c["route"] for c in store.load("changes")}
    assert changed >= {"CAN-express-entry-fsw", "GBR-skilled-worker-visa", "DEU-eu-blue-card"}   # Phase 2 research
    assert all(routes[r]["rule_version"] >= 2 for r in changed)
    assert all(r["rule_version"] == 1 for k, r in routes.items() if k not in changed)


# --- change detection and versions ---------------------------------------------
def test_changes_are_classified_with_direction_and_versions_bump():
    before = R.build_records(VISAS)
    v2 = copy.deepcopy(VISAS)
    uk = next(v for v in v2["GBR"]["visas"] if v["name"] == _uk_skilled_name())
    uk["min_income"] += 500
    uk["fee"] = {**uk["fee"], "amount": uk["fee"]["amount"] + 100}
    v2["GBR"]["visas"].append({**uk, "name": "Brand New Route"})
    removed = v2["USA"]["visas"].pop()
    after = R.build_records(v2)
    changes = R.detect_changes(before, after, "2026-12-01")
    kinds = {(c["route"], c["kind"], c.get("direction")) for c in changes}
    assert (UK_SKILLED, "income_requirement", "increased") in kinds
    assert (UK_SKILLED, "application_fee", "increased") in kinds
    assert ("GBR-brand-new-route", "new_pathway", None) in kinds
    assert (R.route_id("USA", removed["name"]), "removed_or_suspended", None) in kinds
    assert all(c["verification"] == "pending" and c["detected"] == "2026-12-01" for c in changes)
    R.apply_versions({k: {**v, "rule_version": 1} for k, v in before.items()}, after, changes)
    assert after[UK_SKILLED]["rule_version"] == 2
    assert after["GBR-brand-new-route"]["rule_version"] == 1
    assert after["DEU-eu-blue-card"]["rule_version"] == 1


# --- proposals, approval, verification -----------------------------------------
def test_proposals_are_blocked_until_they_are_checkable(imm):
    d, data = imm
    prop = _propose(d, sources=["https://en.wikipedia.org/wiki/Visa"], evidence="")
    problems = workflow.check(prop, VISAS)["problems"]
    assert any("secondary source" in p for p in problems) and any("evidence" in p for p in problems)
    assert workflow.check({**prop, "changes": {"salary": 1}}, VISAS)["problems"]
    assert any("Unknown route" in p for p in workflow.check({**prop, "route": "GBR-nope"}, VISAS)["problems"])


def test_a_model_cannot_approve_or_verify(imm):
    d, data = imm
    _propose(d)
    with pytest.raises(ValueError, match="person"):
        workflow.approve("p1.json", "Claude", d=d, data_dir=data)
    with pytest.raises(ValueError, match="person"):
        workflow.verify(UK_SKILLED, "fees", "LLM", "https://www.gov.uk/x", d=d, data_dir=data)


def test_approved_update_flows_through_to_versions_changes_status_and_impact(imm, monkeypatch):
    d, data = imm
    _propose(d)
    old_income = next(v for v in VISAS["GBR"]["visas"] if v["name"] == _uk_skilled_name())["min_income"]
    res = workflow.approve("p1.json", "A. Reviewer", today="2026-11-21", d=d, data_dir=data)
    assert res["diff"] == [{"key": "min_income", "previous": old_income, "new": 4000}]
    assert not (d / "proposals" / "p1.json").exists()
    _merge_updates(d, data, monkeypatch)
    out = store.build(today="2026-11-21", data_dir=data, d=d)
    (change,) = out["changes"]
    assert change["kind"] == "income_requirement" and change["previous"] == old_income and change["new"] == 4000
    rec = store.load("records", {}, d)["routes"][UK_SKILLED]
    assert rec["rule_version"] == 2
    f = rec["fields"]["min_income"]
    assert f["status"] == "verified" and f["verified_by"] == "A. Reviewer" and f["checked"] == "2026-11-21"
    assert store.load("changes", d=d)[0]["id"] == change["id"]
    # Someone earning between the old and the new threshold loses the route; the rules decide, not a guess.
    mid = Profile(nationality="IND", monthly_income=(old_income + 4000) / 2)
    (hit,) = [x for x in I.impact(mid, [change], json.loads((data / "visas.json").read_text())) if x["route"] == UK_SKILLED]
    assert hit["before"] != "ineligible" and hit["after"] == "ineligible" and hit["effect"] == "no_longer_eligible"
    rich = Profile(nationality="IND", monthly_income=9000)
    assert I.impact(rich, [change], json.loads((data / "visas.json").read_text()))[0]["effect"] == "affects_your_route"
    assert I.impact(rich, [change], VISAS, since="2027-01-01") == []


def test_signing_off_an_existing_value_and_losing_it_when_the_value_changes(imm):
    d, data = imm
    workflow.verify(UK_SKILLED, "duration", "B. Checker", "https://www.gov.uk/skilled-worker-visa", today="2026-11-22",
                    d=d, data_dir=data)
    recs = R.build_records(store.load_visas(data), store.load("updates", d=d), store.load("verifications", d=d))
    assert recs[UK_SKILLED]["fields"]["duration"]["status"] == "verified"
    v2 = store.load_visas(data)
    next(v for v in v2["GBR"]["visas"] if v["name"] == _uk_skilled_name())["duration"] = "Up to 6 years"
    recs = R.build_records(v2, [], store.load("verifications", d=d))
    f = recs[UK_SKILLED]["fields"]["duration"]
    assert f["status"] == "estimated" and "no longer matches" in f["note"]
    with pytest.raises(ValueError, match="no value"):
        workflow.verify(UK_SKILLED, "tax", "B. Checker", "https://www.gov.uk/x", d=d, data_dir=data)


# --- source registry and monitoring ----------------------------------------------
def test_source_registry_lists_publishers_and_marks_secondary_ones():
    srcs = {s["id"]: s for s in store.load("sources")}
    assert srcs["en.wikipedia.org"]["kind"] == "third_party"
    assert srcs["www.gov.uk"]["kind"] == "official" and UK_SKILLED in srcs["www.gov.uk"]["routes"]
    assert all(s["access"] == "manual" for s in srcs.values())


def test_monitor_flags_changed_pages_and_respects_robots():
    src = [{"urls": ["https://a.gov/page", "https://b.gov/private", "https://c.gov/down"], "routes": ["GBR-x"]}]
    pages = {"https://a.gov/page": "<p>Fee: £719</p><script>t=1</script>"}

    def fetch(url):
        if url not in pages:
            raise OSError("timeout")
        return pages[url]

    allowed = lambda url: "private" not in url   # noqa: E731
    first = monitor.check_pages(src, {}, fetch, allowed, today="2026-11-01")
    assert [e["event"] for e in first["events"]] == ["not_allowed", "unreachable"]
    pages["https://a.gov/page"] = "<p>Fee: £719</p><script>t=2</script>"     # only a script changed
    assert not [e for e in monitor.check_pages(src, first["hashes"], fetch, allowed)["events"] if e["event"] == "changed"]
    pages["https://a.gov/page"] = "<p>Fee: £769</p>"
    second = monitor.check_pages(src, first["hashes"], fetch, allowed, today="2026-12-01")
    (changed,) = [e for e in second["events"] if e["event"] == "changed"]
    assert changed["routes"] == ["GBR-x"] and changed["last_seen"] == "2026-11-01"


# --- API ------------------------------------------------------------------------
def test_immigration_api(client):
    r = client.get("/api/immigration/routes?country=GBR").get_json()
    rec = next(x for x in r["routes"] if x["id"] == UK_SKILLED)
    assert rec["fields"]["fees"]["status"] in ("sourced", "outdated") and rec["summary"]["fields"] == len(FIELDS)
    assert "verified" in r["statuses"]
    assert {c["kind"] for c in client.get("/api/immigration/changes?since=2026-01-01").get_json()["changes"]} >= {
        "language_requirement", "education_requirement", "experience_requirement"}
    assert client.get("/api/immigration/changes?since=2099-01-01").get_json() == {"changes": []}
    assert client.get("/api/immigration/sources").get_json()["sources"]
    # A Pakistani with B1 English: the UK's new B2 rule shows up as "no longer eligible" for Skilled Worker.
    imp = client.post("/api/immigration/impact", json={"profile": {"nationality": "PAK", "english": "B1", "monthly_income": 6000}}).get_json()["impact"]
    uk = [x for x in imp if x["route"] == UK_SKILLED]
    assert uk and uk[0]["effect"] == "no_longer_eligible"
    assert client.post("/api/immigration/impact", json={"since": 5}).status_code == 400
    meta = client.get("/api/meta").get_json()
    assert meta["visa_status"][f"GBR|{_uk_skilled_name()}"]["counts"]["sourced"] >= 1
    assert BY_NAME["fees"].fresh_days == 365
