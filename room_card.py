"""room_card.py — the room, drawn: what it is for, what is in it right now,
the one next thing. The data behind the card the app shows when someone
taps "What is this room?".

Kevin, 2 September (Wave C): "maybe an artifact shows up with a design
showing what is in this room instead of the chat appearing." So the door
no longer opens a conversation. It opens a card, built here without a
model call so it appears instantly, from three things the server already
knows:

  purpose / next rule   room_orientation.py (the same map Chief reads)
  what is in it now     a few live counts per room — the practitioner's
                        own numbers, never a description of what could be
  the one next thing    the plug-in list (business_track_router probes):
                        the first undone move that lives in THIS room,
                        else the first undone move anywhere

Plus the floor plan: the four rooms, and this room's doors (its leaves),
so the card also says where they are standing.

NOTHING HERE RAISES. A count that cannot be read is left off the card; a
plug-in list that cannot be resolved leaves the next-thing slot to the
room's next rule. The card must open on day one with an empty business
and on day ninety with a full one.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import sb_clients
import room_orientation as ro

logger = logging.getLogger("room_card")

# How many rows a count reads before it says "N+" instead of an exact
# number. The card is a glance, not a ledger.
COUNT_CAP = 500


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    try:
        r = sb_clients.sb_get_as_service(path)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[room_card] read failed %s: %s", path.split("?")[0], e)
        return None
    return r if isinstance(r, list) else None


def _count(path: str) -> Optional[int]:
    rows = _rows(f"{path}&select=id&limit={COUNT_CAP}")
    return None if rows is None else len(rows)


def _fmt(n: Optional[int]) -> Optional[str]:
    if n is None:
        return None
    return f"{COUNT_CAP}+" if n >= COUNT_CAP else str(n)


def _tile(label: str, n: Optional[int], hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    v = _fmt(n)
    if v is None:
        return None
    t: Dict[str, Any] = {"label": label, "value": v}
    if hint:
        t["hint"] = hint
    return t


# ── what is in it right now, per room ───────────────────────────────────
# Each entry returns tiles for the room it knows about. Labels are generic
# nouns; the frontend swaps in the business's own words where it has them.

def _now_contacts(biz):
    bid = biz["id"]
    total = _count(f"/contacts?business_id=eq.{bid}")
    leads = _count(f"/contacts?business_id=eq.{bid}&status=eq.lead")
    return [_tile("people", total, "everyone you serve or might"),
            _tile("leads", leads, "not yet clients")]


def _now_offerings(biz):
    bid = biz["id"]
    return [_tile("things you sell", _count(f"/offerings?business_id=eq.{bid}&is_active=eq.true"),
                  "with a price on them")]


def _now_invoices(biz):
    bid = biz["id"]
    return [_tile("open invoices", _count(f"/invoices?business_id=eq.{bid}&status=in.(sent,overdue,open,unpaid)"),
                  "waiting to be paid"),
            _tile("paid", _count(f"/invoices?business_id=eq.{bid}&status=eq.paid"), "all time")]


def _now_sessions(biz):
    bid = biz["id"]
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [_tile("coming up", _count(f"/sessions?business_id=eq.{bid}&scheduled_at=gte.{now}"), "booked ahead")]


def _now_queue(biz):
    bid = biz["id"]
    return [_tile("waiting for your yes", _count(f"/agent_queue?business_id=eq.{bid}&status=eq.pending"),
                  "drafted, nothing sends without you")]


def _now_documents(biz):
    bid = biz["id"]
    return [_tile("documents", _count(f"/documents?business_id=eq.{bid}"), "agreements and templates")]


def _now_modules(biz):
    bid = biz["id"]
    return [_tile("custom solutions", _count(f"/custom_modules?business_id=eq.{bid}&is_active=eq.true"),
                  "tools built for your trade")]


def _now_site(biz):
    bid = biz["id"]
    pub = _rows(f"/business_sites?business_id=eq.{bid}&status=eq.published&select=id&limit=1")
    if pub is None:
        return []
    return [{"label": "your site", "value": "live" if pub else "not up yet",
             "hint": "the front door" if pub else "sells what you told Chief you sell"}]


def _now_booking(biz):
    settings = biz.get("settings") or {}
    try:
        from availability_router import _is_open_default_dict
        configured = not _is_open_default_dict(settings.get("availability"))
    except Exception:
        return []
    return [{"label": "your hours", "value": "set" if configured else "not set",
             "hint": "what the booking page offers" if configured else "booking offers nothing until they are"}]


def _now_integrations(biz):
    bid = biz["id"]
    out = []
    try:
        import business_track_router as btr
        pay = btr._done_payments(biz)
        out.append({"label": "getting paid", "value": "connected" if pay else "not yet",
                    "hint": "invoices become money that arrives"})
    except Exception:
        pass
    bank = _rows(f"/plaid_items?business_id=eq.{bid}&status=not.eq.revoked&select=item_id&limit=1")
    if bank is not None:
        out.append({"label": "bank", "value": "linked" if bank else "not linked",
                    "hint": "the books keep themselves"})
    return out


def _now_goals(biz):
    bid = biz["id"]
    return [_tile("goals", _count(f"/goals?business_id=eq.{bid}&status=eq.active"), "with a number on them")]


def _now_notes(biz):
    bid = biz["id"]
    return [_tile("notes", _count(f"/chief_memories?business_id=eq.{bid}"), "what Chief remembers for you")]


def _now_autopilot(biz):
    bid = biz["id"]
    return [_tile("scheduled jobs", _count(f"/chief_scheduled_actions?business_id=eq.{bid}&status=eq.queued"),
                  "Chief's recurring work")]


NOW: Dict[str, Any] = {
    "operate/contacts": _now_contacts,
    "operate/offerings-manager": _now_offerings,
    "operate/invoices": _now_invoices,
    "operate/payments": _now_integrations,
    "operate/sessions": _now_sessions,
    "operate/calendar": _now_sessions,
    "operate/queue": _now_queue,
    "operate/documents": _now_documents,
    "operate/agents": _now_autopilot,
    "grow/goals": _now_goals,
    "grow/notes": _now_notes,
    "build/my-site": _now_site,
    "build/booking": _now_booking,
    "build/booking-share": _now_booking,
    "build/custom-modules": _now_modules,
    "build/integrations": _now_integrations,
    # tab-level cards: the room's headline numbers
    "operate": lambda biz: _now_contacts(biz)[:1] + _now_queue(biz) + _now_invoices(biz)[:1],
    "grow": lambda biz: _now_goals(biz) + _now_contacts(biz)[1:],
    "build": lambda biz: _now_site(biz) + _now_booking(biz) + _now_modules(biz),
    "home": lambda biz: _now_contacts(biz)[:1] + _now_sessions(biz) + _now_queue(biz),
}


def now_tiles(biz: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    fn = NOW.get(key) or NOW.get(key.split("/")[0])
    if not fn:
        return []
    try:
        return [t for t in fn(biz) if t]
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[room_card] now tiles failed for %s: %s", key, e)
        return []


# ── the one next thing ──────────────────────────────────────────────────

def _nav_key(nav: Dict[str, Any]) -> str:
    return ro.room_key(nav.get("tab"), nav.get("sub"), nav.get("page"))


def next_move(biz: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """The first undone, unblocked plug-in whose door is THIS room; else
    the first undone unblocked anywhere; None when all done or unknown."""
    try:
        import business_track_router as btr
        items = btr.resolve_plugins(biz) or []
    except Exception as e:
        logger.warning("[room_card] plugins failed: %s", e)
        return None
    undone = [p for p in items if not p.get("done") and not (p.get("blocked_by") or [])]
    here = [p for p in undone if _nav_key(p.get("nav") or {}) == key
            or (("/" not in key) and _nav_key(p.get("nav") or {}).startswith(key + "/"))]
    pick = (here or undone or [None])[0]
    if not pick:
        return None
    try:
        import business_track_actions as bta
        how = (bta.PLUGIN_CATALOG.get(pick.get("key") or "") or {}).get("chief", "")
    except Exception:
        how = ""
    return {"key": pick.get("key"), "title": pick.get("title"), "why": pick.get("why"),
            "nav": pick.get("nav"), "in_this_room": bool(here),
            "chief_can_do_it_here": how.startswith("DO IT HERE")}


# ── the floor plan ──────────────────────────────────────────────────────

def doors(tab: str) -> List[Dict[str, str]]:
    """This room's leaves, in map order, for the card's floor plan."""
    out = []
    for k, d in ro.ROOMS.items():
        if k.startswith(tab + "/"):
            out.append({"key": k, "leaf": k.split("/", 1)[1], "label": d["label"]})
    return out


def build_room_card(biz: Dict[str, Any], tab: Optional[str], sub: Optional[str] = None,
                    page: Optional[str] = None) -> Dict[str, Any]:
    d = ro.describe(tab, sub, page)
    key = d["key"]
    t = key.split("/")[0]
    tab_meta = ro.TABS.get(t) or {"label": t.title() or "Here", "purpose": "", "next_rule": ""}
    return {
        "ok": True,
        "key": key,
        "tab": t,
        "tab_label": tab_meta["label"],
        "label": d["label"],
        "known": d["known"],
        "purpose": d["purpose"],
        "next_rule": d["next_rule"],
        "now": now_tiles(biz, key),
        "next_move": next_move(biz, key),
        "rooms": [{"tab": k, "label": v["label"]} for k, v in ro.TABS.items()],
        "doors": doors(t),
    }
