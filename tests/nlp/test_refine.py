"""Follow-up conversation: changing the current search instead of starting over."""

import pytest

from relocaitor.web.app import app

W = {"salary": 0.7, "cost": 0.5, "pr": 0.6, "job": 0.7, "climate": 0.4,
     "safety": 0.5, "healthcare": 0.4, "english": 0.5, "internet": 0.3}
BASE = {"weights": W, "region": "All regions", "profile": {}, "top_n": 5}


@pytest.fixture()
def ask():
    c = app.test_client()

    def _ask(prompt, state=BASE):
        r = c.post("/api/refine", json={"prompt": prompt, "state": state})
        assert r.status_code == 200, r.get_json()
        return r.get_json()
    return _ask


def weights_changed(d):
    return {c["key"]: (c["from"], c["to"]) for c in d["changes"] if c["kind"] == "weight"}


def test_comparatives_nudge_from_the_current_value(ask):
    assert weights_changed(ask("cheaper")) == {"cost": (0.5, 0.75)}
    assert weights_changed(ask("colder please")) == {"climate": (0.4, 0.15)}
    both = weights_changed(ask("safer and warmer"))
    assert both == {"safety": (0.5, 0.75), "climate": (0.4, 0.65)}


def test_nudges_are_clamped(ask):
    state = {**BASE, "weights": {**W, "cost": 0.9}}
    assert ask("cheaper", state)["state"]["weights"]["cost"] == 1.0


def test_relative_vs_dismissive_phrasing(ask):
    assert weights_changed(ask("salary matters less")) == {"salary": (0.7, 0.45)}
    d = weights_changed(ask("jobs matter more, forget about salary"))
    assert d["job"] == (0.7, 0.95) and d["salary"] == (0.7, 0.05)


def test_only_what_is_mentioned_changes(ask):
    d = ask("what about Asia?")
    assert d["state"]["region"] == "Asia"
    assert d["state"]["weights"] == W            # weights untouched
    assert d["state"]["profile"]["exclude_countries"] == []


def test_exclusions_accumulate_and_can_be_undone(ask):
    s1 = ask("drop Japan")["state"]
    s2 = ask("remove Spain and Italy", s1)["state"]
    assert set(s2["profile"]["exclude_countries"]) == {"Japan", "Spain", "Italy"}
    s3 = ask("add back Japan", s2)["state"]
    assert set(s3["profile"]["exclude_countries"]) == {"Spain", "Italy"}


def test_easier_visas_steps_through_difficulty(ask):
    s1 = ask("easier visas")["state"]
    assert s1["profile"]["max_difficulty"] == "Moderate"
    s2 = ask("easier visas", s1)["state"]
    assert s2["profile"]["max_difficulty"] == "Easy"
    assert ask("any difficulty", s2)["state"]["profile"]["max_difficulty"] is None


def test_profile_from_a_follow_up(ask):
    p = ask("I'm Indian earning $2k a month")["state"]["profile"]
    assert p["nationality"] == "IND" and p["monthly_income"] == 2000 and p["only_qualifying"]


def test_show_more_and_compare_top(ask):
    assert ask("show more")["state"]["top_n"] == 8
    d = ask("compare the top 3")
    assert d["state"]["top_n"] == 5
    assert d["actions"] == [{"type": "compare", "countries": d["top"][:3]}]


def test_open_and_compare_named_countries(ask):
    assert ask("why Portugal?")["actions"] == [{"type": "open", "country": "Portugal"}]
    assert ask("compare Canada vs Australia")["actions"][0] == {"type": "compare", "countries": ["Canada", "Australia"]}


def test_conversation_moves(ask):
    assert ask("undo")["actions"] == [{"type": "undo"}]
    assert ask("start over")["actions"] == [{"type": "reset"}]


def test_reply_reports_how_the_top_moved(ask):
    d = ask("I don't care about the weather")
    assert d["reply"].startswith("Changed: Climate 0.40 → 0.05.")
    assert d["previous_top"] and d["top"]
    if d["top"][0] == d["previous_top"][0]:
        assert f"{d['top'][0]} stays #1" in d["reply"]
    else:
        assert f"{d['top'][0]} is now #1" in d["reply"]


def test_unknown_follow_up_explains_what_works(ask):
    d = ask("hello")
    assert not d["changes"] and not d["actions"] and "cheaper" in d["reply"]


def test_impossible_filters_say_how_to_recover(ask):
    state = {**BASE, "region": "Oceania", "profile": {"nationality": "NGA", "monthly_income": 100, "only_qualifying": True}}
    d = ask("easier visas", state)
    if not d["top"]:
        assert "undo" in d["reply"]


def test_validation():
    c = app.test_client()
    assert c.post("/api/refine", json={"prompt": ""}).status_code == 400
    assert c.post("/api/refine", json={"prompt": "x", "state": [1]}).status_code == 400
    assert c.post("/api/refine", json={"prompt": "x", "state": {"region": "Mars"}}).status_code == 400
