"""
Browser tests (Playwright + Chromium) for the real UI.

They start the Flask app on a random local port, open it in headless Chromium,
and click through it like a user. The map's CDN files (world atlas, d3-geo,
topojson) are replaced with tiny local fixtures, so the tests run offline and
the same way every time.

Run:   pip install playwright && python -m playwright install chromium
       python -m pytest tests/e2e -q
Skipped automatically when Playwright or a browser isn't available.
Use PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chrome to use an existing browser.
"""

import os
import threading
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def server():
    from werkzeug.serving import make_server
    from relocaitor.web.app import app

    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    pw = playwright_api.sync_playwright().start()
    try:
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        b = pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
    except Exception as err:  # browser not installed
        pw.stop()
        pytest.skip(f"Chromium not available: {err}")
    yield b
    b.close()
    pw.stop()


def _stub_cdn(route):
    url = route.request.url
    if "world-atlas" in url:
        return route.fulfill(path=str(FIXTURES / "fake_atlas.json"), content_type="application/json")
    if "topojson-client" in url:
        return route.fulfill(path=str(FIXTURES / "fake_topojson.mjs"), content_type="application/javascript")
    if "d3-geo" in url:
        return route.fulfill(path=str(FIXTURES / "fake_d3geo.mjs"), content_type="application/javascript")
    if "datamaps" in url:
        return route.fulfill(path=str(FIXTURES / "fake_datamaps.js"), content_type="application/javascript")
    if "d3/3.5.17" in url or "topojson/1.6.20" in url:
        return route.fulfill(body="", content_type="application/javascript")
    if "fonts.googleapis" in url or "fonts.gstatic" in url:
        return route.fulfill(body="", content_type="text/css")
    if url.startswith(("http://127.0.0.1", "file://", "data:", "blob:")):
        return route.continue_()
    return route.abort()  # nothing else may leave the machine


class Page:
    """Thin wrapper: a Playwright page plus the JS errors it produced."""

    def __init__(self, page, onboarded=True):
        self.page = page
        if onboarded:   # skip the first-visit tips so they don't sit over what the tests click
            page.add_init_script("try { localStorage.setItem('relocaitor.onboarded', '1') } catch (e) {}")
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                and self.errors.append(m.text))
        page.route("**/*", _stub_cdn)

    def __getattr__(self, name):
        return getattr(self.page, name)

    def prompt(self, text, wait_ms=900):
        self.page.fill("#prompt-input", text)
        self.page.press("#prompt-input", "Enter")
        self.page.wait_for_selector("#prompt-result:not(.hidden)", state="attached")
        self.page.wait_for_timeout(wait_ms)

    def card_names(self):
        return self.page.locator(".card-name").all_inner_texts()


@pytest.fixture
def make_page(browser):
    contexts = []

    def _make(width=1440, height=1000, onboarded=True, **opts):
        ctx = browser.new_context(viewport={"width": width, "height": height}, **opts)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        contexts.append(ctx)
        return Page(ctx.new_page(), onboarded=onboarded)

    yield _make
    for c in contexts:
        c.close()


@pytest.fixture
def page(make_page):
    p = make_page()
    yield p
    assert p.errors == [], f"JavaScript errors: {p.errors}"
