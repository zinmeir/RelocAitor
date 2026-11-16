"""
relocaitor/web/app.py — Flask backend for RelocAitor, a global relocation decision-support system.

Recommendations come from a transparent rule-based engine (relocaitor.ranking, relocaitor.visas,
reasoning.py, search.py). Claude is an optional layer for Q&A and prompt understanding.

Endpoints:
    GET  /              -> the app (templates/index.html)
    GET  /api/health    -> {"status": "ok"}
    GET  /api/meta      -> factors, presets, regions, visa types, nationalities
    POST /api/score     -> { weights, region?, top_n?, profile? } -> ranked list
    POST /api/insights  -> { country, weights, region?, profile? } -> explanation, visas, what-if…
    POST /api/compare   -> { countries: [≤3 names], weights, region?, profile? }
    POST /api/ask       -> { question, country, weights?, region?, profile? } -> answer
    POST /api/visas     -> { country_code, type?, max_difficulty?, profile? } -> visa list
    POST /api/preferences -> { answers: [{a, b, choice}] } -> next "A or B?" question + learned weights
    POST /api/confidence -> { weights, region?, top_n?, profile? } -> how stable the ranking is
    POST /api/pathways  -> { weights, region?, profile? } -> closest visas + what would open more countries
    POST /api/refine    -> { prompt, state: {weights, region, profile, top_n} } -> follow-up: new state,
                           what changed, how the top moved, and actions (open / compare / undo / reset)
    POST /api/search    -> { prompt } -> what the prompt means (weights, filters, profile),
                           matching visas, and similar countries

`profile` (all optional):
    nationality (ISO-3), monthly_income (USD), investment_budget (USD),
    visa_type, require_pr, max_difficulty, only_qualifying, exclude_home

Run locally:
    python app.py            # then open http://localhost:5000
"""

from __future__ import annotations

import os
from dataclasses import replace

import numpy as np
from flask import Flask, jsonify, render_template, request

from ml import preferences as pref
from pipeline.sources import SHORT_NAMES
from relocaitor import paths
from relocaitor.datasets import (get_country_map, get_data_version, get_map_markers, get_nationalities,
                                 get_provenance, get_regions, load_countries)
from relocaitor.immigration.catalogue import STATUS_LABEL
from relocaitor.nlp import assistant, refine, search
from relocaitor.ranking import confidence, engine
from relocaitor.ranking.factors import DEFAULT_WEIGHTS, FACTORS
from relocaitor.ranking.presets import PRESETS
from relocaitor.ranking.reasoning import generate_explanation, generate_tradeoffs, generate_user_insight
from relocaitor.ranking.scoring import compute_scores, factor_matrix, find_similar_countries
from relocaitor.visas import journey
from relocaitor.visas import qualify as pathways
from relocaitor.visas.catalog import all_visa_types, filter_visas, visas_for_profile
from relocaitor.visas.eligibility import rules as eligibility_rules
from relocaitor.web import icons
from relocaitor.web.validation import (
    BadRequest, NotFound, parse_country, parse_country_list, parse_profile,
    parse_region, parse_top_n, parse_weights,
)
app = Flask(__name__, template_folder=str(paths.TEMPLATES), static_folder=str(paths.STATIC))
app.json.sort_keys = False  # keep factor / field order as defined
app.jinja_env.globals["icon"] = icons.svg   # our own line icons in templates
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024      # no request needs more

from relocaitor.web import security  # noqa: E402  (logging, rate limits, security headers)
from relocaitor.workspace import bp as workspace_bp  # noqa: E402

security.install(app)
app.register_blueprint(workspace_bp)

DROP_COLS = []  # columns never sent to the client (none currently)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object")
    return body


def _common(body: dict):
    # Accept both {"weights": {...}} and a bare weights object (old frontend shape).
    raw_weights = body.get("weights", body if "salary" in body else None)
    return (parse_weights(raw_weights), parse_region(body.get("region")),
            parse_profile(body.get("profile")))


