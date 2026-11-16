"""
impute.py — Machine-learning gap filling for missing source data.

Some countries are missing from some sources (Taiwan isn't in World Bank data;
WHO and the Global Peace Index don't cover Hong Kong; EF doesn't rank a few
small countries). Instead of falling straight back to hand-made values, the
pipeline predicts the missing raw indicator from everything else known about
the country, using multivariate iterative imputation (MICE: each indicator is
regressed on the others with Bayesian ridge regression, repeated until stable).

Every indicator is cross-validated before it's trusted: known values are hidden
fold by fold, re-predicted, and scored with R² (1.0 = perfect, 0 = no better
than guessing the average). Predictions are only used for indicators with
CV R² ≥ MIN_R2; otherwise the editorial fallback is kept. Results and scores
are recorded in data/provenance.csv and data/ml/imputation_report.json.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_R2 = 0.5
FOLDS = 5
SEED = 0

# Indicators that take part (log-transformed where the distribution is skewed).
FEATURES = {
    "NY.GNP.PCAP.CD": "log", "PRICE_LEVEL": "linear", "SL.UEM.TOTL.ZS": "linear",
    "SL.EMP.VULN.ZS": "linear", "VC.IHR.PSRC.P5": "log", "GPI": "linear",
    "UHC_INDEX_REPORTED": "linear", "SP.DYN.LE00.IN": "linear", "IT.NET.USER.ZS": "linear",
    "EF_EPI": "linear", "CITY_TEMP": "linear",
}
# Auxiliary predictors only (never imputed or reported): the editorial money estimates,
# available for every country, help place Taiwan economically.
AUX = {"salary_usd_month": "log", "rent_usd_month": "log"}


def _forward(v: pd.Series, how: str) -> pd.Series:
    return np.log(v.clip(lower=0) + 0.5) if how == "log" else v


def _inverse(v: np.ndarray, how: str) -> np.ndarray:
    return np.exp(v) - 0.5 if how == "log" else v


def _impute(matrix: pd.DataFrame) -> pd.DataFrame:
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401
    from sklearn.impute import IterativeImputer
    from sklearn.linear_model import BayesianRidge

    mu, sd = matrix.mean(), matrix.std().replace(0, 1)
    z = (matrix - mu) / sd
    imp = IterativeImputer(estimator=BayesianRidge(), max_iter=25, random_state=SEED,
                           sample_posterior=False, skip_complete=True)
    filled = pd.DataFrame(imp.fit_transform(z), index=matrix.index, columns=matrix.columns)
    return filled * sd + mu


def build_matrix(raw: dict, editorial: pd.DataFrame) -> pd.DataFrame:
    """Countries × indicators on the modelling scale (log where configured)."""
    codes = list(editorial.index)
    cols = {}
    for sid, how in FEATURES.items():
        s = raw[sid].drop_duplicates("country_code").set_index("country_code")["value"].reindex(codes)
        cols[sid] = _forward(s.astype(float), how)
    for col, how in AUX.items():
        cols[col] = _forward(editorial[col].astype(float), how)
    return pd.DataFrame(cols, index=codes)


def cross_validate(matrix: pd.DataFrame, exclude: dict = None) -> dict:
    """{indicator: R²} from K-fold masking of known values, one indicator at a time."""
    exclude = exclude or {}
    rng = np.random.default_rng(SEED)
    scores = {}
    for sid in FEATURES:
        known = [c for c in matrix.index[matrix[sid].notna()] if c not in exclude.get(sid, set())]
        order = rng.permutation(known)
        preds, truth = [], []
        for k in range(FOLDS):
            hold = order[k::FOLDS]
            m = matrix.copy()
            m.loc[hold, sid] = np.nan
            filled = _impute(m)
            preds += list(filled.loc[hold, sid])
            truth += list(matrix.loc[hold, sid])
        t, p = np.array(truth), np.array(preds)
        ss_res, ss_tot = ((t - p) ** 2).sum(), ((t - t.mean()) ** 2).sum()
        scores[sid] = round(float(1 - ss_res / ss_tot), 3) if ss_tot > 0 else 0.0
    return scores


def impute(raw: dict, editorial: pd.DataFrame, exclude: dict = None):
    """
    Returns (imputed raw values {sid: {code: value}}, cv R² {sid: r2}).
    Only indicators passing MIN_R2 are returned, and only for countries missing them.
    `exclude` = {sid: codes} that are missing by design (e.g. native-English countries for EF).
    """
    exclude = exclude or {}
    matrix = build_matrix(raw, editorial)
    filled = _impute(matrix)
    r2 = cross_validate(matrix, exclude)
    out = {}
    for sid, how in FEATURES.items():
        if r2[sid] < MIN_R2:
            continue
        missing = [c for c in matrix.index[matrix[sid].isna()] if c not in exclude.get(sid, set())]
        if missing:
            vals = _inverse(filled.loc[missing, sid].to_numpy(), how)
            out[sid] = {c: float(v) for c, v in zip(missing, vals)}
    return out, r2
