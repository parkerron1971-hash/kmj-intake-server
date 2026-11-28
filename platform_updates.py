"""
platform_updates.py: What's New, from the database.

Kevin, 2026-11-27 ("yes to all" on solutionist-studio docs/whats-new-rework-plan.md):
the update list moves out of the frontend's whatsNew.ts into platform_updates.
People get a weekly "New for you" card on Home and an Updates list behind the
bell, each ranked for the login and in a church's words at a church; what a
login has seen is kept here, so it follows them across devices; Kevin
publishes from one Mission Control queue.

    supabase/APPLY-2026-11-27-whats-new.sql
        platform_updates        one row an update (draft | published | archived)
        platform_update_seen    (user, business, update) a login has seen, and how
        platform_news_drafts    news posts drafted from updates

WHO AN UPDATE IS FOR (for_viewer), the old ledger's rules plus two:
    kinds   canonical verticals ('ministry'…): only those businesses
    areas   church office areas: an office login only when one is theirs
            (the owner, admins and every other business: everyone)
    roles   logins ('owner', 'admin'…): only those roles. NEW: an accountant
            seat no longer reads about the owner's plan and bill
    date    never anything dated on or before the day this login joined

HOW THEY RANK (rank), best first: made for this kind of business, for this
login's area or role, on a page this login opened lately, big over small,
then newest. A group_key folds one feature shipped over several PRs into its
newest row. The card is the top three unseen from the last NEW_DAYS days.

ROUTES
  Practitioners (any role on the business, through business_access):
    GET  /updates/for-me?business_id=&pages=a:b,c:d&before=&limit=
           {church, card[], updates[], unseen, more}. `pages` is the pages
           this person opened lately (the app keeps them), only for ranking.
    POST /updates/seen?business_id=   {ids[], how} or {all: true, how}
  The platform owner (lead_admin.require_owner):
    GET    /platform/updates?status=&q=&limit=      the queue, with warnings
    POST   /platform/updates                        a new draft
    PATCH  /platform/updates/{id}                   words, audience, status
    GET    /platform/news-drafts?status=
    POST   /platform/news-drafts
    PATCH  /platform/news-drafts/{id}

Chief reads the same list (for_viewer + rank), so the card, the bell, the Help
Center and "what's new?" all say the same thing.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import sb_clients
from auth_supabase import AuthedUser, UserSession
from business_access import business_access
from lead_admin import require_owner

logger = logging.getLogger(__name__)
router = APIRouter(tags=["updates"])

STATUSES = ("draft", "published", "archived")
SOURCES = ("ledger", "pr", "sweep", "editor")
WEIGHTS = ("big", "normal", "small")
SEEN_HOW = ("card", "list", "show_me", "tour", "listen", "dismissed", "all")
NEWS_STATUSES = ("draft", "approved", "dropped")
AUDIENCES = ("all", "business", "church")
ROLES = ("owner", "admin", "manager", "member", "viewer")

NEW_DAYS = 30          # what counts as new: a dot, and a place on the card
CARD_SIZE = 3
PAGE_DEFAULT, PAGE_MAX = 40, 100
SEEN_MAX = 500
PAGES_MAX = 30
CACHE_SECONDS = 60

ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]{1,70}$")
PAGE_RE = re.compile(r"^[a-z0-9_-]{1,30}:[a-z0-9_-]{1,60}$")
KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")

LIMITS = {"title": 200, "line": 300, "body": 6000, "church_title": 200, "church_line": 300,
          "church_body": 6000, "area": 40, "group_key": 80, "notes": 2000}

COLUMNS = ("id,date,status,source,area,page,kinds,areas,roles,weight,group_key,title,line,body,"
           "church_title,church_line,church_body,tour,source_repo,source_pr,notes,created_at,"
           "updated_at,published_at")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().date().isoformat()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _list(v: Any) -> List[str]:
    return [str(x) for x in v if isinstance(x, str) and x] if isinstance(v, list) else []


# ─── Who an update is for ───────────────────────────────────────────────

class Viewer:
    """One login in one business, as the rules see it."""

    def __init__(self, *, kind: str, church: bool, role: Optional[str],
                 areas: Optional[Sequence[str]], joined: str = "",
                 pages: Iterable[str] = (), seen: Iterable[str] = ()):
        self.kind = kind or ""
        self.church = bool(church)
        self.role = role or ""
        self.areas: Optional[Set[str]] = set(areas) if areas is not None else None
        self.joined = joined or ""
        self.pages: Set[str] = {p for p in pages if isinstance(p, str)}
        self.rooms: Set[str] = {p.split(":", 1)[0] for p in self.pages}
        self.seen: Set[str] = set(seen)


def shown_to(entry: Dict[str, Any], v: Viewer) -> bool:
    """Whether this login may see this update at all."""
    kinds = _list(entry.get("kinds"))
    if kinds and v.kind not in kinds:
        return False
    roles = _list(entry.get("roles"))
    if roles and v.role not in roles:
        return False
    areas = _list(entry.get("areas"))
    if areas and v.areas is not None and not (set(areas) & v.areas):
        return False
    if v.joined and str(entry.get("date") or "") <= v.joined:
        return False
    return True


def _why(entry: Dict[str, Any], v: Viewer) -> str:
    """The quiet line under the card: why this one was picked."""
    page = entry.get("page") or ""
    if _list(entry.get("roles")):
        return "For the account owner" if _list(entry.get("roles")) == ["owner"] else "For your role"
    if _list(entry.get("areas")) and v.areas is not None:
        return "For your area"
    if page and page in v.pages:
        return "On a page you use"
    if page and page.split(":", 1)[0] in v.rooms:
        return "Where you work lately"
    if _list(entry.get("kinds")):
        return "Made for churches" if v.church else "Made for businesses like yours"
    return "New for everyone"


def score(entry: Dict[str, Any], v: Viewer, today: str) -> float:
    """Higher ranks first. Ties go to the newer, then the id."""
    s = 0.0
    if _list(entry.get("kinds")):
        s += 3
    if _list(entry.get("areas")) and v.areas is not None:
        s += 3
    if _list(entry.get("roles")):
        s += 2
    page = entry.get("page") or ""
    if page and page in v.pages:
        s += 2.5
    elif page and page.split(":", 1)[0] in v.rooms:
        s += 1
    w = entry.get("weight")
    s += 2 if w == "big" else (-2 if w == "small" else 0)
    try:
        age = (date.fromisoformat(today) - date.fromisoformat(str(entry.get("date"))[:10])).days
    except ValueError:
        age = 365
    return s - max(0, age) / 7.0


def words_for(entry: Dict[str, Any], church: bool) -> Dict[str, str]:
    """The title, line and body this viewer reads: a church's own words at a
    church when the update has them."""
    def pick(k: str) -> str:
        own = entry.get(f"church_{k}") if church else None
        return str(own if isinstance(own, str) and own.strip() else (entry.get(k) or ""))
    return {"title": pick("title"), "line": pick("line"), "body": pick("body")}


def _tour_for(entry: Dict[str, Any], church: bool) -> List[Dict[str, str]]:
    out = []
    for step in entry.get("tour") or []:
        if not isinstance(step, dict):
            continue
        text = step.get("church_text") if church and step.get("church_text") else step.get("text")
        if isinstance(text, str) and text.strip():
            row = {"text": text.strip()}
            if isinstance(step.get("anchor"), str) and step["anchor"].strip():
                row["anchor"] = step["anchor"].strip()
            out.append(row)
    return out


def shape(entry: Dict[str, Any], v: Viewer, today: str) -> Dict[str, Any]:
    """One update as the app gets it."""
    w = words_for(entry, v.church)
    since = (date.fromisoformat(today) - timedelta(days=NEW_DAYS)).isoformat()
    return {
        "id": entry["id"], "date": str(entry.get("date"))[:10], "area": entry.get("area") or "Everywhere",
        "page": entry.get("page") or None, "weight": entry.get("weight") or "normal",
        **w, "tour": _tour_for(entry, v.church),
        "seen": entry["id"] in v.seen,
        "new": entry["id"] not in v.seen and str(entry.get("date"))[:10] >= since,
        "why": _why(entry, v),
    }


def for_viewer(entries: Sequence[Dict[str, Any]], v: Viewer) -> List[Dict[str, Any]]:
    """Published updates this login may see, newest first, one per group."""
    out: List[Dict[str, Any]] = []
    groups: Set[str] = set()
    rows = sorted((e for e in entries if e.get("status") == "published"),
                  key=lambda e: (str(e.get("date")), str(e.get("id"))), reverse=True)
    for e in rows:
        if not shown_to(e, v):
            continue
        g = e.get("group_key")
        if g:
            if g in groups:
                continue
            groups.add(g)
        out.append(e)
    return out


def rank(entries: Sequence[Dict[str, Any]], v: Viewer, today: str) -> List[Dict[str, Any]]:
    """for_viewer's list, best first (Chief and the card)."""
    return sorted(for_viewer(entries, v),
                  key=lambda e: (score(e, v, today), str(e.get("date")), str(e.get("id"))), reverse=True)


