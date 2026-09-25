"""
model_router.py — which model answers a request, and what may be said early.

The routing brain for Chief's two-track reply (2026-09-25, Dev Desk: "make a
Sonnet-backed application feel as fast as Haiku without losing answer
quality ... first token within roughly five hundred milliseconds on every
request, no exceptions"). Pure logic: no I/O, no model calls. The one model
call the router can make (the Haiku tie-breaker for ambiguous requests) and
all the streaming live in chief_fast_track.py; the log and the latency SLO
live in route_ledger.py.

WHAT "LOW COMPLEXITY" MEANS FOR CHIEF

A request is only as simple as the least it needs. "Did Maria pay?" is four
words and still needs her invoice, the answer check (chief_truth) and
possibly a follow-up action — none of which a small prompt on a small model
has. So needing the business's records, or wanting something done, escalates
a request exactly as reasoning, code and long synthesis do. What remains for
Haiku alone is narrow and safe to answer without seeing anything: thanks,
pleasantries, and general-knowledge questions that are not about the
business. Everything else is the full turn (Sonnet, as before) with a Haiku
opening in front of it — which is where the speed comes from.

THE THREE LANES
  fast   Haiku writes the whole answer; the full turn never runs.
  full   Haiku writes a claim-free opening at once; the full turn runs
         behind it and its checked answer continues the same stream.
  cache  a repeat of an earlier fast-lane answer, returned instantly.

Confidence below the floor always routes UP (full): a wrong fast answer costs
trust, an unnecessary full turn costs a few cents.

THE TWO GATES
  OpenerGate  what the opening may say: an acknowledgement and nothing that
              could turn out false. Checked word by word as it streams,
              because the first-token budget does not leave time to wait for
              a whole sentence (measured: first token 383ms median, first
              full sentence 553ms).
  AnswerGate  what a fast-lane answer may say: anything general, nothing
              about the business and no claim that work was done. A reply
              that opens by deflecting ("I don't have access…") escalates
              before a word of it is shown.

Thresholds are env dials (ROUTER_*), so tuning against the route log is a
Railway variable change, not a deploy.
"""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

LANE_FAST = "fast"
LANE_FULL = "full"
LANE_CACHE = "cache"


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _env_on(name: str, default: str = "on") -> bool:
    return (os.environ.get(name) or default).strip().lower() not in ("off", "0", "false", "no")


def fast_max_score() -> float:
    """At or under this complexity (with enough confidence) Haiku answers alone."""
    return _env_float("ROUTER_FAST_MAX_SCORE", 0.25, 0.0, 1.0)


def full_min_score() -> float:
    """At or over this complexity the full turn runs without asking Haiku."""
    return _env_float("ROUTER_FULL_MIN_SCORE", 0.45, 0.0, 1.0)


def min_confidence() -> float:
    """Below this confidence the router defaults upward."""
    return _env_float("ROUTER_MIN_CONFIDENCE", 0.7, 0.0, 1.0)


# ─── Normalisation ───────────────────────────────────────────────────

# Words that carry no meaning for "is this the same question": politeness,
# addressing Chief, and hedges. Stripped from the front and the back only
# where they frame the request; inside a sentence they stay.
_LEAD_FILLERS = re.compile(
    r"^(?:(?:hey|hi|hello|ok(?:ay)?|so|um+|uh+|well|yo)\b[\s,]*)*"
    r"(?:chief\b[\s,:]*)?"
    r"(?:(?:please|pls|quick question|question)\b[\s,:]*)*"
    r"(?:(?:can|could|would|will) you(?: please)?\b\s*)?"
    r"(?:(?:please|pls)\b\s*)?"
    r"(?:(?:tell me|let me know|remind me)\b\s*)?", re.I)
_TRAIL_FILLERS = re.compile(r"(?:\s*\b(?:please|pls|thanks|thank you|chief)\b[\s.!?]*)+$", re.I)
_PUNCT = re.compile(r"[^\w\s'$%.-]|(?<!\d)[.](?!\d)|(?<![\w])-|-(?![\w])", re.U)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """The request as a cache key: case, width, punctuation, spacing and the
    framing words around it no longer matter. Numbers keep their decimal
    point and sign so '$1.5k' and '$15k' never collide."""
    t = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    t = t.replace("’", "'").replace("‘", "'")
    t = _LEAD_FILLERS.sub("", t, count=1)
    t = _TRAIL_FILLERS.sub("", t)
    t = _PUNCT.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


_STOP = frozenset("""
a an the and or of to in on at for with by from about as is are was were be been being
do does did doing have has had i me my we our you your it its this that these those there
what whats what's how who whom which when where why can could would will should shall may
might must tell show give let lets let's just really also some any please thanks thank
""".split())
_NEGATIONS = frozenset({"no", "not", "never", "none", "nothing", "without", "cannot",
                        "cant", "can't", "dont", "don't", "doesnt", "doesn't", "didnt",
                        "didn't", "isnt", "isn't", "arent", "aren't", "wasnt", "wasn't",
                        "wont", "won't", "un", "non"})
_NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?|\b(?:zero|one|two|three|four|five|six|seven|"
                  r"eight|nine|ten|eleven|twelve|hundred|thousand|million|half|double)\b")


def _stem(w: str) -> str:
    for suf in ("ing", "ied", "ies", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            base = w[: -len(suf)]
            return base + ("y" if suf in ("ied", "ies") else "")
    return w


def _content(norm: str) -> Tuple[frozenset, frozenset, frozenset]:
    """(content stems, numbers, negations) of a normalised request."""
    words = norm.split()
    nums = frozenset(_NUM.findall(norm))
    negs = frozenset(w for w in words if w in _NEGATIONS or w.endswith("n't"))
    stems = frozenset(_stem(w) for w in words
                      if w not in _STOP and w not in _NEGATIONS and not _NUM.fullmatch(w))
    return stems, nums, negs


def similarity(a: str, b: str) -> float:
    """How close two normalised requests are, 0..1 — and 0.0 whenever they
    differ in a number or a negation, because 'invoices that are paid' and
    'invoices that are not paid' share every other word."""
    if a == b:
        return 1.0
    sa, na, ga = _content(a)
    sb, nb, gb = _content(b)
    if na != nb or ga != gb or not sa or not sb:
        return 0.0
    ratio = len(a) / max(1, len(b))
    if ratio < 0.6 or ratio > 1.67:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ─── Complexity scoring ──────────────────────────────────────────────

@dataclass
class Complexity:
    score: float                 # 0 trivial … 1 heavy
    confidence: float            # how sure the scorer is, 0 … 1
    kind: str                    # social | general | lookup | action | draft |
                                 # reasoning | code | synthesis | confirm |
                                 # farewell | followup | system | unknown
    needs_records: bool = False
    needs_action: bool = False
    cacheable: bool = False
    signals: List[str] = field(default_factory=list)
    source: str = "heuristic"    # heuristic | haiku | haiku_failed

    def as_log(self) -> Dict[str, Any]:
        return {"score": round(self.score, 3), "confidence": round(self.confidence, 3),
                "kind": self.kind, "needs_records": self.needs_records,
                "needs_action": self.needs_action, "signals": self.signals[:12],
                "source": self.source}


def _rx(words: Iterable[str]) -> "re.Pattern[str]":
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I)


_GRATITUDE = re.compile(
    r"^(?:(?:ok(?:ay)?|great|perfect|awesome|cool|nice|amazing|wonderful|brilliant|lovely|"
    r"sweet|excellent|fantastic)[\s,!.]*)?"
    r"(?:thanks?(?: you)?(?: so much| very much| a lot| a ton)?|thank u|thx|ty|tysm|"
    r"much appreciated|appreciate (?:it|you|that)|cheers)"
    r"(?:[\s,!.]*(?:chief|so much|again|a lot|buddy|friend))*[\s!.😊🙏👍❤️]*$", re.I)
_PRAISE = re.compile(
    r"^(?:(?:you(?:'re| are)|that(?:'s| is| was)|this is)\s+(?:so\s+|really\s+|very\s+)?"
    r"(?:great|awesome|amazing|helpful|brilliant|perfect|the best|incredible|fantastic|"
    r"a lifesaver)|good job|nice work|great work|well done|love (?:it|this|that)|"
    r"lol|haha+|lmao|😂+|👍+|🙏+|❤️+)[\s!.,]*(?:chief|thanks?)?[\s!.]*$", re.I)
_HOW_ARE_YOU = re.compile(r"^(?:hey|hi|hello)?[\s,]*(?:chief[\s,]*)?how(?:'s| is| are)"
                          r"(?: it going| you(?: doing)?| things| your day)"
                          r"(?: today| this morning| this afternoon| tonight| so far| lately)?"
                          r"[\s,]*(?:chief)?[\s?!.]*$", re.I)
_FAREWELL = re.compile(
    r"^(?:ok(?:ay)?[\s,]*)?(?:bye|goodbye|good night|goodnight|see (?:you|ya)|talk (?:to you )?"
    r"(?:later|soon|tomorrow)|that'?s all(?: for now)?|i'?m done(?: for (?:now|today))?|"
    r"signing off|later|ttyl|night)\b", re.I)
_AFFIRM = re.compile(
    r"^(?:y(?:es|eah|ep|up|a)|sure|ok(?:ay)?|k|go(?: ahead| for it)?|do it|send it|"
    r"sounds good|please do|that works|works for me|perfect|great|yes please|approved?|"
    r"confirm(?:ed)?|let'?s do it|absolutely|definitely|correct|right|exactly|"
    r"no|nope|nah|not now|cancel(?: that)?|stop|wait|hold on|never ?mind)\b", re.I)
_SENTINEL = re.compile(r"^\s*\[SYSTEM:", re.I)

