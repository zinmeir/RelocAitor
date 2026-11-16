/* =============================================================
   map.js
   Renders the interactive SVG world map with 3D pop-out on hover.
   Tooltip shows all 9 country metrics, real figures and visa count.
   Countries hidden by the user's filters are dimmed (inactive).
   Touch: a tap pins the card with a "See details" button (a second tap opens).
   Keyboard: focus the map, arrows step through the ranked countries, Enter opens.
   Choosing a region zooms the map to it.
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
  let lastPointer = "mouse";
  let pinnedIso3 = null;      // touch: the card stays open until you tap elsewhere
  let kbdIso3 = null;         // keyboard: the country the arrows are on
  let live = null;
  const FULL = [0, 0, 1000, 500];
  let view = FULL.slice();
  let pendingBox = undefined; // true when a zoom was asked for while the map was hidden
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  async function init({ onSelect }) {
    svg     = document.getElementById("world-map");
    stage   = document.getElementById("map-stage");
    tooltip = document.getElementById("map-tooltip");
    loader  = document.getElementById("map-loader");
    live    = document.getElementById("map-live");
    onCountryClick = onSelect || (() => {});
    wireStage();

    try {
      const { paths, markers } = await window.loadWorldPaths();
      renderPaths(paths);
      renderMarkers(markers);
      loader.classList.add("hidden");
    } catch (err) {
      console.error("Failed to load world map:", err);
      loader.innerHTML = `<div style="color:#f87171; text-align:center">Couldn't load world map data.<br>Check your internet connection and refresh.<br><span style="color:var(--text-muted)">Everything else on the page still works.</span></div>`;
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

  function renderMarkers(markers) {
    for (const m of markers) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      el.setAttribute("cx", m.cx.toFixed(1));
      el.setAttribute("cy", m.cy.toFixed(1));
      el.setAttribute("r", "4");
      el.setAttribute("class", "country active marker");
      el.dataset.iso3 = m.iso3;
      pathByIso3[m.iso3] = el;
      wireEvents(el);
      svg.appendChild(el);   // after paths so dots sit on top
    }
  }

  function wireEvents(el) {
    el.addEventListener("mouseenter", (e) => {
      if (pinnedIso3 || lastPointer !== "mouse") return;
      const data = currentData[el.dataset.iso3];
      if (!data) return;
      setKbd(null);
      showTooltip(data, e);
    });
    el.addEventListener("mousemove", (e) => { if (!pinnedIso3 && lastPointer === "mouse") positionTooltip(e); });
    el.addEventListener("mouseleave", () => { if (!pinnedIso3 && !kbdIso3) hideTooltip(); });
    el.addEventListener("click", (e) => {
      const iso3 = el.dataset.iso3, data = currentData[iso3];
      if (!data) return;
      e.stopPropagation();
      // Touch has no hover: the first tap shows the card, a second tap (or "See details") opens it.
      if (lastPointer !== "mouse" && pinnedIso3 !== iso3) { pin(iso3, e); return; }
      open(iso3);
    });
  }

  function open(iso3) {
    const data = currentData[iso3];
    if (!data) return;
    unpin();
    lockCountry(iso3);
    onCountryClick(data);
  }

  function pin(iso3, e) {
    pinnedIso3 = iso3;
    setKbd(iso3);
    showTooltip(currentData[iso3], e, { pinned: true });
  }
  function unpin() {
    pinnedIso3 = null;
    setKbd(null);
    tooltip.classList.remove("pinned");
    hideTooltip();
  }

  // ------------- Stage: pointers, taps outside, keyboard -------------
  function wireStage() {
    stage.addEventListener("pointerdown", (e) => { lastPointer = e.pointerType || "mouse"; }, true);
    stage.addEventListener("click", (e) => {
      if (e.target.closest(".tt-open")) { open(e.target.closest(".tt-open").dataset.iso3); return; }
      if (pinnedIso3 && !e.target.closest("#map-tooltip")) unpin();
    });
    stage.addEventListener("keydown", onKey);
    stage.addEventListener("blur", (e) => {
      if (!stage.contains(e.relatedTarget)) { setKbd(null); if (!pinnedIso3) hideTooltip(); }
    });
  }

  const ranked = () => Object.values(currentData)
    .filter(c => c.rank && pathByIso3[c.country_code]).sort((a, b) => a.rank - b.rank);

  function onKey(e) {
    if (e.target !== stage) return;
    const list = ranked();
    if (!list.length) return;
    const i = list.findIndex(c => c.country_code === kbdIso3);
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    let next = null;
    if (step) next = i === -1 ? 0 : (i + step + list.length) % list.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = list.length - 1;
    else if ((e.key === "Enter" || e.key === " ") && kbdIso3) { e.preventDefault(); open(kbdIso3); return; }
    else if (e.key === "Escape" && (kbdIso3 || pinnedIso3)) { e.stopPropagation(); setKbd(null); unpin(); return; }
    if (next === null) return;
    e.preventDefault();
    const c = list[next];
    setKbd(c.country_code);
    const r = pathByIso3[c.country_code].getBoundingClientRect();
    showTooltip(c, { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }, { keyboard: true });
    const visas = c.visas_researched === false ? "visas not researched"
      : typeof c.qualifying_visas === "number" ? `${c.qualifying_visas} visa${c.qualifying_visas === 1 ? "" : "s"} open` : "";
    live.textContent = `Number ${c.rank}, ${c.country_name}, ${Math.round(c.score * 100)}% match${visas ? ", " + visas : ""}. Press Enter for details.`;
  }

  function setKbd(iso3) {
    if (kbdIso3 && pathByIso3[kbdIso3]) pathByIso3[kbdIso3].classList.remove("kbd");
    kbdIso3 = iso3;
    if (iso3 && pathByIso3[iso3]) {
      const el = pathByIso3[iso3];
      el.classList.add("kbd");
      el.parentNode.appendChild(el);   // on top, so the lifted outline isn't covered by its neighbours
    }
  }

  // ------------- Region zoom (animated viewBox) -------------
  // codes: the countries to fit, or null for the whole world.
  let wanted = null;
  function focusRegion(codes) {
    wanted = codes && codes.length ? codes : null;
    if (!svg || !svg.getBoundingClientRect().width) { pendingBox = true; return; }   // hidden: zoom when shown
    pendingBox = undefined;
    const box = wanted ? boxFor(wanted) : FULL;
    if (box) animateTo(box);
  }
  function shown() {
    if (!pendingBox) return;
    pendingBox = undefined;
    const box = wanted ? boxFor(wanted) : FULL;
    if (box) animateTo(box, true);
  }
  function boxFor(codes) {
    const boxes = codes.map(c => pathByIso3[c]).filter(Boolean).map(el => el.getBBox());
    if (!boxes.length || boxes.every(b => !b.width && !b.height)) return null;
    // Very wide countries (Russia, Canada) would stretch the box: use their centre instead.
    const pts = boxes.flatMap(b => b.width > 260 && boxes.length > 2
      ? [[b.x + b.width / 2 - 30, b.y + b.height / 2 - 20], [b.x + b.width / 2 + 30, b.y + b.height / 2 + 20]]
      : [[b.x, b.y], [b.x + b.width, b.y + b.height]]);
    let x0 = Math.min(...pts.map(p => p[0])), x1 = Math.max(...pts.map(p => p[0]));
    let y0 = Math.min(...pts.map(p => p[1])), y1 = Math.max(...pts.map(p => p[1]));
    const pad = 24;
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad;
    let w = Math.max(x1 - x0, 160), h = Math.max(y1 - y0, 80);
    if (w / h > 2) h = w / 2; else w = h * 2;                     // keep the stage's 2:1 shape
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    w = Math.min(w, 1000); h = Math.min(h, 500);
    return [Math.max(0, Math.min(1000 - w, cx - w / 2)), Math.max(0, Math.min(500 - h, cy - h / 2)), w, h];
  }
  function animateTo(box, instant = false) {
    const from = view.slice();
    if (from.every((v, i) => Math.abs(v - box[i]) < 0.5)) return;
    svg.classList.toggle("zoomed", box[2] < 999);
    const set = (b) => { view = b; svg.setAttribute("viewBox", b.map(v => v.toFixed(1)).join(" ")); svg.style.setProperty("--zoom", (1000 / b[2]).toFixed(2)); };
    if (instant || reduceMotion) { set(box); return; }
    const t0 = performance.now(), ms = 520;
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      set(from.map((v, i) => v + (box[i] - v) * e));
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
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

      let glow = "rgba(134, 239, 172, 0.7)";                                      // match green
      if (c.score_category === "Medium") glow = "rgba(245, 200, 106, 0.6)";       // lamp gold
      else if (c.score_category === "Low") glow = "rgba(255, 138, 128, 0.5)";     // soft coral
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
  function showTooltip(c, e, { pinned = false, keyboard = false } = {}) {
    const pct = Math.round(c.score * 100);
    const meta = [escape(c.region)];
    if (c.rank) meta.push(`#${c.rank}`);
    if (c.visas_researched === false) meta.push("visas not researched yet");
    else if (typeof c.qualifying_visas === "number")
      meta.push(`${c.qualifying_visas} visa${c.qualifying_visas === 1 ? "" : "s"} likely open to you`);
    const temp = c.avg_temp_c != null ? ` · <b>${Number(c.avg_temp_c).toFixed(1)} °C</b> in ${escape(c.main_city)}` : "";
    tooltip.innerHTML = `
      <div class="tt-name">${escape(c.country_name)}</div>
      <div class="tt-region">${meta.join(" · ")}</div>
      <div class="tt-score-row">
        <div class="tt-score">${pct}%</div>
        <div class="tt-cat ${c.score_category}">${c.score_category} match</div>
      </div>
      <div class="tt-metrics">
        ${row(c, "salary",     "Salary",      c.average_salary)}
        ${row(c, "cost",       "Cost",        c.cost_of_living)}
        ${row(c, "pr",         "PR ease",     c.pr_ease)}
        ${row(c, "job",        "Job market",  c.job_market)}
        ${row(c, "climate",    "Climate",     c.climate)}
        ${row(c, "safety",     "Safety",      c.safety)}
        ${row(c, "healthcare", "Healthcare",  c.healthcare)}
        ${row(c, "english",    "English",     c.english)}
        ${row(c, "internet",   "Internet",    c.internet)}
      </div>
      <div class="tt-foot">
        About ${est(c, "salary_money")}<b>${fmt(c.salary_usd_month)}</b>/mo net salary ·
        ${est(c, "rent_money")}<b>${fmt(c.rent_usd_month)}</b>/mo rent${temp}
      </div>
      ${pinned ? `<button type="button" class="tt-open" data-iso3="${escape(c.country_code)}">See details</button>` : ""}
      ${keyboard ? `<div class="tt-keys">Enter for details · arrows for the next country</div>` : ""}
    `;
    tooltip.classList.toggle("pinned", pinned);
    tooltip.classList.toggle("compact", pinned && stage.clientHeight < 460);   // phones: a short card along the bottom
    tooltip.classList.remove("hidden");
    positionTooltip(e);
  }

  const fmt = (n) => window.fmtMoney ? window.fmtMoney(n) : `$${Math.round(Number(n)).toLocaleString()}`;
  function est(c, key) {
    const keys = ((window.APP_META || {}).estimated || {})[c.country_code] || [];
    return keys.includes(key) ? `<span class="est" title="Estimate: no measurement for this country">≈</span>` : "";
  }

  // Factor rows use the app's line icons and factor colours (window.ICONS), falling back to plain labels.
  function icon(key) {
    const body = window.ICONS && window.ICONS[key];
    return body ? `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${body}</svg>` : "";
  }

  function row(c, key, label, val) {
    return `
      <div class="tt-metric f-${key}">
        <span class="tt-metric-label">${icon(key)}<span>${label}</span></span>
        <span class="tt-metric-value">${est(c, key)}${val.toFixed(2)}</span>
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

  return { init, update, lockCountry, focusRegion, shown };
})();

window.MapView = MapView;
