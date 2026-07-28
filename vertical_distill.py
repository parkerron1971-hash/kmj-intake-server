"""
vertical_distill.py — Feed 2. What one salon learns, the next salon knows.

LAYER_TWO_ARCHITECTURE.md §6 calls this the moat: "every lawyer who uses
the platform makes the next lawyer's experience better." Until now it did
not exist — every memory in the system is business_id-scoped, so learning
compounded inside one tenant and stopped there.

This job reads what businesses in the same vertical have taught Chief,
distils it into patterns, and writes them to vertical_knowledge where the
next business in that vertical retrieves them on day one.

═══════════════════════════════════════════════════════════════════════
THE PRIVACY DESIGN — read this before changing anything below
═══════════════════════════════════════════════════════════════════════
The feature is worth a great deal and one leak would end it, so the
defences are structural rather than careful.

1. K-ANONYMITY IS THE PRIMARY CONTROL.
   A pattern is only written if at least MIN_BUSINESSES distinct
   businesses show it. A thing only one salon does cannot become a row,
   which means a row cannot carry one salon's specifics even if every
   other defence failed. This is checked on the EVIDENCE, before the
   model ever sees it — not on the output, where it would be a filter
   rather than a guarantee.

2. THE MODEL NEVER SEES A CUSTOMER MESSAGE.
   Evidence is drawn from structural signals — which proposal types get
   accepted, which situations recur, which categories get corrected to
   which — not from message bodies. `chief_templates.body` is deliberately
   NOT read. The most valuable-looking source is the most dangerous one.

3. WHAT REMAINS IS SCRUBBED ANYWAY.
   Situation strings are short and practitioner-written, but they can
   still contain a name or a number. `_scrub()` runs over everything on
   the way in, and it strips aggressively — a mangled pattern is a cost
   worth paying.

4. CONTRIBUTION IS CONSENSUAL AND REVOCABLE.
   `settings.feed2.contribute` — on by default (Kevin's ruling
   2026-07-27), off with one toggle, honoured on the READ side so
   switching it off stops future contribution immediately.

5. OUTPUT IS BOUNDED AND AUDITABLE.
   Rows carry `evidence_count` and `source='learned'`, so anything that
   turns out wrong can be found, deactivated, and explained.

FAILS OPEN. No key, no table, no evidence, model refuses → writes nothing
and returns a zero report. Nothing downstream depends on it having run.
Kill switch: FEED2=off.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import httpx

import chief_models
import llm_call
import sb_clients
import vertical_knowledge as vk

logger = logging.getLogger("vertical_distill")

# The k-anonymity floor. Three is the smallest number for which "several
# businesses do this" is a fair description; below it, a pattern is one
# business's habit wearing a plural.
#
# THIS NUMBER IS LOAD-BEARING ON A PROMISE MADE TO PRACTITIONERS.
# Settings → Chief & agents tells them "your clients, your messages, and
# your numbers never leave your account." Two thirds of that is
# structural: message bodies are never read, and _scrub strips numbers.
# CLIENT NAMES ARE NOT. _scrub cannot reliably recognise a name, and the
# fields that do get used (a template's `situation`, an override reason)
# are practitioner-written free text.
#
# What actually protects a name is this floor: it can only travel if
# MIN_BUSINESSES separate businesses independently wrote the identical
# string containing it. At 3 that is vanishingly unlikely. At 1 it is
# certain. So lowering this does not merely weaken a heuristic — it makes
# a sentence in the product UI untrue. Raise it freely; do not lower it
# without changing that copy first.
MIN_BUSINESSES = 3

# How far back evidence is gathered, and how much of it reaches the model.
LOOKBACK_DAYS = 90
MAX_EVIDENCE_PER_VERTICAL = 120
MAX_PATTERNS_PER_RUN = 8

# Per-tick cap: one vertical per run keeps model spend flat and bounded.
_TICK_STATE_KEY = "feed2_last_vertical"


def _enabled() -> bool:
    if (os.environ.get("FEED2") or "on").strip().lower() == "off":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ─── consent ─────────────────────────────────────────────────────────

def contributes(business: Dict[str, Any]) -> bool:
    """Does this business contribute its patterns to its vertical?

    Default TRUE (Kevin's ruling 2026-07-27: on by default with an off
    switch). Read defensively — a malformed settings blob means the
    business is treated as contributing, which matches the default, but
    an explicit false always wins."""
    settings = (business or {}).get("settings") or {}
    if not isinstance(settings, dict):
        return True
    feed2 = settings.get("feed2")
    if isinstance(feed2, dict) and "contribute" in feed2:
        return bool(feed2.get("contribute"))
    if "feed2_contribute" in settings:      # flat form, tolerated
        return bool(settings.get("feed2_contribute"))
    return True


# ─── scrubbing ───────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\.\(\) ]{7,}\d)")
_URL_RE = re.compile(r"https?://\S+")
_MONEY_RE = re.compile(r"[$£€]\s?\d[\d,]*(?:\.\d{2})?")
_LONGNUM_RE = re.compile(r"\b\d{4,}\b")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")


def _scrub(text: str) -> str:
    """Strip the obvious identifiers out of a fragment before it is used
    as evidence. Aggressive on purpose: a pattern that reads a little
    mangled is a far better outcome than one carrying a phone number."""
    t = (text or "")
    t = _URL_RE.sub("[link]", t)
    t = _EMAIL_RE.sub("[email]", t)
    t = _PHONE_RE.sub("[phone]", t)
    t = _MONEY_RE.sub("[amount]", t)
    t = _DATE_RE.sub("[date]", t)
    t = _LONGNUM_RE.sub("[number]", t)
    return " ".join(t.split())[:180]


# ─── evidence gathering ──────────────────────────────────────────────

def _businesses_by_vertical() -> Dict[str, List[str]]:
    """Contributing businesses, grouped by canonical vertical."""
    try:
        rows = sb_clients.sb_get_as_service(
            "/businesses?select=id,type,settings&limit=2000") or []
    except Exception as e:
        logger.warning(f"[feed2] business scan failed: {e}")
        return {}

    import vertical_registry as reg
    alias = reg.alias_to_canonical()

    out: Dict[str, List[str]] = defaultdict(list)
    for b in rows:
        if not contributes(b):
            continue
        key = alias.get((b.get("type") or "").strip().lower())
        if key:
            out[key].append(b["id"])
    return dict(out)


def _gather(business_ids: List[str]) -> Dict[str, Any]:
    """Structural signals only. Note what is absent: no message bodies, no
    contact rows, no invoice amounts. The richest-looking source —
    chief_templates.body, real messages that worked — is exactly the one
    that must not be read, so it is not."""
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    id_list = ",".join(business_ids)

    situations: Dict[str, Set[str]] = defaultdict(set)   # text -> business ids
    corrections: Dict[str, Set[str]] = defaultdict(set)
    proposal_outcomes: Dict[str, Set[str]] = defaultdict(set)

    # Which SITUATIONS recur, and how widely. Situation + kind only.
    try:
        rows = sb_clients.sb_get_as_service(
            f"/chief_templates?business_id=in.({id_list})"
            f"&select=business_id,kind,situation,uses&limit=600") or []
        for r in rows:
            sit = _scrub(r.get("situation") or "")
            if sit:
                situations[f"{r.get('kind')}: {sit}"].add(r["business_id"])
    except Exception as e:
        logger.info(f"[feed2] template scan skipped: {e}")

    # Where Chief was WRONG and the practitioner corrected it. The single
    # most valuable signal in the system, and structurally safe: it is a
    # proposal type plus a reason, never a customer record.
    try:
        rows = sb_clients.sb_get_as_service(
            f"/chief_learning_signals?business_id=in.({id_list})"
            f"&created_at=gte.{since}"
            f"&select=business_id,proposal_type,override_reason&limit=600") or []
        for r in rows:
            reason = _scrub(r.get("override_reason") or "")
            if reason:
                corrections[f"{r.get('proposal_type')}: {reason}"].add(r["business_id"])
    except Exception as e:
        logger.info(f"[feed2] learning-signal scan skipped: {e}")

    # Which proposal types practitioners actually accept.
    try:
        rows = sb_clients.sb_get_as_service(
            f"/chief_proposals?business_id=in.({id_list})"
            f"&created_at=gte.{since}"
            f"&select=business_id,proposal_type,status&limit=800") or []
        for r in rows:
            if r.get("status"):
                proposal_outcomes[
                    f"{r.get('proposal_type')} → {r.get('status')}"
                ].add(r["business_id"])
    except Exception as e:
        logger.info(f"[feed2] proposal scan skipped: {e}")

    return {"situations": situations, "corrections": corrections,
            "proposals": proposal_outcomes}


def _k_anonymous(buckets: Dict[str, Set[str]]) -> List[Dict[str, Any]]:
    """Keep only what MIN_BUSINESSES or more distinct businesses show.

    This runs on the EVIDENCE, before the model sees any of it. Filtering
    the model's OUTPUT instead would be a filter; filtering the input is a
    guarantee — the model is never in a position to generalise from one
    tenant, because it is never shown one tenant."""
    kept = []
    for text, biz_ids in buckets.items():
        if len(biz_ids) >= MIN_BUSINESSES:
            kept.append({"signal": text, "businesses": len(biz_ids)})
    kept.sort(key=lambda d: -d["businesses"])
    return kept


# ─── distillation ────────────────────────────────────────────────────

_SYSTEM = """You are distilling operating patterns for a category of small business.

