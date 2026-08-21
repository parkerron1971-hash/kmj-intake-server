"""
sourcing_router.py — THE SOURCING DESK, stage 1 endpoints (2026-08-21).

POST /sourcing/{business_id}/search   run one search (owner, metered, capped)
GET  /sourcing/{business_id}/searches the runs already paid for
GET  /sourcing/{business_id}/limits   what's left today, for the UI

POST /sourcing/{business_id}/rfq/preview  compose, send nothing
POST /sourcing/{business_id}/rfq/send     compose the SAME letter and send it
GET  /sourcing/{business_id}/rfqs         who was asked, and when

TWO GATES, AND THEY ARE NOT THE SAME GATE
  billing_limits.require_units is the METER — this is an AI action and it
  costs the business a unit, on every tier (Kevin's ruling: sourcing is
  not tier-gated; the vendor list is plain CRUD and the search is the
  part that costs).

  The daily cap is the CIRCUIT BREAKER. Metering answers "may they spend
  this?"; it does not answer "should this fire two hundred times?" A
  retry loop in a client, a double-tap on a slow button, or an
  enthusiastic afternoon can each run up a bill against a business that
  meant to search twice. The cap is counted from the rows themselves, so
  it cannot drift from what was actually run.

  Order matters: the cap is checked FIRST. It is free to evaluate and
  refusing early means a capped business is never metered for a search
  it is not going to get.

WHY SEARCHES ARE OWNER-ONLY TO RUN AND MEMBER-READABLE
  Running one spends the business's money. Reading one does not, and the
  people who manage stock should be able to see who was already looked
  at before asking for it to be run again.

THE RFQ IS THE SAME SHAPE AS THE PURCHASE ORDER, ON PURPOSE
  Chief composes, the practitioner reads it, the practitioner says send.
  Preview and send call the SAME composer with the same inputs, so what
  was approved is what goes out. Nothing here sends unattended.

  Fan-out is capped hard and every recipient gets its own row. The
  distance between "ask five manufacturers for a quote" and "an untargeted
  blast tool" is exactly these two constraints, and the thing being
  protected is our sending domain's reputation, which is shared by every
  practitioner on the platform.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import billing_limits
import rfq_engine
import sb_clients
import sourcing_engine
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("sourcing_router")

router = APIRouter(prefix="/sourcing", tags=["sourcing"])

# A day's worth of genuine use is a handful. This is a runaway guard, not
# a rationing device — a practitioner who hits it has either found a bug
# or is doing something the meter should be having an opinion about.
DAILY_SEARCH_CAP = 12

_NEED_MAX = 400
_LIST_CAP = 50

# One ask goes to a handful of vendors, not a list. Five is enough to
# get comparable quotes and small enough that nobody mistakes this for a
# mailing tool.
RFQ_FAN_OUT_CAP = 5
# And a ceiling across the day, for the same reason the search has one.
DAILY_RFQ_CAP = 25
# Asking the same vendor the same thing twice in a week is a mistake, not
# a follow-up. `force` is how someone means it.
RFQ_REPEAT_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    # select=* rather than a named list, and that is the fix for a real
    # outage: this asked for `industry`, a column that does not exist on
    # this schema (it is `type`). PostgREST answers an unknown column with
    # a 400, sb_clients turns any 4xx into None, and the `or []` below
    # turned that into "business not found" — so EVERY owner-gated
    # sourcing endpoint 404'd. A star cannot name a column wrongly.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _reader(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    from business_collaborators_router import is_active_accountant
    if is_active_accountant(biz, str(user.id)):
        return row
    from business_users_router import require_role
    require_role(biz, str(user.id), "viewer")
    return row


def searches_today(business_id: str) -> int:
    since = (_now() - timedelta(hours=24)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/sourcing_searches?business_id=eq.{business_id}"
        f"&created_at=gte.{since}&select=id&limit={DAILY_SEARCH_CAP + 1}") or []
    return len(rows)


def _business_context(biz_row: Dict[str, Any], business_id: str) -> str:
    """A couple of lines about who is asking, so the search is for THEIR
    business rather than a generic one. Deliberately thin: the name and
    trade sharpen a supplier search; the customer list would not, and
    every extra field is another thing leaving the building."""
    bits: List[str] = []
    name = (biz_row.get("name") or "").strip()
    # `type` is the column that holds the trade on this schema. Values are
    # keys like "personal_services", so the underscores come out before it
    # reaches a prompt that will be read as a sentence.
    trade = (biz_row.get("type") or "").strip().replace("_", " ")
    if name:
        bits.append(name)
    if trade:
        bits.append(f"a {trade} business")
    try:
        offs = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=is.true"
            f"&select=name&limit=6") or []
        names = [str(o.get("name") or "").strip() for o in offs]
        names = [n for n in names if n]
        if names:
            bits.append("sells " + ", ".join(names[:6]))
    except Exception:
        pass
    return "; ".join(bits)


class SearchBody(BaseModel):
    need: str
    region: Optional[str] = None
    qty: Optional[int] = None
    budget_per_unit: Optional[float] = None


@router.get("/{business_id}/limits")
def limits(business_id: str,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(business_id, user)
    used = searches_today(business_id)
    return {"ok": True, "used_today": used, "cap": DAILY_SEARCH_CAP,
            "remaining": max(0, DAILY_SEARCH_CAP - used)}


@router.get("/{business_id}/searches")
def list_searches(business_id: str,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/sourcing_searches?business_id=eq.{business_id}"
        f"&order=created_at.desc&select=*&limit={_LIST_CAP}") or []
    return {"ok": True, "searches": rows}


@router.post("/{business_id}/search")
def run_search(business_id: str, body: SearchBody,
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner(business_id, user)

    need = (body.need or "").strip()
    if len(need) < 3:
        raise HTTPException(400, "say what you're trying to source")
    if len(need) > _NEED_MAX:
        raise HTTPException(400, "that's a long one — trim it to the essentials")
    if body.qty is not None and (body.qty < 0 or body.qty > 10_000_000):
        raise HTTPException(400, "that quantity doesn't look right")
    if body.budget_per_unit is not None and body.budget_per_unit < 0:
        raise HTTPException(400, "that budget doesn't look right")

    # The circuit breaker first — free to check, and a capped business
    # should never be metered for a search it will not receive.
    used = searches_today(business_id)
    if used >= DAILY_SEARCH_CAP:
        raise HTTPException(429, {
            "error": "daily_search_cap",
            "cap": DAILY_SEARCH_CAP,
            "message": (f"That's {DAILY_SEARCH_CAP} vendor searches today. "
                        f"The limit resets on a rolling 24 hours — the ones "
                        f"you've already run are saved below."),
        })

    # Then the meter. This is an AI action like any other.
    billing_limits.require_units(business_id)

    result = sourcing_engine.search_vendors(
        need=need,
        region=(body.region or "").strip() or None,
        qty=body.qty,
        budget_per_unit=body.budget_per_unit,
        business_context=_business_context(biz_row, business_id),
    )

    row = {
        "business_id": business_id,
        "need": need,
        "region": (body.region or "").strip() or None,
        "qty": body.qty,
        "budget_per_unit": body.budget_per_unit,
        "candidates": result["candidates"],
        "sources": result["sources"],
        "coverage_note": result["coverage_note"],
        "left_out": result.get("left_out") or [],
        "better_routes": result.get("better_routes") or [],
        "proposed_count": result["proposed_count"],
        "dropped_count": result["dropped_count"],
        "model": result["model"],
        "created_by": str(user.id),
    }
    saved = None
    try:
        created = sb_clients.sb_post_as_service("/sourcing_searches", row) or []
        saved = created[0] if isinstance(created, list) and created else created
    except Exception as e:
        # The search already ran and the practitioner already paid for it.
        # Failing the response because the receipt would not save would
        # charge them and show them nothing.
        logger.warning("[sourcing] could not record search: %s", e)

    return {"ok": True, "search": saved or row,
            "used_today": used + 1, "cap": DAILY_SEARCH_CAP}


# ─── Stage 2: the bridge ─────────────────────────────────────────────

def _supplier_or_404(business_id: str, supplier_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/suppliers?id=eq.{supplier_id}&business_id=eq.{business_id}"
        f"&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "vendor not found")
    return rows[0]


def _offering(business_id: str, offering_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not offering_id:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
        f"&select=id,name,sku&limit=1") or []
    return rows[0] if rows else None


def _sells(business_id: str) -> List[str]:
    """A few things the business actually sells, so the letter can say so.
    This is the line that turns "please send info" into a real request."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=is.true"
            f"&select=name&limit=5") or []
        return [str(r.get("name") or "").strip() for r in rows
                if str(r.get("name") or "").strip()]
    except Exception:
        return []


