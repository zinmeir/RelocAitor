/* workspace.js — "My relocation": account, profile, shortlist, pathways + timeline, checklist, applications. */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const META = window.APP_META;
  const names = Object.fromEntries(META.nationalities.map(n => [n.code, n.name]));
  let csrf = null;

  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), 2600);
  }
  async function api(url, method = "GET", body) {
    const r = await fetch(url, { method, credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(d.error || `Request failed (${r.status})`), { status: r.status });
    return d;
  }

  // ---------- Account ----------
  $("auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const mode = (e.submitter && e.submitter.dataset.mode) || "login";
    const f = new FormData(e.target);
    try {
      const d = await api(`/api/me/${mode}`, "POST", { email: f.get("email"), password: f.get("password") });
      csrf = d.csrf; show(d.email);
    } catch (err) { $("auth-msg").textContent = err.message; }
  });
  $("ws-logout").addEventListener("click", async () => { await api("/api/me/logout", "POST").catch(() => {}); location.reload(); });

  async function boot() {
    try { const d = await api("/api/me"); csrf = d.csrf; show(d.email); } catch { /* signed out */ }
  }
  function show(email) {
    $("ws-auth").hidden = true; $("ws-app").hidden = false; $("ws-logout").hidden = false;
    $("ws-who").textContent = email;
    $("ws-start").value = new Date().toISOString().slice(0, 10);
    refresh();
  }
  async function refresh() {
    await Promise.all([loadProfile(), loadShortlist(), loadTimeline(), loadChecklist(), loadApps(), loadAlerts()]);
  }

  // ---------- Profile ----------
  const HASH = { nationality: "nat", monthly_income: "inc", investment_budget: "inv", occupation: "job", age: "age",
                 children: "kids", education: "edu", experience_years: "exp", english: "en", german: "de" };
  async function loadProfile() {
    const { profile } = await api("/api/me/profile");
    const bits = [];
    const nat = META.nationalities.find(n => n.code === profile.nationality);
    if (nat) bits.push(`${nat.demonym || nat.name} passport`);
    if (profile.occupation) bits.push((META.occupations.find(o => o.key === profile.occupation) || {}).label);
    if (profile.age) bits.push(`age ${profile.age}`);
    if (profile.education) bits.push(META.labels.education[profile.education]);
    if (profile.experience_years != null) bits.push(`${profile.experience_years} yrs experience`);
    if (profile.english) bits.push(`English ${profile.english}`);
    if (profile.german) bits.push(`German ${profile.german}`);
    if (profile.monthly_income != null) bits.push(`$${Number(profile.monthly_income).toLocaleString()} a month`);
    $("ws-profile").textContent = bits.filter(Boolean).join(", ") || "No profile saved yet.";
    const p = new URLSearchParams();
    for (const [k, h] of Object.entries(HASH)) if (profile[k] != null && profile[k] !== "") p.set(h, profile[k]);
    if (profile.partner) p.set("ptn", "1");
    $("ws-open-search").href = "./#" + p.toString();
  }

  // ---------- Alerts ----------
  async function loadAlerts() {
    const { alerts, note } = await api("/api/me/alerts");
    const eff = { now_eligible: "now open to you", no_longer_eligible: "no longer open to you", now_conditional: "now conditional",
                  affects_your_route: "changed on a route you can use", route_added: "new route", route_removed: "route removed" };
    $("ws-alerts").innerHTML = alerts.length ? alerts.map(a => `<li class="ws-alert"><b>${esc(a.name || a.route)}</b> (${esc(a.route.slice(0, 3))}):
        ${esc((a.label || a.kind).toLowerCase())} changed, ${esc(eff[a.effect] || a.effect)}.
        <small>Detected ${esc(a.detected)}; ${a.verification === "pending" ? "not yet verified by a person" : esc(a.verification)}</small></li>`).join("")
      : `<li class="ws-empty">${esc(note || "No logged rule change affects your saved profile.")}</li>`;
  }

  // ---------- Shortlist ----------
  async function loadShortlist() {
    const { shortlist } = await api("/api/me/shortlist");
    $("ws-shortlist").innerHTML = shortlist.length ? shortlist.map(s => `<li><span>${esc(names[s.country] || s.country)}</span>
        <button class="icon-btn" data-del-country="${esc(s.country)}" aria-label="Remove ${esc(names[s.country])}">×</button></li>`).join("")
      : `<li class="ws-empty">Nothing yet. Open a country on the search page and press <b>Save to My relocation</b>.</li>`;
  }
  $("ws-shortlist").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del-country]");
    if (b) { await api(`/api/me/shortlist?country=${encodeURIComponent(b.dataset.delCountry)}`, "DELETE"); loadShortlist(); }
  });

  // ---------- Pathways and timeline ----------
  async function loadTimeline() {
    const d = await api(`/api/me/timeline?start=${$("ws-start").value}`);
    $("ws-timeline").innerHTML = d.timelines.length ? d.timelines.map(t => `
      <div class="ws-tl">
        <div class="ws-tl-head"><b>${esc(t.title)}</b>
          <button class="btn btn-quiet" data-checklist="${esc(t.pathway)}">Make a checklist</button>
          <button class="btn btn-quiet" data-track="${esc(t.pathway)}">Track an application</button>
          <button class="icon-btn" data-del-path="${esc(t.pathway)}" aria-label="Remove pathway">×</button></div>
        <ol class="ws-milestones">${t.milestones.map(m => `<li><span>${esc(m.label)}</span><time>${m.date ? esc(m.date) : "date not established"}</time></li>`).join("")}</ol>
      </div>`).join("") + `<p class="field-note">${esc(d.note)}</p>`
      : `<p class="ws-empty">No saved pathways. Open a country's <b>Pathways</b> section on the search page and press <b>Save pathway</b>.</p>`;
  }
  $("ws-start").addEventListener("change", loadTimeline);
  const firstRoute = (pid) => pid.replace(/^direct:/, "").replace(/^free:.*/, "");
  $("ws-timeline").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del-path]"), chk = e.target.closest("[data-checklist]"), trk = e.target.closest("[data-track]");
    if (del) { await api(`/api/me/pathways?pathway=${encodeURIComponent(del.dataset.delPath)}`, "DELETE"); loadTimeline(); }
    if (chk) {
      const plan = await api("/api/me/pathways");
      const p = plan.pathways.find(x => x.id === chk.dataset.checklist);
      const routes = (p && p.steps ? p.steps.map(s => s.route).filter(Boolean) : [firstRoute(chk.dataset.checklist)]);
      for (const r of routes) await api("/api/me/checklist", "POST", { route: r }).catch(() => {});
      toast("Checklist updated"); loadChecklist();
    }
    if (trk) { await api("/api/me/applications", "POST", { route: firstRoute(trk.dataset.track) || trk.dataset.track, status: "planned" }); loadApps(); }
  });

  // ---------- Checklist ----------
  async function loadChecklist() {
    const d = await api("/api/me/checklist");
    $("ws-check-note").textContent = d.note;
    $("ws-checklist").innerHTML = d.items.length ? d.items.map(i => `<li>
        <label class="ws-check"><input type="checkbox" data-done="${i.id}" ${i.done ? "checked" : ""}><span>${esc(i.item)}</span></label>
        <small>${esc(i.route)} · ${esc(i.basis)}</small>
        <button class="icon-btn" data-del-item="${i.id}" aria-label="Remove item">×</button></li>`).join("")
      : `<li class="ws-empty">Make a checklist from a saved pathway, or add your own items.</li>`;
  }
  $("ws-checklist").addEventListener("change", async (e) => {
    const c = e.target.closest("[data-done]");
    if (c) await api("/api/me/checklist", "PATCH", { id: Number(c.dataset.done), done: c.checked });
  });
  $("ws-checklist").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del-item]");
    if (b) { await api(`/api/me/checklist?id=${b.dataset.delItem}`, "DELETE"); loadChecklist(); }
  });
  $("ws-check-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const item = e.target.item.value.trim();
    if (item) { await api("/api/me/checklist", "POST", { item }); e.target.reset(); loadChecklist(); }
  });

  // ---------- Applications ----------
  const LABEL = { planned: "Planned", preparing: "Preparing", ready: "Ready to apply", submitted: "Submitted",
                  awaiting_decision: "Awaiting decision", approved: "Approved", rejected: "Rejected", completed: "Completed" };
  async function loadApps() {
    const d = await api("/api/me/applications");
    $("ws-apps").innerHTML = d.applications.length ? d.applications.map(a => `<li>
        <span><b>${esc(a.route)}</b> <small>updated ${esc(a.updated.slice(0, 10))}</small></span>
        <select class="select" data-app="${a.id}" aria-label="Status of ${esc(a.route)}">${d.statuses.map(s => `<option value="${s}" ${s === a.status ? "selected" : ""}>${LABEL[s]}</option>`).join("")}</select>
        <button class="icon-btn" data-del-app="${a.id}" aria-label="Remove application">×</button></li>`).join("")
      : `<li class="ws-empty">Track an application from a saved pathway.</li>`;
  }
  $("ws-apps").addEventListener("change", async (e) => {
    const s = e.target.closest("[data-app]");
    if (s) { await api("/api/me/applications", "PATCH", { id: Number(s.dataset.app), status: s.value }); toast(`Status: ${LABEL[s.value]}`); }
  });
  $("ws-apps").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del-app]");
    if (b) { await api(`/api/me/applications?id=${b.dataset.delApp}`, "DELETE"); loadApps(); }
  });

  // ---------- Data ----------
  $("ws-export").addEventListener("click", async () => {
    const d = await api("/api/me/export");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }));
    a.download = "relocaitor-my-data.json"; a.click();
  });
  $("ws-delete").addEventListener("click", async () => {
    const pw = prompt("This deletes your account and everything in it. Enter your password to confirm.");
    if (!pw) return;
    try { await api("/api/me", "DELETE", { password: pw }); location.href = "./"; }
    catch (err) { toast(err.message); }
  });

  boot();
})();
