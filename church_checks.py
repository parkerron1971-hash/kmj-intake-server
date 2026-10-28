"""church_checks.py — Check requests: money going out, with a receipt, a limit and a yes.

Kevin, 2026-10-27, on the Church Office Prototypes ("Check requests" tab,
artifact 2vGqaUZUynRuiFVKuQEZWo): "lets go with your list", third after
help requests and serving hours. The Bible school coordinator spent $340 on
supplies: on her phone, under Serve, she taps Get paid back, takes a photo
of the receipt, picks the ministry and the amount. The office approves it,
pays it by check or bank transfer, and it shows in the books against that
ministry's budget. Lane: Build, under the Build item "Love City leaves
Subsplash (M-1)".

    a REQUEST ..... who asked (one of the church's people from the member
                    app, or the office itself: "pay the camp directly"),
                    who gets paid, what it was for, the ministry, the
                    amount, the receipt, and a status: new, approved, paid,
                    declined. A decline carries a reason the asker reads
    the RECEIPT ... a photo (made upright, at most 2200px, re-saved as JPEG,
                    so a phone's location tags never travel with it) or a
                    PDF, in the private business-documents bucket under
                    "<church id>/check-requests/". Nobody reads it by a
                    public link: the office through /church/checks, the
                    asker through /my/paid-back, both from the server
    the LEVELS .... who says yes, by amount (church_money_levels.py; Kevin
                    2026-10-23/26, and 2026-10-28 "change check requests
                    yourself"): the treasurer for every amount; $500 and up
                    the pastor too; over $2,500, or past the ministry's
                    budget, a board member too. Each yes from a different
                    person, never the one who asked; what one payee is
                    asked for within 7 days counts together. The pastor and
                    a board member open this page to say yes or no, and
                    nothing more. CHURCH_MONEY_LEVELS=off goes back to the
                    LIMIT below
    the LIMIT ..... (the money levels off) up to it (the church sets it
                    here; $250 unless set) the treasurer's role approves:
                    the owner, admins, the accountant, and logins whose
                    areas include Giving & money. Above it a keeper of Giving & money says yes,
                    through the church keys (church_keys.py), the way Help
                    requests do (church_help.py): a keeper approves it here,
                    or the treasurer asks for a key (an hour's yes, by tap or
                    code). A church with no keeper for Giving & money has
                    only the limit, and the page says so. Raising the limit
                    needs the same yes
    BUDGET LINES .. the church's ministries, each with this year's budget
                    (church_check_settings.lines). The books already have a
                    place for a ministry: an expense's subcategory. So spent
                    is every expense this year whose subcategory is the
                    ministry's name, whoever entered it; a paid request is
                    one of them. The fixed monthly categories in
                    business_budgets (operating, tax, ...) can't say "Kids"
                    or "Youth", so the lines are a small setting of their
                    own. Never saved, they start from the church's ministry
                    groups, else a short starter list
    PAID .......... by check (its number) or bank transfer, and the day.
                    Marking paid writes ONE business_expenses row
                    (Operating, subcategory the ministry, vendor who was
                    paid, the receipt attached), the same plain row Chief's
                    log_expense and the Expenses screen write, so the GL
                    triggers post it. A closed period refuses it. Taking a
                    payment back (the owner and admins) removes its expense
                    and leaves the request approved

  GET    /church/checks/status?business_id=        {enabled, approve, settings}
  GET    /church/checks?business_id=               the settings, budgets, keeper and requests
  PUT    /church/checks/settings                   {business_id, limit?, lines?: [{name, budget}]}
  POST   /church/checks/requests                   {business_id, amount, about, ministry, payee?, contact_id?, name?}
  PATCH  /church/checks/requests/{id}              {business_id, amount?, about?, ministry?, payee?}   while new
  POST   /church/checks/requests/{id}/receipt      multipart: business_id, file
  GET    /church/checks/requests/{id}/receipt?business_id=     the receipt's bytes
  POST   /church/checks/requests/{id}/decide       {business_id, status: approved | declined, reason?}
                                                    (a yes with the levels on: {request, approved, step, missing, told})
  POST   /church/checks/requests/{id}/paid         {business_id, how: check | transfer, check_number?, paid_on?}
  DELETE /church/checks/requests/{id}/paid?business_id=        take the payment back (and its expense)
  POST   /church/checks/requests/{id}/keeper       {business_id}       ask a keeper (church keys; levels off)
  POST   /church/checks/key-code                   {business_id, key_id, code}             (levels off)

The member side is member_portal_checks.py (/my/paid-back), which calls
member_ask / member_requests / member_receipt here. Switched by
CHURCH_CHECKS: off | owner | on (owner until a Thursday): owner opens the
office routes to the platform owner alone, and the member side only in the
platform owner's own preview of the member app. Until
supabase/APPLY-2026-10-27-church-checks.sql is applied the status says
enabled false and every other route answers 503, never 500.
"""
from __future__ import annotations

import io
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

import business_access
import church_money_levels
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/checks", tags=["church"])

STATUSES = ("new", "approved", "paid", "declined")
SOURCES = ("app", "office")
PAID_HOWS = ("check", "transfer")
HOW_WORD = {"check": "check", "transfer": "bank transfer"}
TREASURERS = ("owner", "admin", "accountant")         # the treasurer's role, whatever their areas
WRITERS = ("owner", "admin", "manager", "member", "accountant")
KEEPS_ALL = ("owner", "admin")                          # the limit, the budgets, taking a payment back
MONEY_AREA = "giving_money"

DEFAULT_LIMIT_CENTS = 25000
LEVELS_ON = ("The money levels say who says yes: the treasurer, the pastor too from $500, and a board member "
             "too over $2,500. The limit and the Giving keeper don't decide while they're on.")
MONEY_MAX_CENTS = 10_000_000
NAME_MAX, ABOUT_MAX, PAYEE_MAX, REASON_MAX, LINE_MAX, CHECK_NO_MAX = 120, 200, 120, 300, 60, 20
LINES_MAX = 40
OPEN_DAYS = 365          # a paid or declined request stays on the page a year
MINE_MAX = 30            # the asker's own list in the member app

# Never saved, the budget lines start from the church's ministry groups,
# else these.
STARTER_LINES = ("Kids", "Youth", "Worship", "Hospitality", "Outreach", "Building", "Office")