def rfqs_today(business_id: str) -> int:
    since = (_now() - timedelta(hours=24)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/vendor_rfqs?business_id=eq.{business_id}&status=neq.draft"
        f"&sent_at=gte.{since}&select=id&limit={DAILY_RFQ_CAP + 1}") or []
    return len(rows)


def _asked_recently(business_id: str, supplier_id: str) -> Optional[Dict[str, Any]]:
    since = (_now() - timedelta(days=RFQ_REPEAT_DAYS)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/vendor_rfqs?business_id=eq.{business_id}&supplier_id=eq.{supplier_id}"
        f"&status=neq.draft&sent_at=gte.{since}"
        f"&order=sent_at.desc&select=id,need,sent_at&limit=1") or []
    return rows[0] if rows else None


class RfqBody(BaseModel):
    supplier_ids: List[str]
    need: str
    qty: Optional[int] = None
    offering_id: Optional[str] = None
    force: bool = False


def _validated_rfq(body: RfqBody) -> Tuple[str, List[str]]:
    need = (body.need or "").strip()
    if len(need) < 3:
        raise HTTPException(400, "say what you're asking them to quote")
    if len(need) > _NEED_MAX:
        raise HTTPException(400, "that's a long one - trim it to the essentials")
    ids = [s for s in (body.supplier_ids or []) if s]
    if not ids:
        raise HTTPException(400, "pick at least one vendor")
    if len(ids) > RFQ_FAN_OUT_CAP:
        raise HTTPException(400, {
            "error": "fan_out_cap",
            "cap": RFQ_FAN_OUT_CAP,
            "message": (f"One request goes to at most {RFQ_FAN_OUT_CAP} vendors. "
                        f"Pick the {RFQ_FAN_OUT_CAP} worth asking - comparable "
                        f"quotes beat a wide net."),
        })
    if body.qty is not None and (body.qty < 0 or body.qty > 10_000_000):
        raise HTTPException(400, "that quantity doesn't look right")
    # De-duplicate while keeping order: the same vendor twice in one
    # request is a UI slip, and it must not become two emails.
    seen: set = set()
    unique = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)
    return need, unique


