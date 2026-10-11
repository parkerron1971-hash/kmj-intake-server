"""
sms_routing.py — Chief's SMS routing brain (2026-07-04 architecture).

THE MODEL: one Twilio number for the whole platform. Every inbound is
routed internally: BINDING FIRST, KEYWORD SECOND. The keyword
introduces the relationship; the stored binding sustains it.

THREADS (2026-10-11): a business that texts someone from the shared
number (a booking confirmation, a reminder, a note) never made a binding,
so their reply ("running 10 min late") was told to text a keyword. Now
the businesses this person has texted with in the last THREAD_DAYS are
candidates too, alongside their bindings: one candidate takes the reply,
the most recent conversation within CONTINUITY_HOURS wins among several,
otherwise they choose. Threads are read from sms_messages and never
written to sms_bindings, because a binding is also consent for automated
alerts (sms_alerts.has_sms_consent) and texting someone is not their
consent.

Trust-layer handler (per the Chief handler discipline):
  (a) FIRST-PASS NARRATION — every branch logs what it saw and why it
      chose its path (the [ROUTE] lines).
  (b) ACTION RETURN — route_inbound() returns a structured
      {action, business_id?, reply?} describing exactly what happened.
  (c) SECOND-PASS REPLY — the auto-reply text (connection+consent
      confirmation, disambiguation prompt, help) is composed here and
      sent by the caller AFTER the action is durably recorded.
  (d) DEFLECTION — invalid/reserved keywords, opted-out senders,
      unbound bare messages, and undecidable multi-bindings each hit
      an explicit filter branch; nothing routes silently to the wrong
      practitioner.

SENDER IDENTITY (compliance-critical, Direct model): every outbound is
sent BY the registered brand — sender_brand() is the single seam that
resolves it. Today it always returns the platform brand; under ISV it
resolves per-practitioner. Never present a message as being FROM a
practitioner's own identity under Direct; their name may appear in the
body only.

Tables (supabase/sms-routing-migration.sql): sms_keywords,
sms_bindings, sms_opt_outs. Everything is keyed on the business id
(practitioner) so the Direct→ISV migration is configuration, not a
rewrite.

Endpoints (mounted in kmj_intake_automation.py):
  GET  /sms/keyword?business_id=…      the practitioner's routing keyword
  POST /sms/keyword                    claim/change it (validated, unique)
  POST /sms/broadcast                  send to the practitioner's OWN list
                                       (scoped by business_id; opt-outs
                                       skipped; platform-brand copy)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from auth_supabase import require_user, AuthedUser
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sms_service import (
    _pq, _sb_get, _sb_post, _sb_patch, _sb_headers, _store_sms, _log_event,
    _find_contact_by_phone, normalize_phone, record_inbound_sms,
    _twilio_configured, is_opted_out, sender_for, business_for_number,
)

logger = logging.getLogger("sms_routing")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] route: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(tags=["sms-routing"])

# ─── Sender identity seam (Direct now, ISV later) ─────────────────────

PLATFORM_BRAND = "Solutionist System"


def sender_brand(business_id: Optional[str] = None) -> str:
    """The registered sender identity for outbound copy. Direct model:
    ALWAYS the platform brand, regardless of practitioner. Under ISV
    this resolves the practitioner's own registered brand — change it
    here and nowhere else."""
    return PLATFORM_BRAND


# Platform consent keywords (carrier-level semantics) — reserved; never
# valid as practitioner routing keywords, never treated as routing.
STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
START_WORDS = {"START", "YES", "JOIN", "UNSTOP"}
HELP_WORDS = {"HELP", "INFO"}
RESERVED_WORDS = STOP_WORDS | START_WORDS | HELP_WORDS

KEYWORD_RE = re.compile(r"^[A-Z0-9]{3,20}$")

# Bare replies keep flowing to the same practitioner within this window
# when a customer is bound to several (conversation continuity).
CONTINUITY_HOURS = 72
# A reply to the shared number goes to a business that has been texting
# this person within this many days (a reminder, a confirmation, a note),
# even without a keyword (2026-10-11). Routing only, never consent.
THREAD_DAYS = 30


# ─── Outbound (single seam for auto-replies + broadcast) ──────────────

async def _send_platform_sms(to_number: str, body: str, *,
                             business_id: str,
                             client: Optional[httpx.AsyncClient] = None) -> str:
    """Send one SMS as the platform brand via Twilio's Messaging
    Service, FROM the number that business texts from (sender_for —
    the platform number until the business has its own). business_id
    is keyword-only and required: every caller has it, and a send that
    cannot name its business cannot name its sender. Returns the
    provider message id; raises on hard failure.

    This used to fall through to Telnyx when Twilio was unconfigured.
    That branch was only reachable in an environment with no Twilio
    credentials — where it then failed on the missing Telnyx ones. So
    the fallback's real effect was to answer a Twilio misconfiguration
    with an error naming a provider nobody uses. An unconfigured
    platform should say so in the words of the provider it actually has.
    """
    if not _twilio_configured():
        raise RuntimeError(
            "SMS is not configured — set the TWILIO_* vars in Railway.")
    from starlette.concurrency import run_in_threadpool
    import twilio_sms
    from_number = await sender_for(client, business_id)
    return await run_in_threadpool(
        twilio_sms.send_sms, to_number, body, from_number=from_number)


# ─── Routing helpers ──────────────────────────────────────────────────

async def _keyword_lookup(client: httpx.AsyncClient, word: str) -> Optional[Dict[str, Any]]:
    rows = await _sb_get(
        client, f"/sms_keywords?keyword=eq.{word}&select=business_id,keyword&limit=1",
    ) or []
    return rows[0] if rows else None


async def _bindings_for(client: httpx.AsyncClient, phone: str) -> List[Dict[str, Any]]:
    return await _sb_get(
        client,
        f"/sms_bindings?customer_phone=eq.{_pq(phone)}"
        f"&select=id,business_id,bound_at,last_routed_at&order=bound_at.asc",
    ) or []


async def _bind(client: httpx.AsyncClient, phone: str, business_id: str) -> None:
    """Create or refresh a binding (explicit keyword = clear intent)."""
    now = datetime.now(timezone.utc).isoformat()
    res = await _sb_post(client, "/sms_bindings?on_conflict=customer_phone,business_id", {
        "customer_phone": phone,
        "business_id": business_id,
        "last_routed_at": now,
    })
    if res is None:
        # Conflict path on older PostgREST — refresh the timestamp.
        await _sb_patch(
            client,
            f"/sms_bindings?customer_phone=eq.{_pq(phone)}&business_id=eq.{business_id}",
            {"last_routed_at": now},
        )


async def _recent_threads(client: httpx.AsyncClient, phone: str) -> Dict[str, str]:
    """{business_id: its latest message with this phone (ISO)} over the last
    THREAD_DAYS, either direction (sms_messages). Routing only: unlike a
    binding, a thread is never consent. A failed read is {} (the router
    then asks, as before), never a guess."""
    since = (datetime.now(timezone.utc) - timedelta(days=THREAD_DAYS)).isoformat()
    try:
        rows = await _sb_get(
            client,
            f"/sms_messages?phone_number=eq.{_pq(phone)}&business_id=not.is.null"
            f"&created_at=gte.{_pq(since)}&select=business_id,created_at"
            f"&order=created_at.desc&limit=200",
        ) or []
    except Exception as e:
        logger.warning(f"[ROUTE] threads unread for {phone}: {e}")
        return {}
    out: Dict[str, str] = {}
    for r in rows:
        bid = str(r.get("business_id") or "")
        if bid and bid not in out:
            out[bid] = str(r.get("created_at") or "")
    return out


def _when(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _candidates(bindings: List[Dict[str, Any]], threads: Dict[str, str]) -> List[Dict[str, Any]]:
    """Every business this person may be answering, with its latest activity
    (`last`, a datetime or None): keyword bindings first, oldest first, then
    businesses that have only been texting with them, by id. A stable order,
    so "Reply 1" means the same business when the answer comes back."""
    out: List[Dict[str, Any]] = []
    for b in bindings:
        bid = str(b["business_id"])
        times = [t for t in (_when(b.get("last_routed_at")), _when(threads.get(bid))) if t is not None]
        out.append({"business_id": bid, "bound": True, "last": max(times) if times else None})
    bound = {c["business_id"] for c in out}
    for bid in sorted(threads):
        if bid not in bound:
            out.append({"business_id": bid, "bound": False, "last": _when(threads[bid])})
    return out


async def _touch_binding(client: httpx.AsyncClient, phone: str, business_id: str) -> None:
    await _sb_patch(
        client,
        f"/sms_bindings?customer_phone=eq.{_pq(phone)}&business_id=eq.{business_id}",
        {"last_routed_at": datetime.now(timezone.utc).isoformat()},
    )


async def _biz_name(client: httpx.AsyncClient, business_id: str) -> str:
    rows = await _sb_get(
        client, f"/businesses?id=eq.{business_id}&select=name&limit=1",
    ) or []
    return (rows[0].get("name") if rows else None) or "the business"


async def _ensure_contact(client: httpx.AsyncClient, business_id: str, phone: str) -> None:
    """A bound customer should exist as a contact in the practitioner's
    list (that list is what group sends iterate)."""
    existing = await _find_contact_by_phone(client, business_id, phone)
    if existing:
        return
    await _sb_post(client, "/contacts", {
        "business_id": business_id,
        "name": phone,          # practitioner renames later
        "phone": phone,
        "status": "active",
    })


# ─── The inbound router (called by the Twilio webhook) ────────────────

async def route_inbound(
    *,
    from_number: str,
    text: str,
    provider_id: str = "",
    media: Optional[List[Dict[str, Any]]] = None,
    to_number: str = "",
) -> Dict[str, Any]:
    """Layered per the module docstring. Order:
    OWN NUMBER? (the To number is the routing) → STOP/START/HELP →
    keyword? bind+confirm → binding(s)? route → disambiguate → prompt.
    Returns {action, ...}; the caller has already validated the Twilio
    signature (layer 0)."""
    phone = normalize_phone(from_number) or from_number
    body = (text or "").strip()
    first_word = body.split()[0].upper() if body.split() else ""

    async with httpx.AsyncClient() as client:
        # ── Dedicated number (2026-09-02): To IS the routing ──
        # A customer who texts a business's own line has already said
        # which business — no keyword, no disambiguation. Consent words
        # scope to that business (sms_opt_outs.business_id was built
        # for exactly this). The customer is also bound, so a later
        # text to the SHARED number still finds them.
        own = await business_for_number(client, to_number) if to_number else None
        if own:
            business_id = own["business_id"]
            if first_word in STOP_WORDS:
                logger.info(f"[ROUTE] STOP from {phone} on biz {business_id[:8]}'s own number — scoped opt-out")
                await _sb_post(client, "/sms_opt_outs?on_conflict=phone,business_id", {
                    "phone": phone, "business_id": business_id,
                })
                return {"action": "opt_out", "business_id": business_id, "reply": None}
            if first_word in START_WORDS:
                logger.info(f"[ROUTE] START from {phone} on biz {business_id[:8]}'s own number — scoped opt-out cleared")
                try:
                    await client.delete(
                        f"{os.environ.get('SUPABASE_URL', '').rstrip('/')}/rest/v1"
                        f"/sms_opt_outs?phone=eq.{_pq(phone)}&business_id=eq.{business_id}",
                        headers=_sb_headers(),
                    )
                except Exception as e:
                    logger.warning(f"[ROUTE] scoped opt-out clear failed: {e}")
                return {"action": "opt_in", "business_id": business_id, "reply": None}
            if first_word in HELP_WORDS:
                name = await _biz_name(client, business_id)
                logger.info(f"[ROUTE] HELP from {phone} on biz {business_id[:8]}'s own number")
                return {"action": "help", "business_id": business_id, "reply": (
                    f"{sender_brand()}: You've reached {name}. Email "
                    f"{os.environ.get('SUPPORT_EMAIL', 'kmjcreativesolution@gmail.com')} for help. "
                    f"Msg & data rates may apply. Reply STOP to opt out."
                )}
            logger.info(f"[ROUTE] own-number {phone} → biz {business_id[:8]} (direct)")
            await _bind(client, phone, business_id)
            await _ensure_contact(client, business_id, phone)
            await record_inbound_sms(
                client, from_number=phone, text=body,
                provider_id=provider_id, media=media, business_id=business_id,
            )
            return {"action": "routed_direct", "business_id": business_id, "reply": None}

        if to_number:
            import twilio_sms
            to_clean = normalize_phone(to_number)
            if to_clean and twilio_sms.platform_number() and to_clean != twilio_sms.platform_number():
                # A number in the pool that no live row claims — a
                # released line, or a race with provisioning. Never
                # dropped: it takes the shared path and says so.
                import pii_mask
                logger.warning(
                    f"[ROUTE] unknown To {pii_mask.mask_phone(to_clean)} — not in sms_numbers "
                    f"and not the platform number; falling through to the shared path")

        # ── Consent keywords (platform-level, before any routing) ──
        if first_word in STOP_WORDS:
            logger.info(f"[ROUTE] STOP from {phone} — platform-wide opt-out recorded")
            await _sb_post(client, "/sms_opt_outs?on_conflict=phone,business_id", {
                "phone": phone, "business_id": None,
            })
            # Twilio Advanced Opt-Out sends the carrier-compliant
            # confirmation; we only record. (Deflection: no routing.)
            return {"action": "opt_out", "reply": None}

        if first_word in START_WORDS:
            logger.info(f"[ROUTE] START from {phone} — opt-out cleared")
            try:
                await client.delete(
                    f"{os.environ.get('SUPABASE_URL', '').rstrip('/')}/rest/v1"
                    f"/sms_opt_outs?phone=eq.{_pq(phone)}",
                    # Same identity as every other SMS write (service
                    # role via sms_service._sb_headers) — this was the
                    # one inline anon-header holdout.
                    headers=_sb_headers(),
                )
            except Exception as e:
                logger.warning(f"[ROUTE] opt-out clear failed: {e}")
            return {"action": "opt_in", "reply": None}

        if first_word in HELP_WORDS:
            logger.info(f"[ROUTE] HELP from {phone}")
            return {"action": "help", "reply": (
                f"{sender_brand()}: We're here - email "
                f"{os.environ.get('SUPPORT_EMAIL', 'kmjcreativesolution@gmail.com')}. "
                f"Msg & data rates may apply. Reply STOP to opt out."
            )}

        # ── Routing keyword? (introduces / re-binds) ──
        if KEYWORD_RE.match(first_word) and first_word not in RESERVED_WORDS:
            kw = await _keyword_lookup(client, first_word)
            if kw:
                business_id = kw["business_id"]
                logger.info(f"[ROUTE] keyword {first_word} from {phone} → biz {business_id[:8]} (bind)")
                await _bind(client, phone, business_id)
                await _ensure_contact(client, business_id, phone)
                # Record the remainder (if they wrote more than the keyword).
                remainder = body[len(first_word):].strip()
                if remainder:
                    await record_inbound_sms(
                        client, from_number=phone, text=remainder,
                        provider_id=provider_id, media=media,
                        business_id=business_id,
                    )
                name = await _biz_name(client, business_id)
                # The keyword text IS the opt-in action; this reply
                # confirms connection AND consent in one message.
                return {"action": "bound", "business_id": business_id, "reply": (
                    f"{sender_brand()}: You're now connected with {name}. "
                    f"Msg frequency varies. Msg & data rates may apply. "
                    f"Reply HELP for help, STOP to opt out."
                )}
            # Not a known keyword — fall through to binding routing
            # (it's probably just the first word of a sentence).

        # ── Who they may be answering (sustains the relationship) ──
        # Keyword bindings, and every business that has been texting with
        # them lately (threads): a client who replies "running late" to the
        # reminder a business sent from the shared number reaches that
        # business, without ever having texted its keyword. A thread is
        # routing only: it is never consent (has_sms_consent counts
        # bindings, so threads are kept out of sms_bindings).
        bindings = await _bindings_for(client, phone)
        threads = await _recent_threads(client, phone)
        candidates = _candidates(bindings, threads)

        async def _route(c: Dict[str, Any], how: str) -> Dict[str, Any]:
            business_id = c["business_id"]
            logger.info(f"[ROUTE] {how} {phone} → biz {business_id[:8]}")
            if c["bound"]:
                await _touch_binding(client, phone, business_id)
            await record_inbound_sms(
                client, from_number=phone, text=body,
                provider_id=provider_id, media=media, business_id=business_id,
            )
            return {"action": "routed", "business_id": business_id, "reply": None}

        if len(candidates) == 1:
            return await _route(candidates[0], "bound" if candidates[0]["bound"] else "thread")

        if len(candidates) > 1:
            # Continuity: an active conversation wins.
            now = datetime.now(timezone.utc)
            recent = sorted(
                (c for c in candidates
                 if c["last"] is not None and (now - c["last"]) <= timedelta(hours=CONTINUITY_HOURS)),
                key=lambda c: c["last"], reverse=True,
            )
            if recent:
                return await _route(recent[0], "continuity")

            # Numeric selection reply? ("1" / "2" — the order the prompt listed)
            if body.isdigit() and 1 <= int(body) <= min(len(candidates), 5):
                chosen = candidates[int(body) - 1]
                business_id = chosen["business_id"]
                name = await _biz_name(client, business_id)
                reply = f"{sender_brand()}: Connected with {name} - send your message."
                if chosen["bound"]:
                    await _touch_binding(client, phone, business_id)
                else:
                    # The choice is kept in their thread with that business
                    # (so the next message continues there), not as a
                    # binding: choosing is not consent.
                    await _store_sms(client, business_id, None, phone, reply, "outbound", sent_by="system")
                logger.info(f"[ROUTE] multi {phone} selected {int(body)} → biz {business_id[:8]}")
                return {"action": "selected", "business_id": business_id, "reply": reply}

            # Undecidable — never route silently to the wrong one.
            names = []
            for i, c in enumerate(candidates[:5], start=1):
                names.append(f"{i} for {await _biz_name(client, c['business_id'])}")
            logger.info(f"[ROUTE] multi {phone} — disambiguation prompt")
            return {"action": "disambiguate", "reply": (
                f"{sender_brand()}: You're connected with more than one business. "
                f"Reply {', '.join(names)}."
            )}

        # ── Unbound, no keyword — prompt (deflection, nothing stored) ──
        logger.info(f"[ROUTE] unbound {phone}, no keyword — prompt")
        return {"action": "prompt_keyword", "reply": (
            f"{sender_brand()}: Which business are you trying to reach? "
            f"Text their keyword (the word they shared with you) to connect. "
            f"Msg & data rates may apply. Reply STOP to opt out."
        )}


# ─── Public web-form opt-in (the /sms page's endpoint) ────────────────

_OPTIN_HITS: Dict[str, List[float]] = {}


class OptInBody(BaseModel):
    phone: str
    name: Optional[str] = None
    consent: bool = False


@router.post("/api/sms/opt-in")
async def sms_opt_in(body: OptInBody, request: Request):
    """Records a web-form SMS consent (sms_consents audit row). Public —
    it backs the crawlable /sms page that A2P reviewers verify. Light
    in-memory rate limit (same approach as the intake endpoint).

    Per IP as well as per phone (2026-09-04): the per-phone limit is
    keyed on a value the caller chooses, and the rows this writes are
    the carrier-facing consent audit trail — poisoning it has
    regulatory cost, not just storage cost. Strict."""
    import time as _time
    import rate_limit
    if not rate_limit.allow_strict("sms_opt_in", rate_limit.trusted_client_ip(request)):
        return JSONResponse({"error": "Too many attempts — try again in a little while."}, 429)
    if not body.consent:
        return JSONResponse({"error": "The consent box must be checked to sign up."}, 400)
    phone = normalize_phone(body.phone)
    if not phone:
        return JSONResponse({"error": "That phone number doesn't look valid — use +1XXXXXXXXXX."}, 400)

    # 5 submissions/minute per phone — enough for humans, boring for bots.
    now = _time.time()
    hits = [t for t in _OPTIN_HITS.get(phone, []) if now - t < 60]
    if len(hits) >= 5:
        return JSONResponse({"error": "Too many attempts — try again in a minute."}, 429)
    hits.append(now)
    _OPTIN_HITS[phone] = hits

    async with httpx.AsyncClient() as client:
        res = await _sb_post(client, "/sms_consents", {
            "phone": phone,
            "name": (body.name or "").strip()[:120] or None,
            "source": "web_form",
        })
        if res is None:
            logger.warning("[ROUTE] consent insert failed — sms-consents migration applied?")
            return JSONResponse({"error": "Could not save right now — please try again later."}, 502)
    logger.info(f"[ROUTE] web-form consent recorded for {phone}")
    return {"ok": True}


# ─── Practitioner keyword management ──────────────────────────────────

class KeywordBody(BaseModel):
    business_id: str
    keyword: str


@router.get("/sms/keyword")
async def get_keyword(business_id: str, user: AuthedUser = Depends(require_user)):
    # See the note on /sms/send: `require_user` proves the caller is
    # signed in, not that this business is theirs. A keyword is the word
    # a stranger texts to reach a practitioner — reading someone else's
    # is reading the key to their front door.
    import business_access
    business_access.assert_access(str(business_id), user, "viewer")
    async with httpx.AsyncClient() as client:
        rows = await _sb_get(
            client, f"/sms_keywords?business_id=eq.{business_id}&select=keyword&limit=1",
        ) or []
    return {"keyword": rows[0]["keyword"] if rows else None}


@router.post("/sms/keyword")
async def set_keyword(body: KeywordBody, user: AuthedUser = Depends(require_user)):
    # Admin, not member: under the one-number model the keyword IS the
    # business's inbound identity, and the uniqueness check below made
    # this look safe from the wrong angle — it stops you STEALING a
    # keyword somebody else claimed, and did nothing about setting or
    # rewriting the keyword of a business that is not yours.
    import business_access
    business_access.assert_access(str(body.business_id), user, "admin")
    word = (body.keyword or "").strip().upper()
    if not KEYWORD_RE.match(word):
        return JSONResponse({"error": "Keyword must be 3-20 letters/numbers."}, 400)
    if word in RESERVED_WORDS:
        return JSONResponse({"error": f"{word} is a reserved carrier word — pick another."}, 400)
    async with httpx.AsyncClient() as client:
        taken = await _keyword_lookup(client, word)
        if taken and taken.get("business_id") != body.business_id:
            return JSONResponse({"error": f"{word} is already taken — pick another."}, 409)
        existing = await _sb_get(
            client, f"/sms_keywords?business_id=eq.{body.business_id}&select=id&limit=1",
        ) or []
        if existing:
            await _sb_patch(client, f"/sms_keywords?business_id=eq.{body.business_id}", {
                "keyword": word, "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        else:
            res = await _sb_post(client, "/sms_keywords", {
                "business_id": body.business_id, "keyword": word,
            })
            if res is None:
                return JSONResponse(
                    {"error": "Could not save — is the sms-routing migration applied?"}, 502)
    logger.info(f"[ROUTE] keyword {word} claimed by biz {body.business_id[:8]}")
    return {"ok": True, "keyword": word}


# ─── Broadcast (per-practitioner scoped list — the safety mechanism) ──

class BroadcastBody(BaseModel):
    business_id: str
    message: str


@router.post("/sms/broadcast")
async def broadcast(body: BroadcastBody, user: AuthedUser = Depends(require_user)):
    """Send to every contact WITH a phone on THIS practitioner's list.
    Scoping by business_id is what makes cross-contamination
    structurally impossible; opted-out numbers are skipped."""
    # THE ONE THIS MATTERS MOST FOR. The docstring says scoping by
    # business_id is "what makes cross-contamination structurally
    # impossible" — but the business_id was the CALLER'S to choose. Any
    # signed-in account could text up to 500 of another practitioner's
    # contacts, from the shared platform number, under that
    # practitioner's brand name, billed to the platform and charged
    # against their 10DLC standing. The scoping was real; the
    # authorisation for it was missing. Admin, because this is bulk
    # outbound to the whole list.
    import business_access
    business_access.assert_access(str(body.business_id), user, "admin")
    # No card on file yet (no_card_trial.py): refuse once, up front, rather
    # than fail at sender_for once per contact.
    import billing_limits
    billing_limits.require_card(str(body.business_id), "texts")
    msg = (body.message or "").strip()
    if not msg:
        return JSONResponse({"error": "Message body required"}, 400)
    if len(msg) > 1200:
        return JSONResponse({"error": "Keep broadcasts under 1200 characters."}, 400)

    async with httpx.AsyncClient() as client:
        # Sender identity. A broadcast goes to people who may not have
        # texted in for months, from a number shared with every other
        # business on the platform — it is the single most likely outbound
        # to be read as spam. So it leads with the business name, the same
        # way send_sms_core does for one-to-one sends.
        #
        # Composed ONCE outside the loop: the body is identical for every
        # recipient, and the opt-out tail is unconditional here rather than
        # first-contact-only. A broadcast is bulk unsolicited-feeling
        # traffic; every one of them carries the way out.
        biz_name = await _biz_name(client, body.business_id)
        from sms_service import compose_outbound_body
        msg = compose_outbound_body(biz_name, msg, include_optout=True)

        contacts = await _sb_get(
            client,
            f"/contacts?business_id=eq.{body.business_id}&phone=not.is.null"
            f"&select=id,name,phone&limit=500",
        ) or []
        sent, skipped, failed = 0, 0, 0
        for c in contacts:
            phone = normalize_phone(c.get("phone"))
            if not phone:
                skipped += 1
                continue
            if await is_opted_out(client, phone, body.business_id):
                skipped += 1
                continue
            try:
                sid = await _send_platform_sms(
                    phone, msg, business_id=body.business_id, client=client)
                await _store_sms(
                    client, business_id=body.business_id, contact_id=c.get("id"),
                    phone_number=phone, message=msg, direction="outbound",
                    telnyx_id=sid, status="sent", sent_by="practitioner",
                )
                sent += 1
            except Exception as e:
                failed += 1
                logger.warning(f"[ROUTE] broadcast send failed to {phone}: {e}")
            await asyncio.sleep(0.25)   # gentle pacing — carrier-friendly

        await _log_event(client, body.business_id, None, "sms_broadcast", {
            "preview": msg[:200], "sent": sent, "skipped": skipped, "failed": failed,
        })
    logger.info(f"[ROUTE] broadcast biz {body.business_id[:8]}: sent={sent} skipped={skipped} failed={failed}")
    return {"ok": True, "sent": sent, "skipped": skipped, "failed": failed,
            "total_contacts": len(contacts)}
