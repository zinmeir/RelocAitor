"""User journeys through the real UI."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def open_app(page, url, hash_="", open_groups=True):
    page.goto(url + hash_)
    page.wait_for_selector(".country-card")
    page.wait_for_selector("#map-loader.hidden", state="attached")
    if open_groups:   # the sidebar groups start collapsed (only Priorities is open)
        page.evaluate("document.querySelectorAll('.side-group').forEach(d => d.open = true)")
    page.wait_for_timeout(300)


def test_home_page_loads(page, server):
    open_app(page, server)
    assert len(page.card_names()) == 5
    assert page.locator("#world-map path.country.active").count() > 0
    assert page.locator("#world-map circle.marker").count() > 0       # tiny countries drawn as dots
    assert "Showing 66 of 66" in page.inner_text("#result-count")
    assert page.locator("#flip-insight svg.ico-bulb").count() == 1 and page.inner_text("#flip-insight").strip()


def test_prompt_sets_controls_and_undo_restores(page, server):
    open_app(page, server)
    before = page.card_names()
    page.prompt("I'm a Pakistani software engineer earning $3k a month. I want somewhere safe and "
                "English-speaking in Europe with a path to PR, cold is fine.")
    chips = " ".join(page.locator(".u-chip").all_inner_texts())
    assert "Passport: Pakistan" in chips and "Income: $3,000/mo" in chips and "Region: Europe" in chips
    assert page.input_value("#nationality") == "PAK"
    assert page.input_value("#monthly_income") == "3000"
    assert page.input_value("#region") == "Europe"
    assert page.input_value("#visa_type") == "skilled"
    assert page.is_checked("#require_pr")
    assert "hidden" in page.inner_text("#result-count")

    page.click("#prompt-undo")
    page.wait_for_function("names => JSON.stringify([...document.querySelectorAll('.card-name')].map(e => e.innerText)) === names",
                           arg=__import__("json").dumps(before, separators=(",", ":"), ensure_ascii=False), timeout=5000)
    assert page.input_value("#nationality") == ""
    assert page.input_value("#region") == "All regions"
    assert page.card_names() == before


def test_prompt_exclusions_and_similar_countries(page, server):
    open_app(page, server)
    page.prompt("somewhere like Portugal but cheaper, not Spain")
    assert "excluding Spain" in page.inner_text("#result-count")
    similar = page.locator(".prompt-sub .hit-name").all_inner_texts()
    assert similar and "Spain" not in similar
    page.click("#exclude-clear")
    page.wait_for_timeout(600)
    assert "excluding" not in page.inner_text("#result-count")


def test_prompt_keyword_search_opens_insights(page, server):
    open_app(page, server)
    page.prompt("blue card germany", wait_ms=1200)
    assert page.locator(".prompt-sub .hit-name").all_inner_texts() == ["EU Blue Card"]
    page.wait_for_selector(".breakdown")
    assert page.inner_text(".insight-country").startswith("Germany")


def test_unknown_prompt_explains_itself(page, server):
    open_app(page, server)
    page.prompt("hello there")
    assert "couldn't match" in page.inner_text("#prompt-result")


def test_insights_show_eligibility_with_caveat(page, server):
    open_app(page, server)
    page.select_option("#nationality", "FRA")
    page.wait_for_timeout(600)
    page.prompt("is Germany good for me", wait_ms=1200)
    page.wait_for_selector(".visa-card")
    first = page.locator(".visa-card").first
    assert "free movement" in first.inner_text().lower()
    assert "likely eligible" in first.inner_text().lower()
    assert "aren't checked" in page.inner_text(".visa-caveat")
    assert page.locator(".bd-row").count() == 10            # header + 9 factors
    assert page.get_attribute(".official-link", "href").startswith("https://")


def test_ask_box_answers(page, server):
    open_app(page, server)
    page.locator(".country-card").first.click()
    page.wait_for_selector(".ask-suggestion[data-q]")
    page.click(".ask-suggestion[data-q='How expensive is rent?']")
    page.wait_for_function("document.querySelector('#ask-answer').innerText.includes('$')")
    assert "built-in rules" in page.inner_text("#ask-answer").lower()


def test_compare_three_countries(page, server):
    open_app(page, server)
    toggles = page.locator(".compare-toggle input")
    for k in range(3):
        toggles.nth(k).check()
    page.click("#compare-go")
    page.wait_for_selector("#compare-section:not(.hidden) .compare-table")
    assert page.locator(".compare-table thead th").count() == 4
    assert page.locator(".compare-table td.best").count() > 0
    assert page.is_hidden("#compare-tray")                     # the tray steps aside on the Compare tab
    page.click("#tab-matches")
    toggles.nth(3).click()                                      # a 4th is refused…
    assert "up to 3" in page.inner_text("#toast")
    assert not toggles.nth(3).is_checked()                      # …and its box stays unticked


def test_share_link_restores_state(page, server, make_page):
    open_app(page, server)
    page.click("[data-preset=nomad]")
    page.select_option("#nationality", "PAK")
    page.wait_for_timeout(800)
    page.click("#share-btn")
    url = page.url
    assert "#" in url and "nat=PAK" in url

    other = make_page()
    open_app(other, url)
    assert other.input_value("#nationality") == "PAK"
    assert other.locator(".preset-chip.active").inner_text().strip().endswith("Digital nomad")
    assert other.card_names() == page.card_names()
    assert other.errors == []


def test_reset_restores_defaults(page, server):
    open_app(page, server)
    defaults = page.card_names()
    page.click("[data-preset=retiree]")
    page.wait_for_timeout(700)
    assert page.card_names() != defaults
    page.click("#reset-btn")
    page.wait_for_timeout(700)
    assert page.card_names() == defaults


def test_mobile_layout_has_no_horizontal_scroll(make_page, server):
    p = make_page(390, 844)
    open_app(p, server)
    assert p.evaluate("document.documentElement.scrollWidth") <= 390
    assert p.errors == []


def test_static_builds_work_without_a_server(make_page, tmp_path):
    for flag, name in (([], "index.html"), (["--artifact"], "artifact.html")):
        subprocess.run([sys.executable, str(ROOT / "preview/build_preview.py"), *flag], check=True,
                       cwd=ROOT, capture_output=True)
        p = make_page()
        open_app(p, (ROOT / "dist" / name).as_uri())
        assert len(p.card_names()) == 5
        p.prompt("cheap sunny place for a digital nomad, not Spain")
        assert p.input_value("#visa_type") == "nomad"
        assert "excluding Spain" in p.inner_text("#result-count")
        p.click("#new-search")                                          # a new question, not a follow-up
        p.prompt("I code for American clients from my laptop")          # browser-side trained model
        assert p.locator(".u-chip.kind-learned").count() >= 1
        p.click("#quiz-start")                                         # browser-side preference model
        p.wait_for_selector("#pref-panel:not(.hidden) .pref-pair")
        p.locator(".pref-choose").first.click()
        p.wait_for_timeout(250)
        assert "2 of 8" in p.inner_text("#pref-progress").lower()
        assert p.locator("#landscape circle.ls-dot").count() == 66
        assert p.errors == [], (name, p.errors)


def test_learned_visa_route_from_prompt(page, server):
    open_app(page, server)
    page.prompt("I code for American clients from my laptop")
    chips = page.locator(".u-chip.kind-learned").all_inner_texts()
    assert any("Remote worker" in c for c in chips)
    assert page.input_value("#visa_type") == "nomad"
    assert "trained model" in page.inner_text(".prompt-src").lower()   # CSS uppercases it


def test_preference_quiz_learns_and_applies_weights(page, server):
    open_app(page, server)
    page.click("#quiz-start")
    page.wait_for_selector("#pref-panel:not(.hidden) .pref-pair")
    for _ in range(8):
        # Always choose the cheaper-looking side: whichever card is first is fine for a smoke test.
        page.locator(".pref-choose").first.click()
        page.wait_for_timeout(250)
    page.wait_for_selector("#pref-apply")
    assert "reproduce" in page.inner_text(".pref-done")
    page.click("#pref-apply")
    page.wait_for_timeout(700)
    assert page.inner_text("#pref-apply").strip() == "Applied"
    sliders = [float(page.input_value(f"#{k}")) for k in
               ("salary", "cost", "pr", "job", "climate", "safety", "healthcare", "english", "internet")]
    assert len(set(sliders)) > 1


def test_country_landscape_highlights_the_selection(page, server):
    open_app(page, server)
    assert page.locator("#landscape circle.ls-dot").count() == 66
    assert page.locator("#landscape-legend .ls-legend-item").count() >= 3
    page.locator(".country-card").first.click()
    page.wait_for_selector("#drawer.open")
    page.wait_for_selector("#landscape circle.ls-selected", state="attached")
    assert page.locator("#landscape circle.ls-selected").count() == 1
    assert page.locator("#landscape line.ls-link").count() == 3


def test_confidence_and_pathways(page, server):
    open_app(page, server)
    page.wait_for_selector("#confidence-strip:not(.hidden)")
    assert "scenarios" in page.inner_text("#confidence-strip")
    assert "Likely rank" in page.inner_text(".country-card .card-conf")
    assert page.is_hidden("#pathways-panel")                  # nothing about you entered yet
    page.prompt("I'm Pakistani earning $2,000 a month with $50k savings, safe and English-speaking", wait_ms=1500)
    page.wait_for_selector("#pathways-panel:not(.hidden) .lever")
    assert "Earning $2," in page.inner_text("#pathways-panel")
    page.locator(".near-miss").first.click()
    page.wait_for_selector(".visa-path")
    assert "How to qualify" in page.inner_text("#insights-panel")
    assert "Data reliability" in page.inner_text("#insights-panel")
    assert page.errors == []


def _semantic_build(tmp_path):
    import json
    import os
    from tests import semantic_stub
    payload = tmp_path / "semantic.json"
    payload.write_text(json.dumps(semantic_stub.payload()))
    out = tmp_path / "semantic.html"
    subprocess.run([sys.executable, str(ROOT / "preview/build_preview.py")], check=True, cwd=ROOT, capture_output=True,
                   env={**os.environ, "RELOC_SEMANTIC_PAYLOAD": str(payload), "RELOC_PREVIEW_OUT": str(out)})
    return out


def test_static_build_semantic_search_in_the_browser(make_page, tmp_path):
    from tests import semantic_stub
    out = _semantic_build(tmp_path)
    p = make_page()
    p.page.route("**/@huggingface/transformers**", lambda r: r.fulfill(
        body=semantic_stub.transformers_js_module(), content_type="application/javascript",
        headers={"Access-Control-Allow-Origin": "*"}))
    open_app(p, out.as_uri())
    p.prompt("I want to walk home at night without worrying", wait_ms=1500)
    chips = " ".join(p.locator(".u-chip.kind-semantic").all_inner_texts())
    assert "Safety" in chips
    assert "embeddings" in p.inner_text(".prompt-src").lower()
    p.click("#new-search")
    p.prompt("I can work from my laptop for clients anywhere", wait_ms=1500)
    assert p.locator(".hit-match").count() >= 1
    assert p.errors == []


def test_static_build_falls_back_when_the_model_cannot_load(make_page, tmp_path):
    out = _semantic_build(tmp_path)
    p = make_page()                      # the CDN stub aborts the transformers.js request
    open_app(p, out.as_uri())
    p.prompt("blue card germany", wait_ms=1500)
    assert "couldn't load" in p.inner_text("#prompt-result")
    assert p.locator(".prompt-sub .hit-name").all_inner_texts()[0] == "EU Blue Card"
    assert p.errors == []


def test_rows_report_rank_changes_and_sections_navigate(page, server):
    open_app(page, server)
    page.click(".section-nav a[data-section=results]")
    page.wait_for_timeout(600)
    assert page.inner_text(".section-nav a.active") == "Matches"
    page.locator("#climate").fill("1")
    page.wait_for_timeout(900)
    moves = page.locator(".card-move").all_inner_texts()
    assert moves and all(m.startswith(("▲", "▼")) or m == "New" for m in moves)
    page.keyboard.press("Escape")
    page.locator("body").click(position={"x": 5, "y": 300})
    page.keyboard.press("/")
    assert page.evaluate("document.activeElement.id") == "prompt-input"


def test_phone_preferences_sheet(make_page, server):
    p = make_page(390, 844)
    open_app(p, server)
    assert p.is_hidden("#sidebar .slider") or not p.locator("#sidebar").evaluate("e => e.classList.contains('open')")
    p.click("#prefs-fab")
    p.wait_for_timeout(600)
    assert p.locator("#sidebar").evaluate("e => e.classList.contains('open')")
    p.locator("#nationality").select_option("PAK")
    p.click("#prefs-done")
    p.wait_for_timeout(600)
    assert not p.locator("#sidebar").evaluate("e => e.classList.contains('open')")
    assert "hidden" in p.inner_text("#result-count") or p.input_value("#nationality") == "PAK"
    assert p.errors == []


def test_follow_up_conversation(page, server):
    open_app(page, server)
    page.prompt("safe and English-speaking, I'm Pakistani earning $3k a month", wait_ms=1200)
    assert page.is_visible("#followups")
    page.prompt("what about Asia?", wait_ms=1200)
    assert page.input_value("#region") == "Asia"
    assert "Region: Asia" in page.inner_text("#thread")
    page.prompt("drop Japan", wait_ms=1200)
    assert "excluding Japan" in page.inner_text("#result-count")
    page.click("[data-followup='Undo']")
    page.wait_for_timeout(1200)
    assert "excluding Japan" not in page.inner_text("#result-count")
    assert page.input_value("#region") == "Asia"
    page.prompt("why Portugal?", wait_ms=1500)
    assert page.inner_text(".insight-country").startswith("Portugal")
    page.keyboard.press("Escape")          # close the details panel first
    page.wait_for_timeout(600)
    page.click("#new-search")
    assert page.is_hidden("#followups")


def test_static_build_conversation(make_page):
    subprocess.run([sys.executable, str(ROOT / "preview/build_preview.py")], check=True, cwd=ROOT, capture_output=True)
    p = make_page()
    open_app(p, (ROOT / "dist" / "index.html").as_uri())
    p.prompt("cheap and sunny", wait_ms=900)
    p.prompt("what about Europe?", wait_ms=900)
    assert p.input_value("#region") == "Europe"
    assert "Region: Europe" in p.inner_text("#thread")
    assert p.errors == []


def test_chat_window_keeps_the_page_still(page, server):
    open_app(page, server)
    assert page.is_visible(".starter")
    page.locator(".starter").first.click()
    page.wait_for_selector("#prompt-result:not(.hidden)")
    page.wait_for_timeout(800)
    assert page.inner_text("#first-ask").startswith("Cheap, sunny place")
    assert page.is_hidden(".starter")
    assert page.get_attribute("#prompt-btn", "aria-label") == "Send"
    top = page.evaluate("document.body.scrollTop")
    for msg in ["cheaper", "safer", "warmer", "show more"]:
        page.prompt(msg, wait_ms=700)
    assert page.evaluate("document.body.scrollTop") == top          # the thread scrolls, not the page
    assert page.locator("#thread .turn").count() == 5
    assert page.locator(".bubble.typing").count() == 0
    page.click("#new-search")
    assert page.is_visible(".starter") and page.is_hidden("#first-turn")


def test_job_age_family_and_visa_timelines(page, server):
    open_app(page, server)
    page.prompt("I'm a 58-year-old nurse moving with my wife and two kids, English-speaking", wait_ms=1500)
    assert page.input_value("#occupation") == "healthcare"
    assert page.input_value("#age") == "58"
    assert page.is_checked("#partner") and page.input_value("#children") == "2"
    chips = " ".join(page.locator(".u-chip").all_inner_texts())
    assert "Field: Healthcare" in chips and "Moving with your partner and 2 children" in chips
    assert page.locator(".st-demand").count() >= 1                   # NZ / Canada / Ireland list nurses
    page.goto(server + "#age=58&job=healthcare&c=New%20Zealand")
    page.reload()
    page.wait_for_selector(".journey-card")
    smc = page.locator(".visa-card", has_text="Skilled Migrant Category")
    assert "Age limit: 55 or under" in smc.inner_text()
    assert "NZ$6,450" in smc.inner_text() and smc.locator(".tl-dot.cit").count() == 1
    assert "Healthcare is on it" in page.inner_text(".demand-section")
    assert "secondary source" in page.inner_text(".journey-card")


def test_saved_search_reports_what_changed(page, server):
    open_app(page, server, "#job=tech&r=Europe")
    page.click("#saved-btn")                                         # saved searches live behind the bookmark
    page.click("#save-search")
    assert page.locator(".saved-item").count() == 1
    assert "Europe · Tech & IT" in page.inner_text("#saved-list")
    page.evaluate("""() => { const k = 'relocaitor.saved.v1'; const l = JSON.parse(localStorage.getItem(k));
                     l[0].top = ['Germany', 'Ireland', 'Iceland']; localStorage.setItem(k, JSON.stringify(l)); }""")
    page.reload()
    page.wait_for_selector(".country-card")
    page.evaluate("document.querySelectorAll('.side-group').forEach(d => d.open = true)")
    page.select_option("#region", "Asia")
    page.wait_for_timeout(600)
    page.click("#saved-btn")
    page.click(".saved-open")
    page.wait_for_timeout(1200)
    assert page.input_value("#region") == "Europe" and page.input_value("#occupation") == "tech"
    assert "Iceland" in page.inner_text(".saved-diff").split("dropped:")[1]
    page.click(".saved-del")
    assert "Nothing saved yet" in page.inner_text("#saved-list")


def test_static_build_has_the_journey_features(make_page):
    subprocess.run([sys.executable, str(ROOT / "preview/build_preview.py")], check=True, cwd=ROOT, capture_output=True)
    p = make_page()
    open_app(p, (ROOT / "dist" / "index.html").as_uri())
    p.prompt("Is Toronto good for a data scientist?", wait_ms=1500)
    p.wait_for_selector(".city-card.focus")
    assert p.inner_text(".city-card.focus .city-name").startswith("Toronto")
    assert p.locator(".visa-timeline").count() >= 1
    assert p.errors == []


def test_views_tabs_compare_empty_state_and_methods(page, server):
    open_app(page, server)
    assert page.is_visible("#view-matches") and page.is_hidden("#view-map")
    page.click("#tab-compare")
    assert page.is_visible("#compare-empty") and "Nothing to compare" in page.inner_text("#compare-empty")
    page.click("#compare-top3")
    page.wait_for_selector("#compare-section:not(.hidden) .compare-table")
    assert page.is_hidden("#compare-empty") and page.inner_text("#compare-count") == "3"
    page.focus("#tab-compare")
    page.keyboard.press("ArrowRight")                                 # arrow keys move between tabs
    assert page.get_attribute("#tab-explore", "aria-selected") == "true"
    assert page.is_visible("#landscape") and "v=explore" in page.url
    page.click("#tab-matches")
    page.click("#methods-link")                                       # "How it works" opens Explore at the methods
    assert page.is_visible("#data-sources .sources-body")


def test_map_keyboard_and_region_zoom(page, server):
    open_app(page, server)
    page.select_option("#region", "Europe")
    page.wait_for_timeout(800)
    page.click("#tab-map")
    page.wait_for_timeout(700)
    assert page.get_attribute("#world-map", "viewBox") != "0 0 1000 500"   # zoomed to the region
    page.focus("#map-stage")
    page.keyboard.press("ArrowRight")
    first = page.card_names()[0] if page.locator(".card-name").count() else None
    page.wait_for_selector("#map-tooltip:not(.hidden)")
    assert page.inner_text("#map-tooltip .tt-name") == first
    assert page.inner_text("#map-live").startswith("Number 1,")
    page.keyboard.press("ArrowRight")
    assert page.inner_text("#map-live").startswith("Number 2,")
    page.keyboard.press("Enter")
    page.wait_for_selector("#drawer.open")
    page.keyboard.press("Escape")
    page.select_option("#region", "All regions")
    page.wait_for_function("document.querySelector('#world-map').getAttribute('viewBox').indexOf('0.0 0.0 1000') === 0")


def test_map_tap_shows_a_card_with_see_details(make_page, server):
    p = make_page(390, 844, has_touch=True, is_mobile=True)
    open_app(p, server)
    p.click("#tab-map")
    p.wait_for_timeout(500)
    iso3 = p.get_attribute(".card-conf", "data-code")                 # the #1 country
    target = p.locator(f"#world-map [data-iso3={iso3}]").first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    p.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    p.wait_for_selector(".tt-open")
    assert p.is_hidden("#drawer.open")                                # a tap previews; it doesn't open
    p.click(".tt-open")
    p.wait_for_selector("#drawer.open")
    assert p.errors == []


def test_currency_summaries_and_estimates(page, server):
    open_app(page, server, "#nat=PAK&job=healthcare&age=34&ptn=1&kids=2")
    assert page.inner_text("#profile-summary") == "Pakistani passport, healthcare, age 34, with partner and 2 children"
    assert "PKR" in page.inner_text(".card-figures") and "World Bank" in page.inner_text("#currency-note")
    page.select_option("#currency", "USD")
    page.wait_for_timeout(600)
    assert "$" in page.inner_text(".card-figures") and "cur=USD" in page.url
    page.select_option("#currency", "EUR")
    page.fill("#monthly_income", "3000")
    page.wait_for_timeout(800)
    assert page.inner_text("#monthly_income-local").startswith("≈ €")
    page.goto(server + "#c=Taiwan")                                   # Taiwan's World Bank data is estimated
    page.reload()
    page.wait_for_selector("#drawer.open .bd-row")
    assert page.locator(".breakdown .est").count() >= 3


def test_card_status_line_and_why_first(page, server):
    open_app(page, server, "#nat=PAK")
    first = page.locator(".country-card").first
    assert "open" in first.locator(".card-status").inner_text() or "not researched" in first.inner_text()
    why = page.inner_text(".card-why")
    assert why.startswith("Ahead of ") and "points" in why
    assert page.locator(".card-why").count() == 1


def test_drawer_opens_on_the_section_that_fits_the_search(page, server):
    open_app(page, server, "#nat=PAK")
    page.locator(".country-card").first.click()
    page.wait_for_selector("#drawer.open .ins-nav")
    page.wait_for_timeout(400)
    assert page.get_attribute(".ins-nav a.active", "data-ins") == "visas"
    page.click(".ins-nav a[data-ins=ask]")
    page.wait_for_timeout(700)
    assert page.get_attribute(".ins-nav a.active", "data-ins") == "ask"


def test_empty_results_offer_a_way_out(page, server):
    page.goto(server + "#r=Oceania&x=Australia%7CNew%20Zealand")
    page.wait_for_selector("#top-grid .empty-state")
    assert page.locator("[data-unfilter]").count() >= 2
    page.click("[data-unfilter=exclude]")
    page.wait_for_selector(".country-card")
    assert "excluding" not in page.inner_text("#result-count")


def test_first_visit_tips_show_once(make_page, server):
    p = make_page(onboarded=False)
    p.goto(server)
    p.wait_for_selector("#coach:not([hidden])")
    assert p.inner_text("#coach-step") == "Tip 1 of 3"
    p.click("#coach-next")
    p.click("#coach-next")
    assert p.inner_text("#coach-next") == "Got it"
    p.click("#coach-next")
    assert p.is_hidden("#coach")
    p.reload()
    p.wait_for_selector(".country-card")
    p.wait_for_timeout(700)
    assert p.is_hidden("#coach")
    assert p.errors == []


def test_sidebar_groups_start_collapsed_except_priorities(page, server):
    open_app(page, server, open_groups=False)
    assert page.get_attribute("#group-priorities", "open") is not None
    assert page.get_attribute("#group-about", "open") is None
    assert page.get_attribute("#group-filters", "open") is None
    page.click("#group-filters > summary")
    page.select_option("#region", "Asia")
    page.wait_for_timeout(600)
    assert page.inner_text("#filters-summary") == "1 on: Asia"


def test_visa_cards_say_how_their_data_is_sourced(page, server):
    open_app(page, server, "#c=United%20Kingdom")
    page.wait_for_selector("#drawer.open .visa-card")
    card = page.locator(".visa-card", has_text="Skilled Worker Visa").first
    text = card.locator(".data-status").inner_text()
    assert "from official pages, awaiting verification" in text and "of 24 not known yet" in text
    assert card.locator(".visa-meta .est").count() >= 1                # the curated income figure is an estimate


def test_country_panel_has_pathways_money_career_and_dimensions(page, server):
    open_app(page, server, "#nat=IND&edu=master&de=B1&inc=6000")
    page.goto(server + "#nat=IND&edu=master&de=B1&inc=6000&c=Germany")
    page.reload()
    page.wait_for_selector("#drawer.open .plan-card")
    assert "Blue Card" in page.inner_text("#plan-body") and "1.75 years" in page.inner_text("#plan-body")
    assert page.locator(".dim-row").count() == 6
    page.wait_for_selector("#money-body .money-table")
    assert "38.7%" in page.inner_text("#money-body") or "typical net salary" in page.inner_text("#money-body").lower()
    page.fill("#money-form [name=gross_monthly_usd]", "5000")
    page.click("#money-form button")
    page.wait_for_function("document.querySelector('#money-body').innerText.includes('38.7%')")
    assert page.locator(".proj polyline").count() == 3
    assert "Unemployment" in page.inner_text("#career-body")
    page.click(".ins-nav a[data-ins=ask]")
    page.click(".ask-suggestion[data-q='Which visas can I get?']")
    page.wait_for_function("document.querySelector('#ask-answer').innerText.includes('agents')")
    assert "built-in rules" in page.inner_text("#ask-answer").lower()


def test_workspace_account_shortlist_and_pathway(make_page, server):
    p = make_page()
    p.goto(server + "workspace")
    p.fill("#auth-form [name=email]", "e2e@example.org")
    p.fill("#auth-form [name=password]", "a long enough password")
    p.click("#auth-form [data-mode=register]")
    p.wait_for_selector("#ws-app:not([hidden])")
    open_app(p, server, "#nat=IND&edu=master&de=B1&inc=6000")
    p.click("#save-profile")
    p.wait_for_function("document.querySelector('#toast').innerText.includes('Profile saved')")
    p.goto(server + "#nat=IND&edu=master&de=B1&inc=6000&c=Germany")
    p.reload()
    p.wait_for_selector("#drawer.open .save-pathway")
    p.click("#insight-save")
    p.wait_for_function("document.querySelector('#toast').innerText.includes('saved to My relocation')")
    p.locator(".save-pathway").first.click()
    p.wait_for_function("document.querySelector('#toast').innerText.includes('Pathway saved')")
    p.goto(server + "workspace")
    p.wait_for_selector("#ws-app:not([hidden]) .ws-milestones")
    assert "Germany" in p.inner_text("#ws-shortlist") and "Indian passport" in p.inner_text("#ws-profile")
    p.locator("[data-checklist]").first.click()
    p.wait_for_selector("#ws-checklist .ws-check")
    assert "Degree certificate" in p.inner_text("#ws-checklist")
    p.locator("[data-track]").first.click()
    p.wait_for_selector("#ws-apps select")
    p.select_option("#ws-apps select", "submitted")
    p.wait_for_timeout(300)
    p.reload()
    p.wait_for_selector("#ws-apps select")
    assert p.input_value("#ws-apps select") == "submitted"
    assert p.errors == []


def test_light_theme_is_remembered(page, server):
    open_app(page, server)
    page.click("#theme-btn")
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.reload()
    page.wait_for_selector(".country-card")
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.get_attribute("#theme-btn", "aria-pressed") == "true"
