"""The data pipeline: reproducibility, scaling, fallbacks, provenance and the fetchers."""

import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline import build as b
from pipeline import fetch as f
from pipeline.sources import COLUMN_METHODS, NATIVE_ENGLISH, SOURCES
from relocaitor import paths

DATA = paths.DATA


def test_committed_dataset_is_reproducible():
    """countries.csv must be exactly what the pipeline builds from the committed sources."""
    assert b.is_up_to_date(), "Run: python -m pipeline build"


def test_every_value_has_provenance():
    countries, prov = b.build()
    metrics = b.METRICS + ["salary_usd_month", "rent_usd_month"]
    assert len(prov) == len(countries) * len(metrics)
    assert set(prov["method"]) <= {"computed", "computed-partial", "editorial", "editorial-fallback",
                                   "derived", "rule", "ml-imputed"}
    assert prov["detail"].str.len().min() > 0


def test_most_scores_come_from_real_sources():
    _, prov = b.build()
    sourced_cols = list(COLUMN_METHODS) + ["english", "climate"]
    s = prov[prov["column"].isin(sourced_cols)]
    share = s["method"].isin(["computed", "computed-partial", "rule", "ml-imputed"]).mean()
    assert share > 0.95, share


def test_scores_are_in_range():
    countries, _ = b.build()
    for col in b.METRICS:
        assert countries[col].between(0, 1).all(), col


def test_robust_scale():
    s = pd.Series(list(range(1, 60)) + [10_000])            # ~dataset size, one extreme outlier
    scaled = b.robust_scale(s)
    assert scaled.min() == 0 and scaled.max() == 1
    assert 0.4 < scaled.iloc[29] < 0.6                       # the outlier doesn't squash everyone else
    inv = b.robust_scale(s, higher_is_better=False)
    assert (inv + scaled - 1).abs().max() < 1e-12
    assert b.robust_scale(pd.Series([5, 5, 5])).eq(1).all()


def test_log_transform_spreads_low_values():
    s = pd.Series([1000, 2000, 4000, 8000, 64000])
    lin, log = b.robust_scale(s, lo_q=0, hi_q=1), b.robust_scale(s, "log", lo_q=0, hi_q=1)
    assert log.iloc[1] - log.iloc[0] > lin.iloc[1] - lin.iloc[0]


def test_climate_comfort():
    assert b.climate_comfort(21) == 1
    assert b.climate_comfort(7) == 0 and b.climate_comfort(0) == 0
    assert b.climate_comfort(28) > b.climate_comfort(14)      # heat penalised less than cold
    assert math.isnan(b.climate_comfort(float("nan")))


def test_english_rules():
    countries, prov = b.build()
    c = countries.set_index("country_code")
    for code in NATIVE_ENGLISH & set(c.index):
        assert c.loc[code, "english"] == 1.0
    assert c.loc["NLD", "english"] == 0.9                     # top EF score maps to 0.90
    assert (c["language_barrier"] - (1 - c["english"])).abs().max() < 1e-9


def test_price_level_never_mixes_distant_years():
    ind = b.load_all()
    pl = b.price_level(ind).set_index("country_code")
    assert pl.loc["ARG", "basis"] == "gdp"                    # 2021 PPP vs 2025 FX would be nonsense
    assert pl.loc["SGP", "basis"] == "consumption"
    assert pl["value"].between(0.1, 2).all()


def test_missing_values_are_ml_imputed_only_when_validated():
    _, prov = b.build()
    p = prov.set_index(["country_code", "column"])
    twn = p.loc[("TWN", "healthcare")]
    assert twn["method"] == "ml-imputed" and "CV R²" in twn["detail"]
    assert p.loc[("HKG", "safety"), "method"] == "computed-partial"     # GPI fails validation: not imputed
    assert p.loc[("TWN", "english"), "method"] == "editorial-fallback"  # EF fails validation: not imputed
    rep = b.imputation_report()
    assert all(r >= rep["min_r2"] for sid, r in rep["cv_r2"].items() if sid in rep["used"])
    assert "SL.UEM.TOTL.ZS" in rep["rejected"]


def test_imputation_cross_validation_is_meaningful():
    rep = b.imputation_report()
    assert rep["cv_r2"]["NY.GNP.PCAP.CD"] > 0.8      # income is very predictable from the other indicators
    assert rep["cv_r2"]["UHC_INDEX_REPORTED"] > 0.6


def test_build_works_from_a_copy_of_the_data(tmp_path):
    """The build only reads data/, so it can run anywhere (CI, a fork, a new machine)."""
    shutil.copytree(DATA, tmp_path / "data")
    countries, _ = b.build(tmp_path / "data")
    original, _ = b.build()
    pd.testing.assert_frame_equal(countries, original)


