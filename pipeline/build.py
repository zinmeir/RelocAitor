"""
build.py — Turn raw source data into data/countries.csv, data/provenance.csv
and data/SOURCES.md. Works offline from the files under data/.

    python -m pipeline build            # write the dataset
    python -m pipeline build --check    # only verify the committed dataset is up to date
    python -m pipeline report           # what changed vs the editorial dataset
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import clusters as ml_clusters
from . import impute as ml_impute
from .sources import (
    COLD_SPAN_C, COLUMN_METHODS, HOT_SPAN_C, IDEAL_TEMP_C, NATIVE_ENGLISH, SOURCES, SPECIAL_COLUMNS,
)

DATA = Path(__file__).resolve().parent.parent / "data"
# A country without editorial values is ranked only when it has at least this many of the
# measured indicators below (and an income figure): enough real data that estimates stay a minority.
CORE_INDICATORS = ["NY.GNP.PCAP.CD", "PRICE_LEVEL", "SL.UEM.TOTL.ZS", "SL.EMP.VULN.ZS", "VC.IHR.PSRC.P5",
                   "UHC_INDEX_REPORTED", "SP.DYN.LE00.IN", "IT.NET.USER.ZS", "GPI"]
MIN_MEASURED = 6
METRICS = ["average_salary", "cost_of_living", "pr_ease", "job_market", "language_barrier",
           "climate", "safety", "healthcare", "english", "internet"]
OUTPUT_COLUMNS = (["country_name", "country_code", "region"] + METRICS +
                  ["salary_usd_month", "rent_usd_month", "gni_per_capita_usd", "price_level",
                   "avg_temp_c", "main_city"])


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, comment="#")


def load_world(data_dir: Path = DATA) -> pd.DataFrame:
    """data/world.csv: every country the app knows about (code, name, region, capital…)."""
    return _read_csv(data_dir / "world.csv", ).astype({"m49": str}).set_index("country_code")


def load_indicator(source_id: str, data_dir: Path = DATA) -> pd.DataFrame:
    """[country_code, year, value] for one source id."""
    spec = SOURCES[source_id]
    if spec["kind"] == "worldbank":
        return _read_csv(data_dir / "raw" / "worldbank" / f"{source_id}.csv")
    if spec["kind"] == "who":
        return _read_csv(data_dir / "raw" / "who" / f"{source_id}.csv")
    df = _read_csv(data_dir / spec["file"])
    value_col = "score" if "score" in df else "avg_temp_c"
    year = df["year"] if "year" in df else np.nan
    return pd.DataFrame({"country_code": df["country_code"], "year": year, "value": df[value_col]})


def load_all(data_dir: Path = DATA) -> dict:
    out = {sid: load_indicator(sid, data_dir) for sid, s in SOURCES.items() if s["kind"] != "editorial"}
    out["PRICE_LEVEL"] = price_level(out)
    return out


MAX_YEAR_GAP = 1


def price_level(ind: dict) -> pd.DataFrame:
    """
    Consumer price level vs the US (1.0 = US prices):
      preferred: private-consumption PPP factor ÷ exchange rate, when both are within a year;
      fallback:  economy-wide level = GDP per capita in US$ ÷ GDP per capita in PPP $.
    Mixing years breaks under high inflation (Argentina 2021 PPP vs 2025 exchange rate gives 0.03).
    """
    cons = ind["PA.NUS.PRVT.PP"].merge(ind["PA.NUS.FCRF"], on="country_code", suffixes=("_ppp", "_fx"))
    cons = cons[(cons["year_ppp"] - cons["year_fx"]).abs() <= MAX_YEAR_GAP]
    cons = pd.DataFrame({"country_code": cons["country_code"], "year": cons[["year_ppp", "year_fx"]].min(axis=1),
                         "value": cons["value_ppp"] / cons["value_fx"], "basis": "consumption"})
    gdp = ind["NY.GDP.PCAP.CD"].merge(ind["NY.GDP.PCAP.PP.CD"], on="country_code", suffixes=("_usd", "_ppp"))
    gdp = pd.DataFrame({"country_code": gdp["country_code"], "year": gdp[["year_usd", "year_ppp"]].min(axis=1),
                        "value": gdp["value_usd"] / gdp["value_ppp"], "basis": "gdp"})
    gdp = gdp[~gdp["country_code"].isin(cons["country_code"])]
    return pd.concat([cons, gdp], ignore_index=True)


# ---------------------------------------------------------------------------
# Scaling
# ---------------------------------------------------------------------------

def robust_scale(values: pd.Series, transform: str = "linear", higher_is_better: bool = True,
                 lo_q: float = 0.05, hi_q: float = 0.95) -> pd.Series:
    """Clip to the 5th–95th percentile, min-max to 0–1, optionally log first and invert."""
    v = values.astype(float)
    if transform == "log":
        v = np.log(v.clip(lower=0) + 0.5)
    lo, hi = v.quantile(lo_q), v.quantile(hi_q)
    if hi - lo < 1e-12:
        scaled = pd.Series(1.0, index=v.index)
    else:
        scaled = ((v.clip(lo, hi) - lo) / (hi - lo))
    return scaled if higher_is_better else 1.0 - scaled


def fmt(v: float) -> str:
    v = float(v)
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.3g}"


def climate_comfort(temp_c: float) -> float:
    if temp_c is None or (isinstance(temp_c, float) and math.isnan(temp_c)):
        return float("nan")
    d = temp_c - IDEAL_TEMP_C
    span = COLD_SPAN_C if d < 0 else HOT_SPAN_C
    return max(0.0, 1.0 - abs(d) / span)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def coverage(data_dir: Path = DATA) -> pd.DataFrame:
    """Per country in world.csv: how many core indicators have real data, and whether it is ranked."""
    world = load_world(data_dir)
    editorial = _read_csv(data_dir / "editorial.csv").set_index("country_code")
    ind = load_all(data_dir)
    have = pd.DataFrame({sid: world.index.isin(ind[sid].dropna(subset=["value"])["country_code"])
                         for sid in CORE_INDICATORS}, index=world.index)
    out = pd.DataFrame({"measured": have.sum(axis=1), "has_income": have["NY.GNP.PCAP.CD"],
                        "editorial": world.index.isin(editorial.index)}, index=world.index)
    out["included"] = out["editorial"] | (out["has_income"] & (out["measured"] >= MIN_MEASURED))
    return out


def included_codes(data_dir: Path = DATA) -> list:
    """Countries that get ranked, in world.csv order (alphabetical by name), editorial countries first
    in their existing order so the 66-country dataset stays byte-identical."""
    cov = coverage(data_dir)
    editorial = list(_read_csv(data_dir / "editorial.csv")["country_code"])
    extra = [c for c in cov.index[cov["included"]] if c not in editorial]
    return editorial + extra


@lru_cache(maxsize=4)
def _imputation(data_dir: str):
    """ML gap filling (cached per data folder: cross-validation takes a few seconds)."""
    codes = included_codes(Path(data_dir))
    editorial = _read_csv(Path(data_dir) / "editorial.csv").set_index("country_code").reindex(codes)
    return ml_impute.impute(load_all(Path(data_dir)), editorial, exclude={"EF_EPI": NATIVE_ENGLISH})


def _regional_median(out: pd.DataFrame, column: str, region: str, have: list):
    pool = out.loc[[c for c in have if out.loc[c, "region"] == region], column].dropna()
    if pool.empty:
        pool = out.loc[have, column].dropna()
    return round(float(pool.median()), 2)


def build(data_dir: Path = DATA):
    """Returns (countries DataFrame, provenance DataFrame)."""
    codes = included_codes(data_dir)
    world = load_world(data_dir)
    editorial = _read_csv(data_dir / "editorial.csv").set_index("country_code").reindex(codes)
    has_editorial = set(editorial.dropna(how="all").index)
    ind = load_all(data_dir)
    imputed, cv_r2 = _imputation(str(Path(data_dir).resolve()))

    basis = ind["PRICE_LEVEL"].set_index("country_code")["basis"]

    def label_of(sid, code):
        if sid == "PRICE_LEVEL" and code in basis.index:
            return f"PRICE_LEVEL({basis[code]})"
        return sid

    def series(source_id, use_ml=True):
        df = ind[source_id].drop_duplicates("country_code").set_index("country_code")
        vals, years = df["value"].reindex(codes), df["year"].reindex(codes)
        if use_ml:
            for code, v in imputed.get(source_id, {}).items():
                if pd.isna(vals[code]):
                    vals[code], years[code] = v, ML_YEAR
        return vals, years

    out = pd.DataFrame(index=codes)
    out["country_name"] = world["country_name"].reindex(codes)
    out["region"] = world["region"].reindex(codes)
    prov = []
    pending = []   # (code, column, why) filled with regional medians once every computed value exists

    def fallback(code, column, why):
        """Editorial value if this country has one, otherwise a regional median (filled at the end)."""
        if code in has_editorial and pd.notna(editorial.loc[code, column]):
            out.loc[code, column] = editorial.loc[code, column]
            record(code, column, editorial.loc[code, column], "editorial-fallback", why)
        else:
            out.loc[code, column] = np.nan
            pending.append((code, column, why))

    def record(code, column, value, method, detail):
        prov.append({"country_code": code, "column": column, "value": value, "method": method, "detail": detail})

    # ---- standard composite columns ----
    for column, spec in COLUMN_METHODS.items():
        parts, weights, details = [], [], []
        for sid, w, transform, hib in spec["components"]:
            vals, years = series(sid)
            scaled = robust_scale(vals.dropna(), transform, hib).reindex(codes)
            parts.append(scaled)
            weights.append(w)
            details.append((sid, vals, years))
        mat = pd.concat(parts, axis=1)
        wts = np.array(weights)
        have = mat.notna().to_numpy()
        num = np.nansum(mat.to_numpy() * wts, axis=1)
        den = (have * wts).sum(axis=1)
        combined = pd.Series(np.where(den > 0, num / np.where(den > 0, den, 1), np.nan), index=codes)

        for code in codes:
            used = [f"{label_of(sid, code)} {year_label(y, sid)}={fmt(v[code])}".replace(" =", "=")
                    for sid, v, yy in details for y in [yy[code]] if pd.notna(v[code])]
            ml_used = [sid for sid, v, yy in details if yy[code] == ML_YEAR]
            missing = [sid for sid, v, _ in details if pd.isna(v[code])]
            if pd.isna(combined[code]):
                fallback(code, column, "no source data: " + ", ".join(missing))
            else:
                out.loc[code, column] = round(float(combined[code]), 2)
                method = "ml-imputed" if ml_used else ("computed" if not missing else "computed-partial")
                detail = "; ".join(used) + (f" (missing: {', '.join(missing)})" if missing else "")
                if ml_used:
                    detail += " [ML: " + ", ".join(f"{s} CV R²={cv_r2[s]:.2f}" for s in ml_used) + "]"
                record(code, column, out.loc[code, column], method, detail)

    # ---- english ----
    ef_vals, ef_years = series("EF_EPI")
    ef_scaled = (0.05 + 0.85 * robust_scale(ef_vals.dropna(), "linear", True)).reindex(codes)
    for code in codes:
        if code in NATIVE_ENGLISH:
            v, method, detail = 1.0, "rule", "native English-speaking country"
        elif pd.notna(ef_scaled[code]):
            v, method, detail = round(float(ef_scaled[code]), 2), "computed", f"EF_EPI 2025={ef_vals[code]:.0f}"
        else:
            fallback(code, "english", "not ranked by EF EPI")
            continue
        out.loc[code, "english"] = v
        record(code, "english", v, method, detail)

    # ---- climate ----
    city = _read_csv(data_dir / SOURCES["CITY_TEMP"]["file"]).set_index("country_code")
    nat_vals, _ = series("NATIONAL_TEMP")
    for code in codes:
        if code in city.index:
            t, where = float(city.loc[code, "avg_temp_c"]), city.loc[code, "city"]
            src = "CITY_TEMP"
        elif pd.notna(nat_vals[code]):
            t, where, src = float(nat_vals[code]), "national average", "NATIONAL_TEMP"
        else:
            t, where, src = float("nan"), "", None
        out.loc[code, "avg_temp_c"] = t
        out.loc[code, "main_city"] = where
        if src:
            v = round(climate_comfort(t), 2)
            record(code, "climate", v, "computed", f"{src} {where}={t:.1f}°C")
            out.loc[code, "climate"] = v
        else:
            fallback(code, "climate", "no temperature data")

    # ---- editorial columns + raw figures ----
    gni, _ = series("NY.GNP.PCAP.CD", use_ml=False)       # raw figures: real data only
    price, _ = series("PRICE_LEVEL", use_ml=False)
    out["gni_per_capita_usd"] = gni.round(0)
    out["price_level"] = price.round(3)
    money_models = {col: money_model(editorial, gni, price, col) for col in ("salary_usd_month", "rent_usd_month")}
    for column in ("pr_ease", "salary_usd_month", "rent_usd_month"):
        for code in codes:
            if code in has_editorial:
                out.loc[code, column] = editorial.loc[code, column]
                record(code, column, editorial.loc[code, column], "editorial", SPECIAL_COLUMNS[column])
            elif column in money_models and money_models[column] and pd.notna(gni[code]) and pd.notna(price[code]):
                m = money_models[column]
                v = float(round(m["predict"](gni[code], price[code]), -1))
                out.loc[code, column] = v
                record(code, column, v, "ml-estimate",
                       f"predicted from income and prices (log-linear, CV R²={m['r2']:.2f}, "
                       f"fitted on {m['n']} countries with editorial figures)")
            else:
                pending.append((code, column, "no editorial value" if column == "pr_ease"
                                else "no income or price data to estimate from"))

    # ---- what nobody measures for this country: the median of its region ----
    for code, column, why in pending:
        have = [c for c in codes if pd.notna(out.loc[c, column]) and (c, column) not in {(p, q) for p, q, _ in pending}]
        v = _regional_median(out, column, out.loc[code, "region"], have)
        if column in ("salary_usd_month", "rent_usd_month"):
            v = float(round(v, -1))
        out.loc[code, column] = v
        record(code, column, v, "regional-median", f"{why}; median of {out.loc[code, 'region']} countries")
    for column in ("salary_usd_month", "rent_usd_month"):
        out[column] = out[column].astype(float).round().astype("Int64")
    for code in codes:
        out.loc[code, "language_barrier"] = round(1.0 - float(out.loc[code, "english"]), 2)
        record(code, "language_barrier", out.loc[code, "language_barrier"], "derived", "1 − english")

    out = out.reset_index().rename(columns={"index": "country_code"})[OUTPUT_COLUMNS]
    prov = pd.DataFrame(prov).sort_values(["country_code", "column"]).reset_index(drop=True)
    return out, prov


ML_YEAR = -1    # marker in the "year" slot for ML-imputed values
MONEY_MIN_R2 = 0.5


def money_model(editorial: pd.DataFrame, gni: pd.Series, price: pd.Series, column: str):
    """
    log(figure) ~ a + b·log(GNI per capita) + c·log(price level), fitted on countries that have an
    editorial figure. Used only for countries without one, and only if 5-fold CV R² ≥ MONEY_MIN_R2.
    Returns {"predict", "r2", "n"} or None.
    """
    df = pd.DataFrame({"y": editorial[column], "g": gni, "p": price}).dropna()
    df = df[(df["y"] > 0) & (df["g"] > 0) & (df["p"] > 0)]
    if len(df) < 20:
        return None
    X = np.column_stack([np.ones(len(df)), np.log(df["g"]), np.log(df["p"])])
    y = np.log(df["y"].to_numpy())
    rng = np.random.default_rng(0)
    order = rng.permutation(len(df))
    pred = np.empty(len(df))
    for k in range(5):
        hold = order[k::5]
        train = np.setdiff1d(order, hold)
        beta, *_ = np.linalg.lstsq(X[train], y[train], rcond=None)
        pred[hold] = X[hold] @ beta
    r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    if r2 < MONEY_MIN_R2:
        return None
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return {"predict": lambda g, p: float(np.exp(beta[0] + beta[1] * np.log(g) + beta[2] * np.log(p))),
            "r2": float(r2), "n": len(df)}


def year_label(y, sid) -> str:
    if y == ML_YEAR:
        return "ML"
    return str(int(y)) if pd.notna(y) else ""


def imputation_report(data_dir: Path = DATA) -> dict:
    imputed, r2 = _imputation(str(Path(data_dir).resolve()))
    return {
        "method": "Iterative imputation (MICE) with Bayesian ridge regression, standardized indicators, "
                  f"{ml_impute.FOLDS}-fold cross-validation per indicator",
        "min_r2": ml_impute.MIN_R2,
        "cv_r2": r2,
        "used": {sid: {c: round(v, 3) for c, v in d.items()} for sid, d in imputed.items()},
        "rejected": [sid for sid, v in r2.items() if v < ml_impute.MIN_R2],
    }


def sources_markdown(prov: pd.DataFrame, data_dir: Path = DATA) -> str:
    lines = ["# Data sources and methods",
             "",
             "Generated by `python -m pipeline build`. Do not edit by hand.",
             "",
             "## How each column is built", "",
             "| Column | Method |", "|---|---|"]
    for col, spec in COLUMN_METHODS.items():
        lines.append(f"| `{col}` | {spec['explain']} |")
    for col, text in SPECIAL_COLUMNS.items():
        lines.append(f"| `{col}` | {text} |")
    lines += ["", "Scaling: each indicator is clipped to its 5th–95th percentile across the dataset's "
              "countries and min-max scaled to 0–1, so one extreme country can't squash everyone else.",
              "", "## Sources", "", "| Id | Indicator | Publisher | Licence |", "|---|---|---|---|"]
    for sid, s in SOURCES.items():
        link = f"[{s['name']}]({s['url']})" if s["url"] else s["name"]
        lines.append(f"| `{sid}` | {link} | {s['publisher']} | {s['license']} |")
    counts = prov.groupby("method").size().to_dict()
    lines += ["", "## Coverage", "",
              f"{len(prov)} values: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + ".", "",
              "Values that fell back to the editorial dataset (no source had data):", ""]
    fb = prov[prov["method"] == "editorial-fallback"]
    for _, r in fb.iterrows():
        lines.append(f"- `{r['country_code']}` {r['column']}: {r['detail']}")
    if fb.empty:
        lines.append("- none")
    rep = imputation_report(data_dir)
    lines += ["", "## ML gap filling", "",
              f"{rep['method']}. A predicted value is used only when its indicator's cross-validated "
              f"R² is at least {rep['min_r2']} (1.0 = perfect, 0 = no better than the average).", "",
              "| Indicator | CV R² | Used? | Filled |", "|---|---|---|---|"]
    for sid, r2 in rep["cv_r2"].items():
        filled = ", ".join(f"{c}≈{fmt(v)}" for c, v in rep["used"].get(sid, {}).items()) or "–"
        lines.append(f"| `{sid}` | {r2:.2f} | {'yes' if r2 >= rep['min_r2'] else 'no'} | {filled} |")
    lines += ["", "Predictions are only as good as their inputs: Taiwan's income is inferred partly from the "
              "editorial salary estimate and is likely understated.", "",
              "Per-value detail (source, year, raw value) is in `data/provenance.csv`.", ""]
    return "\n".join(lines)


def write(data_dir: Path = DATA) -> tuple:
    countries, prov = build(data_dir)
    countries.to_csv(data_dir / "countries.csv", index=False)
    prov.to_csv(data_dir / "provenance.csv", index=False)
    (data_dir / "SOURCES.md").write_text(sources_markdown(prov, data_dir), encoding="utf-8")
    (data_dir / "ml").mkdir(exist_ok=True)
    (data_dir / "ml" / "imputation_report.json").write_text(
        json.dumps(imputation_report(data_dir), indent=1), encoding="utf-8")
    (data_dir / "ml" / "country_map.json").write_text(
        json.dumps(ml_clusters.build_map(countries), indent=1), encoding="utf-8")
    return countries, prov


def is_up_to_date(data_dir: Path = DATA) -> bool:
    countries, _ = build(data_dir)
    current = pd.read_csv(data_dir / "countries.csv")
    try:
        pd.testing.assert_frame_equal(countries.reset_index(drop=True), current, check_dtype=False, atol=1e-9)
    except AssertionError:
        return False
    map_file = data_dir / "ml" / "country_map.json"
    return map_file.exists() and json.loads(map_file.read_text()) == \
        json.loads(json.dumps(ml_clusters.build_map(countries)))


def report(data_dir: Path = DATA) -> str:
    """Compare the pipeline's output with the editorial (hand-made) dataset."""
    new, _ = build(data_dir)
    old = _read_csv(data_dir / "editorial.csv")
    m = old.merge(new, on="country_code", suffixes=("_old", "_new"))
    lines = ["Column changes vs the editorial dataset (mean |Δ| on the 0–1 scale, biggest movers):", ""]
    for col in ["average_salary", "cost_of_living", "job_market", "safety", "healthcare", "english",
                "internet", "climate"]:
        d = (m[f"{col}_new"] - m[f"{col}_old"])
        top = d.abs().sort_values(ascending=False).index[:3]
        movers = ", ".join(f"{m.loc[i, 'country_name_old']} {m.loc[i, col + '_old']:.2f}→{m.loc[i, col + '_new']:.2f}"
                           for i in top)
        lines.append(f"  {col:15} mean |Δ| {d.abs().mean():.2f}   {movers}")
    corr = new[METRICS].corr()
    lines += ["", "Correlation between columns (was 0.98 salary/cost, 0.93 salary/job, 0.86 safety/health):",
              f"  salary vs cost {corr.loc['average_salary', 'cost_of_living']:.2f}   "
              f"salary vs job {corr.loc['average_salary', 'job_market']:.2f}   "
              f"safety vs health {corr.loc['safety', 'healthcare']:.2f}"]
    return "\n".join(lines)
