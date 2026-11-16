"""Whole-world coverage: the country list, adding countries through the pipeline, and the live dataset."""

import csv
import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline import build as b
from pipeline import wiki

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REGIONS = {"North America", "South America", "Europe", "Asia", "Middle East", "Africa", "Oceania"}


def _world():
    return pd.read_csv(DATA / "world.csv", comment="#", dtype={"m49": str}, keep_default_na=False)


# ---------- the country list ----------

def test_world_list_covers_every_un_member_and_more():
    w = _world()
    assert len(w) == 196 and w["country_code"].is_unique and w["m49"].is_unique
    assert set(w["region"]) == REGIONS
    assert all(re.fullmatch(r"\d{3}", m) for m in w["m49"])
    assert {"TWN", "HKG", "PSE", "SSD", "TUV", "VAT"} - set(w["country_code"]) == {"VAT"}   # VAT is not a UN member


def test_map_knows_every_country_and_lexicon_names_them():
    codes = set(_world()["country_code"])
    for js in ("static/js/countries.js", "preview/countries_preview.js"):
        block = re.search(r"const M49_TO_ISO3 = \{(.*?)\};", (ROOT / js).read_text(), re.S).group(1)
        assert set(re.findall(r'"\d{3}": "([A-Z]{3})"', block)) == codes, js
    lex = json.loads((DATA / "search_lexicon.json").read_text(encoding="utf-8"))["countries"]
    assert set(lex) == codes


def test_prompts_understand_new_countries():
    import search
    from app import meta
    m = meta()
    for prompt, origin in [("I'm Kazakh, looking at Europe", "KAZ"), ("Ivorian passport", "CIV")]:
        assert search.interpret_rules(prompt, m, use_model=False, use_semantic=False)["profile"]["nationality"] == origin
    assert {n["code"] for n in m["nationalities"]} >= {"KAZ", "CIV", "FJI", "BOL"}


# ---------- adding countries through the pipeline ----------

@pytest.fixture(scope="module")
def world_dir(tmp_path_factory):
    """The committed data plus synthetic raw data for Fiji and Kazakhstan (full) and Cuba (too little)."""
    d = tmp_path_factory.mktemp("world") / "data"
    shutil.copytree(DATA, d)
    rng = np.random.default_rng(1)
    for f in list((d / "raw" / "worldbank").glob("*.csv")) + list((d / "raw" / "who").glob("*.csv")):
        df = pd.read_csv(f)
        med = df["value"].median()
        add = [(c, 2024, med * float(rng.uniform(0.7, 1.3))) for c in ("FJI", "KAZ")]
        if f.stem in ("NY.GNP.PCAP.CD", "SP.DYN.LE00.IN"):
            add.append(("CUB", 2024, med))
        pd.concat([df, pd.DataFrame(add, columns=df.columns)]).to_csv(f, index=False)
    return d


def test_countries_with_enough_data_are_added_and_flagged(world_dir):
    cov = b.coverage(world_dir)
    assert cov.loc["FJI", "included"] and cov.loc["KAZ", "included"] and not cov.loc["CUB", "included"]
    countries, prov = b.build(world_dir)
    assert len(countries) == 68 and list(countries["country_code"][:66]) == list(pd.read_csv(DATA / "editorial.csv")["country_code"])
    p = prov[prov["country_code"] == "FJI"].set_index("column")
    assert p.loc["salary_usd_month", "method"] == "ml-estimate"            # predicted from income + prices
    assert p.loc["pr_ease", "method"] == "regional-median"                 # no public index
    assert p.loc["average_salary", "method"] == "computed"                 # measured data stays measured
    row = countries.set_index("country_code").loc["KAZ"]
    assert all(0 <= row[c] <= 1 for c in b.METRICS)
    assert row["salary_usd_month"] > 0 and row["region"] == "Asia"


def test_existing_countries_are_unchanged_by_new_ones_being_known():
    # Knowing about 196 countries doesn't change the 66 until real data for others arrives.
    assert b.is_up_to_date()


def test_money_model_is_cross_validated():
    ed = pd.read_csv(DATA / "editorial.csv").set_index("country_code")
    countries = pd.read_csv(DATA / "countries.csv").set_index("country_code")
    m = b.money_model(ed, countries["gni_per_capita_usd"], countries["price_level"], "salary_usd_month")
    assert m and m["r2"] >= b.MONEY_MIN_R2 and m["n"] >= 60
    assert 2000 < m["predict"](60000, 1.0) < 6000                           # a rich, US-priced country


