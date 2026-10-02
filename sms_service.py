"""
sms_service.py — the shared SMS core for the Solutionist System.

Despite the history in the name of one column below, this module is not
provider-specific. It owns phone normalisation, outbound body
composition, opt-out handling and the sms_messages store — all of which
a dozen other modules import. Sending itself is Twilio's, via
twilio_sms.py.

Routes:
  POST /sms/send                            send an SMS
  GET  /sms/conversation/{biz}/{contact}    fetch a conversation thread
  POST /sms/session-reminder                send a session reminder by SMS
  GET  /sms/health                          status check

Inbound arrives on Twilio's own webhooks in twilio_sms.py
(/webhooks/twilio/sms and /webhooks/twilio/status), which validate
X-Twilio-Signature and hand off to sms_routing.route_inbound.

Env: the TWILIO_* vars. See twilio_sms.py.

Storage: sms_messages table (see supabase/sms-messages-migration.sql).

  NOTE ON `telnyx_id`: that column holds the PROVIDER message id and has
  done since before Twilio replaced Telnyx. Twilio's MessageSid is what
  goes in it now, and /webhooks/twilio/status PATCHes delivery receipts
  by matching on it. The name is wrong and the column is load-bearing;
  renaming it is a migration plus a sweep of every reader, not a tidy-up
  to fold into removing a dead provider. Left as history, deliberately.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from auth_supabase import require_user, AuthedUser
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(tags=["sms"])
logger = logging.getLogger("sms_service")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] sms: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


HTTP_TIMEOUT = 15.0

# ─── Supabase helpers (anon key, same pattern as the rest of railway/) ──

def _pq(value) -> str:
    """Percent-encode a value for a PostgREST query-string filter.

    E.164 phones start with '+', which URL query parsing decodes as a
    SPACE - so every `phone=eq.+1...` filter silently matched NOTHING
    (proven against prod: raw '+' -> 0 rows, '%2B' -> 1 row). That one
    character broke binding routing ("keeps asking for the keyword"),
    opt-out checks, consent checks, and exact contact matching. Route
    every phone value through this before it enters a URL.
    """
    import urllib.parse
    return urllib.parse.quote(str(value or ""), safe="")


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_anon() -> str:
    # 2026-07-10 root-cause fix: this module (and sms_routing, which
    # imports these helpers) ran on the ANON key under the assumption
    # of permissive RLS — but sms_messages/sms_consents now ship with
    # owner-scoped RLS (text content must NOT be readable with the
    # public browser key). Server-initiated SMS writes are webhook- or
    # signature-validated, so the service role is the correct identity.
    # Anon fallback keeps a partially-configured env limping visibly
    # (warnings) instead of failing dark.
    return (os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.environ.get("SUPABASE_ANON", ""))


def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _sb_get(client: httpx.AsyncClient, path: str) -> Optional[Any]:
    try:
        r = await client.get(f"{_sb_url()}/rest/v1{path}",
                              headers=_sb_headers(), timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase GET {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase GET {path} failed: {e}")
        return None


async def _sb_post(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> Optional[Any]:
    try:
        r = await client.post(f"{_sb_url()}/rest/v1{path}",
                               headers=_sb_headers(),
                               content=json.dumps(body),
                               timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase POST {path} failed: {e}")
        return None


async def _sb_patch(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> None:
    try:
        await client.patch(f"{_sb_url()}/rest/v1{path}",
                            headers=_sb_headers(),
                            content=json.dumps(body),
                            timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"supabase PATCH {path} failed: {e}")


# ─── Phone number normalization ──────────────────────────────────────

def normalize_phone(phone: Optional[str]) -> str:
    """Coerce a phone string to E.164 (+1XXXXXXXXXX for US/CA).

    - Already-prefixed numbers pass through.
    - 10 digits get +1 prepended (US/CA assumption).
    - 11 digits starting with 1 get a + prepended.
    - Anything else returns "" — caller must handle invalid.
    """
    if not phone:
        return ""
    s = str(phone).strip()
    if s.startswith("+") and len(s) >= 8:
        return s
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return ""


# ─── Send ────────────────────────────────────────────────────────────

class SendSmsRequest(BaseModel):
    business_id: str
    contact_id: Optional[str] = None
    to: str
    message: str


SENT_BY = ("practitioner", "chief", "system")


async def _store_sms(
    client: httpx.AsyncClient,
    business_id: str,
    contact_id: Optional[str],
    phone_number: str,
    message: str,
    direction: str,
    telnyx_id: str = "",
    status: Optional[str] = None,
    media: Optional[List[Dict[str, Any]]] = None,
    sent_by: Optional[str] = None,
) -> Optional[str]:
    """Insert a row into sms_messages. Returns the new id.

    sent_by (outbound only): 'practitioner' | 'chief' | 'system' — who
    authored it, so the thread can say so. A text Chief sent used to
    render as "You:" exactly like one the practitioner typed."""
    row = {
        "business_id": business_id,
        "contact_id": contact_id,
        "phone_number": phone_number,
        "message": message,
        "direction": direction,
        "status": status or ("sent" if direction == "outbound" else "received"),
        "telnyx_id": telnyx_id,
        "media_urls": [m.get("url") for m in (media or []) if m.get("url")],
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Outbound messages count as "read" — only inbound is unread by default.
        "read": direction == "outbound",
    }
    if direction == "outbound" and sent_by in SENT_BY:
        row["sent_by"] = sent_by
    inserted = await _sb_post(client, "/sms_messages", row)
    if isinstance(inserted, list) and inserted:
        return inserted[0].get("id")
    if isinstance(inserted, dict):
        return inserted.get("id")
    return None


async def _log_event(
    client: httpx.AsyncClient,
    business_id: str,
    contact_id: Optional[str],
    event_type: str,
    data: Dict[str, Any],
) -> None:
    await _sb_post(client, "/events", {
        "business_id": business_id,
        "contact_id": contact_id,
        "event_type": event_type,
        "data": data,
        "source": "sms_service",
    })


async def is_opted_out(client: httpx.AsyncClient, phone: str,
                       business_id: Optional[str] = None) -> bool:
    """STOP check before EVERY outbound send. A STOP texted to the
    platform number is platform-wide (business_id NULL) and suppresses
    every business. A STOP texted to a business's OWN number (2026-09-02,
    dedicated numbers) is scoped to that business — pass business_id and
    both rows count. Fails OPEN — a DB blip must not block transactional
    sends; carrier-level STOP still protects."""
    scope = "business_id=is.null"
    if business_id:
        scope = f"or=(business_id.is.null,business_id.eq.{business_id})"
    try:
        rows = await _sb_get(
            client,
            f"/sms_opt_outs?phone=eq.{_pq(phone)}&{scope}&select=id&limit=1",
        ) or []
        return bool(rows)
    except Exception:
        return False


def _twilio_configured() -> bool:
    """Twilio is the primary rail when its env is present (2026-07-04 —
    Kevin's Messaging Service). Telnyx stays as the fallback."""
    return all(
        (os.environ.get(k) or "").strip()
        for k in ("TWILIO_ACCOUNT_SID", "TWILIO_API_KEY_SID",
                  "TWILIO_API_KEY_SECRET", "TWILIO_MESSAGING_SERVICE_SID")
    )


# ─── Dedicated numbers (sms_numbers — supabase/APPLY-2026-09-02-sms-numbers.sql)

async def active_number_for(client: httpx.AsyncClient,
                            business_id: Optional[str]) -> Optional[str]:
    """The business's own ACTIVE number, if it has one. Suspended
    (billing lapsed) still receives — see business_for_number — but
    does not send."""
    if not business_id:
        return None
    rows = await _sb_get(
        client,
        f"/sms_numbers?business_id=eq.{business_id}&status=eq.active"
        f"&select=phone_number&limit=1",
    ) or []
    return (rows[0].get("phone_number") if rows else None) or None


async def business_for_number(client: httpx.AsyncClient,
                              to_number: str) -> Optional[Dict[str, Any]]:
    """Inbound: which business owns the number a customer texted?
    {business_id, status} for an active OR suspended line (a lapsed
    account still gets its inbound; it just can't reply from that
    number), else None — the caller falls through to the shared-number
    path."""
    phone = normalize_phone(to_number)
    if not phone:
        return None
    rows = await _sb_get(
        client,
        f"/sms_numbers?phone_number=eq.{_pq(phone)}&status=in.(active,suspended)"
        f"&select=business_id,status&limit=1",
    ) or []
    return rows[0] if rows else None


async def sender_for(client: Optional[httpx.AsyncClient], business_id: Optional[str]) -> str:
    """The number this business texts FROM: its own active line when it
    has one, else the platform number (TWILIO_PLATFORM_NUMBER). This is
    the single seam, so every send (Chief, scheduler, broadcast, booking
    alerts, campaigns) inherits it. A DB blip on the lookup degrades to
    the platform number — the text still goes, from the shared line.
    Empty string = unpinned (see twilio_sms.send_sms)."""
    import twilio_sms
    own: Optional[str] = None
    if business_id:
        if client is None:
            async with httpx.AsyncClient() as c:
                own = await active_number_for(c, business_id)
        else:
            own = await active_number_for(client, business_id)
    return own or twilio_sms.platform_number()


class SmsSendError(RuntimeError):
    """A send failure with the practitioner-readable reason + the HTTP
    status the endpoint wrapper should return."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# ─── Sender identity on outbound (Direct model) ──────────────────────

MAX_BRAND_PREFIX = 32
OPTOUT_TAIL = " Reply STOP to opt out."


def compose_outbound_body(business_name: Optional[str], message: str,
                          *, include_optout: bool = False,
                          include_ai_notice: bool = False) -> str:
    """Lead every practitioner-initiated text with the business name.

    WHY THIS EXISTS
      The platform runs ONE registered A2P 10DLC brand and one number for
      every business (sms_routing's Direct model). That is the compliant,
      zero-per-operator-cost way to do multi-tenant SMS, and inbound routing
      solves recipient→business perfectly via keyword binding.

      The hole was outbound. sms_routing's own auto-replies already brand
      themselves ("Solutionist System: You're now connected with X"), but
      Chief-initiated sends and broadcasts went out as the bare message. So
      a rebooking nudge arrived from an unrecognised number with nothing
      saying which business sent it.

      That is not just confusing, it is corrosive: unrecognised outbound is
      what earns STOP replies and spam reports, and on a SHARED campaign
      those land on every operator on the number, not just the sender. On a
      one-number model sender recognition matters more, not less.

      Under Direct the registered SENDER stays the platform — sms_routing's
      docstring is explicit that a practitioner's name may appear in the
      BODY only. This puts it exactly there, and nowhere else.

    Idempotent: a message that already opens with the business name is left
    alone, so Chief writing "Craft & Co here —" does not become
    "Craft & Co: Craft & Co here —".
    """
    body = (message or "").strip()
    name = (business_name or "").strip()
    if not body:
        return body
    if not name:
        return _append_tails(body, include_ai_notice, include_optout)

    # Long names would eat the segment; the recipient only needs enough to
    # recognise who this is.
    if len(name) > MAX_BRAND_PREFIX:
        name = name[:MAX_BRAND_PREFIX - 1].rstrip() + "…"

    # Already self-identified? Compare on letters/digits only so
    # "Craft & Co" matches "Craft and Co" poorly but "Craft & Co:" exactly.
    lead = body[:len(name) + 2].lower()
    if lead.startswith(name.lower()):
        out = body
    else:
        out = f"{name}: {body}"

    return _append_tails(out, include_ai_notice, include_optout)


def _append_tails(out: str, include_ai_notice: bool,
                  include_optout: bool) -> str:
    """The AI notice, then the opt-out line — in that order.

    ORDER IS DELIBERATE. "Reply STOP to opt out." is the last thing on
    the message because that is where people look for it. The AI notice
    goes ahead of it so the opt-out stays in its conventional place.

    Both are idempotent. Chief writes its own text and sometimes says
    these things unprompted; appending a second copy would read as a
    machine that is not listening to itself.
    """
    if include_ai_notice:
        notice = _ai_notice_text()
        # Match on the marker, not the whole sentence — Chief may phrase
        # it its own way ("I'm an AI assistant"), and stapling the
        # canned line onto a message that already said so is worse than
        # not adding it.
        if notice and AI_NOTICE_MARK.lower() not in out.lower():
            out = f"{out.rstrip()} {notice}"

    if include_optout and "STOP" not in out.upper():
        out += OPTOUT_TAIL
    return out


async def _is_first_outbound(client: httpx.AsyncClient, business_id: str,
                             to_clean: str) -> bool:
    """True when this business has never texted this number before.

    Opt-out language belongs on the FIRST message to someone, not stapled to
    every one of them — CTIA guidance wants it discoverable, and repeating it
    on every text burns characters and reads like spam. Fails CLOSED (returns
    False) on any error: a missing tagline is better than a duplicated one on
    every message because a read hiccuped.
    """
    if not business_id or not to_clean:
        return False
    try:
        rows = await _sb_get(
            client,
            f"/sms_messages?business_id=eq.{business_id}"
            f"&phone_number=eq.{_pq(to_clean)}"
            "&direction=eq.outbound&select=id&limit=1") or []
        return len(rows) == 0
    except Exception as e:
        logger.warning(f"[SMS] first-outbound check failed, omitting opt-out tail: {e}")
        return False


def _ai_notice_text() -> str:
    """The one-line client notice, from ai_disclosure — never a second
    copy. A disclosure that exists twice drifts, and then the record of
    what somebody was told stops matching what they were told."""
    import ai_disclosure
    doc = ai_disclosure.current("client_sms")
    return (doc or {}).get("text", "")


# A stable, human-readable fragment of the notice used to recognise it in
# messages already sent. Deliberately a SUBSTRING rather than the whole
# sentence: the composed body may have been trimmed or edited, and a
# check that only matches the exact string would re-disclose forever
# after any wording change.
AI_NOTICE_MARK = "AI-generated"


async def _ai_notice_already_sent(client: httpx.AsyncClient, business_id: str,
                                  to_clean: str) -> bool:
    """Has this business already told this number it is talking to an AI?

    WHY NOT REUSE _is_first_outbound. That answers "have we ever texted
    them", which is the wrong question. A practitioner types the first
    message themselves, Chief answers the second — under a first-ever
    rule the notice attaches to the human message and never to the AI
    one, disclosing at exactly the wrong moment.

    WHY THIS FAILS OPEN, THE OPPOSITE OF THE OPT-OUT TAIL. On a read
    error this returns False, so the notice IS included. The two are
    genuinely different risks: a duplicated opt-out line is noise, while
    a missing AI disclosure is the harm the feature exists to prevent.
    Telling somebody twice costs a few characters; not telling them
    costs the thing itself.
    """
    if not business_id or not to_clean:
        return False
    try:
        rows = await _sb_get(
            client,
            f"/sms_messages?business_id=eq.{business_id}"
            f"&phone_number=eq.{_pq(to_clean)}"
            f"&direction=eq.outbound&message=ilike.*{AI_NOTICE_MARK}*"
            "&select=id&limit=1") or []
        return len(rows) > 0
    except Exception as e:
        logger.warning(
            "[SMS] AI-notice history check failed, including the notice: %s", e)
        return False


async def _business_name(client: httpx.AsyncClient, business_id: str) -> str:
    if not business_id:
        return ""
    try:
        rows = await _sb_get(
            client, f"/businesses?id=eq.{business_id}&select=name&limit=1") or []
        return (rows[0].get("name") if rows else "") or ""
    except Exception as e:
        logger.warning(f"[SMS] business name lookup failed: {e}")
        return ""


async def send_sms_core(client: httpx.AsyncClient, *, business_id: str,
                        to: str, message: str,
                        contact_id: Optional[str] = None,
                        sent_by: str = "practitioner") -> Dict[str, Any]:
    """The whole outbound send (validate → consent gate → contact
    resolve → Twilio/Telnyx → store → event log), callable IN-PROCESS.

    Extracted from the /sms/send endpoint (2026-07-22) because Chief's
    send_sms handler and the scheduler used to POST to our own endpoint
    — which requires a user JWT neither context carries since the
    endpoint sweep, so every Chief-initiated text 401'd. Raises
    SmsSendError with the reason; returns the endpoint's success body."""
    to_clean = normalize_phone(to)
    if not to_clean:
        raise SmsSendError(f"Invalid phone number: {to}", 400)
    if not (message or "").strip():
        raise SmsSendError("Message body required", 400)

    if not _twilio_configured():
        raise SmsSendError(
            "SMS is not configured. Set the TWILIO_* vars in Railway.", 503)

    # Consent gate — never send to a number that opted out.
    if await is_opted_out(client, to_clean, business_id):
        raise SmsSendError(
            f"{to_clean} has opted out of texts (STOP). "
            f"They can text START to opt back in.", 422)

    # Resolve contact by phone if caller didn't supply one.
    if not contact_id and business_id:
        match = await _find_contact_by_phone(client, business_id, to_clean)
        if match:
            contact_id = match.get("id")

    # Sender identity. One number serves every business, so the body is the
    # only place the recipient learns who is texting them. Composed HERE, in
    # the single seam every practitioner-initiated send passes through, so
    # Chief, the scheduler, broadcasts and booking alerts all inherit it
    # rather than each remembering to prefix. (sms_routing's auto-replies
    # brand themselves and do not come through here.)
    #
    # The composed body is what gets STORED as well as sent — the
    # practitioner's thread must show what the customer actually received,
    # not the draft it was written from.
    biz_name = await _business_name(client, business_id)
    first_time = await _is_first_outbound(client, business_id, to_clean)

    # TELLING THE RECIPIENT AN AI IS WRITING.
    #
    # The practitioner is shown an interrupting modal about how AI works
    # here. Their customer, who never signed up for anything, was being
    # texted by that same AI with no notice at all. That asymmetry was
    # the gap — the client disclosure existed, hashed and versioned, and
    # nothing sent it.
    #
    # Gated on AUTHORSHIP, not on the caller. authorship.current_model()
    # is set inside a Chief turn and unset when a practitioner types a
    # message and hits send, so the notice follows who actually wrote
    # the words rather than which code path carried them. Attaching it
    # to a human-written text would be its own kind of lie.
    ai_model = None
    try:
        import authorship
        ai_model = authorship.current_model()
    except Exception as e:                      # never block a send on this
        logger.warning("[SMS] authorship lookup failed: %s", e)

    include_ai = False
    if ai_model:
        include_ai = not await _ai_notice_already_sent(
            client, business_id, to_clean)

    message = compose_outbound_body(biz_name, message,
                                    include_optout=first_time,
                                    include_ai_notice=include_ai)

    try:
        from starlette.concurrency import run_in_threadpool
        import twilio_sms
        # Twilio's MessageSid lands in the telnyx_id column — see the
        # note at the top of this file. /webhooks/twilio/status PATCHes
        # delivery receipts by matching on it.
        from_number = await sender_for(client, business_id)
        telnyx_id = await run_in_threadpool(
            twilio_sms.send_sms, to_clean, message, from_number=from_number)
    except Exception as e:
        logger.warning(f"[SMS] twilio send failed: {e}")
        raise SmsSendError(str(e)[:300], 502)

    msg_id = await _store_sms(
        client,
        business_id=business_id,
        contact_id=contact_id,
        phone_number=to_clean,
        message=message,
        direction="outbound",
        telnyx_id=telnyx_id,
        status="sent",
        sent_by=sent_by,
    )

    await _log_event(client, business_id, contact_id, "sms_sent", {
        "to": to_clean,
        "preview": message[:200],
        "telnyx_id": telnyx_id,
        "sms_id": msg_id,
    })

    if contact_id:
        await _sb_patch(client, f"/contacts?id=eq.{contact_id}", {
            "last_interaction": datetime.now(timezone.utc).isoformat(),
        })

    logger.info(f"[SMS] sent biz={business_id[:8]} to={to_clean} len={len(message)} telnyx={telnyx_id}")
    return {"status": "sent", "id": msg_id, "telnyx_id": telnyx_id}


@router.post("/sms/send")
async def send_sms(req: SendSmsRequest, user: AuthedUser = Depends(require_user)):
    """Send an SMS (Twilio Messaging Service first; Telnyx fallback)
    and persist it as outbound. Thin wrapper over send_sms_core."""
    # WHOSE BUSINESS. `require_user` only proves the caller is signed in
    # — as ANY user on the platform. business_id arrived in the request
    # and was trusted, so a signed-in stranger could text anyone AS any
    # business: the recipient sees that business's name in the body, the
    # send lands in that business's thread, and it spends their carrier
    # reputation and their 10DLC standing. This is the
    # defect email_sender.send_email already carries a fix and a comment
    # for; SMS never got the sweep, because ownership_sweep exempted this
    # whole module as "inbound webhooks" — which the Twilio webhooks in
    # twilio_sms.py are, and these practitioner endpoints are not.
    import business_access
    business_access.assert_access(str(req.business_id), user, "member")
    async with httpx.AsyncClient() as client:
        try:
            return await send_sms_core(
                client, business_id=req.business_id, to=req.to,
                message=req.message, contact_id=req.contact_id)
        except SmsSendError as e:
            return JSONResponse({"error": str(e)}, e.status)


# ─── Contact lookup helpers ──────────────────────────────────────────

async def _find_contact_by_phone(
    client: httpx.AsyncClient,
    business_id: str,
    phone: str,
) -> Optional[Dict[str, Any]]:
    """Find a contact by phone number. Tries exact E.164 first, then a
    last-10-digits suffix match for tolerance against varied formats."""
    if not phone:
        return None
    rows = await _sb_get(client,
        f"/contacts?business_id=eq.{business_id}&phone=eq.{_pq(phone)}"
        f"&select=id,name,phone,health_score,status&limit=1")
    if rows:
        return rows[0]
    last10 = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if not last10:
        return None
    rows = await _sb_get(client,
        f"/contacts?business_id=eq.{business_id}&phone=like.%25{last10}"
        f"&select=id,name,phone,health_score,status&limit=1")
    return rows[0] if rows else None


# ─── Inbound ─────────────────────────────────────────────────────────
#
# There is no inbound handler here any more. Telnyx's /sms/inbound
# endpoint, and the Ed25519 verifier that guarded it, are gone with the
# rest of the provider.
#
# Inbound SMS arrives on Twilio's own webhooks in twilio_sms.py:
#   POST /webhooks/twilio/sms      validates X-Twilio-Signature, then
#                                  sms_routing.route_inbound, replying
#                                  as TwiML on the same response
#   POST /webhooks/twilio/status   delivery receipts, PATCHed onto
#                                  sms_messages by provider id
#
# Worth stating plainly: the deleted verifier was ADDED in this same
# audit, three days ago, as part of signing the unauthenticated inbound
# webhooks. Signing a dead endpoint was the right move while it was
# still reachable and the wrong one to keep — an endpoint that cannot be
# removed is worth hardening, and one that can is worth removing. The
# whole surface goes rather than the risk being managed.

async def record_inbound_sms(
    client: httpx.AsyncClient,
    *,
    from_number: str,
    text: str,
    business_id: str,
    provider_id: str = "",
    media: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Shared inbound pipeline, called by sms_routing.route_inbound once
    routing has decided WHICH business a text belongs to. Resolves the
    contact within that business (creating one if needed), persists the
    row (read=false -> drives the unread badge), logs the event,
    notifies Chief, and bumps contact health.

    business_id is required. It used to be optional: the Telnyx webhook
    called this with None and the function then guessed -- global
    contact match, else "the oldest business on the platform". On a
    single-tenant install that was a sensible default. On this one it
    means an unrecognised number's text lands in whichever practitioner
    signed up first. Routing already knows the answer by the time it
    gets here, so the guess is gone with the webhook that needed it.
    """
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    current_health = 50

    contact = await _find_contact_by_phone(client, business_id, from_number)
    if not contact:
        created = await _sb_post(client, "/contacts", {
            "business_id": business_id,
            "name": from_number,      # practitioner renames later
            "phone": from_number,
            "status": "active",
        })
        contact = (created or [None])[0] if isinstance(created, list) else created
    if contact:
        contact_id = contact.get("id")
        contact_name = contact.get("name")
        current_health = int(contact.get("health_score") or 50)

    # Persist
    msg_id = await _store_sms(
        client,
        business_id=business_id,
        contact_id=contact_id,
        phone_number=from_number,
        message=text,
        direction="inbound",
        telnyx_id=provider_id,
        status="received",
        media=media,
    )

    await _log_event(client, business_id, contact_id, "sms_received", {
        "from": from_number,
        "from_name": contact_name or "",
        "preview": text[:200],
        "telnyx_id": provider_id,
        "has_media": bool(media),
        "sms_id": msg_id,
    })

    await _sb_post(client, "/chief_notifications", {
        "business_id": business_id,
        "type": "info",
        "title": f"Text from {contact_name or from_number}",
        "body": text[:200],
        "suggested_action": f"Reply to {contact_name or from_number}",
        "status": "unread",
        "data": {
            "contact_id": contact_id,
            "sms_id": msg_id,
            "from_number": from_number,
            "preview": text[:200],
        },
    })

    if contact_id:
        await _sb_patch(client, f"/contacts?id=eq.{contact_id}", {
            "health_score": min(100, current_health + 5),
            "last_interaction": datetime.now(timezone.utc).isoformat(),
        })

    logger.info(
        f"[SMS] inbound from={from_number} biz={business_id[:8]} "
        f"contact={(contact_id or 'unknown')[:8]} len={len(text)}"
    )
    return {"status": "processed", "sms_id": msg_id}


# ─── Conversation thread ─────────────────────────────────────────────

@router.get("/sms/conversation/{business_id}/{contact_id}")
async def get_conversation(business_id: str, contact_id: str, user: AuthedUser = Depends(require_user)):
    """Return the full ordered SMS thread for a contact."""
    # WHOSE BUSINESS. `require_user` only proves the caller is signed in
    # — as ANY user on the platform. business_id arrived in the request
    # and was trusted, so a signed-in stranger could read any business's
    # entire SMS thread with any of their clients, message bodies
    # included. The whole reason this module moved off the anon key (see
    # _sb_anon) is that sms_messages content must not be readable with a
    # public credential — and this handed it out over the service role
    # instead. This is the
    # defect email_sender.send_email already carries a fix and a comment
    # for; SMS never got the sweep, because ownership_sweep exempted this
    # whole module as "inbound webhooks" — which the Twilio webhooks in
    # twilio_sms.py are, and these practitioner endpoints are not.
    import business_access
    business_access.assert_access(str(business_id), user, "viewer")
    async with httpx.AsyncClient() as client:
        rows = await _sb_get(client,
            f"/sms_messages?business_id=eq.{business_id}&contact_id=eq.{contact_id}"
            f"&order=created_at.asc&limit=200"
            f"&select=id,direction,phone_number,message,status,telnyx_id,media_urls,created_at,read"
        ) or []
    return {"messages": rows}


# ─── Session reminder ────────────────────────────────────────────────

class SessionReminderRequest(BaseModel):
    business_id: str
    session_id: str


@router.post("/sms/session-reminder")
async def send_session_reminder(req: SessionReminderRequest, user: AuthedUser = Depends(require_user)):
    """Send a friendly SMS reminder for an upcoming session.

    Pulls the session + contact + business name, formats a short
    message, and routes through /sms/send so all the usual storage +
    event-logging fires.
    """
    # WHOSE BUSINESS. `require_user` only proves the caller is signed in
    # — as ANY user on the platform. business_id arrived in the request
    # and was trusted, so a signed-in stranger could send a reminder as
    # any business, to that business's own client. This is the
    # defect email_sender.send_email already carries a fix and a comment
    # for; SMS never got the sweep, because ownership_sweep exempted this
    # whole module as "inbound webhooks" — which the Twilio webhooks in
    # twilio_sms.py are, and these practitioner endpoints are not.
    import business_access
    business_access.assert_access(str(req.business_id), user, "member")

    async with httpx.AsyncClient() as client:
        sess_rows = await _sb_get(client,
            f"/sessions?id=eq.{req.session_id}&business_id=eq.{req.business_id}"
            f"&select=id,scheduled_for,session_type,contact_id&limit=1") or []
        if not sess_rows:
            return JSONResponse({"error": "Session not found"}, 404)
        session = sess_rows[0]

        contact_id = session.get("contact_id")
        if not contact_id:
            return JSONResponse({"error": "Session has no contact"}, 400)

        contact_rows = await _sb_get(client,
            f"/contacts?id=eq.{contact_id}&select=id,name,phone&limit=1") or []
        if not contact_rows:
            return JSONResponse({"error": "Contact not found"}, 404)
        contact = contact_rows[0]
        if not contact.get("phone"):
            return JSONResponse({"error": "Contact has no phone number"}, 400)

        biz_rows = await _sb_get(client,
            f"/businesses?id=eq.{req.business_id}&select=name&limit=1") or []
        biz_name = biz_rows[0].get("name") if biz_rows else "your practitioner"

        try:
            scheduled = datetime.fromisoformat(
                str(session["scheduled_for"]).replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            return JSONResponse({"error": "Invalid scheduled_for"}, 400)

        # Cross-platform-safe time/day formatting (no %-d on Windows).
        time_str = scheduled.strftime("%I:%M %p").lstrip("0")
        date_str = scheduled.strftime("%A, %B %d").replace(" 0", " ")
        session_type = (session.get("session_type") or "session").replace("_", " ")
        first_name = (contact.get("name") or "").split()[0] if contact.get("name") else ""

        greeting = f"Hi {first_name}! " if first_name else "Hi! "
        message = (
            f"{greeting}Reminder: your {session_type} with {biz_name} is "
            f"{date_str} at {time_str}. Reply Y to confirm or let me know if you need to reschedule."
        )

    return await send_sms(SendSmsRequest(
        business_id=req.business_id,
        contact_id=contact_id,
        to=contact["phone"],
        message=message,
    ))


@router.get("/sms/health")
async def sms_health():
    configured = _twilio_configured()
    return {
        "status": "ok",
        "provider": "twilio" if configured else "none",
        "twilio_configured": configured,
    }
