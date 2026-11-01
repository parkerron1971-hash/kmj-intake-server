"""
giving_sheets.py: the paper count sheet, and reading a photo of one
(Kevin, 2026-11-01).

    "I want to create a way for churches that have sheets they want to fill
    out as hard copy for their records to be able to print out a sheet ...
    and then have a way to take a picture of those sheets and it upload into
    the system and automatically updated based on that person giving ... we
    could store those pictures and the data for future checks and balances
    so we have hard copies digital copies and batches"

The sheet
  GET /giving/{id}/counts/{count}/sheet is a printable page for one service
  count. It has:
    - the church and the service with its date;
    - numbered lines for each gift (name, fund, cash, check amount,
      check #);
    - the cash by bill and coin;
    - the totals;
    - two counters' signatures.
  The funds the church uses are printed as a key, so a hand-written fund
  reads back as one of them.

The photo
  POST /giving/{id}/counts/{count}/photos takes a photo of a filled-in
  sheet (JPEG, PNG or WebP, up to 8 MB). It's kept for good in the private
  "giving-sheets" bucket and is never public. Claude reads it into rows and
  the sheet's written totals:
    - each name is matched to the church's people (exact, else unique by
      first and last name, else left for the treasurer);
    - the rows and the written totals are checked against each other.
  The rows become a DRAFT, never gifts. The screen puts them in the count's
  add-gifts grid beside the photo, and the treasurer checks each one
  against the photo before Save. Handwriting misreads (a $170 read as
  $110) are why nothing is recorded straight from a photo. After the save,
  POST .../photos/{photo}/used ties the photo to the gifts it became.

Metering and limits: llm_call.apost (task giving_sheet_read), the spend
guard, a per-church rate limit, and billing_limits.require_units, the same
as reading a PDF bank statement. Model: GIVING_SHEET_MODEL, else Sonnet 5.5.
"""
from __future__ import annotations

import asyncio
import base64
import html
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

import sb_clients
from auth_supabase import AuthedUser, require_user
# The same gate, count read and helpers as the counts (by name, so the
# access sweep follows the gate into giving_services).
from giving_services import UUID_RE, _count, _gate, _need, _q

logger = logging.getLogger("giving_sheets")
router = APIRouter(tags=["giving"])

BUCKET = "giving-sheets"
MAX_PHOTO_BYTES = 8 * 1024 * 1024
TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
SHEET_LINES = 24
DEFAULT_MODEL = "claude-sonnet-5-5"
READ_MAX_TOKENS = 8000
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=10.0)
DENOMS = [("$100", 10000), ("$50", 5000), ("$20", 2000), ("$10", 1000), ("$5", 500), ("$2", 200), ("$1", 100),
          ("Coins", None)]


def _model() -> str:
    return (os.environ.get("GIVING_SHEET_MODEL") or "").strip() or DEFAULT_MODEL


# ─── The sheet ────────────────────────────────────────────────────────

def _funds(business: Dict[str, Any]) -> List[str]:
    from giving_router import configured_funds, giving_settings
    return configured_funds(giving_settings(business.get("settings")))


def sheet_html(business: Dict[str, Any], count: Dict[str, Any], *, lines: int = SHEET_LINES) -> str:
    """The printable sheet for one count. Pure."""
    e = lambda s: html.escape(str(s or ""), quote=True)  # noqa: E731
    name = e(business.get("name") or "Church")
    funds = " · ".join(e(f) for f in _funds(business))
    rows = "".join(
        f'<tr><td class="n">{i}</td><td></td><td></td><td class="m"></td><td class="m"></td><td></td></tr>'
        for i in range(1, lines + 1))
    denoms = "".join(f'<tr><th>{e(label)}</th><td class="m"></td></tr>' for label, _ in DENOMS)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Count sheet: {e(count.get('name'))}, {e(dayLabel_long(str(count.get('service_date'))[:10]))}</title>