_ACTION = _rx([
    r"send", r"email", r"e-mail", r"text", r"message", r"call", r"book", r"schedule",
    r"reschedule", r"cancel", r"create", r"add", r"make", r"set ?up", r"remind",
    r"invoice", r"bill", r"charge", r"refund", r"pay", r"delete", r"remove", r"update",
    r"change", r"edit", r"move", r"publish", r"post", r"build", r"launch", r"save",
    r"record", r"log", r"mark", r"assign", r"archive", r"upload", r"import", r"export",
    r"order", r"buy", r"purchase", r"reply", r"respond", r"follow ?up", r"undo", r"fix",
    r"turn (?:on|off)", r"enable", r"disable", r"connect", r"open", r"go to", r"take me",
    r"navigate", r"show me", r"pull up",
])
_DRAFT = _rx([r"draft", r"write", r"rewrite", r"compose", r"word(?:ing)?", r"caption",
              r"tagline", r"headline", r"slogan", r"bio", r"script", r"newsletter",
              r"announcement", r"blurb", r"description", r"copy"])
_RECORDS = _rx([
    r"my", r"our", r"mine", r"i have", r"i've got", r"we have", r"client", r"clients",
    r"customer", r"customers", r"invoice", r"invoices", r"booking", r"bookings",
    r"appointment", r"appointments", r"lead", r"leads", r"revenue", r"sales", r"income",
    r"expense", r"expenses", r"profit", r"cash", r"balance", r"calendar", r"today",
    r"tomorrow", r"yesterday", r"this week", r"last week", r"next week", r"this month",
    r"last month", r"inbox", r"emails?", r"messages?", r"texts?", r"site", r"website",
    r"page", r"products?", r"inventory", r"stock", r"orders?", r"contacts?", r"team",
    r"staff", r"payroll", r"tasks?", r"projects?", r"goals?", r"campaigns?", r"reviews?",
    r"how many", r"how much", r"who owes", r"owe", r"owed", r"overdue", r"unpaid",
    r"paid", r"outstanding", r"since", r"latest", r"recent(?:ly)?", r"new", r"status",
    r"update on", r"catch me up", r"what'?s (?:new|up|happening|going on)",
    r"where (?:are|is) we", r"anything",
])
_CODE = re.compile(
    r"```|\bdef \w+\(|\bfunction\b|\bclass \w+|=>|\bSELECT\b|\bINSERT\b|\bimport \w+|"
    r"Traceback|\bstack trace\b|\bregex\b|\bsql\b|\bpython\b|\bjavascript\b|\btypescript\b|"
    r"\bhtml\b|\bcss\b|\bjson\b|\bapi\b|\bwebhook\b|\bscript\b|\bcode\b|\bbug\b|"
    r"\berror\b|\{[^}]*:[^}]*\}", re.I)
_REASONING = _rx([
    r"why", r"should i", r"should we", r"how should", r"compare", r"comparison", r"versus",
    r"vs\.?", r"pros and cons", r"trade-?offs?", r"strateg(?:y|ies|ic)", r"plan", r"analy[sz]e",
    r"analysis", r"evaluate", r"figure out", r"think (?:through|about)", r"best way",
    r"what if", r"recommend", r"advice", r"advise", r"help me decide", r"worth it",
    r"improve", r"grow", r"increase", r"reduce", r"optimi[sz]e", r"price", r"pricing",
    r"forecast", r"projection", r"diagnose", r"troubleshoot",
])
_SYNTHESIS = _rx([
    r"summar(?:y|ize|ise)", r"report", r"overview", r"recap", r"break ?down", r"outline",
    r"everything", r"all of", r"list all", r"full list", r"proposal", r"business plan",
    r"marketing plan", r"step[- ]by[- ]step", r"in detail", r"detailed", r"comprehensive",
])
_GENERAL = re.compile(
    r"^(?:what(?:'s| is| are| does| do)|what's the difference|define|definition of|"
    r"meaning of|how do you (?:spell|say|pronounce)|synonyms? for|another word for|"
    r"translate|convert|how many \w+ (?:are )?in an?|who (?:is|was|invented)|"
    r"when (?:is|was|did)|is it (?:true|correct)|explain)\b", re.I)
_ASKS_ABOUT = re.compile(
    r"^\s*(?:did|does|do|is|are|was|were|has|have|had|when|who|what|which|where|how many|"
    r"how much|any|anything)\b(?!\s+you\s+(?:please\s+)?(?:send|make|create|book|add))", re.I)
_FOLLOWUP = re.compile(r"^(?:and|also|what about|how about|same|then|but|so)\b|"
                       r"\b(?:it|that|this|those|them|they|he|she|him|her)\b", re.I)
_TIME_WORDS = _rx([r"today", r"tonight", r"now", r"current(?:ly)?", r"this (?:week|month|year)",
                   r"latest", r"right now", r"date", r"time", r"weather", r"news"])


def _prior_asked(prior_assistant: Optional[str]) -> bool:
    """Did Chief's last message ask for a decision? Then a one-word reply is
    an answer to it — possibly the go-ahead for a send — not small talk."""
    p = (prior_assistant or "").strip()
    if not p:
        return False
    tail = p[-400:].lower()
    return ("?" in tail[-160:] or any(k in tail for k in (
        "shall i", "should i", "want me to", "would you like", "do you want", "ready to",
        "go ahead", "confirm", "say the word", "let me know", "okay to", "ok to")))