# The receipt: private, read only through the server.
RECEIPT_BUCKET = "business-documents"
RECEIPT_FOLDER = "check-requests"
RECEIPT_MAX_BYTES = 15 * 1024 * 1024
RECEIPT_SIDE = 2200
_RECEIPT_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|pdf)")

REQ_FIELDS = ("id,contact_id,asker_name,payee,ministry,about,amount_cents,receipt_path,receipt_type,status,source,"
              "decline_reason,decided_by,decided_at,paid_how,check_number,paid_on,expense_id,paid_by,paid_at,"
              "created_by,created_at,updated_at")


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_CHECKS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _owner_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        return (user.email or "").strip().lower() == _owner_email()
    return False


_OWNER_SEEN: Dict[str, bool] = {}


def is_platform_owner(owner_id: Any) -> bool:
    """Whether a member-app preview was opened by the platform owner (owner
    mode shows the member side there and nowhere else). A lookup that fails
    is a no, and is asked again next time."""
    key = str(owner_id or "")
    if not key:
        return False
    if key not in _OWNER_SEEN:
        try:
            import platform_suite
            _OWNER_SEEN[key] = (platform_suite._owner_email(key) or "") == _owner_email()
        except Exception:  # noqa: BLE001 — unread is a no
            return False
    return _OWNER_SEEN[key]


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one (or the tables before their
    migration) is a 503, never an empty list."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Check requests couldn't be read just now. Try again.")
    return rows


def usd(cents: Any) -> str:
    c = int(cents or 0)
    return f"${c // 100:,}" if c % 100 == 0 else f"${c / 100:,.2f}"


def cents(v: Any, what: str = "amount", *, allow_none: bool = True) -> Optional[int]:
    """Dollars as typed ("340", "$1,200.50") → cents; blank is None."""
    if v in (None, ""):
        if allow_none:
            return None
        raise HTTPException(400, f"Enter the {what} in dollars.")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = round(float(v) * 100)
    else:
        s = str(v).strip().replace("$", "").replace(",", "")
        if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
            raise HTTPException(400, f"Enter the {what} in dollars, like 340 or 62.18.")
        n = round(float(s) * 100)
    if not 0 <= n <= MONEY_MAX_CENTS:
        raise HTTPException(400, f"Enter the {what} in dollars, like 340 or 62.18.")
    return int(n)


def _amount(v: Any) -> int:
    n = cents(v, allow_none=False)
    if not n:
        raise HTTPException(400, "Enter how much it was, like 340 or 62.18.")
    return n


def _tz(biz_id: str) -> ZoneInfo:
    try:
        import outside_calendar
        return ZoneInfo(outside_calendar.business_timezone(biz_id) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, Exception):
        return ZoneInfo("UTC")


def _today(biz_id: str, cache: Optional[Dict[str, Any]] = None) -> date:
    """Today in the church's clock."""
    if cache is not None:
        if "tz" not in cache:
            cache["tz"] = _tz(biz_id)
        zone = cache["tz"]
    else:
        zone = _tz(biz_id)
    return _now().astimezone(zone).date()


def _chunks(ids: Iterable[Any], n: int = 100) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


# ─── Who's asking (the office) ────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _role(biz_id: str, user: AuthedUser) -> str:
    """The login's role on this church, or 'accountant' for the church's
    accountant (a collaborator, not a seat). 404 for anyone else."""
    try:
        return business_access.assert_access(biz_id, user, "viewer")
    except HTTPException as e:
        if e.status_code != 404:
            raise
        import business_collaborators_router as bcr
        if bcr.is_active_accountant(biz_id, str(user.id)):
            return "accountant"
        raise


def treasurer(biz_id: str, uid: str, role: str) -> bool:
    """The treasurer's role: the owner, admins and the accountant, or an
    office login whose areas include Giving & money (Who sees what). A
    login with every area, or none read, isn't one: money stays with the
    owner, admins and the accountant unless a church says otherwise. A view
    that couldn't be read is a 503, never a yes."""
    if role in TREASURERS:
        return True
    import church_areas
    if church_areas.mode() != "on":
        return False
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    return isinstance(areas, list) and MONEY_AREA in areas


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and this login's standing in its check requests. 404 when
    the switch is closed to them, they have no login here, or it isn't a
    church; 403 for a login outside the treasurer's role, unless the money
    levels make them the pastor or a board member (who say yes or no, and
    nothing more)."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = _role(biz_id, user)
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Check requests are for churches")
    uid = str(user.id)
    keeps = treasurer(biz_id, uid, role)
    me = {"biz": biz, "role": role, "uid": uid, "user": user, "treasurer": keeps,
          "boss": role in KEEPS_ALL, "writer": keeps and role in WRITERS}
    if not keeps and not church_money_levels.approver(me):
        raise HTTPException(403, "Check requests are kept with the treasurer: the owner, admins, the accountant, "
                                 "or a login that works Giving & money.")
    return me


def _writer(me: Dict[str, Any]) -> None:
    if not me["writer"]:
        raise HTTPException(403, "Your login can read check requests but not act on them." if me["treasurer"] else
                            "Adding, changing and paying check requests stays with the treasurer: you say yes or no.")


def _boss(me: Dict[str, Any], why: str) -> None:
    if not me["boss"]:
        raise HTTPException(403, why)


def ready(biz_id: str) -> bool:
    """The two tables answer (one migration makes them)."""
    return isinstance(sb_clients.sb_get_as_service(
        f"/church_check_requests?business_id=eq.{_q(biz_id)}&select=id&limit=1"), list)


# ─── Settings: the limit and the budget lines ─────────────────────────

def _ministry_groups(biz_id: str) -> List[str]:
    rows = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{_q(biz_id)}&kind=eq.ministry&active=eq.true&select=name&order=name.asc&limit={LINES_MAX}")
    names: List[str] = []
    for r in rows if isinstance(rows, list) else []:
        n = _plain(r.get("name"))[:LINE_MAX]
        if n and n.lower() not in {x.lower() for x in names}:
            names.append(n)
    return sorted(names, key=str.lower)


