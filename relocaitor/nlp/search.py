"""
relocaitor/nlp/search.py — Understands a free-text prompt such as

    "I'm a Pakistani software engineer earning $3k a month. I want somewhere
     safe and English-speaking in Europe with a path to PR, cold is fine."

and turns it into slider weights, filters and a profile, plus keyword hits
over the visa database.

Two layers:

1. Concept matching (always on, offline). The vocabulary lives in
   data/search_lexicon.json: hundreds of phrases and synonyms mapped to the
   9 factors, life situations (nomad, student, retiree, investor, founder,
   family, skilled worker), regions, visa difficulty, countries, cities,
   nationalities and currencies. On top of exact phrase matching it handles:
     - typos (fuzzy matching: "helthcare", "portgual")
     - word forms (light stemming: "jobs", "earning", "monthly")
     - intensity ("very safe", "ideally sunny", "X is essential")
     - negation and opposites ("no snow", "not too expensive", "hate the cold")
     - de-prioritising ("don't care about salary", "cold is fine")
     - money ("$3k/month", "60k a year", "€200,000 to invest", "Rs 500,000")
     - roles of country mentions: origin ("I'm Pakistani", "German passport"),
       destination ("is Canada good?"), comparison ("Canada or Australia"),
       similarity ("somewhere like Portugal"), exclusion ("not the US")
2. Claude (optional). With ANTHROPIC_API_KEY set, the prompt is interpreted
   by Claude into the same structure, which handles phrasing no word list can
   anticipate. Any failure falls back to layer 1.

Keyword search ranks visa pathways by name, type and description (BM25-style
idf weighting with prefix and fuzzy matching), so "golden visa", "blue card"
or "nomad visa europe" find the right entries.
"""

from __future__ import annotations

import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional
from relocaitor import paths

LEXICON_PATH = paths.DATA / "search_lexicon.json"

W_MENTION, W_STRONG, W_MILD, W_DEPRIO, W_OPPOSITE, W_UNMENTIONED = 0.8, 1.0, 0.5, 0.05, 0.1, 0.25
# The trained classifier (ml/prompt_model.py) only fills gaps the rules leave, above confidence
# thresholds tuned on out-of-fold training predictions (stored in ml/prompt_model.json).
LEARNED = "learned"   # marker in explicit[...] for factors inferred by the model
SEMANTIC = "semantic"  # marker for factors found by sentence-embedding similarity
# Embeddings don't understand negation well ("I hate hot weather" sits close to "I hate the cold"),
# so clauses containing these are left to the rules.
SEMANTIC_SKIP = [("not",), ("no",), ("dont",), ("doesnt",), ("isnt",), ("arent",), ("never",), ("avoid",),
                 ("hate",), ("dislike",), ("nothing",), ("zero",)]
# ("without", "less" and "fewer" are kept: "without worrying", "less crime" point the same way as the factor.)
LIST_WORDS = {"or", "and", "nor", "either", "neither", "the"}
MAX_PROMPT = 1000


# ---------------------------------------------------------------------------
# Text utilities (mirrored exactly in the JavaScript preview port)
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return text.replace("'", "")


def stem(w: str) -> str:
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) - 3 >= 3:
        return w[:-3] + "y"
    if w.endswith("ing") and len(w) - 3 >= 3:
        return w[:-3]
    if w.endswith("ed") and len(w) - 2 >= 3:
        return w[:-2]
    if w.endswith("es") and len(w) - 2 >= 3 and re.search(r"(s|x|z|ch|sh)es$", w):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) - 1 >= 3:
        return w[:-1]
    if w.endswith("ly") and len(w) - 2 >= 3:
        return w[:-2]
    return w


def words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", normalize(text).lower())


def stems(text: str) -> tuple:
    return tuple(stem(w) for w in words(text))


