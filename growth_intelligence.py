"""Growth measurements shared by HTTP, Chief chat, voice and agent tools.

Pure calculations: money is cash collected from paid invoices, never booked
revenue. Attribution is a recorded relationship, never a causal claim.
"""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from zoneinfo import ZoneInfo


def stamp(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def money(value):
    try:
        n = Decimal(str(value or 0))
        return float(n.quantize(Decimal("0.01"))) if n.is_finite() else 0.0
    except Exception:
        return 0.0


def total(rows, key="total"):
    return money(sum((Decimal(str(r.get(key) or 0)) for r in rows), Decimal(0)))


def shift_month(d, count):
    year, month = divmod(d.year * 12 + d.month - 1 + count, 12)
    return d.replace(year=year, month=month + 1,
                     day=min(d.day, monthrange(year, month + 1)[1]))


def periods(period="mtd", comparison="previous", now=None, tz="UTC", start=None, end=None):
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "custom":
        lo = datetime.fromisoformat(start).replace(tzinfo=now.tzinfo)
        hi = min(datetime.fromisoformat(end).replace(tzinfo=now.tzinfo) + timedelta(days=1), now)
        if lo >= hi or (hi - lo).days > 730:
            raise ValueError("Choose a past or current range of no more than two years.")
    else:
        lo = {"mtd": midnight.replace(day=1),
              "qtd": midnight.replace(month=((now.month-1)//3)*3+1, day=1),
              "ytd": midnight.replace(month=1, day=1),
              "30d": midnight-timedelta(days=29),
              "90d": midnight-timedelta(days=89)}[period]
        hi = now
    months = {"mtd": -1, "qtd": -3, "ytd": -12}.get(period)
    prior_lo = shift_month(lo, -12) if comparison == "year" else shift_month(lo, months) if months else lo-(hi-lo)
    # Equal elapsed duration, capped at the next period boundary for short months.
    prior_hi = min(prior_lo+(hi-lo), lo) if comparison == "previous" else prior_lo+(hi-lo)
    return lo, hi, prior_lo, prior_hi


def inside(row, field, lo, hi):
    d = stamp(row.get(field))
    return bool(d and lo <= d < hi)


def percentage(n, d):
    return round(n / d * 100, 1) if d else None


def normalize_bookings(sessions, entries):
    """Use module booking truth where present; never count its session mirror twice."""
    by_id = {e['id']: e for e in entries}
    mirrors = {}
    result = []
    for session in sessions:
        marker = re.search(r'\[booking:([^\]]+)\]', session.get('notes') or '')
        if marker and marker[1] in by_id:
            mirrors[marker[1]] = session
        else:
            result.append(session)
    for entry in entries:
        d = entry.get('data') or {}
        mirrored = mirrors.get(entry['id'], {})
        raw_status = d.get('status') or ''
        status = raw_status if raw_status in ('scheduled','completed','cancelled','no_show') else mirrored.get('status', 'scheduled')
        if entry.get('status') in ('cancelled','archived','deleted') or raw_status == 'canceled':
            status = 'cancelled'
        result.append({'id':'booking:'+entry['id'], 'contact_id':d.get('contact_id') or mirrored.get('contact_id'),
                       'status':status, 'scheduled_for':entry.get('appointment_at') or d.get('appointment_at') or mirrored.get('scheduled_for'),
                       'duration_minutes':entry.get('duration_min_at_booking') or entry.get('duration_min') or d.get('duration_minutes') or mirrored.get('duration_minutes')})
    return result


def report(data, prefs, period="mtd", comparison="previous", now=None, start=None, end=None):
    from retention_metrics import eligible_paid_invoices, retention_health
    now = now or datetime.now(timezone.utc)
    tz = prefs.get("timezone", "UTC")
    lo, hi, prev_lo, prev_hi = periods(period, comparison, now, tz, start, end)
    currency = prefs.get("currency", "USD")
    invoices = eligible_paid_invoices(data.get("invoices", []), currency, now)
    invoices.sort(key=lambda i: (stamp(i["paid_at"]), i["id"]))
    first = {}
    payment_dates = defaultdict(list)
    for inv in invoices:
        if inv.get("contact_id"):
            first.setdefault(inv["contact_id"], stamp(inv["paid_at"]))
            payment_dates[inv["contact_id"]].append(stamp(inv["paid_at"]))
    contacts = {c["id"]: c for c in data.get("contacts", [])}
    current = [i for i in invoices if inside(i, "paid_at", lo, hi)]
    previous = [i for i in invoices if inside(i, "paid_at", prev_lo, prev_hi)]

    def summarize(rows, start_at):
        new = [i for i in rows if i.get("contact_id") and first[i["contact_id"]] >= start_at]
        returning = [i for i in rows if i.get("contact_id") and first[i["contact_id"]] < start_at]
        buyers = len({i["contact_id"] for i in returning})
        return {"collected": total(rows), "new_revenue": total(new), "returning_revenue": total(returning),
                "unlinked_revenue": total([i for i in rows if not i.get("contact_id")]),
                "buyers": len({i["contact_id"] for i in rows if i.get("contact_id")}),
                "new_buyers": len({i["contact_id"] for i in new}), "returning_buyers": buyers,
                "invoices": len(rows), "frequency": len(returning)/buyers if buyers else 0,
                "average": total(returning)/len(returning) if returning else 0,
                "average_purchase": money(total(rows)/len(rows)) if rows else None}

    cur, prev = summarize(current, lo), summarize(previous, prev_lo)
    # Sequential decomposition reconciles exactly, including zero baselines.
    drivers = [
        {"label": "First-time buyers", "value": money(cur["new_revenue"]-prev["new_revenue"])},
        {"label": "Returning buyers", "value": money((cur["returning_buyers"]-prev["returning_buyers"])*prev["frequency"]*prev["average"])},
        {"label": "Purchase frequency", "value": money(cur["returning_buyers"]*(cur["frequency"]-prev["frequency"])*prev["average"])},
        {"label": "Purchase value", "value": money(cur["returning_buyers"]*cur["frequency"]*(cur["average"]-prev["average"]))},
        {"label": "Unlinked invoices", "value": money(cur["unlinked_revenue"]-prev["unlinked_revenue"])},
    ]
    delta = money(cur["collected"]-prev["collected"])
    drivers[-1]["value"] = money(drivers[-1]["value"] + delta - sum(d["value"] for d in drivers))
    daily = []
    daily_totals = defaultdict(Decimal)
    for inv in current:
        daily_totals[stamp(inv["paid_at"]).astimezone(ZoneInfo(tz)).date()] += Decimal(str(inv.get("total") or 0))
    day = lo.replace(hour=0, minute=0, second=0, microsecond=0)
    cumulative = 0
    while day < hi:
        value = money(daily_totals[day.date()])
        cumulative = money(cumulative+value)
        daily.append({"date": day.date().isoformat(), "value": value, "cumulative": cumulative})
        day += timedelta(days=1)

    cohorts = []
    cohort_ids = defaultdict(list)
    for cid, date in first.items():
        cohort_ids[date.astimezone(ZoneInfo(tz)).strftime("%Y-%m")].append(cid)
    for month, ids in sorted(cohort_ids.items(), reverse=True)[:12]:
        cells = []
        for days in (30, 60, 90):
            eligible = [cid for cid in ids if first[cid]+timedelta(days=days) <= now]
            returned = sum(any(first[cid] < t <= first[cid]+timedelta(days=days) for t in payment_dates[cid][1:]) for cid in eligible)
            cells.append({"days": days, "eligible": len(eligible), "returned": returned, "rate": percentage(returned, len(eligible))})
        cohorts.append({"month": month, "buyers": len(ids), "cells": cells})

    last_date = (hi-timedelta(microseconds=1)).date().isoformat()
    costs = [r for r in data.get("costs", []) if not r.get("archived") and (r.get("currency") or currency) == currency
             and lo.date().isoformat() <= r["date"] <= last_date]
    channels = defaultdict(lambda: {"leads": 0, "new_buyers": set(), "buyers": set(), "revenue": 0, "repeat_buyers": set(), "spend": 0})
    def source(cid):
        return (contacts.get(cid, {}).get("source") or "Unknown").strip().casefold()
    for contact in contacts.values():
        if inside(contact, "created_at", lo, hi):
            channels[source(contact["id"])]["leads"] += 1
    for inv in current:
        cid = inv.get("contact_id")
        c = channels[source(cid)]
        c["revenue"] += money(inv.get("total"))
        if cid:
            c["buyers"].add(cid)
            c["new_buyers" if first[cid] >= lo else "repeat_buyers"].add(cid)
    for cost in costs:
        if cost["kind"] == "marketing":
            channels[(cost.get("source") or "Unknown").strip().casefold()]["spend"] += cost["amount"]
    channel_rows = []
    for name, c in channels.items():
        channel_rows.append({"source": name, **{k: len(v) if isinstance(v, set) else money(v) for k, v in c.items()},
                             "cost_per_new_buyer": money(c["spend"]/len(c["new_buyers"])) if c["spend"] and c["new_buyers"] else None})

    campaign_rows = []
    invoice_map = {i["id"]: i for i in current}
    for campaign in data.get("campaigns", []):
        credits = [r for r in data.get("attributions", []) if not r.get("archived") and r["campaign_id"] == campaign["id"] and r["invoice_id"] in invoice_map]
        attributed = [invoice_map[r["invoice_id"]] for r in credits]
        spend = total([r for r in costs if r.get("campaign_id") == campaign["id"] and r["kind"] == "marketing"], "amount")
        campaign_rows.append({"id": campaign["id"], "name": campaign["name"], "status": campaign["status"],
                              "credited_invoices": len(attributed), "credited_revenue": total(attributed), "spend": spend,
                              "return_on_spend": round(total(attributed)/spend, 2) if spend else None})

    profit = []
    for dimension in ("offering", "contact"):
        groups = defaultdict(lambda: {"revenue": 0, "cost": 0, "cost_records": 0, "hours": 0})
        for inv in current:
            key = (inv.get("category") or "Uncategorized") if dimension == "offering" else inv.get("contact_id") or "Unlinked"
            groups[key]["revenue"] += money(inv.get("total"))
        for cost in costs:
            key = cost.get("offering") if dimension == "offering" else cost.get("contact_id")
            if cost["kind"] == "direct" and key:
                groups[key]["cost"] += cost["amount"]
                groups[key]["hours"] += cost.get("hours", 0)
                groups[key]["cost_records"] += 1
        for key, row in groups.items():
            profit.append({"dimension": dimension, "key": key,
                           "name": contacts.get(key, {}).get("name", "Unlinked") if dimension == "contact" else key,
                           **{k: money(v) for k, v in row.items()},
                           "contribution": money(row["revenue"]-row["cost"]) if row["cost_records"] else None,
                           "margin": percentage(row["revenue"]-row["cost"], row["revenue"]) if row["cost_records"] else None,
                           "revenue_per_hour": money(row["revenue"]/row["hours"]) if row["hours"] else None})

    sessions = data.get("sessions", [])
    calendar_start = now.astimezone(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    upcoming = [s for s in sessions if inside(s, "scheduled_for", now, calendar_start+timedelta(days=14)) and s.get("status") == "scheduled"]
    booked_hours = sum(float(s.get("duration_minutes") or 0)/60 for s in upcoming)
    weekly = prefs.get("weekly_hours")
    completed = [s for s in sessions if inside(s, "scheduled_for", lo, hi) and s.get("status") == "completed"]
    elapsed = [s for s in sessions if inside(s, "scheduled_for", lo, hi)]
    eligible_people = {s.get("contact_id") for s in completed if s.get("contact_id")}
    first_completed = {}
    for session in completed:
        cid, date = session.get("contact_id"), stamp(session["scheduled_for"])
        if cid:
            first_completed[cid] = min(first_completed.get(cid, date), date)
    rebooked = len({s["contact_id"] for s in sessions if s.get("contact_id") in first_completed
                   and s.get("status") in ("scheduled", "completed") and stamp(s.get("scheduled_for"))
                   and stamp(s["scheduled_for"]) > first_completed[s["contact_id"]]})
    capacity = {"weekly_hours": weekly, "available_hours": weekly*2 if weekly is not None else None,
                "booked_hours": round(booked_hours, 1), "booked_count": len(upcoming),
                "open_hours": round(max(0, weekly*2-booked_hours), 1) if weekly is not None else None,
                "utilization": percentage(booked_hours, weekly*2) if weekly else None,
                "cancelled": sum(s.get("status") == "cancelled" for s in elapsed),
                "no_shows": sum(s.get("status") == "no_show" for s in elapsed),
                "cancellation_rate": percentage(sum(s.get("status") == "cancelled" for s in elapsed), len(elapsed)),
                "rebooking_rate": percentage(rebooked, len(eligible_people)), "completed_people": len(eligible_people),
                "missing_duration": sum(not s.get("duration_minutes") for s in upcoming),
                "days": [{"date": (now+timedelta(days=n)).astimezone(ZoneInfo(tz)).date().isoformat(),
                          "bookings": sum(stamp(s["scheduled_for"]).astimezone(ZoneInfo(tz)).date() == (now+timedelta(days=n)).astimezone(ZoneInfo(tz)).date() for s in upcoming)} for n in range(14)]}

    events = data.get("events", [])
    touched = lambda a, b: len({e["contact_id"] for e in events if e.get("contact_id") and e.get("kind") == "interaction" and inside(e, "occurred_at", a, b)})
    conversion_days = [(date-stamp(contacts[cid]["created_at"])).total_seconds()/86400 for cid, date in first.items()
                       if cid in contacts and stamp(contacts[cid].get("created_at")) and lo <= date < hi and date >= stamp(contacts[cid]["created_at"])]
    action_rows = []
    for action in data.get("actions", []):
        if action.get("archived"):
            continue
        a = datetime.fromisoformat(action["start_date"]).replace(tzinfo=ZoneInfo(tz))
        b = datetime.fromisoformat(action["due_date"]).replace(tzinfo=ZoneInfo(tz))+timedelta(days=1)
        ids = set(action.get("contact_ids") or [])
        action_currency = action.get("currency") or currency
        action_invoices = invoices if action_currency == currency else [i for i in data.get("invoices", [])
            if i.get("status") == "paid" and stamp(i.get("paid_at")) and stamp(i["paid_at"]) < now
            and (i.get("currency") or "USD").upper() == action_currency]
        def measurement(x, y):
            if action["metric"] == "revenue":
                return total([i for i in action_invoices if inside(i, "paid_at", x, y) and (not ids or i.get("contact_id") in ids)])
            if action["metric"] == "bookings":
                return sum(inside(s, "scheduled_for", x, y) and s.get("status") != "cancelled" and (not ids or s.get("contact_id") in ids) for s in sessions)
            return len({i["contact_id"] for i in invoices if i.get("contact_id") and inside(i, "paid_at", x, y) and (not ids or i["contact_id"] in ids)})
        value = measurement(a, min(b, now)) if a < now else 0
        baseline = measurement(a-(b-a), a)
        action_rows.append({**action, "currency": action_currency, "current": value, "baseline": baseline,
                            "progress": percentage(value, action["target"]), "change": money(value-baseline)})

    missing_paid_dates = sum(i.get("status") == "paid" and not stamp(i.get("paid_at")) for i in data.get("invoices", []))
    other_currency = sum(i.get("status") == "paid" and (i.get("currency") or "USD").upper() != currency for i in data.get("invoices", []))
    return {"currency": currency, "timezone": tz, "generated_at": now.isoformat(),
            "period": {"key": period, "comparison": comparison, "start": lo.isoformat(), "end": hi.isoformat(), "previous_start": prev_lo.isoformat(), "previous_end": prev_hi.isoformat()},
            "current": cur, "previous": prev, "change": delta, "change_pct": percentage(delta, prev["collected"]),
            "drivers": drivers, "daily": daily, "cohorts": cohorts,
            "retention_health": retention_health(data.get("contacts", []), invoices, now),
            "channels": sorted(channel_rows, key=lambda r: -r["revenue"]), "campaigns": campaign_rows,
            "profitability": sorted(profit, key=lambda r: -r["revenue"]), "costs": costs,
            "overhead": total([c for c in costs if c["kind"] == "overhead"], "amount"), "capacity": capacity,
            "actions": action_rows, "attributions": data.get("attributions", []),
            "engagement": {"current": touched(lo, hi), "previous": touched(prev_lo, prev_hi), "history_since": prefs.get("history_since"),
                           "current_complete": bool(stamp(prefs.get("history_since")) and stamp(prefs["history_since"]) <= lo),
                           "previous_complete": bool(stamp(prefs.get("history_since")) and stamp(prefs["history_since"]) <= prev_lo)},
            "conversion": {"average_days_to_first_payment": round(sum(conversion_days)/len(conversion_days), 1) if conversion_days else None, "samples": len(conversion_days)},
            "quality": {"missing_payment_dates": missing_paid_dates, "other_currency_invoices": other_currency,
                        "unlinked_collections": cur["unlinked_revenue"], "warnings": data.get("warnings", [])},
            "choices": {"contacts": sorted([{"id": c["id"], "name": c.get("name") or "Unnamed"} for c in contacts.values()], key=lambda c: c["name"].casefold()),
                        "invoices": [{"id": i["id"], "label": f"{contacts.get(i.get('contact_id'), {}).get('name', 'Unlinked')} · {money(i.get('total'))} · {i['paid_at'][:10]}"} for i in current],
                        "offerings": sorted({i.get("category") or "Uncategorized" for i in invoices})}}
