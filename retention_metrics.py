"""Shared retention definitions for Growth reporting and Chief context.

These are observations, never contact-status mutations. Lapsed takes precedence
over at-risk. Missing health/history remains unknown rather than a healthy zero.
"""
from datetime import datetime, timezone
from math import isfinite
from decimal import Decimal


DEFINITIONS = {
    "at_risk": "Not lapsed, and health below 40 or no recorded contact for 30 or more days.",
    "lapsed": "Status inactive/churned, or no recorded contact for 60 or more days.",
    "history": "For someone never contacted, elapsed days start at contact creation. Missing dates remain unknown.",
    "repeat_rate": "All-time share of buyers with at least two paid invoices with valid past payment dates, in the reporting currency. This is not the 30/60/90-day cohort rate.",
}


def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (TypeError, ValueError):
        return None


def classify_contact(contact, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        score = float(contact.get("health_score"))
        score = score if isfinite(score) and 0 <= score <= 100 else None
    except (TypeError, ValueError):
        score = None
    touched = timestamp(contact.get("last_interaction"))
    since = touched or timestamp(contact.get("created_at"))
    days = max(0, (now - since).days) if since and since <= now else None
    status = contact.get("status") or "active"
    reasons = []
    if status in ("inactive", "churned"):
        reasons.append("Marked " + status)
    if days is not None and days >= 30:
        reasons.append(f"{days} days " + ("since last contact" if touched else "without a first contact"))
    if score is not None and score < 40:
        reasons.append(f"Health {score:g} / 100")
    bucket = "lapsed" if status in ("inactive", "churned") or (days is not None and days >= 60) else (
        "at_risk" if (score is not None and score < 40) or (days is not None and days >= 30) else "current")
    return {"id": contact["id"], "name": contact.get("name") or "Unnamed contact", "status": status,
            "health_score": score, "days_since_touch": days, "never_contacted": touched is None,
            "classification": bucket, "reasons": reasons}


def risk_sort(row):
    return (row["health_score"] if row["health_score"] is not None else 101,
            -(row["days_since_touch"] or 0), row["id"])


def eligible_paid_invoices(invoices, currency, now):
    return [i for i in invoices if i.get("status") == "paid" and timestamp(i.get("paid_at"))
            and timestamp(i["paid_at"]) < now and (i.get("currency") or "USD").upper() == currency]


def retention_health(contacts, paid_invoices, now):
    people = {c["id"]: classify_contact(c, now) for c in contacts}
    buyers = {}
    for invoice in paid_invoices:
        cid = invoice.get("contact_id")
        if not cid:
            continue
        row = buyers.setdefault(cid, {"id": cid, "name": people.get(cid, {}).get("name", "Former contact"),
                                      "collected": Decimal(0), "paid_invoices": 0, "can_contact": cid in people})
        row["collected"] += Decimal(str(invoice.get("total") or 0))
        row["paid_invoices"] += 1
    for row in buyers.values():
        row["collected"] = float(round(row["collected"], 2))
    rows = [{**person, "collected": buyers.get(cid, {}).get("collected", 0),
             "paid_invoices": buyers.get(cid, {}).get("paid_invoices", 0)} for cid, person in people.items()]
    at_risk = sorted([r for r in rows if r["classification"] == "at_risk"], key=risk_sort)
    lapsed = sorted([r for r in rows if r["classification"] == "lapsed"], key=lambda r: (-r["collected"], r["id"]))
    repeaters = sum(row["paid_invoices"] >= 2 for row in buyers.values())
    return {"total_contacts": len(rows), "current_count": len(rows)-len(lapsed),
            "at_risk_count": len(at_risk), "lapsed_count": len(lapsed),
            "unknown_health_count": sum(r["health_score"] is None for r in rows),
            "unknown_history_count": sum(r["days_since_touch"] is None for r in rows),
            "buyers": len(buyers), "repeat_buyers": repeaters,
            "repeat_rate": round(100*repeaters/len(buyers), 1) if buyers else None,
            "at_risk": at_risk, "lapsed": lapsed,
            "best_clients": sorted(buyers.values(), key=lambda r: (-r["collected"], r["id"])),
            "definitions": DEFINITIONS}