def _records(df) -> list:
    return df.drop(columns=[c for c in DROP_COLS if c in df.columns]).to_dict(orient="records")


def _country_names() -> set:
    return set(load_countries()["country_name"])


@app.errorhandler(BadRequest)
def _bad_request(err):
    return jsonify({"error": str(err)}), 400


@app.errorhandler(NotFound)
def _not_found(err):
    return jsonify({"error": str(err)}), 404


def meta() -> dict:
    return {
        "factors": {k: {"label": m["label"], "icon": m["icon"], "invert": m["invert"]}
                    for k, m in FACTORS.items()},
        "factor_order": list(FACTORS),
        "default_weights": DEFAULT_WEIGHTS,
        "presets": PRESETS,
        "regions": get_regions(),
        "visa_types": all_visa_types(),
        "nationalities": get_nationalities(),
        "country_count": len(load_countries()),
        "country_codes": list(load_countries()["country_code"]),
        "llm_enabled": assistant.llm_enabled(),
        "data_sources": data_sources(),
        "country_map": get_country_map(),
        "source_names": SHORT_NAMES,
        "occupations": [{"key": k, "label": v["label"]} for k, v in journey.occupations().items()],
        "fx": journey.fx(),
        "currencies": journey.currencies(),
        "visa_status": visa_status_meta(),
        "estimated": estimated_factors(),
        "data_version": get_data_version(),
        "scales": eligibility_rules()["scales"],
        "labels": eligibility_rules()["labels"],
    }


# Provenance methods that mean "we had no measurement for this country" (shown with ≈).
ESTIMATE_METHODS = {"ml-imputed", "ml-estimate", "regional-median", "editorial-fallback"}


def estimated_factors() -> dict:
    """{country_code: [factor keys whose value is an estimate]} for the ≈ markers."""
    from relocaitor.datasets import _provenance
    col_to_key = {m["col"]: k for k, m in FACTORS.items()}
    col_to_key.update({"salary_usd_month": "salary_money", "rent_usd_month": "rent_money"})
    out = {}
    for code, cols in _provenance().items():
        keys = [col_to_key[c] for c, p in cols.items() if c in col_to_key and p.get("method") in ESTIMATE_METHODS]
        if keys:
            out[code] = keys
    return out


def data_sources() -> list:
    """How each factor is built, for the 'Data sources & methods' panel."""
    from pipeline.sources import COLUMN_METHODS, SPECIAL_COLUMNS
    labels = {m["col"]: (k, m["label"], m["icon"]) for k, m in FACTORS.items()}
    out = []
    for col, (key, label, icon) in labels.items():
        text = COLUMN_METHODS[col]["explain"] if col in COLUMN_METHODS else SPECIAL_COLUMNS.get(col, "")
        out.append({"key": key, "label": label, "icon": icon, "method": text})
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    m = meta()
    return render_template("index.html", meta_json=m, icons_json=icons.ICONS, map_markers=get_map_markers(), **m)


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@app.route("/api/meta")
def api_meta():
    return jsonify(meta())


@app.route("/api/score", methods=["POST"])
def api_score():
    body = _body()
    weights, region, profile = _common(body)
    top_n = parse_top_n(body.get("top_n"))

    qual = engine.qualification_table(profile, load_countries()["country_code"])
    ranked = engine.rank(weights, region, profile, qual)
    counts = engine.excluded_count(weights, region, profile, qual)

    return jsonify({
        "data_version": get_data_version(),
        "user_insight": generate_user_insight(weights),
        "top": _records(ranked.head(top_n)),
        "all": _records(ranked),
        "counts": counts,
        "flip": engine.what_would_flip_top(weights, region, profile, qual) if len(ranked) > 1 else None,
    })