You are given SIGNALS. Each is something observed across several different \
businesses of the same type, with a count of how many showed it. You never see \
any individual business, customer, or message — by design.

Write general, useful patterns another business of this type could act on.

RULES — a violation makes the output unusable:
- Every pattern must be true of the CATEGORY, never of one business.
- Never invent a statistic. If you write a comparison, it must follow from \
the counts you were given.
- No names, no amounts, no dates, no quoted messages. If a signal contains \
one, generalise past it.
- One sentence each. Concrete and actionable, not motivational.
- If the signals are too thin to support a real pattern, return fewer. \
Returning an empty list is a correct answer.

Return ONLY JSON: {"patterns": [{"content": "...", "confidence": 0.0-1.0}]}"""


def _distil(vertical: str, evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ask the model for patterns. Returns [] on anything unexpected."""
    if not evidence:
        return []
    lines = [f"- {e['signal']}  (seen at {e['businesses']} businesses)"
             for e in evidence[:MAX_EVIDENCE_PER_VERTICAL]]
    user = (f"Business type: {vertical}\n\n"
            f"SIGNALS:\n" + "\n".join(lines) +
            f"\n\nReturn at most {MAX_PATTERNS_PER_RUN} patterns.")

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = llm_call.post_with(client, {
                "model": chief_models.model_for("background"),
                "max_tokens": 1200,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": user}],
            }, task="vertical_distill")
        if resp.status_code >= 400:
            logger.warning(f"[feed2] distil {resp.status_code}: {resp.text[:160]}")
            return []
        text = "".join(b.get("text", "") for b in resp.json().get("content", []))
    except Exception as e:
        logger.warning(f"[feed2] distil failed: {e}")
        return []

    try:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return []
        payload = json.loads(text[start:end + 1])
    except Exception:
        return []

    out = []
    for p in (payload.get("patterns") or [])[:MAX_PATTERNS_PER_RUN]:
        content = _scrub(str(p.get("content") or ""))
        if len(content) < 15:          # too short to be a real pattern
            continue
        try:
            conf = float(p.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        out.append({"content": content, "confidence": max(0.0, min(1.0, conf))})
    return out


# ─── the job ─────────────────────────────────────────────────────────

def run_for_vertical(vertical: str) -> Dict[str, Any]:
    """Distil one vertical now. The unit of work; `tick()` picks which."""
    report = {"vertical": vertical, "businesses": 0, "signals": 0,
              "patterns": 0, "written": 0, "skipped": None}
    if not _enabled():
        report["skipped"] = "disabled"
        return report

    groups = _businesses_by_vertical()
    biz_ids = groups.get(vertical) or []
    report["businesses"] = len(biz_ids)

    # Not enough contributing businesses to say anything about the
    # category without saying something about one of them.
    if len(biz_ids) < MIN_BUSINESSES:
        report["skipped"] = f"only {len(biz_ids)} contributing businesses"
        return report

    ev = _gather(biz_ids)
    signals = (_k_anonymous(ev["situations"])
               + _k_anonymous(ev["corrections"])
               + _k_anonymous(ev["proposals"]))
    report["signals"] = len(signals)
    if not signals:
        report["skipped"] = "no signal cleared the k-anonymity floor"
        return report

    patterns = _distil(vertical, signals)
    report["patterns"] = len(patterns)

    # evidence_count records how many businesses stood behind the WEAKEST
    # signal used, so the number on the row is a floor, not a flattering
    # maximum.
    floor = min((s["businesses"] for s in signals), default=MIN_BUSINESSES)
    for p in patterns:
        if vk.upsert(vertical, vk.KIND_PATTERN, p["content"],
                     source=vk.SOURCE_LEARNED,
                     confidence=p["confidence"],
                     evidence_count=floor):
            report["written"] += 1

    logger.info(f"[feed2] {vertical}: {report['written']} patterns from "
                f"{report['signals']} signals across {len(biz_ids)} businesses")
    return report


def tick() -> Dict[str, Any]:
    """Scheduler entry point. One vertical per run, rotating — keeps model
    spend flat and predictable no matter how many verticals exist."""
    if not _enabled():
        return {"skipped": "disabled"}
    groups = _businesses_by_vertical()
    eligible = sorted(v for v, ids in groups.items() if len(ids) >= MIN_BUSINESSES)
    if not eligible:
        return {"skipped": "no vertical has enough contributing businesses"}

    # Rotate by day so every eligible vertical comes round without needing
    # state anywhere. Deterministic, and survives a restart.
    idx = datetime.now(timezone.utc).toordinal() % len(eligible)
    return run_for_vertical(eligible[idx])
