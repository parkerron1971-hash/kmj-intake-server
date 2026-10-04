"""Acuity CSV migration planning. Pure, bounded, and deliberately model-free.

This release handles one provider's clients and individual appointments. A file
is evidence, never instructions. Dates, service mappings and cancellation state
must be explicit; unfamiliar columns survive in the imported source record.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_ROWS = 500
MAX_BYTES = 2_000_000
VERSION = 1


class MigrationError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def key(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def read_csv(text):
    if not text or not text.strip():
        return [], []
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise MigrationError("Each file must be smaller than 2 MB.")
    if "\x00" in text:
        raise MigrationError("Use a CSV export, not an Excel workbook.")
    try:
        reader = csv.reader(io.StringIO(text.lstrip("\ufeff")), strict=True)
        headers = [h.strip() for h in next(reader)]
        normalized = [key(h) for h in headers]
        if not headers or len(headers) > 100 or any(not h for h in normalized):
            raise MigrationError("The file needs a named header for every column (up to 100).")
        if len(set(normalized)) != len(normalized):
            raise MigrationError("The file has duplicate column names. Rename them before importing.")
        rows = []
        for values in reader:
            if not any(v.strip() for v in values):
                continue
            if len(values) != len(headers):
                raise MigrationError(f"CSV row {reader.line_num} has a different number of columns.")
            if any(len(v) > 10000 for v in values):
                raise MigrationError(f"CSV row {reader.line_num} has a field over 10,000 characters.")
            rows.append(dict(zip(headers, [v.strip() for v in values])))
            if len(rows) > MAX_ROWS:
                raise MigrationError("Import up to 500 rows per file; split larger exports first.")
        return headers, rows
    except (csv.Error, StopIteration) as exc:
        raise MigrationError("This file could not be read as a CSV with column headers.") from exc


def field(row, *aliases):
    data = {key(k): v for k, v in row.items()}
    for alias in aliases:
        if key(alias) in data:
            return data[key(alias)]
    return ""


def email(value):
    value = value.strip().lower()
    if len(value) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise MigrationError("A valid client email is required to match this record safely.")
    return value


def person(row):
    name = (field(row, "Name", "Client name") or " ".join(filter(None, [
        field(row, "First Name", "Client First Name"),
        field(row, "Last Name", "Client Last Name")]))).strip()
    if not name or len(name) > 200:
        raise MigrationError("A client name of up to 200 characters is required.")
    return {"name": name, "email": email(field(row, "Email", "Email Address", "Client Email")),
            "phone": field(row, "Phone", "Phone Number", "Client Phone")[:80],
            "source": row}


def timestamp(raw, zone, date_order):
    raw = raw.strip()
    if not raw:
        raise MigrationError("Appointment start and end times are required.")
    if not re.search(r"\d{1,2}:\d{2}", raw):
        raise MigrationError("Use a complete appointment date/time, including the time of day.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        dates = ["%m/%d/%Y", "%m/%d/%y"] if date_order == "month_first" else ["%d/%m/%Y", "%d/%m/%y"]
        for fmt in [d + " " + t for d in dates for t in ("%I:%M%p", "%I:%M %p", "%H:%M", "%H:%M:%S")]:
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            raise MigrationError("Use an ISO date/time or a numeric date and time matching the selected date format.")
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise MigrationError("Choose a valid time zone such as America/New_York.")
    candidates = {parsed.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
                  for fold in (0, 1)
                  if parsed.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == parsed}
    if len(candidates) != 1:
        raise MigrationError("This time is ambiguous or missing during a daylight-saving change. Include its UTC offset.")
    return candidates.pop()


def money(raw):
    if not raw:
        return None
    # Currency symbols and grouping separators are not guessed.
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        raise MigrationError("Prices must use a plain number such as 75.00.")
    try:
        amount = Decimal(raw)
        if not amount.is_finite() or amount > 1000000:
            raise InvalidOperation
        return str(amount.quantize(Decimal(".01")))
    except InvalidOperation:
        raise MigrationError("The price is outside the supported range.")


def inspect_files(clients_csv, appointments_csv):
    _, clients = read_csv(clients_csv)
    _, appointments = read_csv(appointments_csv)
    if not clients and not appointments:
        raise MigrationError("Choose a client export or appointment export first.")
    return {"client_rows": len(clients), "appointment_rows": len(appointments),
            "services": sorted({field(r, "Appointment Type", "Type") for r in appointments}),
            "calendars": sorted({field(r, "Calendar") for r in appointments}),
            "timezones": sorted({field(r, "Time Zone", "Timezone") for r in appointments if field(r, "Time Zone", "Timezone")})}


def plan_files(clients_csv, appointments_csv, *, zone, date_order, mappings,
               offerings, active_only_confirmed, now=None):
    now = now or datetime.now(timezone.utc)
    if date_order not in ("month_first", "day_first"):
        raise MigrationError("Choose the date format used by your export.")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise MigrationError("Choose a valid time zone such as America/New_York.")
    inventory = inspect_files(clients_csv, appointments_csv)
    _, client_rows = read_csv(clients_csv)
    _, appt_rows = read_csv(appointments_csv)
    clients, appointments, issues, seen = {}, [], [], set()
    if len(inventory["calendars"]) > 1:
        issues.append({"file": "appointments", "row": 0, "message": "This release supports one Acuity calendar. Separate staff calendars need a migration review."})
    if appt_rows and not active_only_confirmed:
        issues.append({"file": "appointments", "row": 0, "message": "Export appointments with canceled appointments excluded, then confirm that choice."})
    for index, row in enumerate(client_rows, 2):
        try:
            p = person(row)
            if p["email"] in clients and clients[p["email"]] != p:
                raise MigrationError("This email appears on different client records; resolve it before importing.")
            clients[p["email"]] = p
        except MigrationError as exc:
            issues.append({"file": "clients", "row": index, "message": str(exc)})
    active_offerings = {str(o["id"]): o for o in offerings if o.get("is_active")}
    for index, row in enumerate(appt_rows, 2):
        try:
            p = person(row)
            aid = field(row, "Appointment ID", "ID")
            if not re.fullmatch(r"\d{1,24}", aid):
                raise MigrationError("An Acuity Appointment ID is required for duplicate protection.")
            if aid in seen:
                raise MigrationError("This Appointment ID appears more than once in the file.")
            seen.add(aid)
            state = field(row, "Canceled", "Cancelled", "Status").lower()
            if state and state not in ("false", "no", "0", "scheduled", "confirmed", "active"):
                raise MigrationError("Canceled or uncertain appointment status: exclude this appointment from the export.")
            appt_zone = field(row, "Time Zone", "Timezone") or zone
            start = timestamp(field(row, "Start Time", "Start Time and Date", "Start", "Date Time"), appt_zone, date_order)
            end = timestamp(field(row, "End Time", "End Time and Date", "End"), appt_zone, date_order)
            seconds = (end - start).total_seconds()
            if seconds <= 0 or seconds > 24 * 3600 or seconds % 60:
                raise MigrationError("An appointment must last a whole number of minutes, from 1 minute to 24 hours.")
            service = field(row, "Appointment Type", "Type")
            offering_id = mappings.get(service)
            if offering_id not in active_offerings:
                raise MigrationError(f"Match the Acuity service '{service[:100]}' to an active Solutionist service.")
            price = money(field(row, "Price"))
            paid_online = money(field(row, "Amount Paid Online", "Amount Paid"))
            paid = field(row, "Paid", "Is Paid").lower()
            if paid and paid not in ("yes", "no", "true", "false", "1", "0"):
                raise MigrationError("The payment status is not recognized. Use yes or no.")
            clients.setdefault(p["email"], p)
            appointments.append({"source_id": aid, "row": index,
                "email": p["email"], "name": p["name"], "offering_id": offering_id,
                "service": service, "start": start.isoformat().replace("+00:00", "Z"),
                "duration": int(seconds // 60), "historical": end <= now,
                "price": price, "paid_online": paid_online,
                "paid": True if paid in ("yes", "true", "1") else False if paid else None,
                "source": row})
        except MigrationError as exc:
            issues.append({"file": "appointments", "row": index, "message": str(exc)})
    future = sorted([a for a in appointments if not a["historical"]], key=lambda a: a["start"])
    for i, a in enumerate(future):
        start = datetime.fromisoformat(a["start"].replace("Z", "+00:00"))
        for b in future[:i]:
            other = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            if (start - other).total_seconds() < b["duration"] * 60:
                issues.append({"file": "appointments", "row": a["row"], "message": f"Overlaps appointment {b['source_id']}; this release supports individual appointments."})
                break
    return {"version": VERSION, "inventory": inventory, "clients": list(clients.values()),
            "appointments": appointments, "issues": issues, "timezone": zone,
            "reminders": "paused", "ready": not issues,
            "not_transferred": ["Saved payment methods and recurring charges", "Package or gift balances and redemption codes", "Acuity forms, automations, staff calendars and booking links"],
            "next_steps": ["Reconcile prepaid balances and active subscriptions before switching.",
                           "Test your Solutionist booking link, payments, rescheduling and cancellation.",
                           "Change your public booking links and turn off duplicate Acuity reminders when ready."]}
