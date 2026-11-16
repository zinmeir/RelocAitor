# Immigration data: statuses, versions, changes and how updates get in

Code: `immigration/`. Data: `data/immigration/`. Schemas: `data/schemas/imm_*.schema.json`.

## One record per route, one status per field

`python -m immigration build` turns `data/visas.json` (what the eligibility engine reads) into
`data/immigration/records.json`. Every one of the 117 routes reports the same 24 fields, grouped as
requirements, costs, timeline, rights and identity (`immigration/catalogue.py`). A field we have never
collected is still listed as **unknown**, so gaps are visible instead of silently missing.

| Status | Meaning | How a value gets it |
|---|---|---|
| verified | A named person checked this exact value against the official page | `approve` or `verify`, recorded in `verifications.json` with a hash of the value |
| sourced | Read from an official page named in the record, not yet signed off | Research merged by `pipeline/visa_details.py`, including AI-assisted research |
| third_party | From a secondary source | Citizenship rules (Wikipedia's naturalisation table) |
| estimated | Curated before per-field sources were recorded, or an editorial rating | The original core values (min income, investment, duration, PR route, difficulty) |
| unknown | No value | Not collected yet |
| outdated | Sourced or verified, but older than the field's freshness window | Computed when read: fees and income 365 days, processing times 180, others 730 |

Rules that keep the labels honest:
- A model can propose a value; it can never verify one. `approve` and `verify` refuse model names,
  and `pipeline.validate` fails if a sign-off by a model ever appears in the file.
- A verification is tied to a hash of the value. If the value later changes, the field drops back to
  its underlying status with a note that the old sign-off no longer matches.
- `difficulty` is always an editorial rating, never "sourced".

The baseline on 16 November 2026 (`python -m immigration report`): nothing verified; fees sourced on
25 routes, processing times on 7, PR timelines on 12, family rules on 9; citizenship from a secondary
source on 109; minimum income, investment, duration and PR route are unsourced estimates on all 117;
education, experience, language, savings, documents, renewal, residence rules, spouse work rights,
tax and application pages are unknown everywhere.

## Versions and the change log

Each route has a `rule_version` that starts at 1 and increases whenever any of its values changes.
`build` compares the new records with the previous ones and appends every difference to
`changes.json`: the route, the brief's category (income requirement, savings, investment, fee,
processing time, permanent residency rules, nationality eligibility, new route, removed or suspended
route…), the direction for numbers, the previous and new value, the sources, the detection date and a
verification status. A status change alone (a sign-off) is not a rule change and is not logged.

`POST /api/immigration/impact` takes a profile and recomputes eligibility for each logged change with
the real rules, once with the old value and once with the new: `now_eligible`, `no_longer_eligible`,
`now_conditional`, or `affects_your_route` (a fee or timeline changed on a route you can use).

## How an update gets in

```bash
# 1. Write a proposal (a person, a script or an AI research run):
#    data/immigration/proposals/uk-skilled-2027.json
#    {"route": "GBR-skilled-worker-visa", "changes": {"fee": {...}},
#     "sources": ["https://www.gov.uk/skilled-worker-visa/how-much-it-costs"],
#     "checked": "2027-04-01", "evidence": "<the exact wording on the page>", "proposed_by": "..."}
python -m immigration review                          # diff + anything that blocks approval
python -m immigration approve uk-skilled-2027.json --by "Your Name"   # the human step
python -m pipeline.visa_details                       # merge approved updates into visas.json
python -m immigration build                           # version, log changes, refresh sources
python -m pipeline.validate && python -m pytest -q --ignore=tests/e2e
```

Proposals are refused when the route or field is unknown, a source isn't https or is a secondary
site, the check date is missing, or there is no quoted evidence. To confirm a value without changing
it: `python -m immigration verify ROUTE FIELD --by NAME --source URL`.

## The official source registry and page monitor

`sources.json` lists every publisher the data cites (71 hosts today): official or third-party,
which countries and routes rely on it, and how it may be read (`manual` for all of them: none has
an API or feed agreement yet). Notes and access methods a person adds survive rebuilds.

`python -m immigration monitor` fetches each cited page that robots.txt allows, fingerprints its
visible text and reports pages that changed since the last run, with the routes that cite them. It
does not extract figures: immigration pages change layout often and many render with JavaScript, so
automated extraction would produce confident wrong numbers. A changed page is a prompt for a person
to re-check, through the proposal workflow. It needs internet access and was not run in the
environment where it was built; it is tested with a fake fetcher.
