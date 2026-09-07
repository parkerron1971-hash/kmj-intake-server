"""Authenticated Growth API and shared mutation cores. No model-generated SQL.

New tables are service-only. HTTP checks the verified owner/team role before
service access; Chief reaches these cores through its authorized action dispatcher.
Every query, including edits and linked-record validation, is business-scoped.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import sb_clients
from auth_supabase import AuthedUser, require_user
from growth_intelligence import report, normalize_bookings

router = APIRouter(prefix="/growth-intelligence", tags=["growth-intelligence"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Preferences(StrictModel):
    timezone: str = "UTC"
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    weekly_hours: Optional[float] = Field(default=None, ge=0, le=10000)


class GrowthAction(StrictModel):
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    title: str = Field(min_length=1, max_length=180)
    owner: str = Field(default="", max_length=120)
    start_date: date
    due_date: date
    metric: Literal["revenue", "bookings", "buyers"]
    target: float = Field(gt=0, le=1e12)
    status: Literal["planned", "active", "completed", "paused"] = "active"
    notes: str = Field(default="", max_length=4000)
    contact_ids: list[UUID] = Field(default_factory=list, max_length=200)
    archived: bool = False


class GrowthCost(StrictModel):
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    description: str = Field(min_length=1, max_length=180)
    date: date
    amount: float = Field(ge=0, le=1e12)
    kind: Literal["marketing", "direct", "overhead"]
    source: str = Field(default="", max_length=120)
    offering: str = Field(default="", max_length=120)
    contact_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    hours: float = Field(default=0, ge=0, le=10000)
    archived: bool = False


class Attribution(StrictModel):
    invoice_id: UUID
    campaign_id: UUID
    evidence: str = Field(min_length=3, max_length=1000)
    archived: bool = False


MODELS = {"preferences": Preferences, "actions": GrowthAction, "costs": GrowthCost, "attributions": Attribution}


class SaveRecord(StrictModel):
    data: dict
    id: Optional[UUID] = None
    revision: Optional[int] = Field(default=None, ge=1)
    request_id: UUID = Field(default_factory=uuid4)


async def db(client, method, path, body=None):
    """Strict variant: a failed read is never an empty healthy business."""
    try:
        res = await client.request(method, sb_clients.sb_url()+"/rest/v1"+path,
                                   headers=sb_clients.sb_headers_service(), json=body, timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Growth data is temporarily unavailable. Try again.") from exc
    if res.status_code >= 400:
        if res.status_code in (404, 406) or "PGRST205" in res.text or "42P01" in res.text:
            raise HTTPException(503, "Growth reporting is not available yet. Its data update needs to be applied.")
        if res.status_code == 409:
            raise HTTPException(409, "This record already exists. Refresh and edit the saved record.")
        raise HTTPException(502, "Growth data could not be read or saved. No success was recorded.")
    return res.json() if res.content else []


async def authorize(client, business_id, user, write=False):
    bid = str(UUID(str(business_id)))
    rows = await db(client, "GET", f"/businesses?id=eq.{bid}&select=id,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "Business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        from business_users_router import require_role
        await asyncio.to_thread(require_role, bid, user.id, "member" if write else "viewer")
    return rows[0]


async def all_rows(client, table, bid, extra="", cap=50000):
    rows = []
    # Offset is advanced by actual size: works even when PostgREST caps below
    # our requested page size. The extra empty request establishes completeness.
    while True:
        page = await db(client, "GET", f"/{table}?business_id=eq.{bid}&select=*&order=id.asc&limit=1000&offset={len(rows)}{extra}")
        if not page:
            return rows
        rows.extend(page)
        if len(rows) > cap:
            raise HTTPException(413, "This report exceeds the current history limit. It has not been shown as a complete total.")


def unpack(row):
    return {**row["data"], "id": row["id"], "revision": row["revision"]}


async def load_report(client, bid, period="mtd", comparison="previous", start=None, end=None):
    bid = str(UUID(str(bid)))
    names = ["contacts", "invoices", "sessions", "campaigns", "growth_records", "growth_events"]
    results = await asyncio.gather(*(all_rows(client, name, bid) for name in names))
    raw = dict(zip(names, results))
    modules, entries = await asyncio.gather(all_rows(client, 'custom_modules', bid, '&archetype=eq.booking_calendar'),
                                           all_rows(client, 'module_entries', bid, '&appointment_at=not.is.null'))
    module_ids = {m['id'] for m in modules}
    raw['sessions'] = normalize_bookings(raw['sessions'], [e for e in entries if e.get('module_id') in module_ids])
    records = raw.pop("growth_records")
    prefs = next((unpack(r) for r in records if r["kind"] == "preferences"), {})
    for kind in ("costs", "actions", "attributions"):
        raw[kind] = [unpack(r) for r in records if r["kind"] == kind]
    raw["events"] = raw.pop("growth_events")
    raw["warnings"] = ["Collections use paid invoice totals; partial payments and refunds need reconciliation in Revenue.",
                       "Capacity combines Sessions and dated booking-calendar records, deduplicating mirrored online bookings.",
                       "Costs are analytical allocations, not additional bookkeeping entries. Contributions use recorded direct costs only."]
    if not prefs:
        raw["warnings"].append("Reporting uses USD and UTC until you save your reporting settings.")
    try:
        result = report(raw, prefs, period, comparison, start=start, end=end)
    except (ValueError, KeyError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(422, "Check the reporting dates, comparison and timezone.") from exc
    result["preferences"] = prefs or {"timezone": "UTC", "currency": "USD", "weekly_hours": None}
    result["records"] = {kind: [unpack(r) for r in records if r["kind"] == kind] for kind in ("actions", "costs", "attributions")}
    return result


async def validate_links(client, bid, kind, data):
    links = []
    if kind == "actions":
        if data["due_date"] < data["start_date"] or (date.fromisoformat(data["due_date"])-date.fromisoformat(data["start_date"])).days > 730:
            raise HTTPException(422, "Action due date must follow its start within two years.")
        links += [("contacts", cid) for cid in data["contact_ids"]]
    if kind in ("costs", "attributions"):
        links += [("contacts", data["contact_id"])] if data.get("contact_id") else []
        links += [("campaigns", data["campaign_id"])] if data.get("campaign_id") else []
    if kind == "costs":
        if data["date"] > date.today().isoformat():
            raise HTTPException(422, "Recorded costs cannot be dated in the future.")
        if data["kind"] == "direct" and not data["offering"].strip() and not data.get("contact_id"):
            raise HTTPException(422, "Assign a direct cost to a service or person.")
        if data["kind"] == "marketing" and not data["source"].strip():
            raise HTTPException(422, "Give marketing spend a source so it can be compared.")
    if kind == "attributions":
        links.append(("invoices", data["invoice_id"]))
    for table, rid in links:
        rows = await db(client, "GET", f"/{table}?business_id=eq.{bid}&id=eq.{rid}&select=id&limit=1")
        if not rows:
            raise HTTPException(422, "A linked record does not belong to this business or no longer exists.")
    if kind == "preferences":
        try:
            ZoneInfo(data["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, "Use a valid timezone, such as America/New_York.")


async def save_record(client, bid, kind, request):
    bid = str(UUID(str(bid)))
    if kind not in MODELS:
        raise HTTPException(422, "Unknown Growth record type")
    try:
        data = MODELS[kind](**request.data).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(422, "Check the required fields and values for this Growth record.") from exc
    if kind in ("costs", "actions") and not data.get("currency"):
        preferences = await db(client, "GET", f"/growth_records?business_id=eq.{bid}&kind=eq.preferences&limit=1")
        data["currency"] = preferences[0]["data"].get("currency", "USD") if preferences else "USD"
    await validate_links(client, bid, kind, data)
    rid = str(request.id) if request.id else str(request.request_id)
    if request.id:
        if request.revision is None:
            raise HTTPException(422, "Recall the current record revision before changing it.")
        old = await db(client, "GET", f"/growth_records?business_id=eq.{bid}&kind=eq.{kind}&id=eq.{rid}&limit=1")
        if not old:
            raise HTTPException(404, "Growth record not found")
        if kind == "preferences":
            data["history_since"] = old[0]["data"].get("history_since")
        if old[0].get("last_request_id") == str(request.request_id) and old[0]["data"] == data:
            return unpack(old[0])
        rows = await db(client, "PATCH", f"/growth_records?business_id=eq.{bid}&kind=eq.{kind}&id=eq.{rid}&revision=eq.{request.revision}",
                        {"data": data, "revision": request.revision+1, "last_request_id": str(request.request_id), "updated_at": datetime.now(timezone.utc).isoformat()})
        if not rows:
            raise HTTPException(409, "Someone changed this record. Refresh before saving again.")
    else:
        previous = await db(client, "GET", f"/growth_records?business_id=eq.{bid}&id=eq.{rid}&limit=1")
        if previous:
            if previous[0]["kind"] != kind or previous[0]["data"] != data:
                raise HTTPException(409, "This save identifier was already used for another change.")
            return unpack(previous[0])
        rows = await db(client, "POST", "/growth_records", {"id": rid, "business_id": bid, "kind": kind, "data": data})
    if not rows:
        raise HTTPException(502, "Growth change was not saved.")
    return unpack(rows[0])


@router.get("/report")
async def get_report(business_id: UUID, period: Literal["mtd", "qtd", "ytd", "30d", "90d", "custom"] = "mtd",
                     comparison: Literal["previous", "year"] = "previous", start: Optional[date] = None, end: Optional[date] = None,
                     user: AuthedUser = Depends(require_user)):
    async with httpx.AsyncClient() as client:
        await authorize(client, business_id, user)
        return await load_report(client, str(business_id), period, comparison, str(start) if start else None, str(end) if end else None)


@router.post("/{kind}")
async def put_record(kind: str, request: SaveRecord, business_id: UUID = Query(...), user: AuthedUser = Depends(require_user)):
    async with httpx.AsyncClient() as client:
        await authorize(client, business_id, user, write=True)
        return await save_record(client, str(business_id), kind, request)