@app.route("/api/insights", methods=["POST"])
def api_insights():
    body = _body()
    weights, region, profile = _common(body)
    name = parse_country(body.get("country"), _country_names())

    qual = engine.qualification_table(profile, load_countries()["country_code"])
    ranked = engine.rank(weights, region, profile, qual)
    rank = engine.rank_of(ranked, name)

    # Always describe the country, even if the current filters hide it.
    all_scored = compute_scores(load_countries(), weights)
    row = all_scored[all_scored["country_name"] == name].iloc[0]
    visa_info = qual[row["country_code"]]

    country = row.to_dict()
    cmap = get_country_map()
    cid = cmap.get("countries", {}).get(row["country_code"], {}).get("cluster")
    country.update(rank=rank, total=len(ranked), hidden_by_filters=rank is None,
                   provenance=get_provenance(row["country_code"]),
                   cluster=cmap["clusters"][cid]["name"] if cid is not None else None)

    return jsonify({
        "data_version": get_data_version(),
        "country":     country,
        "explanation": generate_explanation(row, weights, rank, len(ranked)),
        "tradeoffs":   generate_tradeoffs(row),
        "similar":     _records(find_similar_countries(all_scored, name, n=3)),
        "visas":       pathways.annotate_visas(visa_info["visas"], profile, _names()),
        "reliability": confidence.reliability(row["country_code"], weights),
        "qualifying_count": visa_info["qualifying_count"],
        "visas_researched": visa_info["researched"],
        "citizenship": visa_info["citizenship"],
        "in_demand":   visa_info["in_demand"],
        "field_in_demand": visa_info["field_in_demand"],
        "cities":      journey.cities(row["country_code"]),
        "is_home":     visa_info["is_home"],
        "official_url": visa_info["official_url"],
        "what_if":     engine.what_if_country(weights, region, profile, name, qual) if rank else [],
    })


def _names() -> dict:
    return {n["code"]: n["name"] for n in get_nationalities()}


@app.route("/api/confidence", methods=["POST"])
def api_confidence():
    body = _body()
    weights, region, profile = _common(body)
    top_n = parse_top_n(body.get("top_n"))
    ranked = engine.rank(weights, region, profile)
    return jsonify(confidence.simulate(ranked.to_dict(orient="records"), weights, top_n=top_n))


@app.route("/api/pathways", methods=["POST"])
def api_pathways():
    body = _body()
    weights, region, profile = _common(body)
    open_profile = replace(profile, only_qualifying=False, visa_type="any", require_pr=False, max_difficulty=None)
    candidates = list(engine.rank(weights, region, open_profile)["country_code"])
    return jsonify(pathways.pathways(candidates, profile, _names()))


@app.route("/api/compare", methods=["POST"])
def api_compare():
    body = _body()
    weights, region, profile = _common(body)
    names = parse_country_list(body.get("countries"), _country_names())

    qual = engine.qualification_table(profile, load_countries()["country_code"])
    ranked = engine.rank(weights, region, profile, qual)
    all_scored = compute_scores(load_countries(), weights)

    items = []
    for name in names:
        row = all_scored[all_scored["country_name"] == name].iloc[0]
        info = qual[row["country_code"]]
        pr_routes = [v["name"] for v in info["visas"] if v["qualifies"] and v["pr_route"] in ("Yes", "Eventually")]
        rec = row.to_dict()
        rec.update(
            rank=engine.rank_of(ranked, name),
            qualifying_visas=info["qualifying_count"],
            total_visas=len(info["visas"]),
            pr_routes=pr_routes,
            easiest_visa=min(info["visas"], key=lambda v: {"Easy": 0, "Moderate": 1, "Hard": 2}[v["difficulty"]])["name"]
            if info["visas"] else None,
        )
        items.append(rec)

    return jsonify({"factors": list(FACTORS), "total": len(ranked), "items": items})


@app.route("/api/ask", methods=["POST"])
def api_ask():
    body = _body()
    weights, region, profile = _common(body)
    name = parse_country(body.get("country"), _country_names())
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        raise BadRequest("'question' is required")

    qual = engine.qualification_table(profile, load_countries()["country_code"])
    ranked = engine.rank(weights, region, profile, qual)
    all_scored = compute_scores(load_countries(), weights)
    row = all_scored[all_scored["country_name"] == name].iloc[0]

    result = assistant.answer(question, row, qual[row["country_code"]],
                              engine.rank_of(ranked, name), len(ranked), profile.to_dict())
    result["country"] = name
    return jsonify(result)