def card(entries: Sequence[Dict[str, Any]], v: Viewer, today: str) -> List[Dict[str, Any]]:
    """The weekly card: the best three this login hasn't seen, from the last
    NEW_DAYS days."""
    since = (date.fromisoformat(today) - timedelta(days=NEW_DAYS)).isoformat()
    fresh = [e for e in rank(entries, v, today) if e["id"] not in v.seen and str(e.get("date"))[:10] >= since]
    return fresh[:CARD_SIZE]


# ─── Reading ────────────────────────────────────────────────────────────

_CACHE: Dict[str, Any] = {"at": 0.0, "rows": None}


def published() -> List[Dict[str, Any]]:
    """Every published update, kept a minute per replica. A failed read is
    an empty list for the app (no card, never a broken one) but is never
    cached."""
    now = time.monotonic()
    if _CACHE["rows"] is not None and now - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["rows"]
    try:
        rows = sb_clients.sb_get_all_as_service(
            f"/platform_updates?status=eq.published&select={COLUMNS}", strict=True)
    except sb_clients.PartialRead as e:
        logger.warning(f"[updates] published list not read: {e}")
        return []
    _CACHE.update(at=now, rows=rows or [])
    return _CACHE["rows"]


def forget_cache() -> None:
    _CACHE.update(at=0.0, rows=None)


