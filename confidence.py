"""
confidence.py — How sure is this ranking?

Two sources of doubt, simulated together (Monte Carlo, SAMPLES scenarios):

1. Your weights are approximate. Nobody means "safety = 0.80" exactly, so each
   weight is jittered by about ±WEIGHT_SD.
2. The data is imperfect, and some numbers more than others. Each value is
   jittered by an amount that depends on where it came from (measured by an
   official source < ML-imputed < editorial estimate < flagged fallback), read
   from data/provenance.csv.

For every scenario the countries are re-ranked. The result says how often each
country comes #1 and makes the top N, its plausible rank range, and whether
neighbours in the ranking are effectively tied.

The random numbers come from mulberry32, a tiny generator that gives bit-for-bit
identical sequences in Python and JavaScript, so the static demo matches.
"""

from __future__ import annotations

import math

import numpy as np

from data import _provenance
from factors import FACTORS, FACTOR_KEYS

SAMPLES = 400
SEED = 20261116
WEIGHT_SD = 0.12
SQRT3 = math.sqrt(3.0)

# Standard deviation of the noise added to a 0–1 score, by provenance method.
DATA_SD = {
    "computed": 0.02, "computed-partial": 0.04, "derived": 0.03, "rule": 0.01,
    "ml-imputed": 0.08, "editorial": 0.08, "editorial-fallback": 0.15,
    "ml-estimate": 0.08, "regional-median": 0.15,
}
DEFAULT_SD = 0.08
# How much each method can be trusted, for the per-country reliability summary.
TRUST = {
    "computed": 1.0, "computed-partial": 0.85, "derived": 0.9, "rule": 1.0,
    "ml-imputed": 0.6, "editorial": 0.5, "editorial-fallback": 0.3,
    "ml-estimate": 0.5, "regional-median": 0.25,
}
METHOD_LABEL = {
    "computed": "measured", "computed-partial": "partly measured", "derived": "derived",
    "rule": "rule-based", "ml-imputed": "ML-imputed", "editorial": "an editorial estimate",
    "editorial-fallback": "a fallback estimate",
    "ml-estimate": "an ML estimate", "regional-median": "a regional median (no data)",
}
TIE_BAND = (0.35, 0.65)   # A ahead of B in 35–65% of scenarios → effectively tied


def mulberry32(seed: int, n: int) -> np.ndarray:
    """n uniforms in [0, 1), identical to the JavaScript mulberry32 with the same seed."""
    M = np.uint64(0xFFFFFFFF)
    a = (np.uint64(seed) + (np.arange(1, n + 1, dtype=np.uint64) * np.uint64(0x6D2B79F5))) & M
    a = a.astype(np.uint32)
    with np.errstate(over="ignore"):
        t = (a ^ (a >> np.uint32(15))) * (a | np.uint32(1))
        t = (t + (t ^ (t >> np.uint32(7))) * (t | np.uint32(61))) ^ t
        t = t ^ (t >> np.uint32(14))
    return t.astype(np.float64) / 4294967296.0


def _method(prov: dict, code: str, key: str) -> str:
    return prov.get(code, {}).get(FACTORS[key]["col"], {}).get("method", "editorial")


def reliability(code: str, weights: dict, prov: dict = None) -> dict:
    """Weighted share of this country's score that rests on measured data."""
    prov = _provenance() if prov is None else prov
    used = {k: max(0.0, float(weights.get(k, 0.0))) for k in FACTOR_KEYS}
    total = 0.0
    for k in FACTOR_KEYS:
        total = total + used[k]
    if total == 0:
        used, total = {k: 1.0 for k in FACTOR_KEYS}, float(len(FACTOR_KEYS))
    value = 0.0
    weak = []
    for k in FACTOR_KEYS:
        m = _method(prov, code, k)
        value = value + (used[k] / total) * TRUST.get(m, 0.5)
        if TRUST.get(m, 0.5) < 0.85 and used[k] > 0:
            weak.append({"factor": k, "method": m, "share": used[k] / total,
                         "text": f"{FACTORS[k]['label']} is {METHOD_LABEL.get(m, m)}"})
    weak.sort(key=lambda x: -x["share"])
    level = "High" if value >= 0.85 else "Medium" if value >= 0.65 else "Low"
    measured = sum(1 for k in FACTOR_KEYS if TRUST.get(_method(prov, code, k), 0.5) >= 0.85)
    return {"value": value, "level": level, "measured": measured, "factors": len(FACTOR_KEYS),
            "weak": weak[:3]}


