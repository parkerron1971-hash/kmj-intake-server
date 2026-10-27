"""
giving_statement_mail.py — email every giver their year-end statement.

    GET  /giving/{business_id}/statements/{year}/mail   what would go out
    POST /giving/{business_id}/statements/{year}/mail   send the next batch

A church owes each giver a contribution statement every January
(giving_statements.py has the IRS Pub 1771 reasoning). Building them
existed; sending them did not, so the January run was a church office
printing and posting 400 envelopes. Subsplash emails them; so do we now.

Rules:
- Only the owner, an admin or an invited accountant (giving_records
  .require_finance), and only on an explicit `confirm: true`. Nothing here
  runs on its own; it is an outbound send, class C.
- `goods_and_services` must be answered and a statement that needs a
  good-faith value estimate is never sent (statement_complete).
- Each giver gets ONE email per year: giving_statement_sends records it
  (unique business, contact, year), and Resend's idempotency key backs
  that up for a retried batch.
- Batches of BATCH so one request never runs long; the response says how
  many are left and the caller asks again.
- A giver with no email, or whose email has bounced or unsubscribed
  (email_sender's suppression), is counted, never guessed at.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import church_keys
import giving_statements as gs
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("giving_statement_mail")

router = APIRouter(tags=["giving"])

BATCH = 40
GOODS = ("none", "religious")


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")


def _year(year: int) -> int:
    if not (2000 <= int(year) <= date.today().year):
        raise HTTPException(400, "Choose a year that has already started")
    return int(year)


def _business(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,type,settings&limit=1")
    if rows is None:
        raise HTTPException(503, "Giving couldn't be read. Nothing was sent; try again.")
    if not rows:
        raise HTTPException(404, "Business not found")
    return rows[0]


def _already_sent(biz: str, year: int) -> Optional[set]:
    rows = sb_clients.sb_get_as_service(
        f"/giving_statement_sends?business_id=eq.{biz}&year=eq.{year}&select=contact_id&limit=10000")
    if rows is None:
        return None
    return {str(r.get("contact_id")) for r in rows}


def plan(business_id: str, year: int) -> Dict[str, Any]:
    """Who would get a statement, who can't, and who already has one."""
    biz = _uuid(business_id)
    year = _year(year)
    business = _business(biz)
    run = gs.statements_for_year(biz, year, org_name=business.get("name"))
    sent = _already_sent(biz, year)
    if sent is None:
        raise HTTPException(503, "The send log couldn't be read. Nothing was sent; try again.")
    donors = run.get("donors") or []
    with_email = [d for d in donors if (d.get("email") or "").strip()]
    to_send = [d for d in with_email if str(d["contact_id"]) not in sent]
    return {
        "ok": True, "year": year, "organisation": business.get("name") or "",
        "donors": len(donors),
        "will_send": len(to_send),
        "already_sent": len(with_email) - len(to_send),
        "no_email": [{"contact_id": d["contact_id"], "name": d.get("name") or ""}
                     for d in donors if not (d.get("email") or "").strip()],
        "unattributed_total": run.get("unattributed_total") or 0,
        "_to_send": to_send,
    }


def _email_body(statement: Dict[str, Any], org: str) -> str:
    first = ((statement.get("donor") or {}).get("name") or "").strip().split(" ")[0] or "Friend"
    return (f"Dear {first},\n\n"
            f"Thank you for your faithful giving to {org} in {statement['year']}. "
            f"Your contribution statement is below. Please keep it with your tax records.\n\n"
            f"{gs.render_text(statement)}\n\n"
            f"With gratitude,\n{org}")


async def send_batch(business_id: str, year: int, goods_and_services: str) -> Dict[str, Any]:
    """Send up to BATCH statements not yet sent this year."""
    from email_sender import send_via_resend
    if goods_and_services not in GOODS:
        # A description needs a value estimate the system doesn't have;
        # such a statement is never complete, so never sendable in bulk.
        raise HTTPException(400, "Say whether anything was given in return: none, or only an intangible religious benefit")
    p = await asyncio.to_thread(plan, business_id, year)
    biz, org = _uuid(business_id), p["organisation"] or "the church"
    sent: List[str] = []
    failed: List[Dict[str, str]] = []
    for d in p["_to_send"][:BATCH]:
        cid = str(d["contact_id"])
        stmt = await asyncio.to_thread(gs.statement_for_contact, biz, cid, p["year"],
                                       org_name=org, goods_and_services=goods_and_services)
        if stmt.get("empty") or not stmt.get("statement_complete"):
            continue
        email = (stmt.get("donor") or {}).get("email") or d.get("email")
        try:
            await send_via_resend(
                to_email=email, to_name=(stmt.get("donor") or {}).get("name") or None,
                from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                from_name=org,
                subject=f"Your {p['year']} giving statement from {org}",
                body=_email_body(stmt, org), reply_to=None, business_id=biz,
                idempotency_key=f"giving-statement:{biz}:{cid}:{p['year']}")
        except Exception as e:
            # Suppressed (bounced, unsubscribed) or the provider refused:
            # counted for the church to follow up, never retried blindly.
            logger.warning(f"[statements] send failed biz={biz[:8]} contact={cid[:8]}: {e}")
            failed.append({"contact_id": cid, "name": d.get("name") or ""})
            continue
        logged = await asyncio.to_thread(sb_clients.sb_post_as_service, "/giving_statement_sends", {
            "business_id": biz, "contact_id": cid, "year": p["year"],
            "email": email, "total": stmt.get("total")})
        if not logged:
            logger.warning(f"[statements] sent but not logged biz={biz[:8]} contact={cid[:8]}")
        sent.append(cid)
    remaining = max(0, p["will_send"] - len(sent) - len(failed))
    return {"ok": True, "year": p["year"], "sent": len(sent), "failed": failed,
            "remaining": remaining, "no_email": p["no_email"]}


@router.get("/giving/{business_id}/statements/{year}/mail")
def statements_mail_plan(business_id: str, year: int, user: AuthedUser = Depends(require_user)):
    from giving_records import require_finance
    require_finance(_uuid(business_id), user)
    church_keys.wall(_uuid(business_id), user, "giving_money")
    out = plan(business_id, year)
    out.pop("_to_send", None)
    return out


@router.post("/giving/{business_id}/statements/{year}/mail")
async def statements_mail_send(business_id: str, year: int, body: Dict[str, Any],
                               user: AuthedUser = Depends(require_user)):
    from giving_records import require_finance
    # Called directly (not via to_thread) so the access sweep can see it.
    require_finance(_uuid(business_id), user)
    church_keys.wall(_uuid(business_id), user, "giving_money")
    if (body or {}).get("confirm") is not True:
        raise HTTPException(400, "Confirm to send the statements")
    return await send_batch(business_id, year, str((body or {}).get("goods_and_services") or ""))
