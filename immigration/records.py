"""
immigration/records.py — Versioned immigration route records with a status on every field.

    build(visas, updates, verifications, previous, today) -> (records, changes)

A record is derived from data/visas.json (the file the app already reads), the approved updates
(data/immigration/updates.json) and the human verification log (verifications.json). Nothing is
typed into the records by hand, so they can't drift from what the eligibility engine uses.

Statuses, strictest first:
- verified     a person signed off this exact value against the official source (verifications.json)
- sourced      read from an official page named in the record, not yet signed off. This includes all
               research done by an AI: an interpretation is never "verified" on its own.
- third_party  from a secondary source (e.g. Wikipedia's naturalisation table)
- estimated    curated before per-field sources were recorded, or an editorial judgement
- unknown      no value
- outdated     sourced or verified, but checked longer ago than the field's freshness window
               (computed when read, because it depends on today's date)
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Optional

from .catalogue import FIELDS, RESEARCHED_KEYS, EDITABLE_KEYS, value_of


def route_id(country: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{country}-{slug}"


def value_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _update_provenance(updates: list) -> dict:
    """{(route_id, field): {"source": [...], "checked": date, "by": name}} from approved updates (latest wins)."""
    out = {}
    for u in sorted(updates, key=lambda u: u["checked"]):
        for key in u["changes"]:
            out[(u["route"], EDITABLE_KEYS[key])] = {"sources": u["sources"], "checked": u["checked"],
                                                     "approved_by": u["approved_by"]}
    return out


def _field_status(field, value, visa: dict, entry: dict, rid: str, prov: dict, verified: dict) -> dict:
    if value is None:
        return {"status": "unknown"}
    v = verified.get((rid, field.name))
    if v and v["value_hash"] == value_hash(value):
        return {"status": "verified", "sources": v["sources"], "checked": v["date"],
                "verified_by": v["by"], "verified_on": v["date"]}
    up = prov.get((rid, field.name))
    researched = (visa.get("sources") and visa.get("checked")
                  and (field.key in RESEARCHED_KEYS
                       or (field.name == "pr_pathway" and any(k in visa for k in ("years_to_pr", "pr_note")))
                       or (field.name == "processing_time")))
    if field.name == "citizenship_pathway":
        base = {"status": "third_party" if value.get("source_kind") == "secondary" else "sourced",
                "sources": [value["source"]], "checked": value.get("checked")}
    elif up:
        base = {"status": "sourced", "sources": up["sources"], "checked": up["checked"]}
    elif researched:
        base = {"status": "sourced", "sources": visa["sources"], "checked": visa["checked"]}
    else:
        base = {"status": "estimated",
                "note": "Editorial rating" if field.name == "difficulty"
                        else "Curated before per-field sources were recorded; re-check against the official page"}
    if v:
        base["note"] = f"A verification from {v['date']} no longer matches this value"
    return base


def build_records(visas: dict, updates: list = (), verifications: list = ()) -> dict:
    prov = _update_provenance(list(updates))
    verified = {}
    for v in sorted(verifications, key=lambda v: v["date"]):
        verified[(v["route"], v["field"])] = v
    records = {}
    for code, entry in visas.items():
        for visa in entry["visas"]:
            rid = route_id(code, visa["name"])
            fields = {}
            for f in FIELDS:
                value = value_of(f, visa, entry)
                fields[f.name] = {"value": value, **_field_status(f, value, visa, entry, rid, prov, verified)}
            records[rid] = {"id": rid, "country": code, "name": visa["name"], "category": visa["type"],
                            "official_source": entry.get("official_url"), "fields": fields}
    return records


# ---------------------------------------------------------------------------
# Versions and change detection
# ---------------------------------------------------------------------------
def _kind(field: str, old, new) -> tuple:
    """Brief §2.3 categories, plus a direction for numbers."""
    direction = None
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        direction = "increased" if new > old else "decreased"
    if field == "fees" and isinstance(old, dict) and isinstance(new, dict) and old.get("currency") == new.get("currency"):
        a, b = old.get("amount"), new.get("amount")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
            direction = "increased" if b > a else "decreased"
    kind = {"min_income": "income_requirement", "min_savings": "savings_requirement",
            "investment": "investment_requirement", "fees": "application_fee",
            "processing_time": "processing_time", "pr_pathway": "permanent_residency_rules",
            "citizenship_pathway": "citizenship_rules", "nationality_restrictions": "nationality_eligibility",
            "age": "age_requirement", "dependants": "dependants", "occupations": "eligible_occupations",
            "education": "education_requirement", "work_experience": "experience_requirement",
            "language": "language_requirement",
            "sponsorship": "sponsorship"}.get(field, "other")
    return kind, direction


def detect_changes(previous: Optional[dict], current: dict, today: str) -> list:
    """Compare two sets of records. Only values count: a status change (e.g. a sign-off) is not a rule change."""
    if not previous:
        return []
    changes = []
    for rid, rec in current.items():
        old = previous.get(rid)
        if old is None:
            changes.append({"route": rid, "kind": "new_pathway", "field": None, "previous": None,
                            "new": rec["name"], "detected": today})
            continue
        for name, f in rec["fields"].items():
            before = (old["fields"].get(name) or {}).get("value")
            if before != f["value"]:
                kind, direction = _kind(name, before, f["value"])
                changes.append({"route": rid, "kind": kind, "direction": direction, "field": name,
                                "previous": before, "new": f["value"], "sources": f.get("sources", []),
                                "detected": today})
    for rid, old in previous.items():
        if rid not in current:
            changes.append({"route": rid, "kind": "removed_or_suspended", "field": None,
                            "previous": old["name"], "new": None, "detected": today})
    for c in changes:
        c["verification"] = "pending"
        c["id"] = value_hash([c["route"], c["field"], c["previous"], c["new"], c["detected"]])
    return changes


def apply_versions(previous: Optional[dict], current: dict, changes: list) -> dict:
    """rule_version: 1 for a new route, +1 whenever any of its values changed."""
    changed = {c["route"] for c in changes}
    for rid, rec in current.items():
        before = (previous or {}).get(rid, {}).get("rule_version", 0)
        rec["rule_version"] = before + 1 if (rid in changed or before == 0) else before
    return current


# ---------------------------------------------------------------------------
# Reading: statuses that depend on today's date, and summaries
# ---------------------------------------------------------------------------
def status_on(field_rec: dict, field_name: str, today: date) -> str:
    from .catalogue import BY_NAME
    st = field_rec["status"]
    checked = field_rec.get("checked")
    if st in ("verified", "sourced") and checked:
        age = (today - date.fromisoformat(checked)).days
        if age > BY_NAME[field_name].fresh_days:
            return "outdated"
    return st


def with_current_status(rec: dict, today: date) -> dict:
    out = json.loads(json.dumps(rec))
    for name, f in out["fields"].items():
        f["status"] = status_on(f, name, today)
    out["summary"] = summarize(out)
    return out


def summarize(rec: dict) -> dict:
    counts = {}
    for f in rec["fields"].values():
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    checked = sorted(f["checked"] for f in rec["fields"].values() if f.get("checked"))
    return {"counts": counts, "fields": len(rec["fields"]), "last_checked": checked[-1] if checked else None}
