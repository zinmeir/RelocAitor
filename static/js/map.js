/* =============================================================
   map.js
   Renders the interactive SVG world map with 3D pop-out on hover.
   Tooltip shows all 9 country metrics.
   ============================================================= */

const MapView = (() => {
  let svg = null;
  let stage = null;
  let tooltip = null;
  let loader = null;
  let pathByIso3 = {};
  let currentData = {};
  let onCountryClick = () => {};
  let lockedIso3 = null;

  async function init({ onSelect }) {
    svg     = document.getElementById("world-map");
    stage   = document.getElementById("map-stage");
    tooltip = document.getElementById("map-tooltip");
    loader  = document.getElementById("map-loader");
    onCountryClick = onSelect || (() => {});

    try {
      const paths = await window.loadWorldPaths();
      renderPaths(paths);
      loader.classList.add("hidden");
    } catch (err) {
      console.error("Failed to load world map:", err);
      loader.innerHTML = `<div style="color:#f87171">Couldn't load world map data.<br>Check your internet connection and refresh.</div>`;
    }
  }

  function renderPaths(paths) {
    const frag = document.createDocumentFragment();
    paths.sort((a, b) => (a.iso3 ? 1 : 0) - (b.iso3 ? 1 : 0));

    for (const p of paths) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", "path");
      el.setAttribute("d", p.pathD);
      el.setAttribute("class", p.iso3 ? "country active" : "country inactive");
      if (p.iso3) {
        el.dataset.iso3 = p.iso3;
        el.dataset.name = p.name;
        pathByIso3[p.iso3] = el;
        wireEvents(el);
      }
      frag.appendChild(el);
    }
    svg.appendChild(frag);
  }

  function wireEvents(el) {
    el.addEventListener("mouseenter", (e) => {
      const data = currentData[el.dataset.iso3];
      if (!data) return;
      showTooltip(data, e);
    });
    el.addEventListener("mousemove", positionTooltip);
    el.addEventListener("mouseleave", hideTooltip);
    el.addEventListener("click", () => {
      const data = currentData[el.dataset.iso3];
      if (!data) return;
      lockCountry(el.dataset.iso3);
      onCountryClick(data);
    });
  }

  function update(scoredList) {
    currentData = {};

    for (const c of scoredList) {
      currentData[c.country_code] = c;

      const el = pathByIso3[c.country_code];
      if (!el) continue;

      let tier = "low";
      if (c.score >= 0.85) tier = "top";
      else if (c.score >= 0.65) tier = "high";
      else if (c.score >= 0.4) tier = "mid";
      el.dataset.tier = tier;

      let glow = "rgba(134, 239, 172, 0.9)";
      if (c.score_category === "Medium") glow = "rgba(251, 191, 36, 0.8)";
      else if (c.score_category === "Low") glow = "rgba(248, 113, 113, 0.7)";
      el.style.setProperty("--glow", glow);
    }

    for (const iso3 of Object.keys(pathByIso3)) {
      const el = pathByIso3[iso3];
      if (!currentData[iso3]) {
        el.classList.remove("active");
        el.classList.add("inactive");
        el.removeAttribute("data-tier");
      } else {
        el.classList.add("active");
        el.classList.remove("inactive");
      }
    }
  }

  function lockCountry(iso3) {
    if (lockedIso3 && pathByIso3[lockedIso3]) {
      pathByIso3[lockedIso3].classList.remove("locked");
    }
    lockedIso3 = iso3;
    if (pathByIso3[iso3]) {
      pathByIso3[iso3].classList.add("locked");
    }
  }

  // ------------- Tooltip -------------
  function showTooltip(c, e) {
    const pct = Math.round(c.score * 100);
    tooltip.innerHTML = `
      <div class="tt-name">${escape(c.country_name)}</div>
      <div class="tt-region">${escape(c.region)}</div>
      <div class="tt-score-row">
        <div class="tt-score">${pct}%</div>
        <div class="tt-cat ${c.score_category}">${c.score_category} match</div>
      </div>
      <div class="tt-metrics">
        ${row("💰", "Salary",        c.average_salary)}
        ${row("🛒", "Cost",          c.cost_of_living)}
        ${row("🛂", "PR ease",       c.pr_ease)}
        ${row("💼", "Job market",    c.job_market)}
        ${row("☀️", "Climate",       c.climate)}
        ${row("🛡️", "Safety",        c.safety)}
        ${row("🏥", "Healthcare",    c.healthcare)}
        ${row("🗣️", "English",       c.english)}
        ${row("🌐", "Internet",      c.internet)}
      </div>
    `;
    tooltip.classList.remove("hidden");
    positionTooltip(e);
  }

  function row(icon, label, val) {
    return `
      <div class="tt-metric">
        <span class="tt-metric-label">${icon} ${label}</span>
        <span class="tt-metric-value">${val.toFixed(2)}</span>
        <div class="tt-bar"><div class="tt-bar-fill" style="width:${val * 100}%"></div></div>
      </div>
    `;
  }

  function positionTooltip(e) {
    const rect = stage.getBoundingClientRect();
    const ttRect = tooltip.getBoundingClientRect();
    const pad = 18;
    let x = e.clientX - rect.left + pad;
    let y = e.clientY - rect.top + pad;
    if (x + ttRect.width  > rect.width  - 8) x = e.clientX - rect.left - ttRect.width  - pad;
    if (y + ttRect.height > rect.height - 8) y = e.clientY - rect.top  - ttRect.height - pad;
    tooltip.style.left = `${Math.max(8, x)}px`;
    tooltip.style.top  = `${Math.max(8, y)}px`;
  }

  function hideTooltip() {
    tooltip.classList.add("hidden");
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  return { init, update, lockCountry };
})();

window.MapView = MapView;
