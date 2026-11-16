# Roadmap: RelocAitor as a global mobility intelligence platform

Phases follow the brief's order. Each ends with: tests green, regressions fixed, docs and
`docs/STATUS.md` updated, existing features re-checked. Order is by risk: data correctness first,
because every later engine (pathways, finance, agents) inherits whatever the data gets wrong.

## Status

All eight phases have a working, tested implementation (16 November 2026); see `docs/STATUS.md` for
what each one covers and what still needs data, people or external services. The plan below is kept as
written, with the remaining work listed per phase in STATUS.

## Phase 1 — Immigration data foundation
- `immigration/` package: one field catalogue covering every attribute in brief §2.1.
- Every field of every route carries a **status**: verified, officially sourced (awaiting
  verification), third-party, estimated, unknown or outdated, plus its source and check date.
- Verified only through a recorded human sign-off. Research done by an AI reading an official page
  is "officially sourced", never "verified".
- Official source registry, one entry per publisher, with how it may be read (manual, API, feed).
- Versioned records: each route has a rule version that increases when any field changes; history
  is kept.
- Change detection with the brief's categories, previous/new values, source, date, verification
  status and affected routes; impact recalculation for a profile.
- Proposal → review → approve workflow so updates enter only through a human step.
- Page monitor: hashes official pages (respecting robots.txt) to flag routes for re-checking.
- Data status shown on every visa card.

## Phase 2 — Immigration intelligence content
- Research the 89 unresearched routes through the proposal workflow (no guessed values).
- Add requirement fields to the eligibility rules: education, experience, language level,
  sponsorship, with per-route thresholds as they are researched.
- Profile fields for education, experience and languages.
- Staleness penalties feed the confidence model.

## Phase 3 — Pathway optimizer
- A transition graph (`data/transitions.json`): which visa can legally lead to which, under what
  conditions (e.g. Canada study permit → PGWP → Express Entry). Only researched transitions.
- Search over the graph with deterministic eligibility at each stage; rank by time, cost, risk.
- Counterfactuals extended to education, language and experience.

## Phase 4 — Financial simulator
- Tax and social contribution tables per country (sourced, dated, versioned like visas).
- Take-home pay, cost lines (rent, utilities, food, transport, health, school), moving costs.
- 1/3/5/10-year projections with explicit assumptions and three scenarios.
- Requires: a sourced tax dataset. Without one, the simulator says what it cannot compute.

## Phase 5 — Career intelligence
- Occupation profiles mapped to ISCO codes; shortage lists for more countries; salary ranges
  where an official statistic exists; language and recognition requirements per occupation.
- Live vacancies only through a real job API, clearly separated from occupation statistics.

## Phase 6 — Orchestration
- A custom orchestrator (LangGraph is not installable here) with typed tool calls into the
  deterministic engines, per-agent tool permissions, timeouts, retries, logs and source attribution.
- Agents exist only where they own a tool: immigration, finance, career, lifestyle, pathway,
  verification. LLMs explain and research; they never decide eligibility or compute money.

## Phase 7 — Relocation command center
- Accounts (SQLite to start), encrypted profile storage, shortlist, saved pathways, document
  checklists generated from route requirements, application tracker, timeline.
- Alerts when a change in Phase 1's log affects a saved profile.

## Phase 8 — Product and infrastructure
- Six separate scores (lifestyle, immigration, financial, career, settlement, family).
- Light theme; navigation for the new sections; split `app.js` into modules.
- Monitoring, rate limiting, structured logs, deployment docs.

## Things that need people or services outside this repository

| Need | Why |
|---|---|
| Human reviewers | To move any value from "officially sourced" to "verified". |
| A tax data source | Per-country tax tables (e.g. OECD Taxing Wages, national calculators). |
| A job vacancy API | Real vacancies (e.g. EURES, Adzuna); otherwise only occupation statistics. |
| An LLM API key | Agents' explanation layer; everything deterministic works without it. |
| Independently reviewed profiles | The real-world benchmark the brief asks for cannot be simulated. |
