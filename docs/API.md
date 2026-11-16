# API

JSON in, JSON out. Errors: `400 {"error": "..."}` for invalid input, `404` for unknown countries,
`401`/`403` for sign-in and CSRF, `429` when rate-limited. A `profile` object is accepted by every
endpoint that evaluates eligibility:

```json
{"nationality": "PAK", "monthly_income": 2500, "investment_budget": 50000, "occupation": "healthcare",
 "age": 34, "partner": true, "children": 2, "education": "master", "experience_years": 3,
 "english": "B2", "german": "A1", "visa_type": "skilled", "require_pr": false, "max_difficulty": "Moderate",
 "only_qualifying": false, "exclude_home": true, "exclude_countries": ["USA"]}
```
`education`: secondary | diploma | bachelor | master | doctorate. `english`, `german`: CEFR A1–C2.
Money is US dollars per month (income) or in total (savings).

## Discover (existing, unchanged)

| Endpoint | Purpose |
|---|---|
| `GET /api/meta` | Factors, presets, regions, visa types, nationalities, currencies, scales, data status per visa |
| `POST /api/score` | Ranked countries (compatibility, not success probability) |
| `POST /api/insights` | One country: explanation, breakdown, visas with eligibility, costs and timelines |
| `POST /api/compare` · `/api/confidence` · `/api/pathways` · `/api/preferences` · `/api/search` · `/api/refine` · `/api/visas` · `/api/ask` | As before |

## Immigration intelligence

| Endpoint | Purpose |
|---|---|
| `GET /api/immigration/routes?country=ISO3` | 24 fields per route with value, status, sources, check date |
| `GET /api/immigration/changes?since=DATE` | Logged rule changes |
| `GET /api/immigration/sources` | Official source registry |
| `POST /api/immigration/impact` | `{profile, since}` → changes that affect this person, verdict before/after |

## Pathways, money, career, dimensions, assistant

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/plan` | `{profile, countries?: [ISO3], study_years?}` | Ranked routes to permanent residence (single and multi-stage), unknowns, risk, why #1 beats #2 |
| `POST /api/plan/whatif` | `{profile, changes: {"english": "B2"}}` | Routes that open, close or improve, by re-running the rules |
| `POST /api/finance/simulate` | `{country, gross_monthly_usd?, tax_rate_pct?, rent_usd?, other_spend_usd? \| home_spend_usd + home_country, extra_monthly_usd?, flights_usd?, visa_fee_usd?, deposit_months?, emergency_months?, assumptions?}` | Monthly lines with status, one-off costs, 1/3/5/10-year projections in three scenarios, unknowns |
| `POST /api/finance/compare` | Same plus `countries` (2–4) | One simulation per country |
| `POST /api/career` | `{profile, countries (1–5)}` | Shortage lists, indicators, work routes, skills roadmap |
| `GET /api/career/jobs?country=ISO3&field=tech` | | Live vacancies when a job API is configured, otherwise `enabled: false` |
| `POST /api/dimensions` | `{country, profile, weights?}` | Six separate scores with their basis |
| `POST /api/assistant` | `{question, country, profile, share_profile_with_ai?}` | Answer, mode (rules or llm), agents used, tool steps, warnings, sources |

## My relocation (`/api/me`, session cookie; send `X-CSRF-Token` on changes)

| Endpoint | Purpose |
|---|---|
| `POST /api/me/register` · `/login` · `/logout`, `GET /api/me` | Account and session (`csrf` returned) |
| `GET/PUT /api/me/profile` | Encrypted profile |
| `GET/POST/DELETE /api/me/shortlist` | Saved countries |
| `GET/POST/DELETE /api/me/pathways` | Saved pathways (re-planned with your current profile) |
| `GET /api/me/timeline?start=DATE` | Milestone dates where every earlier duration is known |
| `GET/POST/PATCH/DELETE /api/me/checklist` | Document checklist built from route requirements, plus your own items |
| `GET/POST/PATCH/DELETE /api/me/applications` | Tracker: planned, preparing, ready, submitted, awaiting_decision, approved, rejected, completed |
| `GET /api/me/alerts?mark_seen=1` | Logged rule changes that affect your saved profile |
| `GET /api/me/export`, `DELETE /api/me` | Download all your data; delete the account (password required) |
