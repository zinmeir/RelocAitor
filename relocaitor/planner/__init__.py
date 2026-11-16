"""
relocaitor.planner — the relocation pathway optimizer.

Finds every route to permanent residence open to a profile: single routes that lead to residence
themselves, and the multi-stage pathways in data/transitions.json. Eligibility for the first step is
decided by the real rules (eligibility.evaluate_visa); later steps list the conditions still to meet.
Times and costs add up only what is known; anything unknown is reported, never filled in.

    plan(profile, countries=None, study_years=None) -> {"pathways": [...], "comparison": [...]}
    what_if(profile, changes) -> which routes open or close if the profile changes
"""

from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Optional

from relocaitor.visas.eligibility import Profile, evaluate_visa, free_movement_pathways, rules
from relocaitor.immigration.records import route_id
from relocaitor.visas import journey
from relocaitor.visas import catalog as V
from relocaitor import paths

DATA = paths.DATA
RANK = {"eligible": 0, "conditional": 1, "ineligible": 2}


@lru_cache(maxsize=1)
def transitions() -> dict:
    return json.loads((DATA / "transitions.json").read_text(encoding="utf-8"))


def _routes() -> dict:
    out = {}
    for code, entry in V._load().items():
        for v in entry["visas"]:
            out[route_id(code, v["name"])] = (code, v, entry)
    return out


CHECKED_REQUIREMENTS = ("education", "work_experience", "language")


@lru_cache(maxsize=1)
def _records() -> dict:
    from relocaitor.immigration import store
    return store.load("records", {}).get("routes", {})


def unchecked(rid: str) -> list:
    """Requirements we have no data on for this route: 'likely eligible' can't account for them."""
    from relocaitor.immigration.catalogue import BY_NAME
    rec = _records().get(rid)
    if not rec:
        return [BY_NAME[f].label for f in CHECKED_REQUIREMENTS]
    return [BY_NAME[f].label for f in CHECKED_REQUIREMENTS if rec["fields"][f]["status"] == "unknown"]


def _fee_usd(v: dict) -> Optional[float]:
    fee = v.get("fee")
    return journey.to_usd(fee.get("amount"), fee.get("currency")) if fee else None


def _citizenship(entry: dict) -> Optional[dict]:
    c = entry.get("citizenship")
    return {"years": c["years"], "after_pr": c.get("after_pr"), "source": c["source"],
            "status": "third_party" if c.get("source_kind") == "secondary" else "sourced"} if c else None


def _years_after_pr(cit: Optional[dict], years_to_pr: Optional[float]) -> Optional[float]:
    """Citizenship counted from arrival: the rule's residence years, or PR + years as a permanent resident."""
    if not cit or years_to_pr is None:
        return None
    total = cit["years"]
    if cit.get("after_pr"):
        total = max(total, years_to_pr + cit["after_pr"])
    return max(total, years_to_pr)


def _direct(rid: str, code: str, v: dict, entry: dict, profile: Profile) -> Optional[dict]:
    """A single route that leads to residence by itself, if the time to residence is researched."""
    if v.get("years_to_pr") is None:
        return None
    verdict = evaluate_visa(v, profile)
    fee = _fee_usd(v)
    cit = _citizenship(entry)
    return {
        "id": f"direct:{rid}", "country": code, "kind": "direct", "title": v["name"],
        "steps": [{"route": rid, "label": v["name"], "status": verdict["status"], "reasons": verdict["reasons"],
                   "years": v["years_to_pr"], "fee_usd": fee, "pr": True, "sources": v.get("sources", []),
                   "unchecked": unchecked(rid)}],
        "first_step": verdict["status"], "unchecked": unchecked(rid),
        "years_to_pr": {"min": v["years_to_pr"], "max": v["years_to_pr"], "unknown": []},
        "years_to_citizenship": _years_after_pr(cit, v["years_to_pr"]),
        "citizenship": cit,
        "cost_usd": {"known": fee or 0, "unknown_fees": 0 if fee is not None else 1},
        "limits": [v["pr_note"]] if v.get("pr_note") else [],
        "open_conditions": [],
    }


