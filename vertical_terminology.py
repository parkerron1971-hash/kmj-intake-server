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
    # F.2 v1 — bookkeeping noun layer. Generic across verticals today.
    "transaction":  "Transaction",
    "transactions": "Transactions",
    "expense":      "Expense",
    "expenses":     "Expenses",
    "bank":         "Bank",
    # C.1.4 v1.5 (Category E) — vertical-ledger language surfaced by
    # I.7/I.10: trust accounts (lawyer) + restricted funds (nonprofit).
    "donor":          "Customer",
    "donors":         "Customers",
    "donation":       "Payment",
    "donations":      "Payments",
    "trust_account":  "Bank account",
    "trust_deposit":  "Deposit",
    "trust_disbursement": "Withdrawal",
    "restricted_fund":    "Reserved funds",
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
        # A lawyer doesn't run "sessions" — every scheduled sit-down is a
        # consultation ("Schedule Session" read wrong on the lawyer surface).
        "session":      "Consultation",
        "sessions":     "Consultations",
        # invoice → keep "Invoice" per F3 ambiguity ruling (Lawyer Invoice over Bill)
        # I.7/I.10 — trust-account language.
        "trust_account":      "Trust account (IOLTA)",
        "trust_deposit":      "Client trust deposit",
        "trust_disbursement": "Trust disbursement",
    },
    # Category E — nonprofit language (I.10 donor/restricted surfaces).
    "nonprofit": {
        "customer":     "Donor",
        "customers":    "Donors",
        "contact":      "Donor",
        "contacts":     "Donors",
        "donor":        "Donor",
        "donors":       "Donors",
        "donation":     "Gift",
        "donations":    "Gifts",
        "service":      "Program",
        "services":     "Programs",
        "offering":     "Program",
        "offerings":    "Programs",
        "restricted_fund": "Restricted fund",
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
        # Same word for the session noun — a pastor holds meetings,
        # not "sessions".
        "session":      "Meeting",
        "sessions":     "Meetings",
        "member":       "Member",
        # Giving language — a church says "givers/giving", not
        # "donors/donations" (nonprofit) or "customers" (BASE).
        "donor":            "Giver",
        "donors":           "Givers",
        "donation":         "Gift",
        "donations":        "Giving",
        "restricted_fund":  "Designated fund",
    },
    "personal_services": {
        # Barbers, salons, lash/brow, esthetics, massage, tattoo.
        #
        # The person in the chair is a CLIENT. A previous pass tried
        # "Guest" on a hospitality argument; Kevin overruled it (8/18) —
        # barbers and stylists say "my clients" out loud, "Guest" is hotel
        # language. A shop that wants Guests can rename it per-business in
        # Settings → Terminology.
        "customer":     "Client",
        "customers":    "Clients",
        "contact":      "Client",
        "contacts":     "Clients",
        # The menu on the wall is a list of Services, and what a client picks
        # from it is a Service — not an "Offering", which is retail language
        # this trade does not use.
        "offering":     "Service",
        "offerings":    "Services",
        # appointment / booking deliberately stay BASE. A barber genuinely
        # says "appointment" and "booking"; overriding them would be change
        # for its own sake.
        #
        # But nobody in the chair has a "session" — the session noun maps
        # to the same word the trade already uses: Appointment.
        "session":      "Appointment",
        "sessions":     "Appointments",
    },
    "contractor": {
        # Trades — plumbing, electrical, HVAC, roofing, remodel, landscape.
        #
        # 'customer' deliberately stays BASE. This is the one vertical where
        # the generic noun is already the right one: a contractor says
        # Customer, not Client and not Guest. Overriding it would be change
        # for its own sake. The CONTACT noun, however, must not leak the
        # generic "Contact" — the people register is Customers.
        "contact":      "Customer",
        "contacts":     "Customers",
        #
        # What DOES need its own word is the unit of work. A contractor does
        # not book a "service" or run an "engagement" — they run a JOB, at a
        # site, with a start and an end.
        "service":      "Job",
        "services":     "Jobs",
        # The price list they quote from is still Services — that is the
        # menu, distinct from the Job that gets scheduled off it.
        "offering":     "Service",
        "offerings":    "Services",
        # Dispatch language. Nobody in the trades has an "appointment" —
        # they have a visit, a call-out, or a window.
        "appointment":  "Visit",
        "appointments": "Visits",
        "booking":      "Visit",
        "bookings":     "Visits",
        "session":      "Visit",
        "sessions":     "Visits",
    },
    "therapist": {
        # Private practice mental health. Deliberately plain: a therapist
        # says Client and Session, and the platform's job here is scheduling
        # and billing, not clinical language it has no business holding.
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
    "service_provider": {
        # Intentionally generic baseline.
    },
    "custom": {
        # Explicit generic fallback for self-described custom businesses.
    },
    # Path C Phase 2 — coaching is the legacy alias of coach. Same
    # overrides as the coach key so a business stamped 'coaching'
    # resolves to identical vocabulary. Keep in lockstep with the
    # 'coach' block above.
    "coaching": {
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