def score(message: str, prior_assistant: Optional[str] = None, *,
          has_images: bool = False, mode: Optional[str] = None) -> Complexity:
    """Cheap heuristics first. Returns a score, a confidence and the reason
    words; the policy decides what to do with an unsure one."""
    raw = str(message or "").strip()
    norm = normalize(raw)
    n = len(raw.split())
    sig: List[str] = []

    if _SENTINEL.match(raw):
        return Complexity(1.0, 1.0, "system", signals=["sentinel"])
    if (mode or "") not in ("", "chief"):
        return Complexity(1.0, 1.0, "system", signals=[f"mode:{mode}"])
    if has_images:
        return Complexity(0.8, 1.0, "action", needs_records=True, signals=["images"])
    if not raw:
        return Complexity(0.5, 0.3, "unknown", signals=["empty"])

    asked = _prior_asked(prior_assistant)
    short = n <= 6
    if short and _FAREWELL.match(raw):
        # Farewells close the chat window in the full turn (deterministic
        # goodbye enforcement), so they are never answered on the side.
        return Complexity(0.5, 0.95, "farewell", needs_action=True, signals=["farewell"])
    if asked and short and (_AFFIRM.match(raw) or _GRATITUDE.match(raw)):
        # "yes" / "sounds good" / "perfect, thanks" after "shall I send it?"
        # is the practitioner's go-ahead. It belongs to the turn that asked.
        return Complexity(0.6, 0.95, "confirm", needs_action=True,
                          signals=["reply_to_question"])
    if _GRATITUDE.match(raw) or _PRAISE.match(raw) or _HOW_ARE_YOU.match(raw):
        return Complexity(0.05, 0.92, "social", signals=["social"])
    if short and _AFFIRM.match(raw):
        # A bare "ok" with no question pending is still ambiguous — it may
        # answer something older than the last message.
        return Complexity(0.4, 0.5, "confirm", needs_action=True, signals=["bare_affirm"])

    s = 0.3
    needs_records = False
    needs_action = False
    kind = "unknown"

    if _CODE.search(raw):
        sig.append("code")
        s = max(s, 0.8)
        kind = "code"
    if _SYNTHESIS.search(raw):
        sig.append("synthesis")
        s = max(s, 0.75)
        kind = kind if kind != "unknown" else "synthesis"
    if _REASONING.search(raw):
        sig.append("reasoning")
        s = max(s, 0.6)
        kind = kind if kind != "unknown" else "reasoning"
    if _DRAFT.search(raw):
        sig.append("draft")
        s = max(s, 0.6)
        needs_action = True        # drafts ride the conversational tier (2026-07-03 ruling)
        kind = kind if kind != "unknown" else "draft"
    if _ACTION.search(raw):
        if _ASKS_ABOUT.match(raw) and not _DRAFT.search(raw):
            # "Did Maria pay?" / "Has the email been sent?" name an action
            # but ask about one: a lookup, not a request to act.
            sig.append("asks_about_action")
            needs_records = True
            s = max(s, 0.5)
            kind = kind if kind != "unknown" else "lookup"
        else:
            sig.append("action")
            needs_action = True
            s = max(s, 0.55)
            kind = kind if kind != "unknown" else "action"
    if _RECORDS.search(raw):
        sig.append("records")
        needs_records = True
        s = max(s, 0.5)
        kind = kind if kind != "unknown" else "lookup"
    # A capitalised word that is not the sentence's first is usually a name —
    # a client, a product, a place the business deals with.
    caps = [w for w in re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", raw)
            if w not in ("I", "Chief", "Solutionist")]
    if caps:
        sig.append("name")
        needs_records = True
        s = max(s, 0.5)
    if raw.count("?") >= 2 or re.search(r"\band also\b|\balso\b.*\?", raw, re.I):
        sig.append("multi_ask")
        s = min(1.0, s + 0.15)
    if n > 40:
        sig.append("long")
        s = min(1.0, s + 0.15)
    if n > 120:
        s = max(s, 0.85)
    followup = bool(_FOLLOWUP.search(norm))
    if followup:
        sig.append("followup")

    general = bool(_GENERAL.match(norm)) and not needs_records and not needs_action
    if general and kind in ("unknown",):
        kind = "general"
        s = 0.15 if n <= 14 else 0.3
        sig.append("general")

    if kind == "unknown":
        kind = "followup" if followup else "unknown"

    # Confidence: strong escalators are certain; a lone weak cue is not.
    if needs_records or needs_action or s >= 0.75:
        conf = 0.9
    elif kind == "general":
        conf = 0.8 if not followup else 0.55
        if followup:
            s = max(s, 0.35)
    else:
        conf = 0.5
    cacheable = (kind == "general" and not followup and not _TIME_WORDS.search(norm))
    return Complexity(round(s, 3), conf, kind, needs_records=needs_records,
                      needs_action=needs_action, cacheable=cacheable, signals=sig)


# ─── Dissatisfaction ─────────────────────────────────────────────────

