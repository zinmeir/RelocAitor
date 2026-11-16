/* =============================================================
   app.js — Main controller.
   Manages: prompt search, presets, profile (passport / income / budget), 9 sliders,
   hard filters, reset, shareable URL state, API calls, country grid,
   score breakdowns, insights, what-if, visa eligibility, Q&A,
   side-by-side comparison and the full ranking table.
   ============================================================= */

(function() {

  const META = window.APP_META;
  const FACTOR_KEYS = META.factor_order || Object.keys(META.factors);
  const MAX_COMPARE = 3;
  const VIEWS = ["matches", "map", "compare", "explore"];

  const DEFAULTS = {
    ...META.default_weights,
    top_n: 5,
    region: "All regions",
    visa_type: "any",
    max_difficulty: "",
    require_pr: false,
    only_qualifying: false,
    nationality: "",
    monthly_income: "",
    investment_budget: "",
    occupation: "",
    age: "",
    partner: false,
    children: "",
    education: "",
    experience_years: "",
    english_level: "",
    german_level: "",
    exclude_home: true,
    exclude: [],          // country names to hide (from prompts like "not the US")
    currency: "",         // "" = the passport's currency (or dollars)
  };

  const state = {
    ...DEFAULTS,
    preset: null,
    topCountries: [], allCountries: [],
    selectedCountry: null,
    compare: [],
    view: "matches",
  };

  // ---------- Elements ----------
  const $ = (id) => document.getElementById(id);
  const sliderIds = [...FACTOR_KEYS, "top_n"];
  const sliders = Object.fromEntries(sliderIds.map(id => [id, $(id)]));
  const valueDisplays = Object.fromEntries(
    sliderIds.map(id => [id, document.querySelector(`[data-value-for="${id}"]`)])
  );
  const selectIds   = ["region", "visa_type", "max_difficulty", "nationality", "occupation", "currency", "education", "english_level", "german_level"];
  const numberIds   = ["monthly_income", "investment_budget", "age", "children", "experience_years"];
  const checkboxIds = ["require_pr", "only_qualifying", "exclude_home", "partner"];

  const userInsightEl   = $("user-insight");
  const flipInsightEl   = $("flip-insight");
  const resultCountEl   = $("result-count");
  const topGridEl       = $("top-grid");
  const insightsPanelEl = $("insights-panel");
  const compareSection  = $("compare-section");
  const comparePanelEl  = $("compare-panel");
  const compareTray     = $("compare-tray");
  const tableBody       = document.querySelector("#full-ranking-table tbody");

  let scoreTimer = null;
  let scoreSeq = 0;
  const DEBOUNCE_MS = 180;
  const TYPING_DEBOUNCE_MS = 450;

  // ---------- Small helpers ----------
  function escape(s) {
    return String(s ?? "").replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }
  // ---------- Money in the user's own currency ----------
  // Everything is stored and ranked in US dollars; this only changes how amounts are shown.
  const CUR = META.currencies || { countries: {}, rates: { USD: { usd_per_unit: 1, basis: "dollar" } } };
  function currencyCode() {
    if (state.currency && CUR.rates[state.currency]) return state.currency;
    const home = state.nationality && CUR.countries[state.nationality];
    return home && CUR.rates[home] ? home : "USD";
  }
  const moneyFormats = new Map();
  function money(n) {
    const usd = Number(n), cur = currencyCode();
    if (cur === "USD") return `$${Math.round(usd).toLocaleString()}`;
    let f = moneyFormats.get(cur);
    if (!f) {
      try { f = new Intl.NumberFormat(undefined, { style: "currency", currency: cur, minimumFractionDigits: 0, maximumFractionDigits: 0 }); }
      catch { f = { format: (x) => `${Math.round(x).toLocaleString()} ${cur}` }; }
      moneyFormats.set(cur, f);
    }
    return f.format(usd / CUR.rates[cur].usd_per_unit);
  }
  window.fmtMoney = money;
  const currencyName = (() => {
    let dn = null;
    try { dn = new Intl.DisplayNames(undefined, { type: "currency" }); } catch { /* old browser */ }
    return (code) => (dn && dn.of(code)) || code;
  })();

  // ---------- "≈" on values we estimated rather than measured ----------
  const EST_TITLE = "Estimate: there was no measurement for this country, so this was filled by a model, a regional median or an editorial estimate.";
  const isEst = (code, key) => ((META.estimated || {})[code] || []).includes(key);
  const approx = (code, key) => isEst(code, key)
    ? `<span class="est" title="${EST_TITLE}" aria-label="estimated">≈</span>` : "";
  // Our own line icons (icons.py → window.ICONS). Factor icons take the factor's colour.
  const ico = (name, cls = "") => (window.ICONS && window.ICONS[name])
    ? `<svg class="ico ico-${name} ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${window.ICONS[name]}</svg>` : "";
  const fico = (k) => `<span class="f-${k}">${ico(k)}</span>`;
  const KIND_ICON = { factor: null, learned: "learned", semantic: "semantic", intent: "target", region: "region",
                      exclude: "exclude", include: "pin", similar: "similar", country: "pin", top_n: "top", filter: "check" };
  function chipIcon(c) {
    const name = c.icon || (c.kind === "weight" || c.kind === "factor" ? c.key : KIND_ICON[c.kind]);
    if (!name) return "";
    return META.factors[name] ? fico(name) : ico(name);
  }
  const pct = (v) => Math.round(v * 100);
  const factorValue = (c, key) => {
    const col = { salary: "average_salary", cost: "cost_of_living", pr: "pr_ease", job: "job_market",
                  climate: "climate", safety: "safety", healthcare: "healthcare",
                  english: "english", internet: "internet" }[key];
    return META.factors[key].invert ? 1 - c[col] : c[col];
  };
  const profileIsSet = () => Boolean(state.nationality || state.monthly_income !== "" || state.investment_budget !== ""
                                     || state.occupation || state.age !== "" || state.partner || Number(state.children) > 0
                                     || state.education || state.experience_years !== "" || state.english_level || state.german_level);

  let toastTimer = null;
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 2400);
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  // ---------- Slider painting ----------
  function paintSlider(id) {
    const el = sliders[id];
    const min = parseFloat(el.min), max = parseFloat(el.max);
    const p = ((parseFloat(el.value) - min) / (max - min)) * 100;
    el.style.background = `linear-gradient(90deg, var(--slider-fill) ${p}%, var(--rule) ${p}%)`;
  }

  // ---------- State <-> controls ----------
  function applyStateToControls() {
    renderSummaries();
    for (const id of sliderIds) {
      sliders[id].value = state[id];
      valueDisplays[id].textContent = id === "top_n" ? String(state[id]) : Number(state[id]).toFixed(2);
      paintSlider(id);
    }
    for (const id of selectIds) $(id).value = state[id];
    for (const id of numberIds) $(id).value = state[id];
    for (const id of checkboxIds) $(id).checked = state[id];
    document.querySelectorAll(".preset-chip").forEach(el =>
      el.classList.toggle("active", el.dataset.preset === state.preset));
    if (window.GlassUI) window.GlassUI.sync();
  }

  function clearPreset() {
    if (!state.preset) return;
    state.preset = null;
    document.querySelectorAll(".preset-chip").forEach(el => el.classList.remove("active"));
  }

  // ---------- Wire controls ----------
  for (const id of sliderIds) {
    paintSlider(id);
    sliders[id].addEventListener("input", (e) => {
      const raw = parseFloat(e.target.value);
      state[id] = raw;
      valueDisplays[id].textContent = id === "top_n" ? String(raw) : raw.toFixed(2);
      paintSlider(id);
      if (id !== "top_n") clearPreset();
      renderSummaries();
      scheduleScore();
    });
  }
  for (const id of selectIds) {
    $(id).addEventListener("change", (e) => {
      state[id] = e.target.value;
      if (id === "visa_type" || id === "max_difficulty") clearPreset();
      renderSummaries();
      scheduleScore();
    });
  }
  for (const id of numberIds) {
    $(id).addEventListener("input", (e) => {
      const v = e.target.value.trim();
      state[id] = v === "" || Number(v) < 0 ? "" : v;
      renderSummaries();
      scheduleScore(TYPING_DEBOUNCE_MS);
    });
  }
  for (const id of checkboxIds) {
    $(id).addEventListener("change", (e) => {
      state[id] = e.target.checked;
      if (id === "require_pr") clearPreset();
      renderSummaries();
      scheduleScore();
    });
  }

  document.querySelectorAll(".preset-chip").forEach(el => {
    el.addEventListener("click", () => applyPreset(el.dataset.preset));
  });

  function applyPreset(key) {
    const p = META.presets[key];
    if (!p) return;
    Object.assign(state, p.weights, {
      visa_type: "any", require_pr: false, max_difficulty: "", only_qualifying: false,
    }, p.filters || {});
    state.preset = key;
    applyStateToControls();
    fetchScore();
    toast(`${p.label} profile applied`);
  }

  $("reset-btn").addEventListener("click", () => {
    Object.assign(state, DEFAULTS, { preset: null, exclude: [] });
    $("prompt-result").classList.add("hidden");
    if (typeof endConversation === "function") endConversation();
    applyStateToControls();
    clearCompare();
    clearInsights();
    fetchScore();
  });

  $("share-btn").addEventListener("click", async () => {
    if (window.RELOC_PREVIEW) {
      toast("Share links work in the deployed app. They save every setting in the URL.");
      return;
    }
    syncURL();
    try {
      await navigator.clipboard.writeText(location.href);
      toast("Link copied. Anyone opening it sees exactly these results.");
    } catch {
      toast("Copy the address bar URL to share these results.");
    }
  });

  function scheduleScore(delay = DEBOUNCE_MS) {
    clearTimeout(scoreTimer);
    scoreTimer = setTimeout(fetchScore, delay);
  }

  // ---------- Shareable URL (state lives in the #hash) ----------
  function syncURL() {
    if (window.RELOC_PREVIEW) return;   // standalone preview build: no URL state
    const p = new URLSearchParams();
    const w = FACTOR_KEYS.map(k => Number(state[k]).toFixed(2));
    if (FACTOR_KEYS.some(k => state[k] !== DEFAULTS[k])) p.set("w", w.join(","));
    if (state.region !== DEFAULTS.region) p.set("r", state.region);
    if (state.top_n !== DEFAULTS.top_n) p.set("n", state.top_n);
    if (state.nationality) p.set("nat", state.nationality);
    if (state.monthly_income !== "") p.set("inc", state.monthly_income);
    if (state.investment_budget !== "") p.set("inv", state.investment_budget);
    if (state.occupation) p.set("job", state.occupation);
    if (state.age !== "") p.set("age", state.age);
    if (state.partner) p.set("ptn", "1");
    if (state.children !== "" && Number(state.children) > 0) p.set("kids", state.children);
    if (state.education) p.set("edu", state.education);
    if (state.experience_years !== "") p.set("exp", state.experience_years);
    if (state.english_level) p.set("en", state.english_level);
    if (state.german_level) p.set("de", state.german_level);
    if (state.visa_type !== "any") p.set("vt", state.visa_type);
    if (state.max_difficulty) p.set("md", state.max_difficulty);
    if (state.require_pr) p.set("pr", "1");
    if (state.only_qualifying) p.set("oq", "1");
    if (!state.exclude_home) p.set("eh", "0");
    if (state.preset) p.set("p", state.preset);
    if (state.exclude.length) p.set("x", state.exclude.join("|"));
    if (state.selectedCountry) p.set("c", state.selectedCountry);
    if (state.compare.length) p.set("cmp", state.compare.join("|"));
    if (state.currency) p.set("cur", state.currency);
    if (state.view !== "matches") p.set("v", state.view);
    const hash = p.toString();
    try {
      history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
    } catch { /* some embedded/sandboxed frames block history changes */ }
  }

  function readURL() {
    if (window.RELOC_PREVIEW) return;
    const p = new URLSearchParams(location.hash.slice(1));
    if (p.has("w")) {
      const vals = p.get("w").split(",").map(Number);
      FACTOR_KEYS.forEach((k, i) => {
        if (Number.isFinite(vals[i])) state[k] = Math.min(1, Math.max(0, vals[i]));
      });
    }
    const regions = ["All regions", ...META.regions];
    if (regions.includes(p.get("r"))) state.region = p.get("r");
    const n = parseInt(p.get("n"), 10);
    if (n >= 3 && n <= 10) state.top_n = n;
    if (META.nationalities.some(x => x.code === p.get("nat"))) state.nationality = p.get("nat");
    if (p.get("inc") && Number(p.get("inc")) >= 0) state.monthly_income = p.get("inc");
    if (p.get("inv") && Number(p.get("inv")) >= 0) state.investment_budget = p.get("inv");
    if (META.occupations.some(o => o.key === p.get("job"))) state.occupation = p.get("job");
    const age = parseInt(p.get("age"), 10);
    if (age >= 16 && age <= 100) state.age = String(age);
    state.partner = p.get("ptn") === "1";
    const kids = parseInt(p.get("kids"), 10);
    if (kids >= 1 && kids <= 12) state.children = String(kids);
    const scales = META.scales || { education: [], cefr: [] };
    if (scales.education.includes(p.get("edu"))) state.education = p.get("edu");
    const exp = Number(p.get("exp"));
    if (p.get("exp") && exp >= 0 && exp <= 60) state.experience_years = p.get("exp");
    if (scales.cefr.includes(p.get("en"))) state.english_level = p.get("en");
    if (scales.cefr.includes(p.get("de"))) state.german_level = p.get("de");
    if (META.visa_types.some(v => v.key === p.get("vt"))) state.visa_type = p.get("vt");
    if (["Easy", "Moderate"].includes(p.get("md"))) state.max_difficulty = p.get("md");
    state.require_pr = p.get("pr") === "1";
    state.only_qualifying = p.get("oq") === "1";
    state.exclude_home = p.get("eh") !== "0";
    if (META.presets[p.get("p")]) state.preset = p.get("p");
    if (p.get("x")) state.exclude = p.get("x").split("|").filter(n => META.nationalities.some(x => x.name === n));
    if (p.get("c")) state.selectedCountry = p.get("c");
    if (p.get("cmp")) state.compare = p.get("cmp").split("|").filter(Boolean).slice(0, MAX_COMPARE);
    if (CUR.rates[p.get("cur")]) state.currency = p.get("cur");
    if (VIEWS.includes(p.get("v"))) state.view = p.get("v");
  }

  // ---------- API payloads ----------
  function currentWeights() {
    return Object.fromEntries(FACTOR_KEYS.map(k => [k, state[k]]));
  }
  function currentProfile() {
    return {
      nationality: state.nationality || null,
      monthly_income: state.monthly_income === "" ? null : Number(state.monthly_income),
      investment_budget: state.investment_budget === "" ? null : Number(state.investment_budget),
      occupation: state.occupation || null,
      age: validAge(state.age),
      partner: state.partner ? true : null,
      children: state.children === "" ? null : Math.max(0, Math.min(12, Math.round(Number(state.children)) || 0)),
      education: state.education || null,
      experience_years: state.experience_years === "" ? null : Math.max(0, Math.min(60, Number(state.experience_years) || 0)),
      english: state.english_level || null,
      german: state.german_level || null,
      visa_type: state.visa_type,
      require_pr: state.require_pr,
      max_difficulty: state.max_difficulty || null,
      only_qualifying: state.only_qualifying,
      exclude_home: state.exclude_home,
      exclude_countries: state.exclude,
    };
  }
  function validAge(v) {
    const n = Math.round(Number(v));
    return v === "" || !Number.isFinite(n) || n < 16 || n > 100 ? null : n;
  }
  const basePayload = () => ({ weights: currentWeights(), region: state.region, profile: currentProfile() });

  // ---------- Scoring ----------
  async function fetchScore() {
    const seq = ++scoreSeq;
    syncURL();
    try {
      const data = await postJSON("/api/score", { ...basePayload(), top_n: state.top_n });
      if (seq !== scoreSeq) return;   // a newer request is in flight; drop this one

      const oldRanks = state.allCountries.length
        ? new Map(state.allCountries.map(c => [c.country_name, c.rank])) : null;
      state.topCountries = data.top;
      state.allCountries = data.all;

      userInsightEl.textContent = data.user_insight;
      flipInsightEl.innerHTML = data.flip ? `${ico("bulb")}<span>${escape(data.flip.text)}</span>` : "";
      renderResultCount(data.counts);
      window.MapView.update(data.all);
      window.MapView.focusRegion(state.region === "All regions" ? null : data.all.map(c => c.country_code));
      renderSummaries();
      renderTopCountries(data.top, oldRanks);
      renderFullTable(data.all);

      renderLandscape();
      fetchConfidence(seq);
      fetchPathways(seq);
      if (state.selectedCountry) fetchInsights(state.selectedCountry, { scroll: false });
      if (!compareSection.classList.contains("hidden") && state.compare.length >= 2) runCompare({ scroll: false });
    } catch (err) {
      console.error("Score fetch failed:", err);
      topGridEl.innerHTML = `<div class="error-banner">Couldn't score countries: ${escape(err.message)}</div>`;
    }
  }

  // ---------- How sure is the ranking? (Monte Carlo over weights + data) ----------
  async function fetchConfidence(seq) {
    try {
      const d = await postJSON("/api/confidence", { ...basePayload(), top_n: state.top_n });
      if (seq !== scoreSeq) return;
      renderConfidence(d);
    } catch (err) { console.error("Confidence fetch failed:", err); }
  }

  const pctOf = (p) => `${Math.floor(p * 100 + 0.5)}%`;
  function renderConfidence(d) {
    const el = $("confidence-strip");
    if (!d.verdict) { el.classList.add("hidden"); return; }
    const icon = ico({ clear: "target", likely: "trend", close: "scale", only: "target" }[d.verdict.level]);
    const ties = d.ties.map(t => `<li>#${t.rank} ${escape(t.a)} and #${t.rank + 1} ${escape(t.b)} are effectively tied
      (${escape(t.a)} ahead in ${pctOf(t.p_a_ahead)} of scenarios)</li>`).join("");
    el.innerHTML = `
      <div class="conf-head conf-${d.verdict.level}"><span class="conf-icon" aria-hidden="true">${icon}</span>
        <p><b>How sure is this ranking?</b> ${escape(d.verdict.text)}</p></div>
      ${ties ? `<ul class="conf-ties">${ties}</ul>` : ""}
      <p class="conf-note">Each of ${d.samples} scenarios nudges your weights (±${d.weight_sd}) and every data point
        by how reliable its source is (measured data a little, estimates more), then re-ranks.</p>`;
    el.classList.remove("hidden");
    for (const c of d.countries) {
      const slot = topGridEl.querySelector(`.card-conf[data-code="${c.country_code}"]`);
      if (!slot) continue;
      const range = c.rank_lo === c.rank_hi ? `#${c.rank_lo}` : `#${c.rank_lo}–${c.rank_hi}`;
      const rel = c.reliability;
      slot.innerHTML = `<span title="Rank in 90% of what-if scenarios">Likely rank <b>${range}</b></span>
        <span class="rel-dot rel-${rel.level}" title="Data reliability: ${rel.level}. ${rel.measured}/${rel.factors} factors from measured sources${rel.weak.length ? ". " + escape(rel.weak.map(w => w.text).join("; ")) : ""}"><span>Data ${rel.level.toLowerCase()}</span></span>`;
    }
  }

  // ---------- How could I qualify? (counterfactual visa reasoning) ----------
  async function fetchPathways(seq) {
    const el = $("pathways-panel");
    const relevant = profileIsSet() || state.visa_type !== "any" || state.require_pr || state.max_difficulty || state.only_qualifying;
    if (!relevant) { el.classList.add("hidden"); return; }
    try {
      const d = await postJSON("/api/pathways", basePayload());
      if (seq !== scoreSeq) return;
      renderPathways(d);
    } catch (err) { console.error("Pathways fetch failed:", err); }
  }

  function renderPathways(d) {
    const el = $("pathways-panel");
    const hint = { passport: "passport", income: "monthly income", savings: "savings" };
    const missing = d.missing.length
      ? `<p class="path-hint">Add your ${d.missing.map(m => hint[m]).join(", ")} in <b>Your profile</b> for exact gaps.</p>` : "";
    const levers = d.levers.map(l => `<li class="lever lever-${l.kind}">${escape(l.text)}</li>`).join("");
    const near = d.near_misses.map(n => `
      <button type="button" class="near-miss" data-country="${escape(n.country)}">
        <span class="nm-country">${escape(n.country)}</span>
        <span class="nm-visa">${escape(n.visa)}</span>
        <span class="nm-step">${escape(n.steps[0] || "")}</span>
      </button>`).join("");
    el.innerHTML = `
      <div class="path-head"><h3>How to open more doors</h3>
        <p>You have a likely visa route into <b>${d.open_count}</b> of the ${d.candidate_count} countries you're considering.
          These come from re-running the eligibility rules with one thing changed.</p></div>
      ${levers ? `<h4>Biggest levers</h4><ul class="levers">${levers}</ul>` : ""}
      ${near ? `<h4>Closest visas you don't qualify for yet</h4><div class="near-list">${near}</div>` : ""}
      ${!levers && !near ? `<p class="path-hint">Nothing is just out of reach: every country you're considering is either open to you or needs a bigger change (a different passport or a sponsor).</p>` : ""}
      ${missing}
      <p class="muted-note">Only passport, income and savings are checked. Real applications also depend on your job, age, education and language tests.</p>`;
    el.querySelectorAll(".near-miss").forEach(b => b.addEventListener("click", () => fetchInsights(b.dataset.country)));
    el.classList.remove("hidden");
  }

  function renderResultCount(counts) {
    if (!counts) { resultCountEl.textContent = ""; return; }
    const hidden = counts.hidden_by_filters;
    resultCountEl.innerHTML = `Showing ${counts.shown} of ${counts.in_region} countries` +
      (hidden ? ` · <b>${hidden} hidden</b> by your passport, budget or visa filters` : "") +
      (state.exclude.length ? ` · excluding ${escape(state.exclude.join(", "))} <button type="button" class="exclude-clear" id="exclude-clear">show again</button>` : "");
    const clr = $("exclude-clear");
    if (clr) clr.addEventListener("click", () => { state.exclude = []; fetchScore(); });
  }

  // ---------- Top cards ----------
  // Rows glide from where they were to where they now rank (FLIP), say how far they moved,
  // and their match % counts to the new value, so a slider change is easy to follow.
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function renderTopCountries(list, oldRanks = null) {
    topGridEl.removeAttribute("aria-busy");
    if (!list.length) {
      topGridEl.innerHTML = emptyResultsHTML();
      return;
    }
    const before = new Map();
    topGridEl.querySelectorAll(".country-card").forEach(el =>
      before.set(el.dataset.country, { top: el.getBoundingClientRect().top, score: Number(el.dataset.score) }));

    topGridEl.innerHTML = list.map((c, k) => cardHTML(c, oldRanks, k === 0 ? leadWhy(list) : "")).join("");
    topGridEl.querySelectorAll(".country-card").forEach(el => {
      el.addEventListener("click", () => fetchInsights(el.dataset.country));
    });
    topGridEl.querySelectorAll(".compare-toggle").forEach(el => {
      el.addEventListener("click", (e) => e.stopPropagation());
      el.querySelector("input").addEventListener("change", (e) => toggleCompare(el.dataset.country, e.target.checked));
    });
    markSelectedCard();
    if (reduceMotion || !before.size) return;

    topGridEl.querySelectorAll(".country-card").forEach(el => {
      const was = before.get(el.dataset.country);
      if (!was) { el.classList.add("entering"); return; }
      const dy = was.top - el.getBoundingClientRect().top;
      if (Math.abs(dy) > 1) {
        el.style.transition = "none";
        el.style.transform = `translateY(${dy}px)`;
        requestAnimationFrame(() => requestAnimationFrame(() => {
          el.style.transition = "";
          el.style.transform = "";
        }));
      }
      const num = el.querySelector(".card-score .n");
      const from = pct(was.score), to = pct(Number(el.dataset.score));
      if (num && from !== to) countTo(num, from, to);
    });
  }

  function countTo(node, from, to, ms = 450) {
    const t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      node.textContent = Math.round(from + (to - from) * e);
      if (k < 1 && node.isConnected) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }


  function stackBarHTML(c) {
    const segs = FACTOR_KEYS
      .map(k => [k, c.contributions[k] || 0])
      .filter(([, v]) => v > 0.001)
      .map(([k, v]) => `<div class="stack-seg seg-${k}" style="width:${(v * 100).toFixed(1)}%"
          title="${escape(META.factors[k].label)}: +${(v * 100).toFixed(1)} pts"></div>`)
      .join("");
    return `<div class="stack-bar" title="What makes up the score">${segs}</div>`;
  }

  // One status line per card: visas first, then whether your field is in demand.
  function statusLine(c) {
    const parts = [];
    const n = c.qualifying_visas;
    const forYou = profileIsSet() || state.visa_type !== "any" || state.require_pr || state.max_difficulty;
    if (c.visas_researched === false) {
      parts.push(`<span class="st st-unknown" title="We haven't researched this country's visa routes yet">${ico("question")}Visas not researched yet</span>`);
    } else if (typeof n === "number") {
      const text = forYou ? (n ? `${n} visa${n === 1 ? "" : "s"} open` : "No visa open to you yet")
                          : `${n} visa route${n === 1 ? "" : "s"}`;
      parts.push(`<span class="st ${n ? "st-open" : "st-none"}">${ico(n ? "check" : "lock")}${text}</span>`);
    }
    if (c.field_in_demand) parts.push(`<span class="st st-demand" title="Your field is on this country's official shortage list">${ico("trend")}field in demand</span>`);
    return parts.length ? `<p class="card-status">${parts.join(`<span class="sr-only">, </span>`)}</p>` : "";
  }

  // Why #1 beats #2, in one sentence: the factors where #1 earns the most extra points.
  function leadWhy(list) {
    if (list.length < 2) return "";
    const [a, b] = list;
    if (a.score - b.score < 0.0005) return `${a.country_name} and ${b.country_name} are effectively tied.`;
    const gains = FACTOR_KEYS
      .map(k => [k, ((a.contributions[k] || 0) - (b.contributions[k] || 0)) * 100])
      .filter(([, d]) => d >= 0.5)
      .sort((x, y) => y[1] - x[1]).slice(0, 2);
    if (!gains.length) return "";
    const names = gains.map(([k]) => { const l = META.factors[k].label; return /^English/.test(l) ? l : l.toLowerCase(); });
    const pts = gains.map(([, d]) => `+${d.toFixed(1)}`).join(" and ");
    return `Ahead of ${b.country_name} mainly on ${names.join(" and ")} (${pts} points).`;
  }

  // Shown when the filters leave nothing: one button per filter that is on, each removing it.
  const FILTER_FIXES = [
    ["only_qualifying", () => state.only_qualifying, "Include visas I don't qualify for yet"],
    ["visa_type", () => state.visa_type !== "any", "Allow any visa type"],
    ["max_difficulty", () => Boolean(state.max_difficulty), "Allow harder visas"],
    ["require_pr", () => state.require_pr, "Drop the residency requirement"],
    ["region", () => state.region !== "All regions", "Search every region"],
    ["exclude", () => state.exclude.length > 0, "Show the countries I excluded"],
  ];
  function emptyResultsHTML() {
    const fixes = FILTER_FIXES.filter(([, on]) => on());
    return `<li class="empty-state">
        <h3>No country passes all your filters</h3>
        <p>${fixes.length ? "Loosen one of these to see matches again." : "Try a different region or fewer must-haves."}</p>
        <div class="empty-actions">${fixes.map(([key, , label]) =>
          `<button type="button" class="btn" data-unfilter="${key}">${escape(label)}</button>`).join("")}</div>
      </li>`;
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-unfilter]");
    if (!b) return;
    const key = b.dataset.unfilter;
    state[key] = key === "exclude" ? [] : DEFAULTS[key];
    applyStateToControls();
    fetchScore();
  });

  function moveHTML(c, oldRanks) {
    if (!oldRanks) return "";
    const was = oldRanks.get(c.country_name);
    if (was === undefined) return `<span class="card-move new" title="Newly in your list">New</span>`;
    const d = was - c.rank;
    if (!d) return "";
    return `<span class="card-move ${d > 0 ? "up" : "down"}" title="${d > 0 ? "Up" : "Down"} ${Math.abs(d)} since your last change">${d > 0 ? "▲" : "▼"} ${Math.abs(d)}</span>`;
  }

  function cardHTML(c, oldRanks = null, why = "") {
    const checked = state.compare.includes(c.country_name) ? "checked" : "";
    return `
      <li class="country-card" data-country="${escape(c.country_name)}" data-score="${c.score}" tabindex="0"
          aria-label="#${c.rank} ${escape(c.country_name)}, ${pct(c.score)}% match">
        <span class="card-rank" aria-hidden="true">${String(c.rank).padStart(2, "0")}</span>
        <div class="card-id">
          <div class="card-name">${escape(c.country_name)}</div>
          <div class="card-region">${escape(c.region)}${moveHTML(c, oldRanks)}</div>
        </div>
        <div class="card-match">
          <div class="card-score"><span class="n">${pct(c.score)}</span><small>%</small></div>
          ${stackBarHTML(c)}
        </div>
        <div class="card-facts">
          <span class="card-figures"><span>${approx(c.country_code, "salary_money")}<b>${money(c.salary_usd_month)}</b> salary</span> <span>${approx(c.country_code, "rent_money")}<b>${money(c.rent_usd_month)}</b> rent</span></span>
          ${statusLine(c)}
        </div>
        ${why ? `<p class="card-why">${ico("bulb")}<span>${escape(why)}</span></p>` : ""}
        <div class="card-conf" data-code="${escape(c.country_code)}"></div>
        <label class="compare-toggle" data-country="${escape(c.country_name)}">
          <input type="checkbox" ${checked} aria-label="Compare ${escape(c.country_name)}" /><span>Compare</span>
        </label>
      </li>
    `;
  }

  function metric(label, v) {
    return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${v.toFixed(2)}</div></div>`;
  }

  function markSelectedCard() {
    document.querySelectorAll(".country-card").forEach(el =>
      el.classList.toggle("selected", el.dataset.country === state.selectedCountry));
  }

  // keyboard access for cards
  topGridEl.addEventListener("keydown", (e) => {
    const card = e.target.closest(".country-card");
    if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); fetchInsights(card.dataset.country); }
  });

  // ---------- Insights ----------
  async function fetchInsights(countryName, { scroll = true } = {}) {
    try {
      const data = await postJSON("/api/insights", { ...basePayload(), country: countryName });
      state.selectedCountry = countryName;
      syncURL();
      renderInsights(data);

      const iso3 = data.country.country_code;
      if (iso3) window.MapView.lockCountry(iso3);
      markSelectedCard();
      renderLandscape();
      const fresh = !drawerEl.classList.contains("open") || insightsPanelEl.dataset.country !== countryName;
      insightsPanelEl.dataset.country = countryName;
      openDrawer(scroll);
      if (scroll && fresh) requestAnimationFrame(() => jumpIns(initialSection(), { smooth: false }));
    } catch (err) {
      console.error("Insights fetch failed:", err);
      clearInsights();
    }
  }

  const METHOD_LABEL = { computed: "", "computed-partial": " (partial data)", rule: "", "ml-imputed": "",
                         editorial: " (editorial estimate)", "editorial-fallback": " (no source data: editorial estimate)",
                         "ml-estimate": " (ML estimate)", "regional-median": " (no data: regional median)" };
  function sourceOf(c, key) {
    const col = { salary: "average_salary", cost: "cost_of_living", pr: "pr_ease", job: "job_market",
                  climate: "climate", safety: "safety", healthcare: "healthcare", english: "english",
                  internet: "internet" }[key];
    const p = (c.provenance || {})[col];
    return p ? `${humanize(p.detail)}${METHOD_LABEL[p.method] || ""}` : "";
  }
  // "SL.UEM.TOTL.ZS 2025=6.16" -> "Unemployment % (2025): 6.16"
  function humanize(detail) {
    const names = META.source_names || {};
    return detail
      .replace(/ \[ML: ([^\]]+)\]/, (m, s) => ` · gap filled by an ML model (cross-validated ${s.replace(/[A-Z][A-Z0-9_.]+ /g, "")})`)
      .replace(/([A-Z][A-Z0-9_.]*(?:\((?:consumption|gdp)\))?)(?: (\d{4}|ML))?=([^;·]+)/g,
        (m, id, year, val) => names[id] ? `${names[id]}${year === "ML" ? " (ML estimate)" : year ? ` (${year})` : ""}: ${val.trim()}` : m)
      .replace(/\s*·/g, " ·")
      .replace(/^([A-Z_]+) ([^=]+)=(.+)$/, (m, id, where, val) => names[id] ? `${names[id]} in ${where}: ${val}` : m);
  }

  function breakdownHTML(c) {
    const rows = FACTOR_KEYS
      .map(k => ({ k, v: factorValue(c, k), contrib: c.contributions[k] || 0, w: state[k] }))
      .sort((a, b) => b.contrib - a.contrib || b.v - a.v);
    return `
      <div class="breakdown">
        <div class="bd-row bd-head"><span>Factor · your weight</span><span>Country value</span>
          <span class="bd-val">Value</span><span class="bd-contrib">Points</span></div>
        ${rows.map(r => `
          <div class="bd-row" title="${escape(META.factors[r.k].label)}: value ${r.v.toFixed(2)} × weight share = ${(r.contrib * 100).toFixed(1)} points&#10;Source: ${escape(sourceOf(c, r.k))}">
            <span class="bd-label">${fico(r.k)} ${escape(META.factors[r.k].label)} · ${Number(r.w).toFixed(2)}</span>
            <div class="bd-track"><div class="bd-fill seg-${r.k}" style="width:${(r.v * 100).toFixed(0)}%; opacity:${r.w > 0 ? 1 : 0.3}"></div></div>
            <span class="bd-val">${approx(c.country_code, r.k)}${r.v.toFixed(2)}</span>
            <span class="bd-contrib">${r.contrib > 0 ? "+" + (r.contrib * 100).toFixed(1) : "–"}</span>
          </div>`).join("")}
      </div>
      <p class="bd-note">
        Points add up to the raw match (${(c.raw_score * 100).toFixed(1)} / 100). The % shown elsewhere rescales that
        so the best of all ${META.country_count} countries is 100% and the worst is 0%.
      </p>
      <details class="source-list">
        <summary>Where do these numbers come from?</summary>
        <ul>${rows.map(r => `<li><b>${fico(r.k)} ${escape(META.factors[r.k].label)}</b>: ${escape(sourceOf(c, r.k) || "n/a")}</li>`).join("")}</ul>
        <p>Methods for every factor are in <b>Data sources &amp; methods</b> at the bottom of the page.</p>
      </details>`;
  }

  function whatIfHTML(data) {
    const c = data.country;
    if (c.hidden_by_filters) return `<p style="color:var(--text-muted)">Not ranked under your current filters.</p>`;
    if (c.rank === 1) return `<p>Already your #1 match.</p>`;
    if (!data.what_if.length) return `<p style="color:var(--text-muted)">No single slider change moves ${escape(c.country_name)} up. Its position is driven by the data rather than your weights.</p>`;
    return `<ul class="whatif-list">${data.what_if.map(t => `<li>${escape(t.text)}</li>`).join("")}</ul>`;
  }

  // ---------- Drawer sections: Overview · Visas & costs · Living there · Ask ----------
  const INS_SECTIONS = [["overview", "Overview"], ["visas", "Visas &amp; costs"], ["pathways", "Pathways"], ["money", "Money"],
                        ["career", "Career"], ["living", "Living there"], ["ask", "Ask"]];
  // Open on the part that matches the search: a named city → Living there; a profile or visa filter → Visas.
  function initialSection() {
    if (state.focusCity) return "living";
    if (profileIsSet() || state.visa_type !== "any" || state.require_pr || state.max_difficulty || state.only_qualifying) return "visas";
    return "overview";
  }
  function markIns(id) {
    insightsPanelEl.querySelectorAll(".ins-nav a").forEach(a => {
      const on = a.dataset.ins === id;
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
    });
  }
  function jumpIns(id, { smooth = true } = {}) {
    const sec = $(`ins-${id}`);
    if (!sec) return;
    const behavior = smooth && !reduceMotion ? "smooth" : "auto";
    insLock = performance.now() + (behavior === "smooth" ? 900 : 100);   // let the jump finish before the spy takes over
    if (id === "overview") drawerEl.scrollTo({ top: 0, behavior });
    else sec.scrollIntoView({ block: "start", behavior });     // scroll-margin-top clears the sticky links
    markIns(id);
  }
  function wireInsightNav() {
    insightsPanelEl.querySelectorAll(".ins-nav a").forEach(a => a.addEventListener("click", (e) => {
      e.preventDefault();
      jumpIns(a.dataset.ins);
    }));
    spyIns();
  }
  let insLock = 0;
  function spyIns() {
    if (performance.now() < insLock) return;
    const nav = insightsPanelEl.querySelector(".ins-nav");
    if (!nav) return;
    const line = nav.getBoundingClientRect().bottom + 40;
    let current = "overview";
    for (const [id] of INS_SECTIONS) {
      const sec = $(`ins-${id}`);
      if (sec && sec.getBoundingClientRect().top <= line) current = id;
    }
    if (drawerEl.scrollTop + drawerEl.clientHeight >= drawerEl.scrollHeight - 4) current = "ask";
    markIns(current);
  }

  function renderInsights(data) {
    const c = data.country;
    const visas = [...(data.visas || [])].sort((a, b) => {
      const order = { eligible: 0, conditional: 1, ineligible: 2 };
      return (b.qualifies - a.qualifies) || (order[a.eligibility.status] - order[b.eligibility.status]);
    });
    const rentShare = c.rent_usd_month / c.salary_usd_month;
    const rankLine = c.hidden_by_filters
      ? `Not ranked under your current filters`
      : `Ranked <b>#${c.rank}</b> of ${c.total} for you`;
    const filterTag = state.visa_type !== "any"
      ? `<span class="filter-tag">filter: ${escape(state.visa_type)}</span>` : "";
    const inCompare = state.compare.includes(c.country_name);

    insightsPanelEl.innerHTML = `
      <div class="insight-top">
        <div>
          <h2 class="insight-country" id="drawer-title">${escape(c.country_name)}</h2>
          <div class="insight-rank">${rankLine}, ${escape(c.region)}${c.cluster ? `. Group: <span class="cluster-chip" title="Machine-learned cluster (k-means over the 9 factor scores)">${escape(c.cluster)}</span>` : ""}</div>
        </div>
        <div class="insight-score"><div class="card-score">${pct(c.score)}<small>%</small></div><span>${escape(c.score_category.toLowerCase())} match</span></div>
      </div>
      <nav class="ins-nav" aria-label="Sections of ${escape(c.country_name)}">
        ${INS_SECTIONS.map(([id, label]) => `<a href="#ins-${id}" data-ins="${id}">${label}</a>`).join("")}
      </nav>

      <section class="ins-group" id="ins-overview" aria-label="Overview">
      ${data.reliability ? `<div class="insight-reliability"><span class="rel-dot rel-${data.reliability.level}"></span>
        Data reliability for your priorities: <b>${data.reliability.level.toLowerCase()}</b>.
        ${data.reliability.measured} of ${data.reliability.factors} factors come from measured sources${data.reliability.weak.length ? "; " + escape(data.reliability.weak.map(w => w.text).join(", ")) : ""}.</div>` : ""}
      <div class="insight-actions">
        <button type="button" class="btn" id="insight-compare">${inCompare ? "In comparison" : "Add to compare"}</button>
        ${window.RELOC_PREVIEW ? "" : `<button type="button" class="btn btn-quiet" id="insight-save">${ico("bookmark")} Save to My relocation</button>`}
      </div>
      <div id="dims-body" class="dims"></div>
      ${c.hidden_by_filters ? `<div class="hidden-note">This country is hidden by your current filters. It's shown here for reference.</div>` : ""}
      ${data.is_home ? `<div class="hidden-note">This is your own country (based on the passport you selected).</div>` : ""}

      <div class="insight-section">
        <h4>Why it ranks here</h4>
        <p>${escape(data.explanation)}</p>
      </div>

      <div class="insight-section">
        <h4>Score breakdown</h4>
        ${breakdownHTML(c)}
      </div>

      <div class="insight-section">
        <h4>What would change it</h4>
        ${whatIfHTML(data)}
      </div>

      <div class="insight-section">
        <h4>Trade-offs</h4>
        <ul>${data.tradeoffs.map(t => `<li>${escape(t)}</li>`).join("")}</ul>
      </div>

      <div class="insight-section">
        <h4>Most similar countries <span class="filter-tag" title="Nearest neighbours across all 9 standardized factor scores">found by ML</span></h4>
        <div class="similar-grid">
          ${data.similar.length === 0
            ? `<p style="color:var(--text-muted); grid-column:1/-1;">No similar alternatives found.</p>`
            : data.similar.map(s => `
                <div class="similar-card" data-country="${escape(s.country_name)}" tabindex="0" role="button">
                  <div>
                    <div class="similar-name">${escape(s.country_name)}</div>
                    <div class="similar-region">${escape(s.region)}</div>
                  </div>
                  <div class="similar-score">${pct(s.score)}%</div>
                </div>
              `).join("")}
        </div>
      </div>
      </section>

      <section class="ins-group" id="ins-visas" aria-label="Visas and costs">
      ${demandHTML(data)}

      <div class="insight-section">
        <h4>Visa pathways ${filterTag}</h4>
        ${visas.length ? `<p class="visa-count"><b>${data.qualifying_count} of ${visas.length}</b> visas likely match your profile and filters.</p>` : ""}
        ${visas.length === 0
          ? `<p style="color:var(--text-muted)">${data.visas_researched === false
              ? "This country's visa routes haven't been researched yet. It stays in your results when visa filters are on, so check the official portal yourself."
              : "No visa pathways recorded for this country."}</p>`
          : `<p class="visa-caveat">Eligibility is checked against your passport, income and savings, plus age limits, family rules
               and job lists where we've researched them. Education, language tests and points systems aren't checked, so confirm on the official portal.</p>
             ${journeyHTML(visas, data)}
             <div class="visa-list">${visas.map(v => visaCardHTML(v, c.country_code)).join("")}</div>`}
        ${data.official_url ? `<a class="official-link" href="${escape(data.official_url)}" target="_blank" rel="noopener noreferrer">Official immigration portal ${ico("external")}</a>` : ""}
      </div>
      </section>

      <section class="ins-group" id="ins-pathways" aria-label="Pathways">
        <div class="insight-section"><h4>Routes to permanent residence</h4><div id="plan-body" class="lazy-body">Loading…</div></div>
      </section>

      <section class="ins-group" id="ins-money" aria-label="Money">
        <div class="insight-section"><h4>Money: take-home, savings and five-year outlook</h4>
          <form class="money-form" id="money-form">
            <label>Expected gross salary, USD/mo<input class="select" name="gross_monthly_usd" type="number" min="0" step="100" placeholder="leave empty for the typical net salary" value="${escape(state.money_gross || "")}"></label>
            <label>Other monthly spending, USD<input class="select" name="other_spend_usd" type="number" min="0" step="50" placeholder="food, transport, bills" value="${escape(state.money_other || "")}"></label>
            <label>Flights and moving, USD<input class="select" name="flights_usd" type="number" min="0" step="100" placeholder="one-off"></label>
            <button class="btn" type="submit">Calculate</button>
          </form>
          <div id="money-body" class="lazy-body"></div>
        </div>
      </section>

      <section class="ins-group" id="ins-career" aria-label="Career">
        <div class="insight-section"><h4>Career</h4><div id="career-body" class="lazy-body">Loading…</div></div>
      </section>

      <section class="ins-group" id="ins-living" aria-label="Living there">
      <div class="insight-section">
        <div class="figure-row">
          <div class="figure"><div class="figure-label">Avg net salary</div><div class="figure-value">${approx(c.country_code, "salary_money")}${money(c.salary_usd_month)}</div><div class="figure-sub">per month, editorial estimate</div></div>
          <div class="figure"><div class="figure-label">1-bed rent, city centre</div><div class="figure-value">${approx(c.country_code, "rent_money")}${money(c.rent_usd_month)}</div><div class="figure-sub">per month, editorial estimate</div></div>
          ${c.avg_temp_c != null ? `<div class="figure"><div class="figure-label">Climate · ${escape(c.main_city)}</div><div class="figure-value">${Number(c.avg_temp_c).toFixed(1)} °C</div><div class="figure-sub">average over the year</div></div>` : ""}
          ${c.gni_per_capita_usd != null ? `<div class="figure"><div class="figure-label">Income per person (GNI)</div><div class="figure-value">${money(c.gni_per_capita_usd / 12)}</div><div class="figure-sub">per month · World Bank</div></div>` : ""}
          <div class="figure"><div class="figure-label">Rent vs salary</div><div class="figure-value">${Math.round(rentShare * 100)}%</div><div class="figure-sub">of an average local salary</div></div>
        </div>
      </div>

      ${citiesHTML(data)}
      </section>

      <section class="ins-group" id="ins-ask" aria-label="Ask">
      <div class="insight-section">
        <h4>Ask about ${escape(c.country_name)} ${META.llm_enabled ? `<span class="filter-tag">AI</span>` : ""}</h4>
        <form class="ask-box" id="ask-form">
          <input class="select" id="ask-input" maxlength="500" placeholder="e.g. Can I bring my spouse?" autocomplete="off" />
          <button class="ask-btn" id="ask-btn" type="submit">Ask</button>
        </form>
        <div class="ask-suggestions">
          ${["Which visas can I get?", "Can I bring my spouse?", "Is there a route to PR?", "How expensive is rent?", "Is it safe?"]
            .map(q => `<button type="button" class="ask-suggestion" data-q="${escape(q)}">${escape(q)}</button>`).join("")}
        </div>
        ${META.llm_enabled && !window.RELOC_PREVIEW ? `<label class="toggle-row ask-consent"><input type="checkbox" id="ask-share"><span class="toggle"></span><span>Let the AI see my profile to phrase the answer (it never decides eligibility)</span></label>` : ""}
        <div class="ask-answer" id="ask-answer"></div>
      </div>
      </section>
    `;
    wireInsightNav();
    loadPlatformSections(c);

    insightsPanelEl.querySelectorAll(".similar-card").forEach(el => {
      el.addEventListener("click", () => fetchInsights(el.dataset.country));
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fetchInsights(el.dataset.country); } });
    });
    $("insight-compare").addEventListener("click", () => {
      toggleCompare(c.country_name, !state.compare.includes(c.country_name));
      $("insight-compare").textContent = state.compare.includes(c.country_name) ? "In comparison" : "Add to compare";
    });
    $("ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask(c.country_name, $("ask-input").value); });
    insightsPanelEl.querySelectorAll(".ask-suggestion[data-q]").forEach(el => {
      el.addEventListener("click", () => { $("ask-input").value = el.dataset.q; ask(c.country_name, el.dataset.q); });
    });
  }

  function pathHTML(v) {
    const p = v.path;
    if (!p) return "";
    const st = v.eligibility.status;
    const steps = p.steps.filter(s => s.kind !== "unknown");
    const unknown = p.steps.find(s => s.kind === "unknown");
    if (st === "eligible") return unknown ? `<div class="visa-path muted">${ico("info")} ${escape(unknown.text)}</div>` : "";
    if (!p.reachable) return `<div class="visa-path blocked">${ico("lock")} ${escape(steps[0].text)} This can't be fixed by effort.</div>`;
    if (!steps.length) return "";
    return `<div class="visa-path"><b>How to qualify:</b><ul>${steps.map(s => `<li>${escape(s.text)}</li>`).join("")}</ul>
      ${unknown ? `<span class="muted">${escape(unknown.text)}</span>` : ""}</div>`;
  }

  // How well this route's data is sourced (immigration/records.py → META.visa_status).
  const STATUS_WORDS = [["verified", "verified"], ["sourced", "from official pages, awaiting verification"],
                        ["outdated", "outdated"], ["third_party", "from a secondary source"],
                        ["estimated", "unsourced estimates"]];
  function dataStatusHTML(code, v) {
    const s = (META.visa_status || {})[`${code}|${v.name}`];
    if (!s) return "";
    const n = s.counts, total = Object.values(n).reduce((a, b) => a + b, 0);
    const parts = STATUS_WORDS.filter(([k]) => n[k]).map(([k, w]) => `<span class="ds ds-${k}">${n[k]} ${w}</span>`);
    const unknown = n.unknown || 0;
    return `<div class="data-status" title="Of ${total} things we track for every route (requirements, costs, timelines, rights). Only a person checking the official page can mark a value verified.">
        ${ico("info")}<span><b>Data:</b> ${parts.join(", ")}${unknown ? `${parts.length ? ", " : ""}<span class="ds ds-unknown">${unknown} of ${total} not known yet</span>` : ""}.</span>
      </div>`;
  }

  function visaCardHTML(v, code) {
    const est = ((META.visa_status || {})[`${code}|${v.name}`] || {}).estimated || [];
    const mark = (f) => est.includes(f) ? `<span class="est" title="Unsourced estimate: check the official page">≈</span>` : "";
    const incomeStr = v.min_income > 0
      ? `<span class="visa-meta">${ico("income")} Min income ${mark("min_income")}${money(v.min_income)}/mo</span>` : "";
    const investStr = v.min_investment > 0
      ? `<span class="visa-meta">${ico("savings")} Invest ${mark("investment") || "~"}${money(v.min_investment)}</span>` : "";
    const verified = v.last_verified
      ? `<span class="visa-meta">${ico("verified")} Verified ${escape(v.last_verified)}</span>` : "";
    const prClass = v.pr_route === "Yes" ? "pr-yes" : v.pr_route === "Eventually" ? "pr-soon" : "pr-no";
    const st = v.eligibility.status;
    const badgeText = { eligible: `${ico("tick")} Likely eligible`, conditional: `${ico("question")} Conditional`,
                        ineligible: `${ico("close")} Not eligible` }[st];
    const typeLabel = v.type === "free" ? "free movement" : v.type;
    return `
      <div class="visa-card elig-${st} ${v.qualifies ? "qualifies" : ""}">
        <div class="visa-head">
          <span class="visa-type type-${escape(v.type)}">${escape(typeLabel)}</span>
          <span class="visa-difficulty diff-${escape(v.difficulty)}">${escape(v.difficulty)}</span>
        </div>
        <span class="elig-badge ${st}">${badgeText}</span>
        <div class="visa-name">${escape(v.name)}</div>
        <div class="visa-summary">${escape(v.summary)}</div>
        ${v.eligibility.reasons.length ? `<ul class="elig-reasons">${v.eligibility.reasons.map(r => `<li>${escape(r)}</li>`).join("")}</ul>` : ""}
        ${pathHTML(v)}
        ${v.note ? `<div class="visa-note">${ico("alert")} ${escape(v.note)}</div>` : ""}
        ${timelineHTML(v)}
        <div class="visa-footer">
          <span class="visa-meta">${ico("clock")} ${escape(v.duration)}</span>
          <span class="visa-meta visa-pr ${prClass}">${ico("pr")} PR: ${escape(v.pr_route)}</span>
          ${incomeStr}${investStr}${verified}${familyMeta(v)}${v.age_max != null ? `<span class="visa-meta">${ico("info")} Age ${v.age_max} or under</span>` : ""}
          ${v.field_match ? `<span class="visa-meta demand">${ico("trend")} Your field is listed</span>` : ""}
        </div>
        ${dataStatusHTML(code, v)}
        ${v.sources && v.sources.length ? `<div class="visa-sources">Checked ${escape(v.checked)} on ${v.sources.map((u, k) => `<a href="${escape(u)}" target="_blank" rel="noopener noreferrer">${escape(hostOf(u))}${v.sources.length > 1 ? ` ${k + 1}` : ""}</a>`).join(", ")}</div>` : ""}
      </div>
    `;
  }


  // ---------- Platform sections: pathways, dimensions, money, career (need the server) ----------
  const DIM_LABEL = { lifestyle: "Lifestyle", immigration: "Immigration", financial: "Financial",
                      career: "Career", settlement: "Settlement", family: "Family" };
  let platformSeq = 0;
  async function loadPlatformSections(c) {
    const code = c.country_code;
    if (window.RELOC_PREVIEW) {
      for (const id of ["plan-body", "career-body", "money-body"]) $(id).innerHTML =
        `<p class="muted-note">Needs the full app (it runs on the server). Start it with <code>./run.sh</code>.</p>`;
      $("money-form").hidden = true;
      return;
    }
    const profile = currentProfile();
    const mine = ++platformSeq;
    const [plan, dims, car] = await Promise.all([
      postJSON("/api/plan", { profile, countries: [code] }).catch(e => ({ error: e.message })),
      postJSON("/api/dimensions", { profile, country: code, weights: currentWeights() }).catch(e => ({ error: e.message })),
      postJSON("/api/career", { profile, countries: [code] }).catch(e => ({ error: e.message })),
    ]);
    if (mine !== platformSeq || !$("plan-body")) return;   // the panel was re-rendered meanwhile; that render loads its own
    $("plan-body").innerHTML = plan.error ? `<p class="muted-note">${escape(plan.error)}</p>` : planHTML(plan);
    $("dims-body").innerHTML = dims.error ? "" : dimsHTML(dims);
    $("career-body").innerHTML = car.error ? `<p class="muted-note">${escape(car.error)}</p>` : careerHTML(car);
    insightsPanelEl.querySelectorAll(".save-pathway").forEach(b => b.addEventListener("click", () => saveToWorkspace("/api/me/pathways", { pathway: b.dataset.id }, "Pathway saved to My relocation")));
    const save = $("insight-save");
    if (save) save.onclick = () => saveToWorkspace("/api/me/shortlist", { country: code }, `${c.country_name} saved to My relocation`);
    $("money-form").onsubmit = (e) => { e.preventDefault(); runMoney(code); };
    runMoney(code);
  }

  async function saveToWorkspace(url, body, okText) {
    try {
      const me = await fetch("/api/me", { credentials: "same-origin" });
      if (me.status === 401) { toast("Sign in at My relocation (top bar) to save."); return; }
      const { csrf } = await me.json();
      const r = await fetch(url, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) });
      toast(r.ok ? okText : "Couldn't save that.");
    } catch { toast("Couldn't reach the server."); }
  }

  const yearsText = (y) => y.unknown.length ? `${y.min ? `at least ${yrs(y.min)} plus ` : ""}time we can't work out yet` : (y.min === 0 ? "directly" : `about ${yrs(y.min)}`);
  function planHTML(d) {
    if (!d.pathways.length) return `<p class="muted-note">No researched route to permanent residence for this country yet.</p>`;
    const st = { eligible: "Likely eligible", conditional: "Conditional", ineligible: "Not eligible yet" };
    return `<p class="plan-note">${escape(d.note)}</p>
      ${d.comparison ? `<p class="plan-why">${ico("bulb")}<span>${escape(d.comparison.text)}.</span></p>` : ""}
      <ol class="plan-list">${d.pathways.slice(0, 5).map(p => `
        <li class="plan-card">
          <div class="plan-head"><b>${escape(p.title)}</b><span class="elig-badge ${p.first_step}">${st[p.first_step]}</span></div>
          <ol class="plan-steps">${p.steps.map(s => `<li class="${s.pr ? "pr" : ""}"><span>${escape(s.label)}</span>
              ${s.years != null ? `<small>${s.years === 0 && !s.pr ? "" : escape(yrs(s.years))}</small>` : s.note ? `<small>${escape(s.note)}</small>` : ""}</li>`).join("")}</ol>
          <div class="plan-facts">
            <span>Permanent residence: <b>${escape(yearsText(p.years_to_pr))}</b></span>
            ${p.years_to_citizenship ? `<span>Citizenship from <b>${escape(yrs(p.years_to_citizenship))}</b>${p.citizenship && p.citizenship.status === "third_party" ? " (secondary source)" : ""}</span>` : ""}
            <span>Known fees <b>${money(p.cost_usd.known)}</b>${p.cost_usd.unknown_fees ? ` + ${p.cost_usd.unknown_fees} not researched` : ""}</span>
            <span>Uncertainty <b>${escape(p.risk.level)}</b></span>
          </div>
          ${p.unchecked.length ? `<p class="plan-warn">${ico("alert")} Not checked: ${escape(p.unchecked.join(", ").toLowerCase())}.</p>` : ""}
          ${p.open_conditions.length ? `<ul class="plan-cond">${p.open_conditions.map(x => `<li>${escape(x)}</li>`).join("")}</ul>` : ""}
          ${p.limits.length ? `<p class="plan-limit">${escape(p.limits.join(" "))}</p>` : ""}
          <button type="button" class="btn btn-quiet save-pathway" data-id="${escape(p.id)}">${ico("bookmark")} Save pathway</button>
        </li>`).join("")}</ol>`;
  }

  function dimsHTML(d) {
    const rows = Object.entries(d.dimensions).map(([k, v]) => {
      const pctv = v.score == null ? null : Math.round(v.score * 100);
      return `<div class="dim-row" title="${escape(v.basis)}">
          <span class="dim-label">${DIM_LABEL[k]}</span>
          <div class="bd-track"><div class="bd-fill dim-fill" style="width:${pctv ?? 0}%"></div></div>
          <span class="dim-val">${pctv == null ? "n/a" : pctv}</span></div>`;
    }).join("");
    return `<div class="insight-section"><h4>Six separate views <span class="filter-tag" title="${escape(d.note)}">not combined</span></h4>${rows}
      <p class="muted-note">${escape(d.note)} Hover a row for what it is based on.</p></div>`;
  }

  function careerHTML(d) {
    const c = d.countries[0];
    const sl = c.shortage_list;
    const u = c.indicators.unemployment;
    const gap = d.skills_gap.roadmap;
    return `<div class="career-facts">
        ${sl ? `<p>${sl.field_listed == null ? `Set your job field under About you to check the <b>${escape(sl.name)}</b>.` : sl.field_listed ? `<b>${escape(c.field)}</b> is on the <b>${escape(sl.name)}</b>.` : `${escape(c.field)} isn't on the ${escape(sl.name)}.`}
          <a href="${escape(sl.source)}" target="_blank" rel="noopener noreferrer">Official list ${ico("external")}</a></p>` : `<p class="muted-note">No official shortage list researched for this country.</p>`}
        ${u ? `<p>Unemployment <b>${u.pct.toFixed(1)}%</b> (${u.year}, World Bank). Job-market indicator <b>${c.indicators.job_market_score.toFixed(2)}</b>.</p>` : ""}
      </div>
      ${c.work_routes.length ? `<h5>Work routes for you</h5><ul class="career-routes">${c.work_routes.map(r => `<li><b>${escape(r.name)}</b>: ${escape(r.status)}${r.reasons.length ? ` (${escape(r.reasons[0])})` : ""}</li>`).join("")}</ul>` : ""}
      ${gap.length ? `<h5>What would open more routes</h5><ol class="career-gap">${gap.map(g => `<li><b>${escape(g.action)}</b> opens ${escape(g.opens.map(o => o.route).join(", "))}</li>`).join("")}</ol>
        <p class="muted-note">${escape(d.skills_gap.note)}</p>` : ""}
      <p class="muted-note">Not available: ${escape(c.not_available.join("; "))}. Live vacancies appear only when a job API is configured.</p>`;
  }

  async function runMoney(code) {
    const f = $("money-form");
    if (!f) return;
    const body = { country: code };
    for (const el of f.querySelectorAll("input")) if (el.value !== "") body[el.name] = Number(el.value);
    state.money_gross = body.gross_monthly_usd || "";
    state.money_other = body.other_spend_usd || "";
    try {
      const d = await postJSON("/api/finance/simulate", body);
      $("money-body").innerHTML = moneyHTML(d);
    } catch (e) { $("money-body").innerHTML = `<p class="muted-note">${escape(e.message)}</p>`; }
  }

  const STATUS_TAG = { sourced: "sourced", editorial: "estimate", input: "yours", assumption: "assumption", unknown: "unknown", not_applied: "already net" };
  function moneyHTML(d) {
    const m = d.monthly;
    const line = (l) => `<tr><td>${escape(l.label)}${l.pct != null ? ` (${l.pct}%)` : ""}<span class="mtag mtag-${l.status}" title="${escape(l.note || "")}">${STATUS_TAG[l.status] || l.status}</span></td>
      <td class="num">${l.usd == null ? "–" : money(l.usd)}</td></tr>`;
    const base = d.projections.baseline.years;
    return `<table class="money-table"><tbody>${m.lines.map(line).join("")}
        <tr class="total"><td>Left each month</td><td class="num">${money(m.savings_usd)}</td></tr></tbody></table>
      <table class="money-table"><tbody>${d.one_off.lines.map(line).join("")}</tbody></table>
      ${projectionSVG(d.projections)}
      <p class="muted-note">Savings after ${base.map(y => `${y.year} yr: ${money(y.cumulative_savings_usd)}`).join(", ")} (baseline). ${escape(d.note)}
        ${d.unknown.length ? ` Left out: ${escape(d.unknown.join(", "))}.` : ""}</p>`;
  }

  // Cumulative savings in three scenarios: drawn straight from the simulator's yearly numbers.
  function projectionSVG(p) {
    const names = ["pessimistic", "baseline", "optimistic"];
    const pts = names.flatMap(n => p[n].years.map(y => y.cumulative_savings_usd));
    const lo = Math.min(0, ...pts), hi = Math.max(0, ...pts), W = 420, H = 150, P = 30;
    const x = (yr) => P + (yr - 1) / 9 * (W - 2 * P), y = (v) => H - P / 2 - (v - lo) / ((hi - lo) || 1) * (H - P);
    const dash = { pessimistic: "4 4", baseline: "", optimistic: "1 3" };
    const lines = names.map(n => `<polyline class="proj-${n}" fill="none" stroke-dasharray="${dash[n]}" points="${p[n].years.map(v => `${x(v.year).toFixed(1)},${y(v.cumulative_savings_usd).toFixed(1)}`).join(" ")}"><title>${n}</title></polyline>`).join("");
    const labels = p.baseline.years.map(v => `<text x="${x(v.year)}" y="${H - 2}" text-anchor="middle">${v.year}y</text>`).join("");
    return `<figure class="proj"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative savings over 10 years in three scenarios">
        <line class="proj-zero" x1="${P}" x2="${W - P}" y1="${y(0)}" y2="${y(0)}"/>${lines}${labels}</svg>
      <figcaption>Cumulative savings: <span class="key k-pes">pessimistic</span> <span class="key k-base">baseline</span> <span class="key k-opt">optimistic</span>. Projections, not forecasts.</figcaption></figure>`;
  }

  // ---------- Costs, timelines, job lists, cities ----------
  const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return "source"; } };
  const yrs = (y) => y === 0 ? "on arrival" : `${Number.isInteger(y) ? y : y.toFixed(y < 2 ? 2 : 1).replace(/0$/, "")} year${y === 1 ? "" : "s"}`;

  function familyMeta(v) {
    const f = v.family;
    if (!f || v.type === "family" || v.type === "free") return "";
    const who = f.partner && f.children ? "Partner and children can come" : f.partner ? "Partner can come" : f.children ? "Children can come" : "Family can't come";
    return `<span class="visa-meta">${ico("family")} ${who}</span>`;
  }

  function timelineHTML(v) {
    const t = v.timeline;
    if (!t) return "";
    const end = Math.max(1, ...t.steps.map(s => s.at), (t.citizenship_years || 0));
    const dots = t.steps.filter(s => s.label !== "Visa decision" || s.at / end > 0.05).map(s => `<span class="tl-dot ${s.label === "Citizenship" ? "cit" : s.label.startsWith("Permanent") ? "pr" : ""}"
        style="left:${(s.at / end) * 100}%" title="${escape(s.label)}: ${s.at ? escape(yrs(s.at)) : "start"}"></span>`).join("");
    const facts = [
      t.fee ? `<span><b>${escape(t.fee)}</b> government fee</span>` : "",
      t.processing ? `<span>${escape(t.processing)}</span>` : "",
      t.pr_years != null ? `<span>Permanent residence <b>${escape(yrs(t.pr_years))}</b></span>` : "",
      t.citizenship_years != null ? `<span>Citizenship from <b>${escape(yrs(t.citizenship_years))}</b></span>` : "",
    ].filter(Boolean).join("");
    return `<div class="visa-timeline">
        <div class="tl-facts">${facts}</div>
        ${t.pr_years != null || t.citizenship_years != null ? `<div class="tl-track" aria-hidden="true"><span class="tl-line"></span>${dots}</div>` : ""}
        ${t.fee_note || t.pr_note ? `<div class="tl-note">${escape([t.fee_note, t.pr_note].filter(Boolean).join(". "))}</div>` : ""}
      </div>`;
  }

  // The fastest researched road to a passport, across the visas you can use (or all of them).
  function journeyHTML(visas, data) {
    const timed = visas.filter(v => v.timeline && v.timeline.citizenship_years != null);
    const cit = data.citizenship;
    if (!timed.length && !cit) return "";
    const pool = timed.filter(v => v.qualifies).length ? timed.filter(v => v.qualifies) : timed;
    const best = pool.sort((a, b) => a.timeline.citizenship_years - b.timeline.citizenship_years)[0];
    const rule = cit ? `Citizenship normally needs <b>${cit.years} years</b> of residence${cit.after_pr ? `, ${cit.after_pr} of them as a permanent resident` : ""}${cit.note ? ` (${escape(cit.note)})` : ""}.
      <span class="src-kind" title="Summary of national nationality laws, not an official government page">secondary source: <a href="${escape(cit.source)}" target="_blank" rel="noopener noreferrer">Wikipedia</a></span>` : "";
    return `<div class="journey-card">
        ${best ? `<div class="journey-head">${ico("clock")}<span>Fastest researched road to a passport: <b>${escape(best.name)}</b>, citizenship from about ${escape(yrs(best.timeline.citizenship_years))}${best.qualifies ? "" : " (you don't qualify yet)"}.</span></div>` : ""}
        ${rule ? `<div class="journey-rule">${rule}</div>` : ""}
      </div>`;
  }

  function demandHTML(data) {
    const d = data.in_demand;
    const field = state.occupation ? (META.occupations.find(o => o.key === state.occupation) || {}).label : null;
    if (!d) return "";
    const listed = d.fields.map(k => (META.occupations.find(o => o.key === k) || {}).label || k);
    const verdict = data.field_in_demand === true ? `<b>${escape(field)} is on it.</b> Expect easier invitations and visa routes.`
      : data.field_in_demand === false ? `${escape(field)} isn't on it.` : `Set your job field under "About you" to check yours.`;
    return `<div class="insight-section demand-section ${data.field_in_demand ? "yes" : ""}">
        <h4>${ico("trend")} Jobs in demand</h4>
        <p>${escape(d.list)} covers ${escape(listed.join(", "))}. ${verdict}
          <a href="${escape(d.source)}" target="_blank" rel="noopener noreferrer">Official list ${ico("external")}</a></p>
      </div>`;
  }

  function citiesHTML(data) {
    const cities = data.cities || [];
    if (!cities.length) return "";
    const nat = data.country;
    const focus = (state.focusCity || "").toLowerCase();
    const anyPrice = cities.some(c => c.price_index != null);
    return `<div class="insight-section">
        <h4>Cities</h4>
        <div class="city-grid">${cities.map(c => {
          const diffT = nat.avg_temp_c != null ? c.temp_c - nat.avg_temp_c : null;
          const price = c.price_index != null ? `${c.price_index >= 100 ? "+" : ""}${(c.price_index - 100).toFixed(1)}% prices` : "";
          return `<div class="city-card ${c.name.toLowerCase() === focus ? "focus" : ""}">
              <div class="city-name">${escape(c.name)}${c.name === nat.main_city ? ` <span class="filter-tag">in scores</span>` : ""}</div>
              <div class="city-temp">${c.temp_c.toFixed(1)} °C${diffT != null && c.name !== nat.main_city ? ` <small>${diffT >= 0 ? "+" : ""}${diffT.toFixed(1)}</small>` : ""}</div>
              ${price ? `<div class="city-price">${escape(price)} <small>vs national average</small></div>` : ""}
            </div>`; }).join("")}</div>
        <p class="city-note">Average temperature over the year; scores use ${escape(nat.main_city)}.${anyPrice ? " Price levels: US Bureau of Economic Analysis, 2024." : ""} Other city costs aren't researched yet.</p>
      </div>`;
  }

  function clearInsights() {
    state.selectedCountry = null;
    syncURL();
    insightsPanelEl.innerHTML = "";
    markSelectedCard();
    closeDrawer();
  }

  // ---------- Country details drawer ----------
  const drawerEl = $("drawer");
  let drawerOpener = null;
  function openDrawer(focus = true) {
    if (!drawerEl.classList.contains("open")) { drawerOpener = document.activeElement; drawerEl.scrollTop = 0; }
    drawerEl.classList.add("open");
    drawerEl.setAttribute("aria-hidden", "false");
    drawerEl.setAttribute("aria-labelledby", "drawer-title");
    if (focus) drawerEl.focus({ preventScroll: true });
  }
  function closeDrawer() {
    if (!drawerEl.classList.contains("open")) return;
    drawerEl.classList.remove("open");
    drawerEl.setAttribute("aria-hidden", "true");
    if (drawerOpener && document.contains(drawerOpener)) drawerOpener.focus({ preventScroll: true });
    drawerOpener = null;
  }
  $("drawer-close").addEventListener("click", clearInsights);
  drawerEl.addEventListener("scroll", () => requestAnimationFrame(spyIns), { passive: true });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawerEl.classList.contains("open")) clearInsights(); });
  $("methods-link").addEventListener("click", (e) => {
    e.preventDefault();
    setView("explore");
    $("data-sources").open = true;
    $("data-sources").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  });

  // ---------- Q&A ----------
  async function ask(country, question) {
    question = (question || "").trim();
    if (!question) return;
    const out = $("ask-answer"), btn = $("ask-btn");
    btn.disabled = true;
    out.textContent = "Thinking…";
    try {
      const code = (state.allCountries.find(c => c.country_name === country) || {}).country_code
        || (META.nationalities.find(n => n.name === country) || {}).code;
      if (!window.RELOC_PREVIEW && code) {
        const share = $("ask-share") ? $("ask-share").checked : false;
        const d = await postJSON("/api/assistant", { question, country: code, profile: currentProfile(), share_profile_with_ai: share });
        const src = d.mode === "llm" ? "Phrased by Claude from RelocAitor's engines" : "Answered by built-in rules";
        out.innerHTML = `${escape(d.answer)}
          ${d.warnings.length ? `<ul class="ask-warn">${d.warnings.map(w => `<li>${ico("alert")} ${escape(w)}</li>`).join("")}</ul>` : ""}
          <span class="ask-source">${src} · agents: ${escape(d.agents.join(", "))}${d.sources.length ? ` · <a href="${escape(d.sources[0])}" target="_blank" rel="noopener noreferrer">source</a>` : ""}</span>`;
        return;
      }
      const data = await postJSON("/api/ask", { ...basePayload(), country, question });
      const src = data.source === "llm" ? "Answered by Claude using RelocAitor's data" : "Answered by built-in rules";
      out.innerHTML = `${escape(data.answer)}<span class="ask-source">${src}${data.warning ? " · " + escape(data.warning) : ""}</span>`;
    } catch (err) {
      out.innerHTML = `<span style="color:#fca5a5">${escape(err.message)}</span>`;
    } finally {
      btn.disabled = false;
    }
  }

  // ---------- Preference learning quiz ----------
  const prefPanel = $("pref-panel");
  let prefAnswers = [], prefLast = null;

  $("quiz-start").addEventListener("click", () => {
    prefAnswers = [];
    prefPanel.classList.remove("hidden");
    prefPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    prefStep();
  });
  $("pref-close").addEventListener("click", () => prefPanel.classList.add("hidden"));

  async function prefStep(finishNow = false) {
    try {
      const d = await postJSON("/api/preferences", { answers: prefAnswers });
      if (finishNow) d.done = true;
      prefLast = d;
      renderPref(d);
    } catch (err) {
      $("pref-body").innerHTML = `<div class="error-banner">${escape(err.message)}</div>`;
    }
  }

  function prefCard(c, side) {
    const top = prefLast.question.differences.map(x => x.factor);
    const keys = [...new Set([...top, ...FACTOR_KEYS])].slice(0, 4);
    return `
      <div class="pref-card">
        <div class="pref-name">${escape(c.name)}</div>
        <div class="pref-meta">${escape(c.region)}${c.avg_temp_c != null ? ` · ${escape(c.main_city)} ${Number(c.avg_temp_c).toFixed(0)} °C` : ""}</div>
        <div class="pref-meta pref-money">${ico("income")} ~${money(c.salary_usd_month)}/mo <span>${ico("home")} ~${money(c.rent_usd_month)}/mo</span></div>
        <div class="pref-bars">${keys.map(k => `
          <div class="pref-bar-row"><span>${fico(k)} ${escape(META.factors[k].label)}</span>
            <div class="bd-track"><div class="bd-fill seg-${k}" style="width:${(c.values[k] * 100).toFixed(0)}%"></div></div></div>`).join("")}
        </div>
        <button type="button" class="pref-choose" data-choice="${side}">Choose ${escape(c.name)}</button>
      </div>`;
  }

  function renderPref(d) {
    $("pref-progress").textContent = d.done ? "Done" : `Question ${d.number} of ${d.total}`;
    document.querySelector(".pref-learned h3").textContent = d.answered === 0
      ? "Starting point: every factor equally important" : "What the model has learned so far";
    $("pref-weights").innerHTML = FACTOR_KEYS
      .map(k => [k, d.weights[k]]).sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `<div class="pref-w-row"><span>${fico(k)} ${escape(META.factors[k].label)}</span>
        <div class="bd-track"><div class="bd-fill seg-${k}" style="width:${(v * 100).toFixed(0)}%"></div></div>
        <span class="pref-w-val">${v.toFixed(2)}</span></div>`).join("");

    if (d.done) {
      const cons = d.consistency != null ? `These weights reproduce ${Math.round(d.consistency * 100)}% of your choices.` : "";
      $("pref-body").innerHTML = `
        <div class="pref-done">
          <p><b>${escape(d.user_insight)}</b> ${cons}</p>
          <div class="pref-actions">
            <button type="button" class="prompt-btn" id="pref-apply">Apply these priorities</button>
            <button type="button" class="ask-suggestion" id="pref-restart">Start over</button>
          </div>
        </div>`;
      $("pref-apply").addEventListener("click", () => {
        Object.assign(state, d.weights, { preset: null });
        applyStateToControls();
        fetchScore();
        toast("Priorities learned from your choices are applied");
        $("pref-apply").innerHTML = `${ico("tick")} Applied`;
      });
      $("pref-restart").addEventListener("click", () => { prefAnswers = []; prefStep(); });
      return;
    }
    const q = d.question;
    $("pref-body").innerHTML = `
      <div class="pref-pair">
        ${prefCard(q.a, "a")}
        <div class="pref-vs">
          <span>vs</span>
          ${q.differences.length ? `<ul>${q.differences.map(x => `<li>${escape(x.text)}</li>`).join("")}</ul>` : ""}
        </div>
        ${prefCard(q.b, "b")}
      </div>
      <div class="pref-actions">
        <button type="button" class="ask-suggestion" data-choice="skip">Can't decide</button>
        ${d.answered >= 3 ? `<button type="button" class="ask-suggestion" id="pref-finish">Finish now</button>` : ""}
      </div>`;
    $("pref-body").querySelectorAll("[data-choice]").forEach(btn => btn.addEventListener("click", () => {
      prefAnswers.push({ a: q.a.name, b: q.b.name, choice: btn.dataset.choice });
      prefStep();
    }));
    const fin = $("pref-finish");
    if (fin) fin.addEventListener("click", () => prefStep(true));
  }

  // ---------- ML country landscape ----------
  const CLUSTER_COLORS = ["#86efac", "#22d3ee", "#fbbf24", "#f472b6", "#a78bfa", "#fb923c", "#60a5fa", "#e879f9"];

  function renderLandscape() {
    const svg = $("landscape");
    const cmap = META.country_map;
    if (!svg || !cmap || !cmap.countries) return;
    const W = 760, H = 430, PAD = 34;
    const pts = Object.entries(cmap.countries);
    const xs = pts.map(([, p]) => p.x), ys = pts.map(([, p]) => p.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const sx = (x) => PAD + (x - x0) / (x1 - x0 || 1) * (W - 2 * PAD);
    const sy = (y) => H - PAD - (y - y0) / (y1 - y0 || 1) * (H - 2 * PAD);
    const byCode = Object.fromEntries(state.allCountries.map(c => [c.country_code, c]));
    const names = Object.fromEntries(META.nationalities.map(n => [n.code, n.name]));
    const selected = state.allCountries.find(c => c.country_name === state.selectedCountry)
      || (state.selectedCountry && { country_code: (META.nationalities.find(n => n.name === state.selectedCountry) || {}).code });
    const selCode = selected && selected.country_code;
    const neighbours = selCode && cmap.countries[selCode] ? cmap.countries[selCode].neighbors.slice(0, 3) : [];
    const topCodes = new Set(state.topCountries.map(c => c.country_code));

    let html = `<line class="ls-axis" x1="${PAD}" y1="${H - PAD}" x2="${W - PAD}" y2="${H - PAD}"/>
      <line class="ls-axis" x1="${PAD}" y1="${PAD}" x2="${PAD}" y2="${H - PAD}"/>
      <text class="ls-axis-label" x="${W - PAD}" y="${H - 10}" text-anchor="end">${escape(cmap.axes[0].label)}</text>
      <text class="ls-axis-label" x="12" y="${PAD - 12}">↑ ${escape(cmap.axes[1].label.replace(" →", ""))}</text>`;
    if (selCode && cmap.countries[selCode]) {
      const s = cmap.countries[selCode];
      html += neighbours.map(nb => { const p = cmap.countries[nb];
        return `<line class="ls-link" x1="${sx(s.x)}" y1="${sy(s.y)}" x2="${sx(p.x)}" y2="${sy(p.y)}"/>`; }).join("");
    }
    const ordered = pts.slice().sort((a, b) => ((byCode[a[0]] || {}).score || 0) - ((byCode[b[0]] || {}).score || 0));
    for (const [code, p] of ordered) {
      const c = byCode[code];
      const r = c ? 3.5 + 7 * c.score : 3;
      const cls = ["ls-dot", c ? "" : "ls-dim", code === selCode ? "ls-selected" : "", neighbours.includes(code) ? "ls-nb" : ""].join(" ");
      const label = code === selCode || neighbours.includes(code) || topCodes.has(code);
      const cl = cmap.clusters[p.cluster];
      html += `<g class="ls-point" data-name="${escape(names[code] || code)}" tabindex="0">
        <circle class="${cls}" cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${r.toFixed(1)}" fill="${CLUSTER_COLORS[p.cluster % 8]}">
          <title>${escape(names[code] || code)} · ${escape(cl.name)}${c ? ` · ${pct(c.score)}% match` : " · hidden by your filters"}</title>
        </circle>
        ${label ? (() => { const left = sx(p.x) > W - 130;   // flip labels near the right edge
            return `<text class="ls-label ${code === selCode ? "ls-label-sel" : ""}" text-anchor="${left ? "end" : "start"}" x="${(sx(p.x) + (left ? -(r + 3) : r + 3)).toFixed(1)}" y="${(sy(p.y) + 3).toFixed(1)}">${escape(names[code] || code)}</text>`; })() : ""}
      </g>`;
    }
    svg.innerHTML = html;
    svg.querySelectorAll(".ls-point").forEach(g => {
      g.addEventListener("click", () => fetchInsights(g.dataset.name));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter") fetchInsights(g.dataset.name); });
    });
    $("landscape-legend").innerHTML = cmap.clusters.map(cl =>
      `<span class="ls-legend-item"><span class="ls-swatch" style="background:${CLUSTER_COLORS[cl.id % 8]}"></span>${escape(cl.name)} <em>(${cl.size})</em></span>`
    ).join("");
  }

  // ---------- Compare ----------
  function toggleCompare(name, on) {
    const i = state.compare.indexOf(name);
    if (on && i === -1) {
      if (state.compare.length >= MAX_COMPARE) {
        toast(`You can compare up to ${MAX_COMPARE} countries.`);
        document.querySelectorAll(".compare-toggle").forEach(el => {
          el.querySelector("input").checked = state.compare.includes(el.dataset.country);
        });
        return;
      }
      state.compare.push(name);
    } else if (!on && i !== -1) {
      state.compare.splice(i, 1);
    }
    renderTray();
    syncURL();
    document.querySelectorAll(".compare-toggle").forEach(el => {
      el.querySelector("input").checked = state.compare.includes(el.dataset.country);
    });
    if (state.view === "compare" || !compareSection.classList.contains("hidden")) renderCompareView();
  }

  // The Compare tab: the table once two or more are picked, otherwise a short "how to" with a shortcut.
  function renderCompareView() {
    const n = state.compare.length;
    $("compare-empty").hidden = n >= 2;
    if (n >= 2) { runCompare({ scroll: false }); return; }
    compareSection.classList.add("hidden");
    $("compare-empty").querySelector("h3").textContent = n === 1 ? `Pick one more country to compare with ${state.compare[0]}` : "Nothing to compare yet";
  }
  $("compare-top3").addEventListener("click", () => {
    state.compare = state.topCountries.slice(0, MAX_COMPARE).map(c => c.country_name);
    renderTray();
    syncURL();
    document.querySelectorAll(".compare-toggle").forEach(el => {
      el.querySelector("input").checked = state.compare.includes(el.dataset.country);
    });
    renderCompareView();
  });

  function renderTray() {
    compareTray.classList.toggle("hidden", state.compare.length === 0 || state.view === "compare");
    $("compare-chips").innerHTML = state.compare.map(n => `<span class="tray-chip">${escape(n)}</span>`).join("");
    $("compare-go").disabled = state.compare.length < 2;
    $("compare-go").textContent = state.compare.length < 2 ? "Pick 2+" : `Compare ${state.compare.length}`;
    const badge = $("compare-count");
    badge.hidden = state.compare.length === 0;
    badge.textContent = state.compare.length;
    badge.setAttribute("aria-label", `${state.compare.length} selected`);
    if (typeof placeTabThumb === "function" && tabs.length) placeTabThumb();
  }

  function clearCompare() {
    state.compare = [];
    renderTray();
    compareSection.classList.add("hidden");
    $("compare-empty").hidden = false;
    $("compare-empty").querySelector("h3").textContent = "Nothing to compare yet";
    document.querySelectorAll(".compare-toggle input").forEach(el => { el.checked = false; });
    syncURL();
  }

  $("compare-go").addEventListener("click", () => runCompare());
  $("compare-clear").addEventListener("click", clearCompare);

  async function runCompare({ scroll = true } = {}) {
    if (state.compare.length < 2) return;
    try {
      const data = await postJSON("/api/compare", { ...basePayload(), countries: state.compare });
      renderCompare(data);
      compareSection.classList.remove("hidden");
      $("compare-empty").hidden = true;
      if (scroll) setView("compare", { scroll: true, refresh: false });
    } catch (err) {
      toast(err.message);
    }
  }

  function renderCompare(data) {
    const items = data.items;
    // [label, getter, "high" | "low" | null (no highlight), formatter]
    const rows = [
      ["Your rank", c => c.rank, "low", v => v == null ? "hidden" : `#${v}`],
      ["Match score", c => c.score, "high", v => `${pct(v)}%`],
      ["Avg net salary", c => c.salary_usd_month, "high", money, "salary_money"],
      ["1-bed rent", c => c.rent_usd_month, "low", money, "rent_money"],
      ...FACTOR_KEYS.map(k => [{ k, text: META.factors[k].label }, c => factorValue(c, k), "high", v => v.toFixed(2), k]),
      ["Visas for you", c => (c.visas_researched === false ? null : c.qualifying_visas), "high", v => (v == null ? "not researched" : String(v))],
      ["PR routes for you", c => c.pr_routes.length ? c.pr_routes.join(", ") : "None", null, v => v],
      ["Easiest visa", c => c.easiest_visa || "–", null, v => v],
    ];
    const body = rows.map(([label, get, better, fmt, estKey]) => {
      const vals = items.map(get);
      let best = null;
      if (better) {
        const nums = vals.filter(v => typeof v === "number");
        if (nums.length > 1 && new Set(nums).size > 1) best = better === "high" ? Math.max(...nums) : Math.min(...nums);
      }
      const head = typeof label === "object" ? `${fico(label.k)} ${escape(label.text)}` : escape(label);
      return `<tr><td>${head}</td>${vals.map((v, k) => {
        const isBest = best !== null && v === best;
        return `<td class="${better ? "num" : "small"} ${isBest ? "best" : ""}">${estKey ? approx(items[k].country_code, estKey) : ""}${escape(fmt(v))}${isBest ? `<span class="sr-only"> (best)</span>` : ""}</td>`;
      }).join("")}</tr>`;
    }).join("");

    comparePanelEl.innerHTML = `
      <div class="table-wrap" style="max-height:none; margin-top:0">
        <table class="compare-table">
          <thead><tr><th></th>${items.map(c => `<th>${escape(c.country_name)}<div class="similar-region">${escape(c.region)}</div></th>`).join("")}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>`;
  }

  // ---------- Full table ----------
  function renderFullTable(all) {
    tableBody.innerHTML = all.map(c => `
      <tr data-country="${escape(c.country_name)}">
        <td class="num">${c.rank}</td>
        <td>${escape(c.country_name)}</td>
        <td>${escape(c.region)}</td>
        <td class="num">${c.score.toFixed(2)}</td>
        <td><span class="card-badge ${c.score_category}">${c.score_category}</span></td>
        <td class="num">${approx(c.country_code, "salary_money")}${money(c.salary_usd_month)}</td>
        <td class="num">${approx(c.country_code, "rent_money")}${money(c.rent_usd_month)}</td>
        ${[["salary", "average_salary"], ["cost", "cost_of_living"], ["pr", "pr_ease"], ["job", "job_market"],
           ["climate", "climate"], ["safety", "safety"], ["healthcare", "healthcare"], ["english", "english"], ["internet", "internet"]]
          .map(([k, col]) => `<td class="num">${approx(c.country_code, k)}${c[col].toFixed(2)}</td>`).join("")}
        <td class="num">${c.visas_researched === false ? `<span title="Not researched yet">–</span>` : c.qualifying_visas}</td>
      </tr>
    `).join("");
  }
  tableBody.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-country]");
    if (tr) fetchInsights(tr.dataset.country);
  });

  // ---------- Prompt search ----------
  const promptForm = $("prompt-form"), promptInput = $("prompt-input");
  const promptBtn = $("prompt-btn"), promptOut = $("prompt-result");
  let undoSnapshot = null;

  const SNAP_KEYS = [...FACTOR_KEYS, "top_n", "region", "visa_type", "max_difficulty", "require_pr",
                     "only_qualifying", "nationality", "monthly_income", "investment_budget", "exclude_home",
                     "exclude", "preset"];
  const snapshot = () => JSON.parse(JSON.stringify(Object.fromEntries(SNAP_KEYS.map(k => [k, state[k]]))));

  promptForm.addEventListener("submit", (e) => { e.preventDefault(); runPrompt(promptInput.value); });
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
    if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      promptInput.focus({ preventScroll: true });
      $("search").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    }
  });
  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runPrompt(promptInput.value); }
  });
  document.querySelectorAll(".prompt-example").forEach(el => el.addEventListener("click", () => {
    promptInput.value = el.dataset.prompt;
    runPrompt(el.dataset.prompt);
  }));

  // ---------- Conversation: one chat window; after a first search, messages refine it ----------
  const chatEl = $("chat"), threadEl = $("thread"), followupsEl = $("followups"), examplesEl = $("prompt-examples");
  const firstTurn = $("first-turn"), statusEl = $("chat-status");
  // Short hints on phones, so the one-line composer never clips them.
  const narrow = window.matchMedia("(max-width: 560px)").matches;
  const PLACEHOLDER = narrow ? "Describe your ideal move" : promptInput.placeholder;
  const REFINE_PLACEHOLDER = narrow ? "Refine: cheaper, drop Japan…" : "Refine it: cheaper, what about Asia?, drop Japan, why Portugal?, undo…";
  promptInput.placeholder = PLACEHOLDER;
  let conversation = false;
  const undoStack = [];        // snapshots before each change, for "undo"

  function setConversation(on) {
    conversation = on;
    chatEl.classList.toggle("active", on);
    followupsEl.classList.toggle("hidden", !on);
    promptInput.placeholder = on ? REFINE_PLACEHOLDER : PLACEHOLDER;
    promptBtn.setAttribute("aria-label", on ? "Send" : "Find countries");
  }
  function setStarted(on) {
    chatEl.classList.toggle("started", on);
    firstTurn.classList.toggle("hidden", !on);
  }

  function endConversation() {
    undoStack.length = 0;
    threadEl.querySelectorAll(".turn:not(.first-turn), .typing").forEach(el => el.remove());
    promptOut.classList.add("hidden");
    setStarted(false);
    setConversation(false);
    statusEl.textContent = "";
  }

  function scrollThread() {
    requestAnimationFrame(() => threadEl.scrollTo({ top: threadEl.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" }));
  }

  let typingEl = null;
  function thinking(on) {
    if (on && !typingEl) {
      typingEl = document.createElement("div");
      typingEl.className = "bubble from-app typing";
      typingEl.setAttribute("aria-label", "Working on it");
      typingEl.innerHTML = "<span></span><span></span><span></span>";
      threadEl.appendChild(typingEl);
      scrollThread();
    } else if (!on && typingEl) {
      typingEl.remove();
      typingEl = null;
    }
    statusEl.textContent = on ? "Thinking…" : "";
    chatEl.classList.toggle("busy", on);
  }

  function addTurn(userText, reply, changes = [], kind = "", hits = []) {
    const turn = document.createElement("div");
    turn.className = "turn";
    turn.innerHTML = `
      <div class="bubble from-you">${escape(userText)}</div>
      <div class="bubble from-app ${kind}">
        ${changes.length ? `<div class="turn-chips">${changes.map(c => `<span class="u-chip kind-${escape(c.kind)}">${chipIcon(c)}${escape(c.label)}</span>`).join("")}</div>` : ""}
        ${reply ? `<p>${escape(reply)}</p>` : ""}
        ${hits.length ? `<div class="hit-grid turn-hits">${hits.slice(0, 4).map(h => `
          <button type="button" class="hit-card" data-country="${escape(h.country)}" title="${escape(h.summary)}">
            <div class="hit-name">${escape(h.name)}</div>
            <div class="hit-meta">${escape(h.country)} · ${escape(h.type)} · ${escape(h.difficulty)}</div>
          </button>`).join("")}</div>` : ""}
      </div>`;
    turn.querySelectorAll(".hit-card").forEach(el => el.addEventListener("click", () => fetchInsights(el.dataset.country)));
    threadEl.appendChild(turn);
    scrollThread();
  }

  function applyRefinedState(st) {
    const p = st.profile;
    FACTOR_KEYS.forEach(k => { state[k] = st.weights[k]; });
    Object.assign(state, {
      region: st.region, top_n: st.top_n, preset: null,
      nationality: p.nationality || "",
      monthly_income: p.monthly_income == null ? "" : String(p.monthly_income),
      investment_budget: p.investment_budget == null ? "" : String(p.investment_budget),
      occupation: p.occupation || "", age: p.age == null ? "" : String(p.age),
      partner: Boolean(p.partner), children: p.children == null ? "" : String(p.children),
      visa_type: p.visa_type || "any", require_pr: Boolean(p.require_pr),
      max_difficulty: p.max_difficulty || "", only_qualifying: Boolean(p.only_qualifying),
      exclude_home: p.exclude_home !== false, exclude: p.exclude_countries || [],
    });
  }

  async function undoLast() {
    const prev = undoStack.pop();
    if (!prev) return false;
    Object.assign(state, prev);
    applyStateToControls();
    await fetchScore();
    return true;
  }

  async function refinePrompt(text) {
    const data = await postJSON("/api/refine", {
      prompt: text,
      state: { weights: currentWeights(), region: state.region, profile: currentProfile(), top_n: state.top_n },
    });
    thinking(false);
    const kinds = data.actions.map(a => a.type);
    if (kinds.includes("reset")) {
      $("reset-btn").click();
      endConversation();
      toast("Started over");
      return;
    }
    if (kinds.includes("undo")) {
      const ok = await undoLast();
      addTurn(text, ok ? data.reply : "There's nothing to undo yet.");
      return;
    }
    if (data.changes.length) {
      undoStack.push(snapshot());
      applyRefinedState(data.state);
      applyStateToControls();
      await fetchScore();
    }
    const hits = data.visa_hits || [];
    const reply = data.changes.length ? (data.outcome || "Done.")
      : (!data.actions.length && hits.length ? "Here are the matching visas." : data.reply);
    addTurn(text, reply, data.changes, data.changes.length || data.actions.length || hits.length ? "" : "unclear", hits);
    for (const a of data.actions) {
      if (a.type === "open") fetchInsights(a.country);
      if (a.type === "compare") {
        state.compare = a.countries.slice(0, MAX_COMPARE);
        renderTray();
        document.querySelectorAll(".compare-toggle").forEach(el => {
          el.querySelector("input").checked = state.compare.includes(el.dataset.country);
        });
        runCompare();
      }
    }
  }

  async function runPrompt(text) {
    text = (text || "").trim();
    if (!text) { promptInput.focus(); return; }
    if (chatEl.classList.contains("busy")) return;
    promptBtn.disabled = true;
    promptInput.value = "";
    autoGrow();
    try {
      if (conversation) {
        thinking(true);
        await refinePrompt(text);
      } else {
        $("first-ask").textContent = text;
        promptOut.classList.add("hidden");
        threadEl.querySelectorAll(".turn:not(.first-turn)").forEach(el => el.remove());
        setStarted(true);
        thinking(true);
        const data = await postJSON("/api/search", { prompt: text });
        const before = snapshot();
        const changed = await applyInterpretation(data.interpretation);
        undoSnapshot = changed ? before : null;
        undoStack.length = 0;
        if (changed) undoStack.push(before);
        thinking(false);
        renderPromptResult(data, changed);
        if (data.interpretation.understood || changed) setConversation(true);
      }
    } catch (err) {
      thinking(false);
      if (conversation) addTurn(text, `Something went wrong: ${err.message}`, [], "unclear");
      else {
        promptOut.classList.remove("hidden");
        promptOut.innerHTML = `<div class="error-banner">${escape(err.message)}</div>`;
      }
    } finally {
      thinking(false);
      promptBtn.disabled = false;
      scrollThread();
    }
  }

  // The composer grows with what you type (up to a limit), like Messages.
  function autoGrow() {
    promptInput.style.height = "auto";
    promptInput.style.height = `${Math.min(promptInput.scrollHeight, 180)}px`;
    promptInput.closest(".prompt-box")?.classList.toggle("multiline", promptInput.scrollHeight > 48);
  }
  promptInput.addEventListener("input", autoGrow);

  // Dictation where the browser supports it (Chrome, Edge, Safari).
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = $("mic-btn");
  if (Speech && micBtn && !window.RELOC_PREVIEW) {
    micBtn.hidden = false;
    let rec = null;
    micBtn.addEventListener("click", () => {
      if (rec) { rec.stop(); return; }
      rec = new Speech();
      rec.lang = navigator.language || "en-US";
      rec.interimResults = true;
      const base = promptInput.value ? promptInput.value.trimEnd() + " " : "";
      rec.onresult = (e) => {
        promptInput.value = base + [...e.results].map(r => r[0].transcript).join("");
        autoGrow();
      };
      rec.onend = () => { rec = null; micBtn.classList.remove("listening"); micBtn.setAttribute("aria-pressed", "false"); promptInput.focus(); };
      rec.onerror = (e) => { if (e.error !== "aborted") toast("Dictation isn't available right now."); };
      micBtn.classList.add("listening");
      micBtn.setAttribute("aria-pressed", "true");
      rec.start();
    });
  }

  followupsEl.querySelectorAll("[data-followup]").forEach(el => el.addEventListener("click", () => runPrompt(el.dataset.followup)));
  $("new-search").addEventListener("click", () => {
    endConversation();
    promptInput.value = "";
    autoGrow();
    promptInput.focus();
  });

  // Turn the interpretation into app state. Returns true if settings changed.
  async function applyInterpretation(i) {
    const p = i.profile || {};
    const changesSettings = Boolean(i.weights || Object.keys(p).length || i.region ||
                                    (i.exclude || []).length || i.top_n);
    if (changesSettings) {
      if (i.weights) FACTOR_KEYS.forEach(k => { state[k] = i.weights[k]; });
      // A new prompt starts from clean filters; "about you" fields are kept unless the prompt sets them.
      Object.assign(state, {
        visa_type: p.visa_type || "any",
        require_pr: Boolean(p.require_pr),
        max_difficulty: p.max_difficulty || "",
        only_qualifying: Boolean(p.only_qualifying),
        region: i.region || "All regions",
        exclude: i.exclude || [],
        preset: null,
      });
      if (p.nationality) state.nationality = p.nationality;
      if (p.monthly_income != null) state.monthly_income = String(p.monthly_income);
      if (p.investment_budget != null) state.investment_budget = String(p.investment_budget);
      if (p.occupation) state.occupation = p.occupation;
      if (p.age != null) state.age = String(p.age);
      if (p.partner != null) state.partner = Boolean(p.partner);
      if (p.children != null) state.children = String(p.children);
      if (i.top_n) state.top_n = i.top_n;
      applyStateToControls();
      await fetchScore();
    }
    const countries = i.countries || [];
    state.focusCity = countries.length === 1 ? (i.city || null) : null;
    if (countries.length === 1) {
      fetchInsights(countries[0]);
    } else if (countries.length >= 2) {
      state.compare = countries.slice(0, MAX_COMPARE);
      renderTray();
      document.querySelectorAll(".compare-toggle").forEach(el => {
        el.querySelector("input").checked = state.compare.includes(el.dataset.country);
      });
      runCompare();
    }
    return changesSettings;
  }

  function renderPromptResult(data, changed) {
    const i = data.interpretation;
    const hits = data.visa_hits || [];
    const similar = data.similar || [];
    promptOut.classList.remove("hidden");

    if (!i.understood && !hits.length) {
      promptOut.innerHTML = `<p class="prompt-note">I couldn't match that to anything yet. Try describing
        what matters to you (safety, cost, climate, jobs, English…), your passport, your income, a region,
        a visa type (nomad, study, golden visa…) or a country.</p>`;
      return;
    }
    const extras = [i.chips.some(c => c.kind === "learned") && "trained model",
                    (i.chips.some(c => c.kind === "semantic") || hits.some(h => h.match !== "keyword")) && "sentence embeddings"]
      .filter(Boolean);
    const src = i.source === "llm" ? "Understood by Claude"
      : extras.length ? `Built-in rules + ${extras.join(" + ")}` : "Built-in understanding";
    const summary = i.summary || (changed ? "Here's what I understood:" : "Here's what I found:");
    promptOut.innerHTML = `
      <div class="prompt-summary"><p>${escape(summary)}</p><span class="prompt-src">${src}</span></div>
      <div class="understood-chips">
        ${i.chips.map(c => `<span class="u-chip kind-${escape(c.kind)}" title="${escape(c.detail || "")}">${chipIcon(c)}${escape(c.label)}</span>`).join("")}
      </div>
      ${i.warning ? `<p class="prompt-note">${ico("alert")} ${escape(i.warning)}</p>` : ""}
      ${i.fuzzy && i.fuzzy.length ? `<p class="prompt-note">Read as: ${i.fuzzy.map(escape).join(" · ")}</p>` : ""}
      ${i.unmatched && i.unmatched.length ? `<p class="prompt-note">Not used: <b>${i.unmatched.map(escape).join(", ")}</b></p>` : ""}
      ${changed ? `<p class="prompt-note">Your priorities and filters were updated to match. Keep talking to refine them, or fine-tune them yourself.</p>` : ""}
      ${similar.length ? `
        <div class="prompt-sub"><h5>Countries similar to ${escape(i.similar_to)}</h5>
          <div class="hit-grid">${similar.map(n => `
            <button type="button" class="hit-card" data-country="${escape(n)}">
              <div class="hit-name">${escape(n)}</div><div class="hit-meta">See details</div>
            </button>`).join("")}</div></div>` : ""}
      ${hits.length ? `
        <div class="prompt-sub"><h5>Matching visas</h5>
          <div class="hit-grid">${hits.map(h => `
            <button type="button" class="hit-card" data-country="${escape(h.country)}" title="${escape(h.summary)}">
              <div class="hit-name">${escape(h.name)}</div>
              <div class="hit-meta">${escape(h.country)} · ${escape(h.type)} · ${escape(h.difficulty)}</div>
              ${h.match && h.match !== "keyword" ? `<div class="hit-match match-${escape(h.match)}"
                title="Found by meaning (sentence-embedding similarity ${h.similarity != null ? Number(h.similarity).toFixed(2) : ""})">
                ${h.match === "both" ? `${ico("keyword")}${ico("semantic")} keyword + meaning` : `${ico("semantic")} meaning match`}</div>` : ""}
            </button>`).join("")}</div></div>` : ""}
      ${undoSnapshot ? `<div class="prompt-actions"><button type="button" id="prompt-undo">${ico("undo")} Undo these changes</button></div>` : ""}
    `;
    promptOut.querySelectorAll(".hit-card").forEach(el =>
      el.addEventListener("click", () => fetchInsights(el.dataset.country)));
    const undo = $("prompt-undo");
    if (undo) undo.addEventListener("click", () => {
      Object.assign(state, undoSnapshot);
      undoSnapshot = null;
      endConversation();
      applyStateToControls();
      fetchScore();
      toast("Restored your previous settings");
    });
  }

  // ---------- Saved searches (this device only) ----------
  // Each saved search keeps its settings and the top countries at the time. Opening it re-runs the
  // ranking on today's data and says what moved, so a rule or data change shows up as a difference.
  const SAVED_KEY = "relocaitor.saved.v1";
  const SAVED_FIELDS = [...FACTOR_KEYS, "top_n", "region", "visa_type", "max_difficulty", "require_pr", "only_qualifying",
                        "nationality", "monthly_income", "investment_budget", "occupation", "age", "partner", "children",
                        "education", "experience_years", "english_level", "german_level",
                        "exclude_home", "exclude", "preset"];
  let savedMemory = [];
  const savedNotes = new Map();
  function loadSaved() {
    try { const raw = localStorage.getItem(SAVED_KEY); if (raw) return JSON.parse(raw); } catch { /* storage blocked */ }
    return savedMemory;
  }
  function storeSaved(list) {
    savedMemory = list;
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(list)); } catch { /* kept for this visit only */ }
  }
  function savedName() {
    const parts = [];
    if (state.region !== "All regions") parts.push(state.region);
    const job = META.occupations.find(o => o.key === state.occupation);
    if (job) parts.push(job.label);
    const nat = META.nationalities.find(n => n.code === state.nationality);
    if (nat) parts.push(`${nat.name} passport`);
    if (state.visa_type !== "any") parts.push((META.visa_types.find(v => v.key === state.visa_type) || {}).label || state.visa_type);
    const top = FACTOR_KEYS.filter(k => state[k] >= 0.8).map(k => META.factors[k].label.toLowerCase());
    if (parts.length < 2 && top.length) parts.push(top.slice(0, 2).join(" & "));
    return parts.join(" · ") || (state.topCountries[0] ? `Led by ${state.topCountries[0].country_name}` : "My search");
  }
  const shortDate = (iso) => { try { return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }); } catch { return ""; } };

  function renderSaved() {
    const list = loadSaved();
    $("saved-list").innerHTML = list.length ? list.map(e => `
      <li class="saved-item" data-id="${escape(e.id)}">
        <button type="button" class="saved-open" data-id="${escape(e.id)}">
          <span class="saved-name">${escape(e.name)}</span>
          <span class="saved-meta">Saved ${escape(shortDate(e.saved_at))} · ${escape(e.top.slice(0, 3).join(", ") || "no matches")}</span>
          ${savedNotes.has(e.id) ? `<span class="saved-diff">${escape(savedNotes.get(e.id))}</span>` : ""}
        </button>
        <button type="button" class="icon-btn saved-del" data-id="${escape(e.id)}" aria-label="Delete ${escape(e.name)}">${ico("close")}</button>
      </li>`).join("") : `<li class="saved-empty">Nothing saved yet. Save this search to come back to it later and see what changed.</li>`;
    const n = list.length, badge = $("saved-count");
    badge.hidden = n === 0;
    badge.textContent = n;
  }

  function diffSince(entry, nowTop) {
    const before = entry.top, after = nowTop;
    const updated = entry.data_version && entry.data_version !== META.data_version
      ? ` The data was updated since then (${entry.data_version} → ${META.data_version}).` : "";
    return changesSince(entry, before, after) + updated;
  }
  function changesSince(entry, before, after) {
    if (!before.length && !after.length) return "Still no matches.";
    if (before.join("|") === after.join("|")) return `Same top ${after.length} as on ${shortDate(entry.saved_at)}.`;
    const parts = [];
    if (after[0] && after[0] !== before[0]) parts.push(`${after[0]} is now #1 (was ${before[0] || "none"})`);
    const added = after.filter(c => !before.includes(c)), gone = before.filter(c => !after.includes(c));
    if (added.length) parts.push(`new: ${added.join(", ")}`);
    if (gone.length) parts.push(`dropped: ${gone.join(", ")}`);
    if (!parts.length) parts.push("same countries, new order");
    return `Since ${shortDate(entry.saved_at)}: ${parts.join("; ")}.`;
  }

  async function openSaved(id) {
    const entry = loadSaved().find(e => e.id === id);
    if (!entry) return;
    undoStack.push(Object.fromEntries(SAVED_FIELDS.map(k => [k, Array.isArray(state[k]) ? [...state[k]] : state[k]])));
    Object.assign(state, DEFAULTS, JSON.parse(JSON.stringify(entry.settings)));
    applyStateToControls();
    await fetchScore();
    const note = diffSince(entry, state.topCountries.map(c => c.country_name).slice(0, entry.top.length || state.top_n));
    savedNotes.set(id, note);
    renderSaved();
    toast(note);
  }

  $("save-search").addEventListener("click", () => {
    const list = loadSaved();
    const entry = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      name: savedName(), saved_at: new Date().toISOString(), data_version: META.data_version,
      settings: Object.fromEntries(SAVED_FIELDS.map(k => [k, Array.isArray(state[k]) ? [...state[k]] : state[k]])),
      top: state.topCountries.map(c => c.country_name),
    };
    storeSaved([entry, ...list].slice(0, 12));
    renderSaved();
    toast(`Saved “${entry.name}”`);
  });
  $("saved-list").addEventListener("click", (e) => {
    const del = e.target.closest(".saved-del");
    if (del) { storeSaved(loadSaved().filter(x => x.id !== del.dataset.id)); savedNotes.delete(del.dataset.id); renderSaved(); return; }
    const open = e.target.closest(".saved-open");
    if (open) openSaved(open.dataset.id);
  });


  // ---------- Views: Matches · Map · Compare · Explore (one set of results, four ways to see it) ----------
  const tabs = [...document.querySelectorAll("#view-tabs [role=tab]")];
  const tabThumb = document.querySelector("#view-tabs .seg-thumb");
  function placeTabThumb() {
    const t = tabs.find(x => x.dataset.view === state.view);
    if (!t || !tabThumb || !t.offsetWidth) return;
    tabThumb.style.width = `${t.offsetWidth}px`;
    tabThumb.style.transform = `translateX(${t.offsetLeft - 4}px)`;
    tabThumb.style.opacity = "1";
  }
  function setView(name, { scroll = false, focus = false, refresh = true } = {}) {
    if (!VIEWS.includes(name)) return;
    state.view = name;
    for (const t of tabs) {
      const on = t.dataset.view === name;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    }
    for (const v of VIEWS) $(`view-${v}`).hidden = v !== name;
    placeTabThumb();
    renderTray();
    if (name === "compare" && refresh) renderCompareView();
    if (name === "map") window.MapView.shown();
    syncURL();
    document.dispatchEvent(new CustomEvent("viewchange", { detail: name }));
    if (scroll) $("views").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }
  window.RelocViews = { setView, current: () => state.view };
  // If the tab bar is stuck to the top, keep it there so the new view starts right under it.
  tabs.forEach(t => t.addEventListener("click", () => setView(t.dataset.view, { scroll: $("views").getBoundingClientRect().top < 0 })));
  $("view-tabs").addEventListener("keydown", (e) => {
    const i = tabs.findIndex(t => t.dataset.view === state.view);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    setView(tabs[(next + tabs.length) % tabs.length].dataset.view, { focus: true });
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-goto-view]");
    if (b) setView(b.dataset.gotoView, { scroll: true });
  });
  window.addEventListener("resize", placeTabThumb);

  // ---------- One-line summaries on the collapsed sidebar groups ----------
  const cap = (t) => t ? t[0].toUpperCase() + t.slice(1) : t;
  function renderSummaries() {
    const nat = META.nationalities.find(n => n.code === state.nationality);
    const job = META.occupations.find(o => o.key === state.occupation);
    const kids = Number(state.children) || 0;
    const who = [];
    if (nat) who.push(`${nat.demonym || nat.name} passport`);
    if (job) who.push(job.label.toLowerCase());
    if (validAge(state.age)) who.push(`age ${validAge(state.age)}`);
    if (state.partner || kids) who.push(`with ${[state.partner ? "partner" : "", kids ? `${kids} child${kids === 1 ? "" : "ren"}` : ""].filter(Boolean).join(" and ")}`);
    const eduLabel = ((META.labels || {}).education || {})[state.education];
    if (eduLabel) who.push(eduLabel);
    if (state.experience_years !== "") who.push(`${state.experience_years} yrs experience`);
    if (state.english_level) who.push(`English ${state.english_level}`);
    if (state.german_level) who.push(`German ${state.german_level}`);
    if (state.monthly_income !== "") who.push(`${money(state.monthly_income)} a month`);
    if (state.investment_budget !== "") who.push(`${money(state.investment_budget)} to invest`);
    $("profile-summary").textContent = who.length ? cap(who.join(", ")) : "Add your passport to check visas";

    const preset = state.preset && META.presets[state.preset];
    const ws = FACTOR_KEYS.map(k => [k, Number(state[k])]);
    const flat = ws.every(([, v]) => Math.abs(v - ws[0][1]) < 1e-9);
    const top = ws.filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k]) => META.factors[k].label.toLowerCase());
    $("priorities-summary").textContent = preset ? `${preset.label} profile`
      : flat ? "Every factor counts the same" : `Most weight on ${top.join(" and ")}`;

    const on = [];
    if (state.region !== "All regions") on.push(state.region);
    if (state.visa_type !== "any") on.push(((META.visa_types.find(v => v.key === state.visa_type) || {}).label || state.visa_type).toLowerCase());
    if (state.max_difficulty) on.push(state.max_difficulty === "Easy" ? "easy visas only" : "up to moderate visas");
    if (state.require_pr) on.push("leads to residency");
    if (state.only_qualifying) on.push("visas I qualify for");
    if (state.exclude.length) on.push(`${state.exclude.length} excluded`);
    $("filters-summary").textContent = on.length ? `${on.length} on: ${on.join(", ")}` : "None on: every country is shown";
    renderCurrencyNotes();
  }

  // ---------- Currency picker ----------
  (function fillCurrencies() {
    const sel = $("currency");
    const codes = Object.keys(CUR.rates).sort((a, b) => currencyName(a).localeCompare(currencyName(b)));
    sel.insertAdjacentHTML("beforeend", codes.map(c => `<option value="${c}">${escape(currencyName(c))} (${c})</option>`).join(""));
  })();
  function renderCurrencyNotes() {
    const cur = currencyCode(), r = CUR.rates[cur];
    const auto = $("currency").options[0];
    const home = state.nationality && CUR.countries[state.nationality];
    auto.textContent = home && CUR.rates[home] ? `Your passport's currency (${home})` : "Your passport's currency (else US dollars)";
    $("currency-note").textContent = cur === "USD" ? "Rankings always use US dollars."
      : r.basis === "daily" ? `ECB reference rate of ${CUR.daily_date}. Rankings still use US dollars.`
      : `World Bank average rate for ${r.year}, so amounts are approximate. Rankings still use US dollars.`;
    for (const id of ["monthly_income", "investment_budget"]) {
      const v = state[id];
      $(`${id}-local`).textContent = cur !== "USD" && v !== "" ? `≈ ${money(v)}` : "";
    }
  }

  // ---------- Saved searches live behind the bookmark in the top bar ----------
  const savedBtn = $("saved-btn"), savedPop = $("saved-pop");
  function setSavedOpen(open) {
    savedPop.hidden = !open;
    savedBtn.setAttribute("aria-expanded", String(open));
    if (open) $("save-search").focus({ preventScroll: true });
  }
  savedBtn.addEventListener("click", (e) => { e.stopPropagation(); setSavedOpen(savedPop.hidden); });
  document.addEventListener("click", (e) => {
    if (!savedPop.hidden && !e.composedPath().includes(savedPop.parentElement)) setSavedOpen(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !savedPop.hidden) { setSavedOpen(false); savedBtn.focus(); e.stopImmediatePropagation(); }
  }, true);

  // ---------- First visit: three short tips, then never again ----------
  const COACH_KEY = "relocaitor.onboarded";
  const coachEl = $("coach");
  const shown = (el) => el && el.offsetParent !== null && el.getBoundingClientRect().width > 0;
  const COACH = [
    { target: () => document.querySelector("#search .prompt-box"), title: "Say what you want",
      text: "Describe yourself and the move in your own words. Then keep going to refine it: cheaper, warmer, not Spain." },
    { target: () => shown($("group-priorities")) ? $("group-priorities") : $("prefs-fab"), title: "Tune what matters",
      text: "Drag the sliders, or open About you so visas are checked against your passport, age and family." },
    { target: () => $("view-tabs"), title: "See it four ways",
      text: "Matches is the ranking. Map, Compare and Explore show the same results differently. Select any country for its visas and costs." },
  ];
  let coachStep = -1;
  const onboarded = () => { try { return localStorage.getItem(COACH_KEY) === "1"; } catch { return true; } };
  function endCoach() {
    coachEl.hidden = true;
    document.querySelectorAll(".coach-target").forEach(el => el.classList.remove("coach-target"));
    coachStep = -1;
    try { localStorage.setItem(COACH_KEY, "1"); } catch { /* shown again next visit */ }
  }
  function placeCoach() {
    const step = COACH[coachStep];
    const t = step && step.target();
    if (!t || !shown(t)) return;
    const r = t.getBoundingClientRect(), w = coachEl.offsetWidth, h = coachEl.offsetHeight;
    const below = r.bottom + h + 16 < innerHeight;
    const top = below ? r.bottom + 12 : Math.max(12, r.top - h - 12);
    const left = Math.min(innerWidth - w - 12, Math.max(12, r.left + Math.min(24, r.width / 4)));
    coachEl.style.top = `${top}px`;
    coachEl.style.left = `${left}px`;
    coachEl.dataset.side = below ? "below" : "above";
  }
  function showCoach(i) {
    document.querySelectorAll(".coach-target").forEach(el => el.classList.remove("coach-target"));
    coachStep = i;
    const step = COACH[i], t = step.target();
    if (!t) { endCoach(); return; }
    $("coach-step").textContent = `Tip ${i + 1} of ${COACH.length}`;
    $("coach-title").textContent = step.title;
    $("coach-text").textContent = step.text;
    $("coach-next").textContent = i === COACH.length - 1 ? "Got it" : "Next";
    t.classList.add("coach-target");
    coachEl.hidden = false;
    t.scrollIntoView({ behavior: "auto", block: "nearest" });
    placeCoach();
  }
  $("coach-next").addEventListener("click", () => coachStep + 1 < COACH.length ? showCoach(coachStep + 1) : endCoach());
  $("coach-skip").addEventListener("click", endCoach);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !coachEl.hidden) endCoach(); });
  window.addEventListener("resize", () => { if (!coachEl.hidden) placeCoach(); });
  document.addEventListener("scroll", () => { if (!coachEl.hidden) placeCoach(); }, { passive: true, capture: true });

  const saveProfileBtn = $("save-profile");
  if (saveProfileBtn) saveProfileBtn.addEventListener("click", async () => {
    try {
      const me = await fetch("/api/me", { credentials: "same-origin" });
      if (me.status === 401) { toast("Sign in at My relocation (top bar) first."); return; }
      const { csrf } = await me.json();
      const r = await fetch("/api/me/profile", { method: "PUT", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ profile: currentProfile() }) });
      toast(r.ok ? "Profile saved to your account (encrypted)." : "Couldn't save your profile.");
    } catch { toast("Couldn't reach the server."); }
  });

  // ---------- Light / dark theme ----------
  const themeBtn = $("theme-btn");
  function syncThemeBtn() {
    const light = document.documentElement.dataset.theme === "light";
    themeBtn.setAttribute("aria-pressed", String(light));
    themeBtn.setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme");
  }
  themeBtn.addEventListener("click", () => {
    const light = document.documentElement.dataset.theme !== "light";
    if (light) document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("relocaitor.theme", light ? "light" : "dark"); } catch { /* not remembered */ }
    syncThemeBtn();
  });
  syncThemeBtn();
  if (window.RELOC_PREVIEW) document.querySelectorAll(".server-only").forEach(el => el.remove());

  // ---------- Boot ----------
  async function boot() {
    readURL();
    applyStateToControls();
    renderTray();
    renderSaved();
    setView(state.view, { refresh: false });

    // Load the map and the scores in parallel so cards appear even if the map CDN is slow.
    const mapReady = window.MapView.init({
      onSelect: (country) => fetchInsights(country.country_name),
    });
    await fetchScore();
    await mapReady;
    window.MapView.update(state.allCountries);
    window.MapView.focusRegion(state.region === "All regions" ? null : state.allCountries.map(c => c.country_code));
    // fetchScore() already loaded the selected country's insights; lock it now the map exists.
    const selected = state.allCountries.find(c => c.country_name === state.selectedCountry);
    if (selected) window.MapView.lockCountry(selected.country_code);
    if (state.view === "compare") renderCompareView();
    else if (state.compare.length >= 2) runCompare({ scroll: false });
    if (!onboarded()) setTimeout(() => showCoach(0), 400);
  }

  boot();
})();
