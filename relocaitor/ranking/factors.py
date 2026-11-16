"""
relocaitor/ranking/factors.py — Single source of truth for the 9 scoring factors.

Every other module (scoring, reasoning, assistant, the API's /api/meta endpoint)
reads factor names, labels and column mappings from here, so they can't drift.
"""

# key -> metadata
#   col:        column in data/countries.csv
#   invert:     True if the user wants LOW values (only cost of living)
#   label:      short human label
#   phrase:     noun phrase used in generated sentences
#   descriptor: used when describing what the user prioritises
#   icon:       emoji used in the UI
FACTORS = {
    "salary": {
        "col": "average_salary", "invert": False, "icon": "💰",
        "label": "Salary", "phrase": "salary potential",
        "descriptor": "maximizing income",
    },
    "cost": {
        "col": "cost_of_living", "invert": True, "icon": "🛒",
        "label": "Affordability", "phrase": "affordability",
        "descriptor": "keeping living costs manageable",
    },
    "pr": {
        "col": "pr_ease", "invert": False, "icon": "🛂",
        "label": "PR ease", "phrase": "PR accessibility",
        "descriptor": "long-term stability and permanent residency",
    },
    "job": {
        "col": "job_market", "invert": False, "icon": "💼",
        "label": "Job market", "phrase": "job market strength",
        "descriptor": "career opportunities and a strong job market",
    },
    "climate": {
        "col": "climate", "invert": False, "icon": "☀️",
        "label": "Climate", "phrase": "climate quality",
        "descriptor": "a pleasant climate and natural environment",
    },
    "safety": {
        "col": "safety", "invert": False, "icon": "🛡️",
        "label": "Safety", "phrase": "personal safety",
        "descriptor": "personal safety and security",
    },
    "healthcare": {
        "col": "healthcare", "invert": False, "icon": "🏥",
        "label": "Healthcare", "phrase": "healthcare quality",
        "descriptor": "world-class healthcare access",
    },
    "english": {
        "col": "english", "invert": False, "icon": "🗣️",
        "label": "English", "phrase": "English proficiency",
        "descriptor": "an English-speaking environment",
    },
    "internet": {
        "col": "internet", "invert": False, "icon": "🌐",
        "label": "Internet", "phrase": "internet infrastructure",
        "descriptor": "fast, reliable digital infrastructure",
    },
}

FACTOR_KEYS = list(FACTORS.keys())

DEFAULT_WEIGHTS = {
    "salary": 0.7, "cost": 0.5, "pr": 0.6, "job": 0.7,
    "climate": 0.3, "safety": 0.5, "healthcare": 0.4,
    "english": 0.5, "internet": 0.3,
}


def factor_value(row, key: str) -> float:
    """The country's value for a factor, oriented so that higher is always better."""
    meta = FACTORS[key]
    raw = float(row[meta["col"]])
    return 1.0 - raw if meta["invert"] else raw