_DISSATISFIED = re.compile(
    r"^(?:no[,.!]?\s+)?(?:that'?s|this is|you'?re|it'?s)\s+(?:not (?:right|it|what i (?:asked|meant|wanted))|"
    r"wrong|incorrect|useless|unhelpful|not helpful)|"
    r"\bnot what i (?:asked|meant|wanted|said)\b|\byou (?:didn'?t|did not) (?:answer|read|listen)|"
    r"\b(?:try again|that'?s wrong|wrong answer|makes no sense|doesn'?t (?:help|make sense)|"
    r"you missed|you misunderstood|read (?:it|that) again|be more (?:specific|detailed)|"
    r"more detail|go deeper|that'?s it\?|is that all|are you sure|that can'?t be right)\b|"
    r"^\?+$|^huh\??$|^what\?+$|^(?:no,?\s+)?i (?:meant|said|asked)\b|^(?:ugh|hmm+)\b|👎", re.I)


def dissatisfied(message: str) -> bool:
    """The practitioner saying the last answer missed."""
    return bool(_DISSATISFIED.search(str(message or "").strip()))


# ─── Policy ──────────────────────────────────────────────────────────

@dataclass
class Route:
    lane: str                    # fast | full (cache is decided by the cache)
    reason: str
    ambiguous: bool = False      # heuristics unsure — ask the Haiku classifier

    def as_log(self) -> Dict[str, Any]:
        return {"lane": self.lane, "reason": self.reason, "ambiguous": self.ambiguous}


def decide(c: Complexity, *, allow_fast: bool = True, dissatisfied_now: bool = False,
           sticky_up: bool = False) -> Route:
    """The routing policy. Upward whenever anything is unsure."""
    if not allow_fast:
        return Route(LANE_FULL, "fast_lane_off")
    if dissatisfied_now:
        return Route(LANE_FULL, "dissatisfied")
    if sticky_up:
        return Route(LANE_FULL, "sticky_after_dissatisfaction")
    if c.kind in ("system", "farewell", "confirm"):
        return Route(LANE_FULL, c.kind)
    if c.needs_action:
        return Route(LANE_FULL, "needs_action")
    if c.needs_records:
        return Route(LANE_FULL, "needs_records")
    if "followup" in c.signals or c.kind == "followup":
        # "what about for a salon?" means nothing without the conversation,
        # and the fast lane sees only its last few lines (measured live: it
        # answered a question nobody had asked).
        return Route(LANE_FULL, "followup")
    if c.score >= full_min_score():
        return Route(LANE_FULL, f"complexity>={full_min_score():.2f}")
    if c.score <= fast_max_score() and c.confidence >= min_confidence():
        return Route(LANE_FAST, f"{c.kind}:{c.source}")
    if c.source != "heuristic":
        # The classifier has spoken and is still unsure (or said medium).
        return Route(LANE_FULL, "low_confidence")
    return Route(LANE_FULL, "ambiguous", ambiguous=True)


def from_classifier(c: Complexity, verdict: Optional[Dict[str, Any]]) -> Complexity:
    """Fold the Haiku tie-breaker's JSON into the heuristic result. A missing
    or malformed verdict marks the result failed, which routes upward."""
    if not isinstance(verdict, dict):
        return Complexity(max(c.score, 0.5), 0.0, c.kind, c.needs_records, c.needs_action,
                          False, c.signals + ["classifier_failed"], "haiku_failed")
    level = str(verdict.get("complexity") or "").lower()
    s = {"low": 0.15, "medium": 0.5, "high": 0.85}.get(level, 0.5)
    try:
        conf = max(0.0, min(1.0, float(verdict.get("confidence"))))
    except (TypeError, ValueError):
        conf = 0.0
    needs_records = bool(verdict.get("needs_records")) or c.needs_records
    needs_action = bool(verdict.get("needs_action")) or c.needs_action
    kind = c.kind
    if s <= 0.15 and not needs_records and not needs_action and kind in ("unknown", "followup"):
        kind = "general"
    return Complexity(s, conf, kind, needs_records, needs_action,
                      c.cacheable and s <= 0.15 and not needs_records,
                      c.signals + [f"classifier:{level or '?'}"], "haiku")


# ─── The semantic cache ──────────────────────────────────────────────

@dataclass
class CacheHit:
    answer: str
    similarity: float
    model: str
    age_s: float
    cost_cents_saved: float