def settings(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/church_check_settings?business_id=eq.{_q(biz_id)}&select=limit_cents,lines,updated_at&limit=1")
    s = rows[0] if rows else {}
    limit = s.get("limit_cents")
    lines = _clean_lines(s.get("lines")) if rows else []
    if not rows:
        lines = [{"name": n, "budget_cents": 0} for n in (_ministry_groups(biz_id) or STARTER_LINES)]
    return {"limit_cents": int(limit) if limit is not None else DEFAULT_LIMIT_CENTS, "lines": lines, "saved": bool(rows)}


def _clean_lines(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for x in raw if isinstance(raw, list) else []:
        if not isinstance(x, dict):
            continue
        name = _plain(x.get("name"))[:LINE_MAX]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            budget = max(0, min(int(x.get("budget_cents") or 0), MONEY_MAX_CENTS))
        except (TypeError, ValueError):
            budget = 0
        out.append({"name": name, "budget_cents": budget})
    return out[:LINES_MAX]


def ministry_of(s: Dict[str, Any], v: Any) -> str:
    """One of the church's budget lines, in its own spelling."""
    name = _plain(v)
    for line in s["lines"]:
        if line["name"].lower() == name.lower():
            return line["name"]
    raise HTTPException(400, "Pick the ministry it was for.")


# ─── The keepers (church_keys), as Help requests use them ─────────────

def keeper_state(me: Dict[str, Any]) -> Dict[str, Any]:
    """Whether a keeper of Giving & money says yes above the limit here, and
    where this login stands: a keeper, holding an open key, or waiting on
    one. `on` is false while the keys are off, the church named no keeper
    (then the limit alone governs), or the money levels decide instead."""
    import church_keys
    off = {"on": False, "mine": False, "open_until": None, "asked": None, "keepers": 0}
    if church_keys.mode() == "off" or church_money_levels.on():
        return off
    biz = str(me["biz"]["id"])
    keepers = church_keys.active_keepers(biz, MONEY_AREA)
    if not keepers:
        return off
    state = {**off, "on": True, "keepers": len(keepers), "mine": me["uid"] in keepers}
    if state["mine"]:
        return state
    now = _now()
    rows = _need(f"/church_area_keys?business_id=eq.{_q(biz)}&user_id=eq.{_q(me['uid'])}&area=eq.{MONEY_AREA}"
                 "&status=in.(asked,open)&select=id,status,asked_at,opens_until&order=asked_at.desc&limit=5")
    for r in rows:
        until, asked = church_keys._at(r.get("opens_until")), church_keys._at(r.get("asked_at"))
        if r.get("status") == "open" and until and until > now and not state["open_until"]:
            state["open_until"] = r["opens_until"]
        elif (r.get("status") == "asked" and asked and asked > now - timedelta(hours=church_keys.ASK_HOURS)
              and not state["asked"]):
            state["asked"] = {"id": r["id"], "asked_at": r["asked_at"]}
    return state


def may_approve(me: Dict[str, Any], amount: int, s: Dict[str, Any]) -> None:
    """Whether this login may say yes to `amount` cents: up to the limit, the
    treasurer's role; above it, only while Giving & money is open to them (a
    keeper, or an open key), and never where the church has no keeper (the
    limit alone governs)."""
    _writer(me)
    limit = s["limit_cents"]
    if amount <= limit:
        return
    ks = keeper_state(me)
    if not ks["on"]:
        raise HTTPException(403, {
            "code": "over_limit", "limit_cents": limit,
            "message": f"Your church has no keeper for Giving & money, so {usd(limit)} is the most anyone approves "
                       "at once. The owner or an admin can change the limit on this page."})
    import church_keys
    if not church_keys.is_open(str(me["biz"]["id"]), me["user"], MONEY_AREA):
        raise HTTPException(403, {
            "code": "needs_keeper", "limit_cents": limit,
            "message": f"Above the {usd(limit)} limit, a keeper of Giving & money says yes. Ask a keeper: "
                       "their yes opens it for an hour."})


# ─── The receipt ──────────────────────────────────────────────────────

def prepare_receipt(raw: bytes) -> Tuple[str, bytes, str, str]:
    """(kind, bytes, media type, extension) to keep: a PDF as it came, a
    photo upright, at most RECEIPT_SIDE on its long side, re-saved as JPEG
    (which drops the phone's location tags). 400 for anything else."""
    if not raw:
        raise HTTPException(400, "Add a photo of the receipt.")
    if len(raw) > RECEIPT_MAX_BYTES:
        raise HTTPException(400, "That file is too large. Choose one under 15 MB.")
    if raw[:5] == b"%PDF-":
        return "pdf", raw, "application/pdf", "pdf"
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP", "MPO", "GIF") or im.width * im.height > 60_000_000:
                raise HTTPException(400, "Choose a photo of the receipt (JPG, PNG or WebP) or a PDF.")
            im.load()
            im = ImageOps.exif_transpose(im)
            if min(im.width, im.height) < 32:
                raise HTTPException(400, "That picture is too small to read. Take the photo again.")
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                flat = Image.new("RGB", im.size, (255, 255, 255))
                flat.paste(im, mask=im.getchannel("A"))
                im = flat
            else:
                im = im.convert("RGB")
            im.thumbnail((RECEIPT_SIDE, RECEIPT_SIDE), Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, "JPEG", quality=82, optimize=True, progressive=True)
            return "image", out.getvalue(), "image/jpeg", "jpg"
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "Choose a photo of the receipt (JPG, PNG or WebP) or a PDF.")


def receipt_key(biz_id: str, path: Any) -> bool:
    """True only for a receipt path this module could have made for this church."""
    import storage_links
    biz = storage_links.canonical_business_id(biz_id)
    if not biz or not isinstance(path, str):
        return False
    head = f"{biz}/{RECEIPT_FOLDER}/"
    return path.startswith(head) and bool(_RECEIPT_NAME.fullmatch(path[len(head):]))


def _storage_url(path: str) -> str:
    return f"{(os.environ.get('SUPABASE_URL') or '').rstrip('/')}/storage/v1/object/{RECEIPT_BUCKET}/{path}"


def _storage_put(path: str, data: bytes, media: str) -> Tuple[bool, int, str]:
    import httpx
    import storage_links
    try:
        r = httpx.post(_storage_url(path), headers={**storage_links.service_headers(), "Content-Type": media},
                       content=data, timeout=30)
        return r.is_success, r.status_code, r.text[:300]
    except Exception:  # noqa: BLE001
        logger.warning("church checks: receipt upload failed", exc_info=True)
        return False, 0, ""


def _storage_get(path: str) -> Optional[bytes]:
    import httpx
    import storage_links
    try:
        r = httpx.get(_storage_url(path), headers=storage_links.service_headers(), timeout=30)
    except Exception:  # noqa: BLE001
        logger.warning("church checks: receipt read failed", exc_info=True)
        return None
    return r.content if r.is_success else None


def _storage_drop(path: str) -> None:
    import httpx
    import storage_links
    try:
        httpx.request("DELETE", _storage_url(path), headers=storage_links.service_headers(), timeout=15)
    except Exception:  # noqa: BLE001
        logger.info("church checks: receipt delete skipped", exc_info=True)


def put_receipt(biz_id: str, raw: bytes) -> Tuple[str, str]:
    """Keep a receipt in the private bucket: (its path, image | pdf)."""
    import storage_links
    kind, data, media, ext = prepare_receipt(raw)
    biz = storage_links.canonical_business_id(biz_id)
    if not biz or not storage_links.has_service_key():
        raise HTTPException(503, storage_links.UPLOAD_NOT_CONFIGURED)
    path = f"{biz}/{RECEIPT_FOLDER}/{uuid.uuid4().hex}.{ext}"
    ok, status, body = _storage_put(path, data, media)
    if not ok:
        logger.warning("church checks: receipt refused %s %s", status, body[:200])
        raise HTTPException(503, storage_links.upload_refusal(status, body) if status else storage_links.UPLOAD_UNREACHABLE)
    return path, kind


def read_receipt(biz_id: str, row: Dict[str, Any]) -> Response:
    """A request's receipt, from the server only: never a public link."""
    path = row.get("receipt_path")
    if not path or not receipt_key(biz_id, path):
        raise HTTPException(404, "There's no receipt on this one.")
    data = _storage_get(path)
    if data is None:
        raise HTTPException(503, "The receipt couldn't be read just now. Try again.")
    media = "application/pdf" if str(path).endswith(".pdf") else "image/jpeg"
    return Response(content=data, media_type=media, headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="receipt.{str(path).rsplit(".", 1)[-1]}"'})


# ─── Requests: reading ────────────────────────────────────────────────

def _rows(biz_id: str) -> List[Dict[str, Any]]:
    """Open requests, and the year's paid and declined, newest first."""
    since = _q(_iso(_now() - timedelta(days=OPEN_DAYS)))
    open_ = _need(f"/church_check_requests?business_id=eq.{_q(biz_id)}&status=in.(new,approved)"
                  f"&select={REQ_FIELDS}&order=created_at.desc&limit=500")
    done = _need(f"/church_check_requests?business_id=eq.{_q(biz_id)}&status=in.(paid,declined)"
                 f"&created_at=gte.{since}&select={REQ_FIELDS}&order=created_at.desc&limit=500")
    return open_ + done


def _names(biz_id: str, rows: List[Dict[str, Any]]) -> Dict[str, str]:
    people: Dict[str, str] = {}
    for ids in _chunks(r.get("contact_id") for r in rows):
        for c in _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(ids)})&select=id,name&limit=200"):
            people[str(c["id"])] = _plain(c.get("name"))
    return people


