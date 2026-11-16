"""
Build a single self-contained HTML file of RelocAitor that runs with NO server:
the Flask API (scoring, eligibility, insights, compare, Q&A rules and prompt
search) is ported to JavaScript in mock_api.js and search_port.js.

    python preview/build_preview.py              # dist/index.html  (GitHub Pages / Netlify)
    python preview/build_preview.py --artifact   # dist/artifact.html (sandboxed hosts that block fetch)

Host dist/index.html anywhere static (GitHub Pages, Netlify) for a free demo.
tests/test_js_parity.py checks the JavaScript port gives the same answers as Python.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import journey  # noqa: E402
from app import app, meta  # noqa: E402
from ml.prompt_model import serving_payload  # noqa: E402
from ml.semantic import semantic_payload  # noqa: E402
from data import _provenance, load_countries  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--artifact", action="store_true",
                help="build for sandboxed hosts: map from a script CDN, no URL state")
ARTIFACT = ap.parse_args().artifact

html = app.test_client().get("/").get_data(as_text=True)

css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
banner_css = """
.preview-banner {
  position: relative; z-index: 51; text-align: center;
  font-size: 0.82rem; color: var(--paper-dim);
  padding: 7px 16px; border-bottom: 1px solid var(--rule-soft);
  background: var(--ink-deep);
}
.preview-banner b { color: var(--lamp); font-weight: 600; }
"""


def inline_js(s: str) -> str:
    return s.replace("</script", "<\\/script")


data = {
    "countries": load_countries().to_dict(orient="records"),
    "visas": json.loads((ROOT / "data/visas.json").read_text(encoding="utf-8")),
    "meta": meta(),
    "lexicon": json.loads((ROOT / "data/search_lexicon.json").read_text(encoding="utf-8")),
    "occupations": journey.occupations(),
    "rules": json.loads((ROOT / "data/rules.json").read_text(encoding="utf-8")),
    "cities": journey.cities_meta()["cities"],
    "provenance": _provenance(),
    "prompt_model": serving_payload(),
    # Tests can inject a stub semantic payload (RELOC_SEMANTIC_PAYLOAD=path/to.json).
    **(json.loads(Path(os.environ["RELOC_SEMANTIC_PAYLOAD"]).read_text(encoding="utf-8"))
       if os.environ.get("RELOC_SEMANTIC_PAYLOAD") else semantic_payload()),
}
data_js = ("window.RELOC_PREVIEW = true;\n" if ARTIFACT else "") + "window.RELOC_DATA = " + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";"

scripts = "\n".join([
    f"<script>{inline_js(data_js)}</script>",
    f"<script>{inline_js((HERE / 'search_port.js').read_text(encoding='utf-8'))}</script>",
    f"<script>{inline_js((HERE / 'semantic_port.js').read_text(encoding='utf-8'))}</script>",
    f"<script>{inline_js((HERE / 'mock_api.js').read_text(encoding='utf-8'))}</script>",
    f"<script>{inline_js((HERE / 'countries_preview.js' if ARTIFACT else ROOT / 'static/js/countries.js').read_text(encoding='utf-8'))}</script>",
    f"<script>{inline_js((ROOT / 'static/js/map.js').read_text(encoding='utf-8'))}</script>",
    f"<script>{inline_js((ROOT / 'static/js/app.js').read_text(encoding='utf-8'))}</script>",
    f"<script>{inline_js((ROOT / 'static/js/glass.js').read_text(encoding='utf-8'))}</script>",
])

html, n = re.subn(r'<link rel="stylesheet" href="/static/css/style.css"\s*/?>',
                  lambda m: f"<style>{css}{banner_css}</style>", html)
assert n == 1, "stylesheet link not found"
html, n = re.subn(r'\s*<script src="/static/js/countries.js"></script>\s*'
                  r'<script src="/static/js/map.js"></script>\s*'
                  r'<script src="/static/js/app.js"></script>\s*'
                  r'<script src="/static/js/glass.js"></script>',
                  lambda m: "\n" + scripts, html)
assert n == 1, "script tags not found"
html = html.replace(
    '<header class="topbar">',
    '<div class="preview-banner"><b>Static demo:</b> everything runs in your browser, including prompt search. '
    'The full app adds optional Claude-powered answers.</div>\n'
    '  <header class="topbar">', 1)

out = Path(os.environ["RELOC_PREVIEW_OUT"]) if os.environ.get("RELOC_PREVIEW_OUT") else \
    ROOT / "dist" / ("artifact.html" if ARTIFACT else "index.html")
out.parent.mkdir(exist_ok=True)
out.write_text(html, encoding="utf-8")
print(out.relative_to(ROOT) if out.is_relative_to(ROOT) else out, f"{len(html) / 1024:.0f} KB")
