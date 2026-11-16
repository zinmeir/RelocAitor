/* =============================================================
   mock_api.js — In-browser port of the Flask backend, used ONLY by
   the standalone artifact preview (no server available there).
   Implements /api/score, /api/insights, /api/compare, /api/ask,
   /api/visas with the same logic as engine.py, scoring.py,
   eligibility.py, reasoning.py and assistant.py (rules mode).
   Expects globalThis.RELOC_DATA = {countries, visas, meta}.
   ============================================================= */
(function (root) {
  "use strict";

  const D = root.RELOC_DATA;
  const META = D.meta;
  const FACTOR_KEYS = META.factor_order;
  const COL = {
    salary: "average_salary", cost: "cost_of_living", pr: "pr_ease", job: "job_market",
    climate: "climate", safety: "safety", healthcare: "healthcare", english: "english", internet: "internet",
  };
  const INVERT = { cost: true };
  const PHRASE = {
    salary: "salary potential", cost: "affordability", pr: "PR accessibility", job: "job market strength",
    climate: "climate quality", safety: "personal safety", healthcare: "healthcare quality",
    english: "English proficiency", internet: "internet infrastructure",
  };
  const DESCRIPTOR = {
    salary: "maximizing income", cost: "keeping living costs manageable",
    pr: "long-term stability and permanent residency", job: "career opportunities and a strong job market",
    climate: "a pleasant climate and natural environment", safety: "personal safety and security",
    healthcare: "world-class healthcare access", english: "an English-speaking environment",
    internet: "fast, reliable digital infrastructure",
  };
  const SIM = ["average_salary", "cost_of_living", "pr_ease", "job_market", "language_barrier",
               "climate", "safety", "healthcare", "english", "internet"];
  const DIFF = { Easy: 0, Moderate: 1, Hard: 2 };
  const PR_YES = new Set(["Yes", "Eventually"]);
  const ALL = "All regions";

  const r4 = (x) => Math.round(x * 1e4) / 1e4;
  const r6 = (x) => Math.round(x * 1e6) / 1e6;
  const roundHalfEven = (x) => { const f = Math.floor(x), d = x - f;
    if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1; return Math.round(x); };
  const label = (k) => META.factors[k].label;
  const fv = (row, k) => (INVERT[k] ? 1 - row[COL[k]] : row[COL[k]]);
  const usd = (n) => "$" + Math.round(n).toLocaleString("en-US");
  const f2 = (n) => Number(n).toFixed(2);

  class HttpError extends Error { constructor(status, msg) { super(msg); this.status = status; } }

  // ---------------- eligibility.py ----------------
  // Blocs and visa checks come from data/rules.json, the same file eligibility.py reads.
  const RULES = D.rules;
  const BLOCS = RULES.blocs;

  function visaFilterActive(p) {
    return p.only_qualifying || p.require_pr || !["", "any", null, undefined].includes(p.visa_type) || !!p.max_difficulty;
  }

  function freeMovement(nat, dest) {
    if (!nat || nat === dest) return [];
    return BLOCS.filter(b => b.members.includes(nat) && b.members.includes(dest)).map(b => ({
      type: "free", name: b.name, difficulty: "Easy", duration: b.duration, pr_route: b.pr_route,
      min_income: 0, min_investment: 0, summary: b.summary, generated: true, last_verified: null,
    }));
  }

  const getPath = (obj, path) => path.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
  const fieldLabels = (keys) => keys.map(k => (D.occupations[k] && D.occupations[k].label) || k);
  const pyList = (l) => "[" + l.map(x => `'${x}'`).join(", ") + "]";
  function langText(req) {
    if (req && typeof req === "object") {
      const name = RULES.labels.language[req.lang] || req.lang;
      return `${name} at ${req.cefr || req.test}` + (req.cefr ? " (CEFR)" : "");
    }
    return String(req);
  }
  function ruleText(t, vv, pv) {
    const edu = RULES.labels.education;
    if (t.includes("{visa:education}")) t = t.replace("{visa:education}", edu[vv] || String(vv));
    if (t.includes("{profile:education}")) t = t.replace("{profile:education}", edu[pv] || String(pv));
    if (t.includes("{visa:language}")) t = t.replace("{visa:language}", langText(vv));
    if (t.includes("{profile:language}")) t = t.replace("{profile:language}", String(pv));
    if (t.includes("{visa:fields}")) t = t.replace("{visa:fields}", fieldLabels(vv).join(", "));
    if (t.includes("{visa:usd}")) t = t.replace("{visa:usd}", usd(vv));
    if (t.includes("{profile:usd}")) t = t.replace("{profile:usd}", usd(pv));
    return t.replaceAll("{visa}", String(vv)).replaceAll("{profile}", String(pv));
  }
  function ruleOutcome(rule, v, p) {
    if ((rule.skip_types || []).includes(v.type)) return null;
    const vv = getPath(v, rule.visa);
    if (vv === undefined || vv === null || (Array.isArray(vv) && !vv.length) || (rule.ignore_zero && vv === 0)) return null;
    if (rule.test === "flag") return vv ? [rule.fail, vv, null] : null;
    if (rule.test === "language") {
      const lv = p[vv.lang];
      if (!lv) return [rule.missing, vv, lv];
      if (!vv.cefr) return [rule.incomparable, vv, lv];
      const sc = RULES.scales.cefr;
      return sc.indexOf(lv) < sc.indexOf(vv.cefr) ? [rule.fail, vv, lv] : null;
    }
    const pv = p[rule.profile];
    if (pv === undefined || pv === null || pv === "") return rule.missing ? [rule.missing, vv, pv] : null;
    const failed = { in: () => !vv.includes(pv), at_least: () => pv < vv, at_most: () => pv > vv,
                     allowed: () => vv === false && !!pv,
                     rank_at_least: () => RULES.scales[rule.scale].indexOf(pv) < RULES.scales[rule.scale].indexOf(vv) }[rule.test]();
    return failed ? [rule.fail, vv, pv] : null;
  }
  function evaluateVisa(v, p) {
    let status = "eligible";
    const reasons = [];
    for (const rule of RULES.visa_rules) {
      const hit = ruleOutcome(rule, v, p);
      if (!hit) continue;
      const [outcome, vv, pv] = hit;
      if (rule.only_if_eligible && status !== "eligible") continue;
      if (outcome.status === "ineligible") status = "ineligible";
      else if (status === "eligible") status = "conditional";
      reasons.push(ruleText(outcome.text, vv, pv));
    }
    return { status, reasons };
  }

  function matches(v, p) {
    const vt = p.visa_type;
    if (!["", "any", null, undefined].includes(vt) && v.type !== vt && v.type !== "free") return false;
    if (p.require_pr && !PR_YES.has(v.pr_route)) return false;
    if (p.max_difficulty && (DIFF[v.difficulty] ?? 2) > (DIFF[p.max_difficulty] ?? 2)) return false;
    return true;
  }

  function qualifies(v, verdict, p) {
    if (!matches(v, p)) return false;
    if (verdict.status === "eligible") return true;
    return verdict.status === "conditional" && !!v.requires_sponsor && p.visa_type === "family";
  }

  function visasForProfile(code, p) {
    const entry = D.visas[code];
    const country = entry || {};
    const visas = freeMovement(p.nationality, code).concat(entry ? entry.visas.map(v => ({ ...v })) : []);
    let q = 0;
    for (const v of visas) {
      v.eligibility = evaluateVisa(v, p);
      v.qualifies = qualifies(v, v.eligibility, p);
      v.timeline = timeline(v, country);
      if (v.fields && v.fields.length && p.occupation) v.field_match = v.fields.includes(p.occupation);
      q += v.qualifies ? 1 : 0;
    }
    return { visas, qualifying_count: q, is_home: !!p.nationality && p.nationality === code,
             official_url: entry ? entry.official_url : null,
             researched: !!entry,
             citizenship: country.citizenship ?? null, in_demand: country.in_demand ?? null,
             field_in_demand: fieldInDemand(country, p.occupation) };
  }

  // ---------------- journey.py ----------------
  const FX = META.fx.usd_per_unit;
  const SYMBOL = { USD: "$", EUR: "€", GBP: "£", JPY: "¥", INR: "₹", CAD: "CA$", AUD: "A$", NZD: "NZ$", SGD: "S$", HKD: "HK$" };
  const commas = (n) => Math.round(n).toLocaleString("en-US");
  const pyRound = (x) => roundHalfEven(x);
  function toUsd(amount, cur) {
    if (amount == null || !cur) return null;
    const rate = FX[cur];
    return rate == null ? null : pyRound(amount * rate);
  }
  function feeText(fee) {
    if (!fee || fee.amount == null) return null;
    const sym = SYMBOL[fee.currency];
    const local = sym ? `${sym}${commas(fee.amount)}` : `${commas(fee.amount)} ${fee.currency}`;
    const usdv = toUsd(fee.amount, fee.currency);
    if (fee.currency === "USD" || usdv == null) return local;
    return `${local} (about $${commas(usdv)})`;
  }
  function citizenshipAt(prYears, cit) {
    if (prYears == null || !cit || cit.years == null) return null;
    return Math.max(Number(cit.years), Number(prYears) + Number(cit.after_pr || 0));
  }
  function timeline(v, country) {
    if (v.generated) return null;
    const fee = v.fee;
    let prYears = v.years_to_pr ?? null;
    if (v.pr_route === "No") prYears = null;
    const cit = country.citizenship;
    const citYears = v.pr_route !== "No" ? citizenshipAt(prYears, cit) : null;
    if (!(fee || v.processing || prYears !== null)) return null;
    const weeks = v.processing_weeks ?? null;
    const steps = [{ at: 0, label: "Apply" }];
    if (weeks) steps.push({ at: Math.round(weeks / 52 * 100) / 100, label: "Visa decision" });
    if (prYears !== null) steps.push({ at: prYears, label: prYears ? "Permanent residence" : "Permanent residence on arrival" });
    if (citYears !== null) steps.push({ at: citYears, label: "Citizenship" });
    return {
      fee: feeText(fee), fee_usd: fee ? toUsd(fee.amount, fee.currency) : null, fee_note: fee ? (fee.note ?? null) : null,
      processing: v.processing ?? null, processing_weeks: weeks, pr_years: prYears, pr_note: v.pr_note ?? null, citizenship_years: citYears,
      steps, complete: fee != null && prYears !== null && citYears !== null,
    };
  }
  function fieldInDemand(country, field) {
    const lst = country.in_demand;
    if (!field || !lst) return null;
    return (lst.fields || []).includes(field);
  }

  // ---------------- scoring.py ----------------
  function effectiveWeights(w) {
    const used = {};
    let total = 0;
    for (const k of FACTOR_KEYS) { used[k] = Math.max(0, Number(w[k] || 0)); total += used[k]; }
    if (total === 0) for (const k of FACTOR_KEYS) used[k] = 1;
    return used;
  }

  function computeScores(rows, weights) {
    const used = effectiveWeights(weights);
    const total = FACTOR_KEYS.reduce((s, k) => s + used[k], 0);
    const out = rows.map(r => {
      const contributions = {};
      let raw = 0;
      for (const k of FACTOR_KEYS) { const c = (used[k] / total) * fv(r, k); contributions[k] = r4(c); raw += c; }
      return { ...r, _raw: raw, raw_score: r4(raw), contributions };
    });
    const mn = Math.min(...out.map(o => o._raw)), mx = Math.max(...out.map(o => o._raw));
    for (const o of out) {
      o.score = mx - mn < 1e-9 ? 1 : r4((o._raw - mn) / (mx - mn));
      o.score_category = categorize(o.score);
    }
    return out;
  }
  const categorize = (s) => (s >= 0.66 ? "High" : s >= 0.33 ? "Medium" : "Low");

  function similar(scored, name, n = 3) {
    const t = scored.find(r => r.country_name === name);
    if (!t) return [];
    const entry = ((META.country_map || {}).countries || {})[t.country_code];
    if (entry) {   // ML neighbours from the pipeline's country map
      const out = [];
      entry.neighbors.forEach((nb, i) => {
        const hit = scored.find(r => r.country_code === nb);
        if (hit && out.length < n) out.push({ ...clean(hit), distance: entry.distances[i] });
      });
      return out;
    }
    return scored.filter(r => r.country_name !== name)
      .map(r => ({ ...r, distance: r4(Math.sqrt(SIM.reduce((s, c) => s + (r[c] - t[c]) ** 2, 0))) }))
      .sort((a, b) => a.distance - b.distance).slice(0, n).map(clean);
  }

  // ---------------- engine.py ----------------
  function qualTable(p) {
    const q = {};
    for (const r of D.countries) q[r.country_code] = visasForProfile(r.country_code, p);
    return q;
  }

  function rank(weights, region, p, qual) {
    qual = qual || qualTable(p);
    const scored = computeScores(D.countries, weights).sort((a, b) => r6(b._raw) - r6(a._raw));
    scored.forEach((r, i) => {
      r.global_rank = i + 1;
      r.qualifying_visas = qual[r.country_code].qualifying_count;
      r.is_home = qual[r.country_code].is_home;
      r.field_in_demand = qual[r.country_code].field_in_demand;
      r.visas_researched = qual[r.country_code].researched;
    });
    const active = visaFilterActive(p);
    const excl = new Set(p.exclude_countries || []);
    const out = scored.filter(r =>
      (!region || region === ALL || r.region === region) &&
      !(p.exclude_home && r.is_home) &&
      !excl.has(r.country_code) &&
      !(active && r.qualifying_visas <= 0 && r.visas_researched));
    out.forEach((r, i) => { r.rank = i + 1; });
    return out;
  }

  const rankOf = (ranked, name) => { const r = ranked.find(x => x.country_name === name); return r ? r.rank : null; };

  function whatIfCountry(weights, region, p, name, qual) {
    const old = rankOf(rank(weights, region, p, qual), name);
    if (old == null) return [];
    const res = [];
    for (const k of FACTOR_KEYS) {
      const cur = Number(weights[k] || 0);
      let best = null;
      for (const target of [0, 1]) {
        if (Math.abs(target - cur) < 0.05) continue;
        const nr = rankOf(rank({ ...weights, [k]: target }, region, p, qual), name);
        if (nr != null && nr < old && (best == null || nr < best[1])) best = [target, nr];
      }
      if (best) {
        const [target, nr] = best;
        res.push({ factor: k, from: Math.round(cur * 100) / 100, to: target, old_rank: old, new_rank: nr,
          text: `${target > cur ? "Raising" : "Lowering"} ${label(k)} to ${target.toFixed(1)} would move ${name} from #${old} to #${nr}.` });
      }
    }
    return res.sort((a, b) => a.new_rank - b.new_rank).slice(0, 3);
  }

  function variants(cur) {
    const c = new Set([Math.round(Math.max(0, cur - 0.3) * 100) / 100, Math.round(Math.min(1, cur + 0.3) * 100) / 100, 0, 1]);
    c.delete(Math.round(cur * 100) / 100);
    return [...c].sort((a, b) => Math.abs(a - cur) - Math.abs(b - cur));
  }

  function flipTop(weights, region, p, qual) {
    const base = rank(weights, region, p, qual);
    if (base.length < 2) return null;
    const leader = base[0].country_name;
    let best = null;
    for (const k of FACTOR_KEYS) {
      const cur = Number(weights[k] || 0);
      for (const t of variants(cur)) {
        const nl = rank({ ...weights, [k]: t }, region, p, qual)[0].country_name;
        if (nl !== leader) {
          const d = Math.abs(t - cur);
          if (!best || d < best.delta) best = { factor: k, from: Math.round(cur * 100) / 100, to: t, delta: Math.round(d * 100) / 100, leader, new_leader: nl };
          break;
        }
      }
    }
    if (!best) return { text: `${leader} stays #1 no matter which single slider you move. It's a robust match.`, leader };
    const dir = best.to < best.from ? "less" : "more";
    best.text = `If you cared ${dir} about ${label(best.factor).toLowerCase()} (${f2(best.from)} → ${f2(best.to)}), ${best.new_leader} would take #1 from ${leader}.`;
    return best;
  }

  // ---------------- reasoning.py ----------------
  function quality(v) {
    if (v >= 0.85) return "world-class"; if (v >= 0.7) return "excellent"; if (v >= 0.55) return "strong";
    if (v >= 0.4) return "moderate"; if (v >= 0.25) return "limited"; return "weak";
  }
  const join = (a) => a.length <= 1 ? (a[0] || "") : a.slice(0, -1).join(", ") + " and " + a[a.length - 1];

  function priorities(w, n = 4) {
    const ranked = FACTOR_KEYS.map(k => [k, w[k]]).sort((a, b) => b[1] - a[1]);
    const top = ranked.filter(([, v]) => v > 0).slice(0, n).map(([k]) => k);
    return top.length ? top : [ranked[0][0]];
  }

  function explanation(row, w, rk, total) {
    const name = row.country_name;
    const prefs = priorities(w);
    const phrase = (k) => `${quality(fv(row, k))} ${PHRASE[k]} (${f2(fv(row, k))})`;
    const strengths = prefs.filter(k => fv(row, k) >= 0.55);
    const weak = prefs.filter(k => fv(row, k) < 0.45);
    const pos = rk && total ? `#${rk} of ${total}` : null;
    const top = rk != null && total && (rk <= 5 || rk <= Math.max(1, Math.floor(total / 5)));
    const low = rk != null && total && rk > total * 0.6;

    if (top || (rk == null && strengths.length && !weak.length)) {
      const lead = pos ? `${name} ranks ${pos} for you` : `${name} is a strong match`;
      let t = `${lead} because it offers ${join((strengths.length ? strengths : prefs).slice(0, 3).map(phrase))}, which lines up with your top priorities.`;
      if (weak.length) t += ` The main drawback is ${join(weak.slice(0, 1).map(phrase))}.`;
      return t;
    }
    if (low) {
      const lead = pos ? `${name} ranks ${pos}` : `${name} is a weak match`;
      let t = weak.length
        ? `${lead} mainly because of ${join(weak.slice(0, 2).map(phrase))}, which you rated as important.`
        : `${lead}: it doesn't stand out on the factors you weighted most.`;
      if (strengths.length) t += ` On the plus side, it has ${join(strengths.slice(0, 2).map(phrase))}.`;
      return t;
    }
    const lead = pos ? `${name} ranks ${pos}, a mixed match` : `${name} is a mixed match`;
    const parts = [];
    if (strengths.length) parts.push(`it offers ${join(strengths.slice(0, 2).map(phrase))}`);
    if (weak.length) parts.push(`it falls short on ${join(weak.slice(0, 2).map(phrase))}`);
    if (!parts.length) parts.push("it is average on most of the factors you care about");
    return `${lead}: ${parts.join(", but ")}.`;
  }

  function tradeoffs(r) {
    const t = [];
    const s = r.average_salary, c = r.cost_of_living, p = r.pr_ease, j = r.job_market, l = r.language_barrier,
          cl = r.climate, sf = r.safety, hc = r.healthcare, en = r.english, it = r.internet;
    if (s >= 0.7 && c >= 0.75) t.push("High earning potential, but a correspondingly high cost of living.");
    if (s >= 0.7 && p <= 0.45) t.push("Strong salaries, but permanent residency is relatively difficult to obtain.");
    if (p >= 0.75 && s <= 0.55) t.push("Very accessible PR pathway, but average salaries are on the lower side.");
    if (j >= 0.75 && l >= 0.6) t.push("Robust job market, though a significant language barrier may limit opportunities.");
    if (c <= 0.45 && j <= 0.55) t.push("Affordable to live in, but the job market is less competitive.");
    if (hc >= 0.85 && c >= 0.75) t.push("Excellent healthcare, though the high cost of living offsets some of that benefit.");
    if (cl >= 0.75 && en <= 0.4) t.push("Pleasant climate, but English isn't widely spoken, so expect a language learning curve.");
    if (sf >= 0.85 && j <= 0.55) t.push("Among the safest places in the world, but the job market is somewhat soft.");
    if (it >= 0.85 && s <= 0.55) t.push("Excellent digital infrastructure for a modest salary base.");
    if (en >= 0.85 && c >= 0.75) t.push("Very English-friendly, but with one of the higher costs of living.");
    const sal = r.salary_usd_month, rent = r.rent_usd_month;
    if (sal && rent) {
      const ratio = rent / sal, pc = roundHalfEven(ratio * 100) + "%";  // matches Python's :.0%
      if (ratio >= 1) t.push(`A city-centre 1-bed (~${usd(rent)}) costs more than the average net salary (~${usd(sal)}), so living on a local salary is hard. Remote or foreign income helps a lot.`);
      else if (ratio >= 0.6) t.push(`A city-centre 1-bed (~${usd(rent)}) costs about ${pc} of the average net salary (~${usd(sal)}). Local salaries stretch thin, so remote or foreign income helps a lot.`);
      else if (ratio <= 0.35) t.push(`Rent is manageable: a city-centre 1-bed (~${usd(rent)}) is about ${pc} of the average net salary (~${usd(sal)}).`);
    }
    if (!t.length) t.push("A relatively balanced profile with no major trade-offs.");
    return t;
  }

  function userInsight(w) {
    const sp = FACTOR_KEYS.map(k => [k, w[k]]).sort((a, b) => b[1] - a[1]);
    const vals = sp.map(x => x[1]);
    if (Math.max(...vals) === 0) return "All sliders are at zero, so every factor is weighted equally.";
    if (Math.max(...vals) - Math.min(...vals) < 0.05) return "You weigh every factor about equally. That's a well-rounded search.";
    const [[k1, v1], [k2, v2]] = sp;
    if (v1 - v2 < 0.15) return `You value a balance between ${DESCRIPTOR[k1]} and ${DESCRIPTOR[k2]}.`;
    return `You prioritize ${DESCRIPTOR[k1]} above other factors.`;
  }

  // ---------------- assistant.py (rules mode) ----------------
  const TOPICS = [
    ["family", ["spouse","partner","wife","husband","family","kids","children","child","dependent"]],
    ["pr", ["pr","permanent","residency","citizenship","passport","settle","green card"]],
    ["visa", ["visa","permit","qualify","eligible","apply","move","immigrat"]],
    ["cost", ["cost","rent","expensive","afford","cheap","price","budget"]],
    ["salary", ["salary","pay","earn","income","wage"]],
    ["job", ["job","career","employ","hiring","work"]],
    ["safety", ["safe","crime","danger","security"]],
    ["healthcare", ["health","hospital","doctor","medical","insurance"]],
    ["english", ["english","language","speak"]],
    ["climate", ["weather","climate","hot","cold","rain","sun","winter"]],
    ["internet", ["internet","wifi","broadband","remote"]],
  ];
  function detect(q) {
    q = ` ${q.toLowerCase()} `;
    const plain = q.replace(/\?/g, " ").replace(/,/g, " ");
    return TOPICS.filter(([, ws]) => ws.some(w => (w.length <= 3 ? plain.includes(` ${w} `) : q.includes(w)))).map(([t]) => t);
  }
  function visaLine(v) {
    const tag = { eligible: "", conditional: " (conditional)", ineligible: " (you don't currently qualify)" }[v.eligibility.status];
    return `${v.name}: ${v.difficulty.toLowerCase()}, PR: ${v.pr_route.toLowerCase()}${tag}`;
  }
  function answerRules(question, row, info, rk, total) {
    const name = row.country_name, visas = info.visas, topics = detect(question), parts = [];
    for (const t of topics.slice(0, 3)) {
      if (t === "family") {
        const fam = visas.filter(v => v.type === "family" || v.type === "free");
        parts.push(fam.length ? `Family routes in ${name}: ${fam.map(visaLine).join("; ")}.`
          : `No dedicated family or partner visa is recorded for ${name}. Many work visas let dependants join, but check the official source.`);
      } else if (t === "pr") {
        const pr = visas.filter(v => PR_YES.has(v.pr_route));
        parts.push(pr.length ? `Routes that can lead to permanent residency: ${pr.map(visaLine).join("; ")}.`
          : `None of the recorded ${name} visas lead to permanent residency.`);
      } else if (t === "visa") {
        const ok = visas.filter(v => v.eligibility.status === "eligible");
        if (ok.length) parts.push(`Based on your profile you look eligible for ${ok.length} of ${visas.length} recorded routes: ${ok.slice(0, 4).map(visaLine).join("; ")}.`);
        else if (visas.length) parts.push(`Based on what you entered, you don't clearly qualify for any of the ${visas.length} recorded routes. Check the reasons on each visa card.`);
        else parts.push(`No visa pathways are recorded for ${name}.`);
      } else if (t === "cost") {
        parts.push(`A 1-bed city-centre flat is about ${usd(row.rent_usd_month)}/mo; overall affordability scores ${f2(fv(row, "cost"))}/1.`);
      } else if (t === "salary") {
        parts.push(`The average net salary is roughly ${usd(row.salary_usd_month)}/mo (salary score ${f2(row.average_salary)}/1).`);
      } else {
        parts.push(`${label(t)} scores ${f2(fv(row, t))}/1 in ${name}.`);
      }
    }
    if (!parts.length) {
      const rt = rk ? ` It ranks #${rk} of ${total} for your priorities.` : "";
      parts.push(`I can answer questions about ${name}'s visas, PR routes, family options, costs, salaries, safety, healthcare, English, climate and internet.${rt}`);
    }
    if (topics.some(t => ["family", "pr", "visa"].includes(t))) parts.push("Visa rules change often, so verify with the official immigration portal.");
    return parts.join(" ");
  }


  // ---------------- ml/preferences.py ----------------
  const PREF = { BETA: 6.0, PRIOR_MEAN: 0.5, PRIOR_STRENGTH: 0.5, ITERATIONS: 600, CANDIDATES: 16, DEFAULT_QUESTIONS: 8 };
  const PREF_WORDS = {
    salary: "higher salaries", cost: "cheaper living", pr: "easier PR", job: "stronger job market",
    climate: "warmer", safety: "safer", healthcare: "better healthcare", english: "more English spoken",
    internet: "more people online",
  };
  const sigmoid = (z) => 1 / (1 + Math.exp(-z));
  const dot = (a, b) => { let s = 0; for (let k = 0; k < a.length; k++) s += a[k] * b[k]; return s; };
  const r9 = (x) => Math.round(x * 1e9) / 1e9;

  function prefFit(diffs, outcomes) {
    const n = FACTOR_KEYS.length;
    let w = new Array(n).fill(PREF.PRIOR_MEAN);
    if (!diffs.length) return w;
    let fro = 0;
    for (const d of diffs) for (const v of d) fro += v * v;
    const step = 1 / (PREF.BETA * PREF.BETA * 0.25 * fro + 2 * PREF.PRIOR_STRENGTH);
    for (let it = 0; it < PREF.ITERATIONS; it++) {
      const grad = w.map(v => 2 * PREF.PRIOR_STRENGTH * (v - PREF.PRIOR_MEAN));
      diffs.forEach((d, i) => {
        const r = outcomes[i] - sigmoid(PREF.BETA * dot(d, w));
        for (let k = 0; k < n; k++) grad[k] += -PREF.BETA * d[k] * r;
      });
      w = w.map((v, k) => Math.min(1, Math.max(0, v - step * grad[k])));
    }
    return w;
  }
  function prefSliders(w) {
    const top = Math.max(...w) || 1;
    return Object.fromEntries(FACTOR_KEYS.map((k, i) => [k, Math.round(Math.round(w[i] / top * 20) / 20 * 100) / 100]));
  }
  function prefNext(X, codes, w, asked) {
    const util = X.map(x => dot(x, w));
    const order = codes.map((_, i) => i).sort((a, b) => (r9(util[b]) - r9(util[a])) || cmpStr(codes[a], codes[b]));
    const pool = order.slice(0, PREF.CANDIDATES).sort((a, b) => cmpStr(codes[a], codes[b]));
    let best = null, bestScore = -1;
    for (let x = 0; x < pool.length; x++) for (let y = x + 1; y < pool.length; y++) {
      const i = pool[x], j = pool[y];
      if (asked.has([codes[i], codes[j]].sort().join("|"))) continue;
      const d = X[i].map((v, k) => v - X[j][k]);
      const p = sigmoid(PREF.BETA * dot(d, w));
      const s = r9(p * (1 - p) * dot(d, d));
      if (s > bestScore) { best = [i, j]; bestScore = s; }
    }
    return best;
  }
  const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  function prefDescribe(xa, xb, na, nb, limit = 3) {
    const d = xa.map((v, k) => v - xb[k]);
    const order = d.map((v, k) => k).sort((a, b) => (Math.abs(d[b]) - Math.abs(d[a])) || (a - b));
    const out = [];
    for (const k of order.slice(0, limit)) {
      if (Math.abs(d[k]) < 0.1) break;
      const more = PREF_WORDS[FACTOR_KEYS[k]];
      out.push({ factor: FACTOR_KEYS[k], text: `${more[0].toUpperCase()}${more.slice(1)} in ${d[k] > 0 ? na : nb}`,
                 gap: Math.round(Math.abs(d[k]) * 100) / 100 });
    }
    return out;
  }

  // ---------------- validation.py (subset) ----------------
  function num(v, field) {
    if (typeof v === "boolean") throw new HttpError(400, `'${field}' must be a number`);
    const n = Number(v);
    if (v === null || v === "" || !Number.isFinite(n)) throw new HttpError(400, `'${field}' must be a number`);
    return n;
  }
  function parseWeights(raw) {
    raw = raw || {};
    const out = {};
    for (const k of FACTOR_KEYS) out[k] = Math.min(1, Math.max(0, num(k in raw ? raw[k] : META.default_weights[k], `weights.${k}`)));
    return out;
  }
  function parseRegion(r) {
    if (!r || r === ALL) return ALL;
    if (!META.regions.includes(r)) throw new HttpError(400, `Unknown region '${r}'`);
    return r;
  }
  function money(v, f) {
    if (v === null || v === undefined || v === "") return null;
    const n = num(v, f);
    if (n < 0) throw new HttpError(400, `'${f}' must be ≥ 0`);
    return n;
  }
  function parseProfile(raw) {
    raw = raw || {};
    const nat = raw.nationality ? String(raw.nationality).toUpperCase() : null;
    if (nat && !META.nationalities.some(n => n.code === nat)) throw new HttpError(400, `Unknown nationality '${nat}'`);
    const excl = raw.exclude_countries || [];
    if (!Array.isArray(excl) || excl.length > 250) throw new HttpError(400, "'exclude_countries' must be a list");
    const codes = new Set(D.countries.map(c => c.country_code));
    const byName = Object.fromEntries(META.nationalities.map(n => [n.name.toLowerCase(), n.code]));
    const exclude = [];
    for (const x of excl) {
      const code = (typeof x === "string" && codes.has(x.toUpperCase())) ? x.toUpperCase() : byName[String(x).toLowerCase()];
      if (!codes.has(code)) throw new HttpError(400, `Unknown country in exclude_countries: '${x}'`);
      if (!exclude.includes(code)) exclude.push(code);
    }
    const occ = raw.occupation || null;
    if (occ !== null && !(occ in D.occupations)) throw new HttpError(400, `Unknown occupation '${occ}'`);
    const bounded = (v, f, lo, hi) => {
      if (v === null || v === undefined || v === "") return null;
      const n = num(v, f);
      if (n < lo) throw new HttpError(400, `'${f}' must be ≥ ${lo}`);
      if (n > hi) throw new HttpError(400, `'${f}' must be ≤ ${hi}`);
      return Math.trunc(n);
    };
    const boolish = (v) => (typeof v === "string" ? ["1", "true", "yes", "on"].includes(v.trim().toLowerCase()) : !!v);
    const sc = RULES.scales;
    const pick = (v, f, list) => {
      if (v === null || v === undefined || v === "") return null;
      if (!list.includes(v)) throw new HttpError(400, f === "education" ? `'education' must be one of ${pyList(list)}` : `'${f}' must be a CEFR level ${pyList(list)}`);
      return v;
    };
    const exp = (raw.experience_years === null || raw.experience_years === undefined || raw.experience_years === "") ? null
      : (() => { const n = num(raw.experience_years, "experience_years");
                 if (n < 0) throw new HttpError(400, "'experience_years' must be ≥ 0");
                 if (n > 60) throw new HttpError(400, "'experience_years' must be ≤ 60");
                 return Math.round(n * 10) / 10; })();
    return {
      education: pick(raw.education, "education", sc.education),
      experience_years: exp,
      english: pick(raw.english, "english", sc.cefr),
      german: pick(raw.german, "german", sc.cefr),
      age: bounded(raw.age, "age", 16, 100),
      partner: (raw.partner === null || raw.partner === undefined || raw.partner === "") ? null : boolish(raw.partner),
      children: bounded(raw.children, "children", 0, 12),
      occupation: occ,
      exclude_countries: exclude,
      nationality: nat,
      monthly_income: money(raw.monthly_income, "monthly_income"),
      investment_budget: money(raw.investment_budget, "investment_budget"),
      visa_type: raw.visa_type || "any",
      require_pr: !!raw.require_pr,
      max_difficulty: raw.max_difficulty || null,
      only_qualifying: !!raw.only_qualifying,
      exclude_home: raw.exclude_home === undefined ? true : !!raw.exclude_home,
    };
  }
  function parseCountry(name) {
    if (typeof name !== "string" || !name.trim()) throw new HttpError(400, "'country' is required");
    if (!D.countries.some(c => c.country_name === name)) throw new HttpError(404, `Country '${name}' not found`);
    return name;
  }

  // ---------------- pathways.py ----------------
  const SPONSOR_DISTANCE = 1.0, NEAR_MISS_MAX_DISTANCE = 1.0, NEAR_MISSES = 5, LEVER_STEPS = 3;
  const natNames = () => Object.fromEntries(META.nationalities.map(n => [n.code, n.name]));
  function listText(items, limit = 3) {
    if (items.length <= limit) return items.length === 1 ? items[0] : items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
    return items.slice(0, limit).join(", ") + ` and ${items.length - limit} more`;
  }
  function visaGap(v, p, names) {
    const steps = [], unknown = [];
    let reachable = true;
    const restricted = v.restricted_to;
    if (restricted && restricted.length) {
      if (!p.nationality) unknown.push("passport");
      else if (!restricted.includes(p.nationality)) {
        reachable = false;
        const who = restricted.length <= 3 ? restricted.map(c => names[c] || c).join(", ") : `${restricted.length} listed nationalities`;
        steps.push({ kind: "passport", text: `Only open to citizens of ${who}.` });
      }
    }
    let distance = 0;
    const mi = v.min_income || 0;
    if (mi > 0) {
      if (p.monthly_income == null) unknown.push("income");
      else if (p.monthly_income < mi) {
        const gap = mi - p.monthly_income;
        distance += gap / mi;
        steps.push({ kind: "income", need: mi, gap, text: `Earn ${usd(gap)}/mo more (about ${usd(mi)}/mo in total).` });
      }
    }
    const inv = v.min_investment || 0;
    if (inv > 0) {
      if (p.investment_budget == null) unknown.push("savings");
      else if (p.investment_budget < inv) {
        const gap = inv - p.investment_budget;
        distance += gap / inv;
        steps.push({ kind: "savings", need: inv, gap, text: `Have ${usd(gap)} more to invest (about ${usd(inv)} in total).` });
      }
    }
    if (v.requires_sponsor) {
      distance += SPONSOR_DISTANCE;
      steps.push({ kind: "sponsor", text: "Needs a partner or family member who is a citizen or resident there." });
    }
    if (!steps.length && !unknown.length) return null;
    const hint = { passport: "your passport", income: "your income", savings: "your savings" };
    if (unknown.length) steps.push({ kind: "unknown", text: "Add " + unknown.map(u => hint[u]).join(" and ") + " to check this properly." });
    return { reachable, distance: reachable ? distance : null, steps, unknown };
  }
  const qualCount = (c, p) => visasForProfile(c, p).qualifying_count;
  function pathwaysFor(candidates, p, names) {
    const qual = Object.fromEntries(candidates.map(c => [c, visasForProfile(c, p)]));
    const openNow = candidates.filter(c => qual[c].qualifying_count > 0);
    const openSet = new Set(openNow);
    const near = [];
    for (const c of candidates) {
      if (openSet.has(c)) continue;
      let best = null;
      for (const v of qual[c].visas) {
        if (!matches(v, p)) continue;
        if (v.requires_sponsor && p.visa_type !== "family") continue;
        const gap = visaGap(v, p, names);
        if (!gap || !gap.reachable || gap.unknown.length || gap.distance > NEAR_MISS_MAX_DISTANCE) continue;
        if (gap.distance <= 0) continue;
        if (best === null || gap.distance < best[0]) best = [gap.distance, v, gap];
      }
      if (best) near.push({ country: names[c] || c, country_code: c, visa: best[1].name, type: best[1].type,
                            distance: best[0], steps: best[2].steps.map(s => s.text) });
    }
    near.sort((a, b) => a.distance - b.distance);
    const levers = [];
    const allVisas = candidates.flatMap(c => qual[c].visas.filter(v => matches(v, p)));
    for (const [field, kind, key, unit] of [["monthly_income", "income", "min_income", "/mo"], ["investment_budget", "savings", "min_investment", ""]]) {
      const current = p[field];
      if (current == null) continue;
      const levels = [...new Set(allVisas.map(v => v[key]).filter(x => x && x > current))].sort((a, b) => a - b);
      const seen = new Set();
      for (const level of levels) {
        const opened = candidates.filter(c => !openSet.has(c) && qualCount(c, { ...p, [field]: level }) > 0);
        const fresh = opened.filter(c => !seen.has(c));
        if (!fresh.length) continue;
        const word = kind === "income" ? "Earning" : "Having";
        const what = `${usd(level)}${unit}` + (kind === "savings" ? " to invest" : "");
        const text = `${word} ${what} (+${usd(level - current)}) would ` + (seen.size ? "also " : "")
          + `open ${listText(fresh.map(c => names[c] || c))}` + (seen.size ? ` (${opened.length} new countries in total).` : ".");
        levers.push({ kind, value: level, delta: level - current, count: opened.length, countries: fresh.map(c => names[c] || c), text });
        opened.forEach(c => seen.add(c));
        if (levers.filter(x => x.kind === kind).length >= LEVER_STEPS) break;
      }
    }
    for (const [field, value, lab] of [["require_pr", false, "Allowing routes without permanent residency"],
                                       ["max_difficulty", null, "Allowing harder visas"],
                                       ["visa_type", "any", "Allowing any visa type"]]) {
      const cur = p[field];
      if ([value, null, undefined, "", "any", false].includes(cur)) continue;
      const q = { ...p, [field]: value };
      const opened = candidates.filter(c => !openSet.has(c) && qualCount(c, q) > 0);
      if (opened.length) levers.push({ kind: "filter", field, count: opened.length, countries: opened.map(c => names[c] || c),
                                       text: `${lab} would open ${listText(opened.map(c => names[c] || c))}.` });
    }
    const missing = [["passport", p.nationality], ["income", p.monthly_income], ["savings", p.investment_budget]]
      .filter(([, v]) => v == null || v === "").map(([f]) => f);
    return { open_count: openNow.length, candidate_count: candidates.length, near_misses: near.slice(0, NEAR_MISSES), levers, missing };
  }
  function annotateVisas(visas, p, names) {
    return visas.map(v => ({ ...v, path: v.generated ? null : visaGap(v, p, names) }));
  }

  // ---------------- confidence.py ----------------
  const CONF = { SAMPLES: 400, SEED: 20261116, WEIGHT_SD: 0.12, SQRT3: Math.sqrt(3) };
  const DATA_SD = { "computed": 0.02, "computed-partial": 0.04, "derived": 0.03, "rule": 0.01,
                    "ml-imputed": 0.08, "editorial": 0.08, "editorial-fallback": 0.15,
                    "ml-estimate": 0.08, "regional-median": 0.15 };
  const TRUST = { "computed": 1.0, "computed-partial": 0.85, "derived": 0.9, "rule": 1.0,
                  "ml-imputed": 0.6, "editorial": 0.5, "editorial-fallback": 0.3,
                  "ml-estimate": 0.5, "regional-median": 0.25 };
  const METHOD_LABEL = { "computed": "measured", "computed-partial": "partly measured", "derived": "derived",
    "rule": "rule-based", "ml-imputed": "ML-imputed", "editorial": "an editorial estimate", "editorial-fallback": "a fallback estimate",
    "ml-estimate": "an ML estimate", "regional-median": "a regional median (no data)" };
  function mulberry32(seed, n) {
    const out = new Float64Array(n);
    let a = seed | 0;
    for (let i = 0; i < n; i++) {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      out[i] = ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    return out;
  }
  const provMethod = (code, k) => ((((D.provenance || {})[code] || {})[COL[k]]) || {}).method || "editorial";
  const trustOf = (m) => (TRUST[m] ?? 0.5);
  function reliability(code, weights) {
    let used = Object.fromEntries(FACTOR_KEYS.map(k => [k, Math.max(0, Number(weights[k] || 0))]));
    let total = 0;
    for (const k of FACTOR_KEYS) total = total + used[k];
    if (total === 0) { used = Object.fromEntries(FACTOR_KEYS.map(k => [k, 1])); total = FACTOR_KEYS.length; }
    let value = 0;
    const weak = [];
    for (const k of FACTOR_KEYS) {
      const m = provMethod(code, k);
      value = value + (used[k] / total) * trustOf(m);
      if (trustOf(m) < 0.85 && used[k] > 0)
        weak.push({ factor: k, method: m, share: used[k] / total, text: `${label(k)} is ${METHOD_LABEL[m] || m}` });
    }
    const weakSorted = weak.map((w, i) => [w, i]).sort((a, b) => (b[0].share - a[0].share) || (a[1] - b[1])).map(x => x[0]);
    const level = value >= 0.85 ? "High" : value >= 0.65 ? "Medium" : "Low";
    const measured = FACTOR_KEYS.filter(k => trustOf(provMethod(code, k)) >= 0.85).length;
    return { value, level, measured, factors: FACTOR_KEYS.length, weak: weakSorted.slice(0, 3) };
  }
  const pctText = (p) => `${Math.floor(p * 100 + 0.5)}%`;
  function simulate(rows, weights, topN = 5) {
    const S = CONF.SAMPLES, K = FACTOR_KEYS.length, n = rows.length;
    const show = Math.min(n, topN);
    if (n === 0) return { samples: S, countries: [], verdict: null, ties: [] };
    const baseW = FACTOR_KEYS.map(k => Math.max(0, Math.min(1, Number(weights[k] || 0))));
    const V = rows.map(r => FACTOR_KEYS.map(k => fv(r, k)));
    const SD = rows.map(r => FACTOR_KEYS.map(k => DATA_SD[provMethod(r.country_code, k)] ?? 0.08));
    const block = K + n * K;
    const U = mulberry32(CONF.SEED, S * block);
    const ranks = Array.from({ length: S }, () => new Int32Array(n));
    for (let s = 0; s < S; s++) {
      const off = s * block;
      const W = baseW.map((w, k) => Math.min(1, Math.max(0, w + ((U[off + k] * 2 - 1) * CONF.WEIGHT_SD) * CONF.SQRT3)));
      let total = 0;
      for (let k = 0; k < K; k++) total = total + W[k];
      if (total === 0) { for (let k = 0; k < K; k++) W[k] = 1; total = K; }
      const raw = new Float64Array(n);
      for (let j = 0; j < n; j++) {
        let acc = 0;
        for (let k = 0; k < K; k++) {
          const u = U[off + K + j * K + k];
          const x = Math.min(1, Math.max(0, V[j][k] + ((u * 2 - 1) * SD[j][k]) * CONF.SQRT3));
          acc = acc + (W[k] / total) * x;
        }
        raw[j] = acc;
      }
      const order = Array.from({ length: n }, (_, j) => j).sort((a, b) => (raw[b] - raw[a]) || (a - b));
      order.forEach((j, pos) => { ranks[s][j] = pos + 1; });
    }
    const lo = Math.floor(S / 20), mid = Math.floor(S / 2), hi = S - 1 - Math.floor(S / 20);
    const countries = [];
    for (let j = 0; j < show; j++) {
      const col = ranks.map(r => r[j]);
      const sorted = [...col].sort((a, b) => a - b);
      countries.push({ country: rows[j].country_name, country_code: rows[j].country_code, rank: j + 1,
        p_first: col.filter(x => x === 1).length / S, p_top: col.filter(x => x <= topN).length / S,
        rank_lo: sorted[lo], rank_median: sorted[mid], rank_hi: sorted[hi],
        reliability: reliability(rows[j].country_code, weights) });
    }
    const ties = [];
    for (let j = 0; j < show - 1; j++) {
      const pa = ranks.filter(r => r[j] < r[j + 1]).length / S;
      if (pa >= 0.35 && pa <= 0.65) ties.push({ a: rows[j].country_name, b: rows[j + 1].country_name, rank: j + 1, p_a_ahead: pa });
    }
    const first = countries[0];
    let verdict;
    if (n === 1) verdict = { level: "only", text: `${first.country} is the only country that passes your filters.` };
    else if (first.p_first >= 0.7) verdict = { level: "clear", text: `${first.country} is #1 in ${pctText(first.p_first)} of ${S} what-if scenarios: a clear lead.` };
    else if (first.p_first >= 0.4) verdict = { level: "likely", text: `${first.country} is #1 in ${pctText(first.p_first)} of scenarios: likely, but not certain.` };
    else {
      const rivals = countries.slice(1).map((c, i) => [c, i]).sort((a, b) => (b[0].p_first - a[0].p_first) || (a[1] - b[1]))
        .map(x => x[0]).filter(c => c.p_first >= 0.15).slice(0, 2).map(c => c.country);
      verdict = { level: "close", text: `Too close to call: ${first.country} is #1 in only ${pctText(first.p_first)} of scenarios`
        + (rivals.length ? `, with ${rivals.join(" and ")} close behind.` : ".") };
    }
    return { samples: S, weight_sd: CONF.WEIGHT_SD, countries, verdict, ties };
  }

  // ---------------- refine.py (follow-up conversation) ----------------
  const NUM_WORDS = { two: 2, three: 3, four: 4, five: 5 };
  const DIFFICULTY_STEPS = ["", "Moderate", "Easy"];
  const RV = () => root.RELOC_DATA.lexicon.refine;
  const rnorm = (t) => " " + (t || "").toLowerCase().replace(/’/g, "'").replace(/'/g, "").replace(/[^a-z0-9$€£₹%]+/g, " ").trim() + " ";
  const rhas = (text, phrases) => phrases.some(p => text.includes(` ${p} `));
  function factorNudges(text) {
    const V = RV(), out = {};
    for (const comp of V.comparatives) if (rhas(text, comp.phrases)) out[comp.factor] = comp.dir;
    for (const [f, words] of Object.entries(V.factor_words)) {
      for (const w of words) {
        if (rhas(text, V.more_patterns.map(p => p.replace("{f}", w)))) out[f] = 1;
        if (rhas(text, V.less_patterns.map(p => p.replace("{f}", w)))) out[f] = -1;
        if (rhas(text, V.drop_patterns.map(p => p.replace("{f}", w)))) out[f] = "drop";
      }
    }
    return out;
  }
  function refineState(raw) {
    raw = raw || {};
    let topN = raw.top_n == null || raw.top_n === "" ? 5 : num(raw.top_n, "top_n");
    if (topN !== Math.trunc(topN)) throw new HttpError(400, "'top_n' must be a whole number");
    topN = Math.min(D.countries.length, Math.max(1, topN));
    const p = parseProfile(raw.profile);
    return { weights: parseWeights(raw.weights), region: parseRegion(raw.region), profile: { ...p, exclude_countries: [...p.exclude_countries] }, top_n: topN };
  }
  const rankedNames = (st) => rank(st.weights, st.region, st.profile, null).map(r => r.country_name);
  function refineReply(changes, actions, before, after, outcomeOnly = false) {
    const parts = [];
    if (changes.length) parts.push("Changed: " + changes.map(c => c.label).join("; ") + ".");
    if ((changes.length || outcomeOnly) && after.length) {
      parts.push(before.length && after[0] !== before[0] ? `${after[0]} is now #1 (was ${before[0]}).` : `${after[0]} stays #1.`);
      const newIn = after.filter(c => !before.includes(c)), out = before.filter(c => !after.includes(c));
      if (newIn.length && newIn.length === after.length) parts.push(`Your top ${after.length} is now: ${after.join(", ")}.`);
      else {
        if (newIn.length) parts.push(`New in your top ${after.length}: ${newIn.join(", ")}.`);
        if (out.length) parts.push(`Dropped out: ${out.join(", ")}.`);
      }
    } else if ((changes.length || outcomeOnly) && !after.length) {
      parts.push("No country passes all of that now. Try “any difficulty” or “anywhere”, or say “undo”.");
    }
    for (const a of actions) {
      if (a.type === "open") parts.push(`Opening ${a.country}.`);
      else if (a.type === "compare") parts.push(`Comparing ${a.countries.join(", ")}.`);
    }
    if (!parts.length && outcomeOnly) return "";
    if (!parts.length) return "I didn't catch a change to make. Try “cheaper”, “safer”, “warmer”, “what about Asia?”, “drop Japan”, “easier visas”, “why Portugal?” or “undo”.";
    return parts.join(" ");
  }
  function refineFollowUp(prompt, rawState) {
    const V = RV(), S = root.RelocSearch;
    const text = rnorm(prompt);
    const old = refineState(rawState);
    const nw = JSON.parse(JSON.stringify(old));
    const names = Object.fromEntries(META.nationalities.map(n => [n.code, n.name]));
    const codes = Object.fromEntries(META.nationalities.map(n => [n.name, n.code]));
    const changes = [], actions = [];
    const words = text.trim().split(/\s+/);
    if (rhas(text, V.reset)) { const msg = "Starting over: everything is back to the defaults."; return { state: old, changes: [], actions: [{ type: "reset" }], reply: msg, outcome: msg, visa_hits: [], top: [], previous_top: [] }; }
    if (rhas(text, V.undo) && words.length <= 4) { const msg = "Undone: back to the previous results."; return { state: old, changes: [], actions: [{ type: "undo" }], reply: msg, outcome: msg, visa_hits: [], top: [], previous_top: [] }; }

    const r = S.interpretRules(prompt);
    const nudges = factorNudges(text);
    const explicit = new Set(r.chips.filter(c => ["factor", "learned", "semantic"].includes(c.kind) && "key" in c).map(c => c.key));
    for (const k of FACTOR_KEYS) {
      const before = old.weights[k];
      let after;
      if (nudges[k] === "drop") after = 0.05;
      else if (k in nudges) after = Math.round(Math.min(1, Math.max(0, before + V.step * nudges[k])) * 100) / 100;
      else if (explicit.has(k) && r.weights) after = r.weights[k];
      else continue;
      if (after !== before) {
        nw.weights[k] = after;
        changes.push({ kind: "weight", key: k, icon: k, from: before, to: after, label: `${label(k)} ${before.toFixed(2)} → ${after.toFixed(2)}` });
      }
    }
    if (rhas(text, V.any_region) && old.region !== ALL) { nw.region = ALL; changes.push({ kind: "region", icon: "region", label: "Region: anywhere" }); }
    else if (r.region && r.region !== old.region) { nw.region = r.region; changes.push({ kind: "region", icon: "region", label: `Region: ${r.region}` }); }

    const excl = [...nw.profile.exclude_countries];
    let mentioned = r.countries.filter(n => n in codes).map(n => codes[n]);
    if (rhas(text, V.add_back)) {
      const back = [...new Set(mentioned.concat(r.exclude.filter(n => n in codes).map(n => codes[n])))].filter(c => excl.includes(c));
      for (const c of back) { excl.splice(excl.indexOf(c), 1); changes.push({ kind: "include", icon: "pin", label: `Added back ${names[c]}` }); }
      mentioned = [];
    } else {
      for (const n of r.exclude) { const c = codes[n]; if (c && !excl.includes(c)) { excl.push(c); changes.push({ kind: "exclude", icon: "exclude", label: `Excluding ${n}` }); } }
    }
    nw.profile.exclude_countries = excl;

    const rp = r.profile;
    for (const [key, lab] of [["nationality", "Passport"], ["monthly_income", "Income"], ["investment_budget", "Savings"]]) {
      if (key in rp && rp[key] !== old.profile[key]) {
        nw.profile[key] = rp[key];
        const shown = key === "nationality" ? (names[rp[key]] || rp[key]) : usd(rp[key]);
        changes.push({ kind: "profile", icon: { nationality: "pr", monthly_income: "income", investment_budget: "savings" }[key], label: `${lab}: ${shown}` });
        nw.profile.only_qualifying = true;
      }
    }
    if ("occupation" in rp && rp.occupation !== old.profile.occupation) {
      nw.profile.occupation = rp.occupation;
      changes.push({ kind: "profile", icon: "job", label: `Field: ${S.fieldLabel(rp.occupation)}` });
    }
    if ("age" in rp && rp.age !== old.profile.age) { nw.profile.age = rp.age; changes.push({ kind: "profile", icon: "clock", label: `Age: ${rp.age}` }); }
    let famChanged = false;
    for (const key of ["partner", "children"]) if (key in rp && rp[key] !== old.profile[key]) { nw.profile[key] = rp[key]; famChanged = true; }
    if (famChanged) changes.push({ kind: "profile", icon: "family", label: `Moving with ${S.familyPhrase(nw.profile.partner, nw.profile.children)}` });
    if (rp.visa_type && rp.visa_type !== old.profile.visa_type) { nw.profile.visa_type = rp.visa_type; changes.push({ kind: "filter", icon: "target", label: `Visa type: ${rp.visa_type}` }); }
    if (rp.require_pr && !old.profile.require_pr) { nw.profile.require_pr = true; changes.push({ kind: "filter", icon: "pr", label: "Must lead to permanent residency" }); }
    const diff = old.profile.max_difficulty || "";
    if (rhas(text, V.any_difficulty) && diff) { nw.profile.max_difficulty = null; changes.push({ kind: "filter", icon: "difficulty", label: "Any visa difficulty" }); }
    else if (rp.max_difficulty && rp.max_difficulty !== diff) { nw.profile.max_difficulty = rp.max_difficulty; changes.push({ kind: "filter", icon: "difficulty", label: `Visa difficulty: ${rp.max_difficulty.toLowerCase()} or easier` }); }
    else if (rhas(text, V.easier_visa) && diff !== "Easy") {
      const step = DIFFICULTY_STEPS[DIFFICULTY_STEPS.indexOf(diff) + 1];
      nw.profile.max_difficulty = step;
      changes.push({ kind: "filter", icon: "difficulty", label: `Visa difficulty: ${step.toLowerCase()} or easier` });
    }
    const n = old.top_n;
    const compareTop = text.match(new RegExp(V.compare_top));
    if (compareTop) { /* "compare the top 3" is not "show 3" */ }
    else if (r.top_n && r.top_n !== n) nw.top_n = r.top_n;
    else if (rhas(text, V.show_more)) nw.top_n = Math.min(10, n + 3);
    else if (rhas(text, V.show_fewer)) nw.top_n = Math.max(3, n - 2);
    if (nw.top_n !== n) changes.push({ kind: "top_n", icon: "top", label: `Showing ${nw.top_n} countries` });

    const beforeRank = rankedNames(old), afterRank = rankedNames(nw);
    const topBefore = beforeRank.slice(0, old.top_n), topAfter = afterRank.slice(0, nw.top_n);
    if (compareTop) {
      const k = NUM_WORDS[compareTop[1]] || parseInt(compareTop[1], 10);
      const pick = afterRank.slice(0, Math.max(2, Math.min(3, k)));
      if (pick.length >= 2) actions.push({ type: "compare", countries: pick });
    } else if (mentioned.length >= 2) actions.push({ type: "compare", countries: mentioned.slice(0, 3).map(c => names[c]) });
    else if (mentioned.length === 1) actions.push({ type: "open", country: names[mentioned[0]] });
    if (r.similar_to) actions.push({ type: "open", country: r.similar_to });

    const hits = S.visaSearch(prompt, nw.region === ALL ? null : nw.region, 6, mentioned);
    return { state: nw, changes, actions, visa_hits: hits, reply: refineReply(changes, actions, topBefore, topAfter),
             outcome: refineReply([], actions, topBefore, topAfter, changes.length > 0), top: topAfter, previous_top: topBefore };
  }

  // ---------------- app.py routes ----------------
  function clean(r) { const o = { ...r }; delete o._raw; return o; }
  function common(b) {
    const rawW = "weights" in b ? b.weights : ("salary" in b ? b : null);
    return [parseWeights(rawW), parseRegion(b.region), parseProfile(b.profile)];
  }
  function rowFor(weights, name) { return computeScores(D.countries, weights).find(r => r.country_name === name); }

  function searchResult(b, sem, sims) {
    const S = root.RelocSearch;
    const interp = S.interpretRules(b.prompt, sem);
    const nameToCode = Object.fromEntries(META.nationalities.map(n => [n.name, n.code]));
    let sim = [];
    if (interp.similar_to) {
      const excluded = new Set(interp.exclude || []);
      sim = similar(D.countries, interp.similar_to, 6).map(r => r.country_name).filter(n => !excluded.has(n)).slice(0, 4);
    }
    const th = sem && sem.cfg ? sem.cfg.retrieval_threshold : null;
    const hits = S.visaSearch(b.prompt, interp.region, 6, (interp.countries || []).map(c => nameToCode[c]), sims, th);
    return { interpretation: interp, visa_hits: hits, similar: sim };
  }

  const routes = {
    "/api/score"(b) {
      const [w, region, p] = common(b);
      let topN = b.top_n == null || b.top_n === "" ? 5 : num(b.top_n, "top_n");
      topN = Math.min(D.countries.length, Math.max(1, Math.round(topN)));
      const qual = qualTable(p);
      const ranked = rank(w, region, p, qual);
      const inRegion = rank(w, region, { exclude_home: true, exclude_countries: p.exclude_countries }, null).length;
      return {
        data_version: META.data_version,
        user_insight: userInsight(w),
        top: ranked.slice(0, topN).map(clean),
        all: ranked.map(clean),
        counts: { in_region: inRegion, shown: ranked.length, hidden_by_filters: Math.max(0, inRegion - ranked.length) },
        flip: ranked.length > 1 ? flipTop(w, region, p, qual) : null,
      };
    },
    "/api/insights"(b) {
      const [w, region, p] = common(b);
      const name = parseCountry(b.country);
      const qual = qualTable(p);
      const ranked = rank(w, region, p, qual);
      const rk = rankOf(ranked, name);
      const all = computeScores(D.countries, w);
      const row = all.find(r => r.country_name === name);
      const info = qual[row.country_code];
      return {
        data_version: META.data_version,
        country: { ...clean(row), rank: rk, total: ranked.length, hidden_by_filters: rk == null,
                   provenance: (D.provenance || {})[row.country_code] || {},
                   cluster: (() => { const cm = META.country_map || {}; const e = (cm.countries || {})[row.country_code];
                                     return e ? cm.clusters[e.cluster].name : null; })() },
        explanation: explanation(row, w, rk, ranked.length),
        tradeoffs: tradeoffs(row),
        similar: similar(all, name, 3),
        visas: annotateVisas(info.visas, p, natNames()),
        reliability: reliability(row.country_code, w),
        qualifying_count: info.qualifying_count,
        visas_researched: info.researched,
        citizenship: info.citizenship,
        in_demand: info.in_demand,
        field_in_demand: info.field_in_demand,
        cities: (D.cities[row.country_code] || []).map(c => ({ ...c })),
        is_home: info.is_home,
        official_url: info.official_url,
        what_if: rk ? whatIfCountry(w, region, p, name, qual) : [],
      };
    },
    "/api/confidence"(b) {
      const [w, region, p] = common(b);
      let topN = b.top_n == null || b.top_n === "" ? 5 : num(b.top_n, "top_n");
      topN = Math.min(D.countries.length, Math.max(1, Math.round(topN)));
      return simulate(rank(w, region, p, null).map(clean), w, topN);
    },
    "/api/pathways"(b) {
      const [w, region, p] = common(b);
      const openP = { ...p, only_qualifying: false, visa_type: "any", require_pr: false, max_difficulty: null };
      const candidates = rank(w, region, openP, null).map(r => r.country_code);
      return pathwaysFor(candidates, p, natNames());
    },
    "/api/compare"(b) {
      const [w, region, p] = common(b);
      if (!Array.isArray(b.countries) || !b.countries.length) throw new HttpError(400, "'countries' must be a non-empty list");
      if (b.countries.length > 3) throw new HttpError(400, "Compare at most 3 countries");
      const names = [...new Set(b.countries.map(parseCountry))];
      const qual = qualTable(p);
      const ranked = rank(w, region, p, qual);
      const all = computeScores(D.countries, w);
      const items = names.map(name => {
        const row = all.find(r => r.country_name === name);
        const info = qual[row.country_code];
        const easiest = info.visas.length ? info.visas.reduce((a, v) => (DIFF[v.difficulty] < DIFF[a.difficulty] ? v : a)).name : null;
        return { ...clean(row), rank: rankOf(ranked, name), qualifying_visas: info.qualifying_count,
          total_visas: info.visas.length,
          pr_routes: info.visas.filter(v => v.qualifies && PR_YES.has(v.pr_route)).map(v => v.name),
          easiest_visa: easiest };
      });
      return { factors: FACTOR_KEYS, total: ranked.length, items };
    },
    "/api/preferences"(b) {
      const answers = b.answers || [];
      let total = b.n_questions == null || b.n_questions === "" ? PREF.DEFAULT_QUESTIONS : num(b.n_questions, "top_n");
      total = Math.min(D.countries.length, Math.max(1, Math.round(total)));
      if (!Array.isArray(answers) || answers.length > 30) throw new HttpError(400, "'answers' must be a list of at most 30 items");
      const rows = D.countries;
      const X = rows.map(r => FACTOR_KEYS.map(k => fv(r, k)));
      const codes = rows.map(r => r.country_code);
      const index = Object.fromEntries(rows.map((r, i) => [r.country_name, i]));
      const diffs = [], outcomes = [], asked = new Set();
      for (const a of answers) {
        if (!a || typeof a !== "object" || !(a.a in index) || !(a.b in index) || !["a", "b", "skip"].includes(a.choice))
          throw new HttpError(400, "each answer needs valid 'a', 'b' country names and choice a|b|skip");
        const i = index[a.a], j = index[a.b];
        asked.add([codes[i], codes[j]].sort().join("|"));
        if (a.choice !== "skip") { diffs.push(X[i].map((v, k) => v - X[j][k])); outcomes.push(a.choice === "a" ? 1 : 0); }
      }
      const w = prefFit(diffs, outcomes);
      const weights = prefSliders(w);
      let done = answers.length >= total, question = null;
      const card = (r, x) => ({ name: r.country_name, code: r.country_code, region: r.region, main_city: r.main_city,
        avg_temp_c: r.avg_temp_c, salary_usd_month: r.salary_usd_month, rent_usd_month: r.rent_usd_month,
        values: Object.fromEntries(FACTOR_KEYS.map((k, i) => [k, Math.round(x[i] * 100) / 100])) });
      if (!done) {
        const pair = prefNext(X, codes, w, asked);
        if (!pair) done = true;
        else {
          const [i, j] = pair;
          question = { a: card(rows[i], X[i]), b: card(rows[j], X[j]),
                       differences: prefDescribe(X[i], X[j], rows[i].country_name, rows[j].country_name) };
        }
      }
      let consistency = null;
      if (diffs.length) consistency = roundHalfEven(diffs.filter((d, i) => (dot(d, w) > 0 ? 1 : 0) === outcomes[i]).length / diffs.length * 100) / 100;
      return { done, number: Math.min(answers.length + 1, total), total, question, weights, consistency,
               answered: answers.length, user_insight: userInsight(weights) };
    },
    "/api/search"(b) {
      const S = root.RelocSearch, Sem = root.RelocSemantic;
      if (typeof b.prompt !== "string" || !b.prompt.trim()) throw new HttpError(400, "'prompt' is required");
      if (b.prompt.length > S.MAX_PROMPT) throw new HttpError(400, `'prompt' must be at most ${S.MAX_PROMPT} characters`);
      if (!Sem || !Sem.enabled()) return searchResult(b, null, null);
      // Sentence embeddings: embed the prompt's clauses + the whole query, then run the same logic.
      const clauses = S.semanticClausesFor(b.prompt), query = S.semanticQuery(b.prompt);
      return Sem.embed([...clauses, query || " "])
        .then(vecs => searchResult(b, { cfg: Sem.config(), scores: Sem.conceptScores(clauses, vecs.slice(0, -1)) },
                                   Sem.visaSims(vecs[vecs.length - 1])))
        .catch(err => {
          const out = searchResult(b, null, null);
          out.interpretation.warning = `Meaning-based search couldn't load in this preview (${err.message}); used keywords and rules.`;
          return out;
        });
    },
    "/api/refine"(b) {
      const S = root.RelocSearch;
      if (typeof b.prompt !== "string" || !b.prompt.trim()) throw new HttpError(400, "'prompt' is required");
      if (b.prompt.length > S.MAX_PROMPT) throw new HttpError(400, `'prompt' must be at most ${S.MAX_PROMPT} characters`);
      if (b.state != null && (typeof b.state !== "object" || Array.isArray(b.state))) throw new HttpError(400, "'state' must be an object");
      const out = refineFollowUp(b.prompt, b.state || {});
      const names = Object.fromEntries(META.nationalities.map(n => [n.code, n.name]));
      out.state.profile.exclude_countries = out.state.profile.exclude_countries.map(c => names[c] || c);
      return out;
    },
    "/api/ask"(b) {
      const [w, region, p] = common(b);
      const name = parseCountry(b.country);
      if (typeof b.question !== "string" || !b.question.trim()) throw new HttpError(400, "'question' is required");
      const qual = qualTable(p);
      const ranked = rank(w, region, p, qual);
      const row = rowFor(w, name);
      const q = b.question.trim().slice(0, 500);
      return { answer: answerRules(q, row, qual[row.country_code], rankOf(ranked, name), ranked.length),
               source: "rules", country: name };
    },
  };

  function handle(path, body) {
    const fn = routes[path];
    if (!fn) return { status: 404, json: { error: "Not found" } };
    try {
      if (body !== null && body !== undefined && (typeof body !== "object" || Array.isArray(body)))
        throw new HttpError(400, "Request body must be a JSON object");
      const out = fn(body || {});
      if (out && typeof out.then === "function") return out.then(json => ({ status: 200, json }));
      return { status: 200, json: out };
    } catch (e) {
      if (e instanceof HttpError) return { status: e.status, json: { error: e.message } };
      throw e;
    }
  }

  root.RelocMockAPI = { handle };

  // In the browser, answer the app's fetch("/api/...") calls locally.
  if (typeof window !== "undefined") {
    const realFetch = window.fetch ? window.fetch.bind(window) : null;
    window.fetch = async function (url, opts) {
      const path = typeof url === "string" ? url : url && url.url;
      if (path && path.startsWith("/api/")) {
        let body = {};
        try { body = opts && opts.body ? JSON.parse(opts.body) : {}; } catch { body = null; }
        const { status, json } = await handle(path, body);
        return new Response(JSON.stringify(json), { status, headers: { "Content-Type": "application/json" } });
      }
      return realFetch(url, opts);
    };
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
