# Architecture

One Flask application (a modular monolith). Each box below is a Python package or module with one job;
the arrows are the only calls between them. Reference data are versioned JSON/CSV files under schema
validation; user data live in SQLite.

```mermaid
flowchart LR
  subgraph Browser
    UI[index.html + app.js<br/>search, map, country panel]
    WS[workspace.html + workspace.js<br/>My relocation]
  end
  subgraph Flask app [app.py · security.py]
    API[/REST API/]
  end
  UI --> API
  WS --> API

  API --> RANK[engine · scoring · confidence<br/>compatibility ranking]
  API --> ELIG[eligibility + data/rules.json<br/>deterministic visa rules]
  API --> IMM[immigration/<br/>records · statuses · versions<br/>changes · proposals · monitor · impact]
  API --> PLAN[planner/<br/>multi-stage pathways · what-if]
  API --> FIN[finance/<br/>tax · costs · projections]
  API --> CAR[career/<br/>shortage lists · indicators · skills gap · jobs API]
  API --> DIM[dimensions.py<br/>six separate scores]
  API --> AG[agents/<br/>orchestrator · tool permissions · verification]
  API --> WSP[workspace/<br/>accounts · encrypted profiles · checklist · tracker]

  AG --> ELIG & IMM & PLAN & FIN & CAR
  AG -. optional, with consent .-> LLM[(Claude API)]
  CAR -. optional .-> JOBS[(Adzuna API)]
  PLAN --> ELIG
  IMM --> ELIG
  WSP --> PLAN & IMM
  WSP --> DB[(SQLite)]

  subgraph Data [data/ · versioned, schema-checked]
    VJ[visas.json] --- RJ[rules.json] --- TJ[transitions.json]
    IR[immigration/records.json · changes.json · sources.json]
    TX[finance/tax_oecd.json] --- CC[countries.csv + provenance.csv]
  end
  ELIG --- VJ
  IMM --- IR
  PLAN --- TJ
  FIN --- TX & CC
```

## Boundaries

| Module | Owns | Never does |
|---|---|---|
| `eligibility.py` + `data/rules.json` | Whether a profile meets a route's recorded requirements | Guess a requirement that isn't recorded |
| `immigration/` | What we know about each route, how sure we are, what changed | Mark anything verified without a person |
| `planner/` | Which routes chain to residence; time and cost from known steps | Assume a temporary visa leads to residence |
| `finance/` | Arithmetic over sourced rates, your inputs and stated assumptions | Invent tax rates or living costs |
| `career/` | Official lists, World Bank indicators, rule-based skill gaps | Mix vacancies with statistics or invent jobs |
| `agents/` | Choosing engines for a question, permissions, verification | Let an LLM decide eligibility or compute money |
| `workspace/` | Accounts and personal data | Store documents or share data with third parties |
| `preview/` | The no-server build: `mock_api.js` ports ranking, search and eligibility | Run accounts, pathways, finance, career or agents (they need the server) |

## Two runtimes

The static GitHub Pages build answers ranking, search, eligibility and the immigration data status in the
browser, proven identical to Python by the parity test. The platform features added after Phase 1
(pathways, money, career, dimensions, assistant, accounts) run on the server only; the static build says so
where they would appear.
