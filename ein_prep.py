"""
ein_prep.py — everything the IRS will ask for an EIN, answered from the
records the practitioner already gave us, BEFORE they open the IRS site.

WHY THIS AND NOT "FILE IT FOR THEM"
There is no IRS API for EINs. The only online channel is the IRS's own web
application, which the responsible party (or someone they have signed an
authorization for) completes. It is free, it issues the number on the spot,
and it times out after 15 idle minutes — so the real friction is not the
form, it is sitting down without the answers to hand. This lays the answers
out in the order the application asks, marks which ones came from their
records and which only they can give, and offers the official SS-4 prefilled
for anyone who has to fax or mail instead.

WHAT IT NEVER DOES
  • Ask for, hold or display an SSN or ITIN. The owner types it into the IRS
    site directly; the line says so.
  • Decide anything the IRS form treats as a determination: how an LLC is
    taxed, the reason for applying, the accounting year, employee counts.
    Those rows say "you'll choose this" and why, never a pre-picked answer.
  • Submit anything. Every path ends with the owner on irs.gov or holding an
    unsigned form.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("ein_prep")

IRS_APPLY_URL = ("https://www.irs.gov/businesses/small-businesses-self-employed/"
                 "apply-for-an-employer-identification-number-ein-online")

RECORDS, YOU = "records", "you"

_ENTITY_LABEL = {
    "sole_prop": "Sole proprietor",
    "single_member_llc": "Limited liability company (LLC), one member",
    "multi_member_llc": "Limited liability company (LLC), more than one member",
    "partnership": "Partnership",
    "s_corp": "S corporation",
    "c_corp": "Corporation",
    "nonprofit": "Nonprofit organization",
}

_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "Washington, D.C.",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _row(key: str, question: str, answer: Optional[str], note: str = "",
         source: Optional[str] = None) -> Dict[str, Any]:
    has = bool(answer and str(answer).strip())
    return {
        "key": key,
        "question": question,
        "answer": str(answer).strip() if has else None,
        "source": source or (RECORDS if has else YOU),
        "note": note,
    }


def _get(path: str) -> List[Dict[str, Any]]:
    try:
        rows = sb_clients.sb_get_as_service(path)
        return rows if isinstance(rows, list) else []
    except Exception as e:
        logger.warning(f"[ein_prep] read failed ({path.split('?')[0]}): {e}")
        return []


def load_inputs(business_id: str) -> Dict[str, Any]:
    """The three records the prep and the SS-4 are built from."""
    import business_identity
    biz = (_get(f"/businesses?id=eq.{business_id}&select=id,name,owner_id&limit=1") or [{}])[0]
    identity = business_identity.get_identity(business_id, biz) if biz else {}
    owner = biz.get("owner_id")
    pp = (_get(f"/practitioner_profiles?owner_id=eq.{owner}&limit=1") or [{}])[0] if owner else {}
    bp = (_get(f"/business_profiles?business_id=eq.{business_id}"
               "&select=business_subtype,deliverables_description&limit=1") or [{}])[0]
    return {"business": biz, "identity": identity, "practitioner": pp, "profile": bp}


def prep_for(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """The questions, in the order the IRS online application asks them."""
    biz = inputs.get("business") or {}
    ident = inputs.get("identity") or {}
    pp = inputs.get("practitioner") or {}
    bp = inputs.get("profile") or {}

    et = (ident.get("entity_type") or "").strip().lower()
    is_llc = et in ("single_member_llc", "multi_member_llc")
    formed = (ident.get("formation_state") or "").strip().upper()
    legal_is_real = bool(ident.get("legal_name")) and not ident.get("legal_name_is_fallback")
    display = (biz.get("name") or "").strip()

    addr_bits = [ident.get("address_line1"), ident.get("address_line2")]
    addr = " ".join(str(b).strip() for b in addr_bits if b and str(b).strip())
    city = ", ".join(p for p in [(ident.get("address_city") or "").strip(),
                                 (ident.get("address_state") or "").strip()] if p)
    full_addr = ", ".join(p for p in [addr, " ".join(p for p in [city, (ident.get("address_zip") or "").strip()] if p)] if p)

    items: List[Dict[str, Any]] = [
        _row("entity", "What type of business is this?", _ENTITY_LABEL.get(et),
             "From Legal & tax. The IRS asks this first; if yours is not on file, "
             "finish the entity step before you apply."),
    ]
    if is_llc:
        items.append(_row(
            "llc_members", "How many members does the LLC have?",
            "1" if et == "single_member_llc" else None,
            "Count everyone who owns part of the LLC."))
        items.append(_row(
            "llc_tax", "How should the IRS treat the LLC for tax?", None,
            "The IRS asks this for LLCs. It is a tax choice, so it is yours, "
            "ideally with your accountant; we never pick it."))
    items += [
        _row("formation_state", "Which state was the business formed in?",
             _STATE_NAMES.get(formed, formed or None)),
        _row("reason", "Why are you applying?", None,
             "Most first-time applicants choose \"Started a new business\". "
             "Pick whatever is true for you."),
        _row("responsible_name", "Who is the responsible party?",
             (pp.get("full_legal_name") or "").strip() or None,
             "The person who owns or controls the business."),
        _row("responsible_ssn", "Their Social Security number or ITIN", None,
             "Type it straight into the IRS site. Solutionist never asks for it "
             "and never stores it."),
        _row("legal_name", "Legal name of the business",
             ident.get("legal_name") if legal_is_real else None,
             "Exactly as it appears on your formation paperwork."),
    ]
    if legal_is_real and display and display.lower() != str(ident.get("legal_name")).strip().lower():
        items.append(_row("trade_name", "Trade name (if different)", display))
    items += [
        _row("address", "Business mailing address", full_addr or None),
        _row("phone", "Business phone", ident.get("phone")),
        _row("county", "County where the business is located", None),
        _row("started", "Date the business started", _pretty_date(ident.get("formed_on"))),
        _row("closing_month", "Closing month of your accounting year", None,
             "December for a business that runs on the calendar year. Your "
             "accountant can confirm."),
        _row("employees", "Employees you expect in the next 12 months", None,
             "Enter 0 if you will not have any."),
        _row("activity", "What the business does",
             (bp.get("business_subtype") or bp.get("deliverables_description") or "").strip() or None,
             "The IRS asks for a category and a short description."),
    ]

    from_records = sum(1 for i in items if i["source"] == RECORDS)
    return {
        "ok": True,
        "items": items,
        "from_records": from_records,
        "total": len(items),
        "ein_on_file": bool((ident.get("ein") or "").strip()),
        "apply_url": IRS_APPLY_URL,
        "facts": [
            "The IRS issues the EIN free, on the spot, when the application is approved.",
            "The session ends after 15 minutes without activity, so have these answers open.",
            "One EIN per responsible party per day.",
            "Save the confirmation letter the IRS shows at the end.",
        ],
    }


def _pretty_date(iso: Any) -> Optional[str]:
    from datetime import date
    try:
        d = date.fromisoformat(str(iso or "").strip()[:10])
    except ValueError:
        return None
    return f"{d.strftime('%B')} {d.day}, {d.year}"