def _pref_card(row, x) -> dict:
    return {
        "name": row["country_name"], "code": row["country_code"], "region": row["region"],
        "main_city": row["main_city"], "avg_temp_c": row["avg_temp_c"],
        "salary_usd_month": int(row["salary_usd_month"]), "rent_usd_month": int(row["rent_usd_month"]),
        "values": {k: round(float(v), 2) for k, v in zip(FACTORS, x)},
    }


@app.route("/api/preferences", methods=["POST"])
def api_preferences():
    """Preference learning: send the answers so far, get the learned weights and the next question."""
    body = _body()
    answers = body.get("answers") or []
    total = parse_top_n(body.get("n_questions"), default=pref.DEFAULT_QUESTIONS)
    if not isinstance(answers, list) or len(answers) > 30:
        raise BadRequest("'answers' must be a list of at most 30 items")

    df = load_countries()
    X = factor_matrix(df)[list(FACTORS)].to_numpy()
    codes = list(df["country_code"])
    index = {n: i for i, n in enumerate(df["country_name"])}
    diffs, outcomes, asked = [], [], set()
    for a in answers:
        if not isinstance(a, dict) or a.get("a") not in index or a.get("b") not in index \
                or a.get("choice") not in ("a", "b", "skip"):
            raise BadRequest("each answer needs valid 'a', 'b' country names and choice a|b|skip")
        i, j = index[a["a"]], index[a["b"]]
        asked.add(frozenset((codes[i], codes[j])))
        if a["choice"] != "skip":
            diffs.append(X[i] - X[j])
            outcomes.append(1.0 if a["choice"] == "a" else 0.0)
    D, y = np.array(diffs).reshape(-1, X.shape[1]), np.array(outcomes)
    w = pref.fit(D, y)
    weights = pref.to_slider_weights(w)

    done = len(answers) >= total
    question = None
    if not done:
        pair = pref.next_question(X, codes, w, asked)
        if pair is None:
            done = True
        else:
            i, j = pair
            ra, rb = df.iloc[i], df.iloc[j]
            question = {"a": _pref_card(ra, X[i]), "b": _pref_card(rb, X[j]),
                        "differences": pref.describe_difference(X[i], X[j], ra["country_name"], rb["country_name"])}
    return jsonify({
        "done": done, "number": min(len(answers) + 1, total), "total": total, "question": question,
        "weights": weights, "consistency": pref.consistency(D, y, w),
        "answered": len(answers), "user_insight": generate_user_insight(weights),
    })


@app.route("/api/refine", methods=["POST"])
def api_refine():
    """Follow-up prompt -> the current search, changed only where the prompt says so."""
    body = _body()
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise BadRequest("'prompt' is required")
    if len(prompt) > search.MAX_PROMPT:
        raise BadRequest(f"'prompt' must be at most {search.MAX_PROMPT} characters")
    state = body.get("state") or {}
    if not isinstance(state, dict):
        raise BadRequest("'state' must be an object")
    out = refine.refine(prompt, state, meta())
    names = {n["code"]: n["name"] for n in get_nationalities()}
    out["state"]["profile"]["exclude_countries"] = [names.get(c, c) for c in out["state"]["profile"]["exclude_countries"]]
    return jsonify(out)


@app.route("/api/search", methods=["POST"])
def api_search():
    """Natural-language prompt -> settings to apply + keyword hits."""
    body = _body()
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise BadRequest("'prompt' is required")
    if len(prompt) > search.MAX_PROMPT:
        raise BadRequest(f"'prompt' must be at most {search.MAX_PROMPT} characters")

    m = meta()
    interp = search.interpret(prompt, m)
    name_to_code = {n["name"]: n["code"] for n in m["nationalities"]}
    similar = []
    if interp.get("similar_to"):
        excluded = set(interp.get("exclude") or [])
        sim = find_similar_countries(load_countries(), interp["similar_to"], n=6)
        similar = [n for n in sim["country_name"] if n not in excluded][:4]
    hits = search.visa_search(prompt, interp.get("region"),
                                 countries=[name_to_code[c] for c in interp.get("countries") or []])
    return jsonify({"interpretation": interp, "visa_hits": hits, "similar": similar})