def _seat_names(biz: Dict[str, Any], uids: Iterable[Any]) -> Dict[str, str]:
    want = {str(u) for u in uids if u}
    if not want:
        return {}
    owner = str(biz.get("owner_id") or "")
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(biz['id'])}&status=eq.active&select=user_id,invited_email&limit=500")
    by = {str(s["user_id"]): str(s.get("invited_email") or "") for s in seats or [] if isinstance(s, dict)}
    return {u: ("The owner" if u == owner else by.get(u) or "The office") for u in want}


def shown(me: Dict[str, Any], rows: List[Dict[str, Any]], s: Dict[str, Any]) -> List[Dict[str, Any]]:
    biz = me["biz"]
    people = _names(str(biz["id"]), rows)
    by = _seat_names(biz, [r.get(k) for r in rows for k in ("decided_by", "paid_by", "created_by")])
    out = []
    for r in rows:
        who = people.get(str(r.get("contact_id") or "")) or r.get("asker_name") or None
        paid = None
        if r.get("status") == "paid":
            paid = {"how": r.get("paid_how"), "check_number": r.get("check_number"), "paid_on": r.get("paid_on"),
                    "in_books": bool(r.get("expense_id")), "by": by.get(str(r.get("paid_by") or "")) if r.get("paid_by") else None}
        out.append({
            "id": str(r["id"]), "status": r.get("status"), "source": r.get("source"),
            "who": who, "contact_id": r.get("contact_id"), "payee": r.get("payee") or who,
            "ministry": r.get("ministry"), "about": r.get("about") or "", "amount_cents": int(r.get("amount_cents") or 0),
            "over_limit": int(r.get("amount_cents") or 0) > s["limit_cents"],
            "receipt": r.get("receipt_type") if r.get("receipt_path") else None,
            "decline_reason": r.get("decline_reason") or None,
            "created_at": r.get("created_at"), "decided_at": r.get("decided_at"),
            "decided_by": by.get(str(r.get("decided_by") or "")) if r.get("decided_by") else None,
            "added_by": by.get(str(r.get("created_by") or "")) if r.get("source") == "office" and r.get("created_by") else None,
            "paid": paid,
        })
    return out


def budgets(me: Dict[str, Any], s: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Spent against each ministry's budget this year, in the church's clock:
    every expense whose subcategory is the ministry's name (a paid request is
    one), and what's approved and not paid yet beside it."""
    biz = str(me["biz"]["id"])
    today = _today(biz, me)
    start, end = today.replace(month=1, day=1).isoformat(), today.replace(month=12, day=31).isoformat()
    spent_by: Dict[str, int] = {}
    for e in _need(f"/business_expenses?business_id=eq.{_q(biz)}&date=gte.{start}&date=lte.{end}"
                   "&select=amount,subcategory&limit=20000"):
        key = _plain(e.get("subcategory")).lower()
        if key:
            try:
                spent_by[key] = spent_by.get(key, 0) + round(float(e.get("amount") or 0) * 100)
            except (TypeError, ValueError):
                continue
    committed: Dict[str, int] = {}
    for r in rows:
        if r.get("status") == "approved":
            key = _plain(r.get("ministry")).lower()
            committed[key] = committed.get(key, 0) + int(r.get("amount_cents") or 0)
    lines = [{**line, "spent_cents": spent_by.get(line["name"].lower(), 0),
              "committed_cents": committed.get(line["name"].lower(), 0)} for line in s["lines"]]
    paid_year = sum(int(r.get("amount_cents") or 0) for r in rows
                    if r.get("status") == "paid" and str(r.get("paid_on") or "") >= start)
    return {"year": today.year, "lines": lines, "paid_year_cents": paid_year,
            "budget_cents": sum(x["budget_cents"] for x in lines),
            "spent_cents": sum(x["spent_cents"] for x in lines)}


