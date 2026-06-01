"""
data.py — Expanded country dataset for the AI Global Relocation Intelligence System.

65 countries across all major regions, each with 10 normalized [0, 1] metrics.

Sources for the underlying values (approximated and normalized for demo use):
- Salary / cost data:    Numbeo, Mercer Cost of Living indices
- PR ease:               IMI relocation data, country immigration policy summaries
- Job market:            World Bank, OECD employment statistics
- Language barrier:      EF English Proficiency Index (inverted, English-speaker view)
- Climate quality:       Average livability climate scores
- Safety:                Global Peace Index, Numbeo safety index
- Healthcare:            WHO + Numbeo healthcare quality
- English proficiency:   EF EPI direct values
- Internet speed:        Speedtest Global Index (normalized)
"""

import pandas as pd


# (name, iso3, region, salary, cost, pr_ease, job, lang_barrier,
#  climate, safety, healthcare, english, internet)
COUNTRIES = [
    # ---------------- North America ----------------
    ("United States",        "USA", "North America", 0.95, 0.85, 0.35, 0.90, 0.05, 0.65, 0.55, 0.75, 1.00, 0.85),
    ("Canada",               "CAN", "North America", 0.75, 0.70, 0.85, 0.80, 0.05, 0.45, 0.85, 0.85, 1.00, 0.80),
    ("Mexico",               "MEX", "North America", 0.30, 0.35, 0.55, 0.50, 0.60, 0.70, 0.30, 0.50, 0.30, 0.45),
    ("Costa Rica",           "CRI", "North America", 0.32, 0.40, 0.70, 0.45, 0.60, 0.85, 0.55, 0.65, 0.40, 0.45),
    ("Panama",               "PAN", "North America", 0.40, 0.45, 0.65, 0.55, 0.55, 0.80, 0.45, 0.60, 0.40, 0.55),

    # ---------------- South America ----------------
    ("Brazil",               "BRA", "South America", 0.35, 0.40, 0.60, 0.45, 0.70, 0.75, 0.30, 0.55, 0.20, 0.55),
    ("Argentina",            "ARG", "South America", 0.30, 0.35, 0.65, 0.40, 0.65, 0.65, 0.45, 0.65, 0.30, 0.45),
    ("Chile",                "CHL", "South America", 0.45, 0.45, 0.70, 0.55, 0.65, 0.70, 0.65, 0.70, 0.30, 0.65),
    ("Uruguay",              "URY", "South America", 0.42, 0.45, 0.75, 0.50, 0.65, 0.70, 0.75, 0.70, 0.30, 0.55),
    ("Colombia",             "COL", "South America", 0.28, 0.30, 0.60, 0.45, 0.70, 0.80, 0.30, 0.55, 0.25, 0.40),
    ("Peru",                 "PER", "South America", 0.25, 0.30, 0.55, 0.40, 0.70, 0.65, 0.35, 0.50, 0.25, 0.40),

    # ---------------- Europe ----------------
    ("United Kingdom",       "GBR", "Europe",        0.78, 0.80, 0.55, 0.78, 0.05, 0.50, 0.75, 0.85, 1.00, 0.80),
    ("Ireland",              "IRL", "Europe",        0.80, 0.78, 0.65, 0.82, 0.05, 0.45, 0.85, 0.75, 1.00, 0.75),
    ("Germany",              "DEU", "Europe",        0.80, 0.70, 0.70, 0.82, 0.55, 0.55, 0.80, 0.85, 0.80, 0.75),
    ("France",               "FRA", "Europe",        0.72, 0.72, 0.60, 0.70, 0.65, 0.60, 0.70, 0.85, 0.50, 0.75),
    ("Netherlands",          "NLD", "Europe",        0.82, 0.75, 0.72, 0.80, 0.30, 0.50, 0.85, 0.85, 0.95, 0.85),
    ("Belgium",              "BEL", "Europe",        0.75, 0.72, 0.65, 0.72, 0.55, 0.50, 0.75, 0.80, 0.70, 0.75),
    ("Sweden",               "SWE", "Europe",        0.78, 0.75, 0.78, 0.75, 0.35, 0.40, 0.90, 0.85, 0.95, 0.85),
    ("Norway",               "NOR", "Europe",        0.88, 0.90, 0.65, 0.78, 0.40, 0.35, 0.95, 0.85, 0.90, 0.85),
    ("Denmark",              "DNK", "Europe",        0.82, 0.80, 0.70, 0.80, 0.40, 0.45, 0.95, 0.90, 0.95, 0.85),
    ("Finland",              "FIN", "Europe",        0.75, 0.75, 0.70, 0.75, 0.55, 0.30, 0.95, 0.85, 0.85, 0.90),
    ("Iceland",              "ISL", "Europe",        0.75, 0.85, 0.55, 0.70, 0.45, 0.30, 0.95, 0.80, 0.85, 0.90),
    ("Switzerland",          "CHE", "Europe",        0.98, 0.98, 0.40, 0.85, 0.50, 0.60, 0.95, 0.95, 0.75, 0.85),
    ("Austria",              "AUT", "Europe",        0.75, 0.72, 0.55, 0.72, 0.55, 0.55, 0.95, 0.85, 0.70, 0.80),
    ("Spain",                "ESP", "Europe",        0.55, 0.55, 0.60, 0.55, 0.55, 0.85, 0.75, 0.80, 0.50, 0.75),
    ("Portugal",             "PRT", "Europe",        0.50, 0.50, 0.80, 0.55, 0.60, 0.85, 0.85, 0.75, 0.65, 0.75),
    ("Italy",                "ITA", "Europe",        0.55, 0.60, 0.50, 0.50, 0.65, 0.75, 0.65, 0.75, 0.50, 0.65),
    ("Greece",               "GRC", "Europe",        0.45, 0.55, 0.55, 0.45, 0.65, 0.85, 0.70, 0.65, 0.55, 0.60),
    ("Czech Republic",       "CZE", "Europe",        0.50, 0.45, 0.55, 0.65, 0.65, 0.60, 0.85, 0.70, 0.55, 0.85),
    ("Poland",               "POL", "Europe",        0.45, 0.40, 0.55, 0.65, 0.65, 0.55, 0.70, 0.70, 0.55, 0.85),
    ("Hungary",              "HUN", "Europe",        0.42, 0.40, 0.55, 0.55, 0.70, 0.55, 0.75, 0.65, 0.55, 0.85),
    ("Estonia",              "EST", "Europe",        0.52, 0.50, 0.65, 0.65, 0.55, 0.45, 0.85, 0.75, 0.70, 0.95),
    ("Romania",              "ROU", "Europe",        0.38, 0.35, 0.50, 0.55, 0.65, 0.60, 0.75, 0.60, 0.55, 0.95),
    ("Croatia",              "HRV", "Europe",        0.42, 0.45, 0.55, 0.50, 0.65, 0.60, 0.85, 0.65, 0.60, 0.75),
    ("Slovenia",             "SVN", "Europe",        0.55, 0.50, 0.55, 0.65, 0.55, 0.45, 0.90, 0.75, 0.65, 0.80),

    # ---------------- Oceania ----------------
    ("Australia",            "AUS", "Oceania",       0.85, 0.78, 0.80, 0.82, 0.05, 0.65, 0.80, 0.85, 1.00, 0.70),
    ("New Zealand",          "NZL", "Oceania",       0.72, 0.72, 0.82, 0.70, 0.05, 0.45, 0.95, 0.80, 1.00, 0.65),

    # ---------------- Asia ----------------
    ("Japan",                "JPN", "Asia",          0.72, 0.70, 0.50, 0.75, 0.90, 0.55, 0.95, 0.85, 0.45, 0.85),
    ("South Korea",          "KOR", "Asia",          0.70, 0.65, 0.45, 0.75, 0.85, 0.55, 0.90, 0.85, 0.50, 0.95),
    ("Singapore",            "SGP", "Asia",          0.88, 0.88, 0.55, 0.85, 0.20, 0.40, 0.95, 0.90, 0.85, 0.90),
    ("Taiwan",               "TWN", "Asia",          0.55, 0.50, 0.45, 0.70, 0.85, 0.70, 0.85, 0.85, 0.55, 0.80),
    ("Hong Kong",            "HKG", "Asia",          0.78, 0.85, 0.50, 0.80, 0.20, 0.50, 0.85, 0.80, 0.65, 0.85),
    ("China",                "CHN", "Asia",          0.45, 0.45, 0.25, 0.70, 0.95, 0.55, 0.65, 0.65, 0.40, 0.55),
    ("Vietnam",              "VNM", "Asia",          0.25, 0.25, 0.35, 0.55, 0.85, 0.65, 0.60, 0.50, 0.45, 0.50),
    ("India",                "IND", "Asia",          0.25, 0.25, 0.40, 0.60, 0.15, 0.50, 0.55, 0.45, 0.55, 0.30),
    ("Indonesia",            "IDN", "Asia",          0.22, 0.30, 0.40, 0.55, 0.75, 0.55, 0.45, 0.45, 0.45, 0.35),
    ("Philippines",          "PHL", "Asia",          0.22, 0.25, 0.45, 0.50, 0.10, 0.65, 0.40, 0.45, 0.65, 0.30),
    ("Malaysia",             "MYS", "Asia",          0.40, 0.40, 0.65, 0.55, 0.25, 0.65, 0.65, 0.65, 0.65, 0.55),
    ("Thailand",             "THA", "Asia",          0.35, 0.35, 0.55, 0.50, 0.75, 0.65, 0.55, 0.65, 0.45, 0.55),
    ("Sri Lanka",            "LKA", "Asia",          0.20, 0.25, 0.40, 0.40, 0.30, 0.55, 0.50, 0.55, 0.55, 0.30),

    # ---------------- Middle East ----------------
    ("United Arab Emirates", "ARE", "Middle East",   0.80, 0.70, 0.30, 0.75, 0.30, 0.35, 0.85, 0.80, 0.65, 0.75),
    ("Qatar",                "QAT", "Middle East",   0.85, 0.75, 0.25, 0.75, 0.40, 0.40, 0.90, 0.80, 0.55, 0.75),
    ("Saudi Arabia",         "SAU", "Middle East",   0.65, 0.60, 0.25, 0.65, 0.50, 0.30, 0.70, 0.70, 0.45, 0.70),
    ("Israel",               "ISR", "Middle East",   0.70, 0.78, 0.45, 0.75, 0.40, 0.45, 0.70, 0.85, 0.65, 0.75),
    ("Turkey",               "TUR", "Middle East",   0.35, 0.40, 0.45, 0.50, 0.65, 0.65, 0.45, 0.65, 0.35, 0.60),
    ("Bahrain",              "BHR", "Middle East",   0.55, 0.55, 0.40, 0.55, 0.40, 0.45, 0.85, 0.70, 0.65, 0.65),

    # ---------------- Africa ----------------
    ("South Africa",         "ZAF", "Africa",        0.40, 0.40, 0.55, 0.45, 0.20, 0.60, 0.30, 0.55, 0.85, 0.40),
    ("Egypt",                "EGY", "Africa",        0.20, 0.25, 0.35, 0.40, 0.55, 0.50, 0.40, 0.45, 0.40, 0.30),
    ("Morocco",              "MAR", "Africa",        0.22, 0.30, 0.45, 0.40, 0.55, 0.65, 0.50, 0.45, 0.30, 0.30),
    ("Kenya",                "KEN", "Africa",        0.20, 0.30, 0.40, 0.40, 0.20, 0.65, 0.30, 0.45, 0.85, 0.35),
    ("Nigeria",              "NGA", "Africa",        0.20, 0.30, 0.30, 0.40, 0.20, 0.45, 0.20, 0.35, 0.85, 0.20),
    ("Ghana",                "GHA", "Africa",        0.18, 0.30, 0.40, 0.40, 0.15, 0.65, 0.30, 0.40, 0.85, 0.25),
    ("Mauritius",            "MUS", "Africa",        0.40, 0.45, 0.65, 0.55, 0.25, 0.80, 0.65, 0.65, 0.85, 0.45),

    # ---------------- Other ----------------
    ("Russia",               "RUS", "Europe",        0.35, 0.40, 0.40, 0.55, 0.85, 0.40, 0.55, 0.55, 0.35, 0.65),
    ("Georgia",              "GEO", "Europe",        0.28, 0.35, 0.65, 0.45, 0.75, 0.75, 0.55, 0.55, 0.45, 0.55),
    ("Cyprus",               "CYP", "Europe",        0.55, 0.55, 0.65, 0.55, 0.40, 0.75, 0.80, 0.70, 0.65, 0.55),
]


COLUMNS = [
    "country_name", "country_code", "region",
    "average_salary", "cost_of_living", "pr_ease",
    "job_market", "language_barrier",
    "climate", "safety", "healthcare", "english", "internet",
]


def load_countries() -> pd.DataFrame:
    return pd.DataFrame(COUNTRIES, columns=COLUMNS)


def get_regions() -> list:
    return sorted(load_countries()["region"].unique().tolist())