def simulate(ranked_rows: list, weights: dict, top_n: int = 5, show: int = None) -> dict:
    """
    ranked_rows: the user's current ranking (dicts with country_code, country_name
    and the factor columns), best first. Returns rank statistics for the first
    `show` countries (default: top_n).
    """
    n = len(ranked_rows)
    show = min(n, show or top_n)
    if n == 0:
        return {"samples": SAMPLES, "countries": [], "verdict": None, "ties": []}
    prov = _provenance()
    K = len(FACTOR_KEYS)

    base_w = np.array([max(0.0, min(1.0, float(weights.get(k, 0.0)))) for k in FACTOR_KEYS])
    V = np.array([[(1.0 - float(r[FACTORS[k]["col"]])) if FACTORS[k]["invert"] else float(r[FACTORS[k]["col"]])
                   for k in FACTOR_KEYS] for r in ranked_rows])                       # n × K
    SD = np.array([[DATA_SD.get(_method(prov, r["country_code"], k), DEFAULT_SD) for k in FACTOR_KEYS]
                   for r in ranked_rows])

    block = K + n * K
    U = mulberry32(SEED, SAMPLES * block).reshape(SAMPLES, block)
    W = np.clip(base_w + ((U[:, :K] * 2.0 - 1.0) * WEIGHT_SD) * SQRT3, 0.0, 1.0)      # S × K
    D = U[:, K:].reshape(SAMPLES, n, K)
    X = np.clip(V + ((D * 2.0 - 1.0) * SD) * SQRT3, 0.0, 1.0)                          # S × n × K

    total = np.zeros(SAMPLES)
    for k in range(K):
        total = total + W[:, k]
    zero = total == 0
    W[zero] = 1.0
    total[zero] = float(K)
    raw = np.zeros((SAMPLES, n))
    for k in range(K):
        raw = raw + (W[:, k] / total)[:, None] * X[:, :, k]

    order = np.argsort(-raw, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[np.arange(SAMPLES)[:, None], order] = np.arange(1, n + 1)[None, :]          # S × n

    lo_i, mid_i, hi_i = SAMPLES // 20, SAMPLES // 2, SAMPLES - 1 - SAMPLES // 20
    countries = []
    for j in range(show):
        r = np.sort(ranks[:, j])
        row = ranked_rows[j]
        countries.append({
            "country": row["country_name"], "country_code": row["country_code"], "rank": j + 1,
            "p_first": int((ranks[:, j] == 1).sum()) / SAMPLES,
            "p_top": int((ranks[:, j] <= top_n).sum()) / SAMPLES,
            "rank_lo": int(r[lo_i]), "rank_median": int(r[mid_i]), "rank_hi": int(r[hi_i]),
            "reliability": reliability(row["country_code"], weights, prov),
        })

    ties = []
    for j in range(show - 1):
        p = int((ranks[:, j] < ranks[:, j + 1]).sum()) / SAMPLES
        if TIE_BAND[0] <= p <= TIE_BAND[1]:
            ties.append({"a": ranked_rows[j]["country_name"], "b": ranked_rows[j + 1]["country_name"],
                         "rank": j + 1, "p_a_ahead": p})

    first = countries[0]
    if n == 1:
        verdict = {"level": "only", "text": f"{first['country']} is the only country that passes your filters."}
    elif first["p_first"] >= 0.7:
        verdict = {"level": "clear",
                   "text": f"{first['country']} is #1 in {_pct(first['p_first'])} of {SAMPLES} what-if scenarios: a clear lead."}
    elif first["p_first"] >= 0.4:
        verdict = {"level": "likely",
                   "text": f"{first['country']} is #1 in {_pct(first['p_first'])} of scenarios: likely, but not certain."}
    else:
        rivals = [c["country"] for c in sorted(countries[1:], key=lambda c: -c["p_first"])
                  if c["p_first"] >= 0.15][:2]
        verdict = {"level": "close",
                   "text": f"Too close to call: {first['country']} is #1 in only {_pct(first['p_first'])} of scenarios"
                           + (f", with {' and '.join(rivals)} close behind." if rivals else ".")}
    return {"samples": SAMPLES, "weight_sd": WEIGHT_SD, "countries": countries,
            "verdict": verdict, "ties": ties}


def _pct(p: float) -> str:
    """Whole percent, rounding halves up (identical in the JS port: counts are /400 → exact quarters)."""
    return f"{int(math.floor(p * 100 + 0.5))}%"
