"""
app.py — Flask backend for the AI Global Relocation Intelligence System.

Endpoints:
    GET  /              -> renders the main app (templates/index.html)
    POST /api/score     -> { weights {...}, region?, top_n? } -> ranked list
    POST /api/insights  -> { country, weights, region? } -> explanation, etc.
    POST /api/visas     -> { country_code, type?, max_difficulty? } -> visa list

Run locally:
    python app.py
    # then open http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify

from data import load_countries, get_regions
from scoring import compute_scores, rank_top_n, find_similar_countries, FACTORS
from reasoning import generate_explanation, generate_tradeoffs, generate_user_insight
from visas import get_visas_for, filter_visas, all_visa_types


app = Flask(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "salary": 0.7, "cost": 0.5, "pr": 0.6, "job": 0.7,
    "climate": 0.3, "safety": 0.5, "healthcare": 0.4,
    "english": 0.5, "internet": 0.3,
}


def _parse_weights(raw: dict) -> dict:
    """Sanitize incoming weights dict — only accept known factors."""
    weights = {}
    for k in FACTORS:
        try:
            v = float(raw.get(k, DEFAULT_WEIGHTS.get(k, 0.0)))
            weights[k] = max(0.0, min(1.0, v))
        except (TypeError, ValueError):
            weights[k] = DEFAULT_WEIGHTS.get(k, 0.0)
    return weights


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        regions=get_regions(),
        visa_types=all_visa_types(),
        default_weights=DEFAULT_WEIGHTS,
    )


@app.route("/api/score", methods=["POST"])
def api_score():
    body = request.get_json(silent=True) or {}
    weights = _parse_weights(body.get("weights", body))  # accept both shapes
    region = body.get("region", "All regions")
    top_n = int(body.get("top_n", 5))

    df = load_countries()
    if region and region != "All regions":
        df = df[df["region"] == region].reset_index(drop=True)

    if df.empty:
        return jsonify({
            "user_insight": generate_user_insight(weights),
            "top": [], "all": [],
        })

    scored = compute_scores(df, weights)
    top = rank_top_n(scored, n=top_n)

    return jsonify({
        "user_insight": generate_user_insight(weights),
        "top": top.to_dict(orient="records"),
        "all": scored.sort_values("score", ascending=False).to_dict(orient="records"),
    })


@app.route("/api/insights", methods=["POST"])
def api_insights():
    body = request.get_json(silent=True) or {}
    country_name = body.get("country")
    weights = _parse_weights(body.get("weights", {}))
    region = body.get("region", "All regions")

    df = load_countries()
    if region and region != "All regions":
        df = df[df["region"] == region].reset_index(drop=True)

    scored = compute_scores(df, weights)

    matches = scored[scored["country_name"] == country_name]
    if matches.empty:
        return jsonify({"error": f"Country '{country_name}' not found"}), 404

    row = matches.iloc[0]
    similar = find_similar_countries(scored, country_name, n=3)
    visas = get_visas_for(row["country_code"])

    return jsonify({
        "country":     row.to_dict(),
        "explanation": generate_explanation(row, weights),
        "tradeoffs":   generate_tradeoffs(row),
        "similar":     similar.to_dict(orient="records"),
        "visas":       visas,
    })


@app.route("/api/visas", methods=["POST"])
def api_visas():
    """Standalone visa lookup with optional filtering."""
    body = request.get_json(silent=True) or {}
    code = body.get("country_code")
    visa_type = body.get("type")
    max_difficulty = body.get("max_difficulty")

    visas = get_visas_for(code)
    if visa_type or max_difficulty:
        visas = filter_visas(visas, visa_type=visa_type, max_difficulty=max_difficulty)
    return jsonify({"country_code": code, "visas": visas})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
