# Architecture audit

*Written 16 November 2026, before the Global Mobility Platform work began. Every number below was
measured in the repository on that date. File names are as they were then: the code has since moved into
the `relocaitor` package (see the README's project structure).*

## 1. What exists and works

| Area | Where | State |
|---|---|---|
| Country ranking | `scoring.py`, `engine.py`, `factors.py` | Weighted sum over 9 factors scaled 0–1; explainable per-factor points. Tested. |
| Visa eligibility | `eligibility.py` + `data/rules.json` | Rules are data, read by Python and by the browser build. Passport, income, savings, age, family, job list, free-movement blocs. |
| Gap reasoning | `pathways.py` | Re-runs the rules with one input changed ("earn $370 more"). Single-step only. |
| Confidence | `confidence.py` | 400 Monte Carlo scenarios over weights and data reliability. |
| Prompt understanding | `search.py`, `refine.py`, `ml/` | Rules, a trained classifier, sentence embeddings, optional LLM. Measured on held-out data. |
| Preference learning | `ml/` (Bradley–Terry) | 8-question quiz → weights. |
| Country landscape | `pipeline/clusters.py` | PCA + k-means, stability-tested. |
| Data pipeline | `pipeline/` | World Bank + WHO + manual tables → `countries.csv` with per-value provenance; 196-country world list; schema validation. |
| Visa costs and timelines | `pipeline/visa_details.py` | 28 of 117 routes researched from official pages, each with a source URL and check date. |
| Currencies | `pipeline/currency.py` | ECB daily + World Bank annual rates, 130 currencies. |
| Frontend | `templates/index.html`, `static/js/*.js` | Vanilla JS, no build step; four result views; keyboard and touch accessible. |
| Static build | `preview/` | The whole app without a server (GitHub Pages); `mock_api.js` ports the API and a parity test proves identical answers on 359 requests. |
| Tests | `tests/` | 265 unit/API/parity tests, 35 Playwright browser tests, CI on GitHub Actions. |

## 2. API contracts (kept stable)

`GET /`, `/api/health`, `/api/meta`; `POST /api/score`, `/api/insights`, `/api/confidence`,
`/api/pathways`, `/api/compare`, `/api/ask`, `/api/preferences`, `/api/refine`, `/api/search`,
`/api/visas`. All new endpoints are additive under `/api/immigration/…`; no existing response shape
changes, so the browser build and the parity test stay valid.

## 3. Data schemas

`data/schemas/` validates visas, rules, cities, occupations, fx, currencies, lexicon and version.
`visas.json` is the weak point: 117 routes, but only the fields `type, name, difficulty, duration,
pr_route, min_income, summary, min_investment` exist on every route, and those core values were curated
by hand **with no per-field source**. `last_verified` is `null` on all 117. Research fields (fee,
processing time, years to PR, family, age) exist on 28.

## 4. Scoring logic

One compatibility score per country. It mixes lifestyle factors with `pr_ease` (an editorial
estimate) in a single sum, so "how pleasant" and "how reachable" are not separated. The UI already
avoids calling it a probability; the brief's six-dimension split (Phase 8) builds on this.

## 5. Eligibility logic

Deterministic and rule-driven, which is the right foundation. Gaps: education, work experience,
language tests, sponsorship and points systems are not modelled, so "Likely eligible" overstates
certainty for skilled routes. These need new profile fields **and** researched thresholds per route;
neither can be invented.

## 6. ML components

Five models, each evaluated on held-out data, one disabled because it did not beat the rules. None of
them makes legal or financial decisions. Keep as is.

## 7. Frontend architecture

No build step, which keeps "run with one command" and the static build simple. `app.js` is now
2,000 lines in one closure: the main maintainability risk. Splitting it into ES modules (no bundler
needed) is cheaper than a React rewrite and keeps the static build working.

## 8. Tests

Strong for the size of the project: parity, schema, pipeline reproducibility, browser journeys.
Missing for the new brief: rule versioning, source status, change detection, impact recalculation,
tax, projections, auth and data isolation.

## 9. Technical debt

1. **Unsourced core visa values** (§3). The largest correctness risk in the product.
2. **No history.** When a figure changes in `visas.json` the old value is lost; nobody can see what
   changed or whom it affects.
3. **Two implementations of the API** (Python and `mock_api.js`). Mitigated by the parity test, but
   every engine feature costs twice. New engines (finance, pathways) should be data-driven like
   `rules.json` so the browser port stays small, or be server-only and hidden in the static build.
4. **`app.js` size** (§7).
5. **No persistence or users.** Saved searches live in `localStorage`.

## 10. Missing capabilities against the brief

Verified/versioned immigration records, change monitoring, multi-stage pathways, education /
experience / language requirements, tax and take-home pay, city-level costs beyond 47 cities,
career data beyond 9 fields and 4 shortage lists, agents, accounts and a workspace, light theme.

## Stack decision

The brief recommends FastAPI, SQLAlchemy, PostgreSQL, Redis, React and LangGraph "if migration is
justified". It is not justified yet, and it is not possible in this environment:

- None of FastAPI, SQLAlchemy, LangGraph, Redis or a Postgres driver is installed, and package
  installation is blocked here.
- The project's standing requirements are one-command local runs and a no-server GitHub Pages build.
  A React/TypeScript toolchain and a database server break both.
- The hard problems are data correctness and modelling, not framework limits. Flask serves the current
  load comfortably.

So the platform grows as a **modular monolith on Flask**: new Python packages with clear boundaries
(`immigration/` first), JSON files under schema validation for reference data, and SQLite (standard
library) when user accounts arrive in Phase 7. Each boundary is written so it could later move behind
FastAPI or into Postgres without changing its callers. This is revisited at Phase 7 and Phase 8.