def _multi(p: dict, routes: dict, profile: Profile, study_years: Optional[float]) -> Optional[dict]:
    steps, lo, hi, unknown, known_cost, unknown_fees, conditions = [], 0.0, 0.0, [], 0.0, 0, []
    first = None
    for i, s in enumerate(p["steps"]):
        st = {"label": s["label"], "pr": s.get("pr", False), "sources": list(s.get("sources", [])),
              "note": s.get("years_note")}
        if s.get("route"):
            if s["route"] not in routes:
                return None
            code, v, _ = routes[s["route"]]
            verdict = evaluate_visa(v, profile)
            st.update(route=s["route"], status=verdict["status"], reasons=verdict["reasons"], unchecked=unchecked(s["route"]))
            st["sources"] = sorted(set(st["sources"]) | set(v.get("sources", [])))
            fee = _fee_usd(v)
            st["fee_usd"] = fee
            if fee is None:
                unknown_fees += 1
            else:
                known_cost += fee
            if i > 0 and verdict["status"] != "eligible":
                conditions.append(f"{v['name']}: " + ("; ".join(verdict["reasons"]) or "check eligibility"))
        if first is None:
            first = st.get("status", "conditional")
        years = s.get("years")
        if s.get("years_by_german"):
            years = s["years_by_german"].get(profile.german) if profile.german else None
            if profile.german and years is None:
                scale = rules()["scales"]["cefr"]
                ok = [y for lv, y in s["years_by_german"].items() if scale.index(profile.german) >= scale.index(lv)]
                years = min(ok) if ok else None
            if years is None:
                conditions.append("Reach A1 German at least: " + s["years_note"])
        if years is None and s.get("route") and s["route"].endswith(("pgwp", "graduate-route")) and study_years:
            years = study_years
        if years is None and not s.get("pr"):
            unknown.append(s.get("years_note") or s["label"])
            hi_add = s.get("max_years")
            hi = hi + hi_add if (hi is not None and hi_add) else None
        elif years is not None:
            lo += years
            hi = hi + years if hi is not None else None
        elif s.get("pr"):
            unknown.append(s.get("years_note") or s["label"])
        if s.get("condition"):
            conditions.append(s["condition"])
        st["years"] = years
        steps.append(st)
    code = p["country"]
    cit = _citizenship(V.country_entry(code))
    pr_known = not unknown
    return {
        "id": p["id"], "country": code, "kind": p["kind"], "title": p["title"], "steps": steps,
        "first_step": first, "unchecked": steps[0].get("unchecked", []),
        "years_to_pr": {"min": lo, "max": hi if pr_known else None, "unknown": unknown},
        "years_to_citizenship": _years_after_pr(cit, lo) if pr_known else None,
        "citizenship": cit,
        "cost_usd": {"known": round(known_cost), "unknown_fees": unknown_fees},
        "limits": p.get("limits", []), "open_conditions": conditions,
    }


def _sort_key(pw: dict):
    yrs = pw["years_to_pr"]
    known = 0 if not yrs["unknown"] else 1
    step = RANK.get(pw["first_step"], 2)
    if step == 0 and len(pw.get("unchecked", [])) == len(CHECKED_REQUIREMENTS) and pw["kind"] != "free_movement":
        step = 1          # "eligible" on passport and money alone: not established, rank with conditional routes
    return (step, len(pw.get("unchecked", [])), known, yrs["min"],
            pw["cost_usd"]["unknown_fees"], pw["cost_usd"]["known"])


def plan(profile: Profile, countries: Optional[list] = None, study_years: Optional[float] = None) -> dict:
    routes = _routes()
    out = []
    staged = {p["steps"][0].get("route") for p in transitions()["pathways"]}   # covered by a multi-stage plan
    for rid, (code, v, entry) in routes.items():
        if (countries and code not in countries) or rid in staged:
            continue
        d = _direct(rid, code, v, entry, profile)
        if d:
            out.append(d)
    for p in transitions()["pathways"]:
        if countries and p["country"] not in countries:
            continue
        m = _multi(p, routes, profile, study_years)
        if m:
            out.append(m)
    if profile.nationality:
        for code in (countries or sorted({c for c, _, _ in routes.values()})):
            for fm in free_movement_pathways(profile.nationality, code):
                out.append({"id": f"free:{code}", "country": code, "kind": "free_movement", "title": fm["name"],
                            "steps": [{"label": fm["name"], "status": "eligible", "pr": fm["pr_route"] == "Yes"}],
                            "first_step": "eligible", "unchecked": [], "years_to_pr": {"min": 0, "max": None, "unknown": [fm["duration"]]},
                            "years_to_citizenship": None, "citizenship": _citizenship(V.country_entry(code)),
                            "cost_usd": {"known": 0, "unknown_fees": 1}, "limits": [fm["summary"]], "open_conditions": []})
    out.sort(key=_sort_key)
    for i, pw in enumerate(out, 1):
        pw["rank"] = i
        pw["risk"] = _risk(pw)
    return {"pathways": out, "comparison": compare(out[:2]) if len(out) >= 2 else None,
            "note": "Ranked by whether you can start now, then how many of its requirements we could check, then known time "
                    "to permanent residence, then cost. "
                    "A pathway is a legal possibility, not a prediction that an application succeeds."}


