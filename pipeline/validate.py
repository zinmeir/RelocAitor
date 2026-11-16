"""
pipeline/validate.py — Check every data file against its schema, then check the
files agree with each other.

    python -m pipeline.validate        # exit 1 and list every problem if anything is wrong

Schemas live in data/schemas/*.schema.json (JSON Schema 2020-12, readable by any
language). They catch typos ("ammount"), wrong types, impossible values and
missing sources. The cross-file checks catch what a schema can't:

- every fee currency has an exchange rate
- immigration/records.json matches visas.json, approved updates and sign-offs; no sign-off is by a model
- currencies.json matches its sources (fx.json, data/manual/currency.csv, fx_annual.csv)
- every job field used by a visa or shortage list exists in occupations.json
- every country code in visas.json and cities.json is a country in the dataset
- every rule in rules.json names fields the visas and profile actually have
- data_version is not older than the newest "checked" date
- the visa research record is merged (pipeline.visa_details --check)

Needs the dev dependency `jsonschema`; the running app does not.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FILES = {"visas": "visas.json", "cities": "cities.json", "occupations": "occupations.json",
         "fx": "fx.json", "version": "version.json", "rules": "rules.json", "lexicon": "search_lexicon.json",
         "currencies": "currencies.json",
         "imm_records": "immigration/records.json", "imm_changes": "immigration/changes.json",
         "imm_sources": "immigration/sources.json", "imm_updates": "immigration/updates.json",
         "imm_verifications": "immigration/verifications.json",
         "transitions": "transitions.json", "tax": "finance/tax_oecd.json"}


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def schema_errors() -> list:
    from jsonschema import Draft202012Validator
    out = []
    for key, fname in FILES.items():
        schema_path = DATA / "schemas" / f"{key}.schema.json"
        if not schema_path.exists() or not (DATA / fname).exists():
            continue
        validator = Draft202012Validator(_load(f"schemas/{key}.schema.json"))
        for err in sorted(validator.iter_errors(_load(fname)), key=lambda e: list(e.absolute_path)):
            where = "/".join(str(p) for p in err.absolute_path) or "(top level)"
            out.append(f"{fname}: {where}: {err.message}")
    return out


def cross_file_errors() -> list:
    out = []
    visas, cities, occ, fx, version = (_load(FILES[k]) for k in ("visas", "cities", "occupations", "fx", "version"))
    with open(DATA / "world.csv", encoding="utf-8") as f:
        codes = {r["country_code"] for r in csv.DictReader(l for l in f if not l.startswith("#"))}
    with open(DATA / "world.csv", encoding="utf-8") as f:
        world_rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    regions = {"North America", "South America", "Europe", "Asia", "Middle East", "Africa", "Oceania"}
    m49 = [r["m49"] for r in world_rows]
    for r in world_rows:
        if r["region"] not in regions:
            out.append(f"world.csv: {r['country_code']}: unknown region '{r['region']}'")
        if not (len(r["m49"]) == 3 and r["m49"].isdigit()) or m49.count(r["m49"]) > 1:
            out.append(f"world.csv: {r['country_code']}: M49 code '{r['m49']}' is not a unique 3-digit code")
    with open(DATA / "countries.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] not in codes:
                out.append(f"countries.csv: {r['country_code']}: not in world.csv")
    fields, rates = set(occ["fields"]), set(fx["usd_per_unit"])
    if (DATA / "transitions.json").exists():
        from immigration.records import route_id as _rid
        ids = {_rid(c, v["name"]) for c, e in visas.items() for v in e["visas"]}
        for p in _load("transitions.json")["pathways"]:
            for st in p["steps"]:
                if st.get("route") and st["route"] not in ids:
                    out.append(f"transitions.json: {p['id']}: unknown route {st['route']}")
            if not any(st.get("pr") for st in p["steps"]):
                out.append(f"transitions.json: {p['id']}: no step leads to permanent residence")
    if (DATA / "immigration" / "records.json").exists():
        from immigration import store as imm
        if not imm.is_up_to_date():
            out.append("immigration/records.json is out of date: run python -m immigration build")
        robots = {"claude", "gpt", "llm", "ai", "model", "bot"}
        for v in imm.load("verifications"):
            if v["by"].strip().lower() in robots:
                out.append(f"immigration/verifications.json: {v['route']} {v['field']} was 'verified' by a model")
    if (DATA / "currencies.json").exists():
        from .currency import build as build_currencies
        cur = _load("currencies.json")
        for code in cur["countries"]:
            if code not in codes:
                out.append(f"currencies.json: {code}: not a country in world.csv")
        if cur != json.loads(json.dumps(build_currencies(DATA))):
            out.append("currencies.json is out of date: run python -m pipeline currencies")
    from data import get_nationalities
    passports = {n["code"] for n in get_nationalities()}

    dates = [fx["date"], cities["checked"]]
    for code, entry in visas.items():
        if code not in codes:
            out.append(f"visas.json: {code}: not a country in world.csv")
        if "in_demand" in entry:
            dates.append(entry["in_demand"]["checked"])
            for k in set(entry["in_demand"]["fields"]) - fields:
                out.append(f"visas.json: {code}/in_demand: unknown job field '{k}'")
        if "citizenship" in entry:
            dates.append(entry["citizenship"]["checked"])
        names = [v["name"] for v in entry["visas"]]
        for dup in {n for n in names if names.count(n) > 1}:
            out.append(f"visas.json: {code}: two visas called '{dup}'")
        for v in entry["visas"]:
            where = f"visas.json: {code}/{v['name']}"
            if "checked" in v:
                dates.append(v["checked"])
            if "fee" in v and v["fee"]["currency"] not in rates:
                out.append(f"{where}: no exchange rate for {v['fee']['currency']} in fx.json")
            for k in set(v.get("fields") or []) - fields:
                out.append(f"{where}: unknown job field '{k}'")
            if v.get("age_min") is not None and v.get("age_max") is not None and v["age_min"] > v["age_max"]:
                out.append(f"{where}: age_min is above age_max")
            for c in set(v.get("restricted_to") or []) - passports:
                out.append(f"{where}: restricted_to has unknown passport '{c}'")
    for code in cities["cities"]:
        if code not in codes:
            out.append(f"cities.json: {code}: not a country in world.csv")
    lex = _load("search_lexicon.json")["countries"]
    for code in set(lex) - codes:
        out.append(f"search_lexicon.json: countries/{code}: not in world.csv")
    for code in codes - set(lex):
        out.append(f"search_lexicon.json: no entry for {code} (add its name so prompts can mention it)")
    if version["data_version"] < max(dates):
        out.append(f"version.json: data_version {version['data_version']} is older than the newest check ({max(dates)})")

    rules_path = DATA / FILES["rules"]
    if rules_path.exists():
        from eligibility import Profile
        profile_fields = set(Profile.__dataclass_fields__)
        visa_fields = set(_load("schemas/visas.schema.json")["$defs"]["visa"]["properties"])
        for r in _load(FILES["rules"])["visa_rules"]:
            for side, allowed in (("visa", visa_fields), ("profile", profile_fields)):
                name = r.get(side)
                if name and name.split(".")[0] not in allowed:
                    out.append(f"rules.json: rule '{r['id']}' reads unknown {side} field '{name}'")

    # The prompt patterns must compile in both languages that read them.
    import re
    import shutil
    import subprocess
    personal = _load("search_lexicon.json").get("personal", {})
    pats = {k: v for k, v in personal.items() if k in ("job_cue", "partner", "single", "children", "no_children", "age")}
    for k, pat in pats.items():
        try:
            re.compile(pat)
        except re.error as err:
            out.append(f"search_lexicon.json: personal/{k}: not a valid Python pattern ({err})")
    node = shutil.which("node")
    if node and pats:
        js = "const p=" + json.dumps(pats) + ";for(const [k,v] of Object.entries(p)){try{new RegExp(v)}catch(e){console.log(k+': '+e.message)}}"
        res = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
        out += [f"search_lexicon.json: personal/{line} (JavaScript)" for line in res.stdout.splitlines() if line.strip()]

    from pipeline import visa_details
    if json.dumps(visa_details.merged(), indent=2, ensure_ascii=False) + "\n" != (DATA / "visas.json").read_text(encoding="utf-8"):
        out.append("visas.json: out of date with pipeline/visa_details.py (run python -m pipeline.visa_details)")
    return out


def problems() -> list:
    return schema_errors() + cross_file_errors()


def main() -> int:
    found = problems()
    for p in found:
        print("✗", p)
    checked = [f for f in FILES.values() if (DATA / f).exists()]
    print(f"{len(found)} problem(s)" if found else f"All data files are valid ({', '.join(checked)}).")
    return 1 if found else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
