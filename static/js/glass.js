/* =============================================================
   glass.js — Apple-style "Liquid Glass" behaviour.

   - Specular sheen: glass surfaces catch a soft highlight under the
     pointer (CSS vars --mx/--my).
   - Refraction (Chromium only): floating bars marked [data-refract]
     bend what's behind their edges like a lens. Each gets an SVG
     displacement map computed from its own rounded shape, used as a
     backdrop filter. Other browsers keep the frosted glass.
   - Scroll edge: the floating nav bar turns more opaque once content
     scrolls under it.
   - Segmented controls built from <select data-segmented>.
   - Bottom sheet on phones: drag the grabber down to dismiss.
   Everything respects "reduce transparency" and "reduce motion".
   ============================================================= */
(function () {
  "use strict";

  const reduceTransparency = window.matchMedia("(prefers-reduced-transparency: reduce)").matches;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isChromium = !!(navigator.userAgentData && navigator.userAgentData.brands &&
    navigator.userAgentData.brands.some(b => /Chromium|Google Chrome|Microsoft Edge/.test(b.brand)));

  // ---------- Specular sheen under the pointer ----------
  let pending = null, queued = false;
  document.addEventListener("pointermove", (e) => {
    pending = e;
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const ev = pending;
      const el = ev.target && ev.target.closest && ev.target.closest(".glass");
      if (el) {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${ev.clientX - r.left}px`);
        el.style.setProperty("--my", `${ev.clientY - r.top}px`);
      }
    });
  }, { passive: true });

  // ---------- Scroll edge effect for the nav bar ----------
  const topbar = document.querySelector(".topbar");
  const scroller = document.body;
  const onScroll = () => topbar && topbar.classList.toggle("scrolled", scroller.scrollTop > 12);
  scroller.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ---------- Segmented controls ----------
  const segments = [];
  function buildSegmented(select) {
    const wrap = document.createElement("div");
    wrap.className = "segmented";
    wrap.setAttribute("role", "radiogroup");
    if (select.getAttribute("aria-label")) wrap.setAttribute("aria-label", select.getAttribute("aria-label"));
    const thumb = document.createElement("span");
    thumb.className = "seg-thumb";
    wrap.appendChild(thumb);
    const labels = { "": "Any", Easy: "Easy", Moderate: "Moderate" };
    const buttons = [...select.options].map(opt => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "seg-btn";
      b.setAttribute("role", "radio");
      b.dataset.value = opt.value;
      b.textContent = labels[opt.value] ?? opt.textContent;
      b.title = opt.textContent;
      b.addEventListener("click", () => {
        if (select.value === opt.value) return;
        select.value = opt.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        sync();
      });
      wrap.appendChild(b);
      return b;
    });
    wrap.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      const i = buttons.findIndex(b => b.dataset.value === select.value);
      const next = buttons[(i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length];
      next.click();
      next.focus();
      e.preventDefault();
    });
    select.parentNode.insertBefore(wrap, select);
    const label = document.querySelector(`label[for="${select.id}"]`);
    if (label) label.addEventListener("click", (e) => { e.preventDefault(); buttons[0].focus(); });
    segments.push({ select, buttons, thumb });
  }
  function sync() {
    for (const { select, buttons, thumb } of segments) {
      let active = null;
      for (const b of buttons) {
        const on = b.dataset.value === select.value;
        b.setAttribute("aria-checked", String(on));
        b.tabIndex = on ? 0 : -1;
        if (on) active = b;
      }
      if (active) {
        thumb.style.width = `${active.offsetWidth}px`;
        thumb.style.transform = `translateX(${active.offsetLeft - 3}px)`;
      }
    }
  }
  document.querySelectorAll("select[data-segmented]").forEach(buildSegmented);
  sync();
  window.addEventListener("resize", sync);

  // ---------- Refraction (Chromium): an SVG lens per floating bar ----------
  const SVGNS = "http://www.w3.org/2000/svg";
  let defs = null, filterSeq = 0;
  function ensureDefs() {
    if (defs) return defs;
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.setAttribute("aria-hidden", "true");
    svg.style.position = "absolute";
    defs = document.createElementNS(SVGNS, "defs");
    svg.appendChild(defs);
    document.body.appendChild(svg);
    return defs;
  }

  // Signed distance to a rounded rectangle centred at the origin (negative inside).
  function sdRoundRect(px, py, hw, hh, r) {
    const qx = Math.abs(px) - (hw - r), qy = Math.abs(py) - (hh - r);
    const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
    return Math.hypot(ox, oy) + Math.min(Math.max(qx, qy), 0) - r;
  }

  // Displacement map: R/G = horizontal/vertical shift (0.5 = none). Inside a bezel near the
  // edge, background pixels are pulled inward along the edge normal, like a convex lens rim.
  function lensMap(w, h, radius, bezel) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    const img = ctx.createImageData(w, h);
    const hw = w / 2, hh = h / 2, r = Math.min(radius, hw, hh);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const px = x + 0.5 - hw, py = y + 0.5 - hh;
        const d = -sdRoundRect(px, py, hw, hh, r);           // distance inside the edge
        let dx = 0, dy = 0;
        if (d >= 0 && d < bezel) {
          const gx = sdRoundRect(px + 1, py, hw, hh, r) - sdRoundRect(px - 1, py, hw, hh, r);
          const gy = sdRoundRect(px, py + 1, hw, hh, r) - sdRoundRect(px, py - 1, hw, hh, r);
          const len = Math.hypot(gx, gy) || 1;
          const t = 1 - d / bezel;
          const m = t * t * (3 - 2 * t);                       // smooth falloff
          dx = -(gx / len) * m;
          dy = -(gy / len) * m;
        }
        const i = (y * w + x) * 4;
        img.data[i] = Math.round(127.5 + 127.5 * dx);
        img.data[i + 1] = Math.round(127.5 + 127.5 * dy);
        img.data[i + 2] = 128;
        img.data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return c.toDataURL();
  }

  function refract(el) {
    const w = Math.round(el.offsetWidth), h = Math.round(el.offsetHeight);
    if (w < 20 || h < 20) return;
    const key = `${w}x${h}`;
    if (el.dataset.lensKey === key) return;
    el.dataset.lensKey = key;
    const radius = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 24;
    const bezel = Math.min(28, h * 0.42);
    const id = el.dataset.lensId || `liquid-glass-${++filterSeq}`;
    el.dataset.lensId = id;
    let f = document.getElementById(id);
    if (!f) {
      f = document.createElementNS(SVGNS, "filter");
      f.id = id;
      ensureDefs().appendChild(f);
    }
    for (const [k, v] of Object.entries({ x: 0, y: 0, width: w, height: h, filterUnits: "userSpaceOnUse",
                                         primitiveUnits: "userSpaceOnUse", "color-interpolation-filters": "sRGB" }))
      f.setAttribute(k, v);
    f.innerHTML = "";
    const map = document.createElementNS(SVGNS, "feImage");
    map.setAttribute("href", lensMap(w, h, radius, bezel));
    for (const [k, v] of Object.entries({ x: 0, y: 0, width: w, height: h, result: "lens", preserveAspectRatio: "none" }))
      map.setAttribute(k, v);
    const disp = document.createElementNS(SVGNS, "feDisplacementMap");
    for (const [k, v] of Object.entries({ in: "SourceGraphic", in2: "lens", scale: 44,
                                         xChannelSelector: "R", yChannelSelector: "G" }))
      disp.setAttribute(k, v);
    f.append(map, disp);
    const value = `url(#${id}) blur(7px) saturate(190%)`;
    el.style.backdropFilter = value;
    el.style.webkitBackdropFilter = value;
    el.classList.add("refracting");
  }

  if (isChromium && !reduceTransparency && "ResizeObserver" in window) {
    const ro = new ResizeObserver(entries => entries.forEach(e => refract(e.target)));
    document.querySelectorAll("[data-refract]").forEach(el => ro.observe(el));
    // The compare bar starts hidden: re-check when it appears.
    const mo = new MutationObserver(() => document.querySelectorAll("[data-refract]").forEach(refract));
    document.querySelectorAll("[data-refract]").forEach(el => mo.observe(el, { attributes: true, attributeFilter: ["class"] }));
  }

  // ---------- Sheets: drag the grabber down to dismiss (phones) ----------
  function draggableSheet(sheet, grabber, dismiss) {
    if (!sheet || !grabber) return;
    let startY = null, lastY = 0, lastT = 0, velocity = 0;
    grabber.addEventListener("pointerdown", (e) => {
      startY = e.clientY; lastY = e.clientY; lastT = performance.now(); velocity = 0;
      grabber.setPointerCapture(e.pointerId);
      sheet.classList.add("dragging");
    });
    grabber.addEventListener("pointermove", (e) => {
      if (startY === null) return;
      const now = performance.now();
      velocity = (e.clientY - lastY) / Math.max(1, now - lastT);
      lastY = e.clientY; lastT = now;
      sheet.style.setProperty("--drag", `${Math.max(0, e.clientY - startY)}px`);
    });
    const end = () => {
      if (startY === null) return;
      const dist = lastY - startY;
      startY = null;
      sheet.classList.remove("dragging");
      sheet.style.removeProperty("--drag");
      if (dist > 140 || velocity > 0.8) dismiss();
    };
    grabber.addEventListener("pointerup", end);
    grabber.addEventListener("pointercancel", end);
  }
  draggableSheet(document.getElementById("drawer"), document.getElementById("sheet-grabber"),
                 () => document.getElementById("drawer-close").click());

  // ---------- Preferences sheet (narrow screens) ----------
  const sidebar = document.getElementById("sidebar");
  const fab = document.getElementById("prefs-fab");
  const scrim = document.getElementById("sheet-scrim");
  const narrow = window.matchMedia("(max-width: 1100px)");
  let fabOpener = null;
  function setPrefs(open) {
    if (!sidebar || !fab) return;
    sidebar.classList.toggle("open", open);
    fab.setAttribute("aria-expanded", String(open));
    scrim.hidden = !open;
    document.documentElement.classList.toggle("sheet-open", open);
    if (open) { fabOpener = document.activeElement; sidebar.scrollTop = 0; document.getElementById("prefs-done").focus({ preventScroll: true }); }
    else if (fabOpener && document.contains(fabOpener)) fabOpener.focus({ preventScroll: true });
    requestAnimationFrame(sync);
  }
  if (fab) {
    fab.addEventListener("click", () => setPrefs(true));
    document.getElementById("prefs-done").addEventListener("click", () => setPrefs(false));
    scrim.addEventListener("click", () => setPrefs(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sidebar.classList.contains("open")) setPrefs(false); });
    narrow.addEventListener("change", () => { if (!narrow.matches) setPrefs(false); });
    draggableSheet(sidebar, document.getElementById("prefs-grabber"), () => setPrefs(false));
    // Presets and the quiz live in the sheet: close it so the person sees what happened.
    sidebar.addEventListener("click", (e) => {
      if (narrow.matches && e.target.closest(".preset-chip, #quiz-start")) setTimeout(() => setPrefs(false), 180);
    });
  }

  // The floating button steps aside while the chat's message box is near the bottom of the screen.
  const composer = document.getElementById("prompt-form");
  if (fab && composer && "IntersectionObserver" in window) {
    new IntersectionObserver(([en]) => fab.classList.toggle("tucked", en.isIntersecting),
                             { rootMargin: "-72% 0px 0px 0px" }).observe(composer);
  }

  // ---------- Section navigation in the nav bar ----------
  // "Search" scrolls to the composer; the others open that view of the results.
  // The highlight follows: Search while the composer is on screen, otherwise the open view.
  const nav = document.getElementById("section-nav");
  if (nav) {
    const links = [...nav.querySelectorAll("a[data-section]")];
    const thumb = nav.querySelector(".seg-thumb");
    const place = (a) => {
      links.forEach(l => l.classList.toggle("active", l === a));
      links.forEach(l => (l === a ? l.setAttribute("aria-current", "true") : l.removeAttribute("aria-current")));
      if (a && a.offsetWidth) { thumb.style.width = `${a.offsetWidth}px`; thumb.style.transform = `translateX(${a.offsetLeft - 3}px)`; thumb.style.opacity = "1"; }
      else thumb.style.opacity = "0";
    };
    const search = document.getElementById("search");
    let searchVisible = true;
    const current = () => {
      if (searchVisible) return links.find(l => l.dataset.section === "search");
      const v = window.RelocViews ? window.RelocViews.current() : "matches";
      return links.find(l => l.dataset.view === v) || null;
    };
    if (search) new IntersectionObserver(([en]) => { searchVisible = en.isIntersecting; place(current()); },
                                          { rootMargin: "-30% 0px -60% 0px" }).observe(search);
    document.addEventListener("viewchange", () => place(current()));
    links.forEach(l => l.addEventListener("click", (e) => {
      e.preventDefault();
      if (l.dataset.view && window.RelocViews) {
        window.RelocViews.setView(l.dataset.view, { scroll: true });
        searchVisible = false;
      } else {
        const t = document.getElementById(l.dataset.section);
        if (t) scroller.scrollTo({ top: t.getBoundingClientRect().top + scroller.scrollTop - 70, behavior: reduceMotion ? "auto" : "smooth" });
        searchVisible = true;
      }
      place(current());
    }));
    place(links[0]);
    window.addEventListener("resize", () => place(current()));
  }

  window.GlassUI = { sync, refresh: () => document.querySelectorAll("[data-refract]").forEach(el => { delete el.dataset.lensKey; refract(el); }),
                     reduceMotion };
})();
