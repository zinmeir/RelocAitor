"""
relocaitor/immigration/impact.py — Which logged changes affect this person, and how.

For every change since a date, the route is evaluated twice with the real eligibility rules
(eligibility.evaluate_visa): once with the previous value and once with the new one. A change matters
to a profile when the verdict moves (eligible → ineligible, conditional → eligible, ...) or, for fees
and timelines, when the route is one the person can use.
"""

from __future__ import annotations

from typing import Optional

from relocaitor.visas.eligibility import Profile, evaluate_visa
from . import records as R
from .catalogue import BY_NAME, EDITABLE_KEYS

# Catalogue field -> the visa keys it is read from (to rebuild the "before" visa).
_KEYS = {}
for _k, _f in EDITABLE_KEYS.items():
    _KEYS.setdefault(_f, []).append(_k)


def _visa_before(visa: dict, change: dict) -> dict:
    before = dict(visa)
    field, prev = change["field"], change["previous"]
    keys = _KEYS.get(field, [])
    if len(keys) == 1:
        before[keys[0]] = prev
    elif isinstance(prev, dict):                    # composite fields (age, processing, PR)
        for k in keys:
            before[k] = prev.get({"processing": "text", "processing_weeks": "weeks"}.get(k, k))
    elif prev is None:
        for k in keys:
            before.pop(k, None)
    return before


def impact(profile: Profile, changes: list, visas: dict, since: Optional[str] = None) -> list:
    routes = {R.route_id(c, v["name"]): v for c, e in visas.items() for v in e["visas"]}
    out = []
    for ch in changes:
        if since and ch["detected"] < since:
            continue
        visa = routes.get(ch["route"])
        if visa is None or ch["field"] is None:
            out.append({**_brief(ch), "effect": "route_added" if ch["kind"] == "new_pathway" else "route_removed"})
            continue
        after = evaluate_visa(visa, profile)["status"]
        before = evaluate_visa(_visa_before(visa, ch), profile)["status"]
        if before != after:
            effect = "now_eligible" if after == "eligible" else "no_longer_eligible" if after == "ineligible" else "now_conditional"
        elif after != "ineligible":
            effect = "affects_your_route"
        else:
            continue                                 # a route you can't use changed: not news for you
        out.append({**_brief(ch), "name": visa["name"], "before": before, "after": after, "effect": effect})
    return out


def _brief(ch: dict) -> dict:
    label = BY_NAME[ch["field"]].label if ch.get("field") in BY_NAME else None
    return {"route": ch["route"], "field": ch.get("field"), "label": label, "kind": ch["kind"],
            "direction": ch.get("direction"), "previous": ch["previous"], "new": ch["new"],
            "detected": ch["detected"], "verification": ch.get("verification"), "sources": ch.get("sources", [])}
