"""Data integrity: catches typos and schema drift in the CSV / JSON files."""

from relocaitor.datasets import METRIC_COLUMNS, get_nationalities, get_regions, load_countries
from relocaitor.visas.eligibility import DIFFICULTY_RANK
from relocaitor.visas.catalog import VALID_PR, VISA_TYPES, _load


def test_country_count_and_uniqueness():
    df = load_countries()
    assert len(df) == 66
    assert df["country_code"].is_unique
    assert df["country_name"].is_unique


def test_metrics_are_normalized():
    df = load_countries()
    for col in METRIC_COLUMNS:
        assert df[col].between(0, 1).all(), col


def test_real_figures_are_positive():
    df = load_countries()
    assert (df["salary_usd_month"] > 0).all()
    assert (df["rent_usd_month"] > 0).all()


def test_seven_regions():
    assert len(get_regions()) == 7


def test_every_country_has_visa_entry():
    visas = _load()
    assert set(visas) == set(load_countries()["country_code"])


def test_visa_schema():
    allowed_types = set(VISA_TYPES)
    for code, entry in _load().items():
        assert entry["official_url"].startswith("https://"), code
        assert entry["visas"], f"{code} has no visas"
        for v in entry["visas"]:
            assert v["type"] in allowed_types, (code, v["name"])
            assert v["difficulty"] in DIFFICULTY_RANK, (code, v["name"])
            assert v["pr_route"] in VALID_PR, (code, v["name"], v["pr_route"])
            assert v["min_income"] >= 0 and v["min_investment"] >= 0
            assert v["summary"] and v["duration"]


def test_load_returns_independent_copies():
    a = load_countries()
    a.loc[0, "average_salary"] = -1
    assert load_countries().loc[0, "average_salary"] >= 0


def test_nationalities_include_non_destinations():
    codes = {n["code"] for n in get_nationalities()}
    assert {"PAK", "USA", "DEU"} <= codes
