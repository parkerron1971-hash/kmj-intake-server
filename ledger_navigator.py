"""
ledger_navigator.py — the portal agent. A GUIDE, never a NARRATOR.

Someone opens the ledger because they think something went wrong. They
do not know a verb name or a sequence number; they know "the invoices
for that client last July" or "whatever happened the night the bookings
disappeared". This turns that sentence into a FILTER over real rows and
walks them to it.

THE RULE THAT CANNOT BEND:

    It finds and filters. It never interprets, summarises, or stands
    between the reader and the raw record.

The moment this thing says "here's what happened, trust my summary", the
ledger stops being a proof and becomes another thing you take on faith —
which defeats the entire product. So, concretely:

  * every answer resolves to a filter, rendered against real rows;
  * it may state WHAT FILTER it applied and why that filter;
  * it may NOT state what the records mean, whether they look fine,
    whether anything is wrong, or what probably happened;
  * no "nothing unusual here" — that is a conclusion, and drawing it is
    the reader's job, especially when the reader is an auditor;
  * the model never sees the row CONTENTS. It sees the question and the
    vocabulary, and it returns a filter. It cannot summarise data it was
    never given, which is a stronger guarantee than asking it not to.

That last point is the design: the restraint is structural, not a
prompt instruction that a clever question could talk its way past.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ledger_navigator")

NAV_MODEL = "claude-haiku-4-5-20251001"     # cheap: this is a parser, not a thinker
MAX_TOKENS = 400

# What the model is allowed to emit. Anything else is dropped rather
# than trusted — an unknown key is a hallucinated filter.
_ALLOWED = {"since", "until", "verb", "actor", "subject_id", "failed_only",
            "include_db", "limit"}

_SYSTEM = """You convert a question about a business action log into a FILTER.

You are a search box, not an analyst. You never explain events, never
summarise, never say whether anything looks wrong. You only choose which
records to show.

Return ONLY a JSON object with any of these keys:
  since        ISO8601 UTC start, e.g. "2026-07-01T00:00:00Z"
  until        ISO8601 UTC end
  verb         one exact verb from the vocabulary given below
  actor        one of: chief, user, system, agent, scheduler, trust-track, workflow
  subject_id   an id fragment the user named (an invoice/contact id)
  failed_only  true when they ask about failures, errors, or things not working
  include_db   true when they ask about direct record changes/edits
  limit        integer up to 500

Omit any key you are not confident about. An absent filter shows more
records, which is safe. A guessed filter HIDES records, which is not.
Return {} if the question names no filter at all.

Never invent a verb that is not in the vocabulary."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def deterministic_filter(question: str) -> Dict[str, Any]:
    """Ranges we can resolve without a model. Runs FIRST, and the model
    never overrides what this finds — "last 7 days" has one meaning and
    it is not worth a token or a hallucination."""
    q = (question or "").lower()
    out: Dict[str, Any] = {}
    now = _now()

    if re.search(r"\b(today)\b", q):
        out["since"] = _iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
    elif re.search(r"\byesterday\b", q):
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        out["since"], out["until"] = _iso(start), _iso(start + timedelta(days=1))
    elif m := re.search(r"\blast (\d{1,3}) days?\b", q):
        out["since"] = _iso(now - timedelta(days=int(m.group(1))))
    elif re.search(r"\b(this week|past week|last week)\b", q):
        out["since"] = _iso(now - timedelta(days=7))
    elif re.search(r"\b(this month|past month|last month)\b", q):
        out["since"] = _iso(now - timedelta(days=30))

    # Plurals matter: "show me errors" is the commonest phrasing of this
    # question and \berror\b does not match it.
    if re.search(r"\b(fail\w*|error\w*|didn'?t work|broke|broken|went wrong)\b", q):
        out["failed_only"] = True
    if re.search(r"\b(edit\w*|chang\w*|delet\w*|remov\w*|record changes?)\b", q):
        out["include_db"] = True
    return out


def _vocabulary(limit: int = 120) -> List[str]:
    """The verbs this business could actually have used. Given to the
    model so it selects rather than invents."""
    try:
        import action_registry
        return sorted(action_registry.REGISTRY.keys())[:limit]
    except Exception:
        return []


def _sanitize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only known keys with sane values. A filter is a claim about
    what the reader should see; an unvalidated one silently hides rows."""
    out: Dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    vocab = set(_vocabulary(1000))
    for k, v in raw.items():
        if k not in _ALLOWED or v in (None, "", []):
            continue
        if k in ("since", "until"):
            s = str(v).strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}", s):
                out[k] = s.replace("+00:00", "Z")
        elif k == "verb":
            if str(v) in vocab or str(v).startswith(("db:", "rules:", "webhook:", "job:", "ledger:")):
                out[k] = str(v)[:80]
        elif k == "actor":
            if str(v) in ("chief", "user", "system", "agent", "scheduler",
                          "trust-track", "workflow"):
                out[k] = str(v)
        elif k == "subject_id":
            out[k] = re.sub(r"[^A-Za-z0-9\-]", "", str(v))[:80] or None
            if not out[k]:
                out.pop("subject_id", None)
        elif k in ("failed_only", "include_db"):
            out[k] = bool(v)
        elif k == "limit":
            try:
                out[k] = max(1, min(int(v), 500))
            except (TypeError, ValueError):
                pass
    return out


def describe(f: Dict[str, Any]) -> str:
    """State the FILTER, in plain words. This is the only sentence the
    navigator is permitted to produce, and it is about the search — never
    about the records."""
    if not f:
        return "Showing everything recorded, most recent first."
    parts: List[str] = []
    if f.get("failed_only"):
        parts.append("only actions that failed")
    if f.get("verb"):
        parts.append(f"the action “{f['verb']}”")
    if f.get("actor"):
        parts.append(f"things done by {f['actor']}")
    if f.get("subject_id"):
        parts.append(f"records touching {f['subject_id']}")
    when = ""
    if f.get("since") and f.get("until"):
        when = f" between {f['since'][:10]} and {f['until'][:10]}"
    elif f.get("since"):
        when = f" since {f['since'][:10]}"
    elif f.get("until"):
        when = f" up to {f['until'][:10]}"
    body = ", ".join(parts) if parts else "everything recorded"
    tail = ", including direct record changes" if f.get("include_db") else ""
    return f"Showing {body}{when}, most recent first{tail}."


def resolve(question: str, *, use_model: bool = True) -> Dict[str, Any]:
    """question -> {filter, description, model_used}.

    The model NEVER sees ledger rows — only the question and the verb
    vocabulary. It cannot summarise records it was never given, which is
    why the no-narration rule holds structurally rather than by asking
    nicely.
    """
    base = deterministic_filter(question)
    model_used = False

    if use_model and (question or "").strip():
        try:
            import llm_call
            vocab = _vocabulary()
            resp = llm_call.post({
                "model": NAV_MODEL,
                "max_tokens": MAX_TOKENS,
                "system": _SYSTEM + "\n\nVocabulary:\n" + ", ".join(vocab),
                "messages": [{"role": "user", "content": str(question)[:600]}],
            }, task="ledger_navigator", timeout=20.0)
            if resp.status_code < 400:
                text = llm_call.text_of(resp.json())
                m = re.search(r"\{.*\}", text, re.S)
                if m:
                    parsed = _sanitize(json.loads(m.group(0)))
                    # Deterministic wins: a resolved date range is not a
                    # matter of opinion.
                    parsed.update(base)
                    base = parsed
                    model_used = True
        except Exception as e:
            logger.info(f"[navigator] model unavailable, using literal filter: {e}")

    return {"filter": base, "description": describe(base), "model_used": model_used}