def _risk(pw: dict) -> dict:
    reasons = []
    if pw.get("unchecked"):
        reasons.append("not checked: " + ", ".join(pw["unchecked"]).lower())
    if pw["first_step"] != "eligible":
        reasons.append("you don't yet meet the first step")
    if pw["years_to_pr"]["unknown"]:
        reasons.append(f"{len(pw['years_to_pr']['unknown'])} unknown duration(s)")
    if pw["cost_usd"]["unknown_fees"]:
        reasons.append(f"{pw['cost_usd']['unknown_fees']} unresearched fee(s)")
    if pw["limits"]:
        reasons.append("documented limits (e.g. competitive selection)")
    if pw["open_conditions"]:
        reasons.append(f"{len(pw['open_conditions'])} condition(s) still to meet")
    points = len(reasons) + max(0, len(pw.get("unchecked", [])) - 1)
    level = "low" if points <= 1 else "medium" if points <= 3 else "high"
    return {"level": level, "reasons": reasons}


def compare(pair: list) -> dict:
    """Why the first pathway ranks above the second, from the same keys the ranking uses."""
    a, b = pair
    why = []
    if RANK[a["first_step"]] < RANK[b["first_step"]]:
        why.append(f"you can start it now ({a['first_step']}) while the other's first step is {b['first_step']}")
    elif len(a.get("unchecked", [])) < len(b.get("unchecked", [])):
        why.append("more of its requirements are researched, so 'likely eligible' means more")
    ya, yb = a["years_to_pr"], b["years_to_pr"]
    if not ya["unknown"] and yb["unknown"]:
        why.append("its time to permanent residence is fully known")
    elif not ya["unknown"] and not yb["unknown"] and ya["min"] < yb["min"]:
        why.append(f"it reaches permanent residence sooner ({ya['min']:g} vs {yb['min']:g} years)")
    if a["cost_usd"]["unknown_fees"] < b["cost_usd"]["unknown_fees"]:
        why.append("more of its fees are researched")
    elif a["cost_usd"]["known"] < b["cost_usd"]["known"] and not a["cost_usd"]["unknown_fees"]:
        why.append(f"it costs less in known fees (${a['cost_usd']['known']:,.0f} vs ${b['cost_usd']['known']:,.0f})")
    return {"first": a["id"], "second": b["id"],
            "text": f"{a['title']} ranks above {b['title']} because " + ("; ".join(why) if why else "they tie on every ranking key; order is by cost")}


# ---------------------------------------------------------------------------
# Counterfactuals: re-run the real rules with the profile changed
# ---------------------------------------------------------------------------
WHAT_IF_FIELDS = {"monthly_income", "investment_budget", "education", "experience_years", "english", "german", "age"}


def what_if(profile: Profile, changes: dict) -> dict:
    bad = set(changes) - WHAT_IF_FIELDS
    if bad:
        raise ValueError(f"Can't model a change to: {', '.join(sorted(bad))}")
    after = replace(profile, **changes)
    opened, closed, improved = [], [], []
    for rid, (code, v, _) in _routes().items():
        a, b = evaluate_visa(v, profile)["status"], evaluate_visa(v, after)["status"]
        if a == b:
            continue
        item = {"route": rid, "country": code, "name": v["name"], "before": a, "after": b,
                "reasons_after": evaluate_visa(v, after)["reasons"]}
        if b == "eligible":
            opened.append(item)
        elif RANK[b] > RANK[a]:
            closed.append(item)
        else:
            improved.append(item)
    return {"changes": changes, "opened": opened, "closed": closed, "improved": improved,
            "note": "Eligibility re-checked with the same rules after the change. This is what the rules say, not a guarantee."}
