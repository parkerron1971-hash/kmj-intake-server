# push_notifications.py
# ─────────────────────────────────────────────────────────────────────
# Chief-in-your-pocket (2026-06-12) — Web Push for the installed PWA.
#
#   POST /push/subscribe     — store this device's PushSubscription
#   POST /push/unsubscribe   — remove it
#   GET  /push/vapid-public  — the public key the frontend subscribes with
#   POST /push/test          — send a test push to the caller's devices
#
# send_to_user()/send_to_business() are the internal senders other
# modules call (morning brief tick below; rules_engine proposal pushes).
# Dead subscriptions (404/410 from the push service) are pruned on send.
#
# Env (Kevin sets on Railway):
#   VAPID_PRIVATE_KEY  — base64url private key
#   VAPID_PUBLIC_KEY   — matching public key (served to the frontend)
#   VAPID_SUBJECT      — mailto:kmjcreativesolution@gmail.com
# Generate once with:  npx web-push generate-vapid-keys
#
# Quiet-by-default: if the keys are unset, every endpoint reports
# {"enabled": false} and senders no-op — nothing breaks.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

log = logging.getLogger("push")

router = APIRouter(prefix="/push", tags=["push"])

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:kmjcreativesolution@gmail.com")


def push_enabled() -> bool:
    return bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)


# ─── Models ──────────────────────────────────────────────────────────

class SubscribeBody(BaseModel):
    business_id: str
    subscription: Dict[str, Any]   # the browser PushSubscription.toJSON()
    user_agent: Optional[str] = None


class UnsubscribeBody(BaseModel):
    endpoint: str


# ─── Endpoints ───────────────────────────────────────────────────────

@router.get("/vapid-public")
def vapid_public() -> Dict[str, Any]:
    return {"enabled": push_enabled(), "key": VAPID_PUBLIC_KEY or None}


