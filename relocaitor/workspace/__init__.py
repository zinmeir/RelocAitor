"""
relocaitor.workspace — accounts and the personal relocation workspace ("My relocation").

Blueprint mounted at /api/me. Every route except register/login needs a session cookie, and every
request that changes something also needs the CSRF token returned at sign-in (header X-CSRF-Token).
Users only ever see their own rows: every query filters by the session's user id.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import date, datetime, timezone
from functools import wraps

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import BadRequest

from . import db

bp = Blueprint("workspace", __name__, url_prefix="/api/me")
COOKIE = "reloc_session"
SESSION_DAYS = 14
STATUSES = ("planned", "preparing", "ready", "submitted", "awaiting_decision", "approved", "rejected", "completed")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _audit(uid, action):
    db.conn().execute("INSERT INTO audit (user_id, action, at) VALUES (?, ?, ?)", (uid, action, _now()))
    db.conn().commit()


# ---------------------------------------------------------------------------
# Passwords and sessions
# ---------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


def _token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def _start_session(uid: int):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    db.conn().execute("INSERT INTO sessions (token_hash, user_id, csrf, expires) VALUES (?, ?, ?, ?)",
                      (_token_hash(token), uid, csrf, time.time() + SESSION_DAYS * 86400))
    db.conn().commit()
    return token, csrf


def _set_cookie(resp, token, max_age=SESSION_DAYS * 86400):
    secure = os.environ.get("RELOC_SECURE_COOKIES", "1" if os.environ.get("FLASK_ENV") == "production" else "0") == "1"
    resp.set_cookie(COOKIE, token, max_age=max_age, httponly=True, samesite="Lax", secure=secure, path="/")
    return resp


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        token = request.cookies.get(COOKIE)
        row = token and db.conn().execute(
            "SELECT s.user_id, s.csrf, s.expires, u.email FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ?", (_token_hash(token),)).fetchone()
        if not row or row["expires"] < time.time():
            return jsonify({"error": "Sign in first."}), 401
        if request.method not in ("GET", "HEAD") and not hmac.compare_digest(
                request.headers.get("X-CSRF-Token", ""), row["csrf"]):
            return jsonify({"error": "Missing or wrong CSRF token."}), 403
        g.uid, g.email, g.csrf = row["user_id"], row["email"], row["csrf"]
        return fn(*a, **kw)
    return wrapper


def _body() -> dict:
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        raise BadRequest("Send a JSON object")
    return b


def _credentials(b):
    email = str(b.get("email") or "").strip().lower()
    pw = str(b.get("password") or "")
    if not EMAIL.match(email):
        raise BadRequest("Enter a valid email address")
    return email, pw


@bp.post("/register")
def register():
    email, pw = _credentials(_body())
    if len(pw) < 10:
        raise BadRequest("Use a password of at least 10 characters")
    try:
        cur = db.conn().execute("INSERT INTO users (email, pw_hash, created) VALUES (?, ?, ?)",
                                (email, hash_password(pw), _now()))
        db.conn().commit()
    except db.sqlite3.IntegrityError:
        return jsonify({"error": "That email already has an account; sign in instead."}), 409
    _audit(cur.lastrowid, "register")
    token, csrf = _start_session(cur.lastrowid)
    return _set_cookie(jsonify({"email": email, "csrf": csrf}), token), 201


@bp.post("/login")
def login():
    email, pw = _credentials(_body())
    row = db.conn().execute("SELECT id, pw_hash FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not check_password(pw, row["pw_hash"]):
        return jsonify({"error": "Email or password is wrong."}), 401
    _audit(row["id"], "login")
    token, csrf = _start_session(row["id"])
    return _set_cookie(jsonify({"email": email, "csrf": csrf}), token)


@bp.post("/logout")
@login_required
def logout():
    db.conn().execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(request.cookies[COOKIE]),))
    db.conn().commit()
    return _set_cookie(jsonify({"ok": True}), "", max_age=0)


@bp.get("")
@login_required
def me():
    return jsonify({"email": g.email, "csrf": g.csrf})


# ---------------------------------------------------------------------------
# Profile (encrypted at rest)
# ---------------------------------------------------------------------------
def _profile_dict() -> dict:
    row = db.conn().execute("SELECT data FROM profiles WHERE user_id = ?", (g.uid,)).fetchone()
    return db.decrypt(row["data"]) if row else {}


@bp.route("/profile", methods=["GET", "PUT"])
@login_required
def profile():
    if request.method == "GET":
        return jsonify({"profile": _profile_dict()})
    from relocaitor.web.validation import parse_profile
    raw = _body().get("profile")
    parse_profile(raw)                       # validate with the same rules as every other endpoint
    db.conn().execute("INSERT INTO profiles (user_id, data, updated) VALUES (?, ?, ?) "
                      "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
                      (g.uid, db.encrypt(raw), _now()))
    db.conn().commit()
    _audit(g.uid, "profile_saved")
    return jsonify({"profile": raw})


# ---------------------------------------------------------------------------
# Shortlist and saved pathways
# ---------------------------------------------------------------------------
def _country(code):
    from relocaitor.datasets import load_countries
    if code not in set(load_countries()["country_code"]):
        raise BadRequest(f"Unknown country '{code}'")
    return code


@bp.route("/shortlist", methods=["GET", "POST", "DELETE"])
@login_required
def shortlist():
    c = db.conn()
    if request.method == "POST":
        b = _body()
        c.execute("INSERT OR REPLACE INTO shortlist (user_id, country, note, added) VALUES (?, ?, ?, ?)",
                  (g.uid, _country(b.get("country")), str(b.get("note") or "")[:500], _now()))
        c.commit()
    elif request.method == "DELETE":
        c.execute("DELETE FROM shortlist WHERE user_id = ? AND country = ?", (g.uid, request.args.get("country")))
        c.commit()
    rows = c.execute("SELECT country, note, added FROM shortlist WHERE user_id = ? ORDER BY added", (g.uid,)).fetchall()
    return jsonify({"shortlist": [dict(r) for r in rows]})


@bp.route("/pathways", methods=["GET", "POST", "DELETE"])
@login_required
def saved_pathways():
    from relocaitor import planner
    c = db.conn()
    if request.method == "POST":
        pid = str(_body().get("pathway") or "")
        if not re.match(r"^(direct:|free:)?[A-Z]{3}[-a-z0-9:]*$", pid):
            raise BadRequest("Unknown pathway id")
        c.execute("INSERT OR IGNORE INTO saved_pathways (user_id, pathway_id, added) VALUES (?, ?, ?)", (g.uid, pid, _now()))
        c.commit()
    elif request.method == "DELETE":
        c.execute("DELETE FROM saved_pathways WHERE user_id = ? AND pathway_id = ?", (g.uid, request.args.get("pathway")))
        c.commit()
    ids = [r["pathway_id"] for r in c.execute("SELECT pathway_id FROM saved_pathways WHERE user_id = ? ORDER BY added", (g.uid,))]
    from relocaitor.web.validation import parse_profile
    plan = planner.plan(parse_profile(_profile_dict()), countries=sorted({i.split(":")[-1][:3] for i in ids}) or None)
    by_id = {p["id"]: p for p in plan["pathways"]}
    return jsonify({"pathways": [by_id.get(i, {"id": i, "missing": True}) for i in ids]})


# ---------------------------------------------------------------------------
# Document checklist: generated from the route's researched requirements
# ---------------------------------------------------------------------------
def checklist_items(route_id: str, profile: dict) -> list:
    from relocaitor.immigration.records import route_id as rid_of
    from relocaitor.visas import catalog as V
    from relocaitor.visas.eligibility import rules
    for code, e in V._load().items():
        for v in e["visas"]:
            if rid_of(code, v["name"]) != route_id:
                continue
            items = [("Valid passport", "general: needed for every visa")]
            if v.get("language"):
                lang = rules()["labels"]["language"].get(v["language"]["lang"], v["language"]["lang"])
                lvl = v["language"].get("cefr") or v["language"].get("test")
                items.append((f"{lang} test result at {lvl}", "route requirement: language (official source)"))
            if v.get("education_min"):
                items.append(("Degree certificate and transcripts", "route requirement: education (official source)"))
                if "Credential Assessment" in (v.get("requirements_note") or ""):
                    items.append(("Educational Credential Assessment (ECA)", "route requirement (official source)"))
            if v.get("experience_years"):
                items.append((f"Reference letters covering {v['experience_years']:g}+ years of skilled work",
                              "route requirement: work experience (official source)"))
            if v.get("requires_sponsor"):
                items.append(("Job offer from a licensed sponsor", "route requirement (unsourced estimate)"))
            if v.get("min_income") or v.get("min_investment"):
                items.append(("Proof of income or funds (e.g. bank statements)", "route requirement (unsourced estimate)"))
            if profile.get("partner") and (v.get("family") or {}).get("partner"):
                items.append(("Marriage or partnership certificate", "family: your partner is coming (official source)"))
            if profile.get("children") and (v.get("family") or {}).get("children"):
                items.append(("Children's birth certificates", "family: children are coming (official source)"))
            return items
    raise BadRequest(f"Unknown route '{route_id}'")


@bp.route("/checklist", methods=["GET", "POST", "PATCH", "DELETE"])
@login_required
def checklist():
    c = db.conn()
    if request.method == "POST":
        b = _body()
        if b.get("route"):
            for item, basis in checklist_items(str(b["route"]), _profile_dict()):
                exists = c.execute("SELECT 1 FROM checklist WHERE user_id = ? AND route = ? AND item = ?",
                                   (g.uid, b["route"], item)).fetchone()
                if not exists:
                    c.execute("INSERT INTO checklist (user_id, route, item, basis) VALUES (?, ?, ?, ?)",
                              (g.uid, b["route"], item, basis))
        if b.get("item"):
            c.execute("INSERT INTO checklist (user_id, route, item, basis) VALUES (?, ?, ?, ?)",
                      (g.uid, str(b.get("for") or "custom")[:80], str(b["item"])[:200], "added by you"))
        c.commit()
    elif request.method == "PATCH":
        b = _body()
        c.execute("UPDATE checklist SET done = ? WHERE id = ? AND user_id = ?", (1 if b.get("done") else 0, b.get("id"), g.uid))
        c.commit()
    elif request.method == "DELETE":
        c.execute("DELETE FROM checklist WHERE id = ? AND user_id = ?", (request.args.get("id"), g.uid))
        c.commit()
    rows = c.execute("SELECT id, route, item, basis, done FROM checklist WHERE user_id = ? ORDER BY route, id", (g.uid,)).fetchall()
    return jsonify({"items": [dict(r) for r in rows],
                    "note": "Built from each route's researched requirements. The official document list for most routes "
                            "hasn't been researched yet: check the official page. Files are not uploaded or stored."})


# ---------------------------------------------------------------------------
# Application tracker, timeline, alerts, export, deletion
# ---------------------------------------------------------------------------
@bp.route("/applications", methods=["GET", "POST", "PATCH", "DELETE"])
@login_required
def applications():
    c = db.conn()
    if request.method in ("POST", "PATCH"):
        b = _body()
        status = b.get("status", "planned")
        if status not in STATUSES:
            raise BadRequest(f"'status' must be one of {list(STATUSES)}")
        if request.method == "POST":
            c.execute("INSERT INTO applications (user_id, route, status, notes, updated) VALUES (?, ?, ?, ?, ?)",
                      (g.uid, str(b.get("route") or "")[:80], status, str(b.get("notes") or "")[:1000], _now()))
        else:
            c.execute("UPDATE applications SET status = ?, notes = COALESCE(?, notes), updated = ? WHERE id = ? AND user_id = ?",
                      (status, b.get("notes"), _now(), b.get("id"), g.uid))
        c.commit()
    elif request.method == "DELETE":
        c.execute("DELETE FROM applications WHERE id = ? AND user_id = ?", (request.args.get("id"), g.uid))
        c.commit()
    rows = c.execute("SELECT id, route, status, notes, updated FROM applications WHERE user_id = ? ORDER BY updated DESC", (g.uid,))
    return jsonify({"applications": [dict(r) for r in rows], "statuses": list(STATUSES)})


@bp.get("/timeline")
@login_required
def timeline():
    """Milestones for saved pathways: dated only where every duration before it is known."""
    from relocaitor import planner
    from relocaitor.web.validation import parse_profile
    start = request.args.get("start") or date.today().isoformat()
    try:
        d0 = date.fromisoformat(start)
    except ValueError:
        raise BadRequest("'start' must be YYYY-MM-DD") from None
    ids = [r["pathway_id"] for r in db.conn().execute("SELECT pathway_id FROM saved_pathways WHERE user_id = ?", (g.uid,))]
    plan = {p["id"]: p for p in planner.plan(parse_profile(_profile_dict()))["pathways"]}
    out = []
    for pid in ids:
        p = plan.get(pid)
        if not p:
            continue
        t, known, ms = 0.0, True, []
        for s in p["steps"]:
            years = s.get("years")
            if s.get("pr"):                      # a residence step's years are the wait until it is granted
                if years is None:
                    known = False
                else:
                    t += years
                ms.append({"label": s["label"], "pr": True, "date": _add_years(d0, t) if known else None})
            else:
                ms.append({"label": s["label"], "pr": False, "date": _add_years(d0, t) if known else None})
                if years is None:
                    known = False
                else:
                    t += years
        if known and p.get("years_to_citizenship"):
            ms.append({"label": "Citizenship (earliest, by the residence rule)", "pr": False,
                       "date": _add_years(d0, p["years_to_citizenship"])})
        out.append({"pathway": pid, "title": p["title"], "milestones": ms})
    return jsonify({"start": start, "timelines": out,
                    "note": "Dates appear only where every earlier duration is established; processing times are not included."})


def _add_years(d: date, years: float) -> str:
    days = round(years * 365.25)
    return date.fromordinal(d.toordinal() + days).isoformat()


@bp.get("/alerts")
@login_required
def alerts():
    from relocaitor.immigration import impact as I, store
    from relocaitor.web.validation import parse_profile
    seen = db.conn().execute("SELECT alerts_seen FROM users WHERE id = ?", (g.uid,)).fetchone()["alerts_seen"]
    prof = _profile_dict()
    if not any(v not in (None, "", False, [], 0) for k, v in prof.items() if k not in ("exclude_home", "visa_type")):
        return jsonify({"alerts": [], "since": seen, "note": "Save your profile to see which rule changes affect you."})
    hits = I.impact(parse_profile(prof), store.load("changes"), store.load_visas(), since=seen)
    if request.args.get("mark_seen") == "1":
        db.conn().execute("UPDATE users SET alerts_seen = ? WHERE id = ?", (date.today().isoformat(), g.uid))
        db.conn().commit()
    return jsonify({"alerts": hits, "since": seen})


@bp.get("/export")
@login_required
def export():
    c = db.conn()
    out = {"email": g.email, "profile": _profile_dict()}
    for t in ("shortlist", "saved_pathways", "checklist", "applications"):
        out[t] = [dict(r) for r in c.execute(f"SELECT * FROM {t} WHERE user_id = ?", (g.uid,))]
        for r in out[t]:
            r.pop("user_id", None)
    _audit(g.uid, "export")
    return jsonify(out)


@bp.delete("")
@login_required
def delete_account():
    b = _body()
    row = db.conn().execute("SELECT pw_hash FROM users WHERE id = ?", (g.uid,)).fetchone()
    if not check_password(str(b.get("password") or ""), row["pw_hash"]):
        return jsonify({"error": "Confirm with your password."}), 403
    db.conn().execute("DELETE FROM users WHERE id = ?", (g.uid,))      # cascades to every table
    db.conn().execute("UPDATE audit SET user_id = NULL WHERE user_id = ?", (g.uid,))
    db.conn().commit()
    return _set_cookie(jsonify({"deleted": True}), "", max_age=0)
