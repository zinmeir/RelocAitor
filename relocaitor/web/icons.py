"""
relocaitor/web/icons.py — RelocAitor's own line icons (replacing emoji).

Drawn on a 24 × 24 grid as plain SVG paths: one stroke weight, round caps and
joins, no fills, so they take the colour of the text around them and stay
crisp at any size. The same set is used by the server-rendered page (the
`icon()` Jinja helper) and by the browser (window.ICONS, used by app.js).
"""

from __future__ import annotations

from markupsafe import Markup

ICONS = {
    # ---- the nine factors ----
    "salary": '<rect x="2.75" y="6.25" width="18.5" height="11.5" rx="2.25"/><circle cx="12" cy="12" r="2.6"/>'
              '<path d="M6.25 9.5h.01M17.75 14.5h.01"/>',
    "cost": '<path d="M3.5 12.4V5.25c0-.97.78-1.75 1.75-1.75h7.15l7.98 7.98c.69.69.69 1.8 0 2.48l-7.04 7.04'
            'c-.69.69-1.8.69-2.48 0z"/><circle cx="8.25" cy="8.25" r="1.5"/>',
    "pr": '<rect x="5" y="2.75" width="14" height="18.5" rx="2.25"/><circle cx="12" cy="10.25" r="3"/>'
          '<path d="M9 10.25h6M12 7.25c-.9.9-1.2 1.9-1.2 3s.3 2.1 1.2 3M9 16.75h6"/>',
    "job": '<rect x="3" y="7" width="18" height="12.75" rx="2.25"/><path d="M8.75 7V5.5c0-.97.78-1.75 1.75-1.75h3'
           'c.97 0 1.75.78 1.75 1.75V7M3 12.25c5.6 2.1 12.4 2.1 18 0"/>',
    "climate": '<circle cx="12" cy="12" r="3.75"/><path d="M12 2.75v2M12 19.25v2M2.75 12h2M19.25 12h2M5.46 5.46l1.41 1.41'
               'M17.13 17.13l1.41 1.41M5.46 18.54l1.41-1.41M17.13 6.87l1.41-1.41"/>',
    "safety": '<path d="M12 2.9l7.25 2.9v5.5c0 4.55-3.07 8.5-7.25 9.8-4.18-1.3-7.25-5.25-7.25-9.8V5.8z"/>'
              '<path d="M8.9 12.1l2.15 2.15 4.1-4.4"/>',
    "healthcare": '<path d="M12 20.25s-7.75-4.6-7.75-10.4A4.35 4.35 0 0 1 12 7.2a4.35 4.35 0 0 1 7.75 2.65'
                  'c0 5.8-7.75 10.4-7.75 10.4z"/><path d="M7.4 12.25h2.6l1.3-2.3 2 4.4 1.35-2.1h1.95"/>',
    "english": '<path d="M4.25 4.75h9.5c.97 0 1.75.78 1.75 1.75v6c0 .97-.78 1.75-1.75 1.75H9l-3.25 2.75v-2.75h-1.5'
               'c-.97 0-1.75-.78-1.75-1.75v-6c0-.97.78-1.75 1.75-1.75z"/><path d="M18.5 9h1.25c.97 0 1.75.78 1.75 1.75'
               'v5.5c0 .97-.78 1.75-1.75 1.75H19v2.5l-3-2.5h-2.5"/><path d="M6.6 11.75L8.75 7.5l2.15 4.25M7.4 10.25h2.7"/>',
    "internet": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.55 3.75 5.55 3.75 9S14.5 18.45 12 21'
                'c-2.5-2.55-3.75-5.55-3.75-9S9.5 5.55 12 3z"/>',

    # ---- presets ----
    "balanced": '<path d="M12 4.25v15.5M8 19.75h8M5.25 7h13.5"/><path d="M7.25 7l-3 6.5a3 3 0 0 0 6 0zM16.75 7l-3 6.5'
                'a3 3 0 0 0 6 0z"/><circle cx="12" cy="4.25" r="1"/>',
    "nomad": '<rect x="4.25" y="4.75" width="15.5" height="10.5" rx="1.75"/><path d="M2.5 18.75h19M10.25 18.75'
             'l.5-1.25h2.5l.5 1.25"/>',
    "student": '<path d="M2.5 9.25L12 5l9.5 4.25L12 13.5z"/><path d="M6.5 11.25v4.1c0 1.5 2.46 2.9 5.5 2.9s5.5-1.4 5.5-2.9'
               'v-4.1M21.5 9.25v5"/>',
    "family": '<circle cx="8.5" cy="7.75" r="2.75"/><circle cx="16.75" cy="9.25" r="2.1"/><path d="M3.25 19.25'
              'c0-3.05 2.35-5.25 5.25-5.25s5.25 2.2 5.25 5.25M14.1 14.6c.75-.35 1.65-.55 2.65-.55 2.35 0 4 1.7 4 4.45"/>',
    "retiree": '<path d="M2.75 18.25h18.5M6.75 18.25a5.25 5.25 0 0 1 10.5 0"/><path d="M12 7.75v-2.5M6.15 10.15'
               'L4.4 8.4M17.85 10.15l1.75-1.75M5.75 21.25h12.5"/>',
    "career": '<path d="M3.5 17.75l6-6.25 4 4 7-7.25"/><path d="M15.25 8.25h5.25v5.25"/>',

    # ---- what the prompt reader understood ----
    "income": '<path d="M4 7.25h14.25c.97 0 1.75.78 1.75 1.75v9.25c0 .97-.78 1.75-1.75 1.75h-12.5'
              'c-.97 0-1.75-.78-1.75-1.75zM4 7.25v-1c0-1.1.9-2 2-2h9.5"/><path d="M15.5 11.5H20v4.25h-4.5'
              'a2.12 2.12 0 0 1 0-4.25z"/>',
    "savings": '<path d="M3.5 9.5L12 4.5l8.5 5M5.25 10.25v7M9.75 10.25v7M14.25 10.25v7M18.75 10.25v7M3.5 19.5h17"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8.25 12.25l2.5 2.5 5-5.25"/>',
    "region": '<path d="M3.25 6.5l5.25-2.25 7 2.5 5.25-2.25v13.25l-5.25 2.25-7-2.5-5.25 2.25z"/>'
              '<path d="M8.5 4.25v13.25M15.5 6.75V20"/>',
    "exclude": '<circle cx="12" cy="12" r="9"/><path d="M5.65 5.65l12.7 12.7"/>',
    "similar": '<path d="M4 8.25h13.25l-3.5-3.5M20 15.75H6.75l3.5 3.5"/>',
    "pin": '<path d="M12 21.25s-6.75-5.75-6.75-11.25a6.75 6.75 0 0 1 13.5 0c0 5.5-6.75 11.25-6.75 11.25z"/>'
           '<circle cx="12" cy="10" r="2.4"/>',
    "compare": '<rect x="3.25" y="4.25" width="7.25" height="15.5" rx="1.75"/><rect x="13.5" y="4.25" width="7.25"'
               ' height="15.5" rx="1.75"/><path d="M6.25 8.5h1.5M16.5 8.5h1.5"/>',
    "target": '<circle cx="12" cy="12" r="8.75"/><circle cx="12" cy="12" r="4.75"/><path d="M12 12h.01"/>',
    "difficulty": '<path d="M4 7h9.25M17.25 7H20M4 17h2.75M10.75 17H20"/><circle cx="15.25" cy="7" r="2"/>'
                  '<circle cx="8.75" cy="17" r="2"/>',
    "top": '<path d="M9.25 6.5H20M9.25 12H20M9.25 17.5H20M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/>',
    "learned": '<rect x="6" y="6" width="12" height="12" rx="2.25"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>'
               '<path d="M9.5 2.75V6M14.5 2.75V6M9.5 18v3.25M14.5 18v3.25M2.75 9.5H6M2.75 14.5H6M18 9.5h3.25M18 14.5h3.25"/>',
    "semantic": '<path d="M11 3.25l1.65 4.6 4.6 1.65-4.6 1.65L11 15.75l-1.65-4.6-4.6-1.65 4.6-1.65z"/>'
                '<path d="M18 14.25l.75 2 2 .75-2 .75-.75 2-.75-2-2-.75 2-.75z"/>',
    "keyword": '<path d="M5.25 7.25V5.5h13.5v1.75M12 5.5v13M9.5 18.5h5"/>',

    # ---- interface ----
    "bulb": '<path d="M9.25 18h5.5M10.25 21h3.5"/><path d="M12 3a6 6 0 0 0-3.55 10.85c.7.5 1.05 1.3 1.05 2.15h5'
            'c0-.85.35-1.65 1.05-2.15A6 6 0 0 0 12 3z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7.25V12l3.25 2"/>',
    "bookmark": '<path d="M6.75 3.75h10.5a1 1 0 0 1 1 1v15.5L12 16.25l-6.25 4V4.75a1 1 0 0 1 1-1z"/>',
    "city": '<path d="M3.75 20.25h16.5"/><path d="M5.75 20.25V9.75l5-3v13.5"/><path d="M10.75 20.25V4.75l7.5 3.5v12"/><path d="M13.75 10.25h1.5M13.75 13.25h1.5M13.75 16.25h1.5M7.75 12.25h1M7.75 15.25h1"/>',
    "passport": '<rect x="5.25" y="3.25" width="13.5" height="17.5" rx="1.75"/><circle cx="12" cy="10.5" r="3"/><path d="M9 16.75h6"/>',
    "home": '<path d="M3.75 11L12 4.25 20.25 11"/><path d="M6 9.25v10.5h12V9.25M10 19.75v-5h4v5"/>',
    "alert": '<path d="M10.5 4.6L2.9 17.75c-.67 1.17.17 2.5 1.5 2.5h15.2c1.33 0 2.17-1.33 1.5-2.5L13.5 4.6'
             'c-.67-1.15-2.33-1.15-3 0z"/><path d="M12 9.5v4M12 16.75h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.75h.01"/>',
    "lock": '<rect x="4.75" y="10.25" width="14.5" height="10.5" rx="2.25"/><path d="M8 10.25V7.75a4 4 0 0 1 8 0v2.5'
            'M12 14.5v2"/>',
    "undo": '<path d="M9 6.75L4.75 11 9 15.25"/><path d="M4.75 11h9.75a4.75 4.75 0 0 1 0 9.5H12"/>',
    "external": '<path d="M14 4h6v6M20 4l-8.5 8.5"/><path d="M18 14v5.25c0 .97-.78 1.75-1.75 1.75H5.75'
                'C4.78 21 4 20.22 4 19.25V8.75C4 7.78 4.78 7 5.75 7H10"/>',
    "link": '<path d="M10 14a4.25 4.25 0 0 0 6 0l3-3a4.25 4.25 0 0 0-6-6l-1 1"/><path d="M14 10a4.25 4.25 0 0 0-6 0'
            'l-3 3a4.25 4.25 0 0 0 6 6l1-1"/>',
    "chevron": '<path d="M7 10l5 5 5-5"/>',
    "explore": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    "keyboard": '<rect x="2.75" y="6.25" width="18.5" height="11.5" rx="2.25"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M8 14h8"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "tick": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.55 2.28c-.65.3-1.15.92-1.15 1.64'
                'v.43M12 16.9h.01"/>',
    "verified": '<path d="M12 2.75l2.2 1.6 2.7-.2.9 2.6 2.2 1.6-.85 2.6.85 2.6-2.2 1.6-.9 2.6-2.7-.2L12 21.25'
                'l-2.2-1.6-2.7.2-.9-2.6-2.2-1.6.85-2.6-.85-2.6 2.2-1.6.9-2.6 2.7.2z"/><path d="M9 12.2l2 2 4-4.2"/>',
    "trend": '<path d="M3.5 17.75l6-6.25 4 4 7-7.25"/><path d="M15.25 8.25h5.25v5.25"/>',
    "scale": '<path d="M12 4.25v15.5M8 19.75h8M5.25 7h13.5"/><path d="M7.25 7l-3 6.5a3 3 0 0 0 6 0zM16.75 7l-3 6.5'
             'a3 3 0 0 0 6 0z"/>',
}

# Which icon goes with which preset (presets.py keys)
PRESET_ICONS = {"balanced": "balanced", "nomad": "nomad", "student": "student", "family": "family",
                "retiree": "retiree", "career": "career"}


def svg(name: str, cls: str = "") -> Markup:
    body = ICONS.get(name) or ICONS["info"]
    classes = f"ico ico-{name} {cls}".strip()
    return Markup(f'<svg class="{classes}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{body}</svg>')