class SemanticCache:
    """Record-free answers, keyed by the normalised request.

    Only fast-lane answers of kind `general` are ever stored — never a
    turn that read the business or acted on it (docs/inference_layer.md: a
    stale answer about the practitioner's books is the unforgivable
    failure mode), and never social replies, because hearing the identical
    "Anytime!" every time you say thanks is a machine tell.

    Scoped per business AND user: an answer may carry the practitioner's
    name or phrasing. In-process, bounded, TTL'd; a restart empties it,
    which only costs a Haiku call per repeat."""

    def __init__(self, max_entries: int = 4000, ttl_s: Optional[float] = None) -> None:
        self._max = max_entries
        self._ttl = ttl_s
        self._by_scope: "OrderedDict[str, OrderedDict[str, Dict[str, Any]]]" = OrderedDict()
        self._n = 0
        self._lock = threading.Lock()

    def ttl(self) -> float:
        if self._ttl is not None:
            return self._ttl
        return _env_float("ROUTER_CACHE_TTL_S", 86400.0, 60.0, 30 * 86400.0)

    @staticmethod
    def threshold() -> float:
        return _env_float("ROUTER_CACHE_SIMILARITY", 0.8, 0.6, 1.0)

    def get(self, scope: str, text: str, *, now: Optional[float] = None) -> Optional[CacheHit]:
        key = normalize(text)
        if not scope or not key:
            return None
        now = time.time() if now is None else now
        with self._lock:
            entries = self._by_scope.get(scope)
            if not entries:
                return None
            best, best_sim = None, 0.0
            for k, e in list(entries.items()):
                if now - e["at"] > self.ttl():
                    del entries[k]
                    self._n -= 1
                    continue
                sim = 1.0 if k == key else similarity(key, k)
                if sim > best_sim:
                    best, best_sim = e, sim
            if best is None or best_sim < self.threshold():
                return None
            entries.move_to_end(best["key"])
            best["hits"] += 1
            return CacheHit(best["answer"], best_sim, best["model"], now - best["at"],
                            best["cost_cents"])

    def put(self, scope: str, text: str, answer: str, *, model: str = "",
            cost_cents: float = 0.0, now: Optional[float] = None) -> None:
        key = normalize(text)
        if not scope or not key or not (answer or "").strip():
            return
        with self._lock:
            entries = self._by_scope.setdefault(scope, OrderedDict())
            if key not in entries:
                self._n += 1
            entries[key] = {"key": key, "answer": answer, "model": model,
                            "cost_cents": cost_cents, "hits": 0,
                            "at": time.time() if now is None else now}
            entries.move_to_end(key)
            self._by_scope.move_to_end(scope)
            while self._n > self._max and self._by_scope:
                oldest_scope, oldest = next(iter(self._by_scope.items()))
                if oldest:
                    oldest.popitem(last=False)
                    self._n -= 1
                if not oldest:
                    del self._by_scope[oldest_scope]

    def invalidate(self, scope: str) -> None:
        with self._lock:
            gone = self._by_scope.pop(scope, None)
            if gone:
                self._n -= len(gone)

    def __len__(self) -> int:
        return self._n


# ─── What the opening may say ────────────────────────────────────────

# An opening is Chief saying what it is about to do. It has to START that
# way — "let me check…", "I'll draft…", "checking…" — and inside that frame a
# clause like "whether Maria paid" is a question being looked into, not an
# answer. What can still turn it into an unchecked answer is narrow, so that
# is what the gate cuts on: a second clause after a break ("let me check —
# she paid"), a figure the practitioner did not say, a name they did not say,
# and "already". A word blocklist was tried first and cut half of the natural
# openings Haiku wrote ("let me see what's changed" stopped at "changed").
_INTERJECTION_WORDS = (r"sure|okay|ok|got it|of course|absolutely|certainly|alright|"
                       r"all right|right|happy to|will do|you bet|no problem|yes|"
                       r"good question|great question|on it|i'm on it")
# An opening that, once a local lead has said "On it —", adds nothing.
_ECHO_ONLY = re.compile(r"^\s*(?:i'?m\s+)?(?:on it|will do|got it|sure)\s*[.!]?\s*$", re.I)
_INTERJECTION = re.compile(r"^\s*(?:" + _INTERJECTION_WORDS + r")\b[\s,.!—–-]*", re.I)
_INTENT_LEAD = re.compile(
    r"^\s*(?:(?:" + _INTERJECTION_WORDS + r")\b[\s,.!—–-]*)?"
    r"(?:let me|let's|i'll|i will|i'm going to|i am going to|i'm (?:checking|looking|pulling|"
    r"grabbing|getting|on it|digging|writing|drafting|putting)|checking|looking|pulling|"
    r"grabbing|getting|one (?:sec|second|moment)|give me (?:a|one)|on it|working on|"
    r"digging|finding|drafting|writing|putting together|setting|lining|reading|opening)\b",
    re.I)
_CLAUSE_JOIN = re.compile(r"\s+(?:and|but|so|which|since|because|though|although|yet)\b", re.I)
_ALREADY = re.compile(r"\balready\b", re.I)
_SAFE_CAPS = re.compile(r"^(?:I|I'(?:ll|m|d|ve)|Chief|OK|Okay)$")
_MONEYISH = re.compile(r"[$€£%#@]|\d")
_END = re.compile(r"[.!?…]\s*$")


def strip_interjection(text: str) -> str:
    """Drop a leading 'Sure,' / 'Okay —' so it can follow a lead that
    already said one, and lowercase what is left (never 'I')."""
    t = _INTERJECTION.sub("", text or "", count=1)
    if t and t[0].isupper() and not re.match(r"I\b", t):
        t = t[0].lower() + t[1:]
    return t


