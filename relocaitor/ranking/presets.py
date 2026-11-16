"""
relocaitor/ranking/presets.py — One-click starting profiles. Each sets slider weights and
optional hard filters; the user can tweak anything afterwards.
"""

from relocaitor.ranking.factors import DEFAULT_WEIGHTS

PRESETS = {
    "balanced": {
        "label": "Balanced", "icon": "⚖️",
        "description": "Sensible defaults across all factors.",
        "weights": dict(DEFAULT_WEIGHTS),
        "filters": {},
    },
    "nomad": {
        "label": "Digital nomad", "icon": "💻",
        "description": "Fast internet, low costs, good weather, a nomad visa.",
        "weights": {"salary": 0.1, "cost": 0.8, "pr": 0.2, "job": 0.1, "climate": 0.7,
                    "safety": 0.6, "healthcare": 0.4, "english": 0.5, "internet": 1.0},
        "filters": {"visa_type": "nomad"},
    },
    "student": {
        "label": "Student", "icon": "🎓",
        "description": "Affordable, English-friendly, with post-study work rights.",
        "weights": {"salary": 0.3, "cost": 0.8, "pr": 0.6, "job": 0.6, "climate": 0.3,
                    "safety": 0.6, "healthcare": 0.4, "english": 0.8, "internet": 0.5},
        "filters": {"visa_type": "study"},
    },
    "family": {
        "label": "Family with kids", "icon": "👨‍👩‍👧",
        "description": "Safety, healthcare and a path to permanent residency.",
        "weights": {"salary": 0.5, "cost": 0.6, "pr": 0.8, "job": 0.6, "climate": 0.4,
                    "safety": 1.0, "healthcare": 0.9, "english": 0.5, "internet": 0.3},
        "filters": {"require_pr": True},
    },
    "retiree": {
        "label": "Retiree", "icon": "🌴",
        "description": "Healthcare, safety, sunshine and low costs on a passive income.",
        "weights": {"salary": 0.0, "cost": 0.8, "pr": 0.4, "job": 0.0, "climate": 0.9,
                    "safety": 0.9, "healthcare": 1.0, "english": 0.5, "internet": 0.3},
        "filters": {"visa_type": "passive"},
    },
    "career": {
        "label": "Career-focused", "icon": "🚀",
        "description": "Top salaries and job markets via a skilled-worker route.",
        "weights": {"salary": 1.0, "cost": 0.3, "pr": 0.6, "job": 1.0, "climate": 0.2,
                    "safety": 0.4, "healthcare": 0.4, "english": 0.5, "internet": 0.4},
        "filters": {"visa_type": "skilled"},
    },
}
