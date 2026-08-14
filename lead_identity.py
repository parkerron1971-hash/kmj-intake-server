"""
lead_identity.py — one answer to "is this the same person?"

THE DEFECT
═══════════════════════════════════════════════════════════════════════
Four public lead doors, four different answers:

  /intake/submit          NO DEDUPE AT ALL. Every submission created a
                          fresh contact. The same person enquiring
                          twice became two leads, two AI scoring calls
                          and two drafted replies.
  /sites/…/contact-submit email ilike (LIKE wildcards escaped) OR
                          normalized phone. The most complete of the
                          four.
  /concierge/…/lead       email ilike only. A visitor who left a phone
                          number and no email always became a new row.
  booking widget          email=eq — CASE SENSITIVE at the database.
                          A contact stored as Dana@x.com is invisible
                          to a booking for dana@x.com, so the booking
                          creates a second contact for the same person.

This module is the one rule, and every door calls it.

WHY THERE IS NO UNIQUE INDEX BEHIND IT
═══════════════════════════════════════════════════════════════════════
The obvious backstop is UNIQUE (business_id, lower(email)). Production
says no, and not merely because duplicates exist today: one of the two
clusters is `Rev. Marcus Williams` and `Sister Williams` — two DIFFERENT
people at one household address, in one church's contact list.

A shared email is a legitimate state for a church, a family business, a
couple. A database constraint would make the second person unable to
exist, and would surface as a 500 on a form submission with no
explanation. Application-level resolution can weigh a name; a unique
index cannot weigh anything.

WHICH ERROR TO PREFER
═══════════════════════════════════════════════════════════════════════
A FALSE MERGE puts two people in one record: their messages interleave,
one person's history is attributed to another, and untangling it by
hand means reassigning rows across seventeen foreign keys. A FALSE
SPLIT makes a duplicate: mildly annoying, visible, and mergeable later.

False split is the cheap error, so the name guard below errs that way —
an email match with no name in common at all creates a new contact
rather than assuming.

KNOWN LIMIT, STATED PLAINLY: the Williams pair above WOULD still merge,
because they share the token "williams". Splitting them would require
matching on given names, which false-splits ordinary variations like
"D. Reyes" and "Dana Reyes" — a duplicate for every person who fills a
form in twice with a nickname. The guard catches the clear cases and
declines to guess at the unclear ones.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("lead_identity")

# Titles carry no identity. Without stripping these, "Pastor Dana" and
# "Pastor Marcus" share a token and read as the same person.
HONORIFICS = {
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor",
    "rev", "reverend", "pastor", "father", "fr", "sister", "sr",
    "brother", "br", "bishop", "deacon", "elder", "rabbi", "imam",
    "sheikh", "coach", "chief", "capt", "captain", "sgt", "officer",
    "the", "and", "a",
}

_WORD = re.compile(r"[a-z0-9]+")


def name_tokens(name: Any) -> set:
    """Identity-bearing words in a name, lowercased."""
    words = _WORD.findall(str(name or "").lower())
    return {w for w in words if w not in HONORIFICS and len(w) > 1}


def same_person(stored_name: Any, incoming_name: Any) -> bool:
    """Could these two names be the same human?

    Generous on purpose — see "which error to prefer" above. Only a
    complete absence of shared identity is treated as a different
    person, because a false split is recoverable and a false merge is
    not.
    """
    a, b = name_tokens(stored_name), name_tokens(incoming_name)
    if not a or not b:
        return True          # nothing to contradict
    return bool(a & b)


def _escaped(email: str) -> str:
    """ilike with no wildcards = case-insensitive exact match, but an
    email legally contains '_', which IS a LIKE single-character
    wildcard. Unescaped, jo_n@x.com matches joan@x.com and two
    strangers get merged."""
    return (email.replace("\\", "\\\\")
                 .replace("%", "\\%")
                 .replace("_", "\\_"))


def normalize_email(email: Any) -> str:
    return str(email or "").strip().lower()


def normalize_phone(phone: Any) -> str:
    try:
        from sms_service import normalize_phone as _np
        return _np(str(phone or ""))
    except Exception:
        return ""


@dataclass
class Resolution:
    """Who this submission belongs to, and whether we just invented
    them."""
    contact_id: Optional[str]
    created: bool
    existing: Optional[Dict[str, Any]] = None
    matched_on: str = ""          # "email" | "phone" | "" (new)

    @property
    def ok(self) -> bool:
        return bool(self.contact_id)


def find(business_id: str, *, email: Any = None, phone: Any = None,
         name: Any = None, select: str = "id,name,email,phone,metadata"
         ) -> Optional[Dict[str, Any]]:
    """The existing contact for this person, or None. Never raises.

    Email first, then phone. Always WITHIN business_id — the same human
    is legitimately a separate contact of two different businesses, and
    a cross-tenant match would be a data leak, not a convenience.
    """
    import sb_clients

    email_clean = normalize_email(email)
    phone_clean = normalize_phone(phone)

    def _rejected(row: Dict[str, Any]) -> bool:
        if same_person(row.get("name"), name):
            return False
        logger.info(
            "[lead_identity] same contact details, different person — "
            "%r vs %r in %s; creating a separate contact",
            row.get("name"), name, business_id[:8])
        return True

    try:
        if email_clean:
            rows = sb_clients.sb_get_as_service(
                f"/contacts?business_id=eq.{business_id}"
                f"&email=ilike.{urllib.parse.quote(_escaped(email_clean), safe='')}"
                f"&select={select}&limit=5") or []
            for row in rows:
                if not _rejected(row):
                    return dict(row, _matched_on="email")

        if phone_clean:
            rows = sb_clients.sb_get_as_service(
                f"/contacts?business_id=eq.{business_id}"
                f"&phone=eq.{urllib.parse.quote(phone_clean, safe='')}"
                f"&select={select}&limit=5") or []
            for row in rows:
                if not _rejected(row):
                    return dict(row, _matched_on="phone")
    except Exception as e:
        logger.warning("[lead_identity] lookup failed for %s: %s",
                       business_id[:8], e)
    return None


def resolve(business_id: str, *, name: Any, email: Any = None,
            phone: Any = None, source: str = "",
            source_detail: Any = None,
            attribution: Optional[Dict[str, Any]] = None,
            extra: Optional[Dict[str, Any]] = None,
            select: str = "id,name,email,phone,metadata") -> Resolution:
    """Find this person or create them. One rule, every door.

    `extra` is merged into the INSERT only — never into an update, so a
    returning visitor's stored record is not overwritten by whatever
    the newest form happened to collect.
    """
    import sb_clients

    existing = find(business_id, email=email, phone=phone, name=name,
                    select=select)
    if existing:
        return Resolution(contact_id=str(existing.get("id")), created=False,
                          existing=existing,
                          matched_on=existing.get("_matched_on", ""))

    payload: Dict[str, Any] = {
        "business_id": business_id,
        "name": str(name or "").strip()[:200] or "Unnamed",
        "email": normalize_email(email) or None,
        "phone": normalize_phone(phone) or None,
        "status": "lead",
        "source": source or "unknown",
    }
    if source_detail:
        payload["source_detail"] = str(source_detail)[:200]
    if attribution:
        payload["attribution"] = attribution
    payload.update(extra or {})

    try:
        created = sb_clients.sb_post_as_service("/contacts", payload)
    except Exception as e:
        logger.warning("[lead_identity] create failed for %s: %s",
                       business_id[:8], e)
        created = None

    if not isinstance(created, list) or not created:
        # A concurrent submission may have just created them. There is
        # no unique index to lose the race against (see the module
        # docstring), but a losing insert for any other reason should
        # still hand back the person if they now exist rather than
        # dropping the lead entirely.
        again = find(business_id, email=email, phone=phone, name=name,
                     select=select)
        if again:
            return Resolution(contact_id=str(again.get("id")), created=False,
                              existing=again,
                              matched_on=again.get("_matched_on", ""))
        logger.warning(
            "[lead_identity] could not resolve or create a contact for %s "
            "— see the preceding sb_clients log line", business_id[:8])
        return Resolution(contact_id=None, created=False)

    return Resolution(contact_id=str(created[0]["id"]), created=True)