def seen_ids(user_id: str, business_id: str) -> Optional[Set[str]]:
    """What this login has seen here. None when it couldn't be read: the
    caller then shows nothing as new rather than everything."""
    try:
        rows = sb_clients.sb_get_all_as_service(
            f"/platform_update_seen?user_id=eq.{_q(user_id)}&business_id=eq.{_q(business_id)}&select=update_id",
            key="update_id", strict=True)
    except sb_clients.PartialRead:
        return None
    return {str(r.get("update_id")) for r in rows or []}


def joined_day(business: Dict[str, Any], user_id: str, role: Optional[str]) -> str:
    """The day this login joined this business: the business's own day for
    the owner, the seat's for everyone else. When the seat can't be read, or
    has no day, it is today: nothing older shows, rather than everything."""
    if role == "owner":
        return str(business.get("created_at") or "")[:10] or _today()
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(business.get('id'))}&user_id=eq.{_q(user_id)}"
        f"&status=eq.active&select=*&limit=1")
    if isinstance(rows, list) and rows:
        r = rows[0]
        day = str(r.get("accepted_at") or r.get("created_at") or r.get("invited_at") or "")[:10]
        if day:
            return day
    return _today()


def viewer_for(business: Dict[str, Any], user_id: str, *, pages: Iterable[str] = (),
               seen: Optional[Iterable[str]] = None) -> Viewer:
    """The Viewer for a login in a business (the route and Chief)."""
    import vertical_registry
    role = business.get("_caller_role")
    if role is None:
        from business_users_router import role_of
        role = role_of(str(business.get("id")), str(user_id))
    kind = vertical_registry.resolve(business.get("type") or "")
    areas = None
    if role and role != "owner" and kind == "ministry":
        try:
            import church_areas
            view = church_areas.my_areas(str(business.get("id")), str(user_id), role)
            if view is None:
                # None is "the switch is off" (the whole church, as before) or
                # "the read failed". With the switch on it can only be the
                # second, and that narrows to nothing rather than widening.
                if church_areas.mode() == "on":
                    areas = []
            elif isinstance(view.get("areas"), list):
                areas = view["areas"]
        except Exception as e:  # noqa: BLE001: the areas narrow; failing to read them never widens
            logger.warning(f"[updates] areas not read: {type(e).__name__}")
            areas = []
    return Viewer(kind=kind, church=kind == "ministry", role=role, areas=areas,
                  joined=joined_day(business, user_id, role), pages=pages, seen=seen or ())