class OpenerGate:
    """Streams an opening through, and stops at the first point where it
    could become a claim.

    Feed it model text as it arrives; each call returns what is safe to show
    now. Nothing goes out until the first words prove the intent frame
    (about 2 tokens after the model's first); after that, whole words go out
    as they complete. Once `closed`, nothing more is released — the full
    turn's checked answer carries on from what was said. `dangling` is True
    when the cut fell mid-sentence, so the caller can close it with a dash."""

    MAX_WORDS = 14
    LEAD_PROBE_WORDS = 3

    def __init__(self, user_message: str, *, after_lead: bool = False) -> None:
        said = set()
        for w in re.findall(r"\S+", user_message or ""):
            w = w.lower().strip(".,!?;:\"()'").replace("’", "'")
            said.add(w[:-2] if w.endswith("'s") else w)
        self._said = said
        self._pending = ""           # text before the intent frame is proved
        self._buf = ""
        self._framed = False
        self._words = 0
        self.after_lead = after_lead
        self.closed = False
        self.cut_reason: Optional[str] = None
        self.text = ""

    @property
    def dangling(self) -> bool:
        return bool(self.text.strip()) and not _END.search(self.text) \
            and not self.text.rstrip().endswith(("—", "–"))

    def feed(self, piece: str) -> str:
        if self.closed or not piece:
            return ""
        if not self._framed:
            self._pending += piece
            probe = strip_interjection(self._pending) if self.after_lead else self._pending
            words = re.findall(r"[A-Za-z']+(?=[\s,.!?;:—–-])", probe)   # whole words only
            enough = (len(words) >= self.LEAD_PROBE_WORDS + 1
                      or bool(re.search(r"[.!?]\s*$", probe)))
            if self.after_lead and _ECHO_ONLY.match(self._pending):
                if re.search(r"[.!?]\s*$", self._pending):
                    self.close("echo_of_lead")
                return ""
            if not _INTENT_LEAD.match(probe):
                if enough or len(probe) > 40:
                    self.close("no_intent_lead")
                return ""
            self._framed = True
            self._pending = ""
            piece = probe
        self._buf += piece
        return self._release(final=False)

    def _release(self, *, final: bool) -> str:
        out: List[str] = []
        if self.after_lead and not self.text and self._buf:
            # Framed before the lead went out but not yet shown ("Pulling"
            # still growing when the deadline came): it now follows the lead.
            self._buf = strip_interjection(self._buf.lstrip())
        while not self.closed and self._buf:
            m = re.match(r"(\s*)(\S+)(\s|$)", self._buf)
            if not m or (not m.group(3) and not final):
                break                       # the last word may still be growing
            ws, word = m.group(1), m.group(2)
            nxt = self._buf[m.end(2):]
            if word.endswith(",") and not final and not re.match(r"\s+\S+\s", nxt):
                break                       # a comma: wait to see what joins it
            why = self._word_problem(word, not self.text)
            if why:
                self.close(why)
                break
            if self._words >= self.MAX_WORDS:
                self.close("length")
                break
            # A second clause starting after this word ("…that, and she paid",
            # "…check: she paid") is where an opening turns into an answer.
            # Stop at the word, without its comma or colon.
            second_clause = (word.endswith((";", ":"))
                             or (word.endswith(",") and _CLAUSE_JOIN.match(nxt)))
            if second_clause:
                word = word[:-1]
            is_dash = word in ("—", "–", "-", "--")
            lead_dash = is_dash and bool(re.fullmatch(
                r"\s*(?:" + _INTERJECTION_WORDS + r")\s*", self.text, re.I))
            chunk = (ws if self.text else "") + word
            self.text += chunk
            self._words += 0 if is_dash else 1
            out.append(chunk)
            self._buf = nxt
            if _END.search(word):
                self.close("sentence_end")
            elif second_clause:
                self.close("clause_break")
            elif is_dash and not lead_dash:
                # "I'll grab that —": the dash stays; it reads as a pause.
                self.close("clause_break")
        return "".join(out)

    def _word_problem(self, word: str, first: bool) -> Optional[str]:
        bare = word.strip(".,!?;:\"()—–-…").replace("’", "'")
        if not bare:
            return None
        low = bare.lower()
        low_base = low[:-2] if low.endswith("'s") else low
        if _MONEYISH.search(bare) and low_base not in self._said:
            return "figure"
        if _ALREADY.fullmatch(low):
            return "already"
        if (bare[0].isupper() and not first and not _SAFE_CAPS.match(bare)
                and low_base not in self._said):
            return f"name:{bare}"
        return None

    def finish(self) -> str:
        """The model stopped: release the last word if it is safe."""
        if self.closed:
            return ""
        if not self._framed:
            self.close("no_intent_lead")
            return ""
        out = self._release(final=True)
        self.close(self.cut_reason or "model_end")
        return out

    def close(self, reason: str = "closed") -> None:
        if not self.closed:
            self.closed = True
            self.cut_reason = self.cut_reason or reason


# ─── What a fast-lane answer may say ─────────────────────────────────

