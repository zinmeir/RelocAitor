"""
pathways.py — "How could I qualify?" Counterfactual reasoning over the visa rules.

Two questions, both answered by re-running the real eligibility rules on
changed profiles (never by guessing):

1. visa_gap(visa, profile): what stands between this person and this visa?
   Income or savings shortfalls (with exact amounts), a sponsor requirement,
   or a passport restriction (which can't be fixed by effort). Each gap gets a
   `distance`: the shortfall as a share of the requirement, so "$100 short of
   $3,000" (0.03) is closer than "$2,000 short of $3,000" (0.67).

2. pathways(...): across all countries the person is considering,
   - near misses: the closest visas in countries they can't currently use;
   - levers: the smallest income / savings increase that opens new countries,
     and which hard filters are costing them the most options.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from eligibility import Profile, matches_constraints
from visas import visas_for_profile

SPONSOR_DISTANCE = 1.0        # needing a partner/family sponsor: a life change, not an effort
NEAR_MISS_MAX_DISTANCE = 1.0  # beyond this a route isn't "close"
NEAR_MISSES = 5
LEVER_STEPS = 3


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def visa_gap(visa: dict, profile: Profile, names: Optional[dict] = None) -> Optional[dict]:
    """
    {"reachable": bool, "distance": float|None, "steps": [{kind, text, ...}], "unknown": [...]}
    or None when the person already looks eligible and nothing is unknown.
    """
    names = names or {}
    steps, unknown = [], []
    reachable = True

    restricted = visa.get("restricted_to")
    if restricted:
        if not profile.nationality:
            unknown.append("passport")
        elif profile.nationality not in restricted:
            reachable = False
            who = (", ".join(names.get(c, c) for c in restricted) if len(restricted) <= 3
                   else f"{len(restricted)} listed nationalities")
            steps.append({"kind": "passport", "text": f"Only open to citizens of {who}."})

    distance = 0.0
    mi = visa.get("min_income") or 0
    if mi > 0:
        if profile.monthly_income is None:
            unknown.append("income")
        elif profile.monthly_income < mi:
            gap = mi - profile.monthly_income
            distance += gap / mi
            steps.append({"kind": "income", "need": mi, "gap": gap,
                          "text": f"Earn {_usd(gap)}/mo more (about {_usd(mi)}/mo in total)."})

    inv = visa.get("min_investment") or 0
    if inv > 0:
        if profile.investment_budget is None:
            unknown.append("savings")
        elif profile.investment_budget < inv:
            gap = inv - profile.investment_budget
            distance += gap / inv
            steps.append({"kind": "savings", "need": inv, "gap": gap,
                          "text": f"Have {_usd(gap)} more to invest (about {_usd(inv)} in total)."})

    if visa.get("requires_sponsor"):
        distance += SPONSOR_DISTANCE
        steps.append({"kind": "sponsor",
                      "text": "Needs a partner or family member who is a citizen or resident there."})

    if not steps and not unknown:
        return None
    hint = {"passport": "your passport", "income": "your income", "savings": "your savings"}
    if unknown:
        steps.append({"kind": "unknown",
                      "text": "Add " + " and ".join(hint[u] for u in unknown) + " to check this properly."})
    return {"reachable": reachable, "distance": distance if reachable else None,
            "steps": steps, "unknown": unknown}


def _qualifying_codes(codes, profile: Profile) -> set:
    return {c for c in codes if visas_for_profile(c, profile)["qualifying_count"] > 0}


def _levels(values, current: Optional[float]) -> list:
    """Distinct requirement levels above what the person has now, ascending."""
    if current is None:
        return []
    return sorted({v for v in values if v and v > current})


def pathways(candidates: list, profile: Profile, names: dict) -> dict:
    """
    candidates: country codes the person is considering (region, exclusions and
    home country already applied, visa filters NOT applied), in ranking order.
    """
    qual = {c: visas_for_profile(c, profile) for c in candidates}
    open_now = [c for c in candidates if qual[c]["qualifying_count"] > 0]
    open_set = set(open_now)

    # ---- near misses: closest route in each country that isn't open yet ----
    near = []
    for c in candidates:
        if c in open_set:
            continue
        best = None
        for v in qual[c]["visas"]:
            if not matches_constraints(v, profile):
                continue
            if v.get("requires_sponsor") and profile.visa_type != "family":
                continue                       # needing a spouse there isn't a "near miss"
            gap = visa_gap(v, profile, names)
            if not gap or not gap["reachable"] or gap["unknown"] or gap["distance"] > NEAR_MISS_MAX_DISTANCE:
                continue
            if gap["distance"] <= 0:
                continue
            if best is None or gap["distance"] < best[0]:
                best = (gap["distance"], v, gap)
        if best:
            near.append({"country": names.get(c, c), "country_code": c, "visa": best[1]["name"],
                         "type": best[1]["type"], "distance": best[0],
                         "steps": [s["text"] for s in best[2]["steps"]]})
    near.sort(key=lambda x: x["distance"])     # stable: ranking order breaks ties

    # ---- levers: what single change opens the most new countries ----
    levers = []
    all_visas = [v for c in candidates for v in qual[c]["visas"] if matches_constraints(v, profile)]
    for field, kind, key, unit in (("monthly_income", "income", "min_income", "/mo"),
                                   ("investment_budget", "savings", "min_investment", "")):
        current = getattr(profile, field)
        seen = set()
        for level in _levels([v.get(key) for v in all_visas], current):
            opened = [c for c in candidates
                      if c not in open_set and c in _qualifying_codes([c], replace(profile, **{field: level}))]
            new = [c for c in opened if c not in seen]
            if not new:
                continue
            word = "Earning" if kind == "income" else "Having"
            what = f"{_usd(level)}{unit}" + (" to invest" if kind == "savings" else "")
            text = (f"{word} {what} (+{_usd(level - current)}) would " + ("also " if seen else "")
                    + f"open {_list([names.get(c, c) for c in new])}"
                    + (f" ({len(opened)} new countries in total)." if seen else "."))
            levers.append({"kind": kind, "value": level, "delta": level - current, "count": len(opened),
                           "countries": [names.get(c, c) for c in new], "text": text})
            seen.update(opened)
            if sum(1 for x in levers if x["kind"] == kind) >= LEVER_STEPS:
                break

    relax = [("require_pr", False, "Allowing routes without permanent residency"),
             ("max_difficulty", None, "Allowing harder visas"),
             ("visa_type", "any", "Allowing any visa type")]
    for field, value, label in relax:
        if getattr(profile, field) in (value, None, "", "any", False):
            continue
        opened = sorted(_qualifying_codes(candidates, replace(profile, **{field: value})) - open_set,
                        key=candidates.index)
        if opened:
            levers.append({"kind": "filter", "field": field, "count": len(opened),
                           "countries": [names.get(c, c) for c in opened],
                           "text": f"{label} would open {_list([names.get(c, c) for c in opened])}."})

    missing = [f for f, v in (("passport", profile.nationality), ("income", profile.monthly_income),
                              ("savings", profile.investment_budget)) if v in (None, "")]
    return {
        "open_count": len(open_now),
        "candidate_count": len(candidates),
        "near_misses": near[:NEAR_MISSES],
        "levers": levers,
        "missing": missing,
    }


def _list(items: list, limit: int = 3) -> str:
    if len(items) <= limit:
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    return ", ".join(items[:limit]) + f" and {len(items) - limit} more"


def annotate_visas(visas: list, profile: Profile, names: dict) -> list:
    """Copies of the visa cards with a `path` (None when nothing stands in the way)."""
    out = []
    for v in visas:
        v = dict(v)
        v["path"] = None if v.get("generated") else visa_gap(v, profile, names)
        out.append(v)
    return out