@app.route("/api/visas", methods=["POST"])
def api_visas():
    """Standalone visa lookup with optional filtering and eligibility."""
    body = _body()
    code = body.get("country_code")
    if not isinstance(code, str) or code not in set(load_countries()["country_code"]):
        raise NotFound(f"Country code '{code}' not found")
    profile = parse_profile(body.get("profile"))
    info = visas_for_profile(code, profile)
    visas = filter_visas(info["visas"], visa_type=body.get("type"),
                         max_difficulty=body.get("max_difficulty"))
    return jsonify({"country_code": code, "visas": visas, "official_url": info["official_url"]})


# ---------------------------------------------------------------------------
# Global mobility platform (additive endpoints; the existing contracts are unchanged)
# ---------------------------------------------------------------------------
def _engine_error(fn):
    """Engines raise ValueError for bad input; the API turns that into 400."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except ValueError as err:
            raise BadRequest(str(err)) from None
    return wrapper


def _codes(raw, field="countries"):
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw) or len(raw) > 70:
        raise BadRequest(f"'{field}' must be a list of ISO-3 codes")
    known = set(load_countries()["country_code"])
    bad = [c for c in raw if c not in known]
    if bad:
        raise NotFound(f"Unknown country: {bad[0]}")
    return raw


@app.route("/api/plan", methods=["POST"])
@_engine_error
def api_plan():
    """Routes to permanent residence for this profile, ranked, with the reason #1 beats #2."""
    from relocaitor import planner
    body = _body()
    study = body.get("study_years")
    if study is not None and (isinstance(study, bool) or not isinstance(study, (int, float)) or not 0 < study <= 8):
        raise BadRequest("'study_years' must be a number between 0 and 8")
    return jsonify(planner.plan(parse_profile(body.get("profile")), _codes(body.get("countries")), study))


@app.route("/api/plan/whatif", methods=["POST"])
@_engine_error
def api_plan_whatif():
    """Re-run the rules with the profile changed: which routes open or close."""
    from relocaitor import planner
    body = _body()
    profile = parse_profile(body.get("profile"))
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise BadRequest("'changes' must be an object, e.g. {\"english\": \"B2\"}")
    merged = parse_profile({**profile.to_dict(), **{k: v for k, v in profile.to_dict().items() if v is not None}, **changes,
                            "exclude_countries": []})
    return jsonify(planner.what_if(profile, {k: getattr(merged, k) for k in changes}))


@app.route("/api/finance/simulate", methods=["POST"])
@_engine_error
def api_finance_simulate():
    from relocaitor import finance
    body = _body()
    _codes([body.get("country")] if isinstance(body.get("country"), str) else None, "country")
    return jsonify(finance.simulate(body))


@app.route("/api/finance/compare", methods=["POST"])
@_engine_error
def api_finance_compare():
    from relocaitor import finance
    body = _body()
    _codes(body.get("countries"))
    return jsonify(finance.compare(body))


@app.route("/api/career", methods=["POST"])
@_engine_error
def api_career():
    from relocaitor import career
    body = _body()
    countries = _codes(body.get("countries")) or []
    if not 1 <= len(countries) <= 5:
        raise BadRequest("'countries' must list 1 to 5 ISO-3 codes")
    return jsonify(career.career_report(parse_profile(body.get("profile")), countries))


@app.route("/api/career/jobs")
def api_career_jobs():
    from relocaitor.career import jobs
    country = request.args.get("country", "")
    _codes([country], "country")
    return jsonify(jobs.search(country, request.args.get("field") or "", request.args.get("q")))


