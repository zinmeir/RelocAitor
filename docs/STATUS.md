# Implementation status

Updated 16 November 2026, after Phases 1–8. Labels follow the brief: **Done** (implemented and tested),
**Partial**, **Prototype**, **Needs external API**, **Needs human verification**, **Not started**.
Tests: 297 unit/API/parity, 39 browser.

| Phase | Capability | Status | What exists, and what doesn't |
|---|---|---|---|
| 1 | Immigration data model, per-field status, versions, change log, proposals, verification, source registry, impact | Done | `relocaitor/immigration/`. 117 routes × 24 fields. Nothing is verified yet: that takes a person. |
| 1 | Official page monitor | Prototype | Works offline in tests; never run against live sites from this environment. |
| 2 | Education, experience and language requirements in the rules | Done | `data/rules.json` (`rank_at_least`, `language`), Python and browser engines, parity-tested. |
| 2 | Requirement data | Partial | Researched from official pages for UK Skilled Worker (English B2), Canada FSW (1 year, CLB 7), Germany Blue Card (degree). 114 routes still unknown. |
| 2 | Germany Blue Card salary update | Needs human verification | Proposal waiting in `data/immigration/proposals/` (€50,700 a year). Run `python -m relocaitor.immigration approve`. |
| 3 | Pathway optimizer: single and multi-stage routes, ranking, comparison, risk | Done | `relocaitor/planner/`. Three researched multi-stage pathways (Canada study→PGWP→CEC, UK student→Graduate→Skilled Worker→settlement, Germany Blue Card→settlement) plus every route with a researched time to residence. |
| 3 | Counterfactual planning (income, savings, education, language, experience, age) | Done | `POST /api/plan/whatif`. |
| 3 | More transitions (nomad→residence, business→residence, family) | Needs human verification | Only add with an official source. |
| 4 | Take-home pay, costs, one-off costs, 1/3/5/10-year projections in three scenarios, comparison | Done | `relocaitor/finance/`. Tax: OECD Taxing Wages 2026 (38 countries, rate at the average wage). |
| 4 | Tax outside the OECD, tax by income band, family tax | Needs external API | No sourced dataset here; the simulator says so and accepts your own rate. |
| 4 | City-level costs | Partial | 47 cities with temperatures and US price levels; city rent and costs aren't sourced. |
| 5 | Career intelligence: shortage lists, unemployment, work routes, skills roadmap | Done | `relocaitor/career/`. Shortage lists for 4 countries. |
| 5 | Live vacancies | Needs external API | Adzuna connector; off without `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`. |
| 5 | Salary ranges by occupation, qualification recognition | Not started | Needs sourced data (national wage statistics, recognition databases). |
| 6 | Orchestrator with immigration, pathway, financial, career, lifestyle and verification agents | Done | `relocaitor/agents/`: tool permissions, profile isolation, timeout, retry, call limit, logs, sources, number checking of LLM text. |
| 6 | LLM phrasing | Needs external API | Uses `ANTHROPIC_API_KEY` if set and the person consents; rule-based answers otherwise. |
| 7 | Accounts, encrypted profile, shortlist, saved pathways, checklist, tracker, timeline, alerts, export, deletion | Done | `relocaitor/workspace/` + `/workspace`. SQLite. |
| 7 | Document upload and storage | Not started | Deliberately not built: needs encrypted object storage, malware scanning and a retention policy. |
| 7 | Email verification, password reset, 2FA, email alerts | Not started | Needs an email service. |
| 8 | Six separate dimensions | Done | `relocaitor/ranking/dimensions.py`, shown on each country's Overview. |
| 8 | Light theme, new sections, My relocation link | Done | |
| 8 | Structured logs, rate limits, security headers, deployment docs | Done | `relocaitor/web/security.py`, `docs/DEPLOY.md`. An error-monitoring service (e.g. Sentry) isn't wired: it needs an account. |
| 8 | React/TypeScript, FastAPI, PostgreSQL, Redis | Not started | Not installable here and not yet needed; see `docs/ARCHITECTURE_AUDIT.md`. |
| — | Real-world benchmark from independently reviewed profiles | Needs human verification | Cannot be simulated. |

## Immigration field coverage (117 routes)

Regenerate with `python -m relocaitor.immigration report`. Verified: 0 everywhere. Sourced from official pages:
fees 25, processing time 7, residence timeline 12, dependants 9, language 2, education 1, experience 1,
age 1. Citizenship from a secondary source: 109. Minimum income, investment, duration and difficulty are
unsourced estimates on all routes. Savings, documents, renewal, residence rules, spouse work rights, tax
and application pages: unknown everywhere.

## Decisions recorded

- No stack migration (see the audit). Everything new is a package inside the Flask app.
- Eligibility, money and time are computed by code from data; LLMs only phrase results.
- A route that is "eligible" only on passport and money ranks with conditional routes, because its main
  requirements are unchecked.
- New server-only features are hidden or labelled in the static build rather than ported twice.
