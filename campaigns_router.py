"""
campaigns_router.py — Marketing Campaigns Phase 1 (2026-07-21).

"Chief as Marketing Director", the spine: a campaign is a goal + an
audience slice + a sequence of touches (email/SMS) that Chief drafts in
the practitioner's voice. The practitioner reviews/edits, launches once,
and campaigns_tick executes touches on schedule — through the SAME rails
everything else uses (Resend + suppression, platform SMS + the shared
consent rule + quiet hours).

Honesty contract:
- Audience counts shown pre-launch come from the same query the sweep
  uses at send time. No estimated reach, ever.
- Results are labeled activity: sends from the campaign_sends ledger,
  replies/bookings = events among the audience since launch (correlation
  surfaced as such, not claimed as attribution).
- campaign_sends UNIQUE(campaign,touch,contact) = the sweep can crash
  mid-run and re-run without double-sending anyone.

Kill switch: CAMPAIGNS=off (endpoints keep working; the sweep no-ops).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

import llm_call
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("campaigns")

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

ANTHROPIC_VERSION = "2023-06-01"
DRAFT_MODEL = os.environ.get("CAMPAIGN_DRAFT_MODEL", "claude-sonnet-5")
HTTP_TIMEOUT = 60.0

MAX_TOUCHES = 8
MAX_SENDS_PER_TICK = 100        # safety valve; the next tick continues
SEND_PACING_SEC = 0.25          # same gentle pacing as /sms/broadcast

AUDIENCE_KINDS = ("silent", "leads", "clients", "all")


def campaigns_enabled() -> bool:
    return (os.environ.get("CAMPAIGNS") or "on").strip().lower() not in (
        "off", "0", "false", "no")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts_for_query(value: Any) -> str:
    """Timestamp formatted for a PostgREST QUERY STRING. isoformat()'s
    '+00:00' offset reads as a space in a URL and silently kills the
    whole filter (the live '0 people' bug, 2026-07-21) — always use the
    'Z' form in query paths. JSON bodies are unaffected."""
    s = str(value)
    return s.replace("+00:00", "Z").replace(" ", "T")


# ─── Ownership / loading ─────────────────────────────────────────────

def _load_business(business_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "Business not found")
    return rows[0]


def _require_owner(user: AuthedUser, business: Dict[str, Any],
                   min_role: str = "viewer") -> None:
    """Seat-access arc (7/31): role-ranked. Owner always passes; team
    seats pass by rank — reads at viewer, draft/edit at member,
    launch/pause/delete at manager (bulk sends spend Twilio money)."""
    if business.get("owner_id") == user.id:
        return
    from business_users_router import require_role
    require_role(str(business.get("id")), str(user.id), min_role)


def _load_campaign(campaign_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/campaigns?id=eq.{campaign_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "Campaign not found")
    return rows[0]


# ─── Audience resolution (ONE query shape, used everywhere) ──────────

def _audience_filter(audience: Dict[str, Any]) -> str:
    """PostgREST filter for the audience slice. The SAME string is used
    for the pre-launch preview and the send-time sweep — the number the
    practitioner approved is the number the sweep works from."""
    kind = (audience or {}).get("kind") or "silent"
    if kind == "leads":
        return "status=eq.lead"
    if kind == "clients":
        return "status=in.(active,vip)"
    if kind == "all":
        return "status=not.in.(inactive,churned)"
    # 'silent' — quiet for N+ days (or never contacted), not inactive.
    days = int((audience or {}).get("days_silent") or 30)
    cutoff = _ts_for_query((_now() - timedelta(days=days)).isoformat())
    return (f"status=not.in.(inactive,churned)"
            f"&or=(last_interaction.is.null,last_interaction.lt.{cutoff})")


def _resolve_audience(business_id: str, audience: Dict[str, Any]) -> List[Dict[str, Any]]:
    filt = _audience_filter(audience)
    return sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&{filt}"
        f"&select=id,name,email,phone,status,last_interaction&limit=500") or []


def _audience_summary(contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    emailable = [c for c in contacts if (c.get("email") or "").strip()]
    textable = [c for c in contacts if (c.get("phone") or "").strip()]
    return {
        "count": len(contacts),
        "emailable": len(emailable),
        "textable": len(textable),
        "sample": [c.get("name") or "?" for c in contacts[:5]],
    }


# ─── Touch validation ────────────────────────────────────────────────

def _clean_touches(raw: Any) -> List[Dict[str, Any]]:
    """Validate/normalize a touches list from the model or the editor.
    Unknown channels and empty bodies are dropped; offsets clamp 0-60."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for t in raw[:MAX_TOUCHES]:
        if not isinstance(t, dict):
            continue
        channel = (t.get("channel") or "").strip().lower()
        body = (t.get("body") or "").strip()
        if channel not in ("email", "sms") or not body:
            continue
        try:
            offset = max(0, min(60, int(t.get("offset_days") or 0)))
        except (TypeError, ValueError):
            offset = 0
        touch: Dict[str, Any] = {
            "channel": channel,
            "offset_days": offset,
            "body": body,
            "completed_at": t.get("completed_at"),
        }
        if channel == "email":
            touch["subject"] = (t.get("subject") or "").strip() or "A note from us"
        out.append(touch)
    out.sort(key=lambda t: t["offset_days"])
    return out


