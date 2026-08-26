"""
chief_sms_actions.py — the texting SETUP verbs.

THE GAP THIS CLOSES: Chief could send a text and mark one read. It could
not do any of the things that make texting work in the first place.

  THE KEYWORD. One Twilio number serves the whole platform, so an inbound
  text is routed by the word the client sends first: the keyword claims
  the binding, the binding sustains it (sms_routing's whole model). There
  is an endpoint to claim one and a regex to validate it, and no verb. A
  practitioner who said "set up texting for me" reached a dead end at the
  only step that matters — without a keyword, a client texting the number
  is routed to nobody and gets the help reply.

  THE ALERT SWITCH. `sms_alerts` reads
  `businesses.settings.sms_alerts = {confirmations, reminders}` and its
  own docstring says the toggle is "Honored via Chief/settings edits
  today; frontend toggle can come later." Nothing in this codebase writes
  that key — not Chief, not a router, not the frontend. Both alerts
  default TRUE when the key is absent, so every business on the platform
  sends automated booking confirmations and 24-hour reminders and no
  practitioner has ever been able to turn them off. That is the wrong way
  round for a control whose entire purpose is restraint: a practitioner
  who says "stop texting my clients reminders" was owed an answer and had
  none.

WHY THERE IS NO `broadcast_sms`
  `/sms/broadcast` exists and texts up to 500 contacts. It is deliberately
  NOT wrapped as a verb. It gates on opt-out only — it never calls
  `sms_alerts.has_sms_consent` — while `campaigns_router` runs the same
  bulk traffic through the consent check, quiet hours, and a per-touch
  audience. Giving Chief a one-line verb pointing at the weaker of two
  paths would make the weaker one the default, because a verb is what the
  model reaches for. Bulk SMS belongs to campaigns, and the prompt says so.

TRUST-LAYER DISCIPLINE:
  • What changes? One `sms_keywords` row, or one key inside
    `businesses.settings`. Nothing is sent. No client is contacted.
  • Seen first? Both verbs report the state they are changing FROM, so a
    keyword change names the old word and an alert switch names what it
    was — the practitioner can read what happened and put it back.
  • Reversible? Class A. A keyword is re-claimable and a toggle is a
    toggle. `sms_status` writes nothing at all.
  • Ambiguity is refused. A keyword already claimed by someone else is
    refused with the reason, never silently suffixed into something free.

Return shape: every handler returns {type, result, label, …, nav}. `result`
and `label` are NON-NEGOTIABLE — the frontend action card calls
.toLowerCase() on them and a missing key blanks the app.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("chief_sms_actions")

# The two automated legs sms_alerts owns. Named here so a typo in an
# action is refused rather than written as a key nothing ever reads.
ALERT_KINDS = ("confirmations", "reminders")

_ON_WORDS = {"on", "true", "yes", "y", "1", "enable", "enabled", "resume"}
_OFF_WORDS = {"off", "false", "no", "n", "0", "disable", "disabled",
              "stop", "pause"}


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    logger.info(f"Action {action_type} failed: {msg}")
    # "failed": True is the machine-readable seam _action_failed reads —
    # without it a failure here is audited and narrated as a success.
    return {
        "type": action_type,
        "result": msg,
        "label": action_type,
        "nav": None,
        "failed": True,
    }


def _nav_sms() -> Dict[str, Any]:
    return {"tab": "operate", "sub": "sms"}


def _coerce_switch(value: Any) -> Optional[bool]:
    """Accept the many shapes of "turn it off" — or None when unreadable."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    word = str(value).strip().lower()
    if word in _ON_WORDS:
        return True
    if word in _OFF_WORDS:
        return False
    return None


# ─── keyword ──────────────────────────────────────────────────────────

def _current_keyword(business_id: str) -> Optional[str]:
    rows = sb_clients.sb_get_as_service(
        f"/sms_keywords?business_id=eq.{business_id}&select=keyword&limit=1") or []
    return rows[0].get("keyword") if rows else None


def _keyword_owner(word: str) -> Optional[str]:
    rows = sb_clients.sb_get_as_service(
        f"/sms_keywords?keyword=eq.{word}&select=business_id&limit=1") or []
    return rows[0].get("business_id") if rows else None


