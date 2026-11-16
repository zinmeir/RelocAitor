"""
relocaitor/immigration/store.py — Files under data/immigration/ and the build that keeps them in step.

    records.json        every route with a value, status and source per field, and its rule_version
    changes.json        every detected change: previous and new value, source, date, verification status
    sources.json        the official source registry (one entry per publisher)
    updates.json        approved updates (applied by pipeline/visa_details.py on top of the research record)
    verifications.json  human sign-offs, one per (route, field, value)
    page_hashes.json    what each official page looked like when last monitored
    proposals/          proposed updates waiting for review
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import records as R
from relocaitor import paths

ROOT = paths.ROOT
DATA = ROOT / "data"
DIR = DATA / "immigration"


def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_visas(data_dir: Path = DATA) -> dict:
    return _read(data_dir / "visas.json", {})


def load(name: str, default=None, d: Path = DIR):
    return _read(d / f"{name}.json", [] if default is None else default)


def save(name: str, obj, d: Path = DIR) -> None:
    _write(d / f"{name}.json", obj)


def build(today: str = None, data_dir: Path = DATA, d: Path = DIR, write: bool = True) -> dict:
    """Rebuild records.json from visas.json; log what changed since the last build."""
    today = today or date.today().isoformat()
    previous = load("records", {}, d).get("routes")
    current = R.build_records(load_visas(data_dir), load("updates", d=d), load("verifications", d=d))
    changes = R.detect_changes(previous, current, today)
    R.apply_versions(previous, current, changes)
    out = {"about": "Built by `python -m relocaitor.immigration build` from data/visas.json, updates.json and verifications.json. "
                    "Do not edit by hand.",
           "routes": current}
    if write:
        save("records", out, d)
        log = load("changes", d=d)
        known = {c["id"] for c in log}
        save("changes", log + [c for c in changes if c["id"] not in known], d)
        save("sources", build_sources(load_visas(data_dir), load("sources", d=d), load("updates", d=d)), d)
    return {"routes": len(current), "changes": changes}


def is_up_to_date(data_dir: Path = DATA, d: Path = DIR) -> bool:
    """True when records.json already reflects visas.json, updates and verifications (for CI)."""
    stored = load("records", {}, d).get("routes") or {}
    current = R.build_records(load_visas(data_dir), load("updates", d=d), load("verifications", d=d))
    strip = lambda recs: {k: {**v, "rule_version": None} for k, v in recs.items()}   # noqa: E731
    return strip(stored) == strip(current)


# ---------------------------------------------------------------------------
# Official source registry
# ---------------------------------------------------------------------------
SECONDARY_HOSTS = {"en.wikipedia.org"}


def build_sources(visas: dict, existing: list, updates: list = ()) -> list:
    """One entry per publisher (host). Kind and access are derived; notes a person adds are kept."""
    keep = {s["id"]: s for s in existing}
    hosts = {}

    def add(url: str, country: str, route: str = None):
        host = urlparse(url).hostname
        if not host:
            return
        h = hosts.setdefault(host, {"id": host, "urls": set(), "countries": set(), "routes": set()})
        h["urls"].add(url)
        h["countries"].add(country)
        if route:
            h["routes"].add(route)

    for code, entry in visas.items():
        if entry.get("official_url"):
            add(entry["official_url"], code)
        if entry.get("citizenship", {}).get("source"):
            add(entry["citizenship"]["source"], code)
        if entry.get("in_demand", {}).get("source"):
            add(entry["in_demand"]["source"], code)
        for v in entry["visas"]:
            for u in v.get("sources", []):
                add(u, code, R.route_id(code, v["name"]))
    for u in updates:
        for url in u["sources"]:
            add(url, u["route"].split("-")[0], u["route"])
    out = []
    for host, h in sorted(hosts.items()):
        prev = keep.get(host, {})
        out.append({
            "id": host,
            "kind": "third_party" if host in SECONDARY_HOSTS else "official",
            "access": prev.get("access", "manual"),       # manual | api | feed: how updates may be read
            "notes": prev.get("notes", ""),
            "countries": sorted(h["countries"]),
            "routes": sorted(h["routes"]),
            "urls": sorted(h["urls"]),
        })
    return out
