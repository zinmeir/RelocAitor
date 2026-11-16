"""
refine.py — Follow-up conversation: change the current search instead of starting over.

    refine("cheaper, and what about Asia?", state, meta)

`state` is what the app currently shows: {weights, region, profile, top_n}.
A follow-up is read in three layers:

1. Relative changes the rules can't express as absolutes: "cheaper", "safer",
   "warmer", "colder", "jobs matter more", "forget about salary" → nudge that
   weight by STEP (0.25) up or down from where it is now.
2. Everything the normal prompt reader understands ("in Asia", "not Japan",
   "I'm Indian", "$3k a month", "top 10", "safety is important"), merged into
   the current state: only what the follow-up mentions changes.
3. Conversation moves: "undo", "start over", "add back Japan", "easier visas",
   "show more", "why Portugal?", "compare the top 3".

The reply says what changed and how the top of the list moved, computed by
re-running the real ranking before and after.
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache

import engine
import search
from factors import FACTOR_KEYS, FACTORS
from validation import parse_profile, parse_region, parse_top_n, parse_weights

NUM_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}
DIFFICULTY_STEPS = ["", "Moderate", "Easy"]          # each "easier" moves one step right


@lru_cache(maxsize=1)
def vocab() -> dict:
    return search.lexicon()["refine"]


def norm(text: str) -> str:
    """Lowercase, apostrophes dropped, punctuation to spaces, padded with spaces for phrase lookups."""
    t = (text or "").lower().replace("’", "'").replace("'", "")
    t = re.sub(r"[^a-z0-9$€£₹%]+", " ", t)
    return f" {t.strip()} "


def has(text: str, phrases) -> bool:
    return any(f" {p} " in text for p in phrases)


def factor_nudges(text: str) -> dict:
    """{factor: +1 / -1 / "drop"} from comparatives ("cheaper"), relative patterns ("jobs matter more",
    "salary matters less") and dismissals ("forget about salary", which sets it to almost nothing)."""
    V = vocab()
    out = {}
    for comp in V["comparatives"]:
        if has(text, comp["phrases"]):
            out[comp["factor"]] = comp["dir"]
    for f, words in V["factor_words"].items():
        for w in words:
            if has(text, [p.replace("{f}", w) for p in V["more_patterns"]]):
                out[f] = 1
            if has(text, [p.replace("{f}", w) for p in V["less_patterns"]]):
                out[f] = -1
            if has(text, [p.replace("{f}", w) for p in V["drop_patterns"]]):
                out[f] = "drop"
    return out


def _state_from(raw: dict) -> dict:
    raw = raw or {}
    weights = parse_weights(raw.get("weights"))
    profile = parse_profile(raw.get("profile"))
    p = profile.to_dict()
    p["exclude_countries"] = list(p.get("exclude_countries") or [])
    return {"weights": dict(weights), "region": parse_region(raw.get("region")),
            "profile": p, "top_n": parse_top_n(raw.get("top_n"))}


def _ranked_names(state: dict) -> list:
    from eligibility import Profile
    p = dict(state["profile"])
    p["exclude_countries"] = tuple(p.get("exclude_countries") or ())
    ranked = engine.rank(state["weights"], state["region"], Profile(**p))
    return list(ranked["country_name"])


def _label(k: str) -> str:
    return FACTORS[k]["label"]


def refine(prompt: str, raw_state: dict, meta: dict) -> dict:
    V = vocab()
    text = norm(prompt)
    old = _state_from(raw_state)
    new = copy.deepcopy(old)
    names = {n["code"]: n["name"] for n in meta["nationalities"]}
    codes = {n["name"]: n["code"] for n in meta["nationalities"]}
    changes, actions = [], []

    words = text.split()
    if has(text, V["reset"]):
        msg = "Starting over: everything is back to the defaults."
        return {"state": old, "changes": [], "actions": [{"type": "reset"}],
                "reply": msg, "outcome": msg, "visa_hits": [], "top": [], "previous_top": []}
    if has(text, V["undo"]) and len(words) <= 4:
        msg = "Undone: back to the previous results."
        return {"state": old, "changes": [], "actions": [{"type": "undo"}],
                "reply": msg, "outcome": msg, "visa_hits": [], "top": [], "previous_top": []}

    r = search.interpret_rules(prompt, meta)

    # ---- weights: relative nudges first, then absolute mentions ----
    nudges = factor_nudges(text)
    explicit = {c["key"] for c in r["chips"] if c.get("kind") in ("factor", "learned", "semantic") and "key" in c}
    for k in FACTOR_KEYS:
        before = old["weights"][k]
        if nudges.get(k) == "drop":
            after = search.W_DEPRIO
        elif k in nudges:                      # relative phrasing wins over the rules' absolute reading
            after = round(min(1.0, max(0.0, before + V["step"] * nudges[k])), 2)
        elif k in explicit and r["weights"]:
            after = r["weights"][k]
        else:
            continue
        if after != before:
            new["weights"][k] = after
            changes.append({"kind": "weight", "key": k, "icon": k, "from": before, "to": after,
                            "label": f"{_label(k)} {before:.2f} → {after:.2f}"})

    # ---- region ----
    if has(text, V["any_region"]) and old["region"] != "All regions":
        new["region"] = "All regions"
        changes.append({"kind": "region", "icon": "region", "label": "Region: anywhere"})
    elif r["region"] and r["region"] != old["region"]:
        new["region"] = r["region"]
        changes.append({"kind": "region", "icon": "region", "label": f"Region: {r['region']}"})

    # ---- countries: drop, add back, open, compare ----
    excl = list(new["profile"]["exclude_countries"])
    mentioned = [codes[n] for n in r["countries"] if n in codes]
    if has(text, V["add_back"]):
        back = [c for c in mentioned + [codes[n] for n in r["exclude"] if n in codes] if c in excl]
        for c in dict.fromkeys(back):
            excl.remove(c)
            changes.append({"kind": "include", "icon": "pin", "label": f"Added back {names[c]}"})
        mentioned = []
    else:
        for n in r["exclude"]:
            c = codes.get(n)
            if c and c not in excl:
                excl.append(c)
                changes.append({"kind": "exclude", "icon": "exclude", "label": f"Excluding {n}"})
    new["profile"]["exclude_countries"] = excl

    # ---- about you and filters ----
    rp = r["profile"]
    for key, label in (("nationality", "Passport"), ("monthly_income", "Income"), ("investment_budget", "Savings")):
        if key in rp and rp[key] != old["profile"].get(key):
            new["profile"][key] = rp[key]
            shown = names.get(rp[key], rp[key]) if key == "nationality" else search.money_fmt(rp[key])
            changes.append({"kind": "profile", "icon": {"nationality": "pr", "monthly_income": "income", "investment_budget": "savings"}[key], "label": f"{label}: {shown}"})
            new["profile"]["only_qualifying"] = True
    if "occupation" in rp and rp["occupation"] != old["profile"].get("occupation"):
        new["profile"]["occupation"] = rp["occupation"]
        changes.append({"kind": "profile", "icon": "job", "label": f"Field: {search._field_label(rp['occupation'])}"})
    if "age" in rp and rp["age"] != old["profile"].get("age"):
        new["profile"]["age"] = rp["age"]
        changes.append({"kind": "profile", "icon": "clock", "label": f"Age: {rp['age']}"})
    fam_changed = False
    for key in ("partner", "children"):
        if key in rp and rp[key] != old["profile"].get(key):
            new["profile"][key] = rp[key]
            fam_changed = True
    if fam_changed:
        who = search.family_phrase(new["profile"].get("partner"), new["profile"].get("children"))
        changes.append({"kind": "profile", "icon": "family", "label": f"Moving with {who}"})
    if rp.get("visa_type") and rp["visa_type"] != old["profile"].get("visa_type"):
        new["profile"]["visa_type"] = rp["visa_type"]
        changes.append({"kind": "filter", "icon": "target", "label": f"Visa type: {rp['visa_type']}"})
    if rp.get("require_pr") and not old["profile"].get("require_pr"):
        new["profile"]["require_pr"] = True
        changes.append({"kind": "filter", "icon": "pr", "label": "Must lead to permanent residency"})

    diff = old["profile"].get("max_difficulty") or ""
    if has(text, V["any_difficulty"]) and diff:
        new["profile"]["max_difficulty"] = None
        changes.append({"kind": "filter", "icon": "difficulty", "label": "Any visa difficulty"})
    elif rp.get("max_difficulty") and rp["max_difficulty"] != diff:
        new["profile"]["max_difficulty"] = rp["max_difficulty"]
        changes.append({"kind": "filter", "icon": "difficulty", "label": f"Visa difficulty: {rp['max_difficulty'].lower()} or easier"})
    elif has(text, V["easier_visa"]) and diff != "Easy":
        step = DIFFICULTY_STEPS[DIFFICULTY_STEPS.index(diff) + 1]
        new["profile"]["max_difficulty"] = step
        changes.append({"kind": "filter", "icon": "difficulty", "label": f"Visa difficulty: {step.lower()} or easier"})

    # ---- how many to show ----
    n = old["top_n"]
    compare_top = re.search(V["compare_top"], text)
    if compare_top:
        pass                                    # "compare the top 3" is not "show 3"
    elif r["top_n"] and r["top_n"] != n:
        new["top_n"] = r["top_n"]
    elif has(text, V["show_more"]):
        new["top_n"] = min(10, n + 3)
    elif has(text, V["show_fewer"]):
        new["top_n"] = max(3, n - 2)
    if new["top_n"] != n:
        changes.append({"kind": "top_n", "icon": "top", "label": f"Showing {new['top_n']} countries"})

    # ---- rank before and after ----
    before_rank = _ranked_names(old)
    after_rank = _ranked_names(new)
    top_before, top_after = before_rank[:old["top_n"]], after_rank[:new["top_n"]]

    m = compare_top
    if m:
        k = NUM_WORDS.get(m.group(1)) or int(m.group(1))
        pick = after_rank[:max(2, min(3, k))]
        if len(pick) >= 2:
            actions.append({"type": "compare", "countries": pick})
    elif len(mentioned) >= 2:
        actions.append({"type": "compare", "countries": [names[c] for c in mentioned[:3]]})
    elif len(mentioned) == 1:
        actions.append({"type": "open", "country": names[mentioned[0]]})
    if r.get("similar_to"):
        actions.append({"type": "open", "country": r["similar_to"]})

    hits = search.visa_search(prompt, None if new["region"] == "All regions" else new["region"],
                              countries=mentioned)
    reply = _reply(changes, actions, top_before, top_after, new)
    outcome = _reply([], actions, top_before, top_after, new, outcome_only=bool(changes))
    return {"state": new, "changes": changes, "actions": actions, "reply": reply, "outcome": outcome, "visa_hits": hits,
            "top": top_after, "previous_top": top_before}


def _reply(changes, actions, before, after, state, outcome_only=False) -> str:
    """The full reply; with outcome_only, just how the list moved (the UI shows the changes as chips)."""
    parts = []
    if changes:
        parts.append("Changed: " + "; ".join(c["label"] for c in changes) + ".")
    if (changes or outcome_only) and after:
        if before and after[0] != before[0]:
            parts.append(f"{after[0]} is now #1 (was {before[0]}).")
        else:
            parts.append(f"{after[0]} stays #1.")
        new_in = [c for c in after if c not in before]
        out = [c for c in before if c not in after]
        if new_in and len(new_in) == len(after):
            parts.append(f"Your top {len(after)} is now: {', '.join(after)}.")
        else:
            if new_in:
                parts.append(f"New in your top {len(after)}: {', '.join(new_in)}.")
            if out:
                parts.append(f"Dropped out: {', '.join(out)}.")
    elif (changes or outcome_only) and not after:
        parts.append("No country passes all of that now. Try “any difficulty” or “anywhere”, or say “undo”.")
    for a in actions:
        if a["type"] == "open":
            parts.append(f"Opening {a['country']}.")
        elif a["type"] == "compare":
            parts.append(f"Comparing {', '.join(a['countries'])}.")
    if not parts and outcome_only:
        return ""
    if not parts:
        return ("I didn't catch a change to make. Try “cheaper”, “safer”, “warmer”, “what about Asia?”, "
                "“drop Japan”, “easier visas”, “why Portugal?” or “undo”.")
    return " ".join(parts)