def page(me: Dict[str, Any]) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    s = settings(biz)
    rows = _rows(biz)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    new = [r for r in rows if r.get("status") == "new"]
    approved = [r for r in rows if r.get("status") == "approved"]
    views = shown(me, rows, s)
    spend = budgets(me, s, rows)
    church_money_levels.annotate(me, views, rows, spend["lines"])
    return {
        "settings": s,
        "budgets": spend,
        "keeper": keeper_state(me),
        "levels": church_money_levels.page_view(me),
        "requests": views,
        "totals": {"waiting": len(new), "waiting_cents": sum(int(r.get("amount_cents") or 0) for r in new),
                   "approved": len(approved), "approved_cents": sum(int(r.get("amount_cents") or 0) for r in approved)},
        "me": _can(me),
    }


def _can(me: Dict[str, Any]) -> Dict[str, Any]:
    """approve: say yes or no; pay: add, change and pay (the treasurer's
    role); settings: the limit and the budgets."""
    return {"approve": me["writer"] or church_money_levels.approver(me), "pay": me["writer"], "settings": me["boss"]}


# ─── Requests: writing ────────────────────────────────────────────────

def _contact(biz_id: str, v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    cid = _uuid(v, "person")
    if not _need(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}&select=id&limit=1"):
        raise HTTPException(400, "That person isn't one of this church's people.")
    return cid


def _about(v: Any) -> str:
    about = _plain(v)[:ABOUT_MAX]
    if not about:
        raise HTTPException(400, "Say what it was for, like craft supplies for Bible school.")
    return about


def resolve(me: Dict[str, Any], rid: Any) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    rows = _need(f"/church_check_requests?id=eq.{_q(_uuid(rid, 'request'))}&business_id=eq.{_q(biz)}"
                 f"&select={REQ_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That request isn't here.")
    return rows[0]


def _one(me: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    biz = str(me["biz"]["id"])
    s = settings(biz)
    view = shown(me, [row], s)[0]
    if church_money_levels.on():
        rows = _rows(biz)
        if not any(str(r["id"]) == str(row["id"]) for r in rows):
            rows.append(row)
        church_money_levels.annotate(me, [view], [row], budgets(me, s, rows)["lines"], rows)
    return view


def _patch(me: Dict[str, Any], row: Dict[str, Any], fields: Dict[str, Any], *, was: str) -> Dict[str, Any]:
    """Change a request only from the status it was read in: two people
    pressing at once settle once."""
    biz = str(me["biz"]["id"])
    fields["updated_at"] = _iso(_now())
    got = sb_clients.sb_patch_as_service(
        f"/church_check_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&status=eq.{_q(was)}", fields)
    if not isinstance(got, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "Someone changed this request just now. Open it again.")
    return got[0]


def add(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """The office's own request: pay the camp directly, or one a volunteer
    handed in on paper."""
    _writer(me)
    biz = str(me["biz"]["id"])
    s = settings(biz)
    amount = _amount(body.get("amount"))
    about = _about(body.get("about"))
    ministry = ministry_of(s, body.get("ministry"))
    contact = _contact(biz, body.get("contact_id"))
    name = None if contact else (_plain(body.get("name"))[:NAME_MAX] or None)
    payee = _plain(body.get("payee"))[:PAYEE_MAX] or None
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service("/church_check_requests", {
        "id": str(uuid.uuid4()), "business_id": biz, "contact_id": contact, "asker_name": name, "payee": payee,
        "ministry": ministry, "about": about, "amount_cents": amount, "status": "new", "source": "office",
        "created_by": me["uid"], "created_at": now, "updated_at": now})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That request didn't save. Try again.")
    return {"request": _one(me, saved[0])}


def edit(me: Dict[str, Any], rid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Fix the amount, what it was for, the ministry or who gets paid, while
    it waits for a yes."""
    _writer(me)
    row = resolve(me, rid)
    if row["status"] != "new":
        raise HTTPException(409, "Only a request waiting for a yes can be changed.")
    s = settings(str(me["biz"]["id"]))
    fields: Dict[str, Any] = {}
    if "amount" in body:
        fields["amount_cents"] = _amount(body.get("amount"))
    if "about" in body:
        fields["about"] = _about(body.get("about"))
    if "ministry" in body:
        fields["ministry"] = ministry_of(s, body.get("ministry"))
    if "payee" in body:
        fields["payee"] = _plain(body.get("payee"))[:PAYEE_MAX] or None
    if not fields:
        return {"request": _one(me, row)}
    changed = any(k in fields and fields[k] != row.get(k) for k in ("amount_cents", "ministry", "payee"))
    if changed and church_money_levels.on():
        # A yes was for what it asked before: they go, before and after the
        # change (one given as it changed goes too).
        biz = str(me["biz"]["id"])
        if not church_money_levels.take_back_yeses(biz, str(row["id"])):
            raise HTTPException(503, "That didn't save. Try again.")
        saved = _patch(me, row, fields, was="new")
        church_money_levels.take_back_yeses(biz, str(row["id"]))
        return {"request": _one(me, saved)}
    return {"request": _one(me, _patch(me, row, fields, was="new"))}


def attach(me: Dict[str, Any], rid: str, raw: bytes) -> Dict[str, Any]:
    """The office adds or replaces a receipt (an invoice from the camp, a
    receipt handed in on paper), before it's paid."""
    _writer(me)
    biz = str(me["biz"]["id"])
    row = resolve(me, rid)
    if row["status"] not in ("new", "approved"):
        raise HTTPException(409, "A receipt goes on before the request is paid.")
    path, kind = put_receipt(biz, raw)
    try:
        saved = _patch(me, row, {"receipt_path": path, "receipt_type": kind}, was=row["status"])
    except HTTPException:
        _storage_drop(path)
        raise
    old = row.get("receipt_path")
    if old and old != path and receipt_key(biz, old):
        _storage_drop(old)
    return {"request": _one(me, saved)}


def decide(me: Dict[str, Any], rid: str, status: Any, reason: Any) -> Dict[str, Any]:
    """Approve or decline with a reason the asker reads. With the money
    levels on, a yes is this login's step and the request is approved once
    every step it needs has one; the pastor or a board member declines one
    that waits on them. With them off: up to the limit, or above it with a
    keeper's yes."""
    if status not in ("approved", "declined"):
        raise HTTPException(400, "A request is approved or declined.")
    if not church_money_levels.on():
        _writer(me)
    row = resolve(me, rid)
    if status == "declined":
        if row["status"] not in ("new", "approved"):
            raise HTTPException(409, "This one was paid already. Take the payment back first."
                                if row["status"] == "paid" else "This one was declined already.")
        if not me["writer"]:
            lv = church_money_levels.check(me, row)[1] if row["status"] == "new" else {"needs": []}
            if not set(lv["needs"]) & church_money_levels.steps_of(me) or (lv.get("why_not") or "").startswith("You asked"):
                raise HTTPException(403, "This one isn't waiting on you.")
        why = _plain(reason)[:REASON_MAX]
        if not why:
            raise HTTPException(400, "Say why, in a sentence they'll read: it shows in their app.")
        saved = _patch(me, row, {"status": "declined", "decline_reason": why, "decided_by": me["uid"],
                                 "decided_at": _iso(_now())}, was=row["status"])
        return {"request": _one(me, saved)}
    if row["status"] != "new":
        raise HTTPException(409, {"approved": "This one is approved already.", "paid": "This one was paid already.",
                                  "declined": "This one was declined. Add it again if things changed."}.get(
                                      row["status"], "This request was settled already."))
    if church_money_levels.on():
        return church_money_levels.approve(me, row)
    s = settings(str(me["biz"]["id"]))
    may_approve(me, int(row.get("amount_cents") or 0), s)
    saved = _patch(me, row, {"status": "approved", "decline_reason": None, "decided_by": me["uid"],
                             "decided_at": _iso(_now())}, was="new")
    return {"request": _one(me, saved)}


def _day(v: Any, me: Dict[str, Any]) -> date:
    biz = str(me["biz"]["id"])
    if v in (None, ""):
        return _today(biz, me)
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, "Pick the day it was paid.")
    if d > _today(biz, me) + timedelta(days=1):
        raise HTTPException(400, "Mark it paid once it's paid: that day hasn't come yet.")
    return d


def _closed_books(biz: str, day: date) -> None:
    import period_lock
    period = period_lock.locked_period(biz, day.isoformat())
    if period:
        raise HTTPException(409, {
            "code": "books_closed",
            "message": f"{day:%b} {day.day}, {day.year} is in books that are closed "
                       f"({period.get('period_start')} to {period.get('period_end')}). Pick another day, "
                       "or reopen that period in Bookkeeping."})


def _who_paid(me: Dict[str, Any], row: Dict[str, Any]) -> Optional[str]:
    if row.get("payee"):
        return row["payee"]
    if row.get("contact_id"):
        return _names(str(me["biz"]["id"]), [row]).get(str(row["contact_id"])) or row.get("asker_name")
    return row.get("asker_name")


def _expense(me: Dict[str, Any], row: Dict[str, Any], how: str, day: date, number: Optional[str]) -> str:
    """The money out, in the books the way every expense goes: a plain
    business_expenses row (Operating, the ministry as its subcategory, the
    receipt attached), which the GL triggers post."""
    paid = f"check #{number}" if how == "check" and number else HOW_WORD[how]
    saved = sb_clients.sb_post_as_service("/business_expenses", {
        "business_id": str(me["biz"]["id"]), "amount": round(int(row["amount_cents"]) / 100, 2),
        "category": "operating", "subcategory": _plain(row.get("ministry"))[:LINE_MAX] or None,
        "description": f"Check request: {_plain(row.get('about'))[:ABOUT_MAX]} (paid by {paid})",
        "date": day.isoformat(), "vendor": (_who_paid(me, row) or None),
        "payment_method": "check" if how == "check" else None,
        "receipt_path": row.get("receipt_path") or None,
    })
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        raise HTTPException(503, "That didn't reach the books, so nothing was saved. Try again.")
    return str(saved[0]["id"])


def mark_paid(me: Dict[str, Any], rid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Paid by check (its number) or bank transfer, on a day. One expense in
    the ministry's line; a closed period refuses it."""
    _writer(me)
    biz = str(me["biz"]["id"])
    how = body.get("how")
    if how not in PAID_HOWS:
        raise HTTPException(400, "Say how it was paid: a check, or a bank transfer.")
    number = _plain(body.get("check_number"))[:CHECK_NO_MAX] or None
    if how == "check" and not number:
        raise HTTPException(400, "Enter the check number.")
    if how == "check" and not re.fullmatch(r"[A-Za-z0-9 #-]{1,20}", number or ""):
        raise HTTPException(400, "Enter the check number as it's printed, like 1043.")
    day = _day(body.get("paid_on"), me)
    row = resolve(me, rid)
    if row["status"] != "approved":
        raise HTTPException(409, {"new": "Approve it first, then mark it paid.", "paid": "This one was paid already.",
                                  "declined": "This one was declined."}.get(row["status"], "This request can't be paid."))
    _closed_books(biz, day)
    expense_id = _expense(me, row, how, day, number)
    fields = {"status": "paid", "paid_how": how, "check_number": number if how == "check" else None,
              "paid_on": day.isoformat(), "expense_id": expense_id, "paid_by": me["uid"], "paid_at": _iso(_now()),
              "updated_at": _iso(_now())}
    got = sb_clients.sb_patch_as_service(
        f"/church_check_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&status=eq.approved", fields)
    if not isinstance(got, list) or not got:
        # Ours didn't land (someone paid it a moment ago, or the write
        # failed): our expense goes, so it's in the books once.
        sb_clients.sb_delete_as_service(f"/business_expenses?id=eq.{_q(expense_id)}&business_id=eq.{_q(biz)}")
        if isinstance(got, list):
            raise HTTPException(409, "Someone marked this paid just now. Open it again.")
        raise HTTPException(503, "That didn't save. Try again.")
    return {"request": _one(me, got[0]), "in_books": True}


def take_back(me: Dict[str, Any], rid: str) -> Dict[str, Any]:
    """Take a payment back, with its expense: the owner and admins. The
    request goes back to approved."""
    _boss(me, "Only the owner or an admin takes a payment back.")
    biz = str(me["biz"]["id"])
    row = resolve(me, rid)
    if row["status"] != "paid":
        raise HTTPException(409, "This one isn't marked paid.")
    if row.get("expense_id") and row.get("paid_on"):
        _closed_books(biz, date.fromisoformat(str(row["paid_on"])[:10]))
    # The request first: a request still saying paid while its expense is
    # gone would be the books and the page disagreeing.
    saved = _patch(me, row, {"status": "approved", "paid_how": None, "check_number": None, "paid_on": None,
                             "expense_id": None, "paid_by": None, "paid_at": None}, was="paid")
    books = True
    if row.get("expense_id") and not sb_clients.sb_delete_as_service(
            f"/business_expenses?id=eq.{_q(row['expense_id'])}&business_id=eq.{_q(biz)}"):
        books = False
    said = None if books else ("The payment is taken back, but its expense is still in the books. "
                               "Remove it in Bookkeeping, under Expenses.")
    return {"request": _one(me, saved), "books": books, "message": said}


def _lines_in(body: Any, have: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(body, list):
        raise HTTPException(400, "Send the budget lines as a list.")
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for x in body:
        if not isinstance(x, dict):
            raise HTTPException(400, "Each budget line needs a name.")
        name = _plain(x.get("name"))[:LINE_MAX]
        if not name:
            raise HTTPException(400, "Each budget line needs a name, like Kids or Hospitality.")
        if name.lower() in seen:
            raise HTTPException(400, f"{name} is on the list twice.")
        seen.add(name.lower())
        out.append({"name": name, "budget_cents": cents(x.get("budget"), f"budget for {name}") or 0})
    if not out:
        raise HTTPException(400, "Keep at least one ministry, so a request has somewhere to go.")
    if len(out) > LINES_MAX:
        raise HTTPException(400, f"{LINES_MAX} ministries at most.")
    return out


def put_settings(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """The limit and the budget lines: the owner and admins. Raising the
    limit needs a keeper's yes where the church has keepers (else it would
    be the way around them)."""
    _boss(me, "Only the owner or an admin changes the limit and the budgets.")
    biz = str(me["biz"]["id"])
    have = settings(biz)
    out: Dict[str, Any] = {}
    if "lines" in body:
        out["lines"] = _lines_in(body.get("lines"), have)
    if "limit" in body:
        limit = cents(body.get("limit"), "limit", allow_none=False)
        if church_money_levels.on() and limit != have["limit_cents"]:
            raise HTTPException(400, {"code": "levels_on", "message": LEVELS_ON})
        if limit > have["limit_cents"]:
            ks = keeper_state(me)
            import church_keys
            if ks["on"] and not church_keys.is_open(biz, me["user"], MONEY_AREA):
                raise HTTPException(403, {
                    "code": "needs_keeper", "limit_cents": have["limit_cents"],
                    "message": "Raising the limit needs a keeper of Giving & money. Ask a keeper: their yes "
                               "opens it for an hour."})
        out["limit_cents"] = limit
    if not out:
        return {"settings": have}
    saved = sb_clients.sb_post_as_service("/church_check_settings?on_conflict=business_id", {
        "business_id": biz, "limit_cents": have["limit_cents"], "lines": have["lines"], **out,
        "updated_by": me["uid"], "updated_at": _iso(_now())},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"settings": settings(biz)}


def ask_keeper(me: Dict[str, Any], rid: str) -> Dict[str, Any]:
    """Ask the keepers of Giving & money for a yes above the limit: the
    church keys' own ask (every keeper hears it, with a code to read out).
    The reason names the ministry and the amount. Only with the money
    levels off."""
    _writer(me)
    biz = str(me["biz"]["id"])
    row = resolve(me, rid)
    if church_money_levels.on():
        raise HTTPException(409, {"code": "levels_on", "message": LEVELS_ON})
    if row["status"] != "new":
        raise HTTPException(409, "Only a request waiting for a yes needs a keeper.")
    s = settings(biz)
    amount = int(row.get("amount_cents") or 0)
    if amount <= s["limit_cents"]:
        raise HTTPException(400, f"That's within the {usd(s['limit_cents'])} limit: approve it here.")
    ks = keeper_state(me)
    if not ks["on"]:
        raise HTTPException(409, {"code": "over_limit", "limit_cents": s["limit_cents"],
                                  "message": f"Your church has no keeper for Giving & money, so "
                                             f"{usd(s['limit_cents'])} is the most anyone approves at once."})
    if ks["mine"]:
        raise HTTPException(409, "You keep Giving & money, so you can approve it here.")
    import church_keys
    got = church_keys.ask(biz, me["user"], MONEY_AREA,
                          f"Check request: {row.get('ministry') or 'a ministry'}, {usd(amount)} "
                          f"(over the {usd(s['limit_cents'])} limit)")
    return {"key": got.get("key"), "told": got.get("told", 0), "request": _one(me, row)}


def key_code(me: Dict[str, Any], key_id: Any, code: Any) -> Dict[str, Any]:
    """The code a keeper read out, for this login's ask for Giving & money."""
    _writer(me)
    if church_money_levels.on():
        raise HTTPException(409, {"code": "levels_on", "message": LEVELS_ON})
    biz = str(me["biz"]["id"])
    kid = _uuid(key_id, "ask")
    rows = _need(f"/church_area_keys?id=eq.{_q(kid)}&business_id=eq.{_q(biz)}&select=area,user_id&limit=1")
    if not rows or rows[0].get("area") != MONEY_AREA or str(rows[0].get("user_id")) != me["uid"]:
        raise HTTPException(404, "That ask isn't here.")
    import church_keys
    return church_keys.enter_code(biz, me["user"], kid, str(code or ""))


# ─── The member side (member_portal_checks.py) ────────────────────────

def serves(biz: Dict[str, Any], person: Dict[str, Any]) -> bool:
    """Whether this member serves, so Get paid back is theirs: a place on a
    Sunday team, a church role, a group they lead, a kids room, or a church
    login by their email (an office seat, or the owner). A read that fails
    is a no."""
    biz_id, cid = str(biz["id"]), str(person.get("id") or "")
    if not cid:
        return False

    def some(path: str) -> bool:
        rows = sb_clients.sb_get_as_service(path)
        return isinstance(rows, list) and bool(rows)
    b, c = _q(biz_id), _q(cid)
    if some(f"/church_leader_roles?business_id=eq.{b}&contact_id=eq.{c}&status=eq.active&select=id&limit=1"):
        return True
    if some(f"/group_members?business_id=eq.{b}&contact_id=eq.{c}&role=eq.leader&select=group_id&limit=1"):
        return True
    if some(f"/space_leaders?business_id=eq.{b}&contact_id=eq.{c}&select=contact_id&limit=1"):
        return True
    try:
        import sunday_serving
        if sunday_serving.serves(biz, cid):
            return True
    except Exception:  # noqa: BLE001 — a read that fails is a no
        logger.info("church checks: serving read skipped", exc_info=True)
    email = (person.get("email") or "").strip().lower()
    if "@" not in email:
        return False
    import church_areas
    if some(f"/business_users?business_id=eq.{b}&status=eq.active"
            f"&invited_email=ilike.{_q(church_areas._escape_ilike(email))}&select=user_id&limit=1"):
        return True
    return _church_owner_email(biz.get("owner_id")) == email


_OWNER_MAIL: Dict[str, str] = {}


def _church_owner_email(owner_id: Any) -> str:
    """The church owner's sign-in email, kept per replica once read; '' when
    it can't be read (and asked again next time)."""
    key = str(owner_id or "")
    if not key:
        return ""
    if key not in _OWNER_MAIL:
        try:
            import platform_suite
            _OWNER_MAIL[key] = platform_suite._owner_email(key) or ""
        except Exception:  # noqa: BLE001
            return ""
    return _OWNER_MAIL[key]


def member_lines(biz: Dict[str, Any]) -> List[str]:
    return [line["name"] for line in settings(str(biz["id"]))["lines"]]


def member_requests(biz: Dict[str, Any], person: Dict[str, Any]) -> List[Dict[str, Any]]:
    """This member's own requests, newest first: never anyone else's."""
    rows = _need(f"/church_check_requests?business_id=eq.{_q(biz['id'])}&contact_id=eq.{_q(_uuid(person['id'], 'person'))}"
                 f"&select={REQ_FIELDS}&order=created_at.desc&limit={MINE_MAX}")
    return [{"id": str(r["id"]), "status": r.get("status"), "ministry": r.get("ministry"), "about": r.get("about") or "",
             "amount_cents": int(r.get("amount_cents") or 0), "receipt": r.get("receipt_type") if r.get("receipt_path") else None,
             "decline_reason": r.get("decline_reason") if r.get("status") == "declined" else None,
             "paid_how": r.get("paid_how") if r.get("status") == "paid" else None,
             "check_number": r.get("check_number") if r.get("status") == "paid" else None,
             "paid_on": r.get("paid_on") if r.get("status") == "paid" else None,
             "created_at": r.get("created_at")} for r in rows]


def member_ask(biz: Dict[str, Any], person: Dict[str, Any], amount: Any, about: Any, ministry: Any,
               raw: bytes) -> Dict[str, Any]:
    """A volunteer asks to be paid back: the receipt, the amount, what it
    was for and the ministry. It waits for the treasurer's yes."""
    biz_id = str(biz["id"])
    cid = _uuid(person.get("id"), "person")
    s = settings(biz_id)
    amount_c = _amount(amount)
    about_t = _about(about)
    line = ministry_of(s, ministry)
    path, kind = put_receipt(biz_id, raw)
    name = _plain(person.get("name"))[:NAME_MAX] or None
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service("/church_check_requests", {
        "id": str(uuid.uuid4()), "business_id": biz_id, "contact_id": cid, "asker_name": name, "payee": name,
        "ministry": line, "about": about_t, "amount_cents": amount_c, "receipt_path": path, "receipt_type": kind,
        "status": "new", "source": "app", "created_at": now, "updated_at": now})
    if not isinstance(saved, list) or not saved:
        _storage_drop(path)
        raise HTTPException(503, "That didn't send. Try again in a moment.")
    return saved[0]


def member_receipt(biz: Dict[str, Any], person: Dict[str, Any], rid: Any) -> Response:
    """The receipt on one of this member's own requests."""
    rows = _need(f"/church_check_requests?id=eq.{_q(_uuid(rid, 'request'))}&business_id=eq.{_q(biz['id'])}"
                 f"&contact_id=eq.{_q(_uuid(person.get('id'), 'person'))}&select=id,receipt_path&limit=1")
    if not rows:
        raise HTTPException(404, "That request isn't here.")
    return read_receipt(str(biz["id"]), rows[0])


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def checks_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's office shows Check requests: the app asks once,
    so its menu offers the page only where it opens. Quietly false for a
    closed switch, a business that isn't a church, a login outside the
    treasurer's role, or tables not made yet."""
    off = {"enabled": False, "approve": False, "pay": False, "settings": False}
    if not open_to(user):
        return off
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail == "Check requests are for churches":
            return off
        raise
    if not ready(str(me["biz"]["id"])):
        return off
    return {"enabled": True, **_can(me)}


@router.get("")
def checks_page(business_id: str, user: AuthedUser = Depends(require_user)):
    return page(_access(business_id, user))


@router.put("/settings")
def checks_settings(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return put_settings(me, body or {})


@router.post("/requests")
def checks_add(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return add(me, body or {})


@router.patch("/requests/{rid}")
def checks_edit(rid: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return edit(me, rid, body or {})


@router.post("/requests/{rid}/receipt")
def checks_attach(rid: str, business_id: str = Form(...), file: UploadFile = File(...),
                  user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    raw = file.file.read(RECEIPT_MAX_BYTES + 1)
    return attach(me, rid, raw)


@router.get("/requests/{rid}/receipt")
def checks_receipt(rid: str, business_id: str, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    return read_receipt(str(me["biz"]["id"]), resolve(me, rid))


@router.post("/requests/{rid}/decide")
def checks_decide(rid: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return decide(me, rid, body.get("status"), body.get("reason"))


@router.post("/requests/{rid}/paid")
def checks_paid(rid: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return mark_paid(me, rid, body or {})


@router.delete("/requests/{rid}/paid")
def checks_take_back(rid: str, business_id: str, user: AuthedUser = Depends(require_user)):
    return take_back(_access(business_id, user), rid)


@router.post("/requests/{rid}/keeper")
def checks_keeper(rid: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return ask_keeper(me, rid)


@router.post("/key-code")
def checks_key_code(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return key_code(me, body.get("key_id"), body.get("code"))