async def handle_set_sms_keyword(client, biz, action) -> Dict[str, Any]:
    """Claim or change the word a client texts to reach this business."""
    import sms_routing

    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("set_sms_keyword", "no business on record")

    word = str(action.get("keyword") or action.get("word")
               or action.get("value") or "").strip().upper()
    if not word:
        return _fail("set_sms_keyword",
                     "What word should clients text? 3-20 letters or numbers "
                     "— usually the business name.")

    # The routing module owns both rules; borrowing them keeps one
    # definition of what a legal keyword is.
    if not sms_routing.KEYWORD_RE.match(word):
        return _fail("set_sms_keyword",
                     f"'{word}' won't work as a keyword — it needs to be 3-20 "
                     f"letters or numbers, no spaces or punctuation.")
    if word in sms_routing.RESERVED_WORDS:
        return _fail("set_sms_keyword",
                     f"'{word}' is reserved by the phone carriers (it means "
                     f"something to them), so it can't be used. Pick another.")

    owner = await asyncio.to_thread(_keyword_owner, word)
    if owner and str(owner) != business_id:
        return _fail("set_sms_keyword",
                     f"'{word}' is already taken by another business on the "
                     f"platform. Pick another.")

    previous = await asyncio.to_thread(_current_keyword, business_id)
    if previous == word:
        return {
            "type": "set_sms_keyword",
            "result": f"'{word}' is already your keyword — nothing to change.",
            "label": f"Text keyword: {word}",
            "keyword": word,
            "nav": _nav_sms(),
        }

    try:
        if previous is not None:
            await asyncio.to_thread(
                sb_clients.sb_patch_as_service,
                f"/sms_keywords?business_id=eq.{business_id}", {"keyword": word})
        else:
            await asyncio.to_thread(
                sb_clients.sb_post_as_service, "/sms_keywords",
                {"business_id": business_id, "keyword": word})
    except Exception as e:
        logger.exception(f"set_sms_keyword write failed: {e}")
        return _fail("set_sms_keyword",
                     "I couldn't save that keyword just now — try again in a moment.")

    if previous:
        # SAY WHAT BREAKS. Anyone who already texted the old word keeps
        # their binding, but printed cards and signs carrying it stop
        # working for new clients, and that is not obvious.
        result = (f"Keyword changed from '{previous}' to '{word}'. Clients "
                  f"who already texted you stay connected, but anywhere "
                  f"'{previous}' is printed will need updating.")
    else:
        result = (f"'{word}' is yours. Clients text {word} to your number and "
                  f"they're connected to you — that's what puts their replies "
                  f"in your Inbox instead of nowhere.")

    return {
        "type": "set_sms_keyword",
        "result": result,
        "label": f"Text keyword: {word}",
        "keyword": word,
        "previous_keyword": previous,
        "nav": _nav_sms(),
    }


# ─── automated alerts ─────────────────────────────────────────────────

async def handle_set_sms_alerts(client, biz, action) -> Dict[str, Any]:
    """Turn the automated booking confirmations and 24-hour reminders on
    or off for this business."""
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("set_sms_alerts", "no business on record")

    # Which legs the practitioner meant. Naming neither means both —
    # "stop texting my clients" is the common ask and it means all of it.
    requested: Dict[str, bool] = {}
    for kind in ALERT_KINDS:
        switch = _coerce_switch(action.get(kind))
        if switch is not None:
            requested[kind] = switch

    if not requested:
        blanket = _coerce_switch(
            action.get("on") if action.get("on") is not None
            else action.get("enabled") if action.get("enabled") is not None
            else action.get("value"))
        kinds = action.get("kinds") or action.get("kind")
        if isinstance(kinds, str):
            kinds = [kinds]
        if blanket is None:
            return _fail("set_sms_alerts",
                         "On or off? I can switch booking confirmations and "
                         "appointment reminders either way, together or "
                         "separately.")
        targets = ALERT_KINDS
        if kinds:
            targets = tuple(str(k).strip().lower() for k in kinds)
            unknown = [k for k in targets if k not in ALERT_KINDS]
            if unknown:
                return _fail("set_sms_alerts",
                             f"I don't have an alert called '{unknown[0]}'. "
                             f"There are two: confirmations and reminders.")
        requested = {k: blanket for k in targets}

    settings = dict(biz.get("settings") or {})
    # Absent means ON — that is sms_alerts._alert_setting's own default,
    # restated here so the "was" half of the message is true rather than
    # assumed.
    current = dict(settings.get("sms_alerts") or {})
    before = {k: bool(current.get(k, True)) for k in ALERT_KINDS}

    merged = dict(current)
    merged.update(requested)
    settings["sms_alerts"] = merged

    try:
        await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/businesses?id=eq.{business_id}", {"settings": settings})
    except Exception as e:
        logger.exception(f"set_sms_alerts write failed: {e}")
        return _fail("set_sms_alerts",
                     "I couldn't save that just now — try again in a moment.")
    # Same-turn reads see the change.
    biz["settings"] = settings

    label_of = {"confirmations": "booking confirmations",
                "reminders": "appointment reminders"}
    changed = [k for k, v in requested.items() if before.get(k) != v]
    if not changed:
        state = ", ".join(f"{label_of[k]} {'on' if requested[k] else 'off'}"
                          for k in sorted(requested))
        return {
            "type": "set_sms_alerts",
            "result": f"Already set that way — {state}.",
            "label": "Automated texts unchanged",
            "sms_alerts": merged,
            "nav": _nav_sms(),
        }

    parts = [f"{label_of[k]} {'on' if requested[k] else 'off'}"
             for k in sorted(changed)]
    result = "Automated texts: " + ", ".join(parts) + "."
    if any(requested[k] is False for k in changed):
        result += (" Your clients stop getting those automatically — anything "
                   "you send yourself is unaffected.")
    return {
        "type": "set_sms_alerts",
        "result": result,
        "label": "Automated texts updated",
        "sms_alerts": merged,
        "changed": sorted(changed),
        "nav": _nav_sms(),
    }


