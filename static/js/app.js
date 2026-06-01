/* =============================================================
   app.js — Main controller.
   Manages: 9 sliders, region filter, visa-type filter, reset,
   API calls, country grid, insights, visa pathways, full table.
   ============================================================= */

(function() {

  const DEFAULTS = {
    salary: 0.7, cost: 0.5, pr: 0.6, job: 0.7,
    climate: 0.3, safety: 0.5, healthcare: 0.4,
    english: 0.5, internet: 0.3,
    top_n: 5,
    region: "All regions",
    visa_type: "any",
  };

  const FACTOR_KEYS = ["salary", "cost", "pr", "job",
                       "climate", "safety", "healthcare", "english", "internet"];

  const state = { ...DEFAULTS, topCountries: [], allCountries: [], selectedCountry: null };

  // ---------- Elements ----------
  const sliderIds = [...FACTOR_KEYS, "top_n"];
  const sliders = Object.fromEntries(sliderIds.map(id => [id, document.getElementById(id)]));
  const valueDisplays = Object.fromEntries(
    sliderIds.map(id => [id, document.querySelector(`[data-value-for="${id}"]`)])
  );
  const regionSelect    = document.getElementById("region");
  const visaSelect      = document.getElementById("visa_type");
  const resetBtn        = document.getElementById("reset-btn");
  const userInsightEl   = document.getElementById("user-insight");
  const topGridEl       = document.getElementById("top-grid");
  const insightsPanelEl = document.getElementById("insights-panel");
  const tableBody       = document.querySelector("#full-ranking-table tbody");

  let scoreTimer = null;
  const DEBOUNCE_MS = 180;

  // ---------- Slider painting ----------
  function paintSlider(id) {
    const el = sliders[id];
    const min = parseFloat(el.min), max = parseFloat(el.max);
    const pct = ((parseFloat(el.value) - min) / (max - min)) * 100;
    el.style.background = `linear-gradient(90deg, var(--accent-2) ${pct}%, rgba(255,255,255,0.08) ${pct}%)`;
  }

  // ---------- Wire sliders ----------
  for (const id of sliderIds) {
    const el = sliders[id];
    paintSlider(id);
    el.addEventListener("input", (e) => {
      const raw = parseFloat(e.target.value);
      state[id] = raw;
      valueDisplays[id].textContent = id === "top_n" ? String(raw) : raw.toFixed(2);
      paintSlider(id);
      scheduleScore();
    });
  }

  regionSelect.addEventListener("change", (e) => { state.region = e.target.value; scheduleScore(); });
  visaSelect.addEventListener("change",   (e) => { state.visa_type = e.target.value; renderTopCountries(state.topCountries); });

  resetBtn.addEventListener("click", () => {
    Object.assign(state, DEFAULTS);
    for (const id of sliderIds) {
      sliders[id].value = DEFAULTS[id];
      valueDisplays[id].textContent = id === "top_n" ? String(DEFAULTS[id]) : DEFAULTS[id].toFixed(2);
      paintSlider(id);
    }
    regionSelect.value = DEFAULTS.region;
    visaSelect.value = DEFAULTS.visa_type;
    fetchScore();
  });

  function scheduleScore() {
    clearTimeout(scoreTimer);
    scoreTimer = setTimeout(fetchScore, DEBOUNCE_MS);
  }

  // ---------- API calls ----------
  function currentWeights() {
    return Object.fromEntries(FACTOR_KEYS.map(k => [k, state[k]]));
  }

  async function fetchScore() {
    try {
      const res = await fetch("/api/score", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          weights: currentWeights(),
          region:  state.region,
          top_n:   state.top_n,
        }),
      });
      const data = await res.json();
      state.topCountries = data.top;
      state.allCountries = data.all;

      userInsightEl.textContent = data.user_insight;
      window.MapView.update(data.all);
      renderTopCountries(data.top);
      renderFullTable(data.all);

      if (state.selectedCountry) {
        const stillExists = data.all.find(c => c.country_name === state.selectedCountry);
        if (stillExists) fetchInsights(state.selectedCountry);
        else clearInsights();
      }
    } catch (err) {
      console.error("Score fetch failed:", err);
    }
  }

  async function fetchInsights(countryName) {
    try {
      const res = await fetch("/api/insights", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          country: countryName,
          weights: currentWeights(),
          region:  state.region,
        }),
      });
      if (!res.ok) { clearInsights(); return; }
      const data = await res.json();
      renderInsights(data);
      state.selectedCountry = countryName;

      const iso3 = data.country.country_code;
      if (iso3) window.MapView.lockCountry(iso3);

      document.querySelectorAll(".country-card").forEach(el =>
        el.classList.toggle("selected", el.dataset.country === countryName)
      );

      // Scroll insights into view
      insightsPanelEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      console.error("Insights fetch failed:", err);
    }
  }

  // ---------- Renderers ----------
  function renderTopCountries(list) {
    // Optional: highlight which top countries match the visa-type filter
    const visaType = state.visa_type;
    topGridEl.innerHTML = list.map((c, i) => cardHTML(c, i + 1, visaType)).join("");
    topGridEl.querySelectorAll(".country-card").forEach(el => {
      el.addEventListener("click", () => fetchInsights(el.dataset.country));
    });
  }

  function cardHTML(c, rank, visaType) {
    const pct = Math.round(c.score * 100);
    const visaTag = visaType !== "any"
      ? `<span class="visa-filter-pill">filtering: ${escape(visaType)}</span>` : "";
    return `
      <div class="country-card" data-country="${escape(c.country_name)}"
           style="animation-delay:${rank * 0.05}s">
        <div class="card-top">
          <div>
            <div class="card-rank">#${rank}</div>
            <div class="card-name">${escape(c.country_name)}</div>
            <div class="card-region">${escape(c.region)}</div>
            <span class="card-badge ${c.score_category}">${c.score_category}</span>
          </div>
          <div class="card-score">${pct}%</div>
        </div>
        <div class="card-bar"><div class="card-bar-fill" style="width:${pct}%"></div></div>
        <div class="card-metrics">
          ${metric("Salary", c.average_salary)}
          ${metric("Cost",   c.cost_of_living)}
          ${metric("PR",     c.pr_ease)}
          ${metric("Jobs",   c.job_market)}
        </div>
        ${visaTag}
      </div>
    `;
  }

  function metric(label, v) {
    return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${v.toFixed(2)}</div></div>`;
  }

  function renderInsights(data) {
    const c = data.country;
    const pct = Math.round(c.score * 100);

    const visaType = state.visa_type;
    const visas = (data.visas || []).filter(v => visaType === "any" ? true : v.type === visaType);

    insightsPanelEl.innerHTML = `
      <div class="insight-country">
        ${escape(c.country_name)}
        <span class="card-badge ${c.score_category}" style="margin-left:10px; font-size:0.62rem; vertical-align:middle;">${c.score_category}</span>
        <span class="card-score" style="float:right; font-size:1.4rem;">${pct}%</span>
      </div>
      <div class="insight-region">${escape(c.region)}</div>

      <div class="insight-section">
        <h4>✨ Why this country?</h4>
        <p>${escape(data.explanation)}</p>
      </div>

      <div class="insight-section">
        <h4>⚖️ Trade-offs</h4>
        <ul>${data.tradeoffs.map(t => `<li>${escape(t)}</li>`).join("")}</ul>
      </div>

      <div class="insight-section">
        <h4>🛂 Visa pathways ${visaType !== "any" ? `<span class="filter-tag">filter: ${escape(visaType)}</span>` : ""}</h4>
        ${visas.length === 0
          ? `<p style="color:var(--text-muted)">No ${visaType !== "any" ? escape(visaType) + " " : ""}visa pathways recorded for this country${visaType !== "any" ? " — try changing the visa-type filter" : ""}.</p>`
          : `<div class="visa-list">${visas.map(visaCardHTML).join("")}</div>`
        }
      </div>

      <div class="insight-section">
        <h4>🔄 Similar alternatives</h4>
        <div class="similar-grid">
          ${data.similar.length === 0
            ? `<p style="color:var(--text-muted); grid-column:1/-1;">No similar alternatives in this region.</p>`
            : data.similar.map(s => `
                <div class="similar-card" data-country="${escape(s.country_name)}">
                  <div>
                    <div class="similar-name">${escape(s.country_name)}</div>
                    <div class="similar-region">${escape(s.region)}</div>
                  </div>
                  <div class="similar-score">${Math.round(s.score * 100)}%</div>
                </div>
              `).join("")}
        </div>
      </div>
    `;

    // Wire similar-card clicks
    insightsPanelEl.querySelectorAll(".similar-card").forEach(el => {
      el.addEventListener("click", () => fetchInsights(el.dataset.country));
    });
  }

  function visaCardHTML(v) {
    const incomeStr = v.min_income > 0
      ? `<span class="visa-meta">💵 Min income: $${v.min_income.toLocaleString()}/mo</span>` : "";
    const prClass = v.pr_route === "Yes" ? "pr-yes" : v.pr_route === "Eventually" ? "pr-soon" : "pr-no";
    return `
      <div class="visa-card">
        <div class="visa-head">
          <span class="visa-type type-${escape(v.type)}">${escape(v.type)}</span>
          <span class="visa-difficulty diff-${escape(v.difficulty)}">${escape(v.difficulty)}</span>
        </div>
        <div class="visa-name">${escape(v.name)}</div>
        <div class="visa-summary">${escape(v.summary)}</div>
        <div class="visa-footer">
          <span class="visa-meta">⏱ ${escape(v.duration)}</span>
          <span class="visa-meta visa-pr ${prClass}">🛂 PR: ${escape(v.pr_route)}</span>
          ${incomeStr}
        </div>
      </div>
    `;
  }

  function clearInsights() {
    state.selectedCountry = null;
    insightsPanelEl.innerHTML = `<p class="muted">Click a top country (or a country on the map) to see its breakdown and visa pathways.</p>`;
  }

  function renderFullTable(all) {
    tableBody.innerHTML = all.map((c, i) => `
      <tr>
        <td class="num">${i + 1}</td>
        <td>${escape(c.country_name)}</td>
        <td>${escape(c.region)}</td>
        <td class="num">${c.score.toFixed(2)}</td>
        <td><span class="card-badge ${c.score_category}">${c.score_category}</span></td>
        <td class="num">${c.average_salary.toFixed(2)}</td>
        <td class="num">${c.cost_of_living.toFixed(2)}</td>
        <td class="num">${c.pr_ease.toFixed(2)}</td>
        <td class="num">${c.job_market.toFixed(2)}</td>
        <td class="num">${c.climate.toFixed(2)}</td>
        <td class="num">${c.safety.toFixed(2)}</td>
        <td class="num">${c.healthcare.toFixed(2)}</td>
        <td class="num">${c.english.toFixed(2)}</td>
        <td class="num">${c.internet.toFixed(2)}</td>
      </tr>
    `).join("");
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  // ---------- Boot ----------
  async function boot() {
    await window.MapView.init({
      onSelect: (country) => fetchInsights(country.country_name),
    });
    await fetchScore();
  }

  boot();
})();
