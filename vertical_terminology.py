"""
vertical_terminology.py — Phase C.1.4 v1.

Server-side mirror of solutionist-studio's
src/core/terminology/dictionary.ts. Same shape, same content; kept in
lockstep manually for v1 (future enhancement: shared JSON source of
truth). Used by booking_confirmation_emails and any backend module
that ships practitioner-facing or customer-facing copy.

Lookup: vertical[k] OR BASE[k]. Generic fallback when the vertical
isn't in the override map (F6 ruling).
"""
from __future__ import annotations

from typing import Dict, Optional


# Canonical generic terminology. Every key here is also the API
# every UI surface uses to ask "what should I call this term?"
BASE_TERMS: Dict[str, str] = {
    "customer":     "Customer",
    "customers":    "Customers",
    "client":       "Client",
    "clients":      "Clients",
    # VABI v1.5 — 'contact' is the load-bearing CTS noun (ContactsList
    # navigation, ContactDetail columns, "Add contact" CTA, etc.).
    # Defaults to 'Contact' generic; verticals can override (lawyer →
    # 'Client', ministry → 'Member', personal_services keeps 'Contact').
    "contact":      "Contact",
    "contacts":     "Contacts",
    "service":      "Service",
    "services":     "Services",
    "appointment":  "Appointment",
    "appointments": "Appointments",
    "booking":      "Booking",
    "bookings":     "Bookings",
    "invoice":      "Invoice",
    "invoices":     "Invoices",
    "schedule":     "Schedule",
    "offering":     "Offering",
    "offerings":    "Offerings",
    "session":      "Session",
    "sessions":     "Sessions",
    "payment":      "Payment",
    "refund":       "Refund",
    "bill":         "Invoice",   # 'bill' alias resolves to Invoice by default
    "member":       "Member",
    # VABI v1.5 — used by GROW dashboards + Chief.
    "lead":         "Lead",
    "leads":        "Leads",
    "prospect":     "Prospect",
    "prospects":    "Prospects",
}


# Per-vertical overrides. Only declare what differs from BASE_TERMS.
# Lookup chain: VERTICAL_TERMS[business_type].get(k) or BASE_TERMS.get(k).
VERTICAL_TERMS: Dict[str, Dict[str, str]] = {
    # F4 — new lawyer archetype (mirrors the SQL seed row).
    "lawyer": {
        "customer":     "Client",
        "customers":    "Clients",
        "contact":      "Client",
        "contacts":     "Clients",
        "service":      "Matter",
        "services":     "Matters",
        "appointment":  "Consultation",
        "appointments": "Consultations",
        "booking":      "Consultation",
        "bookings":     "Consultations",
        # invoice → keep "Invoice" per F3 ambiguity ruling (Lawyer Invoice over Bill)
    },
    "coach": {
        "customer":     "Client",
        "customers":    "Clients",
        "contact":      "Client",
        "contacts":     "Clients",
        "service":      "Session",
        "services":     "Sessions",
        "appointment":  "Session",
        "appointments": "Sessions",
        "booking":      "Session",
        "bookings":     "Sessions",
        "offering":     "Package",
        "offerings":    "Packages",
    },
    "consultant": {
        "customer":     "Client",
        "customers":    "Clients",
        "contact":      "Client",
        "contacts":     "Clients",
        "service":      "Engagement",
        "services":     "Engagements",
        "appointment":  "Meeting",
        "appointments": "Meetings",
        "booking":      "Meeting",
        "bookings":     "Meetings",
    },
    "course_creator": {
        "customer":     "Student",
        "customers":    "Students",
        "contact":      "Student",
        "contacts":     "Students",
        "service":      "Course",
        "services":     "Courses",
        "appointment":  "Class",
        "appointments": "Classes",
        "booking":      "Class",
        "bookings":     "Classes",
        "session":      "Class",
        "sessions":     "Classes",
    },
    "creative": {
        "customer":     "Client",
        "customers":    "Clients",
        "contact":      "Client",
        "contacts":     "Clients",
        "service":      "Project",
        "services":     "Projects",
        "appointment":  "Meeting",
        "appointments": "Meetings",
        "booking":      "Meeting",
        "bookings":     "Meetings",
    },
    "financial_educator": {
        "customer":     "Client",
        "customers":    "Clients",
        "contact":      "Client",
        "contacts":     "Clients",
        "service":      "Program",
        "services":     "Programs",
        "appointment":  "Consultation",
        "appointments": "Consultations",
    },
    "fitness_wellness": {
        # F3 ruling — customer → Client for v1 (defer Patient distinction to v1.5)
        "customer":     "Client",
        "customers":    "Clients",
        "contact":      "Client",
        "contacts":     "Clients",
        "service":      "Session",
        "services":     "Sessions",
        "appointment":  "Session",
        "appointments": "Sessions",
        "booking":      "Session",
        "bookings":     "Sessions",
    },
    "ministry": {
        "customer":     "Member",
        "customers":    "Members",
        "contact":      "Member",
        "contacts":     "Members",
        # F3 ruling — service → "Ministry" to disambiguate from worship service
        "service":      "Ministry",
        "services":     "Ministries",
        "appointment":  "Meeting",
        "appointments": "Meetings",
        "booking":      "Meeting",
        "bookings":     "Meetings",
        "member":       "Member",
    },
    "personal_services": {
        # Closest-to-generic vertical (barbers, salons). Keep BASE as-is.
    },
    "service_provider": {
        # Intentionally generic baseline.
    },
    "custom": {
        # Explicit generic fallback for self-described custom businesses.
    },
}


def get_term(business_type: Optional[str], key: str) -> str:
    """Resolve a terminology key for a given vertical.

    business_type: the businesses.type value (None / unknown ok).
    key: a BASE_TERMS key. Unknown keys return the key itself
         (defensive — caller bug, not data bug).

    Falls back through:
      VERTICAL_TERMS[business_type].get(key)  →
      BASE_TERMS.get(key)                     →
      key                                     (defensive)
    """
    if not key:
        return ""
    bt = (business_type or "").lower().strip()
    vertical = VERTICAL_TERMS.get(bt) or {}
    return vertical.get(key) or BASE_TERMS.get(key) or key


def apply_substitutions(template: str, business_type: Optional[str]) -> str:
    """Post-hoc token substitution for static templates (F9 γ ruling).

    Replaces `{term:<key>}` tokens with the vertical-aware term, e.g.
    `{term:appointment}` → "Consultation" for lawyer / "Appointment"
    for personal_services. Unknown keys pass through unchanged.
    Tolerant to None / no-token inputs."""
    if not template or "{term:" not in template:
        return template or ""
    out = template
    # Cheap manual parse — avoids regex import + handles nested braces
    # never appearing in TEXT-class content.
    while True:
        i = out.find("{term:")
        if i < 0:
            break
        j = out.find("}", i + 6)
        if j < 0:
            break
        key = out[i + 6:j].strip()
        replacement = get_term(business_type, key)
        out = out[:i] + replacement + out[j + 1:]
    return out