def edit_distance(a: str, b: str, limit: int = 2) -> int:
    """Damerau-Levenshtein (optimal string alignment), early exit above limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2 = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def fuzzy_limit(n: int) -> int:
    return 0 if n < 5 else (1 if n < 8 else 2)


def money_fmt(n: float) -> str:
    return f"${n:,.0f}"


# ---------------------------------------------------------------------------
# Lexicon → phrase index
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def lexicon() -> dict:
    with open(LEXICON_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def phrase_index() -> dict:
    """
    {first_stem: [entry, ...]} with entries sorted longest first.
    entry = {"stems": tuple, "kind": str, "value": ..., "polarity": int, "upper": bool}
    """
    L = lexicon()
    entries = []

    def add(phrase, kind, value, polarity=1):
        st = stems(phrase)
        if st:
            entries.append({"stems": st, "kind": kind, "value": value, "polarity": polarity,
                            "upper": kind == "country" and phrase == "us", "text": phrase})

    for key, spec in L["factors"].items():
        for p in spec["positive"]:
            add(p, "factor", key, 1)
        for p in spec["negative"]:
            add(p, "factor", key, -1)
    for intent in L["intents"]:
        for p in intent["phrases"]:
            add(p, "intent", intent["id"])
    for region, ps in L["regions"].items():
        for p in ps:
            add(p, "region", region)
    for level, ps in L["difficulty"].items():
        for p in ps:
            add(p, "difficulty", level)
    for p in L["qualify"]:
        add(p, "qualify", True)
    for code, spec in L["countries"].items():
        for p in spec["aliases"]:
            add(p, "country", {"code": code, "via": "name"})
        for p in spec["cities"]:
            add(p, "country", {"code": code, "via": "city", "city": p})
        for p in spec["demonyms"]:
            add(p, "country", {"code": code, "via": "demonym"})

    kind_rank = {"country": 0, "intent": 1, "factor": 2, "region": 3, "difficulty": 4, "qualify": 5}
    index = {}
    for e in entries:
        index.setdefault(e["stems"][0], []).append(e)
    for lst in index.values():
        lst.sort(key=lambda e: (-len(e["stems"]), -len(e["text"]), kind_rank[e["kind"]]))
    singles = sorted((e for e in entries if len(e["stems"]) == 1 and len(e["stems"][0]) >= 5),
                     key=lambda e: (kind_rank[e["kind"]], e["text"]))
    return {"index": index, "singles": singles}


@lru_cache(maxsize=1)
def word_sets() -> dict:
    L = lexicon()
    return {k: [stems(p) for p in L[k]] for k in (
        "strong", "mild", "negators", "deprioritise", "origin_before", "origin_after",
        "exclude_before", "similar_before", "investment_words", "income_words", "residence_before",
        "period_month", "period_year", "language_words", "compare_words")} | {
        "not_residence": {stem(w) for w in L["not_residence_before"]},
        "function_stems": {st for k in ("strong", "mild", "negators", "deprioritise", "origin_before",
                                        "residence_before", "exclude_before", "similar_before", "origin_after",
                                        "compare_words", "language_words", "qualify")
                           for p in L[k] for st in stems(p)},
        "fillers": {stem(w) for w in L["fillers"]},
        "breakers": {stem(w) for w in L["clause_breakers"]},
        "stop": {stem(w) for w in L["stopwords"]},
    }


def _ends_with(seq: tuple, phrase: tuple) -> bool:
    return len(phrase) <= len(seq) and seq[len(seq) - len(phrase):] == phrase


def _contains(seq: tuple, phrase: tuple) -> bool:
    n = len(phrase)
    return any(seq[i:i + n] == phrase for i in range(len(seq) - n + 1))


def _any_contains(seq: tuple, phrases) -> bool:
    return any(_contains(seq, p) for p in phrases)


# ---------------------------------------------------------------------------
# Tokenizing & money
# ---------------------------------------------------------------------------

MONEY_RE = re.compile(
    r"(?P<pre>[$€£₹]|\b(?:usd|eur|gbp|pkr|inr|aed|cad|aud|rs\.?)\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<mult>k|m|mn|million|thousand|lakh|lac|crore)?\b"
    r"(?:\s?(?P<cur>usd|us dollars|dollars?|bucks|eur|euros?|gbp|pounds?|quid|pkr|rupees?|inr|aed|dirhams?|cad|aud))?",
    re.IGNORECASE,
)
# Words right before an amount that only describe the money ("earning $3k", "savings of €50k").
MONEY_LEADS = {stem(w) for w in (
    "income", "earn", "earning", "earns", "make", "making", "salary", "paid", "pay", "paying", "wage", "wages",
    "invest", "investment", "investing", "savings", "saved", "save", "budget", "capital", "deposit", "have",
    "of", "about", "around", "roughly", "approximately", "approx", "is", "my", "i", "a", "with", "total", "worth",
    "are", "was", "be", "at", "only", "just")}
INDIA_HINTS = re.compile(r"\b(india|indian|inr|delhi|mumbai|bangalore|bengaluru|hyderabad|chennai|kolkata|pune)\b|₹", re.I)


def _rupee_rate(text: str) -> float:
    """'lakh', 'crore', 'rupees' and 'Rs' are used in India and Pakistan: pick by context."""
    cur = lexicon()["currencies"]
    return cur["inr"]["rate"] if INDIA_HINTS.search(text) else cur["pkr"]["rate"]
MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "lakh": 1e5, "lac": 1e5, "crore": 1e7}


def _currency_rate(token: Optional[str]) -> Optional[float]:
    if not token:
        return None
    t = token.lower().strip().rstrip(".")
    for spec in lexicon()["currencies"].values():
        for w in spec["words"]:
            if t == w or t.rstrip("s") == w.rstrip("s"):
                return spec["rate"]
    return None


def extract_money(text: str) -> tuple:
    """Returns ([{amount_usd, kind: income|investment, raw}], text with amounts blanked)."""
    ws = word_sets()
    found = []
    blanked = text
    for m in MONEY_RE.finditer(text):
        raw = m.group(0).strip()
        num = float(m.group("num").replace(",", ""))
        mult = MULT.get((m.group("mult") or "").lower(), 1.0)
        rate = _currency_rate(m.group("pre")) or _currency_rate(m.group("cur"))
        before = stems(text[max(0, m.start() - 40):m.start()])[-5:]
        after_text = text[m.end():m.end() + 30].lower()
        after = stems(after_text)[:4]
        has_money_word = _any_contains(before, ws["income_words"] + ws["investment_words"])
        if after[:2] in (("year", "old"), ("yr", "old")) or (after and after[0] in ("country", "option", "place", "result", "choice")):
            continue
        if rate is None and m.group("mult") is None and not has_money_word:
            continue
        if before and before[-1] == "top":
            continue
        cur_word = (m.group("pre") or m.group("cur") or "").lower().strip().rstrip(".")
        if (m.group("mult") or "").lower() in ("lakh", "lac", "crore") and rate is None or cur_word.startswith("rupee") or cur_word == "rs":
            rate = _rupee_rate(text)
        amount = num * mult * (rate or 1.0)
        if amount < 50:
            continue
        slash = re.match(r"\s*(?:/|per|a|an|every|each)?\s*(month|mo|mth|m\b|year|yr|annum|annually|monthly|yearly|pa\b|pm\b)",
                         after_text)
        period = None
        if slash:
            tok = slash.group(1)
            period = "year" if tok in ("year", "yr", "annum", "annually", "yearly", "pa") else "month"
        elif _any_contains(after, ws["period_year"]):
            period = "year"
        elif _any_contains(after, ws["period_month"]):
            period = "month"

        near = before[-1:] + after[:2]          # the words right next to the amount decide first
        if period:
            kind = "income"
        elif _any_contains(near, ws["investment_words"]) and not _any_contains(near, ws["income_words"]):
            kind = "investment"
        elif _any_contains(near, ws["income_words"]) and not _any_contains(near, ws["investment_words"]):
            kind = "income"
        elif _any_contains(before + after, ws["investment_words"]) and not _any_contains(before, ws["income_words"]):
            kind = "investment"
        elif _any_contains(before + after, ws["income_words"]):
            kind = "income"
        else:
            kind = "investment" if amount >= 20000 else "income"
        if kind == "income" and period == "year":
            amount /= 12
        found.append({"amount_usd": round(amount), "kind": kind, "raw": raw})
        # Blank the amount, its period ("a month", "/yr") and the money words right before it
        # ("earning", "invest", "savings of"), so they aren't also read as preferences.
        a, b = m.start(), m.end()
        if slash:
            b += slash.end()
            trail = re.match(r"(\s*(?:salary|income|pension|savings|earnings|in savings|net)\b)", text[b:], re.I)
            if trail:
                b += trail.end()
        else:
            tail = re.match(r"(\s*(?:a|an|per|every|each)?\s*(?:month|monthly|year|yearly|annually|annum)s?\b)", text[b:], re.I)
            if tail:
                b += tail.end()
            trail = re.match(r"(\s*(?:salary|income|pension|savings|earnings|in savings|net)\b)", text[b:], re.I)
            if trail:
                b += trail.end()
        money_words = MONEY_LEADS
        head = re.search(r"((?:[A-Za-z']+\W+){1,4})$", text[:a])
        if head:
            ws_before = re.findall(r"[A-Za-z']+|\W+", head.group(1))
            cut = len(head.group(1))
            consumed = 0
            for tok in reversed(ws_before):
                if re.match(r"\W+$", tok):
                    consumed += len(tok)
                    continue
                if stem(normalize(tok).lower()) in money_words:
                    consumed += len(tok)
                else:
                    break
            a -= consumed if consumed <= cut else cut
        blanked = blanked[:a] + " " * (b - a) + blanked[b:]
    return found, blanked


def tokenize(text: str) -> list:
    """[{w, s, upper, clause}] — clause changes at punctuation and at 'but/however/…'."""
    ws = word_sets()
    out = []
    clause = 0
    for part in re.split(r"[.,;!?\n]+", normalize(text)):
        clause += 1
        for raw in re.findall(r"[A-Za-z0-9]+", part):
            w = raw.lower()
            s = stem(w)
            if s in ws["breakers"] and not (out and out[-1]["s"] in ("anywhere", "anything", "everywhere", "all")):
                clause += 1
            out.append({"w": w, "s": s, "upper": raw.isupper() and len(raw) > 1, "clause": clause})
    return out


# ---------------------------------------------------------------------------
# Concept matching
# ---------------------------------------------------------------------------

def match_concepts(tokens: list) -> list:
    """Greedy longest-match over the phrase index, with a fuzzy fallback for single words."""
    cues = word_sets()["function_stems"]
    idx = phrase_index()
    stop = word_sets()["stop"]
    matches = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        best = None
        for e in idx["index"].get(t["s"], []):
            n = len(e["stems"])
            span = tokens[i:i + n]
            if len(span) == n and tuple(x["s"] for x in span) == e["stems"] and \
                    all(x["clause"] == t["clause"] for x in span) and (not e["upper"] or t["upper"]):
                best = e
                break
        fuzzy = False
        # Cue words ("remove", "except", "versus") are never fuzzy-matched to concepts ("remove" ≠ "remote").
        if best is None and len(t["s"]) >= 5 and t["s"] not in stop and t["s"] not in cues and not t["s"].isdigit():
            lim = fuzzy_limit(len(t["s"]))
            cands = []
            for e in idx["singles"]:
                if abs(len(e["stems"][0]) - len(t["s"])) > lim:
                    continue
                d = edit_distance(t["s"], e["stems"][0], lim)
                if d <= lim:
                    cands.append((d, e))
            if cands:
                best = min(cands, key=lambda c: c[0])[1]
                fuzzy = True
        if best:
            n = len(best["stems"])
            matches.append({"entry": best, "start": i, "end": i + n, "clause": t["clause"],
                            "fuzzy": fuzzy, "said": " ".join(x["w"] for x in tokens[i:i + n])})
            i += n
        else:
            i += 1
    return matches


def _window(tokens, start, end, clause, before=3, after=3, taken=None):
    taken = taken or set()
    b = tuple(tokens[k]["s"] for k in range(max(0, start - before), start)
              if tokens[k]["clause"] == clause and k not in taken)
    a = tuple(tokens[k]["s"] for k in range(end, min(len(tokens), end + after))
              if tokens[k]["clause"] == clause and k not in taken)
    return b, a


def _clause_stems(tokens, clause):
    return tuple(t["s"] for t in tokens if t["clause"] == clause)


# ---------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------

def _cue_end(b: tuple, phrases, fillers):
    """(cue, start index) if a cue phrase ends right before a mention (one filler like 'the' allowed)."""
    for p in phrases:
        if _ends_with(b, p):
            return p, len(b) - len(p)
        if b and b[-1] in fillers and _ends_with(b[:-1], p):
            return p, len(b) - 1 - len(p)
    return None


def _country_role(before: tuple, after: tuple, via: str, ws: dict) -> str:
    """origin | residence | exclude | similar | destination."""
    if _any_contains(before, ws["exclude_before"]) and not _cue_end(before, ws["origin_before"], ws["fillers"]):
        return "exclude"
    sim = _cue_end(before, ws["similar_before"], ws["fillers"])
    if sim:
        cue, k = sim
        if not (cue == ("like",) and k > 0 and before[k - 1] in ("i", "id", "would", "we", "realy")):
            return "similar"
    if _cue_end(before, ws["origin_before"], ws["fillers"]) or via == "demonym" \
            or any(after[:len(p)] == p for p in ws["origin_after"]):
        return "origin"
    res = _cue_end(before, ws["residence_before"], ws["fillers"])
    if res:
        cue, k = res
        if not (k > 0 and before[k - 1] in ws["not_residence"]):
            return "residence"
    return "destination"


def semantic_clauses(tokens: list, ws: dict) -> list:
    """[(clause id, text)] worth embedding: no negation/de-prioritising, at least 2 content words."""
    by_clause = {}
    for t in tokens:
        by_clause.setdefault(t["clause"], []).append(t)
    out = []
    for cid, toks in by_clause.items():
        stems_ = tuple(t["s"] for t in toks)
        skip = [tuple(stem(w) for w in phrase) for phrase in SEMANTIC_SKIP]
        if _any_contains(stems_, skip) or _any_contains(stems_, ws["deprioritise"]):
            continue
        content = [s for s in stems_ if s not in ws["stop"] and s not in ws["function_stems"] and not s.isdigit()]
        if len(content) >= 2:
            out.append((cid, " ".join(t["w"] for t in toks)))
    return out[:8]


def interpret_rules(prompt: str, meta: dict, use_model: bool = True, use_semantic: bool = True) -> dict:
    L = lexicon()
    ws = word_sets()
    factor_labels = {k: v["label"] for k, v in meta["factors"].items()}
    names = {n["code"]: n["name"] for n in meta["nationalities"]}
    destinations = {c for c in meta["country_codes"]}

    prompt = (prompt or "")[:MAX_PROMPT]
    money, rest = extract_money(prompt)
    tokens = tokenize(rest)
    matches = match_concepts(tokens)
    taken = {k for m in matches for k in range(m["start"], m["end"])}

    chips, fuzzy_notes = [], []
    explicit, intents = {}, []
    region = difficulty = None
    qualify = False
    origin = None  # (strength, code, said)
    dests, similar, exclude = [], [], []
    city_said = {}   # destination code -> first city named for it ("Toronto")
    negated_visas = set()

    factor_starts = {m["start"] for m in matches if m["entry"]["kind"] == "factor"}
    last = {}   # kind -> (end index, clause, role/weight) of the previous match, for "X or Y" lists

    def continues_list(kind, m):
        prev = last.get(kind)
        if not prev or prev[1] != m["clause"]:
            return None
        between = [tokens[k]["s"] for k in range(prev[0], m["start"])]
        return prev[2] if between and all(w in LIST_WORDS for w in between) else None

    for m in matches:
        e, cl = m["entry"], m["clause"]
        before, after = _window(tokens, m["start"], m["end"], cl, taken=taken)
        b4, a4 = _window(tokens, m["start"], m["end"], cl, before=4, after=4, taken=taken)
        negated = _any_contains(before[-2:], ws["negators"]) or _any_contains(before, [("not",), ("no",), ("dont",)])
        if m["fuzzy"]:
            fuzzy_notes.append(f"“{m['said']}” → {e['text']}")

        if e["kind"] == "factor":
            key = e["value"]
            if _any_contains(b4 + ("|",) + a4, ws["deprioritise"]) or continues_list("factor", m) == W_DEPRIO:
                w, how = W_DEPRIO, "not important"
            else:
                pol = e["polarity"] * (-1 if (negated and e["polarity"] < 0) else 1)
                if pol < 0:
                    w, how = W_OPPOSITE, f"you prefer the opposite ({m['said']})"
                elif _any_contains(before + after, ws["strong"]):
                    w, how = W_STRONG, "very important"
                elif _any_contains(before + after, ws["mild"]):
                    w, how = W_MILD, "nice to have"
                else:
                    w, how = W_MENTION, "important"
            prev = explicit.get(key)
            if prev is None or (w > prev[0] and prev[0] != W_DEPRIO) or w == W_DEPRIO:
                explicit[key] = (w, how, m["said"])
            last["factor"] = (m["end"], cl, w)

        elif e["kind"] == "intent":
            if negated:
                spec = next(x for x in L["intents"] if x["id"] == e["value"])
                negated_visas.add(spec.get("visa_type"))
                continue
            if e["value"] not in [x["id"] for x in intents]:
                spec = next(x for x in L["intents"] if x["id"] == e["value"])
                intents.append(spec | {"said": m["said"]})

        elif e["kind"] == "region":
            if not negated and region is None:
                region = (e["value"], m["said"])

        elif e["kind"] == "difficulty":
            difficulty = difficulty or e["value"]

        elif e["kind"] == "qualify":
            qualify = True

        elif e["kind"] == "country":
            code, via = e["value"]["code"], e["value"]["via"]
            # "Spanish-speaking", "speak fluent Spanish": a language, not a passport. Only adjacent words
            # count, so "I'm Pakistani, safe and English-speaking" keeps the passport.
            near_lang = _any_contains(before[-2:] + after[:1], ws["language_words"])
            if via == "demonym" and near_lang:
                continue
            role = _country_role(before, after, via, ws)
            if via == "demonym" and m["end"] in factor_starts and tokens[m["end"]]["clause"] == cl:
                role = "destination"        # "Japanese healthcare": an adjective, not a passport
            if role == "destination" and continues_list("country", m) in ("exclude", "similar"):
                role = continues_list("country", m)
            last["country"] = (m["end"], cl, role)
            if role == "exclude":
                exclude.append(code)
            elif role == "similar":
                similar.append(code)
            elif role in ("origin", "residence"):
                cand = (3 if via == "demonym" or role == "origin" else 1, code, m["said"])
                if origin is None or cand[0] > origin[0]:
                    origin = cand
            elif code in destinations:
                if code not in dests:
                    dests.append(code)
                if via == "city":
                    city_said.setdefault(code, e["value"]["city"])

    # ---------- trained model fills the gaps ----------
    learned_prob, learned_visa = {}, None
    if use_model:
        from ml import prompt_model
        pred = prompt_model.predict(rest)
        if pred and pred["thresholds"]["factor"] is not None:
            for k in factor_labels:
                prob = pred["factors"].get(k, 0.0)
                if k not in explicit and prob >= pred["thresholds"]["factor"]:
                    explicit[k] = (W_MENTION, "important", LEARNED)
                    learned_prob[k] = prob
        if pred and pred["thresholds"]["visa"] is not None:
            if not any(i.get("visa_type") for i in intents):
                cls = max(pred["visa"], key=lambda c: (pred["visa"][c], c))
                if cls != "none" and pred["visa"][cls] >= pred["thresholds"]["visa"] and cls not in negated_visas:
                    learned_visa = (cls, pred["visa"][cls])

    # ---------- sentence embeddings fill what is still missing ----------
    semantic_prob, semantic_visa, used_clauses = {}, None, set()
    if use_semantic:
        from ml import semantic
        cfg = semantic.config()
        fth, vth = cfg.get("factor_threshold"), cfg.get("visa_type_threshold")
        if (fth is not None or vth is not None) and semantic.available():
            clauses = semantic_clauses(tokens, ws)
            for (cid, clause), best in zip(clauses, semantic.concept_scores([c for _, c in clauses])):
                if fth is not None:
                    cands = sorted(((sim, k, proto) for (kind, k), (sim, proto) in best.items()
                                    if kind == "factor" and sim >= fth), key=lambda x: (-x[0], x[1]))
                    for sim, k, proto in cands[:cfg.get("max_factors_per_clause", 2)]:
                        if k in explicit and explicit[k][2] != SEMANTIC:
                            continue
                        if k not in semantic_prob or sim > semantic_prob[k][0]:
                            semantic_prob[k] = (sim, clause, proto)
                            explicit[k] = (W_MENTION, "important", SEMANTIC)
                        used_clauses.add(cid)
                if vth is not None and not learned_visa and not any(i.get("visa_type") for i in intents):
                    vs = sorted(((sim, k, proto) for (kind, k), (sim, proto) in best.items()
                                 if kind == "visa_type" and sim >= vth and k not in negated_visas),
                                key=lambda x: (-x[0], x[1]))
                    if vs and (semantic_visa is None or vs[0][0] > semantic_visa[1]):
                        semantic_visa = (vs[0][1], vs[0][0], clause, vs[0][2])
                        used_clauses.add(cid)

    # ---------- weights ----------
    weights = None
    if explicit or any(i["boosts"] for i in intents):
        weights = {k: W_UNMENTIONED for k in factor_labels}
        for it in intents:
            for k, v in it["boosts"].items():
                weights[k] = v
        for k, (w, how, said) in explicit.items():
            weights[k] = w
        weights = {k: round(v, 2) for k, v in weights.items()}

    for k, (w, how, said) in sorted(explicit.items(), key=lambda kv: -kv[1][0]):
        if said == SEMANTIC:
            sim, clause, proto = semantic_prob[k]
            chips.append({"kind": "semantic", "key": k, "icon": "semantic",
                          "label": f"{factor_labels[k]}: important",
                          "detail": f"meaning match {sim:.2f}: “{clause}” ≈ “{proto}”"})
        elif said == LEARNED:
            chips.append({"kind": "learned", "key": k, "icon": "learned",
                          "label": f"{factor_labels[k]}: important",
                          "detail": f"inferred by the trained model (confidence {learned_prob[k]:.0%})"})
        else:
            chips.append({"kind": "factor", "key": k, "icon": k,
                          "label": f"{factor_labels[k]}: {how}",
                          "detail": f"weight {w:.2f} (from “{said}”)"})

    # ---------- profile & filters ----------
    profile = {}
    visa_intent = next((i for i in intents if i.get("visa_type")), None)
    if visa_intent:
        profile["visa_type"] = visa_intent["visa_type"]
    if learned_visa:
        profile["visa_type"] = learned_visa[0]
        label = next(i["label"] for i in L["intents"] if i.get("visa_type") == learned_visa[0])
        chips.append({"kind": "learned", "icon": "learned", "label": label,
                      "detail": f"inferred by the trained model (confidence {learned_visa[1]:.0%}) → {learned_visa[0]} visas"})
    if semantic_visa and not learned_visa and "visa_type" not in profile:
        profile["visa_type"] = semantic_visa[0]
        label = next(i["label"] for i in L["intents"] if i.get("visa_type") == semantic_visa[0])
        chips.append({"kind": "semantic", "icon": "semantic", "label": label,
                      "detail": f"meaning match {semantic_visa[1]:.2f}: “{semantic_visa[2]}” ≈ “{semantic_visa[3]}” → {semantic_visa[0]} visas"})
    for it in intents:
        chips.append({"kind": "intent", "icon": "target", "label": it["label"],
                      "detail": f"from “{it['said']}”" + (f" → {it['visa_type']} visas" if it.get("visa_type") == profile.get("visa_type") and it.get("visa_type") else "")})
        if it.get("require_pr"):
            profile["require_pr"] = True

    pr = explicit.get("pr")
    if pr and pr[2] in (LEARNED, SEMANTIC):
        pr = None            # a model guess never sets a hard filter
    if pr and pr[0] >= W_MENTION:
        profile["require_pr"] = True
    elif pr and pr[0] <= W_OPPOSITE:
        profile["require_pr"] = False
    if profile.get("require_pr"):
        chips.append({"kind": "filter", "icon": "pr", "label": "Must lead to permanent residency"})

    if difficulty:
        profile["max_difficulty"] = difficulty
        chips.append({"kind": "filter", "icon": "difficulty", "label": f"Visa difficulty: {difficulty.lower()} or easier"})

    if origin:
        profile["nationality"] = origin[1]
        assumed = " (assumed from where you live)" if origin[0] == 1 else ""
        chips.append({"kind": "profile", "icon": "pr", "label": f"Passport: {names.get(origin[1], origin[1])}{assumed}",
                      "detail": f"from “{origin[2]}”"})

    for mny in money:
        if mny["kind"] == "income" and "monthly_income" not in profile:
            profile["monthly_income"] = mny["amount_usd"]
            chips.append({"kind": "profile", "icon": "income", "label": f"Income: {money_fmt(mny['amount_usd'])}/mo",
                          "detail": f"from “{mny['raw']}”"})
        elif mny["kind"] == "investment" and "investment_budget" not in profile:
            profile["investment_budget"] = mny["amount_usd"]
            chips.append({"kind": "profile", "icon": "savings", "label": f"Savings to invest: {money_fmt(mny['amount_usd'])}",
                          "detail": f"from “{mny['raw']}”"})

    me = extract_personal(prompt)
    if me["occupation"]:
        profile["occupation"] = me["occupation"]
        chips.append({"kind": "profile", "icon": "job", "label": f"Field: {_field_label(me['occupation'])}",
                      "detail": f"from “{me['occupation_said']}”"})
    if me["age"] is not None:
        profile["age"] = me["age"]
        chips.append({"kind": "profile", "icon": "clock", "label": f"Age: {me['age']}",
                      "detail": f"from “{me['age_said']}”"})
    if me["partner"] is not None:
        profile["partner"] = me["partner"]
    if me["children"] is not None:
        profile["children"] = me["children"]
    if me["partner"] or me["children"]:
        chips.append({"kind": "profile", "icon": "family", "label": "Moving with " + family_phrase(me["partner"], me["children"], me.get("children_unsure")),
                      "detail": f"from “{me['family_said']}”"})

    if qualify or "nationality" in profile or "monthly_income" in profile or "investment_budget" in profile:
        profile["only_qualifying"] = True
        chips.append({"kind": "filter", "icon": "check", "label": "Only countries with a visa you likely qualify for"})

    if region:
        chips.append({"kind": "region", "icon": "region", "label": f"Region: {region[0]}", "detail": f"from “{region[1]}”"})

    exclude = [c for c in dict.fromkeys(exclude) if c in destinations]
    similar = [c for c in dict.fromkeys(similar) if c in destinations]
    dests = [c for c in dests if c not in exclude and c not in similar and c != profile.get("nationality")]
    for c in exclude:
        chips.append({"kind": "exclude", "icon": "exclude", "label": f"Excluding {names[c]}"})
    if similar:
        chips.append({"kind": "similar", "icon": "similar", "label": f"Similar to {names[similar[0]]}"})
    city = None
    if len(dests) == 1:
        city = city_said.get(dests[0])
        where = f"{city.title()}, {names[dests[0]]}" if city else names[dests[0]]
        chips.append({"kind": "country", "icon": "pin", "label": f"Looking at {where}"})
    elif len(dests) > 1:
        chips.append({"kind": "country", "icon": "compare", "label": "Comparing " + ", ".join(names[c] for c in dests[:3])})

    top_n = None
    m = re.search(r"\btop\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:countries|options|places|choices|results|destinations)\b",
                  prompt.lower())
    if m:
        top_n = max(3, min(10, int(m.group(1) or m.group(2))))

    if top_n:
        chips.append({"kind": "filter", "icon": "top", "label": f"Showing your top {top_n}"})

    content = [t for k, t in enumerate(tokens) if k not in taken and t["clause"] not in used_clauses
               and t["s"] not in ws["stop"]
               and t["s"] not in ws["function_stems"] and t["s"] not in ws["breakers"]
               and not t["s"].isdigit() and len(t["w"]) > 2
               and not any(edit_distance(t["s"], sw, 1) <= 1 for sw in ws["stop"] if len(sw) >= 5)]
    understood = bool(chips)
    personal_words = set(re.findall(r"[a-z0-9]+", " ".join(
        x for x in (me["occupation_said"], me["age_said"], me["family_said"]) if x).replace("'", "")))
    return {
        "source": "rules",
        "understood": understood,
        "weights": weights,
        "region": region[0] if region else None,
        "profile": profile,
        "exclude": [names[c] for c in exclude],
        "countries": [names[c] for c in dests[:3]],
        "city": city.title() if city else None,
        "similar_to": names[similar[0]] if similar else None,
        "top_n": top_n,
        "chips": chips,
        "fuzzy": fuzzy_notes,
        "unmatched": list(dict.fromkeys(t["w"] for t in content if t["w"] not in personal_words))[:8],
        "summary": summarize(weights, profile, region[0] if region else None,
                             [k for k, _ in sorted(explicit.items(), key=lambda kv: -kv[1][0])]),
    }


# ---------------------------------------------------------------------------
# About the person: job field, age, who is coming (mirrored in search_port.js)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def personal_patterns() -> dict:
    """The "personal" section of the lexicon, compiled. The JavaScript port compiles the same strings."""
    P = lexicon()["personal"]
    return {"num": P["number_words"], "cue_only": set(P["cue_only_jobs"]), "age_range": P["age_range"],
            **{k: re.compile(P[k]) for k in ("job_cue", "partner", "single", "children", "no_children", "age")}}


def _field_label(key: str) -> str:
    from relocaitor.visas.journey import field_label
    return field_label(key) or key


@lru_cache(maxsize=1)
def _job_phrases() -> list:
    """[(phrase, field)], longest first, so 'software engineer' wins over 'engineer'."""
    from relocaitor.visas.journey import occupations
    out = [(p, k) for k, v in occupations().items() for p in v["phrases"]]
    return sorted(out, key=lambda pk: (-len(pk[0]), pk[0]))


def family_phrase(partner, children, unsure=False) -> str:
    parts = []
    if partner:
        parts.append("your partner")
    if children:
        parts.append("children" if unsure else "1 child" if children == 1 else f"{children} children")
    return " and ".join(parts) or "nobody else"


def extract_personal(prompt: str) -> dict:
    """{"occupation", "occupation_said", "age", "age_said", "partner", "children", "family_said"}."""
    P = personal_patterns()
    text = " " + re.sub(r"\s+", " ", (prompt or "").lower().replace("’", "'")) + " "
    out = {"occupation": None, "occupation_said": None, "age": None, "age_said": None,
           "partner": None, "children": None, "family_said": None}

    best = None
    for phrase, field in _job_phrases():
        for m in re.finditer(r"(?<![a-z])" + re.escape(phrase) + r"(?:s|es)?(?![a-z])", text):
            if phrase in P["cue_only"] and not P["job_cue"].search(text[max(0, m.start() - 24):m.start()]):
                continue
            cand = (m.start(), -len(phrase), phrase, field)
            if best is None or cand < best:
                best = cand
            break
    if best:
        out["occupation"], out["occupation_said"] = best[3], best[2]

    lo, hi = P["age_range"]
    for m in P["age"].finditer(text):
        age = int(next(g for g in m.groups() if g))
        if lo <= age <= hi:
            out["age"], out["age_said"] = age, m.group(0).strip()
            break

    said = []
    m = P["partner"].search(text)
    if m:
        out["partner"] = True
        said.append(m.group(0).strip())
    elif P["single"].search(text):
        out["partner"] = False
    if P["no_children"].search(text):
        out["children"] = 0
    else:
        m = P["children"].search(text)
        if m:
            # "my kids" says there are children but not how many: count 1, word it as "children".
            out["children"] = P["num"].get(m.group(1), 1) if m.group(1) else 1
            out["children_unsure"] = not m.group(1) and m.group(3) in ("kids", "children")
            said.append(m.group(0).strip())
    out["family_said"] = ", ".join(said) or None
    return out


SUMMARY_NAMES = {"salary": "high salaries", "cost": "low living costs", "pr": "an easy path to PR",
                 "job": "a strong job market", "climate": "good weather", "safety": "safety",
                 "healthcare": "great healthcare", "english": "English being widely spoken",
                 "internet": "fast internet"}
VISA_NAMES = {"skilled": "skilled-worker visas", "nomad": "digital-nomad visas", "investor": "investor visas",
              "study": "study visas", "startup": "startup visas", "family": "family/partner visas",
              "passive": "passive-income and retirement visas"}


def summarize(weights, profile, region, explicit_keys=()) -> str:
    """One readable sentence, led by what the user actually said."""
    keys = [k for k in explicit_keys if weights and weights.get(k, 0) >= W_MENTION][:4]
    parts = []
    if keys:
        names = [SUMMARY_NAMES[k] for k in keys]
        parts.append("Looking for " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]))
    if profile.get("visa_type"):
        parts.append(("with " if parts else "Looking for ") + VISA_NAMES[profile["visa_type"]])
    if region:
        parts.append(f"in {region}" if parts else f"Looking in {region}")
    if profile.get("require_pr") and "pr" not in keys:
        parts.append("with a route to permanent residency")
    return (" ".join(parts) + ".") if parts else ""


# ---------------------------------------------------------------------------
# Keyword search over visas
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _visa_index():
    from relocaitor.visas.catalog import _load, VISA_TYPES
    from relocaitor.datasets import load_countries
    names = dict(load_countries()[["country_code", "country_name"]].itertuples(index=False))
    regions = dict(load_countries()[["country_code", "region"]].itertuples(index=False))
    docs = []
    for code, entry in _load().items():
        for v in entry["visas"]:
            docs.append({
                "code": code, "country": names[code], "region": regions[code], "visa": v,
                "fields": [(3.0, set(stems(v["name"]))),
                           (2.0, set(stems(VISA_TYPES.get(v["type"], v["type"]) + " " + v["type"]))),
                           (1.5, set(stems(names[code]))),
                           (1.0, set(stems(v["summary"])))],
            })
    df = {}
    for d in docs:
        for s in set().union(*(f[1] for f in d["fields"][:2])):
            df[s] = df.get(s, 0) + 1
    n = len(docs)
    idf = {s: math.log(1 + (n - c + 0.5) / (c + 0.5)) for s, c in df.items()}
    return docs, idf, math.log(1 + (n + 0.5) / 0.5)


def _tok_score(q: str, field: set) -> float:
    if q in field:
        return 1.0
    best = 0.0
    for t in field:
        if len(q) >= 4 and len(t) >= 4 and (t.startswith(q) or q.startswith(t)):
            best = max(best, 0.8)
        elif len(q) >= 5 and edit_distance(q, t, fuzzy_limit(len(q))) <= fuzzy_limit(len(q)):
            best = max(best, 0.7)
    return best


def keyword_query(prompt: str) -> tuple:
    """Words worth searching visa names for: drops money, 'top N', and words already
    understood as preferences, regions, filters or countries. Returns (stems, country codes named)."""
    ws = word_sets()
    _, rest = extract_money(prompt or "")
    rest = re.sub(r"\btop\s+\d{1,2}\b", " ", rest, flags=re.I)
    tokens = tokenize(rest)
    drop, codes = set(), []
    factor_words = {e["stems"][0] for lst in phrase_index()["index"].values() for e in lst
                    if e["kind"] == "factor" and len(e["stems"]) == 1}
    for m in match_concepts(tokens):
        kind = m["entry"]["kind"]
        if kind == "country":
            codes.append(m["entry"]["value"]["code"])
        if kind != "intent":
            drop.update(range(m["start"], m["end"]))
        else:  # keep distinctive intent words ("golden", "nomad", "blue card"), drop generic ones ("job")
            spec = next(x for x in lexicon()["intents"] if x["id"] == m["entry"]["value"])
            prev = [tokens[k]["s"] for k in range(max(0, m["start"] - 2), m["start"])]
            if not spec.get("visa_type") or any(w in ("not", "no", "dont") for w in prev):
                drop.update(range(m["start"], m["end"]))
            else:
                drop.update(k for k in range(m["start"], m["end"]) if tokens[k]["s"] in factor_words)
    q = [t["s"] for k, t in enumerate(tokens) if k not in drop and t["s"] not in ws["stop"]
         and t["s"] not in ws["function_stems"] and not t["s"].isdigit() and len(t["s"]) > 1]
    return list(dict.fromkeys(q)), codes


def keyword_search(prompt: str, region: Optional[str] = None, limit: int = 6, countries=None) -> list:
    q, named = keyword_query(prompt)
    if not q:
        return []
    only = set(countries or [])
    docs, idf, max_idf = _visa_index()
    hits = []
    for d in docs:
        if region and d["region"] != region:
            continue
        if only and d["code"] not in only:
            continue
        score, name_hit = 0.0, False
        for s in q:
            best = 0.0
            for i, (w, field) in enumerate(d["fields"]):
                ts = _tok_score(s, field)
                if ts and i < 2:
                    name_hit = True
                best = max(best, w * ts)
            score += best * idf.get(s, max_idf)
        if name_hit and score > 0:
            hits.append((score, d))
    if not hits:
        return []
    hits.sort(key=lambda h: (-h[0], h[1]["country"], h[1]["visa"]["name"]))
    top = hits[0][0]
    if top < 4.0:
        return []
    return [{"country": d["country"], "name": d["visa"]["name"], "type": d["visa"]["type"],
             "difficulty": d["visa"]["difficulty"], "summary": d["visa"]["summary"], "score": round(s, 2)}
            for s, d in hits if s >= 0.6 * top][:limit]


def semantic_query(prompt: str) -> str:
    """The prompt with money and 'top N' removed: what gets embedded for visa retrieval."""
    _, rest = extract_money(prompt or "")
    return re.sub(r"\btop\s+\d{1,2}\b", " ", rest, flags=re.I).strip()


def visa_search(prompt: str, region: Optional[str] = None, limit: int = 6, countries=None) -> list:
    """
    Hybrid retrieval, keyword first: visas whose NAME matches the query (BM25-style,
    high precision) keep their order at the top; visas whose description is close in
    meaning (sentence-embedding cosine similarity above a tuned threshold) fill the
    remaining places. Each hit says how it matched: "keyword", "meaning" or "both".
    Without the embedding model (or if the evaluation switched retrieval off) this is
    exactly keyword_search.
    """
    keyword = keyword_search(prompt, region, limit=limit, countries=countries)
    from ml import semantic
    th = semantic.config().get("retrieval_threshold")
    if th is None or not semantic.available():
        return [dict(h, match="keyword") for h in keyword]

    docs = {(d["code"], d["visa"]["name"]): d for d in _visa_index()[0]}
    only = set(countries or [])
    sims = semantic.visa_similarities(semantic_query(prompt))
    meaning = [key for sim, key in sorted(
        ((sim, key) for key, sim in sims.items() if sim >= th and key in docs
         and (not region or docs[key]["region"] == region) and (not only or key[0] in only)),
        key=lambda x: (-x[0], x[1]))]
    by_name = {(d["country"], d["visa"]["name"]): k for k, d in docs.items()}
    order = [by_name[(h["country"], h["name"])] for h in keyword]
    order += [k for k in meaning if k not in order]
    meaning_set = set(meaning)
    keyword_set = set(order[:len(keyword)])
    out = []
    for k in order[:limit]:
        d = docs[k]
        how = "both" if k in keyword_set and k in meaning_set else "keyword" if k in keyword_set else "meaning"
        out.append({"country": d["country"], "name": d["visa"]["name"], "type": d["visa"]["type"],
                    "difficulty": d["visa"]["difficulty"], "summary": d["visa"]["summary"],
                    "match": how, "similarity": round(sims[k], 3) if k in sims else None})
    return out


# ---------------------------------------------------------------------------
# Optional Claude interpretation
# ---------------------------------------------------------------------------

LLM_SYSTEM = (
    "You convert a relocation request into JSON for a country recommender. Reply with ONLY a JSON object, no prose. "
    "Keys (omit or null when not stated or clearly implied): "
    "weights: object with keys salary, cost, pr, job, climate, safety, healthcare, english, internet, each 0-1 "
    "(1 = very important, 0.25 = not mentioned, 0.05 = explicitly unimportant; 'cost' high means they want LOW "
    "cost of living; 'climate' high means warm/pleasant weather, low if they prefer cold); "
    "region: one of Europe, Asia, Middle East, Africa, Oceania, North America, South America; "
    "nationality: the user's own country name; monthly_income_usd: number; investment_budget_usd: number; "
    "visa_type: one of skilled, nomad, investor, study, startup, family, passive; require_pr: boolean; "
    "max_difficulty: Easy or Moderate; only_qualifying: boolean; countries: destination country names they asked about; "
    "similar_to: a country name; exclude: country names to avoid; top_n: integer; "
    "summary: one short sentence describing what they want."
)


def interpret_llm(prompt: str, meta: dict) -> Optional[dict]:
    from relocaitor.nlp import assistant
    raw = assistant.ask_llm_raw(LLM_SYSTEM, prompt[:MAX_PROMPT], max_tokens=500)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    rules = interpret_rules(prompt, meta)       # used to resolve names and build chips
    resolve = _name_resolver(meta)
    names = {n["code"]: n["name"] for n in meta["nationalities"]}
    dest = set(meta["country_codes"])

    out = {"source": "llm", "understood": True, "region": None, "profile": {}, "exclude": [], "countries": [],
           "similar_to": None, "top_n": None, "chips": [], "fuzzy": [], "unmatched": [],
           "summary": str(data.get("summary") or "")[:200], "weights": None}
    if isinstance(data.get("weights"), dict):
        out["weights"] = {k: round(min(1.0, max(0.0, float(data["weights"].get(k, W_UNMENTIONED)))), 2)
                          for k in meta["factors"]}
        for k, v in sorted(out["weights"].items(), key=lambda kv: -kv[1]):
            if v >= W_MENTION or v <= W_OPPOSITE:
                how = "very important" if v >= 0.95 else "important" if v >= W_MENTION else "not important"
                out["chips"].append({"kind": "factor", "key": k, "icon": k,
                                     "label": f"{meta['factors'][k]['label']}: {how}"})
    if data.get("region") in meta["regions"]:
        out["region"] = data["region"]
        out["chips"].append({"kind": "region", "icon": "region", "label": f"Region: {data['region']}"})
    p = out["profile"]
    nat = resolve(data.get("nationality"))
    if nat:
        p["nationality"] = nat
        out["chips"].append({"kind": "profile", "icon": "pr", "label": f"Passport: {names[nat]}"})
    for key, pk, label, ic in (("monthly_income_usd", "monthly_income", "Income: {}/mo", "income"),
                               ("investment_budget_usd", "investment_budget", "Savings to invest: {}", "savings")):
        try:
            v = float(data.get(key))
            if v > 0:
                p[pk] = round(v)
                out["chips"].append({"kind": "profile", "icon": ic, "label": label.format(money_fmt(v))})
        except (TypeError, ValueError):
            pass
    if data.get("visa_type") in ("skilled", "nomad", "investor", "study", "startup", "family", "passive"):
        p["visa_type"] = data["visa_type"]
        out["chips"].append({"kind": "intent", "icon": "target", "label": f"{data['visa_type'].capitalize()} visas"})
    if data.get("require_pr") is True:
        p["require_pr"] = True
        out["chips"].append({"kind": "filter", "icon": "pr", "label": "Must lead to permanent residency"})
    if data.get("max_difficulty") in ("Easy", "Moderate"):
        p["max_difficulty"] = data["max_difficulty"]
        out["chips"].append({"kind": "filter", "icon": "difficulty", "label": f"Visa difficulty: {data['max_difficulty'].lower()} or easier"})
    if data.get("only_qualifying") or "nationality" in p or "monthly_income" in p:
        p["only_qualifying"] = True
        out["chips"].append({"kind": "filter", "icon": "check", "label": "Only countries with a visa you likely qualify for"})
    out["exclude"] = [names[c] for c in (resolve(x) for x in data.get("exclude") or []) if c in dest]
    out["countries"] = [names[c] for c in (resolve(x) for x in data.get("countries") or []) if c in dest
                        and names[c] not in out["exclude"]][:3]
    sim = resolve(data.get("similar_to"))
    out["similar_to"] = names[sim] if sim in dest else None
    for n_ in out["exclude"]:
        out["chips"].append({"kind": "exclude", "icon": "exclude", "label": f"Excluding {n_}"})
    if out["similar_to"]:
        out["chips"].append({"kind": "similar", "icon": "similar", "label": f"Similar to {out['similar_to']}"})
    if out["countries"]:
        out["chips"].append({"kind": "country", "icon": "pin" if len(out["countries"]) == 1 else "compare",
                             "label": ("Looking at " if len(out["countries"]) == 1 else "Comparing ")
                             + ", ".join(out["countries"])})
    if isinstance(data.get("top_n"), int):
        out["top_n"] = max(3, min(10, data["top_n"]))
    # Job field, age and family come from the built-in reader, which is exact for these.
    for k in ("occupation", "age", "partner", "children"):
        if k in rules["profile"]:
            p[k] = rules["profile"][k]
    out["chips"] += [c for c in rules["chips"] if c.get("icon") in ("job", "family")
                     or c.get("label", "").startswith("Age: ")]
    out["city"] = rules.get("city") if out["countries"] == rules.get("countries") else None
    out["fuzzy"] = rules["fuzzy"]
    return out


def _name_resolver(meta):
    L = lexicon()
    table = {}
    for n in meta["nationalities"]:
        table[n["name"].lower()] = n["code"]
        table[n["code"].lower()] = n["code"]
    for code, spec in L["countries"].items():
        for w in spec["aliases"] + spec["demonyms"] + spec["cities"]:
            table.setdefault(w.lower(), code)

    def resolve(x):
        if not isinstance(x, str) or not x.strip():
            return None
        return table.get(x.strip().lower())
    return resolve


def interpret(prompt: str, meta: dict) -> dict:
    from relocaitor.nlp import assistant
    if assistant.llm_enabled():
        try:
            res = interpret_llm(prompt, meta)
            if res:
                return res
        except Exception as err:  # network, JSON, schema: fall back to rules
            res = interpret_rules(prompt, meta)
            res["warning"] = f"Claude interpretation unavailable ({type(err).__name__}); used built-in understanding."
            return res
    return interpret_rules(prompt, meta)