def _personalize(text: str, contact: Dict[str, Any]) -> str:
    first = ((contact.get("name") or "").strip().split(" ") or ["there"])[0] or "there"
    return text.replace("{{first_name}}", first)


# ─── Chief drafting ──────────────────────────────────────────────────

async def _draft_campaign_with_chief(business: Dict[str, Any], goal: str,
                                     audience: Dict[str, Any],
                                     summary: Dict[str, Any]) -> Dict[str, Any]:
    """One model call → {name, touches[]}. Falls back to a plain
    2-touch skeleton if the model is unavailable — the practitioner can
    still edit + launch (fail-open, never fail-dark)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    biz_name = business.get("name") or "the business"
    practitioner = (business.get("settings") or {}).get("practitioner_name") or "the owner"
    voice = business.get("voice_profile") or {}
    fallback = {
        "name": (goal or "New campaign")[:60],
        "touches": [
            {"channel": "email", "offset_days": 0,
             "subject": f"A note from {biz_name}",
             "body": f"Hi {{{{first_name}}}},\n\nJust reaching out personally — {goal or 'we have something coming up you should know about'}.\n\nReply and let me know if you're interested.\n\n— {practitioner}"},
            {"channel": "email", "offset_days": 4,
             "subject": "Following up",
             "body": f"Hi {{{{first_name}}}},\n\nCircling back on my last note — I'd love to hear from you.\n\n— {practitioner}"},
        ],
    }
    if not key:
        return fallback

    kind = (audience or {}).get("kind") or "silent"
    system = (
        f"You are the marketing director for {biz_name}, a {business.get('type') or 'general'} "
        f"business. You write in the personal voice of {practitioner}. "
        f"Voice profile: tone={voice.get('tone', 'warm and professional')}; "
        f"personality={voice.get('personality', 'helpful')}; "
        f"audience={voice.get('audience', 'clients')}. "
        "Design a short outreach campaign as JSON ONLY (no prose, no code fences): "
        '{"name": str (<=60 chars), "touches": [{"channel": "email"|"sms", '
        '"offset_days": int (0 = launch day), "subject": str (email only), "body": str}]}. '
        "Rules: 2-4 touches. Emails read like a personal note from "
        f"{practitioner} (not a newsletter), under 150 words, may use {{{{first_name}}}}. "
        "Include at most ONE sms touch, under 300 chars, only if it genuinely helps; "
        "sms must end with 'Reply STOP to opt out.' "
        "Every email ends with a genuine sign-off from the practitioner. No emojis in subjects."
    )
    user_msg = (
        f"Goal: {goal or 'Re-engage this audience.'}\n"
        f"Audience: {kind} — {summary['count']} people "
        f"({summary['emailable']} reachable by email, {summary['textable']} by text).\n"
        "Draft the campaign."
    )
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await llm_call.apost(client, {
                "model": DRAFT_MODEL, "max_tokens": 1500, "system": system,
                "messages": [{"role": "user", "content": user_msg}],
            }, key=key)
        if resp.status_code >= 400:
            logger.warning(f"campaign draft model error {resp.status_code}")
            return fallback
        text = "".join(b.get("text", "") for b in resp.json().get("content", [])
                       if isinstance(b, dict)).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        data = json.loads(text)
        touches = _clean_touches(data.get("touches"))
        if not touches:
            return fallback
        return {"name": (data.get("name") or fallback["name"])[:60],
                "touches": touches}
    except Exception as e:
        logger.warning(f"campaign draft failed, using fallback: {e}")
        return fallback


# ─── Cores (shared by the HTTP endpoints and Chief's campaign verbs) ─
#
# S10 gap-close: campaigns had a full product surface and ZERO
# Chief-callable actions. The verbs (chief_campaign_actions.py) must not
# re-derive audience/consent/launch rules — one query shape, one launch
# check-list, whoever calls. Each core raises the same HTTPExceptions the
# endpoint always raised, so HTTP behavior is unchanged and the Chief
# handlers translate them into honest failure labels.

async def plan_campaign_core(biz: Dict[str, Any], goal: str,
                             audience_in: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Draft a campaign for a goal + audience. Saves a DRAFT row —
    nothing sends until a launch. Returns {campaign, audience_preview}."""
    import billing_limits
    billing_limits.require_units(biz["id"])   # Chief drafts = an AI action
    audience = audience_in if (audience_in or {}).get("kind") in AUDIENCE_KINDS \
        else {"kind": "silent", "days_silent": 30}
    contacts = _resolve_audience(biz["id"], audience)
    summary = _audience_summary(contacts)
    draft = await _draft_campaign_with_chief(biz, (goal or "").strip(), audience, summary)
    rows = sb_clients.sb_post_as_service("/campaigns", {
        "business_id": biz["id"],
        "name": draft["name"],
        "goal": (goal or "").strip() or None,
        "audience": audience,
        "touches": draft["touches"],
        "status": "draft",
    }) or []
    row = rows[0] if isinstance(rows, list) and rows else None
    if not row:
        raise HTTPException(500, "Campaign insert failed — is the campaigns migration applied?")
    return {"campaign": row, "audience_preview": summary}