def test_new_sources_reduce_overlap_between_factors():
    countries, _ = b.build()
    corr = countries[b.METRICS].corr()
    assert corr.loc["average_salary", "job_market"] < 0.85
    assert corr.loc["safety", "healthcare"] < 0.75


def test_sources_markdown_lists_everything():
    _, prov = b.build()
    md = b.sources_markdown(prov)
    for sid in SOURCES:
        assert f"`{sid}`" in md
    for col in COLUMN_METHODS:
        assert f"`{col}`" in md


# ---------------- fetchers (offline, with fake API responses) ----------------

def test_parse_worldbank_keeps_latest_non_null():
    payload = [{"page": 1}, [
        {"countryiso3code": "DEU", "date": "2025", "value": None},
        {"countryiso3code": "DEU", "date": "2024", "value": 55090},
        {"countryiso3code": "DEU", "date": "2023", "value": 55420},
        {"countryiso3code": "", "date": "2024", "value": 1},
    ]]
    assert f.parse_worldbank(payload) == [("DEU", 2024, 55090.0)]
    assert f.parse_worldbank([{"message": "error"}]) == []


def test_parse_who_filters_to_known_countries():
    payload = {"value": [
        {"SpatialDim": "DEU", "TimeDim": 2022, "NumericValue": 86},
        {"SpatialDim": "DEU", "TimeDim": 2023, "NumericValue": 87},
        {"SpatialDim": "WB_SSA", "TimeDim": 2023, "NumericValue": 40},
    ]}
    assert f.parse_who(payload, {"DEU"}) == [("DEU", 2023, 87.0)]


def test_fetch_all_writes_raw_files(tmp_path):
    calls = []

    def fake_get(url):
        calls.append(url)
        if "ghoapi" in url:
            return {"value": [{"SpatialDim": "AAA", "TimeDim": 2023, "NumericValue": 50}]}
        return [{}, [{"countryiso3code": "AAA", "date": "2024", "value": 2.5}]]

    counts = f.fetch_all(["AAA", "BBB"], data_dir=tmp_path, get=fake_get, pause=0)
    wb = [s for s, v in SOURCES.items() if v["kind"] == "worldbank"]
    assert set(counts) == set(wb) | {"UHC_INDEX_REPORTED"}
    assert pd.read_csv(tmp_path / "raw/worldbank/NY.GNP.PCAP.CD.csv").to_dict("records") == \
        [{"country_code": "AAA", "year": 2024, "value": 2.5}]
    assert all(len(u) < 400 for u in calls)                   # stays under URL-length limits


# ---------------- ML: clusters, PCA map, neighbours ----------------

def _map():
    import json
    return json.loads((DATA / "ml" / "country_map.json").read_text())


def test_country_map_is_complete():
    m = _map()
    countries = pd.read_csv(DATA / "countries.csv")
    assert set(m["countries"]) == set(countries["country_code"])
    assert m["k"] in range(3, 9)
    assert sum(c["size"] for c in m["clusters"]) == len(countries)
    assert len({c["name"] for c in m["clusters"]}) == m["k"]          # names are unique
    for code, p in m["countries"].items():
        assert code not in p["neighbors"] and len(p["neighbors"]) == 8
        assert p["distances"] == sorted(p["distances"])


def test_clustering_quality_is_reported_honestly():
    m = _map()
    assert m["silhouette_by_k"][str(m["k"])] == max(m["silhouette_by_k"].values())
    assert 0 < m["stability_ari"]["mean"] <= 1
    assert 0.5 < sum(m["explained_variance"]) <= 1


def test_clusters_and_neighbours_make_sense():
    m = _map()["countries"]
    gulf = {m[c]["cluster"] for c in ("ARE", "QAT", "SAU", "BHR")}
    assert len(gulf) == 1                                             # the Gulf states group together
    assert set(m["DEU"]["neighbors"][:3]) <= {"NLD", "BEL", "AUT", "DNK", "SWE", "FIN", "NOR", "CHE", "GBR", "FRA"}


def test_cluster_names_only_use_shared_traits():
    from pipeline.clusters import FEATURES, LABELS, MIN_AGREEMENT, standardize
    m = _map()
    z = standardize(pd.read_csv(DATA / "countries.csv").set_index("country_code"))
    label_to = {lab: (f, i == 0) for f, (hi, lo) in LABELS.items() for i, lab in enumerate((hi, lo))}
    for c in m["clusters"]:
        for part in c["name"].split(" · "):
            f, high = label_to[part]
            share = ((z.loc[c["members"], f] > 0) == high).mean()
            assert share >= MIN_AGREEMENT, (c["name"], part, share)
