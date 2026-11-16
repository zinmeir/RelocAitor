"""
relocaitor/nlp/assistant.py — Free-form Q&A about a country ("Can I bring my spouse?").

Two modes:
1. LLM mode: if ANTHROPIC_API_KEY is set, the question goes to Claude together
   with this app's own data for that country, and Claude is told to answer only
   from that data. No extra Python dependency, it's a single HTTPS call.
2. Rules mode (default / fallback): keyword matching over the same data.
   Always works offline.

Environment variables:
    ANTHROPIC_API_KEY   enables LLM mode
    ANTHROPIC_MODEL     optional, defaults to claude-haiku-5-5
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from relocaitor.ranking.factors import FACTORS, factor_value

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-5-5"
MAX_QUESTION_LEN = 500

SYSTEM_PROMPT = (
    "You are the assistant inside RelocAitor, a country-relocation recommender. "
    "Answer the user's question about the given country using ONLY the JSON data provided. "
    "Scores are normalized 0-1 (higher is better, except cost_of_living where higher means "
    "more expensive). Money figures are approximate USD. Each visa has an 'eligibility' verdict "
    "for this user; use it. If the data doesn't cover the question, say so plainly and point "
    "to the official_url. Never invent visa rules, fees or numbers. Keep answers under 150 "
    "words, in plain prose. End with a one-line reminder to verify with the official source "
    "when the answer involves visas or legal status."
)


def llm_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def build_context(row, visa_info: dict, rank: Optional[int], total: int, profile: dict) -> dict:
    metrics = {meta["col"]: round(float(row[meta["col"]]), 2) for meta in FACTORS.values()}
    metrics["language_barrier"] = round(float(row["language_barrier"]), 2)
    return {
        "country": row["country_name"],
        "region": row["region"],
        "rank_for_user": rank,
        "countries_ranked": total,
        "match_score": round(float(row["score"]), 2),
        "metrics": metrics,
        "avg_net_salary_usd_month": int(row["salary_usd_month"]),
        "rent_1bed_city_centre_usd_month": int(row["rent_usd_month"]),
        "user_profile": {k: v for k, v in profile.items() if v not in (None, "", False, "any")},
        "official_url": visa_info.get("official_url"),
        "visas": [
            {k: v.get(k) for k in ("name", "type", "difficulty", "duration", "pr_route",
                                   "min_income", "min_investment", "summary", "note")}
            | {"eligibility": v["eligibility"]["status"],
               "eligibility_reasons": v["eligibility"]["reasons"]}
            for v in visa_info.get("visas", [])
        ],
    }


def ask_llm(question: str, context: dict, timeout: float = 20.0) -> str:
    return ask_llm_raw(
        SYSTEM_PROMPT,
        f"Data:\n{json.dumps(context, ensure_ascii=False)}\n\nQuestion: {question}",
        max_tokens=400, timeout=timeout,
    )


def ask_llm_raw(system: str, user: str, max_tokens: int = 400, timeout: float = 20.0) -> str:
    """One Messages API call; returns the reply text. Raises on network/HTTP errors."""
    body = {
        "model": os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


# ---------------------------------------------------------------------------
# Rules mode
# ---------------------------------------------------------------------------

TOPICS = [
    ("family",     ["spouse", "partner", "wife", "husband", "family", "kids", "children", "child", "dependent"]),
    ("pr",         ["pr", "permanent", "residency", "citizenship", "passport", "settle", "green card"]),
    ("visa",       ["visa", "permit", "qualify", "eligible", "apply", "move", "immigrat"]),
    ("cost",       ["cost", "rent", "expensive", "afford", "cheap", "price", "budget"]),
    ("salary",     ["salary", "pay", "earn", "income", "wage"]),
    ("job",        ["job", "career", "employ", "hiring", "work"]),
    ("safety",     ["safe", "crime", "danger", "security"]),
    ("healthcare", ["health", "hospital", "doctor", "medical", "insurance"]),
    ("english",    ["english", "language", "speak"]),
    ("climate",    ["weather", "climate", "hot", "cold", "rain", "sun", "winter"]),
    ("internet",   ["internet", "wifi", "broadband", "remote"]),
]


def _detect(question: str) -> list:
    q = f" {question.lower()} "
    found = []
    for topic, words in TOPICS:
        for w in words:
            # whole-word match for short tokens like "pr", substring for stems
            if (len(w) <= 3 and f" {w} " in q.replace("?", " ").replace(",", " ")) or (len(w) > 3 and w in q):
                found.append(topic)
                break
    return found


def _visa_line(v: dict) -> str:
    status = v["eligibility"]["status"]
    tag = {"eligible": "", "conditional": " (conditional)", "ineligible": " (you don't currently qualify)"}[status]
    return f"{v['name']}: {v['difficulty'].lower()}, PR: {v['pr_route'].lower()}{tag}"


def answer_with_rules(question: str, row, visa_info: dict, rank, total) -> str:
    name = row["country_name"]
    visas = visa_info.get("visas", [])
    topics = _detect(question)
    parts = []

    for t in topics[:3]:
        if t == "family":
            fam = [v for v in visas if v["type"] in ("family", "free")]
            if fam:
                parts.append(f"Family routes in {name}: " + "; ".join(_visa_line(v) for v in fam) + ".")
            else:
                parts.append(f"No dedicated family or partner visa is recorded for {name}. Many work "
                             f"visas let dependants join, but check the official source.")
        elif t == "pr":
            pr = [v for v in visas if v["pr_route"] in ("Yes", "Eventually")]
            if pr:
                parts.append("Routes that can lead to permanent residency: "
                             + "; ".join(_visa_line(v) for v in pr) + ".")
            else:
                parts.append(f"None of the recorded {name} visas lead to permanent residency.")
        elif t == "visa":
            ok = [v for v in visas if v["eligibility"]["status"] == "eligible"]
            if ok:
                parts.append(f"Based on your profile you look eligible for {len(ok)} of {len(visas)} "
                             f"recorded routes: " + "; ".join(_visa_line(v) for v in ok[:4]) + ".")
            elif visas:
                parts.append(f"Based on what you entered, you don't clearly qualify for any of the "
                             f"{len(visas)} recorded routes. Check the reasons on each visa card.")
            else:
                parts.append(f"No visa pathways are recorded for {name}.")
        elif t == "cost":
            parts.append(f"A 1-bed city-centre flat is about ${row['rent_usd_month']:,.0f}/mo; "
                         f"overall affordability scores {factor_value(row, 'cost'):.2f}/1.")
        elif t == "salary":
            parts.append(f"The average net salary is roughly ${row['salary_usd_month']:,.0f}/mo "
                         f"(salary score {row['average_salary']:.2f}/1).")
        else:
            meta = FACTORS[t]
            parts.append(f"{meta['label']} scores {factor_value(row, t):.2f}/1 in {name}.")

    if not parts:
        rank_txt = f" It ranks #{rank} of {total} for your priorities." if rank else ""
        parts.append(f"I can answer questions about {name}'s visas, PR routes, family options, "
                     f"costs, salaries, safety, healthcare, English, climate and internet.{rank_txt}")

    if any(t in ("family", "pr", "visa") for t in topics):
        parts.append("Visa rules change often, so verify with the official immigration portal.")
    return " ".join(parts)


def answer(question: str, row, visa_info: dict, rank, total, profile: dict) -> dict:
    question = (question or "").strip()[:MAX_QUESTION_LEN]
    if llm_enabled():
        try:
            text = ask_llm(question, build_context(row, visa_info, rank, total, profile))
            if text:
                return {"answer": text, "source": "llm"}
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as err:
            fallback = answer_with_rules(question, row, visa_info, rank, total)
            return {"answer": fallback, "source": "rules",
                    "warning": f"LLM unavailable ({type(err).__name__}); used built-in rules."}
    return {"answer": answer_with_rules(question, row, visa_info, rank, total), "source": "rules"}