# ---------- countries whose visas aren't researched ----------

def test_unresearched_countries_stay_when_a_visa_filter_is_on(monkeypatch):
    import engine
    import visas
    from eligibility import Profile
    data = dict(visas._load())
    data.pop("KEN")
    monkeypatch.setattr(visas, "_load", lambda: data)
    ranked = engine.rank({}, None, Profile(nationality="IND", only_qualifying=True, monthly_income=10))
    ken = ranked[ranked["country_code"] == "KEN"]
    assert len(ken) == 1 and not ken["visas_researched"].iloc[0] and ken["qualifying_visas"].iloc[0] == 0


# ---------- reading the published tables ----------

GPI_HTML = """<table class="wikitable sortable"><tr><th>Country</th><th>2025 score</th><th>2026 rank</th><th>2026 score</th></tr>
{rows}</table>"""


def _rows(items, fmt):
    return "".join(fmt.format(*it) for it in items)


def test_wiki_parser_reads_gpi_latest_year_and_skips_unknowns():
    names = wiki.name_index(list(csv.DictReader(l for l in open(DATA / "world.csv", encoding="utf-8") if not l.startswith("#"))))
    rows = _rows([("Iceland", "1.10", "1", "1.095"), ("Côte d'Ivoire[a]", "2.0", "90", "1.98"),
                  ("Narnia", "1.5", "2", "1.4"), ("Fiji", "1.9", "70", "9.9")],
                 "<tr><td>{0}</td><td>{1}</td><td>{2}</td><td>{3}</td></tr>")
    got = wiki.parse(wiki.TABLES["GPI"], GPI_HTML.format(rows=rows), names)
    assert got == {"ISL": (1.095, "Iceland"), "CIV": (1.98, "Côte d'Ivoire[a]")}   # Fiji out of range, Narnia unknown


def test_wiki_extends_manual_files_without_touching_existing_rows(tmp_path):
    d = tmp_path / "data"
    (d / "manual").mkdir(parents=True)
    shutil.copy(DATA / "world.csv", d / "world.csv")
    shutil.copy(DATA / "manual" / "climate_national.csv", d / "manual" / "climate_national.csv")
    before = (d / "manual" / "climate_national.csv").read_text(encoding="utf-8")
    w = _world()
    rows = "".join(f"<tr><td>{n}</td><td>{20 + (i % 9) * 0.5:.1f}</td></tr>" for i, n in enumerate(w["country_name"]))
    page = f'<table class="wikitable"><tr><th>Country</th><th>Average yearly temperature (°C)</th></tr>{rows}</table>'
    rep = wiki.extend_manual("NATIONAL_TEMP", page, d, today="2026-11-16")
    after = (d / "manual" / "climate_national.csv").read_text(encoding="utf-8")
    old_rows = [l for l in before.splitlines() if not l.startswith("#")]
    assert after.splitlines()[-len(old_rows) - rep["added"]:][:len(old_rows)] == old_rows   # untouched, in order
    have = {l.split(",")[0] for l in old_rows[1:]}
    assert rep["added"] == len(set(w["country_code"]) - have)
    assert "added automatically by `python -m pipeline fetch` on 2026-11-16" in after


def test_wiki_refuses_a_table_that_does_not_parse(tmp_path):
    d = tmp_path / "data"
    (d / "manual").mkdir(parents=True)
    shutil.copy(DATA / "world.csv", d / "world.csv")
    rep = wiki.extend_manual("EF_EPI", "<p>No tables here</p>", d)
    assert rep["added"] == 0 and "only 0 rows parsed" in rep["error"]


# ---------- the live dataset (whatever size it is) ----------

def test_live_dataset_is_sane():
    c = pd.read_csv(DATA / "countries.csv")
    prov = pd.read_csv(DATA / "provenance.csv")
    assert len(c) >= 66 and c["country_code"].is_unique
    assert set(c["country_code"]) <= set(_world()["country_code"])
    assert c[b.METRICS].notna().all().all() and ((c[b.METRICS] >= 0) & (c[b.METRICS] <= 1)).all().all()
    assert set(prov["method"]) <= {"computed", "computed-partial", "derived", "rule", "ml-imputed", "editorial",
                                   "editorial-fallback", "ml-estimate", "regional-median"}
