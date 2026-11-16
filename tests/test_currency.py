"""Display currencies (data/currencies.json) and the ≈ estimate markers sent to the page."""

import json
from pathlib import Path

from pipeline import currency

DATA = Path(__file__).resolve().parent.parent / "data"


def test_currencies_file_matches_its_sources():
    assert json.loads((DATA / "currencies.json").read_text(encoding="utf-8")) == json.loads(json.dumps(currency.build()))


def test_daily_rates_win_and_annual_rates_fill_the_rest():
    out = currency.build()
    assert out["rates"]["EUR"]["basis"] == "daily"
    assert out["rates"]["USD"] == {"usd_per_unit": 1.0, "basis": "dollar"}
    pkr = out["rates"]["PKR"]
    assert pkr["basis"] == "annual" and pkr["year"] >= 2024
    assert 250 < 1 / pkr["usd_per_unit"] < 320            # rupees per dollar, a sanity range
    assert out["countries"]["PAK"] == "PKR" and out["countries"]["DEU"] == "EUR"


def test_stale_rates_are_left_out(tmp_path):
    (tmp_path / "manual").mkdir()
    (tmp_path / "manual" / "currency.csv").write_text("country_code,currency\nAAA,XAA\nBBB,XBB\n")
    (tmp_path / "manual" / "fx_annual.csv").write_text(
        "# test\ncountry_code,year,lcu_per_usd\nAAA,2025,10\nBBB,2017,5\n")
    (tmp_path / "fx.json").write_text(json.dumps({"date": "2026-01-01", "source": "https://x", "usd_per_unit": {"USD": 1.0}}))
    out = currency.build(tmp_path)
    assert out["rates"]["XAA"]["usd_per_unit"] == 0.1
    assert "XBB" not in out["rates"] and "BBB" not in out["countries"]


def test_meta_sends_currencies_estimates_and_demonyms():
    import app
    m = app.meta()
    assert "PKR" in m["currencies"]["rates"]
    assert set(m["estimated"]["TWN"]) >= {"salary", "healthcare"}      # Taiwan has no World Bank data
    assert all(k in {*app.FACTORS, "salary_money", "rent_money"} for ks in m["estimated"].values() for k in ks)
    assert next(n for n in m["nationalities"] if n["code"] == "PAK")["demonym"] == "Pakistani"