def clean_pages(raw: Optional[str]) -> List[str]:
    out: List[str] = []
    for p in (raw or "").split(","):
        p = p.strip().lower()
        if PAGE_RE.match(p) and p not in out:
            out.append(p)
        if len(out) >= PAGES_MAX:
            break
    return out


@router.get("/updates/for-me")
def for_me(business: Dict[str, Any] = Depends(business_access("viewer")),
           session: UserSession = Depends(sb_clients.authed_request),
           pages: Optional[str] = Query(default=None, max_length=2000),
           before: Optional[str] = Query(default=None, max_length=90),
           limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX)) -> Dict[str, Any]:
    """The card and the Updates list for this login in this business."""
    user_id = str(session.user.id)
    seen = seen_ids(user_id, str(business["id"]))
    v = viewer_for(business, user_id, pages=clean_pages(pages), seen=seen or ())
    today = _today()
    rows = published()
    visible = for_viewer(rows, v)
    # Seen couldn't be read: nothing is new and there is no card, rather
    # than every update shouting at once.
    if seen is None:
        v.seen = {e["id"] for e in visible}
    picked = card(rows, v, today)
    # The list pages by (date, id), newest first; `before` is the last row's "date|id".
    if before:
        bd, _, bi = before.partition("|")
        visible = [e for e in visible if (str(e.get("date")), str(e["id"])) < (bd, bi)]
    page = visible[:limit]
    since = (date.fromisoformat(today) - timedelta(days=NEW_DAYS)).isoformat()
    unseen = sum(1 for e in for_viewer(rows, v) if e["id"] not in v.seen and str(e.get("date"))[:10] >= since)
    return {
        "ok": True, "church": v.church,
        "card": [shape(e, v, today) for e in picked],
        "updates": [shape(e, v, today) for e in page],
        "unseen": unseen,
        "more": len(visible) > limit,
        "next": f"{page[-1]['date']}|{page[-1]['id']}" if len(visible) > limit and page else None,
    }


