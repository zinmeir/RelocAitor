"""
pipeline/visa_details.py — Researched visa costs, timelines, family and age rules,
citizenship rules and shortage lists, merged into data/visas.json.

    python -m pipeline.visa_details          # merge (idempotent)
    python -m pipeline.visa_details --check  # fail if visas.json is out of date

Rules for what goes in here:
- Visa figures come from the official government page named in `sources`, read on
  CHECKED. Anything that could not be confirmed there is left out, not guessed:
  the app shows nothing rather than a guess.
- Citizenship residence periods are the exception: they come from Wikipedia's
  summary table of national nationality laws (a secondary source, labelled as
  such in the data and the UI), because no single official source covers 66 countries.
- Amounts are in the local currency. data/fx.json (ECB reference rates) is used
  only to show an approximate dollar figure next to them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VISAS = ROOT / "data" / "visas.json"
CHECKED = "2026-11-16"

WIKI_NATURALISATION = "https://en.wikipedia.org/wiki/Naturalization#Summary_by_country"

# ---------------------------------------------------------------------------
# Visa routes: (country, visa name) -> researched fields
# ---------------------------------------------------------------------------
GOVUK = "https://www.gov.uk"
VISAS_RESEARCH = {
    ("USA", "F-1 Student Visa"): {
        "fee": {"amount": 535, "currency": "USD", "note": "$185 visa application fee + $350 SEVIS fee"},
        "sources": ["https://ustraveldocs.com/qa/qa-niv-visafeeinfo.asp"],
    },
    ("USA", "IR-1/CR-1 Spouse Visa"): {
        "fee": {"amount": 325, "currency": "USD",
                "note": "Immigrant visa fee per person; the I-130 petition and affidavit review ($120) are extra"},
        "years_to_pr": 0,
        "sources": ["https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/fees/fees-visa-services.html"],
    },
    ("CAN", "Express Entry (FSW)"): {
        "fee": {"amount": 1590, "currency": "CAD", "note": "CAD 990 processing + CAD 600 right of permanent residence fee"},
        "years_to_pr": 0,
        "sources": ["https://ircc.canada.ca/english/information/fees/fees.asp"],
    },
    ("CAN", "Start-up Visa Program"): {
        "fee": {"amount": 2495, "currency": "CAD", "note": "CAD 1,895 processing + CAD 600 right of permanent residence fee"},
        "years_to_pr": 0,
        "sources": ["https://ircc.canada.ca/english/information/fees/fees.asp"],
    },
    ("CAN", "Study Permit + PGWP"): {
        "fee": {"amount": 150, "currency": "CAD", "note": "Study permit fee per person"},
        "sources": ["https://ircc.canada.ca/english/information/fees/fees.asp"],
    },
    ("CAN", "Spousal / Partner Sponsorship"): {
        "fee": {"amount": 1260, "currency": "CAD", "note": "Sponsorship, processing and right of permanent residence fees together"},
        "years_to_pr": 0,
        "sources": ["https://ircc.canada.ca/english/information/fees/fees.asp"],
    },
    ("GBR", "Skilled Worker Visa"): {
        "fee": {"amount": 819, "currency": "GBP",
                "note": "For up to 3 years (£1,618 for longer), plus the £1,035 a year health surcharge"},
        "years_to_pr": 5,
        "sources": [f"{GOVUK}/skilled-worker-visa/how-much-it-costs", f"{GOVUK}/indefinite-leave-to-remain"],
    },
    ("GBR", "Innovator Founder Visa"): {
        "fee": {"amount": 1357, "currency": "GBP", "note": "Applying from outside the UK"},
        "processing": "Usually within 3 weeks from outside the UK", "processing_weeks": 3,
        "years_to_pr": 3,
        "family": {"partner": True, "children": True},
        "sources": [f"{GOVUK}/innovator-founder-visa"],
    },
    ("GBR", "Student Visa + Graduate Route"): {
        "fee": {"amount": 558, "currency": "GBP",
                "note": "Plus the health surcharge. The Graduate visa lasts 2 years (18 months if you apply from 1 January 2027; 3 years after a PhD)"},
        "processing": "Usually within 3 weeks from outside the UK", "processing_weeks": 3,
        "sources": [f"{GOVUK}/student-visa"],
    },
    ("GBR", "Family Visa (Partner)"): {
        "fee": {"amount": 2064, "currency": "GBP", "note": "Plus the health surcharge, £2,587.50 per adult for 2½ years"},
        "processing": "Usually about 12 weeks from outside the UK", "processing_weeks": 12,
        "years_to_pr": 5,
        "sources": [f"{GOVUK}/uk-family-visa/how-much-it-costs", f"{GOVUK}/uk-family-visa/partner-spouse"],
    },
    ("IRL", "Critical Skills Employment Permit"): {
        "fee": {"amount": 1000, "currency": "EUR", "note": "90% refunded if the permit is refused"},
        "years_to_pr": 5,
        "family": {"partner": True, "children": True},
        "sources": ["https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/permit-types/critical-skills-employment-permit/"],
    },
    ("DEU", "EU Blue Card"): {
        "fee": {"amount": 75, "currency": "EUR", "note": "National (D) visa fee. Salary from €50,700 a year (€45,934 in shortage jobs) in 2026"},
        "years_to_pr": 1.75,
        "pr_note": "Settlement permit after 21 months with B1 German, or 27 months with A1",
        "family": {"partner": True, "children": True},
        "sources": ["https://www.make-it-in-germany.com/en/visa-residence/types/eu-blue-card",
                    "https://www.make-it-in-germany.com/en/visa-residence/procedure/entry-process"],
    },
    ("DEU", "Opportunity Card (Job Search)"): {
        "fee": {"amount": 75, "currency": "EUR", "note": "National (D) visa fee. Needs €1,091 a month in a blocked account (2026)"},
        "sources": ["https://www.make-it-in-germany.com/en/visa-residence/types/job-search-opportunity-card",
                    "https://www.make-it-in-germany.com/en/visa-residence/procedure/entry-process"],
    },
    ("DEU", "Student Visa + 18-Month Job Search"): {
        "fee": {"amount": 75, "currency": "EUR", "note": "National (D) visa fee. Blocked account of €11,904 for 2026"},
        "sources": ["https://www.make-it-in-germany.com/en/visa-residence/types/studying",
                    "https://www.make-it-in-germany.com/en/visa-residence/procedure/entry-process"],
    },
    ("DEU", "Family Reunification Visa"): {
        "fee": {"amount": 75, "currency": "EUR", "note": "National (D) visa fee"},
        "sources": ["https://www.make-it-in-germany.com/en/visa-residence/procedure/entry-process"],
    },
    ("FRA", "Talent Passport"): {
        "fee": {"amount": 99, "currency": "EUR", "note": "Long-stay visa fee; residence permit fees in France are extra"},
        "sources": ["https://france-visas.gouv.fr/documents/d/france-visas/frais-de-visa-francais"],
    },
    ("FRA", "Long-Stay Student Visa"): {
        "fee": {"amount": 99, "currency": "EUR", "note": "Standard long-stay visa fee; some nationalities pay less"},
        "sources": ["https://france-visas.gouv.fr/documents/d/france-visas/frais-de-visa-francais"],
    },
    ("NLD", "Highly Skilled Migrant Visa"): {
        "fee": {"amount": 423, "currency": "EUR", "note": "2026 fee. Salary from €5,942 a month at 30+, €4,357 under 30"},
        "years_to_pr": 5,
        "family": {"partner": True, "children": True},
        "sources": ["https://ind.nl/en/fees-costs-of-an-application", "https://ind.nl/en/required-amounts-income-requirements",
                    "https://ind.nl/en/residence-permits/work/highly-skilled-migrant"],
    },
    ("NLD", "DAFT (US treaty)"): {
        "fee": {"amount": 423, "currency": "EUR", "note": "2026 self-employed permit fee"},
        "sources": ["https://ind.nl/en/fees-costs-of-an-application"],
    },
    ("NLD", "Startup Visa"): {
        "fee": {"amount": 423, "currency": "EUR", "note": "2026 fee. Needs a facilitator on the RVO list"},
        "processing": "Decided within 90 days (can be extended)", "processing_weeks": 13,
        "sources": ["https://ind.nl/en/residence-permits/work/start-up", "https://ind.nl/en/fees-costs-of-an-application"],
    },
    ("DNK", "Pay Limit Scheme"): {
        "fee": {"amount": 6810, "currency": "DKK", "note": "Pay of at least DKK 552,000 a year (2026)"},
        "processing": "Normally 1 month, up to 3 if more information is needed", "processing_weeks": 4,
        "family": {"partner": True, "children": True},
        "sources": ["https://www.nyidanmark.dk/en-GB/You-want-to-apply/Work/Pay-limit-scheme"],
    },
    ("FIN", "Startup Permit"): {
        "fee": {"amount": 450, "currency": "EUR", "note": "Online application (€580 on paper). Needs a Business Finland eligibility statement"},
        "processing": "About 2 weeks with the fast-track service", "processing_weeks": 2,
        "sources": ["https://migri.fi/en/start-up-entrepreneur"],
    },
    ("FIN", "Specialist Residence Permit"): {
        "processing": "About 2 weeks with the fast-track service", "processing_weeks": 2,
        "sources": ["https://migri.fi/en/specialist"],
    },
    ("NOR", "Skilled Worker Permit"): {
        "years_to_pr": 3,
        "family": {"partner": True, "children": True},
        "sources": ["https://www.udi.no/en/want-to-apply/work-immigration/skilled-workers/"],
    },
    ("SWE", "Work Permit"): {
        "family": {"partner": True, "children": True},
        "sources": ["https://www.migrationsverket.se/English/Private-individuals/Working-in-Sweden/Employed.html"],
    },
    ("AUT", "Red-White-Red Card"): {
        "fee": {"amount": 218, "currency": "EUR", "note": "Application fee. Points test: 70 of 100"},
        "sources": ["https://www.migration.gv.at/en/types-of-immigration/permanent-immigration/very-highly-qualified-workers/"],
    },
    ("NZL", "Skilled Migrant Category"): {
        "fee": {"amount": 6450, "currency": "NZD", "note": "From NZD 6,450"},
        "years_to_pr": 0,
        "age_max": 55,
        "family": {"partner": True, "children": True},
        "sources": ["https://www.immigration.govt.nz/visas/skilled-migrant-category-resident-visa/"],
    },
    ("SGP", "Employment Pass"): {
        "fee": {"amount": 105, "currency": "SGD", "note": "Application fee; a further fee is charged when the pass is issued"},
        "family": {"partner": True, "children": True},
        "sources": ["https://www.mom.gov.sg/passes-and-permits/employment-pass/apply-for-a-pass",
                    "https://www.mom.gov.sg/passes-and-permits/employment-pass"],
    },
}

# One correction found while researching: Germany replaced the Job Seeker Visa in June 2024.
RENAMES = {
    ("DEU", "Job Seeker Visa"): {
        "name": "Opportunity Card (Job Search)",
        "duration": "Up to 1 year",
        "summary": "Points-based card (6+ points) to look for skilled work for up to a year; needs €1,091 a month in a blocked account.",
    },
}

# ---------------------------------------------------------------------------
# Citizenship by naturalisation: (years of residence, years that must be as a
# permanent resident, note). Secondary source: WIKI_NATURALISATION.
# Countries where the requirement is discretionary, not applicable or disputed
# against what I could confirm are left out (Singapore, China, Hong Kong, Denmark).
# ---------------------------------------------------------------------------
CITIZENSHIP = {
    "USA": (5, 5, "5 years as a permanent resident (3 if married to a citizen)"),
    "CAN": (3, 2, "1,095 days in Canada in the last 5 years, mostly as a permanent resident"),
    "MEX": (5, 0, "2 years for spouses of citizens"),
    "CRI": (7, 0, None), "PAN": (5, 0, None), "BRA": (4, 0, "1 year for Portuguese speakers and some family ties"),
    "ARG": (2, 0, "Continuous residence"), "CHL": (5, 0, None), "URY": (5, 0, "3 years with a family in Uruguay"),
    "COL": (7, 5, "Needs 5 years as a permanent resident"), "PER": (5, 0, None),
    "GBR": (5, 1, "Settled status (ILR) for 12 months first"), "IRL": (5, 0, "5 of the last 9 years; 3 if married to a citizen"),
    "DEU": (5, 0, None), "FRA": (5, 0, "2 years after a French master's degree"), "NLD": (5, 0, None),
    "BEL": (5, 0, None), "SWE": (8, 0, None), "NOR": (8, 0, "8 of the last 11 years"), "FIN": (8, 0, "5 in some cases"),
    "ISL": (7, 0, None), "CHE": (10, 0, "Needs a C permit"), "AUT": (10, 0, "6 years for some groups"),
    "ESP": (10, 0, "2 years for Latin American, Portuguese and some other nationals"), "PRT": (10, 0, None),
    "ITA": (10, 0, None), "GRC": (7, 0, None), "CZE": (10, 0, None), "POL": (10, 3, "Or 3 years as a permanent resident"),
    "HUN": (8, 0, None), "EST": (8, 0, "Multiple citizenship not allowed for naturalised citizens"), "ROU": (8, 0, None),
    "HRV": (8, 0, None), "SVN": (10, 0, None), "AUS": (4, 1, "Including 12 months as a permanent resident"),
    "NZL": (5, 5, "As a resident visa holder"), "JPN": (10, 0, None), "KOR": (5, 0, None), "TWN": (5, 0, None),
    "VNM": (5, 0, None), "IND": (12, 0, None), "IDN": (5, 0, None), "PHL": (10, 0, None), "MYS": (12, 0, None),
    "THA": (5, 0, None), "LKA": (5, 0, None), "ARE": (30, 0, None), "QAT": (25, 0, None), "SAU": (10, 0, None),
    "ISR": (3, 0, None), "TUR": (5, 0, None), "BHR": (10, 0, None), "ZAF": (5, 0, None), "EGY": (10, 0, None),
    "MAR": (5, 0, None), "KEN": (7, 0, None), "NGA": (15, 0, None), "GHA": (5, 0, None), "MUS": (5, 0, None),
    "RUS": (5, 0, None), "GEO": (10, 0, None), "CYP": (7, 0, None),
}

# ---------------------------------------------------------------------------
# Official shortage / priority lists, mapped to the job fields in data/occupations.json
# ---------------------------------------------------------------------------
IN_DEMAND = {
    "CAN": {"fields": ["healthcare", "tech", "engineering", "science", "trades", "education"],
            "list": "Express Entry category-based selection",
            "source": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/rounds-invitations/category-based-selection.html"},
    "DEU": {"fields": ["tech", "engineering", "science", "healthcare", "education"],
            "list": "EU Blue Card shortage occupations",
            "source": "https://www.make-it-in-germany.com/en/visa-residence/types/eu-blue-card"},
    "IRL": {"fields": ["healthcare", "tech", "science", "finance"],
            "list": "Critical Skills Occupations List",
            "source": "https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/employment-permit-eligibility/highly-skilled-eligible-occupations-list/"},
    "NZL": {"fields": ["tech", "engineering", "healthcare", "education", "trades"],
            "list": "Green List (March 2026)",
            "source": "https://www.immigration.govt.nz/opsmanual/89117.htm"},
}

VISA_KEYS = ("fee", "processing", "processing_weeks", "years_to_pr", "pr_note", "family", "age_min", "age_max",
             "fields", "sources", "education_min", "experience_years", "language", "requirements_note")

# Education, experience and language requirements (Phase 2), read from the official pages below on CHECKED.
# Only what the page states is recorded: Canada's CLB 7 isn't converted to a CEFR level, because there is no
# official conversion, so the app says it can't compare it rather than guessing.
REQUIREMENTS = {
    ("GBR", "Skilled Worker Visa"): {
        "language": {"lang": "english", "cefr": "B2"},
        "requirements_note": "B2 applies to new applications; extensions of visas held before 8 January 2026 need B1.",
        "sources": ["https://www.gov.uk/skilled-worker-visa/knowledge-of-english"],
    },
    ("CAN", "Express Entry (FSW)"): {
        "experience_years": 1,
        "language": {"lang": "english", "test": "CLB 7 in all four abilities (or the French equivalent)"},
        "requirements_note": "At least 1 year of continuous skilled work (TEER 0-3) in the last 10 years. Foreign "
                             "education needs an Educational Credential Assessment.",
        "sources": ["https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply/federal-skilled-workers.html"],
    },
    ("DEU", "EU Blue Card"): {
        "education_min": "bachelor",
        "requirements_note": "A German or comparable foreign degree (or a 3-year ISCED/EQF level 6 qualification). "
                             "German is not required for the card; A1 or B1 shortens the wait for a settlement permit.",
        "sources": ["https://www.make-it-in-germany.com/en/visa-residence/types/eu-blue-card"],
    },
}


UPDATES = ROOT / "data" / "immigration" / "updates.json"


def _apply_updates(data: dict) -> None:
    """Approved updates (python -m immigration approve) go on top of the research record, oldest first."""
    if not UPDATES.exists():
        return
    import re
    ids = {f"{c}-{re.sub(r'[^a-z0-9]+', '-', v['name'].lower()).strip('-')}": v
           for c, e in data.items() for v in e["visas"]}
    for u in sorted(json.loads(UPDATES.read_text(encoding="utf-8")), key=lambda u: u["approved"]):
        v = ids.get(u["route"])
        if v is None:
            raise SystemExit(f"Approved update for an unknown route: {u['route']}")
        v.update(u["changes"])
        v["sources"] = sorted(set(v.get("sources", [])) | set(u["sources"]))
        v["checked"] = max(v.get("checked") or "", u["checked"])


def merged() -> dict:
    data = json.loads(VISAS.read_text(encoding="utf-8"))
    seen = set()
    for code, entry in data.items():
        for k in ("citizenship", "in_demand"):
            entry.pop(k, None)
        if code in CITIZENSHIP:
            years, after_pr, note = CITIZENSHIP[code]
            entry["citizenship"] = {"years": years, "after_pr": after_pr, "note": note,
                                    "source": WIKI_NATURALISATION, "source_kind": "secondary", "checked": CHECKED}
        if code in IN_DEMAND:
            entry["in_demand"] = {**IN_DEMAND[code], "checked": CHECKED}
        for v in entry["visas"]:
            fix = RENAMES.get((code, v["name"]))
            if fix:
                v.update(fix)
            for k in VISA_KEYS + ("checked",):
                v.pop(k, None)
            info = VISAS_RESEARCH.get((code, v["name"]))
            if info:
                seen.add((code, v["name"]))
                v.update({k: info[k] for k in VISA_KEYS if k in info})
                v["checked"] = CHECKED
    for (code, name), req in REQUIREMENTS.items():
        v = next((v for v in data[code]["visas"] if v["name"] == name), None)
        if v is None:
            raise SystemExit(f"Requirement research for an unknown route: {code} {name}")
        v.update({k: x for k, x in req.items() if k != "sources"})
        v["sources"] = sorted(set(v.get("sources", [])) | set(req["sources"]))
        v["checked"] = CHECKED
    _apply_updates(data)
    missing = set(VISAS_RESEARCH) - seen
    if missing:
        raise SystemExit(f"Researched visas not found in visas.json: {sorted(missing)}")
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--check", action="store_true", help="fail if data/visas.json is out of date")
    args = ap.parse_args(argv)
    text = json.dumps(merged(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        ok = VISAS.read_text(encoding="utf-8") == text
        print("visas.json is up to date" if ok else "visas.json is out of date: run python -m pipeline.visa_details")
        return 0 if ok else 1
    VISAS.write_text(text, encoding="utf-8")
    print(f"Merged research for {len(VISAS_RESEARCH)} visas, {len(CITIZENSHIP)} citizenship rules, "
          f"{len(IN_DEMAND)} shortage lists into {VISAS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