# ─── status ───────────────────────────────────────────────────────────

def _opted_out_count(business_id: str) -> Optional[int]:
    """How many of this business's contacts have texted STOP.

    Opt-outs are platform-wide by phone under the Direct model, so this
    is an intersection, not a table count: the numbers on THIS
    practitioner's list that are on the platform's opt-out list.
    """
    try:
        contacts = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}&phone=not.is.null"
            f"&select=phone&limit=1000") or []
        if not contacts:
            return 0
        import sms_service
        phones = {sms_service.normalize_phone(c.get("phone"))
                  for c in contacts}
        phones.discard("")
        if not phones:
            return 0
        outs = sb_clients.sb_get_as_service(
            "/sms_opt_outs?select=phone&limit=2000") or []
        stopped = {o.get("phone") for o in outs}
        return len(phones & stopped)
    except Exception as e:
        logger.warning(f"[sms] opt-out tally failed (non-fatal): {e}")
        return None


async def handle_sms_status(client, biz, action) -> Dict[str, Any]:
    """Is texting actually working for this business, and what is it
    sending on its own?

    The read behind "why aren't my texts going out" — which had no
    answer, because the three things that decide it (a keyword, the
    provider, the alert switches) lived in three places and none of them
    was readable from a conversation.
    """
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("sms_status", "no business on record")

    keyword = await asyncio.to_thread(_current_keyword, business_id)

    configured = False
    try:
        import sms_service
        configured = bool(sms_service._twilio_configured())
    except Exception as e:
        logger.warning(f"[sms] provider check failed (non-fatal): {e}")

    alerts_on = True
    try:
        import sms_alerts
        alerts_on = bool(sms_alerts.alerts_enabled())
    except Exception as e:
        logger.warning(f"[sms] alerts kill-switch check failed: {e}")

    current = dict((biz.get("settings") or {}).get("sms_alerts") or {})
    per_business = {k: bool(current.get(k, True)) for k in ALERT_KINDS}
    effective = {k: (v and alerts_on) for k, v in per_business.items()}

    opted_out = await asyncio.to_thread(_opted_out_count, business_id)

    # The report leads with what is BROKEN, because that is the question
    # being asked. A missing keyword is the one that silently loses
    # inbound texts, so it goes first.
    lines: List[str] = []
    if not configured:
        lines.append("texting isn't switched on for this account yet")
    if not keyword:
        lines.append("no keyword yet — clients texting your number reach "
                     "nobody until you claim one")
    else:
        lines.append(f"keyword {keyword}")
    lines.append("booking confirmations "
                 + ("on" if effective["confirmations"] else "off"))
    lines.append("appointment reminders "
                 + ("on" if effective["reminders"] else "off"))
    if opted_out:
        lines.append(f"{opted_out} contact"
                     f"{'s' if opted_out != 1 else ''} opted out")

    ready = bool(configured and keyword)
    return {
        "type": "sms_status",
        "result": "; ".join(lines) + ".",
        "label": "Texting — ready" if ready else "Texting — needs setup",
        "keyword": keyword,
        "provider_configured": configured,
        "alerts": effective,
        "alerts_platform_enabled": alerts_on,
        "opted_out_contacts": opted_out,
        # `signal` is what the agent surface's handoff predicates read.
        # Prose gets reworded; a flag does not (mcp_server.HANDOFFS).
        "signal": {"has_keyword": 1 if keyword else 0,
                   "configured": 1 if configured else 0,
                   "ready": 1 if ready else 0,
                   "opted_out": opted_out or 0},
        "nav": _nav_sms(),
    }
