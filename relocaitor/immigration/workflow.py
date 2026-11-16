"""
relocaitor/immigration/workflow.py — How a new immigration figure gets into RelocAitor.

1. propose   Someone (a person, a script, or an AI research run) writes a proposal file in
             data/immigration/proposals/: the route, the new values, the official page and the date
             it was read, and the exact wording relied on. Nothing changes yet.
2. review    `python -m relocaitor.immigration review` shows each proposal as a diff against the current data,
             with problems (unknown route, unknown field, non-official source, missing evidence).
3. approve   `python -m relocaitor.immigration approve FILE --by NAME` is the human step. It appends the change to
             updates.json and records a verification for each field (the approver checked the source).
4. publish   `python -m pipeline.visa_details` merges updates into visas.json, then
             `python -m relocaitor.immigration build` versions the routes and logs the changes.

A proposal from an AI run can be reviewed and approved like any other, but approval is a person's
name: the verification log never says "verified by" a model.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import records as R
from . import store
from .catalogue import EDITABLE_KEYS

SECONDARY = store.SECONDARY_HOSTS


def load_proposals(d: Path = store.DIR) -> list:
    folder = d / "proposals"
    if not folder.exists():
        return []
    out = []
    for p in sorted(folder.glob("*.json")):
        prop = json.loads(p.read_text(encoding="utf-8"))
        prop["_file"] = p.name
        out.append(prop)
    return out


def check(proposal: dict, visas: dict) -> dict:
    """Problems that block approval, and the diff it would make."""
    problems, diff = [], []
    routes = {R.route_id(c, v["name"]): (c, v) for c, e in visas.items() for v in e["visas"]}
    rid = proposal.get("route")
    if rid not in routes:
        problems.append(f"Unknown route '{rid}'")
    for key in proposal.get("changes", {}):
        if key not in EDITABLE_KEYS:
            problems.append(f"'{key}' can't be changed through a proposal")
    srcs = proposal.get("sources") or []
    if not srcs:
        problems.append("No source")
    for u in srcs:
        host = urlparse(u).hostname or ""
        if not u.startswith("https://"):
            problems.append(f"Source is not https: {u}")
        if host in SECONDARY:
            problems.append(f"{host} is a secondary source, not an official one")
    try:
        date.fromisoformat(proposal.get("checked", ""))
    except ValueError:
        problems.append("'checked' must be the date the page was read (YYYY-MM-DD)")
    if not (proposal.get("evidence") or "").strip():
        problems.append("No evidence: quote the wording on the official page that supports each value")
    if rid in routes:
        _, visa = routes[rid]
        for key, new in proposal.get("changes", {}).items():
            if visa.get(key) != new:
                diff.append({"key": key, "previous": visa.get(key), "new": new})
        if not diff and not problems:
            problems.append("No difference from the current data")
    return {"problems": problems, "diff": diff}


def approve(proposal_file: str, by: str, today: str = None, d: Path = store.DIR, data_dir: Path = store.DATA) -> dict:
    """The human step: record the update and a verification for each changed field."""
    if not by or not by.strip():
        raise ValueError("Approval needs the reviewer's name")
    if by.strip().lower() in {"claude", "gpt", "llm", "ai", "model", "bot"}:
        raise ValueError("Approval must be by a person; a model can propose but not verify")
    today = today or date.today().isoformat()
    path = d / "proposals" / proposal_file
    prop = json.loads(path.read_text(encoding="utf-8"))
    visas = store.load_visas(data_dir)
    result = check(prop, visas)
    if result["problems"]:
        raise ValueError("; ".join(result["problems"]))
    updates = store.load("updates", d=d)
    updates.append({"route": prop["route"], "changes": prop["changes"], "sources": prop["sources"],
                    "checked": prop["checked"], "evidence": prop["evidence"],
                    "proposed_by": prop.get("proposed_by", ""), "approved_by": by.strip(), "approved": today})
    store.save("updates", updates, d)
    # One verification per catalogue field touched, against the value the field will have after merging.
    code, visa = next((c, v) for c, e in visas.items() for v in e["visas"] if R.route_id(c, v["name"]) == prop["route"])
    after = {**visa, **prop["changes"]}
    from .catalogue import BY_NAME, value_of
    entry = {**visas[code], "visas": []}
    ver = store.load("verifications", d=d)
    for field in sorted({EDITABLE_KEYS[k] for k in prop["changes"]}):
        ver.append({"route": prop["route"], "field": field, "value_hash": R.value_hash(value_of(BY_NAME[field], after, entry)),
                    "by": by.strip(), "date": today, "sources": prop["sources"]})
    store.save("verifications", ver, d)
    path.rename(path.with_suffix(".approved"))
    return {"route": prop["route"], "diff": result["diff"]}


def verify(route: str, field: str, by: str, source: str, today: str = None, d: Path = store.DIR,
           data_dir: Path = store.DATA) -> dict:
    """Sign off an existing value without changing it (a reviewer re-read the official page)."""
    if by.strip().lower() in {"claude", "gpt", "llm", "ai", "model", "bot"}:
        raise ValueError("Verification must be by a person")
    if not source.startswith("https://") or (urlparse(source).hostname or "") in SECONDARY:
        raise ValueError("Verify against an official https page")
    recs = R.build_records(store.load_visas(data_dir), store.load("updates", d=d), store.load("verifications", d=d))
    if route not in recs or field not in recs[route]["fields"]:
        raise ValueError(f"Unknown route or field: {route} {field}")
    value = recs[route]["fields"][field]["value"]
    if value is None:
        raise ValueError("There is no value to verify; propose one instead")
    ver = store.load("verifications", d=d)
    entry = {"route": route, "field": field, "value_hash": R.value_hash(value), "by": by.strip(),
             "date": today or date.today().isoformat(), "sources": [source]}
    store.save("verifications", ver + [entry], d)
    return entry