@router.post("/updates/seen")
def mark_seen(business: Dict[str, Any] = Depends(business_access("viewer")),
              session: UserSession = Depends(sb_clients.authed_request),
              payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Record that this login has seen these updates here. Only published
    updates they may see are recorded; seeing one twice keeps the first."""
    body = payload if isinstance(payload, dict) else {}
    ids, how, everything = body.get("ids"), body.get("how"), body.get("all") is True
    if not everything and (not isinstance(ids, list) or not ids):
        raise HTTPException(400, "ids is a list of update ids, or all is true")
    if how not in SEEN_HOW:
        raise HTTPException(400, f"how is one of {', '.join(SEEN_HOW)}")
    user_id = str(session.user.id)
    v = viewer_for(business, user_id)
    mine = [e["id"] for e in for_viewer(published(), v)]
    if everything:
        # "Mark all seen": every update this login may see, the pages the app
        # hasn't loaded yet too. What was seen already keeps its first row.
        already = seen_ids(user_id, str(business["id"]))
        if already is None:
            raise HTTPException(503, "Couldn't save that just now.")
        keep = [i for i in mine if i not in already]
    else:
        allowed = set(mine)
        keep = [i for i in dict.fromkeys(str(x) for x in ids[:SEEN_MAX]) if i in allowed]
    if not keep:
        return {"ok": True, "saved": 0}
    rows = [{"user_id": user_id, "business_id": str(business["id"]), "update_id": i, "how": how} for i in keep]
    res = sb_clients.sb_post_as_service(
        "/platform_update_seen?on_conflict=user_id,business_id,update_id", rows,  # type: ignore[arg-type]
        prefer="resolution=ignore-duplicates,return=representation")
    if res is None:
        raise HTTPException(503, "Couldn't save that just now.")
    return {"ok": True, "saved": len(keep)}


# ─── Mission Control: the queue ─────────────────────────────────────────

BUSINESS_WORDS = re.compile(r"\b(customers?|clients?|between jobs|invoices?|your business|sales|shop)\b", re.I)
CHURCH_WORDS = re.compile(r"\b(members?|pastors?|sundays?|congregations?|church(es)?|ministr(y|ies)|sermons?|giving)\b", re.I)


def warnings(entry: Dict[str, Any]) -> List[str]:
    """What the editor should look at before publishing, in plain words."""
    out: List[str] = []
    kinds = _list(entry.get("kinds"))
    churches_see = not kinds or "ministry" in kinds
    others_see = not kinds or any(k != "ministry" for k in kinds)
    text = " ".join(str(entry.get(k) or "") for k in ("title", "line", "body"))
    church_text = " ".join(str(entry.get(f"church_{k}") or "") for k in ("title", "line", "body")).strip()
    if churches_see:
        hit = BUSINESS_WORDS.search(church_text or text)
        if hit:
            out.append(f"Churches will read “{hit.group(0)}”. Add church words, or set it for businesses only.")
    if others_see:
        hit = CHURCH_WORDS.search(text)
        if hit:
            out.append(f"Businesses will read “{hit.group(0)}”. Set it for churches only, or reword it.")
    if not _plain(entry.get("line")):
        out.append("No one-line version: the card would show the title alone.")
    elif len(_plain(entry.get("line"))) > 140:
        out.append("The one line is long for the card (over 140 letters).")
    if len(_plain(entry.get("title"))) > 90:
        out.append("The title is long for the card (over 90 letters).")
    if entry.get("weight") == "big" and not entry.get("page"):
        out.append("A big change with no page: Show me and the tour have nowhere to go.")
    return out


def _clean_entry(raw: Dict[str, Any], *, creating: bool) -> Dict[str, Any]:
    """The editable fields of an update, checked. Raises 400 on a bad one."""
    if not isinstance(raw, dict):
        raise HTTPException(400, "send an object")
    out: Dict[str, Any] = {}
    for k, cap in LIMITS.items():
        if k not in raw:
            continue
        val = raw[k]
        if val is None and (k.startswith("church_") or k == "group_key"):
            out[k] = None
            continue
        val = str(val or "").strip() if k in ("body", "church_body", "notes") else _plain(val)
        if len(val) > cap:
            raise HTTPException(400, f"{k} is over {cap} letters")
        if k == "title" and not val:
            raise HTTPException(400, "an update needs a title")
        if k == "area" and not val:
            raise HTTPException(400, "an update needs an area")
        out[k] = val if (val or k not in ("church_title", "church_line", "church_body", "group_key")) else None
    if "date" in raw:
        try:
            out["date"] = date.fromisoformat(str(raw["date"])[:10]).isoformat()
        except ValueError:
            raise HTTPException(400, "date is YYYY-MM-DD")
    if "page" in raw:
        p = raw["page"]
        if p in (None, ""):
            out["page"] = None
        elif not (isinstance(p, str) and PAGE_RE.match(p)):
            raise HTTPException(400, "page is 'area:id'")
        else:
            out["page"] = p
    for k in ("kinds", "areas"):
        if k in raw:
            vals = _list(raw[k])
            if any(not KEY_RE.match(x) for x in vals):
                raise HTTPException(400, f"{k} are lower-case keys")
            out[k] = list(dict.fromkeys(vals))
    if "roles" in raw:
        vals = _list(raw["roles"])
        if any(x not in ROLES for x in vals):
            raise HTTPException(400, f"roles are from {', '.join(ROLES)}")
        out["roles"] = list(dict.fromkeys(vals))
    if "weight" in raw:
        if raw["weight"] not in WEIGHTS:
            raise HTTPException(400, f"weight is one of {', '.join(WEIGHTS)}")
        out["weight"] = raw["weight"]
    if "status" in raw:
        if raw["status"] not in STATUSES:
            raise HTTPException(400, f"status is one of {', '.join(STATUSES)}")
        out["status"] = raw["status"]
    if "tour" in raw:
        tour = raw["tour"]
        if not isinstance(tour, list) or len(tour) > 6:
            raise HTTPException(400, "tour is a list of up to 6 steps")
        steps = []
        for s in tour:
            if not isinstance(s, dict) or not _plain(s.get("text")):
                raise HTTPException(400, "each tour step has text")
            step = {"text": _plain(s["text"])[:400]}
            if _plain(s.get("church_text")):
                step["church_text"] = _plain(s["church_text"])[:400]
            if _plain(s.get("anchor")):
                step["anchor"] = _plain(s["anchor"])[:80]
            steps.append(step)
        out["tour"] = steps
    if creating:
        if "title" not in out:
            raise HTTPException(400, "an update needs a title")
        out.setdefault("date", _today())
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:60].rstrip("-") or "update")


def _one(update_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(f"/platform_updates?id=eq.{_q(update_id)}&select={COLUMNS}&limit=1")
    return rows[0] if isinstance(rows, list) and rows else None


def _with_warnings(row: Dict[str, Any]) -> Dict[str, Any]:
    return {**row, "warnings": warnings(row)}


@router.get("/platform/updates")
def queue(status: str = Query(default="draft"), q: Optional[str] = Query(default=None, max_length=80),
          limit: int = Query(default=100, ge=1, le=500),
          _: AuthedUser = Depends(require_owner)) -> Dict[str, Any]:
    if status not in STATUSES + ("all",):
        raise HTTPException(400, "status is draft, published, archived or all")
    flt = "" if status == "all" else f"status=eq.{status}&"
    if q and q.strip():
        term = _q("*" + re.sub(r"[*,()]", " ", q.strip()) + "*")
        flt += f"or=(title.ilike.{term},line.ilike.{term},id.ilike.{term})&"
    rows = sb_clients.sb_get_as_service(
        f"/platform_updates?{flt}select={COLUMNS}&order=date.desc,id.desc&limit={limit}")
    if rows is None:
        raise HTTPException(503, "The updates didn't load. Nothing has changed.")
    counts = {s: sb_clients.sb_count_as_service(f"/platform_updates?status=eq.{s}&select=id") for s in STATUSES}
    return {"ok": True, "rows": [_with_warnings(r) for r in rows], "counts": counts}


@router.post("/platform/updates")
def create(payload: Dict[str, Any] = Body(...), _: AuthedUser = Depends(require_owner)) -> Dict[str, Any]:
    row = _clean_entry(payload, creating=True)
    uid = payload.get("id") if isinstance(payload.get("id"), str) else f"{row['date']}-{_slug(row['title'])}"
    if not ID_RE.match(uid):
        raise HTTPException(400, "id is YYYY-MM-DD-short-slug")
    if _one(uid):
        raise HTTPException(409, "An update with that id already exists.")
    row.update(id=uid, source="editor", status=row.get("status", "draft"))
    if row["status"] == "published":
        row["published_at"] = _now().isoformat()
    res = sb_clients.sb_post_as_service("/platform_updates", row)
    if not res:
        raise HTTPException(503, "Couldn't save that just now.")
    forget_cache()
    return {"ok": True, "row": _with_warnings(res[0] if isinstance(res, list) else res)}


@router.patch("/platform/updates/{update_id}")
def edit(update_id: str, payload: Dict[str, Any] = Body(...),
         _: AuthedUser = Depends(require_owner)) -> Dict[str, Any]:
    if not ID_RE.match(update_id):
        raise HTTPException(404, "No such update.")
    before = _one(update_id)
    if not before:
        raise HTTPException(404, "No such update.")
    row = _clean_entry(payload, creating=False)
    if not row:
        return {"ok": True, "row": _with_warnings(before)}
    row["updated_at"] = _now().isoformat()
    if row.get("status") == "published" and before.get("status") != "published":
        row["published_at"] = _now().isoformat()
    res = sb_clients.sb_patch_as_service(f"/platform_updates?id=eq.{_q(update_id)}", row)
    if not res:
        raise HTTPException(503, "Couldn't save that just now.")
    forget_cache()
    return {"ok": True, "row": _with_warnings(res[0] if isinstance(res, list) else res)}


# ─── Mission Control: news drafts ───────────────────────────────────────

NEWS_COLUMNS = ("id,update_id,status,audience,headline,body,church_headline,church_body,source_repo,"
                "source_pr,created_at,updated_at,decided_at")


def _clean_news(raw: Dict[str, Any], *, creating: bool) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(400, "send an object")
    out: Dict[str, Any] = {}
    for k, cap in (("headline", 200), ("church_headline", 200)):
        if k in raw:
            val = _plain(raw[k])
            if len(val) > cap:
                raise HTTPException(400, f"{k} is over {cap} letters")
            out[k] = val or (None if k.startswith("church_") else "")
    for k, cap in (("body", 8000), ("church_body", 8000)):
        if k in raw:
            val = str(raw[k] or "").strip()
            if len(val) > cap:
                raise HTTPException(400, f"{k} is over {cap} letters")
            out[k] = val or (None if k.startswith("church_") else "")
    if "audience" in raw:
        if raw["audience"] not in AUDIENCES:
            raise HTTPException(400, "audience is all, business or church")
        out["audience"] = raw["audience"]
    if "status" in raw:
        if raw["status"] not in NEWS_STATUSES:
            raise HTTPException(400, "status is draft, approved or dropped")
        out["status"] = raw["status"]
    if "update_id" in raw:
        u = raw["update_id"]
        if u is not None and not (isinstance(u, str) and ID_RE.match(u)):
            raise HTTPException(400, "update_id is an update's id")
        out["update_id"] = u
    if creating and not out.get("headline"):
        raise HTTPException(400, "a news draft needs a headline")
    return out


@router.get("/platform/news-drafts")
def news_drafts(status: str = Query(default="draft"), limit: int = Query(default=100, ge=1, le=300),
                _: AuthedUser = Depends(require_owner)) -> Dict[str, Any]:
    if status not in NEWS_STATUSES + ("all",):
        raise HTTPException(400, "status is draft, approved, dropped or all")
    flt = "" if status == "all" else f"status=eq.{status}&"
    rows = sb_clients.sb_get_as_service(
        f"/platform_news_drafts?{flt}select={NEWS_COLUMNS}&order=created_at.desc&limit={limit}")
    if rows is None:
        raise HTTPException(503, "The news drafts didn't load. Nothing has changed.")
    return {"ok": True, "rows": rows}


@router.post("/platform/news-drafts")
def create_news(payload: Dict[str, Any] = Body(...), _: AuthedUser = Depends(require_owner)) -> Dict[str, Any]:
    row = _clean_news(payload, creating=True)
    res = sb_clients.sb_post_as_service("/platform_news_drafts", row)
    if not res:
        raise HTTPException(503, "Couldn't save that just now.")
    return {"ok": True, "row": res[0] if isinstance(res, list) else res}


@router.patch("/platform/news-drafts/{draft_id}")
def edit_news(draft_id: str, payload: Dict[str, Any] = Body(...),
              _: AuthedUser = Depends(require_owner)) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f-]{36}", draft_id or ""):
        raise HTTPException(404, "No such draft.")
    row = _clean_news(payload, creating=False)
    if not row:
        raise HTTPException(400, "nothing to change")
    row["updated_at"] = _now().isoformat()
    if row.get("status") in ("approved", "dropped"):
        row["decided_at"] = _now().isoformat()
    res = sb_clients.sb_patch_as_service(f"/platform_news_drafts?id=eq.{_q(draft_id)}", row)
    if not res:
        raise HTTPException(404, "No such draft.")
    return {"ok": True, "row": res[0] if isinstance(res, list) else res}