@router.post("/{business_id}/rfq/preview")
def preview_rfq(business_id: str, body: RfqBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Compose and send NOTHING. The same composer the send uses, so the
    preview is the email rather than an impression of it."""
    biz = _owner(business_id, user)
    need, ids = _validated_rfq(body)
    offering = _offering(business_id, body.offering_id)
    sells = _sells(business_id)

    out: List[Dict[str, Any]] = []
    for sid in ids:
        sup = _supplier_or_404(business_id, sid)
        letter = rfq_engine.compose_rfq(
            biz=biz, supplier=sup, need=need, qty=body.qty,
            offering=offering, sells=sells)
        to_email = (letter["to_email"] or "").strip()
        out.append({
            "supplier_id": sid,
            "supplier_name": sup.get("name"),
            "to_email": to_email,
            "subject": letter["subject"],
            "body": letter["body"],
            # Surfaced in the preview so the practitioner sees the problem
            # while they can still fix it, not as a send-time failure.
            "blocked": (None if to_email and "@" in to_email else "no_email"),
            "asked_recently": _asked_recently(business_id, sid),
        })
    return {"ok": True, "letters": out}


@router.post("/{business_id}/rfq/send")
async def send_rfq(business_id: str, body: RfqBody,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Send the composed request to each chosen vendor. One row each.

    Per-vendor failures do NOT abort the batch. If the third address
    bounces, the first two were still asked, and the practitioner needs to
    know exactly that — being told "the whole thing failed" is how a
    vendor ends up asked twice.
    """
    import os
    import email_sender

    biz = _owner(business_id, user)
    need, ids = _validated_rfq(body)

    sent_today = rfqs_today(business_id)
    if sent_today + len(ids) > DAILY_RFQ_CAP:
        raise HTTPException(429, {
            "error": "daily_rfq_cap",
            "cap": DAILY_RFQ_CAP,
            "message": (f"That would pass {DAILY_RFQ_CAP} vendor requests in 24 "
                        f"hours. The limit protects the sending address every "
                        f"practitioner here shares."),
        })

    billing_limits.require_units(business_id)

    offering = _offering(business_id, body.offering_id)
    sells = _sells(business_id)
    reply_to = email_sender.build_routed_reply_to(business_id, None)
    from_email = (os.environ.get("RESEND_FROM_EMAIL")
                  or email_sender.DEFAULT_FROM_EMAIL)

    results: List[Dict[str, Any]] = []
    for sid in ids:
        sup = _supplier_or_404(business_id, sid)
        name = sup.get("name") or "that vendor"
        letter = rfq_engine.compose_rfq(
            biz=biz, supplier=sup, need=need, qty=body.qty,
            offering=offering, sells=sells)

        to_email = (letter["to_email"] or "").strip()
        if not to_email or "@" not in to_email:
            results.append({"supplier_id": sid, "name": name, "sent": False,
                            "reason": "no email address on file"})
            continue

        recent = None if body.force else _asked_recently(business_id, sid)
        if recent:
            results.append({"supplier_id": sid, "name": name, "sent": False,
                            "reason": (f"already asked on "
                                       f"{str(recent.get('sent_at'))[:10]}"),
                            "needs_force": True})
            continue

        try:
            await email_sender.send_via_resend(
                to_email=to_email,
                to_name=letter["to_name"],
                from_email=from_email,
                from_name=(biz.get("name") or None),
                subject=letter["subject"],
                body=letter["body"],
                reply_to=reply_to,
                business_id=business_id,
            )
        except Exception as e:
            logger.warning("[sourcing] rfq to %s failed: %s", sid, e)
            results.append({"supplier_id": sid, "name": name, "sent": False,
                            "reason": "the send failed"})
            continue

        now_iso = _now().isoformat()
        try:
            sb_clients.sb_post_as_service("/vendor_rfqs", {
                "business_id": business_id,
                "supplier_id": sid,
                "offering_id": body.offering_id,
                "need": need,
                "qty": body.qty,
                "subject": letter["subject"],
                # What is stored is what was sent.
                "body": letter["body"],
                "to_email": to_email,
                "status": "sent",
                "sent_at": now_iso,
                "created_by": str(user.id),
            }, prefer=None)
        except Exception as e:
            # The email is already gone. A lost receipt must never read as
            # "not sent" — that is how a vendor gets asked twice.
            logger.warning("[sourcing] rfq record failed for %s: %s", sid, e)

        # candidate -> contacted. Never downgrade a vendor already active:
        # asking an existing supplier for a quote does not make them a
        # prospect again.
        if (sup.get("status") or "") == "candidate":
            try:
                sb_clients.sb_patch_as_service(
                    f"/suppliers?id=eq.{sid}",
                    {"status": "contacted", "updated_at": now_iso})
            except Exception as e:
                logger.warning("[sourcing] status bump failed for %s: %s", sid, e)

        results.append({"supplier_id": sid, "name": name, "sent": True,
                        "to_email": to_email})

    sent = [r for r in results if r.get("sent")]
    return {"ok": True, "results": results, "sent_count": len(sent),
            "sent_today": sent_today + len(sent), "cap": DAILY_RFQ_CAP}


@router.get("/{business_id}/rfqs")
def list_rfqs(business_id: str,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/vendor_rfqs?business_id=eq.{business_id}"
        f"&order=created_at.desc&select=*&limit={_LIST_CAP}") or []
    if rows:
        ids = ",".join({str(r["supplier_id"]) for r in rows})
        sups = sb_clients.sb_get_as_service(
            f"/suppliers?id=in.({ids})&select=id,name,email,status"
            f"&limit={_LIST_CAP}") or []
        by_id = {str(s["id"]): s for s in sups}
        for r in rows:
            r["supplier"] = by_id.get(str(r["supplier_id"]))
    return {"ok": True, "rfqs": rows}


# ─── Stage 4: the anonymous peer signal ──────────────────────────────
#
# The privacy rules live in the database function — opt-in, reciprocal,
# k-anonymous, and it names nobody. Putting them there rather than here
# means a future caller that forgets to check cannot leak a raw count.
#
# What lives HERE is the fourth rule: NO ENUMERATION. A business may only
# ask about vendors it already holds — its own saved vendors, or
# candidates its own paid searches turned up. Without that, this endpoint
# is a directory you can walk one domain at a time, which is the exact
# thing §0 of the spec refused to build.

PEER_MIN = 3
_PEER_DOMAIN_CAP = 60


def _domain_of(value: str) -> Optional[str]:
    """Mirror of the suppliers.domain generated column, in Python.

    Two implementations of one rule is a drift risk, so it is worth being
    precise about which way this one can fail: it is used ONLY to build
    the allow-list of domains a business may ask about, and to normalise
    what the caller sent. If it ever disagrees with the SQL, the result
    is a legitimate lookup being dropped — never an illegitimate one
    being answered. It fails closed.

    Agreement with the SQL is pinned by test_vendor_peers against the six
    shapes the column itself was verified on in production.
    """
    v = (value or "").strip().lower()
    if not v:
        return None
    v = re.sub(r"^\s*https?://", "", v)
    # An address contributes its domain half, matching split_part(email,'@',2).
    if "@" in v:
        v = v.split("@")[-1]
    v = re.sub(r"^www\.", "", v)
    v = re.split(r"[/?#]", v)[0]
    return v.strip() or None


def _askable_domains(business_id: str) -> set:
    """Every vendor domain this business is entitled to ask about: the
    ones it has saved, plus the ones its own sourcing searches found."""
    out: set = set()
    try:
        rows = sb_clients.sb_get_as_service(
            f"/suppliers?business_id=eq.{business_id}&domain=not.is.null"
            f"&select=domain&limit={_LIST_CAP}") or []
        for r in rows:
            d = _domain_of(str(r.get("domain") or ""))
            if d:
                out.add(d)
    except Exception as e:
        logger.warning(f"[sourcing] askable (saved) failed: {e}")
    try:
        searches = sb_clients.sb_get_as_service(
            f"/sourcing_searches?business_id=eq.{business_id}"
            f"&order=created_at.desc&select=candidates&limit=25") or []
        for s in searches:
            for c in (s.get("candidates") or []):
                if not isinstance(c, dict):
                    continue
                for key in ("website", "source_url"):
                    d = _domain_of(str(c.get(key) or ""))
                    if d:
                        out.add(d)
    except Exception as e:
        logger.warning(f"[sourcing] askable (searches) failed: {e}")
    return out


@router.get("/{business_id}/sharing")
def sharing_state(business_id: str,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/vendor_sharing_consent?business_id=eq.{business_id}"
        f"&select=*&limit=1") or []
    row = rows[0] if rows else None
    sharing = bool(row and not row.get("opted_out_at"))
    return {"ok": True, "sharing": sharing,
            "since": (row or {}).get("opted_in_at") if sharing else None,
            "min_peers": PEER_MIN}


class SharingBody(BaseModel):
    sharing: bool


@router.post("/{business_id}/sharing")
def set_sharing(business_id: str, body: SharingBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Turning it on and off is the owner's call and nobody else's.

    Withdrawal stamps opted_out_at rather than deleting the row: "they
    turned it off in September" is a fact worth being able to answer. It
    takes effect for everyone immediately, because every count joins on
    opted_out_at is null.
    """
    _owner(business_id, user)
    now = _now().isoformat()
    existing = sb_clients.sb_get_as_service(
        f"/vendor_sharing_consent?business_id=eq.{business_id}"
        f"&select=business_id&limit=1") or []
    if existing:
        sb_clients.sb_patch_as_service(
            f"/vendor_sharing_consent?business_id=eq.{business_id}",
            {"opted_out_at": None if body.sharing else now,
             "actor": str(user.id), "updated_at": now,
             **({"opted_in_at": now} if body.sharing else {})})
    elif body.sharing:
        sb_clients.sb_post_as_service("/vendor_sharing_consent", {
            "business_id": business_id, "opted_in_at": now,
            "actor": str(user.id), "updated_at": now}, prefer=None)
    # Opting out when there was never a row is a no-op, not a row that
    # records a consent nobody ever gave.
    return {"ok": True, "sharing": bool(body.sharing)}


class PeersBody(BaseModel):
    domains: List[str]


@router.post("/{business_id}/peers")
def peer_counts(business_id: str, body: PeersBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """How many other businesses here work with these vendors.

    Domains the business is not entitled to ask about are dropped
    silently rather than refused: an error naming a domain would itself
    confirm that domain is interesting, and the caller has no legitimate
    need to learn which of its own list was filtered.
    """
    _reader(business_id, user)

    # Keyed by what the CALLER sent, not by the normalised domain.
    # Otherwise every caller has to reimplement the domain rule to match
    # a result back to the vendor it belongs to, and a third copy of one
    # rule is a third thing to drift. Several inputs may normalise to the
    # same domain; each keeps its own key and they share the answer.
    by_domain: Dict[str, List[str]] = {}
    for raw in (body.domains or [])[:_PEER_DOMAIN_CAP]:
        key = str(raw or "")
        d = _domain_of(key)
        if d:
            by_domain.setdefault(d, []).append(key)
    wanted: List[str] = list(by_domain.keys())

    sharing = _is_sharing(business_id)
    if not wanted or not sharing:
        # Not contributing means no answer, and saying so plainly is what
        # lets the surface explain the trade rather than look broken.
        return {"ok": True, "peers": {}, "sharing": sharing,
                "min_peers": PEER_MIN}

    allowed = _askable_domains(business_id)
    wanted = [d for d in wanted if d in allowed]

    peers: Dict[str, Any] = {}
    for d in wanted:
        try:
            got = sb_clients.sb_post_as_service("/rpc/vendor_peer_counts", {
                "p_business_id": business_id, "p_domain": d, "p_min": PEER_MIN,
            })
        except Exception as e:
            logger.warning(f"[sourcing] peer count failed for {d}: {e}")
            continue
        row = got[0] if isinstance(got, list) and got else got
        if not isinstance(row, dict):
            continue
        # Only k-cleared numbers ever reach the wire. The function returns
        # null below the threshold and nothing here invents a zero to fill
        # the gap — "not enough to say" and "nobody" must not look alike.
        if row.get("peers_any") is not None:
            answer = {"any": row["peers_any"],
                      "trade": row.get("peers_trade"),
                      "trade_name": row.get("trade")}
            for key in by_domain.get(d, []):
                peers[key] = answer
    return {"ok": True, "peers": peers, "sharing": True, "min_peers": PEER_MIN}


def _is_sharing(business_id: str) -> bool:
    rows = sb_clients.sb_get_as_service(
        f"/vendor_sharing_consent?business_id=eq.{business_id}"
        f"&opted_out_at=is.null&select=business_id&limit=1") or []
    return bool(rows)