def launch_campaign_core(biz: Dict[str, Any], camp: Dict[str, Any],
                         start_at_override: Optional[str] = None) -> Dict[str, Any]:
    """Flip a draft/paused campaign to running. The audience count checked
    here is the SAME query the sweep sends from (honesty contract). The
    sweep — not the launch — enforces consent, suppression and quiet
    hours per send. Returns {campaign, audience_preview}."""
    # A locked (canceled/expired) account must not bulk-send — Twilio
    # spend on a dead subscription. Dormant behind BILLING_ENFORCE.
    import billing_limits
    billing_limits.require_live_access(camp["business_id"])
    if camp.get("status") not in ("draft", "paused"):
        raise HTTPException(409, f"Campaign is {camp.get('status')}.")
    touches = _clean_touches(camp.get("touches"))
    if not touches:
        raise HTTPException(400, "Add at least one touch before launching.")
    summary = _audience_summary(_resolve_audience(biz["id"], camp.get("audience") or {}))
    if summary["count"] == 0:
        raise HTTPException(409, "This audience is empty right now — nothing to send.")
    start_at = camp.get("start_at")
    if camp.get("status") == "draft" or not start_at:
        start_at = (start_at_override or _now().isoformat())
    sb_clients.sb_patch_as_service(f"/campaigns?id=eq.{camp['id']}", {
        "status": "running", "start_at": start_at,
        "updated_at": _now().isoformat(),
    })
    return {"campaign": _load_campaign(camp["id"]), "audience_preview": summary}


