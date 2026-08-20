"""
inventory_count.py — SCAN THE SHELF, rung two: THE COUNT SESSION
(2026-08-20).

THE GAP THIS CLOSES
  Rung one made it cheap to say WHICH product you are holding. This one
  is where inventory accuracy is actually won or lost.

  Every business with stock has the same recurring wound: the system
  says 12, the shelf says 9, and nobody knows when the three left or
  whether they were sold, broken, or walked out the door. Correcting
  that today is thirty separate form fills — so it doesn't happen, so
  the number rots, and every downstream promise ("Only 2 left!", the
  reorder point, the shrink you never see) rots with it.

  A count session is: start it, walk the shelf, say what you actually
  see, finish. One submit, one batch, one honest report.

WHY ONE ENDPOINT AND NO NEW TABLES
  A session in progress is a draft, and a draft belongs to the device
  holding it — the frontend keeps it in localStorage so a phone locking
  mid-count loses nothing. The server only ever sees a FINISHED count.
  That keeps the whole feature one endpoint, one event type, and zero
  migrations, and it means there is no such thing as an abandoned
  half-session rotting in a table nobody queries.

WHAT LANDS ON THE SPINE
  • one `stock_adjusted` row per line that actually MOVED, reason
    "count <date>" — so the movement history says *counted*, not
    "someone typed a number", and rung one's history view needs no
    changes to show it.
  • exactly one `stock_counted` row for the session, carrying every
    line including the ones that matched. That row is the audit trail
    ("we counted it and it was right") and it is what makes the repeat-
    variance read below possible without a table.

  A line that matches writes NO adjustment. Counting 200 products and
  finding 3 wrong should leave 3 movements, not 200.

THE FACT THIS UNLOCKS
  Shrink becomes visible, and a product that is off in count after
  count is a pattern rather than an anecdote. `repeat_misses` reads the
  last few `stock_counted` rows and says which items were also wrong
  last time — the thing a practitioner can act on.

Endpoint (manager+, the same ladder as every other stock write):
  POST /store/inventory/{business_id}/count
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("inventory_count")

router = APIRouter(tags=["store"])

# A stocktake is a walk down a shelf, not a data import. The cap is
# generous for a real small business and low enough that a runaway
# client cannot ask us to write ten thousand rows.
_MAX_LINES = 500

# How many past sessions a repeat-variance claim looks back over.
# Three is enough to separate "one bad day" from "this keeps happening"
# and short enough that the claim still means something recent.
_LOOKBACK_SESSIONS = 3

_SELLABLE = {"product", "course", "package"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CountLine(BaseModel):
    offering_id: str
    counted_qty: int = Field(..., ge=0)


class CountBody(BaseModel):
    lines: List[CountLine]
    note: Optional[str] = Field(default=None, max_length=200)


# ─── Pure helpers (unit-tested; no network) ──────────────────────────


def build_report(offerings: Dict[str, Dict[str, Any]],
                 lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Expected vs counted, per line and in total. Pure.

    `value_short` deliberately values ONLY the units that went missing,
    at what they sell for. Netting found stock against missing stock
    would let a mis-scan on one product hide real shrink on another,
    which is the exact number a practitioner is counting to find.
    """
    items: List[Dict[str, Any]] = []
    units_short = 0
    units_over = 0
    value_short = 0.0
    for ln in lines:
        oid = str(ln.get("offering_id"))
        off = offerings.get(oid)
        if not off:
            continue
        counted = int(ln.get("counted_qty") or 0)
        raw = off.get("inventory_qty")
        expected = int(raw) if raw is not None else None
        # An untracked product being counted for the first time has no
        # expectation to miss — it starts tracking at what's on the
        # shelf, and calling that a variance would invent shrink.
        delta = (counted - expected) if expected is not None else None
        try:
            price = float(off.get("current_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if delta is not None and delta < 0:
            units_short += -delta
            value_short += (-delta) * price
        elif delta is not None and delta > 0:
            units_over += delta
        items.append({
            "offering_id": oid,
            "name": off.get("name") or "",
            "expected": expected,
            "counted": counted,
            "delta": delta,
            "was_tracked": expected is not None,
        })
    off_items = [i for i in items if (i["delta"] or 0) != 0]
    return {
        "counted": len(items),
        "matched": len(items) - len(off_items),
        "off": len(off_items),
        "units_short": units_short,
        "units_over": units_over,
        "value_short": round(value_short, 2),
        "items": items,
    }


def repeat_misses(report_items: List[Dict[str, Any]],
                  past_sessions: List[Dict[str, Any]]) -> Dict[str, int]:
    """{offering_id: how many of the recent sessions ALSO had it wrong}.

    Only for items wrong in THIS session — a product that used to drift
    and has been right ever since is good news, not a finding.
    """
    wrong_now = {str(i["offering_id"]) for i in report_items
                 if (i.get("delta") or 0) != 0}
    if not wrong_now:
        return {}
    counts: Dict[str, int] = {}
    for sess in past_sessions[:_LOOKBACK_SESSIONS]:
        seen: set = set()
        for it in (sess.get("items") or []):
            oid = str(it.get("offering_id"))
            if oid in wrong_now and (it.get("delta") or 0) != 0 and oid not in seen:
                seen.add(oid)
                counts[oid] = counts.get(oid, 0) + 1
    return counts


def summary_line(report: Dict[str, Any], currency_symbol: str = "$") -> str:
    """The one sentence the drawer leads with. Plain, and never cheerful
    about a number that isn't good."""
    if report["counted"] == 0:
        return "Nothing was counted."
    if report["off"] == 0:
        return (f"All {report['counted']} counted and every one matched. "
                "Your stock numbers are true.")
    bits = [f"{report['off']} of {report['counted']} were off"]
    if report["units_short"]:
        bits.append(f"{report['units_short']} unit"
                    f"{'' if report['units_short'] == 1 else 's'} missing"
                    + (f" (about {currency_symbol}{report['value_short']:,.0f})"
                       if report["value_short"] >= 1 else ""))
    if report["units_over"]:
        bits.append(f"{report['units_over']} more on the shelf than expected")
    return " — ".join(bits) + "."


# ─── The endpoint ────────────────────────────────────────────────────


def _past_sessions(business_id: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/events?business_id=eq.{business_id}&event_type=eq.stock_counted"
        "&select=data,created_at&order=created_at.desc"
        f"&limit={_LOOKBACK_SESSIONS}") or []
    return [(r.get("data") or {}) for r in rows]


@router.post("/store/inventory/{business_id}/count")
def finish_count(business_id: str, body: CountBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Close a stocktake: set every counted product to what was actually
    on the shelf, and answer with the variance.

    Manager+, the same ladder as a single adjustment — a count is a pile
    of adjustments and must not be a cheaper way to make one.
    """
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")

    if not body.lines:
        raise HTTPException(400, "a count needs at least one product")
    if len(body.lines) > _MAX_LINES:
        raise HTTPException(413, f"a count session tops out at {_MAX_LINES} products")

    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&select=id,name,category,current_price,inventory_qty&limit=500") or []
    offerings = {str(o["id"]): o for o in rows
                 if (o.get("category") or "") in _SELLABLE}

    # Deduplicate on the way in: a scanner session can land the same
    # product twice, and the LAST count is the one the human meant.
    seen: Dict[str, Dict[str, Any]] = {}
    for ln in body.lines:
        oid = str(ln.offering_id)
        if oid not in offerings:
            raise HTTPException(
                404, "one of those products isn't in this business's stock")
        seen[oid] = {"offering_id": oid, "counted_qty": int(ln.counted_qty)}
    lines = list(seen.values())

    report = build_report(offerings, lines)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reason = f"count {stamp}"
    if body.note:
        reason = f"{reason} — {body.note.strip()[:120]}"
    actor = (getattr(user, "email", None) or str(user.id))

    from store_router import _emit_stock_event

    moved = 0
    for item in report["items"]:
        # A line that matched writes nothing. Counting 200 products and
        # finding 3 wrong must leave 3 movements, not 200.
        if item["was_tracked"] and item["delta"] == 0:
            continue
        oid = item["offering_id"]
        new_qty = int(item["counted"])
        sb_clients.sb_patch_as_service(
            f"/offerings?id=eq.{oid}&business_id=eq.{business_id}",
            {"inventory_qty": new_qty})
        moved += 1
        _emit_stock_event(business_id, oid, item["name"],
                          delta=item["delta"], new_qty=new_qty,
                          reason=reason, actor=actor)
        # A count that finds MORE than expected is a restock nobody
        # recorded — it closes an outstanding purchase order the same
        # way a manual receive does.
        try:
            from reorder_engine import clear_reorder_pending_if_restocked
            clear_reorder_pending_if_restocked(business_id, oid, new_qty)
        except Exception as e:
            logger.warning(f"[count] reorder pending-clear failed (non-fatal): {e}")

    repeats = repeat_misses(report["items"], _past_sessions(business_id))

    # ONE session row, carrying every line including the matches. This
    # is the audit trail and the only reason repeat_misses can work
    # without a table.
    try:
        import event_spine
        event_spine.emit("stock_counted", business_id, {
            "counted": report["counted"],
            "off": report["off"],
            "units_short": report["units_short"],
            "units_over": report["units_over"],
            "value_short": report["value_short"],
            "note": (body.note or "")[:200],
            "actor": actor[:120],
            "finished_at": _now_iso(),
            "items": report["items"],
        }, source="store")
    except Exception as e:
        logger.warning(f"[count] session event emit failed (non-fatal): {e}")

    logger.info(f"[count] biz={business_id[:8]} counted={report['counted']} "
                f"off={report['off']} moved={moved} short={report['units_short']}")

    return {"ok": True, "report": report, "adjusted": moved,
            "repeat_misses": repeats, "summary": summary_line(report),
            "reason": reason}
