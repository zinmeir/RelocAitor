"""
agents — a small, explicit orchestrator over RelocAitor's deterministic engines.

Each agent owns a fixed set of tools (functions into eligibility, the immigration records, the pathway
optimizer, the finance simulator and career intelligence). The orchestrator:

1. understands the request (which country, which topics) with deterministic matching,
2. picks the agents that own those topics,
3. runs their tools under per-agent permissions, a timeout and one retry, logging every call,
4. passes all results to the verification agent, which flags unknown, estimated, outdated and
   third-party data and checks that any LLM wording only uses numbers that came from a tool,
5. writes the answer: from templates, or with an LLM if a key is set AND the person consented to
   sharing their profile with it. If the LLM text fails verification, the template answer is used.

LLMs never decide eligibility or compute money: they only phrase results that tools produced.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Callable, Optional

from eligibility import Profile

log = logging.getLogger("relocaitor.agents")
TOOL_TIMEOUT_S = 8.0
MAX_TOOL_CALLS = 12
_pool = ThreadPoolExecutor(max_workers=4)


# ---------------------------------------------------------------------------
# Tools: thin wrappers over the deterministic engines
# ---------------------------------------------------------------------------
def _t_visas(country: str, profile: Profile, **_):
    import visas as V
    info = V.visas_for_profile(country, profile)
    return {"visas": [{"name": v["name"], "type": v["type"], "status": v["eligibility"]["status"],
                       "reasons": v["eligibility"]["reasons"], "qualifies": v["qualifies"]} for v in info["visas"]],
            "sources": [info["official_url"]] if info.get("official_url") else []}


def _t_records(country: str, **_):
    from datetime import date
    from immigration import records as R, store
    recs = [R.with_current_status(r, date.today()) for r in store.load("records", {}).get("routes", {}).values()
            if r["country"] == country]
    return {"routes": [{"name": r["name"], "summary": r["summary"]["counts"]} for r in recs]}


def _t_changes(country: str, profile: Profile, **_):
    from immigration import impact as I, store
    hits = [x for x in I.impact(profile, store.load("changes"), store.load_visas()) if x["route"].startswith(country + "-")]
    return {"changes": hits}


def _t_plan(country: str, profile: Profile, **_):
    import planner
    res = planner.plan(profile, countries=[country])
    return {"pathways": res["pathways"][:3], "note": res["note"]}


def _t_finance(country: str, profile: Profile, **_):
    import finance
    body = {"country": country}
    return finance.simulate(body)


def _t_career(country: str, profile: Profile, **_):
    import career
    return career.career_report(profile, [country])


def _t_lifestyle(country: str, **_):
    from data import load_countries
    row = load_countries().set_index("country_code").loc[country]
    keys = ["safety", "healthcare", "climate", "internet", "english"]
    return {"scores": {k: round(float(row[k]), 2) for k in keys}, "main_city": row.get("main_city"),
            "avg_temp_c": None if row.get("avg_temp_c") != row.get("avg_temp_c") else row.get("avg_temp_c")}


@dataclass
class Agent:
    name: str
    topics: tuple
    tools: dict                     # tool name -> function
    profile_access: bool = True     # may this agent's tools see the person's profile?
    responsibilities: str = ""


AGENTS = {
    "immigration": Agent("immigration", ("visa", "eligib", "qualif", "permit", "passport", "spouse", "bring my"),
                         {"visas": _t_visas, "records": _t_records, "changes": _t_changes},
                         responsibilities="Visa eligibility, requirements, data status and rule changes"),
    "pathway": Agent("pathway", ("pr", "permanent", "residen", "citizen", "how long", "path", "plan", "steps", "settle"),
                     {"plan": _t_plan}, responsibilities="Multi-stage routes to residence and citizenship"),
    "financial": Agent("financial", ("cost", "rent", "expensive", "afford", "save", "salary", "tax", "money", "cheap"),
                       {"finance": _t_finance}, profile_access=False,
                       responsibilities="Tax, take-home pay, living costs and projections"),
    "career": Agent("career", ("job", "career", "work", "skill", "demand", "occupation", "hire"),
                    {"career": _t_career}, responsibilities="Shortage lists, labour indicators and skills gaps"),
    "lifestyle": Agent("lifestyle", ("safe", "crime", "health", "weather", "climate", "warm", "internet", "english", "school", "family"),
                       {"lifestyle": _t_lifestyle}, profile_access=False,
                       responsibilities="Safety, healthcare, climate, infrastructure"),
}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
@dataclass
class Step:
    agent: str
    tool: str
    ok: bool
    ms: int
    error: Optional[str] = None


@dataclass
class Run:
    steps: list = field(default_factory=list)
    results: dict = field(default_factory=dict)


def route(question: str) -> list:
    q = question.lower()
    picked = [name for name, a in AGENTS.items() if any(re.search(rf"\b{re.escape(t)}", q) for t in a.topics)]
    return picked or ["immigration", "lifestyle"]


def call_tool(agent: Agent, tool: str, run: Run, **kwargs) -> None:
    if tool not in agent.tools:
        raise PermissionError(f"Agent '{agent.name}' may not call '{tool}'")
    if len(run.steps) >= MAX_TOOL_CALLS:
        raise RuntimeError("Tool call limit reached")
    if not agent.profile_access:
        kwargs["profile"] = Profile()          # this agent never sees personal data
    fn: Callable = agent.tools[tool]
    for attempt in (1, 2):
        t0 = time.perf_counter()
        try:
            out = _pool.submit(fn, **kwargs).result(timeout=TOOL_TIMEOUT_S)
            run.steps.append(Step(agent.name, tool, True, int((time.perf_counter() - t0) * 1000)))
            run.results[f"{agent.name}.{tool}"] = out
            return
        except FutureTimeout:
            err = "timeout"
        except Exception as e:          # tool failure: logged, retried once
            err = f"{type(e).__name__}: {e}"[:200]
        run.steps.append(Step(agent.name, tool, False, int((time.perf_counter() - t0) * 1000), err))
        log.warning("tool %s.%s failed (attempt %d): %s", agent.name, tool, attempt, err)


def verify(run: Run) -> list:
    """The verification agent: flag weak data in the results."""
    warnings = []
    for key, res in run.results.items():
        if key == "immigration.records":
            for r in res["routes"]:
                c = r["summary"]
                if not c.get("verified"):
                    warnings.append(f"No value for {r['name']} has been verified by a person yet.")
                    break
        if key == "financial.finance" and res.get("unknown"):
            warnings.append("Not known, so left out of totals: " + ", ".join(res["unknown"]) + ".")
        if key == "pathway.plan":
            for p in res["pathways"]:
                if p.get("unchecked"):
                    warnings.append(f"{p['title']}: not checked against " + ", ".join(p["unchecked"]).lower() + ".")
    failed = [s for s in run.steps if not s.ok]
    if failed and not any(s.ok for s in run.steps):
        warnings.append("The engines didn't answer; try again.")
    return list(dict.fromkeys(warnings))


def _numbers(text: str) -> set:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def numbers_supported(text: str, run: Run) -> bool:
    """Every number in generated text must appear in some tool result (years and list numbering excepted)."""
    import json
    facts = _numbers(json.dumps(run.results, default=str))
    for n in _numbers(text):
        n2 = n.rstrip(".")
        if n2 in facts or len(n2) <= 1 or (n2.isdigit() and 1900 <= int(n2) <= 2100):
            continue
        if any(f.startswith(n2) or n2.startswith(f.split(".")[0] + ".") for f in facts if f):
            continue
        return False
    return True


def money(x) -> str:
    return f"${x:,.0f}"


def template_answer(run: Run, country_name: str) -> str:
    parts = []
    r = run.results
    if "immigration.visas" in r:
        vs = r["immigration.visas"]["visas"]
        ok = [v["name"] for v in vs if v["qualifies"]]
        parts.append(f"In {country_name}, {len(ok)} of {len(vs)} researched visas look open to you"
                     + (f": {', '.join(ok)}." if ok else "."))
        for v in vs:
            if v["status"] != "eligible" and v["reasons"]:
                parts.append(f"{v['name']}: {v['reasons'][0]}")
                break
    if "immigration.changes" in r and r["immigration.changes"]["changes"]:
        c = r["immigration.changes"]["changes"][0]
        parts.append(f"A recent rule change affects you: {c['label'] or c['kind']} on {c['route']} ({c['effect'].replace('_', ' ')}).")
    if "pathway.plan" in r and r["pathway.plan"]["pathways"]:
        p = r["pathway.plan"]["pathways"][0]
        y = p["years_to_pr"]
        when = ("permanent residence directly" if not y["unknown"] and y["min"] == 0 else
                f"about {y['min']:g} years" if not y["unknown"] else "a time we can't fully work out yet")
        parts.append(f"The best-ranked route to permanent residence is {p['title']}: {when}" + ("" if when.startswith("permanent") else " to residence")
                     + (f", citizenship from about {p['years_to_citizenship']:g} years" if p.get("years_to_citizenship") else "") + ".")
    if "financial.finance" in r:
        f = r["financial.finance"]["monthly"]
        rent = next(x for x in f["lines"] if x["label"].startswith("Rent"))
        parts.append(f"Rent for a 1-bed city-centre flat is about {money(rent['usd'])}/mo (editorial estimate), "
                     f"against a typical net salary of about {money(f['net_usd'])}/mo.")
    if "career.career" in r:
        c = r["career.career"]["countries"][0]
        sl = c["shortage_list"]
        if sl and sl["field_listed"] is not None:
            parts.append(f"Your field is {'on' if sl['field_listed'] else 'not on'} the {sl['name']}.")
        if c["indicators"]["unemployment"]:
            u = c["indicators"]["unemployment"]
            parts.append(f"Unemployment is {u['pct']:.1f}% ({u['year']}, World Bank).")
        gap = r["career.career"]["skills_gap"]["roadmap"]
        if gap:
            parts.append(f"Most useful next step: {gap[0]['action']} (opens {gap[0]['opens'][0]['route']}).")
    if "lifestyle.lifestyle" in r:
        s = r["lifestyle.lifestyle"]["scores"]
        parts.append("On a 0–1 scale: safety " + f"{s['safety']:.2f}, healthcare {s['healthcare']:.2f}, "
                     f"climate {s['climate']:.2f}, internet {s['internet']:.2f}, English {s['english']:.2f}.")
    return " ".join(parts) or "I couldn't find anything for that question."


def run(question: str, country: str, profile: Profile, share_with_llm: bool = False,
        llm: Optional[Callable] = None) -> dict:
    from data import load_countries
    names = dict(zip(load_countries()["country_code"], load_countries()["country_name"]))
    if country not in names:
        raise ValueError(f"Unknown country '{country}'")
    picked = route(question)
    r = Run()
    for name in picked:
        agent = AGENTS[name]
        for tool in agent.tools:
            call_tool(agent, tool, r, country=country, profile=profile)
    warnings = verify(r)
    answer, mode = template_answer(r, names[country]), "rules"
    if llm and share_with_llm:
        import json
        facts = json.dumps(r.results, default=str)[:12000]
        try:
            text = llm("You explain relocation facts. Use ONLY the facts in the JSON. Never add numbers, "
                       "requirements or rules that aren't in it. Say what is unknown. Under 120 words.",
                       f"Question: {question}\nCountry: {names[country]}\nFacts: {facts}")
            if numbers_supported(text, r):
                answer, mode = text, "llm"
            else:
                warnings.append("The AI wording used a number not found in the data, so the rule-based answer is shown.")
        except Exception as e:          # LLM failures fall back to the template
            warnings.append(f"The AI service didn't answer ({type(e).__name__}); showing the rule-based answer.")
    sources = sorted({u for res in r.results.values() for u in _collect_sources(res)})
    log.info("assistant country=%s agents=%s steps=%d mode=%s", country, ",".join(picked), len(r.steps), mode)
    return {"answer": answer, "mode": mode, "agents": picked,
            "steps": [s.__dict__ for s in r.steps], "warnings": warnings, "sources": sources[:12]}


def _collect_sources(obj) -> list:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("source", "sources") and isinstance(v, str) and v.startswith("https://"):
                out.append(v)
            elif k == "sources" and isinstance(v, list):
                out += [u for u in v if isinstance(u, str) and u.startswith("https://")]
            else:
                out += _collect_sources(v)
    elif isinstance(obj, list):
        for x in obj:
            out += _collect_sources(x)
    return out