def pause_campaign_core(camp: Dict[str, Any]) -> Dict[str, Any]:
    """Pause a running campaign — the sweep skips non-running rows, so
    nothing more sends until a relaunch. Returns the updated campaign."""
    if camp.get("status") != "running":
        raise HTTPException(409, f"Campaign is {camp.get('status')}.")
    sb_clients.sb_patch_as_service(f"/campaigns?id=eq.{camp['id']}", {
        "status": "paused", "updated_at": _now().isoformat()})
    return _load_campaign(camp["id"])


def list_campaigns_core(business_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Recent campaigns with their sent_total folded in (one query)."""
    rows = sb_clients.sb_get_as_service(
        f"/campaigns?business_id=eq.{business_id}"
        f"&order=created_at.desc&limit={limit}&select=*") or []
    ids = ",".join(r["id"] for r in rows)
    counts: Dict[str, int] = {}
    if ids:
        sends = sb_clients.sb_get_as_service(
            f"/campaign_sends?campaign_id=in.({ids})&select=campaign_id") or []
        for s in sends:
            counts[s["campaign_id"]] = counts.get(s["campaign_id"], 0) + 1
    for r in rows:
        r["sent_total"] = counts.get(r["id"], 0)
    return rows


# ─── Endpoints ───────────────────────────────────────────────────────

class PlanBody(BaseModel):
    business_id: str
    goal: str = ""
    audience: Dict[str, Any] = {}


class PatchBody(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    audience: Optional[Dict[str, Any]] = None
    touches: Optional[List[Dict[str, Any]]] = None


class LaunchBody(BaseModel):
    start_at: Optional[str] = None


@router.post("/plan")
async def plan_campaign(body: PlanBody, user: AuthedUser = Depends(require_user)):
    """Chief drafts a campaign for a goal + audience. Saved as a DRAFT —
    nothing sends until the practitioner reviews and launches."""
    biz = _load_business(body.business_id)
    _require_owner(user, biz, min_role="member")
    return {"ok": True, **(await plan_campaign_core(biz, body.goal, body.audience))}


@router.get("")
async def list_campaigns(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _load_business(business_id)
    _require_owner(user, biz)
    return {"ok": True, "campaigns": list_campaigns_core(business_id)}


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str, user: AuthedUser = Depends(require_user)):
    camp = _load_campaign(campaign_id)
    biz = _load_business(camp["business_id"])
    _require_owner(user, biz)
    return {"ok": True, "campaign": camp, "results": _campaign_results(camp)}


@router.post("/{campaign_id}/audience-preview")
async def audience_preview(campaign_id: str, user: AuthedUser = Depends(require_user)):
    camp = _load_campaign(campaign_id)
    biz = _load_business(camp["business_id"])
    _require_owner(user, biz)
    return {"ok": True,
            "audience_preview": _audience_summary(
                _resolve_audience(biz["id"], camp.get("audience") or {}))}


@router.patch("/{campaign_id}")
async def patch_campaign(campaign_id: str, body: PatchBody,
                         user: AuthedUser = Depends(require_user)):
    camp = _load_campaign(campaign_id)
    biz = _load_business(camp["business_id"])
    _require_owner(user, biz, min_role="member")
    if camp.get("status") not in ("draft", "paused"):
        raise HTTPException(409, "Only draft or paused campaigns can be edited.")
    patch: Dict[str, Any] = {"updated_at": _now().isoformat()}
    if body.name is not None:
        patch["name"] = body.name.strip()[:60] or camp["name"]
    if body.goal is not None:
        patch["goal"] = body.goal.strip() or None
    if body.audience is not None and (body.audience or {}).get("kind") in AUDIENCE_KINDS:
        patch["audience"] = body.audience
    if body.touches is not None:
        touches = _clean_touches(body.touches)
        if not touches:
            raise HTTPException(400, "A campaign needs at least one valid touch.")
        patch["touches"] = touches
    sb_clients.sb_patch_as_service(f"/campaigns?id=eq.{campaign_id}", patch)
    return {"ok": True, "campaign": _load_campaign(campaign_id)}


@router.post("/{campaign_id}/launch")
async def launch_campaign(campaign_id: str, body: LaunchBody,
                          user: AuthedUser = Depends(require_user)):
    camp = _load_campaign(campaign_id)
    biz = _load_business(camp["business_id"])
    _require_owner(user, biz, min_role="manager")
    return {"ok": True, **launch_campaign_core(biz, camp, body.start_at)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, user: AuthedUser = Depends(require_user)):
    camp = _load_campaign(campaign_id)
    biz = _load_business(camp["business_id"])
    _require_owner(user, biz, min_role="manager")
    return {"ok": True, "campaign": pause_campaign_core(camp)}


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str, user: AuthedUser = Depends(require_user)):
    camp = _load_campaign(campaign_id)
    biz = _load_business(camp["business_id"])
    _require_owner(user, biz, min_role="manager")
    if camp.get("status") not in ("draft", "completed", "paused"):
        raise HTTPException(409, "Pause a running campaign before deleting it.")
    sb_clients.sb_delete_as_service(f"/campaigns?id=eq.{campaign_id}")
    return {"ok": True}


# ─── Results (honest activity, not claimed attribution) ──────────────

def _campaign_results(camp: Dict[str, Any]) -> Dict[str, Any]:
    sends = sb_clients.sb_get_as_service(
        f"/campaign_sends?campaign_id=eq.{camp['id']}"
        f"&select=touch_idx,channel,contact_id") or []
    by_touch: Dict[int, int] = {}
    contact_ids = set()
    emails = texts = 0
    for s in sends:
        by_touch[s["touch_idx"]] = by_touch.get(s["touch_idx"], 0) + 1
        contact_ids.add(s["contact_id"])
        if s["channel"] == "email":
            emails += 1
        else:
            texts += 1
    replies = bookings = 0
    start = camp.get("start_at")
    if start and contact_ids:
        ids = ",".join(sorted(contact_ids))
        ev = sb_clients.sb_get_as_service(
            f"/events?business_id=eq.{camp['business_id']}"
            f"&contact_id=in.({ids})&created_at=gte.{_ts_for_query(start)}"
            f"&event_type=in.(email_reply_received,email_replied,sms_received,booking_created)"
            f"&select=event_type") or []
        for e in ev:
            if e["event_type"] == "booking_created":
                bookings += 1
            else:
                replies += 1
    return {"emails_sent": emails, "texts_sent": texts,
            "people_reached": len(contact_ids),
            "replies_since_launch": replies,
            "bookings_since_launch": bookings,
            "sends_by_touch": by_touch}


# ─── The sweep (scheduler leader, minute cadence) ────────────────────

async def campaigns_tick() -> Dict[str, int]:
    """Execute due touches for running campaigns. Never raises.
    Exactly-once per (campaign,touch,contact) via the sends ledger;
    per-tick send cap; SMS honors the shared consent rule + quiet hours;
    email honors the suppression list."""
    stats = {"campaigns": 0, "emails": 0, "sms": 0, "skipped": 0, "completed": 0}
    if not campaigns_enabled():
        return stats
    try:
        running = sb_clients.sb_get_as_service(
            "/campaigns?status=eq.running&select=*&limit=100") or []
    except Exception as e:
        logger.warning(f"campaigns_tick list failed: {e}")
        return stats

    import email_sender
    import sms_alerts
    from sms_routing import _send_platform_sms
    from sms_service import _store_sms, normalize_phone

    budget = MAX_SENDS_PER_TICK
    for camp in running:
        if budget <= 0:
            break
        stats["campaigns"] += 1
        try:
            biz = _load_business(camp["business_id"])
        except HTTPException:
            continue
        # The practitioner's pause switch, honored here too.
        #
        # settings.automations_paused stopped the rules engine and the
        # trust sweep and nothing else — so a practitioner who paused
        # their automations watched a campaign keep mailing their list.
        # This path has no Chief verb to hand policy_engine, which is
        # where the check now lives for the four paths that do, so it
        # reads the same predicate directly.
        #
        # The campaign stays RUNNING and is simply not advanced: pausing
        # automations is a "not now", not a cancellation, and the touches
        # resume from where they stopped when it is switched back on.
        try:
            import rules_engine
            if rules_engine.business_paused(biz):
                stats["skipped"] += 1
                continue
        except Exception as e:
            logger.warning(f"campaigns_tick pause check failed for "
                           f"{camp.get('business_id')}: {e}")
        touches = camp.get("touches") or []
        start_raw = camp.get("start_at")
        if not start_raw:
            continue
        start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        contacts = _resolve_audience(camp["business_id"], camp.get("audience") or {})
        already = sb_clients.sb_get_as_service(
            f"/campaign_sends?campaign_id=eq.{camp['id']}"
            f"&select=touch_idx,contact_id") or []
        sent_keys = {(s["touch_idx"], s["contact_id"]) for s in already}

        touches_dirty = False
        all_done = True
        for idx, touch in enumerate(touches):
            if touch.get("completed_at"):
                continue
            due_at = start + timedelta(days=int(touch.get("offset_days") or 0))
            if due_at > _now():
                all_done = False
                continue
            pending = [c for c in contacts if (idx, c["id"]) not in sent_keys]
            remaining = 0
            for contact in pending:
                if budget <= 0:
                    remaining += 1
                    continue
                try:
                    sent = await _send_touch(
                        biz, camp, idx, touch, contact,
                        email_sender, sms_alerts, _send_platform_sms,
                        _store_sms, normalize_phone)
                except _Defer:
                    # Quiet hours — leave unclaimed; a daytime tick sends.
                    remaining += 1
                    continue
                except Exception as e:
                    logger.warning(f"campaign send failed c={contact.get('id')}: {e}")
                    sent = "skipped"
                if sent == "email":
                    stats["emails"] += 1
                    budget -= 1
                elif sent == "sms":
                    stats["sms"] += 1
                    budget -= 1
                else:
                    stats["skipped"] += 1
                await asyncio.sleep(SEND_PACING_SEC)
            if remaining == 0:
                touch["completed_at"] = _now().isoformat()
                touches_dirty = True
            else:
                all_done = False

        patch: Dict[str, Any] = {}
        if touches_dirty:
            patch["touches"] = touches
        if all_done and touches and all(t.get("completed_at") for t in touches):
            patch["status"] = "completed"
            stats["completed"] += 1
            _notify_completed(biz, camp)
        if patch:
            patch["updated_at"] = _now().isoformat()
            try:
                sb_clients.sb_patch_as_service(f"/campaigns?id=eq.{camp['id']}", patch)
            except Exception as e:
                logger.warning(f"campaign patch failed {camp['id']}: {e}")
    if stats["emails"] or stats["sms"] or stats["completed"]:
        logger.info(f"campaigns_tick: {stats}")
    return stats


async def _send_touch(biz, camp, idx, touch, contact,
                      email_sender, sms_alerts, send_platform_sms,
                      store_sms, normalize_phone) -> str:
    """One send. Returns 'email' | 'sms' | 'skipped'. Records the
    campaign_sends row FIRST (unique key) so a crash after insert can
    never double-send — a lost send costs less than a duplicate."""
    channel = touch.get("channel")
    body = _personalize(touch.get("body") or "", contact)

    if channel == "email":
        to_email = (contact.get("email") or "").strip()
        if not to_email:
            return "skipped"
        if await email_sender.is_suppressed(to_email):
            return "skipped"
        claimed = sb_clients.sb_post_as_service("/campaign_sends", {
            "campaign_id": camp["id"], "business_id": camp["business_id"],
            "touch_idx": idx, "contact_id": contact["id"], "channel": "email",
        })
        if not claimed:
            return "skipped"   # duplicate key → someone already sent it
        subject = _personalize(touch.get("subject") or "A note from us", contact)
        reply_to = email_sender.build_routed_reply_to(camp["business_id"], contact["id"])
        await email_sender.send_via_resend(
            to_email=to_email, to_name=contact.get("name"),
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=biz.get("name") or None,
            subject=subject, body=body,
            reply_to=reply_to or None,
            business_id=camp["business_id"])
        _log_campaign_event(camp, contact, "campaign_email_sent",
                            {"touch_idx": idx, "subject": subject})
        return "email"

    if channel == "sms":
        phone = normalize_phone(contact.get("phone") or "")
        if not phone:
            return "skipped"
        if not sms_alerts.alerts_enabled():
            return "skipped"
        # Quiet hours: same window as the reminder sweep — outside it we
        # simply DON'T claim the send, so the next daytime tick delivers.
        now_et = _now().astimezone(sms_alerts.QUIET_TZ)
        if not (sms_alerts.QUIET_SEND_START_HOUR <= now_et.hour
                < sms_alerts.QUIET_SEND_END_HOUR):
            raise _Defer()
        # Sender identity + opt-out (the PR #308 rule): a campaign touch
        # is bulk unsolicited-feeling traffic on the ONE Twilio number
        # every business shares — exactly the profile /sms/broadcast has.
        # Brand it the same way: business name leads the body, and every
        # message carries the way out. compose_outbound_body is idempotent
        # (a touch Chief drafted as "Craft & Co: ..." is not double-
        # prefixed) and caps the brand prefix at 32 chars. Composed per
        # contact because the body is personalized per contact.
        from sms_service import compose_outbound_body
        sms_body = compose_outbound_body(
            biz.get("name"), body, include_optout=True)
        async with httpx.AsyncClient(timeout=30.0) as client:
            if not await sms_alerts.has_sms_consent(client, camp["business_id"], phone):
                return "skipped"
            claimed = sb_clients.sb_post_as_service("/campaign_sends", {
                "campaign_id": camp["id"], "business_id": camp["business_id"],
                "touch_idx": idx, "contact_id": contact["id"], "channel": "sms",
            })
            if not claimed:
                return "skipped"
            msg_id = await send_platform_sms(phone, sms_body)
            await store_sms(client, camp["business_id"], contact["id"],
                            phone, sms_body, "outbound", telnyx_id=msg_id or "")
        _log_campaign_event(camp, contact, "campaign_sms_sent", {"touch_idx": idx})
        return "sms"

    return "skipped"


class _Defer(Exception):
    """Quiet-hours: leave the touch unclaimed for a later tick."""


def _log_campaign_event(camp, contact, event_type: str, data: Dict[str, Any]) -> None:
    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": camp["business_id"],
            "contact_id": contact["id"],
            "event_type": event_type,
            "source": "campaigns",
            "data": {"campaign_id": camp["id"], "campaign_name": camp.get("name"), **data},
        })
    except Exception as e:
        logger.warning(f"campaign event log failed: {e}")


def _notify_completed(biz, camp) -> None:
    try:
        results = _campaign_results(camp)
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": camp["business_id"],
            "type": "success",
            "title": f"Campaign finished — {camp.get('name')}",
            "body": (f"{results['emails_sent']} emails and {results['texts_sent']} "
                     f"texts went out to {results['people_reached']} people. "
                     f"{results['replies_since_launch']} replies and "
                     f"{results['bookings_since_launch']} bookings since launch."),
            "status": "unread",
            "data": {"kind": "campaign_completed", "campaign_id": camp["id"]},
        })
    except Exception as e:
        logger.warning(f"campaign completion notify failed: {e}")