NEED_RECORDS = "NEED_RECORDS"
_DEFLECT_LEAD = re.compile(
    r"^\W*(?:NEED_RECORDS|I (?:don'?t|do not|can'?t|cannot|am unable|'m unable|'m not able|"
    r"am not able|have no|haven'?t)|I'?m (?:not sure|sorry|afraid)|Unfortunately|Sorry|"
    r"As an AI|I would need|I'd need|I need (?:to|more)|To answer (?:that|this)|"
    r"Could you (?:clarify|tell me|share)|Can you (?:clarify|tell me|share))", re.I)
_COMPLETION = re.compile(
    r"\b(?:I(?:'ve| have)? (?:just )?(?:sent|added|booked|scheduled|created|updated|saved|"
    r"deleted|cancel+ed|changed|set up|emailed|texted|posted|published|logged|recorded|"
    r"marked|moved|removed|drafted)|(?:it'?s|that'?s|all) (?:done|set|sent|booked)|"
    r"done[.!])", re.I)
_BUSINESS_CLAIM = re.compile(
    r"\byou(?:'ve| have)(?: got)? (?:\d|a few|several|no|some|many|\w+ (?:clients|invoices|"
    r"bookings|leads|appointments|customers))|\byour (?:revenue|sales|income|clients?|"
    r"customers?|invoices?|bookings?|calendar|schedule|inbox|balance|site|website|leads?)"
    r" (?:is|are|was|were|has|have|shows?)\b", re.I)
_THIN = re.compile(
    r"\b(?:I don'?t have (?:access|that|your|the)|I can'?t (?:see|access|check|look)|"
    r"I'?m (?:not able|unable) to|I don'?t know|I'?m not sure|check (?:your|with)|"
    r"you(?:'ll| will)? (?:need|want) to (?:check|look|ask)|in your records|"
    r"I (?:would|'d) need (?:more|to)|" + NEED_RECORDS + r")\b", re.I)


class AnswerGate:
    """Streams a fast-lane answer.

    Its first words are held until they show the reply is not a deflection,
    so "I don't have access to your calendar" escalates to the full turn
    before anyone sees it. After that the last few words are always held
    back: the claims the fast lane cannot make ("I've just sent…", "your
    revenue is…") are only recognisable once whole, and by then their first
    word must not already be on screen."""

    LEAD_WORDS = 3
    TAIL_WORDS = 4

    def __init__(self) -> None:
        self._pending = ""          # generated, not yet shown
        self._lead_ok = False
        self.text = ""              # shown
        self.closed = False
        self.escalate: Optional[str] = None     # set → hand the turn to Sonnet

    def feed(self, piece: str) -> str:
        if self.closed or not piece:
            return ""
        self._pending += piece
        if not self._lead_ok:
            if _DEFLECT_LEAD.match(self._pending):
                self._stop("deflection")
                return ""
            if len(self._pending.split()) <= self.LEAD_WORDS:
                return ""
            self._lead_ok = True
        return self._release(final=False)

    def _release(self, *, final: bool) -> str:
        window = self.text[-160:] + self._pending
        base = len(window) - len(self._pending)      # where _pending starts
        m = _COMPLETION.search(window) or _BUSINESS_CLAIM.search(window)
        if m and m.end() > base:
            upto = max(0, m.start() - base)
            keep = self._pending[:upto]
            b = max(keep.rfind(". "), keep.rfind("! "), keep.rfind("? "), keep.rfind("\n"))
            keep = keep[: b + 1] if b >= 0 else keep.rstrip()
            self.text += keep
            self._pending = ""
            self._stop("claim")
            return keep
        if final:
            out, self._pending = self._pending, ""
        else:
            # Release all but the last TAIL_WORDS words (and a word in progress).
            spans = [mm.start() for mm in re.finditer(r"\S+", self._pending)]
            if len(spans) <= self.TAIL_WORDS:
                return ""
            cut = spans[-self.TAIL_WORDS]
            out, self._pending = self._pending[:cut], self._pending[cut:]
        self.text += out
        return out

    def finish(self) -> str:
        if self.closed:
            return ""
        if not self._lead_ok and _DEFLECT_LEAD.match(self._pending):
            self._stop("deflection")
            return ""
        self._lead_ok = True
        out = self._release(final=True)
        self.closed = True
        return out

    def _stop(self, reason: str) -> None:
        self.closed = True
        self.escalate = self.escalate or reason


def looks_thin(answer: str, c: Complexity, *, stop_reason: str = "") -> Optional[str]:
    """Why a finished fast-lane answer is not good enough, or None."""
    a = (answer or "").strip()
    if not a:
        return "empty"
    if stop_reason == "max_tokens":
        return "truncated"
    if stop_reason == "refusal":
        return "refusal"
    if _THIN.search(a):
        return "hedged"
    if c.kind == "general" and len(a.split()) < 4:
        return "too_short"
    return None


# ─── Local leads (the budget's floor) ────────────────────────────────

_LEADS = {
    "social": "Of course —",
    "general": "Sure —",
    "action": "On it —",
    "draft": "On it —",
}


def local_lead(kind: str) -> str:
    """The words that go out when no model has spoken by the deadline. An
    interjection and nothing else: it composes with whatever follows it, and
    it cannot be wrong."""
    return _LEADS.get(kind or "", "Okay —")
