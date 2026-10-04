"""Owner-only review and commit of Acuity CSV exports."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import acuity_migration as migration
import sb_clients
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix="/acuity-migration", tags=["migration"])


class Files(BaseModel):
    clients_csv: str = Field(default="", max_length=migration.MAX_BYTES)
    appointments_csv: str = Field(default="", max_length=migration.MAX_BYTES)


class Review(Files):
    timezone: str = Field(min_length=1, max_length=100)
    date_order: Literal["month_first", "day_first"]
    mappings: dict[str, UUID] = Field(default_factory=dict, max_length=100)
    active_only_confirmed: bool = False
    uses_staff_calendars: bool = False
    uses_classes: bool = False
    uses_subscriptions: bool = False
    has_prepaid_balances: bool = False


class Commit(BaseModel):
    batch_id: UUID
    reviewed: bool = False


class Reminders(BaseModel):
    batch_id: UUID
    enabled: bool
    cutover_confirmed: bool = False


def _rows(path):
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "I could not verify the current records. Nothing was imported; try again.")
    return rows


def _owner(business: UUID, user):
    rows = _rows(f"/businesses?id=eq.{business}&select=id,name,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "Business not found.")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "Only this business's owner can review or import Acuity records.")
    return rows[0]


def _offerings(business):
    rows = _rows(f"/offerings?business_id=eq.{business}&is_active=eq.true&select=id,name,duration_min,currency,is_active&order=name&limit=501")
    if len(rows) > 500:
        raise HTTPException(409, "This business needs an assisted migration because its service list exceeds this import's limit.")
    return rows


def _all(path, limit=20000):
    out = []
    while len(out) < limit:
        rows = _rows(f"{path}&limit=1000&offset={len(out)}")
        out.extend(rows)
        if len(rows) < 1000:
            return out
    raise HTTPException(409, "This business has more records than this migration can fully check. An assisted migration is needed.")


@router.get("/{business}/config")
def config(business: UUID, user: AuthedUser = Depends(require_user)):
    biz = _owner(business, user)
    return {"offerings": _offerings(business),
            "timezone": ((biz.get("settings") or {}).get("availability") or {}).get("timezone") or "",
            "max_rows": migration.MAX_ROWS, "max_bytes": migration.MAX_BYTES}


@router.post("/{business}/inspect")
def inspect(business: UUID, req: Files, user: AuthedUser = Depends(require_user)):
    _owner(business, user)
    try:
        return migration.inspect_files(req.clients_csv, req.appointments_csv)
    except migration.MigrationError as exc:
        raise HTTPException(422, str(exc)) from exc


def _check_current(business, plan):
    contacts = _all(f"/contacts?business_id=eq.{business}&select=id,email&order=id")
    by_email = {}
    for c in contacts:
        by_email.setdefault(str(c.get("email") or "").strip().lower(), []).append(c)
    for p in plan["clients"]:
        matches = by_email.get(p["email"], [])
        p["action"] = "existing" if matches else "new"
        if len(matches) > 1:
            plan["issues"].append({"file": "clients", "row": 0, "message": f"Multiple existing clients use {p['email']}. Resolve them before importing."})
    if not plan["appointments"]:
        return
    modules = _rows(f"/custom_modules?business_id=eq.{business}&archetype=eq.booking_calendar&is_active=eq.true&select=id&limit=2")
    if len(modules) != 1:
        plan["issues"].append({"file": "setup", "row": 0, "message": "Set up one active booking calendar before importing appointments."})
        return
    plan["module_id"] = modules[0]["id"]
    imported = _all(f"/acuity_migration_records?business_id=eq.{business}&select=source_id,source_hash,entry_id&order=source_id")
    existing = {r["source_id"]: r for r in imported}
    future = [a for a in plan["appointments"] if not a["historical"]]
    sessions = []
    entries = []
    if future:
        # All active calendar records, rather than a narrow window that could
        # miss a long appointment starting before the first imported one.
        entries = _all(f"/module_entries?business_id=eq.{business}&module_id=eq.{plan['module_id']}&status=eq.active&select=id,appointment_at,duration_min_at_booking,data&order=id")
        sessions = _all(f"/sessions?business_id=eq.{business}&status=eq.scheduled&select=id,scheduled_for,duration_minutes,notes&order=id")
    for a in plan["appointments"]:
        a["action"] = "new"
        prior = existing.get(a["source_id"])
        if prior:
            a["action"] = "existing"
            if not prior.get("entry_id"):
                plan["issues"].append({"file": "appointments", "row": a["row"], "message": "The previously imported appointment was deleted. Review it before importing again."})
            if prior["source_hash"] != a["source_hash"]:
                plan["issues"].append({"file": "appointments", "row": a["row"], "message": "This Acuity appointment changed since it was imported. Review it in your calendar; it will not be overwritten."})
            continue
        if a["historical"]:
            continue
        start = datetime.fromisoformat(a["start"].replace("Z", "+00:00"))
        end = start + timedelta(minutes=a["duration"])
        try:
            intervals = []
            for e in entries:
                data = e.get("data") or {}
                stamp = e.get("appointment_at") or data.get("appointment_at")
                duration = e.get("duration_min_at_booking") or data.get("duration_min_at_booking") or data.get("duration_min")
                if not stamp or not duration:
                    raise ValueError("unknown booking interval")
                intervals.append((stamp, duration))
            intervals += [(s["scheduled_for"], s["duration_minutes"]) for s in sessions]
            for stamp, duration in intervals:
                other = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if other.tzinfo is None or int(duration) <= 0:
                    raise ValueError("unknown calendar interval")
                if other < end and other + timedelta(minutes=int(duration)) > start:
                    plan["issues"].append({"file": "appointments", "row": a["row"], "message": "This appointment overlaps a booking or session already in Solutionist."})
                    break
        except (ValueError, KeyError, TypeError):
            plan["issues"].append({"file": "appointments", "row": a["row"], "message": "An existing calendar record has an unknown time or duration. Resolve it before importing."})


def _public_plan(plan, batch=None):
    return {"batch_id": batch, "ready": plan["ready"], "issues": plan["issues"],
            "timezone": plan["timezone"], "inventory": plan["inventory"],
            "clients": [{k: p[k] for k in ("name", "email", "action")} for p in plan["clients"]],
            "appointments": [{k: a[k] for k in ("source_id", "name", "start", "duration", "service", "historical", "action", "paid", "price")} for a in plan["appointments"]],
            "not_transferred": plan["not_transferred"], "next_steps": plan["next_steps"],
            "reminders": "paused"}


@router.post("/{business}/preview")
def preview(business: UUID, req: Review, user: AuthedUser = Depends(require_user)):
    biz = _owner(business, user)
    try:
        plan = migration.plan_files(req.clients_csv, req.appointments_csv,
            zone=req.timezone, date_order=req.date_order,
            mappings={k: str(v) for k, v in req.mappings.items()}, offerings=_offerings(business),
            active_only_confirmed=req.active_only_confirmed)
    except migration.MigrationError as exc:
        raise HTTPException(422, str(exc)) from exc
    for a in plan["appointments"]:
        # Ignore position and the changing clock when identifying re-imports.
        a["source_hash"] = migration.digest({k: a[k] for k in ("source_id", "source", "offering_id", "start", "duration")})
        a["action"] = "new"
    for p in plan["clients"]:
        p["action"] = "new"
    unsupported = {"uses_staff_calendars": "separate staff calendars", "uses_classes": "group classes",
                   "uses_subscriptions": "active recurring memberships", "has_prepaid_balances": "unused prepaid packages or gift balances"}
    for field, label in unsupported.items():
        if plan["inventory"]["appointment_rows"] and getattr(req, field):
            plan["issues"].append({"file": "readiness", "row": 0,
                "message": f"Your business uses {label}. This needs a migration review before a full switch; the first release does not transfer it."})
    capacity = ((biz.get("settings") or {}).get("availability") or {}).get("concurrent_capacity", 1)
    if plan["appointments"] and capacity != 1:
        plan["issues"].append({"file": "readiness", "row": 0, "message": "This import supports one provider with one appointment at a time."})
    _check_current(business, plan)
    plan["ready"] = not plan["issues"]
    batch = None
    if plan["ready"]:
        rows = sb_clients.sb_post_as_service("/acuity_migration_batches", {
            "business_id": str(business), "owner_id": str(user.id), "plan": plan})
        if not isinstance(rows, list) or not rows or not rows[0].get("id"):
            raise HTTPException(503, "The import review could not be saved. Nothing was imported; try again.")
        batch = rows[0]["id"]
    return _public_plan(plan, batch)


@router.post("/{business}/commit")
def commit(business: UUID, req: Commit, user: AuthedUser = Depends(require_user)):
    _owner(business, user)
    if not req.reviewed:
        raise HTTPException(422, "Review the preview and confirm the import first.")
    result = sb_clients.sb_post_as_service("/rpc/acuity_migration_commit", {
        "p_business": str(business), "p_owner": str(user.id), "p_batch": str(req.batch_id)})
    if not isinstance(result, dict) or not result.get("batch_id"):
        # A response can be lost after commit. Recover the durable receipt;
        # never tell the owner to create a second import blindly.
        rows = _rows(f"/acuity_migration_batches?id=eq.{req.batch_id}&business_id=eq.{business}&owner_id=eq.{user.id}&select=receipt,state&limit=1")
        if rows and rows[0].get("state") == "imported" and rows[0].get("receipt"):
            return rows[0]["receipt"]
        raise HTTPException(409, "The import was not completed. Your calendar or services may have changed. Review the files again before retrying.")
    return result


@router.get("/{business}/receipts")
def receipts(business: UUID, user: AuthedUser = Depends(require_user)):
    _owner(business, user)
    return {"receipts": _rows(f"/acuity_migration_batches?business_id=eq.{business}&state=eq.imported&select=receipt&order=imported_at.desc&limit=20")}


@router.post("/{business}/reminders")
def reminders(business: UUID, req: Reminders, user: AuthedUser = Depends(require_user)):
    _owner(business, user)
    if req.enabled and not req.cutover_confirmed:
        raise HTTPException(422, "Confirm that your booking flow is tested and duplicate Acuity reminders are turned off.")
    result = sb_clients.sb_post_as_service('/rpc/acuity_migration_reminders', {
        'p_business': str(business), 'p_owner': str(user.id), 'p_batch': str(req.batch_id), 'p_enabled': req.enabled})
    if not isinstance(result, dict) or not result.get('batch_id'):
        raise HTTPException(503, "I could not verify the reminder setting. Refresh the import receipt before trying again.")
    return result