@router.post("/subscribe")
def subscribe(body: SubscribeBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    if not push_enabled():
        return {"ok": False, "enabled": False}
    # business_id arrives in the BODY and decides who gets fanned out to:
    # send_to_business() pushes to every subscription row carrying it. So
    # a signed-in stranger naming someone else's business would start
    # receiving that practitioner's morning brief, overdue invoices and
    # session alerts. assert_access, not the dependency, because a
    # dependency's parameters resolve from the QUERY STRING.
    import business_access
    business_access.assert_access(str(body.business_id), user, "member")
    endpoint = str(body.subscription.get("endpoint") or "")
    if not endpoint:
        raise HTTPException(status_code=422, detail="subscription.endpoint required")
    sb_clients.sb_post_as_service(
        "/push_subscriptions?on_conflict=endpoint",
        {
            "user_id": user.id,
            "business_id": body.business_id,
            "endpoint": endpoint,
            "subscription": body.subscription,
            "user_agent": (body.user_agent or "")[:300],
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        prefer="resolution=merge-duplicates",
    )
    return {"ok": True, "enabled": True}


@router.post("/unsubscribe")
def unsubscribe(body: UnsubscribeBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    from urllib.parse import quote
    sb_clients.sb_delete_as_service(
        f"/push_subscriptions?endpoint=eq.{quote(body.endpoint, safe='')}&user_id=eq.{user.id}"
    )
    return {"ok": True}


@router.post("/test")
def send_test(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    if not push_enabled():
        return {"ok": False, "enabled": False, "sent": 0}
    sent = send_to_user(
        user.id,
        title="Solutionist",
        body="Push notifications are live on this device. ✦",
        nav="home",
    )
    return {"ok": True, "enabled": True, "sent": sent}


# ─── Senders ─────────────────────────────────────────────────────────

def _send_one(sub_row: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    """Send to a single stored subscription; prune it when the push
    service says it's gone (404/410). Returns True when delivered."""
    try:
        from pywebpush import webpush, WebPushException
    except Exception:  # pragma: no cover — dependency missing
        log.warning("pywebpush not installed; push disabled")
        return False
    try:
        webpush(
            subscription_info=sub_row.get("subscription") or {},
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=3600,
        )
        return True
    except WebPushException as e:  # type: ignore[misc]
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            from urllib.parse import quote
            endpoint = str(sub_row.get("endpoint") or "")
            if endpoint:
                sb_clients.sb_delete_as_service(
                    f"/push_subscriptions?endpoint=eq.{quote(endpoint, safe='')}"
                )
            log.info("pruned dead push subscription (%s)", status)
        else:
            log.warning("push send failed: %s", e)
        return False
    except Exception as e:  # pragma: no cover
        log.warning("push send error: %s", e)
        return False


def _payload(title: str, body: str, nav: str, tag: Optional[str] = None) -> Dict[str, Any]:
    return {"title": title, "body": body, "nav": nav, "tag": tag or "solutionist"}


def send_to_user(user_id: str, *, title: str, body: str, nav: str = "home",
                 tag: Optional[str] = None) -> int:
    if not push_enabled():
        return 0
    rows = sb_clients.sb_get_as_service(
        f"/push_subscriptions?user_id=eq.{user_id}&select=endpoint,subscription&limit=10"
    ) or []
    return sum(1 for r in rows if _send_one(r, _payload(title, body, nav, tag)))


def send_to_business(business_id: str, *, title: str, body: str, nav: str = "home",
                     tag: Optional[str] = None) -> int:
    if not push_enabled():
        return 0
    rows = sb_clients.sb_get_as_service(
        f"/push_subscriptions?business_id=eq.{business_id}&select=endpoint,subscription&limit=20"
    ) or []
    return sum(1 for r in rows if _send_one(r, _payload(title, body, nav, tag)))


# ─── Morning brief tick (scheduler) ──────────────────────────────────
# v1 runs once per day at a fixed UTC hour (13:00 UTC ≈ morning across
# US timezones). Per-business timezones are a follow-on — businesses
# don't store one yet (surfaced in the ship report).

async def morning_brief_tick() -> None:
    if not push_enabled():
        return
    try:
        subs = sb_clients.sb_get_as_service(
            "/push_subscriptions?select=business_id&limit=500"
        ) or []
        biz_ids = sorted({str(r.get("business_id")) for r in subs if r.get("business_id")})
        today = datetime.now(timezone.utc).date().isoformat()
        for biz_id in biz_ids:
            try:
                biz_rows = sb_clients.sb_get_as_service(
                    f"/businesses?id=eq.{biz_id}&select=name,settings"
                ) or []
                if not biz_rows:
                    continue
                settings = (biz_rows[0].get("settings") or {})
                notif = settings.get("notifications") or {}
                if notif.get("morning_brief_enabled") is False:
                    continue

                sessions = sb_clients.sb_get_as_service(
                    f"/sessions?business_id=eq.{biz_id}"
                    f"&scheduled_for=gte.{today}T00:00:00&scheduled_for=lte.{today}T23:59:59"
                    f"&select=id&limit=50"
                ) or []
                drafts = sb_clients.sb_get_as_service(
                    f"/agent_queue?business_id=eq.{biz_id}&status=eq.draft&select=id&limit=50"
                ) or []
                overdue = sb_clients.sb_get_as_service(
                    f"/invoices?business_id=eq.{biz_id}&status=eq.overdue&select=id&limit=50"
                ) or []

                bits: List[str] = []
                if sessions:
                    bits.append(f"{len(sessions)} session{'s' if len(sessions) != 1 else ''} today")
                if overdue:
                    bits.append(f"{len(overdue)} overdue invoice{'s' if len(overdue) != 1 else ''}")
                if drafts:
                    bits.append(f"{len(drafts)} draft{'s' if len(drafts) != 1 else ''} waiting")
                if not bits:
                    bits.append("clear runway — go do the deep work")

                send_to_business(
                    biz_id,
                    title="Good morning ✦ Chief here",
                    body=" · ".join(bits) + ".",
                    nav="home",
                    tag=f"morning-{today}",
                )
            except Exception as e:
                log.warning("morning brief for %s failed: %s", biz_id, e)
    except Exception as e:
        log.warning("morning_brief_tick failed: %s", e)