<style>
@page {{ size: letter; margin: 12mm; }}
* {{ box-sizing: border-box; }}
body {{ font: 12px/1.35 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #111; margin: 0; padding: 16px; background: #fff; }}
.bar {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; border-bottom: 2px solid #111; padding-bottom: 8px; }}
h1 {{ font-size: 18px; margin: 0; }}
.sub {{ font-size: 14px; margin: 2px 0 0; }}
.code {{ font: 11px ui-monospace, Menlo, monospace; color: #444; text-align: right; }}
.funds {{ margin: 8px 0; font-size: 11px; color: #333; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #555; padding: 0 6px; height: 26px; text-align: left; }}
th {{ font-size: 11px; background: #f2f2f2; }}
td.n {{ width: 28px; text-align: center; color: #666; }}
.m {{ width: 90px; }}
.grid {{ display: grid; grid-template-columns: 1fr 220px; gap: 14px; margin-top: 12px; align-items: start; }}
.sign {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 18px; }}
.sign div {{ border-top: 1px solid #111; padding-top: 4px; font-size: 11px; }}
.note {{ font-size: 10px; color: #555; margin-top: 10px; }}
.print {{ margin: 0 0 12px; padding: 8px 14px; font: inherit; font-size: 14px; cursor: pointer; }}
@media print {{ .print {{ display: none; }} body {{ padding: 0; }} }}
</style></head><body>
<button class="print" onclick="window.print()">Print</button>
<div class="bar"><div><h1>{name}</h1>
<p class="sub">{e(count.get('name'))} · {e(dayLabel_long(str(count.get('service_date'))[:10]))}</p></div>
<div class="code">Count sheet<br>{e(str(count.get('id'))[:8].upper())}</div></div>
<p class="funds"><strong>Funds:</strong> {funds}. Write one per line; leave Fund empty for {e(_funds(business)[0])}.</p>
<table><thead><tr><th>#</th><th>Name (or "Loose offering")</th><th>Fund</th><th class="m">Cash</th><th class="m">Check</th><th>Check #</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="grid">
<table><thead><tr><th colspan="2">Totals</th></tr></thead><tbody>
<tr><th>Cash (from the lines)</th><td class="m"></td></tr><tr><th>Checks (from the lines)</th><td class="m"></td></tr>
<tr><th>Total</th><td class="m"></td></tr></tbody></table>
<table><thead><tr><th colspan="2">Cash counted</th></tr></thead><tbody>{denoms}
<tr><th>Cash total</th><td class="m"></td></tr></tbody></table>
</div>
<div class="sign"><div>Counted by (print and sign)</div><div>Counted by (print and sign)</div></div>
<p class="note">Online gifts are recorded on their own: don't write them here. Take a clear photo of this sheet from straight above, in good light, and upload it to this service's count.</p>
</body></html>"""


def dayLabel_long(day: str) -> str:
    try:
        d = datetime.fromisoformat(day[:10])
    except ValueError:
        return day
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}, {d.year}"


@router.get("/giving/{business_id}/counts/{count_id}/sheet", response_class=HTMLResponse)
def count_sheet(business_id: str, count_id: str, user: AuthedUser = Depends(require_user)):
    biz = _gate(business_id, user)
    count = _count(business_id, count_id)
    names = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=name&limit=1") or []
    page = sheet_html({**biz, "name": (names[0] if names else {}).get("name")}, count)
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


# ─── The photo ────────────────────────────────────────────────────────

SHEET_TOOL = {
    "name": "count_sheet",
    "description": "Everything written on the church's count sheet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "items": {"type": "object", "properties": {
                "line": {"type": "integer", "description": "The printed line number, if any."},
                "name": {"type": "string", "description": "The giver's name as written, or 'Loose offering'."},
                "fund": {"type": "string", "description": "The fund as written, empty if none."},
                "cash": {"type": "number", "description": "Cash amount in dollars, 0 if none."},
                "check": {"type": "number", "description": "Check amount in dollars, 0 if none."},
                "check_number": {"type": "string"},
                "unsure": {"type": "boolean", "description": "True when any part of this line was hard to read."},
            }, "required": ["name", "cash", "check"]}},
            "written_cash_total": {"type": "number"},
            "written_checks_total": {"type": "number"},
            "written_total": {"type": "number"},
            "counted_cash_total": {"type": "number", "description": "The 'Cash counted' box total, if filled."},
            "counters": {"type": "array", "items": {"type": "string"}},
            "readable": {"type": "boolean", "description": "False when this isn't a count sheet or can't be read."},
        },
        "required": ["lines", "readable"],
    },
}
_READ_SYSTEM = (
    "You read a church's hand-written offering count sheet into the count_sheet tool, exactly as written. "
    "One entry per filled line, in order. Amounts in dollars as numbers. Never guess a name or an amount: "
    "copy what is written, and mark the line unsure when any part is hard to read. A line with only an "
    "amount and no name is a giver whose name wasn't written: name ''. Leave blank lines out. Read the "
    "totals boxes and the counters' printed names when they are filled. If the picture isn't a count "
    "sheet or can't be read, set readable false.")


def _money_c(v: Any) -> int:
    """Dollars as read → cents. Nothing that isn't a positive number is
    money. A misread huge amount is kept as read (not quietly capped): the
    treasurer sees it, and saving it is refused with a reason."""
    import math
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(n) or n <= 0:
        return 0
    return min(round(n * 100), 10_000_000_000)


def _norm(s: Any) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", str(s or "").lower()).split())


def match_names(lines: List[Dict[str, Any]], contacts: List[Dict[str, Any]]) -> None:
    """contact_id on each line whose name is one person: the whole name
    (any case), else the only person with that first and last name. Two
    people with the name, or none, stays for the treasurer."""
    full: Dict[str, List[str]] = {}
    ends: Dict[str, List[str]] = {}
    for c in contacts:
        n = _norm(c.get("name"))
        if not n:
            continue
        full.setdefault(n, []).append(str(c["id"]))
        parts = n.split()
        if len(parts) >= 2:
            ends.setdefault(f"{parts[0]} {parts[-1]}", []).append(str(c["id"]))
    for ln in lines:
        n = _norm(ln.get("name"))
        ids = full.get(n) or []
        if not ids and len(n.split()) >= 2:
            p = n.split()
            ids = ends.get(f"{p[0]} {p[-1]}") or []
        one = len(set(ids)) == 1
        ln["contact_id"] = ids[0] if one else None
        ln["name_match"] = "one" if one else ("several" if ids else "none")


def draft_from(got: Dict[str, Any], contacts: List[Dict[str, Any]], funds: List[str]) -> Dict[str, Any]:
    """The tool's reading → the draft the screen shows. Pure. A line with
    both cash and a check becomes two rows."""
    rows: List[Dict[str, Any]] = []
    fund_by = {f.lower(): f for f in funds}
    for i, ln in enumerate(got.get("lines") or []):
        if not isinstance(ln, dict):
            continue
        name = " ".join(str(ln.get("name") or "").split())[:120]
        loose = _norm(name) in ("loose offering", "loose", "plate", "loose cash")
        fund_raw = " ".join(str(ln.get("fund") or "").split())[:40]
        fund = fund_by.get(fund_raw.lower()) or (fund_raw or funds[0])
        base = {"line": ln.get("line") if isinstance(ln.get("line"), int) else i + 1,
                "name": "" if loose else name, "loose": loose, "fund": fund,
                "fund_known": not fund_raw or fund_raw.lower() in fund_by, "unsure": ln.get("unsure") is True}
        cash, check = _money_c(ln.get("cash")), _money_c(ln.get("check"))
        if cash:
            rows.append({**base, "method": "cash", "amount_cents": cash, "check_number": None})
        if check:
            cn = re.sub(r"[^A-Za-z0-9-]", "", str(ln.get("check_number") or ""))[:20] or None
            rows.append({**base, "method": "check", "amount_cents": check, "check_number": cn})
    match_names([r for r in rows if not r["loose"]], contacts)
    for r in rows:
        if r["loose"]:
            r.update(contact_id=None, name_match="loose")
    cash_sum = sum(r["amount_cents"] for r in rows if r["method"] == "cash")
    check_sum = sum(r["amount_cents"] for r in rows if r["method"] == "check")
    checks = []
    for label, written, ours in (("cash", got.get("written_cash_total"), cash_sum),
                                 ("checks", got.get("written_checks_total"), check_sum),
                                 ("total", got.get("written_total"), cash_sum + check_sum),
                                 ("counted cash", got.get("counted_cash_total"), cash_sum)):
        if written is not None and _money_c(written):
            checks.append({"what": label, "written_cents": _money_c(written), "lines_cents": ours,
                           "agrees": _money_c(written) == ours})
    counters = [" ".join(str(c or "").split())[:60] for c in (got.get("counters") or []) if str(c or "").strip()][:4]
    return {"rows": rows, "cash_cents": cash_sum, "checks_cents": check_sum, "checks": checks,
            "agrees": all(c["agrees"] for c in checks), "counters": counters,
            "unsure": sum(1 for r in rows if r["unsure"] or r["name_match"] in ("several", "none")
                          or not r["fund_known"])}


async def read_photo(business_id: str, raw: bytes, media_type: str) -> Dict[str, Any]:
    """Claude's reading of the sheet (the count_sheet tool's input)."""
    import billing_limits
    import llm_call
    import model_ladder
    import rate_limit
    import spend_guard
    if not llm_call.api_key():
        raise HTTPException(503, "Reading sheet photos isn't set up here. Type the gifts in instead.")
    try:
        capped = await asyncio.to_thread(spend_guard.over_budget, business_id)
    except Exception:  # noqa: BLE001
        capped = False
    if capped:
        raise HTTPException(429, "Reading sheet photos has reached today's limit. Try again tomorrow, or type "
                                 "the gifts in.")
    if not rate_limit.allow("giving_sheet_read", str(business_id)):
        raise HTTPException(429, "That's a lot of sheets in an hour. Wait a little, or type the gifts in.")
    await asyncio.to_thread(billing_limits.require_units, business_id)
    model = _model()
    forced = model_ladder.supports_forced_tool_choice(model)
    system = _READ_SYSTEM if forced else (
        _READ_SYSTEM + " Answer only by calling the count_sheet tool, exactly once; never in plain text.")
    payload = {
        "model": model, "max_tokens": READ_MAX_TOKENS, "system": system, "tools": [SHEET_TOOL],
        "tool_choice": {"type": "tool", "name": "count_sheet"} if forced else {"type": "auto"},
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.standard_b64encode(raw).decode("ascii")}},
            {"type": "text", "text": "Read this count sheet into the count_sheet tool."}]}],
        **model_ladder.thinking_off_kwargs(model),
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await llm_call.apost(client, payload, task="giving_sheet_read", business_id=business_id)
    if resp.status_code >= 400:
        print(f"[giving_sheets] read {resp.status_code}: {resp.text[:300]}", flush=True)
        raise HTTPException(502, "The sheet couldn't be read just now. Try again, or type the gifts in.")
    data = resp.json()
    got = next((b.get("input") for b in data.get("content") or []
                if b.get("type") == "tool_use" and b.get("name") == "count_sheet"), None)
    if not isinstance(got, dict):
        print(f"[giving_sheets] read gave no sheet call (stop {data.get('stop_reason')})", flush=True)
        raise HTTPException(502, "The sheet couldn't be read just now. Try again.")
    return got


def sniff(raw: bytes) -> Optional[str]:
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _store(path: str, raw: bytes, media_type: str) -> bool:
    import storage_links
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not base or not storage_links.has_service_key():
        return False
    try:
        r = httpx.post(f"{base}/storage/v1/object/{BUCKET}/{path}", content=raw, timeout=60.0,
                       headers={**storage_links.service_headers(), "Content-Type": media_type,
                                "x-upsert": "false"})
        if r.status_code >= 400:
            print(f"[giving_sheets] store {r.status_code}: {r.text[:200]}", flush=True)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[giving_sheets] store failed: {e}", flush=True)
        return False


PHOTO_FIELDS = "id,count_id,path,media_type,status,draft,error,created_by,created_at,used_at,gift_ids"


async def _mark_unread(pid: str, msg: str) -> None:
    """A photo that couldn't be read says why, never sits at 'reading'."""
    out = await asyncio.to_thread(sb_clients.sb_patch_as_service, f"/giving_count_photos?id=eq.{pid}",
                                  {"status": "unread", "error": msg[:300]})
    if not out:
        print(f"[giving_sheets] photo {pid} couldn't be marked unread", flush=True)


@router.post("/giving/{business_id}/counts/{count_id}/photos")
async def upload_photo(business_id: str, count_id: str, photo: UploadFile = File(...),
                       user: AuthedUser = Depends(require_user)):
    """Keep the photo (always, first), then read it into a draft. A photo
    that can't be read is still kept, with what went wrong."""
    biz = await asyncio.to_thread(lambda: _gate(business_id, user))
    count = await asyncio.to_thread(lambda: _count(business_id, count_id))
    raw = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "That photo is over 8 MB. Take it again a little farther away.")
    media_type = sniff(raw)
    if not media_type:
        raise HTTPException(415, "Upload a JPEG, PNG or WebP photo of the sheet.")
    pid = str(uuid.uuid4())
    path = f"{business_id}/{count_id}/{pid}.{TYPES[media_type]}"
    if not await asyncio.to_thread(_store, path, raw, media_type):
        raise HTTPException(503, "The photo couldn't be saved. Please try again.")
    row = {"id": pid, "business_id": business_id, "count_id": count_id, "path": path,
           "media_type": media_type, "status": "reading", "created_by": str(user.id)}
    if not await asyncio.to_thread(sb_clients.sb_post_as_service, "/giving_count_photos", row):
        raise HTTPException(503, "The photo was saved but couldn't be listed. Please try again.")
    try:
        got = await read_photo(business_id, raw, media_type)
        if got.get("readable") is False:
            raise HTTPException(422, "That doesn't look like a count sheet, or it can't be read. Take the photo "
                                     "again from straight above, in good light.")
        contacts = await asyncio.to_thread(
            _need, f"/contacts?business_id=eq.{_q(business_id)}&select=id,name&limit=10000")
        draft = draft_from(got, contacts, _funds(biz))
    except HTTPException as e:
        msg = e.detail.get("message") if isinstance(e.detail, dict) else str(e.detail)
        await _mark_unread(pid, str(msg))
        raise
    except Exception as e:  # noqa: BLE001 — a timeout or a dropped connection: the photo stays, said so
        print(f"[giving_sheets] read failed for photo {pid}: {e}", flush=True)
        await _mark_unread(pid, "The sheet couldn't be read just now. The photo is kept; try reading it again, "
                                "or type the gifts in.")
        raise HTTPException(502, "The sheet couldn't be read just now. The photo is kept. Try again, or type the "
                                 "gifts in.")
    saved = await asyncio.to_thread(sb_clients.sb_patch_as_service, f"/giving_count_photos?id=eq.{pid}",
                                    {"status": "read", "draft": draft})
    if not saved:
        logger.warning(f"[giving_sheets] draft not saved for photo {pid}")
    return {"ok": True, "photo_id": pid, "count_open": count.get("status") == "open", "draft": draft}


@router.get("/giving/{business_id}/counts/{count_id}/photos")
async def list_photos(business_id: str, count_id: str, user: AuthedUser = Depends(require_user)):
    import storage_links
    await asyncio.to_thread(lambda: _gate(business_id, user))
    await asyncio.to_thread(lambda: _count(business_id, count_id))
    rows = await asyncio.to_thread(
        _need, f"/giving_count_photos?business_id=eq.{_q(business_id)}&count_id=eq.{_q(count_id)}"
                  f"&select={PHOTO_FIELDS}&order=created_at.asc&limit=50")
    async with httpx.AsyncClient() as client:
        urls = await asyncio.gather(*(storage_links.signed_url(client, BUCKET, r["path"], ttl=900) for r in rows))
    return {"photos": [{"id": r["id"], "url": u, "status": r.get("status"), "draft": r.get("draft"),
                        "error": r.get("error"), "created_at": r.get("created_at"), "used_at": r.get("used_at"),
                        "gift_ids": r.get("gift_ids") or []} for r, u in zip(rows, urls)]}


@router.post("/giving/{business_id}/counts/{count_id}/photos/{photo_id}/used")
def photo_used(business_id: str, count_id: str, photo_id: str, body: Dict[str, Any],
               user: AuthedUser = Depends(require_user)):
    """Tie the photo to the gifts its draft became (the checks and balances
    trail: the sheet, its photo, the gifts)."""
    _gate(business_id, user)
    if not UUID_RE.match(photo_id):
        raise HTTPException(404, "Photo not found")
    ids = [str(i) for i in ((body or {}).get("gift_ids") or []) if UUID_RE.match(str(i))][:200]
    keep: List[str] = []
    if ids:
        rows = _need(f"/invoices?business_id=eq.{_q(business_id)}&giving_count_id=eq.{_q(count_id)}"
                        f"&id=in.({','.join(ids)})&select=id&limit=200")
        keep = [r["id"] for r in rows]
    saved = sb_clients.sb_patch_as_service(
        f"/giving_count_photos?id=eq.{_q(photo_id)}&business_id=eq.{_q(business_id)}"
        f"&count_id=eq.{_q(count_id)}",
        {"status": "used", "used_at": datetime.now(timezone.utc).isoformat(), "gift_ids": keep})
    if saved is None:
        raise HTTPException(503, "The photo couldn't be updated. Please try again.")
    if not saved:
        raise HTTPException(404, "Photo not found")
    return {"ok": True, "gift_ids": keep}
