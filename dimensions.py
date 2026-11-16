"""
dimensions.py — six separate views of a country, never added into one number.

    lifestyle     climate, safety, healthcare, internet, English, weighted by your sliders
    immigration   whether a researched route is open to you, and how much of it we could check
    financial     typical net salary against rent, after tax where it is sourced
    career        job market indicator, unemployment, your field on an official shortage list
    settlement    researched time to permanent residence and citizenship, plus the PR-ease estimate
    family        only when a partner or children are coming: whether open routes allow them,
                  safety and healthcare

Each dimension has a 0–1 score where the inputs support one, the components behind it, and a basis
saying what kind of data it rests on. The compatibility match % stays the app's ranking; it is not a
probability of immigration success, and neither is anything here.
"""

from __future__ import annotations

from eligibility import Profile


def _row(code: str):
    from data import load_countries
    return load_countries().set_index("country_code").loc[code]


def dimensions(code: str, profile: Profile, weights: dict) -> dict:
    import planner
    import visas as V
    from factors import FACTORS
    row = _row(code)
    out = {}

    # Lifestyle
    keys = ["climate", "safety", "healthcare", "internet", "english"]
    w = {k: float(weights.get(k, 0.5)) for k in keys}
    tot = sum(w.values()) or 1.0
    vals = {k: float(row[FACTORS[k]["col"]]) for k in keys}
    out["lifestyle"] = {"score": round(sum(vals[k] * w[k] for k in keys) / tot, 3),
                        "components": {k: round(v, 2) for k, v in vals.items()},
                        "basis": "Measured indicators (WHO, World Bank, GPI, EF EPI, climate), weighted by your sliders"}

    # Immigration feasibility
    info = V.visas_for_profile(code, profile)
    statuses = [v["eligibility"]["status"] for v in info["visas"]]
    best = "eligible" if "eligible" in statuses else "conditional" if "conditional" in statuses else ("ineligible" if statuses else None)
    open_routes = [v["name"] for v in info["visas"] if v["qualifies"]]
    checked = [3 - len(planner.unchecked(planner.route_id(code, v["name"]))) for v in info["visas"] if not v.get("generated")]
    coverage = round(sum(checked) / (3 * len(checked)), 2) if checked else 0.0
    out["immigration"] = {"score": {"eligible": 1.0, "conditional": 0.5, "ineligible": 0.0}.get(best),
                          "components": {"best_status": best, "open_routes": open_routes,
                                         "requirements_checked": coverage},
                          "basis": "The eligibility rules on researched routes; 'requirements_checked' is how much of "
                                   "education, experience and language we could check (1 = all)"}

    # Financial
    import finance
    tax = finance.tax_table()["rates_pct"].get(code)
    net, rent = float(row["salary_usd_month"]), float(row["rent_usd_month"])
    ratio = max(0.0, min(1.0, (net - rent) / net)) if net else None
    out["financial"] = {"score": round(ratio, 3) if ratio is not None else None,
                        "components": {"typical_net_salary_usd": net, "rent_usd": rent, "oecd_tax_pct_at_average_wage": tax},
                        "basis": "Share of a typical net salary left after a 1-bed city-centre rent (editorial estimates); "
                                 "tax rate from OECD where available"}

    # Career
    from career import _unemployment
    demand = V.country_entry(code).get("in_demand")
    listed = (profile.occupation in demand["fields"]) if (demand and profile.occupation) else None
    out["career"] = {"score": round(float(row["job_market"]), 3),
                     "components": {"unemployment": _unemployment(code), "field_on_shortage_list": listed,
                                    "shortage_list": demand["list"] if demand else None},
                     "basis": "World Bank labour indicators; shortage list where researched (4 countries)"}

    # Settlement
    plan = planner.plan(profile, countries=[code])["pathways"]
    known = [p for p in plan if not p["years_to_pr"]["unknown"]]
    fastest = min(known, key=lambda p: p["years_to_pr"]["min"]) if known else None
    cit = (V.country_entry(code).get("citizenship") or {})
    out["settlement"] = {"score": round(float(row["pr_ease"]), 3),
                         "components": {"fastest_researched_years_to_pr": fastest["years_to_pr"]["min"] if fastest else None,
                                        "via": fastest["title"] if fastest else None,
                                        "citizenship_residence_years": cit.get("years")},
                         "basis": "PR-ease is an editorial estimate; times come from researched routes; citizenship rule "
                                  "from a secondary source"}

    # Family
    if profile.partner or (profile.children or 0) > 0:
        fam = [v for v in info["visas"] if v["qualifies"] and v.get("family")]
        ok = [v["name"] for v in fam if (not profile.partner or v["family"].get("partner"))
              and (not profile.children or v["family"].get("children"))]
        out["family"] = {"score": round((float(row["safety"]) + float(row["healthcare"])) / 2, 3),
                         "components": {"open_routes_that_allow_your_family": ok,
                                        "routes_with_unresearched_family_rules": len([v for v in info["visas"] if v["qualifies"] and not v.get("family")])},
                         "basis": "Safety and healthcare indicators; family rules from official pages where researched"}
    else:
        out["family"] = {"score": None, "components": {}, "basis": "Not applicable: no partner or children in your profile"}

    return {"country": code, "dimensions": out,
            "note": "Six separate views. They are not combined, and none is a probability of a successful application."}
