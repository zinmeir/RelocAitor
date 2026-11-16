/* =============================================================
   search_port.js — JavaScript port of search.py (rules mode) for the
   standalone preview. Same lexicon (RELOC_DATA.lexicon), same steps:
   money extraction, tokenizing, longest-phrase + fuzzy matching,
   intensity / negation / de-prioritising, country roles, keyword
   search over visas. Kept line-for-line close to the Python so the
   parity test can compare outputs.
   ============================================================= */
(function (root) {
  "use strict";

  const D = root.RELOC_DATA;
  const L = D.lexicon;
  const META = D.meta;

  const W_MENTION = 0.8, W_STRONG = 1.0, W_MILD = 0.5, W_DEPRIO = 0.05, W_OPPOSITE = 0.1, W_UNMENTIONED = 0.25;
  const SEMANTIC = "semantic";
  const SEMANTIC_SKIP = [["not"], ["no"], ["dont"], ["doesnt"], ["isnt"], ["arent"], ["never"], ["avoid"],
                         ["hate"], ["dislike"], ["nothing"], ["zero"]];
  const LEARNED = "learned";   // marker for factors inferred by the trained model
  const LIST_WORDS = new Set(["or", "and", "nor", "either", "neither", "the"]);
  const MAX_PROMPT = 1000;

  // ---------------- text utilities ----------------
  const normalize = (t) => t.replace(/’/g, "'").replace(/‘/g, "'").replace(/'/g, "");
  function stem(w) {
    if (w.length <= 3) return w;
    if (w.endsWith("ies") && w.length - 3 >= 3) return w.slice(0, -3) + "y";
    if (w.endsWith("ing") && w.length - 3 >= 3) return w.slice(0, -3);
    if (w.endsWith("ed") && w.length - 2 >= 3) return w.slice(0, -2);
    if (w.endsWith("es") && w.length - 2 >= 3 && /(s|x|z|ch|sh)es$/.test(w)) return w.slice(0, -2);
    if (w.endsWith("s") && !w.endsWith("ss") && w.length - 1 >= 3) return w.slice(0, -1);
    if (w.endsWith("ly") && w.length - 2 >= 3) return w.slice(0, -2);
    return w;
  }
  const words = (t) => normalize(t).toLowerCase().match(/[a-z0-9]+/g) || [];
  const stems = (t) => words(t).map(stem);
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const eq = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

  function editDistance(a, b, limit = 2) {
    if (Math.abs(a.length - b.length) > limit) return limit + 1;
    let prev2 = null, prev = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i].concat(new Array(b.length).fill(0));
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) cur[j] = Math.min(cur[j], prev2[j - 2] + 1);
      }
      if (Math.min(...cur) > limit) return limit + 1;
      prev2 = prev; prev = cur;
    }
    return prev[prev.length - 1];
  }
  const fuzzyLimit = (n) => (n < 5 ? 0 : n < 8 ? 1 : 2);
  const moneyFmt = (n) => "$" + Math.round(n).toLocaleString("en-US");
  const roundHalfEven = (x) => { const f = Math.floor(x), d = x - f;
    if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1; return Math.round(x); };

  // ---------------- lexicon index ----------------
  const KIND_RANK = { country: 0, intent: 1, factor: 2, region: 3, difficulty: 4, qualify: 5 };
  const IDX = (() => {
    const entries = [];
    const add = (phrase, kind, value, polarity = 1) => {
      const st = stems(phrase);
      if (st.length) entries.push({ stems: st, kind, value, polarity, upper: kind === "country" && phrase === "us", text: phrase });
    };
    for (const [key, spec] of Object.entries(L.factors)) {
      spec.positive.forEach(p => add(p, "factor", key, 1));
      spec.negative.forEach(p => add(p, "factor", key, -1));
    }
    for (const it of L.intents) it.phrases.forEach(p => add(p, "intent", it.id));
    for (const [r, ps] of Object.entries(L.regions)) ps.forEach(p => add(p, "region", r));
    for (const [lvl, ps] of Object.entries(L.difficulty)) ps.forEach(p => add(p, "difficulty", lvl));
    L.qualify.forEach(p => add(p, "qualify", true));
    for (const [code, spec] of Object.entries(L.countries)) {
      spec.aliases.forEach(p => add(p, "country", { code, via: "name" }));
      spec.cities.forEach(p => add(p, "country", { code, via: "city", city: p }));
      spec.demonyms.forEach(p => add(p, "country", { code, via: "demonym" }));
    }
    const index = {};
    for (const e of entries) (index[e.stems[0]] = index[e.stems[0]] || []).push(e);
    for (const k of Object.keys(index))
      index[k].sort((a, b) => (b.stems.length - a.stems.length) || (b.text.length - a.text.length) || (KIND_RANK[a.kind] - KIND_RANK[b.kind]));
    const singles = entries.filter(e => e.stems.length === 1 && e.stems[0].length >= 5)
      .sort((a, b) => (KIND_RANK[a.kind] - KIND_RANK[b.kind]) || cmp(a.text, b.text));
    return { index, singles };
  })();

  const WS = (() => {
    const out = {};
    for (const k of ["strong", "mild", "negators", "deprioritise", "origin_before", "origin_after", "exclude_before",
                     "similar_before", "investment_words", "income_words", "residence_before", "period_month",
                     "period_year", "language_words", "compare_words"]) out[k] = L[k].map(stems);
    out.not_residence = new Set(L.not_residence_before.map(stem));
    out.fillers = new Set(L.fillers.map(stem));
    const fs = new Set();
    for (const k of ["strong", "mild", "negators", "deprioritise", "origin_before", "residence_before", "exclude_before",
                     "similar_before", "origin_after", "compare_words", "language_words", "qualify"])
      for (const p of L[k]) for (const st of stems(p)) fs.add(st);
    out.function_stems = fs;
    out.breakers = new Set(L.clause_breakers.map(stem));
    out.stop = new Set(L.stopwords.map(stem));
    return out;
  })();

  const endsWith = (seq, p) => p.length <= seq.length && eq(seq.slice(seq.length - p.length), p);
  const contains = (seq, p) => { for (let i = 0; i + p.length <= seq.length; i++) if (eq(seq.slice(i, i + p.length), p)) return true; return false; };
  const anyContains = (seq, ps) => ps.some(p => contains(seq, p));

  // ---------------- money ----------------
  const MONEY_RE = /(?<pre>[$€£₹]|\b(?:usd|eur|gbp|pkr|inr|aed|cad|aud|rs\.?)\s?)?(?<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?<mult>k|m|mn|million|thousand|lakh|lac|crore)?\b(?:\s?(?<cur>usd|us dollars|dollars?|bucks|eur|euros?|gbp|pounds?|quid|pkr|rupees?|inr|aed|dirhams?|cad|aud))?/gi;
  const MULT = { k: 1e3, thousand: 1e3, m: 1e6, mn: 1e6, million: 1e6, lakh: 1e5, lac: 1e5, crore: 1e7 };
  const MONEY_LEADS = new Set(["income", "earn", "earning", "earns", "make", "making", "salary", "paid", "pay", "paying", "wage", "wages",
    "invest", "investment", "investing", "savings", "saved", "save", "budget", "capital", "deposit", "have",
    "of", "about", "around", "roughly", "approximately", "approx", "is", "my", "i", "a", "with", "total", "worth",
    "are", "was", "be", "at", "only", "just"].map(stem));
  const INDIA_HINTS = /\b(india|indian|inr|delhi|mumbai|bangalore|bengaluru|hyderabad|chennai|kolkata|pune)\b|₹/i;
  const rupeeRate = (text) => INDIA_HINTS.test(text) ? L.currencies.inr.rate : L.currencies.pkr.rate;
  const TRAIL_RE = /^(\s*(?:salary|income|pension|savings|earnings|in savings|net)\b)/i;

  function currencyRate(token) {
    if (!token) return null;
    const t = token.toLowerCase().trim().replace(/\.+$/, "");
    for (const spec of Object.values(L.currencies))
      for (const w of spec.words)
        if (t === w || t.replace(/s+$/, "") === w.replace(/s+$/, "")) return spec.rate;
    return null;
  }

  function extractMoney(text) {
    const found = [];
    let blanked = text;
    for (const m of text.matchAll(MONEY_RE)) {
      if (m[0] === "") continue;
      const g = m.groups;
      const start = m.index, end = m.index + m[0].length;
      const raw = m[0].trim();
      const num = parseFloat(g.num.replace(/,/g, ""));
      const mult = MULT[(g.mult || "").toLowerCase()] || 1.0;
      let rate = currencyRate(g.pre) || currencyRate(g.cur);
      const curWord = (g.pre || g.cur || "").toLowerCase().trim().replace(/\.+$/, "");
      if ((["lakh", "lac", "crore"].includes((g.mult || "").toLowerCase()) && rate == null) || curWord.startsWith("rupee") || curWord === "rs")
        rate = rupeeRate(text);
      const before = stems(text.slice(Math.max(0, start - 40), start)).slice(-5);
      const afterText = text.slice(end, end + 30).toLowerCase();
      const after = stems(afterText).slice(0, 4);
      const hasMoneyWord = anyContains(before, WS.income_words.concat(WS.investment_words));
      const a2 = after.slice(0, 2);
      if (eq(a2, ["year", "old"]) || eq(a2, ["yr", "old"]) || (after.length && ["country", "option", "place", "result", "choice"].includes(after[0]))) continue;
      if (rate == null && g.mult == null && !hasMoneyWord) continue;
      if (before.length && before[before.length - 1] === "top") continue;
      let amount = num * mult * (rate || 1.0);
      if (amount < 50) continue;
      const slash = afterText.match(/^\s*(?:\/|per|a|an|every|each)?\s*(month|mo|mth|m\b|year|yr|annum|annually|monthly|yearly|pa\b|pm\b)/);
      let period = null;
      if (slash) period = ["year", "yr", "annum", "annually", "yearly", "pa"].includes(slash[1]) ? "year" : "month";
      else if (anyContains(after, WS.period_year)) period = "year";
      else if (anyContains(after, WS.period_month)) period = "month";
      let kind;
      const near = before.slice(-1).concat(after.slice(0, 2));
      if (period) kind = "income";
      else if (anyContains(near, WS.investment_words) && !anyContains(near, WS.income_words)) kind = "investment";
      else if (anyContains(near, WS.income_words) && !anyContains(near, WS.investment_words)) kind = "income";
      else if (anyContains(before.concat(after), WS.investment_words) && !anyContains(before, WS.income_words)) kind = "investment";
      else if (anyContains(before.concat(after), WS.income_words)) kind = "income";
      else kind = amount >= 20000 ? "investment" : "income";
      if (kind === "income" && period === "year") amount /= 12;
      found.push({ amount_usd: roundHalfEven(amount), kind, raw });

      let a = start, b = end;
      if (slash) {
        b += slash[0].length;
        const trail = text.slice(b).match(TRAIL_RE);
        if (trail) b += trail[0].length;
      } else {
        const tail = text.slice(b).match(/^(\s*(?:a|an|per|every|each)?\s*(?:month|monthly|year|yearly|annually|annum)s?\b)/i);
        if (tail) b += tail[0].length;
        const trail = text.slice(b).match(TRAIL_RE);
        if (trail) b += trail[0].length;
      }
      const head = text.slice(0, a).match(/((?:[A-Za-z']+\W+){1,4})$/);
      if (head) {
        const parts = head[1].match(/[A-Za-z']+|\W+/g);
        const cut = head[1].length;
        let consumed = 0;
        for (const tok of parts.reverse()) {
          if (/^\W+$/.test(tok)) { consumed += tok.length; continue; }
          if (MONEY_LEADS.has(stem(normalize(tok).toLowerCase()))) consumed += tok.length;
          else break;
        }
        a -= consumed <= cut ? consumed : cut;
      }
      blanked = blanked.slice(0, a) + " ".repeat(b - a) + blanked.slice(b);
    }
    return [found, blanked];
  }

  function tokenize(text) {
    const out = [];
    let clause = 0;
    for (const part of normalize(text).split(/[.,;!?\n]+/)) {
      clause += 1;
      for (const raw of part.match(/[A-Za-z0-9]+/g) || []) {
        const w = raw.toLowerCase(), s = stem(w);
        if (WS.breakers.has(s) && !(out.length && ["anywhere", "anything", "everywhere", "all"].includes(out[out.length - 1].s))) clause += 1;
        out.push({ w, s, upper: raw.length > 1 && raw === raw.toUpperCase() && raw !== raw.toLowerCase(), clause });
      }
    }
    return out;
  }

  // ---------------- matching ----------------
  function matchConcepts(tokens) {
    const matches = [];
    let i = 0;
    while (i < tokens.length) {
      const t = tokens[i];
      let best = null;
      for (const e of IDX.index[t.s] || []) {
        const n = e.stems.length, span = tokens.slice(i, i + n);
        if (span.length === n && eq(span.map(x => x.s), e.stems) && span.every(x => x.clause === t.clause) && (!e.upper || t.upper)) { best = e; break; }
      }
      let fuzzy = false;
      if (!best && t.s.length >= 5 && !WS.stop.has(t.s) && !WS.function_stems.has(t.s) && !/^\d+$/.test(t.s)) {
        const lim = fuzzyLimit(t.s.length);
        let bestD = null;
        for (const e of IDX.singles) {
          if (Math.abs(e.stems[0].length - t.s.length) > lim) continue;
          const d = editDistance(t.s, e.stems[0], lim);
          if (d <= lim && (bestD === null || d < bestD)) { bestD = d; best = e; }
        }
        if (best) fuzzy = true;
      }
      if (best) {
        const n = best.stems.length;
        matches.push({ entry: best, start: i, end: i + n, clause: t.clause, fuzzy, said: tokens.slice(i, i + n).map(x => x.w).join(" ") });
        i += n;
      } else i += 1;
    }
    return matches;
  }

  function windowOf(tokens, start, end, clause, taken, before = 3, after = 3) {
    const b = [], a = [];
    for (let k = Math.max(0, start - before); k < start; k++) if (tokens[k].clause === clause && !taken.has(k)) b.push(tokens[k].s);
    for (let k = end; k < Math.min(tokens.length, end + after); k++) if (tokens[k].clause === clause && !taken.has(k)) a.push(tokens[k].s);
    return [b, a];
  }

  function cueEnd(b, phrases, fillers) {
    for (const p of phrases) {
      if (endsWith(b, p)) return [p, b.length - p.length];
      if (b.length && fillers.has(b[b.length - 1]) && endsWith(b.slice(0, -1), p)) return [p, b.length - 1 - p.length];
    }
    return null;
  }

  function countryRole(before, after, via) {
    if (anyContains(before, WS.exclude_before) && !cueEnd(before, WS.origin_before, WS.fillers)) return "exclude";
    const sim = cueEnd(before, WS.similar_before, WS.fillers);
    if (sim) {
      const [cue, k] = sim;
      if (!(eq(cue, ["like"]) && k > 0 && ["i", "id", "would", "we", "realy"].includes(before[k - 1]))) return "similar";
    }
    if (cueEnd(before, WS.origin_before, WS.fillers) || via === "demonym" || WS.origin_after.some(p => eq(after.slice(0, p.length), p))) return "origin";
    const res = cueEnd(before, WS.residence_before, WS.fillers);
    if (res) {
      const [, k] = res;
      if (!(k > 0 && WS.not_residence.has(before[k - 1]))) return "residence";
    }
    return "destination";
  }

  // ---------------- interpretation ----------------
  const SUMMARY_NAMES = { salary: "high salaries", cost: "low living costs", pr: "an easy path to PR",
    job: "a strong job market", climate: "good weather", safety: "safety", healthcare: "great healthcare",
    english: "English being widely spoken", internet: "fast internet" };
  const VISA_NAMES = { skilled: "skilled-worker visas", nomad: "digital-nomad visas", investor: "investor visas",
    study: "study visas", startup: "startup visas", family: "family/partner visas", passive: "passive-income and retirement visas" };

  function summarize(weights, profile, region, explicitKeys) {
    const keys = explicitKeys.filter(k => weights && (weights[k] || 0) >= W_MENTION).slice(0, 4);
    const parts = [];
    if (keys.length) {
      const names = keys.map(k => SUMMARY_NAMES[k]);
      parts.push("Looking for " + (names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names[names.length - 1] : names[0]));
    }
    if (profile.visa_type) parts.push((parts.length ? "with " : "Looking for ") + VISA_NAMES[profile.visa_type]);
    if (region) parts.push(parts.length ? `in ${region}` : `Looking in ${region}`);
    if (profile.require_pr && !keys.includes("pr")) parts.push("with a route to permanent residency");
    return parts.length ? parts.join(" ") + "." : "";
  }

  // ---------------- trained prompt classifier (port of ml/prompt_model.py) ----------------
  let PM = null;
  function promptModel() {
    if (PM === null) {
      const m = D.prompt_model || null;
      if (m) m.index = new Map(m.vocab.map((f, i) => [f, i]));
      PM = m || false;
    }
    return PM || null;
  }
  const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  function featurize(text) {
    const t = (text || "").replace(/’/g, "'").replace(/'/g, "").toLowerCase();
    const words = t.match(/[a-z0-9]+/g) || [];
    const stems = words.map(stem);
    const feats = new Map();
    const add = (f) => feats.set(f, (feats.get(f) || 0) + 1);
    for (const s of stems) add("w:" + s);
    for (let i = 0; i + 1 < stems.length; i++) add("b:" + stems[i] + "_" + stems[i + 1]);
    for (const w of words) {
      if (w.length < 3) continue;
      const padded = " " + w + " ";
      for (const n of [3, 4]) for (let i = 0; i + n <= padded.length; i++) add("c:" + padded.slice(i, i + n));
    }
    return feats;
  }
  function vectorize(feats, index, idf) {
    const vec = new Map();
    for (const f of [...feats.keys()].sort(cmpStr)) {
      const i = index.get(f);
      if (i !== undefined) vec.set(i, (1 + Math.log(feats.get(f))) * idf[i]);
    }
    let sq = 0;
    for (const v of vec.values()) sq += v * v;
    const norm = Math.sqrt(sq);
    if (norm > 0) for (const [i, v] of vec) vec.set(i, v / norm);
    return vec;
  }
  function linear(vec, weights, bias) {
    let z = bias;
    for (const i of [...vec.keys()].sort((a, b) => a - b)) {
      const w = weights[String(i)];
      if (w !== undefined) z += vec.get(i) * w;
    }
    return z;
  }
  function modelPredict(text) {
    const m = promptModel();
    if (!m) return null;
    const vec = vectorize(featurize(text), m.index, m.idf);
    const factors = {};
    for (const [key, head] of Object.entries(m.factors || {})) factors[key] = 1 / (1 + Math.exp(-linear(vec, head.w, head.b)));
    const logits = Object.fromEntries(Object.entries(m.visa).map(([c, h]) => [c, linear(vec, h.w, h.b)]));
    const mx = Math.max(...Object.values(logits));
    const exps = Object.fromEntries(Object.entries(logits).map(([c, v]) => [c, Math.exp(v - mx)]));
    let total = 0;
    for (const e of Object.values(exps)) total += e;
    const th = m.thresholds || {};
    return { factors, visa: Object.fromEntries(Object.entries(exps).map(([c, e]) => [c, e / total])),
             thresholds: { factor: th.factor ?? null, visa: th.visa ?? null } };
  }
  const pct = (x) => (x * 100).toFixed(0) + "%";

  // ---------------- sentence embeddings (search.semantic_clauses) ----------------
  function semanticClauses(tokens) {
    const byClause = new Map();
    for (const t of tokens) { if (!byClause.has(t.clause)) byClause.set(t.clause, []); byClause.get(t.clause).push(t); }
    const skip = SEMANTIC_SKIP.map(p => p.map(stem));
    const out = [];
    for (const [cid, toks] of byClause) {
      const st = toks.map(t => t.s);
      if (anyContains(st, skip) || anyContains(st, WS.deprioritise)) continue;
      const content = st.filter(x => !WS.stop.has(x) && !WS.function_stems.has(x) && !/^\d+$/.test(x));
      if (content.length >= 2) out.push([cid, toks.map(t => t.w).join(" ")]);
    }
    return out.slice(0, 8);
  }
  const semanticClausesFor = (prompt) => semanticClauses(tokenize(extractMoney((prompt || "").slice(0, MAX_PROMPT))[1])).map(([, c]) => c);
  const semanticQuery = (prompt) => extractMoney(prompt || "")[1].replace(/\btop\s+\d{1,2}\b/gi, " ").trim();

  // sem (optional): { cfg, scores: Map(clause text → {"factor|safety": [similarity, prototype], …}) }
  // ---------------- about the person (search.py extract_personal) ----------------
  // Same pattern strings as search.py (lexicon "personal" section).
  const PP = L.personal;
  const NUM_WORDS_P = PP.number_words;
  const CUE_ONLY = new Set(PP.cue_only_jobs);
  const JOB_CUE_RE = new RegExp(PP.job_cue);
  const PARTNER_RE = new RegExp(PP.partner);
  const SINGLE_RE = new RegExp(PP.single);
  const KIDS_RE = new RegExp(PP.children);
  const NO_KIDS_RE = new RegExp(PP.no_children);
  const AGE_RE = new RegExp(PP.age, "g");
  const reEscape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const OCC = D.occupations;
  const fieldLabel = (k) => (OCC[k] && OCC[k].label) || k;
  const JOB_PHRASES = Object.entries(OCC).flatMap(([k, v]) => v.phrases.map(p => [p, k]))
    .sort((a, b) => (b[0].length - a[0].length) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));

  function familyPhrase(partner, children, unsure = false) {
    const parts = [];
    if (partner) parts.push("your partner");
    if (children) parts.push(unsure ? "children" : children === 1 ? "1 child" : `${children} children`);
    return parts.join(" and ") || "nobody else";
  }

  function extractPersonal(prompt) {
    const text = " " + (prompt || "").toLowerCase().replace(/’/g, "'").replace(/\s+/g, " ") + " ";
    const out = { occupation: null, occupation_said: null, age: null, age_said: null, partner: null, children: null, family_said: null };
    let best = null;
    for (const [phrase, field] of JOB_PHRASES) {
      const re = new RegExp("(?<![a-z])" + reEscape(phrase) + "(?:s|es)?(?![a-z])", "g");
      let m;
      while ((m = re.exec(text)) !== null) {
        if (CUE_ONLY.has(phrase) && !JOB_CUE_RE.test(text.slice(Math.max(0, m.index - 24), m.index))) continue;
        const cand = [m.index, -phrase.length, phrase, field];
        const less = (a, b) => { for (let i = 0; i < 4; i++) { if (a[i] < b[i]) return true; if (a[i] > b[i]) return false; } return false; };
        if (best === null || less(cand, best)) best = cand;
        break;
      }
    }
    if (best) { out.occupation = best[3]; out.occupation_said = best[2]; }
    AGE_RE.lastIndex = 0;
    let am;
    while ((am = AGE_RE.exec(text)) !== null) {
      const age = parseInt(am[1] || am[2] || am[3], 10);
      if (age >= PP.age_range[0] && age <= PP.age_range[1]) { out.age = age; out.age_said = am[0].trim(); break; }
    }
    const said = [];
    const pm = text.match(PARTNER_RE);
    if (pm) { out.partner = true; said.push(pm[0].trim()); }
    else if (SINGLE_RE.test(text)) out.partner = false;
    if (NO_KIDS_RE.test(text)) out.children = 0;
    else {
      const km = text.match(KIDS_RE);
      if (km) {
        out.children = km[1] ? (NUM_WORDS_P[km[1]] ?? 1) : 1;
        out.children_unsure = !km[1] && (km[3] === "kids" || km[3] === "children");
        said.push(km[0].trim());
      }
    }
    out.family_said = said.join(", ") || null;
    return out;
  }
  const titleCase = (s) => s.toLowerCase().replace(/(^|[^\p{L}])(\p{L})/gu, (m, a, b) => a + b.toUpperCase());

  function interpretRules(prompt, sem = null) {
    const factorLabels = Object.fromEntries(Object.entries(META.factors).map(([k, v]) => [k, v.label]));
    const names = Object.fromEntries(META.nationalities.map(n => [n.code, n.name]));
    const destinations = new Set(META.country_codes);

    prompt = (prompt || "").slice(0, MAX_PROMPT);
    const [money, rest] = extractMoney(prompt);
    const tokens = tokenize(rest);
    const matches = matchConcepts(tokens);
    const taken = new Set();
    for (const m of matches) for (let k = m.start; k < m.end; k++) taken.add(k);

    const chips = [], fuzzyNotes = [], intents = [];
    const explicit = new Map();
    let region = null, difficulty = null, qualify = false, origin = null;
    const dests = [], similar = [], exclude = [];
    const citySaid = {};
    const negatedVisas = new Set();

    const factorStarts = new Set(matches.filter(m => m.entry.kind === "factor").map(m => m.start));
    const last = {};
    const continuesList = (kind, m) => {
      const prev = last[kind];
      if (!prev || prev[1] !== m.clause) return null;
      const between = [];
      for (let k = prev[0]; k < m.start; k++) between.push(tokens[k].s);
      return between.length && between.every(w => LIST_WORDS.has(w)) ? prev[2] : null;
    };

    for (const m of matches) {
      const e = m.entry, cl = m.clause;
      const [before, after] = windowOf(tokens, m.start, m.end, cl, taken);
      const [b4, a4] = windowOf(tokens, m.start, m.end, cl, taken, 4, 4);
      const negated = anyContains(before.slice(-2), WS.negators) || anyContains(before, [["not"], ["no"], ["dont"]]);
      if (m.fuzzy) fuzzyNotes.push(`“${m.said}” → ${e.text}`);

      if (e.kind === "factor") {
        const key = e.value;
        let w, how;
        if (anyContains(b4.concat(["|"], a4), WS.deprioritise) || continuesList("factor", m) === W_DEPRIO) { w = W_DEPRIO; how = "not important"; }
        else {
          const pol = e.polarity * ((negated && e.polarity < 0) ? -1 : 1);
          if (pol < 0) { w = W_OPPOSITE; how = `you prefer the opposite (${m.said})`; }
          else if (anyContains(before.concat(after), WS.strong)) { w = W_STRONG; how = "very important"; }
          else if (anyContains(before.concat(after), WS.mild)) { w = W_MILD; how = "nice to have"; }
          else { w = W_MENTION; how = "important"; }
        }
        const prev = explicit.get(key);
        if (prev === undefined || (w > prev[0] && prev[0] !== W_DEPRIO) || w === W_DEPRIO) explicit.set(key, [w, how, m.said]);
        last.factor = [m.end, cl, w];
      } else if (e.kind === "intent") {
        if (negated) { negatedVisas.add(L.intents.find(x => x.id === e.value).visa_type ?? null); continue; }
        if (!intents.some(x => x.id === e.value)) intents.push({ ...L.intents.find(x => x.id === e.value), said: m.said });
      } else if (e.kind === "region") {
        if (!negated && region === null) region = [e.value, m.said];
      } else if (e.kind === "difficulty") {
        difficulty = difficulty || e.value;
      } else if (e.kind === "qualify") {
        qualify = true;
      } else if (e.kind === "country") {
        const { code, via } = e.value;
        const nearLang = anyContains(before.slice(-2).concat(after.slice(0, 1)), WS.language_words);
        if (via === "demonym" && nearLang) continue;
        let role = countryRole(before, after, via);
        if (via === "demonym" && factorStarts.has(m.end) && tokens[m.end].clause === cl) role = "destination";
        if (role === "destination" && ["exclude", "similar"].includes(continuesList("country", m))) role = continuesList("country", m);
        last.country = [m.end, cl, role];
        if (role === "exclude") exclude.push(code);
        else if (role === "similar") similar.push(code);
        else if (role === "origin" || role === "residence") {
          const cand = [(via === "demonym" || role === "origin") ? 3 : 1, code, m.said];
          if (origin === null || cand[0] > origin[0]) origin = cand;
        } else if (destinations.has(code)) {
          if (!dests.includes(code)) dests.push(code);
          if (via === "city" && !(code in citySaid)) citySaid[code] = e.value.city;
        }
      }
    }

    // ---------- trained model fills the gaps ----------
    const learnedProb = {};
    let learnedVisa = null;
    const pred = modelPredict(rest);
    if (pred && pred.thresholds.factor !== null) {
      for (const k of Object.keys(factorLabels)) {
        const prob = pred.factors[k] ?? 0;
        if (!explicit.has(k) && prob >= pred.thresholds.factor) { explicit.set(k, [W_MENTION, "important", LEARNED]); learnedProb[k] = prob; }
      }
    }
    if (pred && pred.thresholds.visa !== null && !intents.some(i => i.visa_type)) {
      let cls = null;
      for (const c of Object.keys(pred.visa))
        if (cls === null || pred.visa[c] > pred.visa[cls] || (pred.visa[c] === pred.visa[cls] && c > cls)) cls = c;
      if (cls !== "none" && pred.visa[cls] >= pred.thresholds.visa && !negatedVisas.has(cls)) learnedVisa = [cls, pred.visa[cls]];
    }

    // ---------- sentence embeddings fill what is still missing ----------
    const semanticProb = {};
    let semanticVisa = null;
    const usedClauses = new Set();
    if (sem && sem.cfg) {
      const fth = sem.cfg.factor_threshold, vth = sem.cfg.visa_type_threshold;
      for (const [cid, clause] of semanticClauses(tokens)) {
        const best = sem.scores.get(clause);
        if (!best) continue;
        const entries = Object.entries(best).map(([key, [sim, proto]]) => { const [kind, k] = key.split("|"); return { kind, k, sim, proto }; });
        if (fth != null) {
          const cands = entries.filter(e => e.kind === "factor" && e.sim >= fth).sort((a, b) => (b.sim - a.sim) || cmp(a.k, b.k));
          for (const e of cands.slice(0, sem.cfg.max_factors_per_clause ?? 2)) {
            if (explicit.has(e.k) && explicit.get(e.k)[2] !== SEMANTIC) continue;
            if (!(e.k in semanticProb) || e.sim > semanticProb[e.k][0]) {
              semanticProb[e.k] = [e.sim, clause, e.proto];
              explicit.set(e.k, [W_MENTION, "important", SEMANTIC]);
            }
            usedClauses.add(cid);
          }
        }
        if (vth != null && !learnedVisa && !intents.some(i => i.visa_type)) {
          const vs = entries.filter(e => e.kind === "visa_type" && e.sim >= vth && !negatedVisas.has(e.k)).sort((a, b) => (b.sim - a.sim) || cmp(a.k, b.k));
          if (vs.length && (semanticVisa === null || vs[0].sim > semanticVisa[1])) { semanticVisa = [vs[0].k, vs[0].sim, clause, vs[0].proto]; usedClauses.add(cid); }
        }
      }
    }

    let weights = null;
    if (explicit.size || intents.some(i => Object.keys(i.boosts).length)) {
      weights = Object.fromEntries(Object.keys(factorLabels).map(k => [k, W_UNMENTIONED]));
      for (const it of intents) for (const [k, v] of Object.entries(it.boosts)) weights[k] = v;
      for (const [k, [w]] of explicit) weights[k] = w;
      for (const k of Object.keys(weights)) weights[k] = Math.round(weights[k] * 100) / 100;
    }
    const explicitSorted = [...explicit.entries()].sort((a, b) => b[1][0] - a[1][0]);
    for (const [k, [w, how, said]] of explicitSorted) {
      if (said === SEMANTIC) {
        const [sim, clause, proto] = semanticProb[k];
        chips.push({ kind: "semantic", key: k, icon: "semantic", label: `${factorLabels[k]}: important`, detail: `meaning match ${sim.toFixed(2)}: “${clause}” ≈ “${proto}”` });
      } else if (said === LEARNED)
        chips.push({ kind: "learned", key: k, icon: "learned", label: `${factorLabels[k]}: important`, detail: `inferred by the trained model (confidence ${pct(learnedProb[k])})` });
      else
        chips.push({ kind: "factor", key: k, icon: k, label: `${factorLabels[k]}: ${how}`, detail: `weight ${w.toFixed(2)} (from “${said}”)` });
    }

    const profile = {};
    const visaIntent = intents.find(i => i.visa_type);
    if (visaIntent) profile.visa_type = visaIntent.visa_type;
    if (learnedVisa) {
      profile.visa_type = learnedVisa[0];
      const label = L.intents.find(i => i.visa_type === learnedVisa[0]).label;
      chips.push({ kind: "learned", icon: "learned", label, detail: `inferred by the trained model (confidence ${pct(learnedVisa[1])}) → ${learnedVisa[0]} visas` });
    }
    if (semanticVisa && !learnedVisa && !("visa_type" in profile)) {
      profile.visa_type = semanticVisa[0];
      const label = L.intents.find(i => i.visa_type === semanticVisa[0]).label;
      chips.push({ kind: "semantic", icon: "semantic", label, detail: `meaning match ${semanticVisa[1].toFixed(2)}: “${semanticVisa[2]}” ≈ “${semanticVisa[3]}” → ${semanticVisa[0]} visas` });
    }
    for (const it of intents) {
      chips.push({ kind: "intent", icon: "target", label: it.label,
        detail: `from “${it.said}”` + ((it.visa_type === profile.visa_type && it.visa_type) ? ` → ${it.visa_type} visas` : "") });
      if (it.require_pr) profile.require_pr = true;
    }
    let pr = explicit.get("pr");
    if (pr && (pr[2] === LEARNED || pr[2] === SEMANTIC)) pr = undefined;   // a model guess never sets a hard filter
    if (pr && pr[0] >= W_MENTION) profile.require_pr = true;
    else if (pr && pr[0] <= W_OPPOSITE) profile.require_pr = false;
    if (profile.require_pr) chips.push({ kind: "filter", icon: "pr", label: "Must lead to permanent residency" });
    if (difficulty) {
      profile.max_difficulty = difficulty;
      chips.push({ kind: "filter", icon: "difficulty", label: `Visa difficulty: ${difficulty.toLowerCase()} or easier` });
    }
    if (origin) {
      profile.nationality = origin[1];
      const assumed = origin[0] === 1 ? " (assumed from where you live)" : "";
      chips.push({ kind: "profile", icon: "pr", label: `Passport: ${names[origin[1]] || origin[1]}${assumed}`, detail: `from “${origin[2]}”` });
    }
    for (const mny of money) {
      if (mny.kind === "income" && !("monthly_income" in profile)) {
        profile.monthly_income = mny.amount_usd;
        chips.push({ kind: "profile", icon: "income", label: `Income: ${moneyFmt(mny.amount_usd)}/mo`, detail: `from “${mny.raw}”` });
      } else if (mny.kind === "investment" && !("investment_budget" in profile)) {
        profile.investment_budget = mny.amount_usd;
        chips.push({ kind: "profile", icon: "savings", label: `Savings to invest: ${moneyFmt(mny.amount_usd)}`, detail: `from “${mny.raw}”` });
      }
    }
    const me = extractPersonal(prompt);
    if (me.occupation) {
      profile.occupation = me.occupation;
      chips.push({ kind: "profile", icon: "job", label: `Field: ${fieldLabel(me.occupation)}`, detail: `from “${me.occupation_said}”` });
    }
    if (me.age !== null) {
      profile.age = me.age;
      chips.push({ kind: "profile", icon: "clock", label: `Age: ${me.age}`, detail: `from “${me.age_said}”` });
    }
    if (me.partner !== null) profile.partner = me.partner;
    if (me.children !== null) profile.children = me.children;
    if (me.partner || me.children)
      chips.push({ kind: "profile", icon: "family", label: "Moving with " + familyPhrase(me.partner, me.children, me.children_unsure), detail: `from “${me.family_said}”` });

    if (qualify || "nationality" in profile || "monthly_income" in profile || "investment_budget" in profile) {
      profile.only_qualifying = true;
      chips.push({ kind: "filter", icon: "check", label: "Only countries with a visa you likely qualify for" });
    }
    if (region) chips.push({ kind: "region", icon: "region", label: `Region: ${region[0]}`, detail: `from “${region[1]}”` });

    const excl = [...new Set(exclude)].filter(c => destinations.has(c));
    const sim = [...new Set(similar)].filter(c => destinations.has(c));
    const dst = dests.filter(c => !excl.includes(c) && !sim.includes(c) && c !== profile.nationality);
    for (const c of excl) chips.push({ kind: "exclude", icon: "exclude", label: `Excluding ${names[c]}` });
    if (sim.length) chips.push({ kind: "similar", icon: "similar", label: `Similar to ${names[sim[0]]}` });
    let city = null;
    if (dst.length === 1) {
      city = citySaid[dst[0]] || null;
      chips.push({ kind: "country", icon: "pin", label: `Looking at ${city ? titleCase(city) + ", " + names[dst[0]] : names[dst[0]]}` });
    }
    else if (dst.length > 1) chips.push({ kind: "country", icon: "compare", label: "Comparing " + dst.slice(0, 3).map(c => names[c]).join(", ") });

    let top_n = null;
    const tm = prompt.toLowerCase().match(/\btop\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:countries|options|places|choices|results|destinations)\b/);
    if (tm) top_n = Math.max(3, Math.min(10, parseInt(tm[1] || tm[2], 10)));

    if (top_n) chips.push({ kind: "filter", icon: "top", label: `Showing your top ${top_n}` });

    const personalWords = new Set(([me.occupation_said, me.age_said, me.family_said].filter(Boolean).join(" ").replace(/'/g, "").match(/[a-z0-9]+/g)) || []);
    const stopLong = [...WS.stop].filter(sw => sw.length >= 5);
    const content = tokens.filter((t, k) => !taken.has(k) && !usedClauses.has(t.clause) && !WS.stop.has(t.s) && !WS.function_stems.has(t.s) && !WS.breakers.has(t.s)
      && !/^\d+$/.test(t.s) && t.w.length > 2 && !stopLong.some(sw => editDistance(t.s, sw, 1) <= 1));
    return {
      source: "rules",
      understood: chips.length > 0,
      weights,
      region: region ? region[0] : null,
      profile,
      exclude: excl.map(c => names[c]),
      countries: dst.slice(0, 3).map(c => names[c]),
      city: city ? titleCase(city) : null,
      similar_to: sim.length ? names[sim[0]] : null,
      top_n,
      chips,
      fuzzy: fuzzyNotes,
      unmatched: [...new Set(content.map(t => t.w).filter(w => !personalWords.has(w)))].slice(0, 8),
      summary: summarize(weights, profile, region ? region[0] : null, explicitSorted.map(([k]) => k)),
    };
  }

  // ---------------- keyword search ----------------
  const VINDEX = (() => {
    const typeLabels = Object.fromEntries(META.visa_types.map(v => [v.key, v.label]));
    const byCode = Object.fromEntries(D.countries.map(c => [c.country_code, c]));
    const docs = [];
    for (const [code, entry] of Object.entries(D.visas)) {
      for (const v of entry.visas) {
        docs.push({ code, country: byCode[code].country_name, region: byCode[code].region, visa: v,
          fields: [[3.0, new Set(stems(v.name))], [2.0, new Set(stems((typeLabels[v.type] || v.type) + " " + v.type))],
                   [1.5, new Set(stems(byCode[code].country_name))], [1.0, new Set(stems(v.summary))]] });
      }
    }
    const df = {};
    for (const d of docs) for (const s of new Set([...d.fields[0][1], ...d.fields[1][1]])) df[s] = (df[s] || 0) + 1;
    const n = docs.length, idf = {};
    for (const [s, c] of Object.entries(df)) idf[s] = Math.log(1 + (n - c + 0.5) / (c + 0.5));
    return { docs, idf, maxIdf: Math.log(1 + (n + 0.5) / 0.5) };
  })();

  const FACTOR_WORDS = new Set();
  for (const lst of Object.values(IDX.index)) for (const e of lst) if (e.kind === "factor" && e.stems.length === 1) FACTOR_WORDS.add(e.stems[0]);

  function tokScore(q, field) {
    if (field.has(q)) return 1.0;
    let best = 0;
    for (const t of field) {
      if (q.length >= 4 && t.length >= 4 && (t.startsWith(q) || q.startsWith(t))) best = Math.max(best, 0.8);
      else if (q.length >= 5 && editDistance(q, t, fuzzyLimit(q.length)) <= fuzzyLimit(q.length)) best = Math.max(best, 0.7);
    }
    return best;
  }

  function keywordQuery(prompt) {
    let [, rest] = extractMoney(prompt || "");
    rest = rest.replace(/\btop\s+\d{1,2}\b/gi, " ");
    const tokens = tokenize(rest);
    const drop = new Set();
    for (const m of matchConcepts(tokens)) {
      if (m.entry.kind !== "intent") { for (let k = m.start; k < m.end; k++) drop.add(k); continue; }
      const spec = L.intents.find(x => x.id === m.entry.value);
      const prev = [];
      for (let k = Math.max(0, m.start - 2); k < m.start; k++) prev.push(tokens[k].s);
      if (!spec.visa_type || prev.some(w => ["not", "no", "dont"].includes(w))) { for (let k = m.start; k < m.end; k++) drop.add(k); }
      else for (let k = m.start; k < m.end; k++) if (FACTOR_WORDS.has(tokens[k].s)) drop.add(k);
    }
    const q = tokens.filter((t, k) => !drop.has(k) && !WS.stop.has(t.s) && !WS.function_stems.has(t.s) && !/^\d+$/.test(t.s) && t.s.length > 1).map(t => t.s);
    return [...new Set(q)];
  }

  function keywordSearch(prompt, region = null, limit = 6, countries = null) {
    const q = keywordQuery(prompt);
    if (!q.length) return [];
    const only = new Set(countries || []);
    const hits = [];
    for (const d of VINDEX.docs) {
      if (region && d.region !== region) continue;
      if (only.size && !only.has(d.code)) continue;
      let score = 0, nameHit = false;
      for (const s of q) {
        let best = 0;
        d.fields.forEach(([w, field], i) => {
          const ts = tokScore(s, field);
          if (ts && i < 2) nameHit = true;
          best = Math.max(best, w * ts);
        });
        score += best * (s in VINDEX.idf ? VINDEX.idf[s] : VINDEX.maxIdf);
      }
      if (nameHit && score > 0) hits.push([score, d]);
    }
    if (!hits.length) return [];
    hits.sort((a, b) => (b[0] - a[0]) || cmp(a[1].country, b[1].country) || cmp(a[1].visa.name, b[1].visa.name));
    const top = hits[0][0];
    if (top < 4.0) return [];
    return hits.filter(([s]) => s >= 0.6 * top).slice(0, limit).map(([s, d]) => ({
      country: d.country, name: d.visa.name, type: d.visa.type, difficulty: d.visa.difficulty,
      summary: d.visa.summary, score: Math.round(s * 100) / 100 }));
  }

  // Keyword-first hybrid (search.visa_search). sims: Map("CODE|visa name" → cosine) or null.
  function visaSearch(prompt, region = null, limit = 6, countries = null, sims = null, threshold = null) {
    const keyword = keywordSearch(prompt, region, limit, countries);
    if (!sims || threshold == null) return keyword.map(h => ({ ...h, match: "keyword" }));
    const docs = new Map(VINDEX.docs.map(d => [`${d.code}|${d.visa.name}`, d]));
    const only = new Set(countries || []);
    const meaning = [...sims.entries()]
      .filter(([key, sim]) => sim >= threshold && docs.has(key) && (!region || docs.get(key).region === region)
              && (!only.size || only.has(key.split("|")[0])))
      .sort((a, b) => (b[1] - a[1]) || cmp(a[0], b[0])).map(([key]) => key);
    const byName = new Map(VINDEX.docs.map(d => [`${d.country}|${d.visa.name}`, `${d.code}|${d.visa.name}`]));
    const order = keyword.map(h => byName.get(`${h.country}|${h.name}`));
    const kw = new Set(order);
    for (const k of meaning) if (!kw.has(k)) order.push(k);
    const ms = new Set(meaning);
    return order.slice(0, limit).map(k => {
      const d = docs.get(k);
      return { country: d.country, name: d.visa.name, type: d.visa.type, difficulty: d.visa.difficulty, summary: d.visa.summary,
               match: kw.has(k) && ms.has(k) ? "both" : kw.has(k) ? "keyword" : "meaning",
               similarity: sims.has(k) ? Math.round(sims.get(k) * 1000) / 1000 : null };
    });
  }

  root.RelocSearch = { interpretRules, keywordSearch, visaSearch, semanticClausesFor, semanticQuery, MAX_PROMPT,
                       extractPersonal, familyPhrase, fieldLabel };
})(typeof globalThis !== "undefined" ? globalThis : this);