@app.route("/api/dimensions", methods=["POST"])
@_engine_error
def api_dimensions():
    from relocaitor.ranking import dimensions
    body = _body()
    code = body.get("country")
    _codes([code] if isinstance(code, str) else ["?"], "country")
    weights = parse_weights(body.get("weights")) if body.get("weights") is not None else DEFAULT_WEIGHTS
    return jsonify(dimensions.dimensions(code, parse_profile(body.get("profile")), weights))


@app.route("/api/assistant", methods=["POST"])
@_engine_error
def api_assistant():
    """The orchestrator: agents call the deterministic engines; an LLM only phrases results, with consent."""
    from relocaitor import agents
    body = _body()
    q = body.get("question")
    if not isinstance(q, str) or not q.strip() or len(q) > 500:
        raise BadRequest("'question' must be 1-500 characters")
    code = body.get("country")
    _codes([code] if isinstance(code, str) else ["?"], "country")
    share = body.get("share_profile_with_ai") is True
    llm = (lambda system, user: assistant.ask_llm_raw(system, user, max_tokens=350)) if assistant.llm_enabled() else None
    return jsonify(agents.run(q.strip(), code, parse_profile(body.get("profile")), share_with_llm=share, llm=llm))


@app.route("/workspace")
def workspace_page():
    m = meta()
    return render_template("workspace.html", meta_json=m, icons_json=icons.ICONS, **m)


# ---------------------------------------------------------------------------
# Immigration intelligence (additive: /api/immigration/...)
# ---------------------------------------------------------------------------
def _immigration_records() -> dict:
    from relocaitor.immigration import store
    return store.load("records", {}).get("routes", {})


@app.route("/api/immigration/routes")
def api_immigration_routes():
    """Every route with a value, status, source and check date per field. ?country=ISO3 to filter."""
    from datetime import date as _date
    from relocaitor.immigration import records as R
    code = request.args.get("country")
    today = _date.today()
    recs = [R.with_current_status(r, today) for r in _immigration_records().values()
            if not code or r["country"] == code]
    return jsonify({"routes": recs, "statuses": STATUS_LABEL})


@app.route("/api/immigration/sources")
def api_immigration_sources():
    from relocaitor.immigration import store
    return jsonify({"sources": store.load("sources")})


@app.route("/api/immigration/changes")
def api_immigration_changes():
    """Logged changes, newest first. ?since=YYYY-MM-DD"""
    from relocaitor.immigration import store
    since = request.args.get("since") or ""
    changes = [c for c in store.load("changes") if c["detected"] >= since]
    return jsonify({"changes": sorted(changes, key=lambda c: c["detected"], reverse=True)})


@app.route("/api/immigration/impact", methods=["POST"])
def api_immigration_impact():
    """Which logged changes affect this profile: verdicts recomputed before and after each change."""
    from relocaitor.immigration import impact as I, store
    body = _body()
    since = body.get("since")
    if since is not None and not isinstance(since, str):
        raise BadRequest("'since' must be a date string (YYYY-MM-DD)")
    profile = parse_profile(body.get("profile"))
    return jsonify({"impact": I.impact(profile, store.load("changes"), store.load_visas(), since)})


def visa_status_meta() -> dict:
    """{"ISO3|visa name": summary} so each visa card can say how well its data is sourced."""
    from datetime import date as _date
    from relocaitor.immigration import records as R
    today = _date.today()
    out = {}
    for r in _immigration_records().values():
        summ = R.with_current_status(r, today)["summary"]
        cur = R.with_current_status(r, today)
        out[f"{r['country']}|{r['name']}"] = {"counts": summ["counts"], "checked": summ["last_checked"],
                                               "version": r.get("rule_version"),
                                               "estimated": sorted(k for k, f in cur["fields"].items()
                                                                   if f["status"] == "estimated")}
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Development server. Production runs `gunicorn app:app` (see the root app.py)."""
    port = int(os.environ.get("PORT", 5000))
    # Debug mode (auto-reload + interactive debugger) only when explicitly asked for:
    #   FLASK_DEBUG=1 python app.py
    # Never enable it on a machine reachable from a network.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=debug)
