"""
clusters.py — Unsupervised learning over the country profiles.

1. Standardize the 9 factor scores (z-scores), so no factor dominates by scale.
2. PCA → 2 components: a "country landscape" map where nearby countries have
   similar profiles. Axes are labelled by their strongest loadings.
3. K-means for k = 3..8; k is chosen by silhouette score. Clusters are named
   automatically from their most distinctive factors (largest |centroid z|).
4. Stability: the clustering is re-run on 30 bootstrap resamples and compared
   with the adjusted Rand index (1.0 = identical groupings).
5. Nearest neighbours in the standardized space power "similar countries".

Output: data/ml/country_map.json (consumed by the app at runtime; no
scikit-learn needed outside the pipeline).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["average_salary", "cost_of_living", "pr_ease", "job_market", "climate",
            "safety", "healthcare", "english", "internet"]
K_RANGE = range(3, 9)
SEED = 0
N_NEIGHBOURS = 8
BOOTSTRAPS = 30

LABELS = {   # feature -> (label when high, label when low)
    "average_salary": ("High income", "Lower income"),
    "cost_of_living": ("Expensive", "Affordable"),
    "pr_ease": ("Easy PR", "Hard PR"),
    "job_market": ("Strong job market", "Weak job market"),
    "climate": ("Warm", "Cooler"),
    "safety": ("Very safe", "Less safe"),
    "healthcare": ("Great healthcare", "Weaker healthcare"),
    "english": ("English-friendly", "Little English"),
    "internet": ("Highly connected", "Less connected"),
}
AXIS_WORDS = {
    "average_salary": "income", "cost_of_living": "cost", "pr_ease": "PR ease", "job_market": "jobs",
    "climate": "warmth", "safety": "safety", "healthcare": "healthcare", "english": "English",
    "internet": "internet",
}


def standardize(df: pd.DataFrame) -> pd.DataFrame:
    x = df[FEATURES].astype(float)
    return (x - x.mean()) / x.std(ddof=0).replace(0, 1)


def _kmeans(z: np.ndarray, k: int, seed: int = SEED):
    from sklearn.cluster import KMeans
    return KMeans(n_clusters=k, n_init=20, random_state=seed).fit(z)


MIN_AGREEMENT = 0.75


def name_cluster(centroid_z: pd.Series, members_z: pd.DataFrame, taken: set) -> str:
    """
    Name from the cluster's most distinctive traits, using only traits that at
    least 75% of its members actually share (so a mostly-cold group containing
    Portugal isn't called "Cold").
    """
    agree = {f: float(((members_z[f] > 0) == (centroid_z[f] > 0)).mean()) for f in FEATURES}
    ranked = sorted(FEATURES, key=lambda f: -abs(centroid_z[f]) * agree[f])
    good = [f for f in ranked if agree[f] >= MIN_AGREEMENT] or ranked
    parts = [LABELS[f][0] if centroid_z[f] > 0 else LABELS[f][1] for f in good[:3]]
    name = " · ".join(parts[:2])
    if name in taken:
        name = " · ".join(parts)
    return name


def axis_label(loadings: pd.Series) -> str:
    top = loadings.abs().sort_values(ascending=False).index[:3]
    pos = [AXIS_WORDS[f] for f in top if loadings[f] > 0]
    neg = [AXIS_WORDS[f] for f in top if loadings[f] < 0]
    if pos and neg:
        return f"more {' & '.join(pos)} → (vs {' & '.join(neg)})"
    return f"more {' & '.join(pos or neg)} →"


def build_map(countries: pd.DataFrame) -> dict:
    from sklearn.decomposition import PCA
    from sklearn.metrics import adjusted_rand_score, silhouette_score

    df = countries.set_index("country_code")
    z = standardize(df)
    zv = z.to_numpy()

    # --- PCA landscape ---
    pca = PCA(n_components=2, random_state=SEED).fit(zv)
    xy = pca.transform(zv)
    # Make orientation deterministic: axis 1 points towards higher income.
    for i in range(2):
        if pca.components_[i][FEATURES.index("average_salary")] < 0 and i == 0:
            xy[:, i] *= -1
            pca.components_[i] *= -1
        if i == 1 and pca.components_[i][FEATURES.index("climate")] < 0:
            xy[:, i] *= -1
            pca.components_[i] *= -1

    # --- choose k by silhouette ---
    sil = {}
    for k in K_RANGE:
        sil[k] = round(float(silhouette_score(zv, _kmeans(zv, k).labels_)), 3)
    best_k = max(sil, key=lambda k: (sil[k], -k))
    km = _kmeans(zv, best_k)
    labels = km.labels_

    # Relabel clusters so cluster 0 is the highest-income group (stable ids).
    cent = pd.DataFrame(km.cluster_centers_, columns=FEATURES)
    order = cent["average_salary"].sort_values(ascending=False).index.tolist()
    remap = {old: new for new, old in enumerate(order)}
    labels = np.array([remap[l] for l in labels])
    cent = cent.loc[order].reset_index(drop=True)

    # --- stability (bootstrap ARI) ---
    rng = np.random.default_rng(SEED)
    aris = []
    for b in range(BOOTSTRAPS):
        idx = rng.choice(len(zv), size=len(zv), replace=True)
        boot = _kmeans(zv[idx], best_k, seed=b + 1)
        aris.append(adjusted_rand_score(labels, boot.predict(zv)))

    # --- names ---
    taken, clusters = set(), []
    for cid in range(best_k):
        cz = cent.loc[cid]
        members = [c for c, l in zip(df.index, labels) if l == cid]
        name = name_cluster(cz, z.loc[members], taken)
        taken.add(name)
        clusters.append({
            "id": cid, "name": name, "size": len(members), "members": members,
            "centroid_z": {f: round(float(cz[f]), 2) for f in FEATURES},
        })

    # --- nearest neighbours in standardized space ---
    dist = np.linalg.norm(zv[:, None, :] - zv[None, :, :], axis=2)
    codes = list(df.index)
    countries_out = {}
    for i, code in enumerate(codes):
        order_i = [j for j in np.argsort(dist[i], kind="stable") if j != i][:N_NEIGHBOURS]
        countries_out[code] = {
            "x": round(float(xy[i, 0]), 4), "y": round(float(xy[i, 1]), 4),
            "cluster": int(labels[i]),
            "neighbors": [codes[j] for j in order_i],
            "distances": [round(float(dist[i, j]), 3) for j in order_i],
        }

    return {
        "method": "z-scored 9 factors → PCA (2D map) + k-means (k by silhouette) + Euclidean nearest neighbours",
        "features": FEATURES,
        "k": best_k,
        "silhouette_by_k": sil,
        "stability_ari": {"mean": round(float(np.mean(aris)), 3), "min": round(float(np.min(aris)), 3),
                          "bootstraps": BOOTSTRAPS},
        "explained_variance": [round(float(v), 3) for v in pca.explained_variance_ratio_],
        "axes": [{"label": axis_label(pd.Series(pca.components_[i], index=FEATURES)),
                  "loadings": {f: round(float(v), 3) for f, v in zip(FEATURES, pca.components_[i])}}
                 for i in range(2)],
        "clusters": clusters,
        "countries": countries_out,
    }
