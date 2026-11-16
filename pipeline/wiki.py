"""
pipeline/wiki.py — Extend the hand-copied tables in data/manual/ to every country,
from the same published tables they were copied from (via Wikipedia's page HTML).

    python -m pipeline fetch           # runs this after the World Bank / WHO download

Rules, so a parsing mistake can't quietly change the existing data:
- Rows already in a data/manual/*.csv file are never changed. Only countries that
  are missing get added, each marked with the retrieval date.
- A table is used only if enough rows parse and every value is in a plausible
  range; otherwise nothing is written and the reason is printed.
- Country names are matched against data/world.csv (names, aliases, common
  Wikipedia spellings). Unmatched rows are skipped.

Only the standard library is used.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import re
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
PAGE_HTML = "https://en.wikipedia.org/api/rest_v1/page/html/{title}"

# Wikipedia spellings that differ from world.csv names and aliases.
EXTRA_NAMES = {
    "czechia": "CZE", "turkiye": "TUR", "republic of korea": "KOR", "korea south": "KOR", "korea north": "PRK",
    "democratic peoples republic of korea": "PRK", "congo democratic republic of the": "COD",
    "democratic republic of the congo": "COD", "congo republic of the": "COG", "republic of congo": "COG",
    "congo": "COG", "east timor": "TLS", "state of palestine": "PSE", "palestinian territories": "PSE",
    "federated states of micronesia": "FSM", "macau": None, "kosovo": None, "russian federation": "RUS",
    "viet nam": "VNM", "lao pdr": "LAO", "iran islamic republic of": "IRN", "syrian arab republic": "SYR",
    "united states of america": "USA", "uk": "GBR", "great britain": "GBR", "hong kong sar": "HKG",
    "hong kong china": "HKG", "taiwan roc": "TWN", "republic of china": "TWN", "brunei darussalam": "BRN",
    "swaziland": "SWZ", "cabo verde": "CPV", "burma": "MMR",
}

# source id -> how to read it. "value" picks the column; "range" rejects implausible values.
TABLES = {
    "GPI": {"title": "Global_Peace_Index", "file": "manual/gpi.csv", "columns": ["country_code", "country", "score", "year"],
            "value": ("score", "latest_year"), "range": (1.0, 4.5)},
    "EF_EPI": {"title": "EF_English_Proficiency_Index", "file": "manual/ef_epi.csv",
               "columns": ["country_code", "country", "score", "year"], "value": ("score",), "range": (300, 750)},
    "NATIONAL_TEMP": {"title": "List_of_countries_by_average_yearly_temperature", "file": "manual/climate_national.csv",
                      "columns": ["country_code", "country", "avg_temp_c"], "value": ("temperature", "°c", "average"),
                      "range": (-25, 32)},
    "CITY_TEMP": {"title": "List_of_cities_by_average_temperature", "file": "manual/climate_city.csv",
                  "columns": ["country_code", "city", "avg_temp_c"], "value": ("year",), "range": (-25, 35),
                  "city": True},
}
MIN_ROWS = 40


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", html.unescape(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\[[^\]]*\]", "", s)            # footnote markers
    s = re.sub(r"\([^)]*\)", "", s)             # "(Turkey)" style notes
    s = s.replace("&", "and").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"^the ", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def name_index(world_rows: list) -> dict:
    idx = {}
    for r in world_rows:
        names = [r["country_name"]] + [a for a in (r.get("aliases") or "").split("|") if a]
        for n in names:
            idx[norm(n)] = r["country_code"]
    for k, v in EXTRA_NAMES.items():
        idx.setdefault(norm(k), v)
    return idx


class _Tables(HTMLParser):
    """Collects every <table class="wikitable…"> as rows of cell text (header rows included)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._depth, self._row, self._cell, self._skip = [], 0, None, None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            if self._depth or "wikitable" in (a.get("class") or ""):
                self._depth += 1
                if self._depth == 1:
                    self.tables.append([])
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("sup", "style") and self._cell is not None:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "table" and self._depth:
            self._depth -= 1
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None
        elif tag in ("sup", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def tables(page_html: str) -> list:
    p = _Tables()
    p.feed(page_html)
    return [t for t in p.tables if len(t) >= 3]


def _number(text: str):
    t = text.replace("−", "-").replace("–", "-").replace(",", "")
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", t)
    return float(m.group(1)) if m else None


def _value_column(header: list, keys: tuple):
    h = [c.lower() for c in header]
    if "latest_year" in keys:
        years = [int(y) for c in h for y in re.findall(r"\b(20\d\d)\b", c)]
        if years:
            latest = str(max(years))
            for i, c in enumerate(h):
                if latest in c and keys[0] in c:
                    return i
            for i, c in enumerate(h):
                if latest in c:
                    return i
    for key in keys:
        if key == "latest_year":
            continue
        for i, c in enumerate(h):
            if key in c:
                return i
    return None


def parse(spec: dict, page_html: str, names: dict, capitals: dict = None) -> dict:
    """{country_code: (value, label)} from the first table(s) that fit the spec."""
    lo, hi = spec["range"]
    found = {}
    for t in tables(page_html):
        header = t[0]
        hl = [c.lower() for c in header]
        ci = next((i for i, c in enumerate(hl) if "country" in c or "nation" in c), None)
        vi = _value_column(header, spec["value"])
        city_i = next((i for i, c in enumerate(hl) if c.startswith("city")), None) if spec.get("city") else None
        if ci is None or vi is None or (spec.get("city") and city_i is None):
            continue
        for row in t[1:]:
            if len(row) <= max(ci, vi, city_i or 0):
                continue
            code = names.get(norm(row[ci]))
            val = _number(row[vi])
            if not code or val is None or not (lo <= val <= hi):
                continue
            label = row[city_i] if city_i is not None else row[ci]
            if spec.get("city") and code in found:
                # prefer the capital when a country has several cities
                if capitals and norm(label) == norm(capitals.get(code, "")):
                    found[code] = (val, label)
                continue
            found.setdefault(code, (val, label))
    return found


def _fetch(title: str) -> str:
    url = PAGE_HTML.format(title=urllib.parse.quote(title))
    req = urllib.request.Request(url, headers={"User-Agent": "RelocAitor data pipeline (github.com/zinmeir/relocator)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def _read_manual(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    comments = [l for l in lines if l.startswith("#")]
    rows = list(csv.DictReader([l for l in lines if not l.startswith("#")]))
    return comments, rows


def extend_manual(source_id: str, page_html: str, data_dir: Path = DATA, today: str = None) -> dict:
    """Add rows for countries missing from one data/manual file. Returns a small report."""
    spec = TABLES[source_id]
    with open(data_dir / "world.csv", encoding="utf-8") as f:
        world = list(csv.DictReader(l for l in f if not l.startswith("#")))
    names = name_index(world)
    capitals = {r["country_code"]: r["capital"] for r in world}
    found = parse(spec, page_html, names, capitals)
    if len(found) < MIN_ROWS:
        return {"source": source_id, "added": 0, "error": f"only {len(found)} rows parsed; table layout may have changed"}

    path = data_dir / spec["file"]
    comments, rows = _read_manual(path)
    have = {r["country_code"] for r in rows}
    fields = list(rows[0].keys()) if rows else spec["columns"]
    today = today or dt.date.today().isoformat()
    year = rows[0].get("year") if rows and "year" in rows[0] else str(dt.date.today().year)
    added = []
    for code, (val, label) in sorted(found.items()):
        if code in have:
            continue
        row = {"country_code": code}
        if "country" in fields:
            row["country"] = next(r["country_name"] for r in world if r["country_code"] == code)
        if "city" in fields:
            row["city"] = label
        row["score" if "score" in fields else "avg_temp_c"] = f"{val:g}"
        if "year" in fields:
            row["year"] = year
        added.append({k: row.get(k, "") for k in fields})
    if added:
        note = f"# Rows for {len(added)} more countries added automatically by `python -m pipeline fetch` on {today}."
        with open(path, "w", encoding="utf-8", newline="") as f:
            for c in comments:
                if not c.startswith("# Rows for ") or "added automatically" not in c:
                    f.write(c + "\n")
            f.write(note + "\n")
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows + added)
    return {"source": source_id, "added": len(added), "parsed": len(found)}


def fetch_all(data_dir: Path = DATA, get=_fetch) -> list:
    out = []
    for sid, spec in TABLES.items():
        try:
            out.append(extend_manual(sid, get(spec["title"]), data_dir))
        except OSError as err:
            out.append({"source": sid, "added": 0, "error": f"download failed: {err}"})
    return out
