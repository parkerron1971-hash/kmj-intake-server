# site_vertical_features.py
# ─────────────────────────────────────────────────────────────────────
# WHAT A SITE OF THIS KIND MUST DECIDE (2026-09-04, the barbershop bench).
#
# The bench built one two-chair barbershop three ways. The render a
# designer made with everything on file did not win on decoration; it
# won on decisions no rule had asked for: a line that says open now
# until 7, a duration next to every price, book with the barber you
# want, a directions link, a call button pinned to the bottom of a
# phone. Those are not taste. They are what a visitor to THAT KIND of
# business comes to the page to do, and the Director's prompt carried
# no list of them — it carried the same 8-to-11-section density
# skeleton for every business on the platform.
#
# This module is that list, per SITE FAMILY. A site family is not a
# billing vertical: the registry maps a barbershop to 'custom' (it has
# no bookkeeping rules of its own), but for a website a barbershop, a
# nail salon, a tattoo studio and a bakery are the same animal — a
# place you walk into. Families are matched on the business type's own
# words first, then on the registry's canonical vertical, then generic.
#
# Every item is a DECISION for the Director to write into the spec —
# or to decline in one line ("no staff booking: one practitioner").
# Facts stay facts: an item that needs hours, prices, or staff names
# applies only when THE FACTS / the inventory carry them.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# (family, keywords in the business type's own words). First match wins;
# order matters where words overlap ("fitness coach" is a practice, a
# "gym" is a walk-in place).
_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("practice", ("coach", "consult", "therap", "counsel", "lawyer", "attorney",
                  "law firm", "legal", "account", "bookkeep", "cpa", "financial",
                  "advisor", "tutor", "trainer", "nutrition", "doula",
                  "chiropract", "dentist", "clinic", "physio", "massage therap")),
    ("store", ("ecommerce", "e-commerce", "online store", "online shop", "shopify",
               "retail online", "merch")),
    ("walk_in", ("barber", "salon", "spa", "nail", "lash", "brow", "tattoo",
                 "piercing", "detail", "cafe", "coffee", "bakery", "restaurant",
                 "diner", "bar ", "pub", "brewery", "shop", "store", "boutique",
                 "gym", "studio", "yoga", "pilates", "car wash", "laundr",
                 "grooming", "florist", "market")),
    ("creative", ("creative", "agency", "design", "photograph", "videograph",
                  "film", "brand", "illustrat", "artist", "music", "producer",
                  "writer", "copywrit", "architect", "interior")),
    ("trade", ("contractor", "plumb", "electric", "roof", "hvac", "landscap",
               "lawn", "clean", "paint", "handyman", "remodel", "construct",
               "mover", "moving", "pest", "tree", "fence", "garage", "auto repair",
               "mechanic", "towing")),
    ("gathering", ("church", "ministry", "congregation", "parish", "temple",
                   "mosque", "synagogue", "nonprofit", "non-profit", "charity",
                   "foundation", "community")),
    ("product", ("saas", "software", "app", "course", "membership", "newsletter",
                 "podcast", "creator")),
]

# registry canonical → family, for types the keywords miss
_CANONICAL_FAMILY: Dict[str, str] = {
    "coach": "practice", "consultant": "practice", "therapist": "practice",
    "lawyer": "practice", "financial_educator": "practice",
    "fitness_wellness": "practice", "service_provider": "practice",
    "personal_services": "walk_in",
    "creative": "creative",
    "contractor": "trade",
    "ministry": "gathering", "nonprofit": "gathering",
    "ecommerce": "store",
    "saas": "product", "course_creator": "product",
}

FAMILY_LABEL: Dict[str, str] = {
    "walk_in": "a place people walk into",
    "practice": "a practice people book time with",
    "creative": "a studio whose work is the pitch",
    "trade": "a trade people call when something needs doing",
    "gathering": "a gathering people join",
    "store": "a store people buy from",
    "product": "a product people sign up for",
    "generic": "a business",
}

# The decisions. Each line is one thing the spec must decide, with the
# fact it depends on named so the Director never invents it.
FEATURES: Dict[str, List[str]] = {
    "walk_in": [
        "TODAY'S HOURS, LIVE: when THE FACTS carry hours, the hero states today's status in words the page computes from the posted hours (\"Open now until 7pm\" / \"Closed today, back Tuesday at 10am\"), with the full week posted once lower down. Never a guess; the posted hours are the only source.",
        "DURATION BESIDE EVERY PRICE: when the inventory carries duration_min, the service list shows minutes next to dollars on the same row. A menu with one number is half a menu.",
        "BOOK WITH A NAMED PERSON: when two or more staff are named on file and booking is ON, each person gets their own book action, worded with their name. One practitioner: one book action, and say so.",
        "THE MOBILE ACTION BAR: on phones, a bar pinned to the bottom of the screen with the two things a walk-in customer does: call (when a phone is on file) and book (when booking is ON). Nothing else in it.",
        "DIRECTIONS: the address on file is a link that opens directions, and the page says where to park if the owner said.",
        "THE WALK-IN LINE: one sentence that says whether walk-ins are taken and how booking relates (\"walk in when a chair is open; booking holds your spot\"). Only what the owner said.",
        "THE WORK LEADS THE PROOF: real photos of the work outrank testimonials in placement; captions say what the photo shows.",
    ],
    "practice": [
        "THE FIRST STEP, NAMED: the way a stranger starts (a call, a consult, an intake form) with its length and price when on file, and it is the primary action above the fold.",
        "WHO IT IS FOR, WHO IT IS NOT: one plain paragraph each, from the owner's words. A practice that is for everyone is for no one.",
        "WHAT AN ENGAGEMENT LOOKS LIKE: length, cadence, and what happens between sessions, when the offerings or the dossier say. Package names and prices exactly as on file.",
        "THE PRACTITIONER, NAMED: the person's name, the credentials on file (none invented), and the years they stated themselves.",
        "THE INTAKE DOOR: booking when it is ON; otherwise the inquiry form is the door, and the form's confirmation says what happens next.",
        "PROOF THAT IS REAL: testimonials as written; no counts or ratings unless proven stats carry them.",
    ],
    "creative": [
        "THE WORK OPENS THE PAGE: the strongest real piece is the hero; the portfolio comes before the pitch.",
        "EVERY PIECE SAYS WHAT IT WAS: client type, medium, and what the studio did, as captions the Director writes from the labeled images. No raw filenames.",
        "SERVICES AS PROJECT TYPES: the offerings framed as the kinds of projects taken, with starting-at pricing only when the inventory carries a price.",
        "THE PROCESS, IN THE STUDIO'S WORDS: how a project runs from first call to delivery, when the dossier describes it.",
        "THE INQUIRY IS THE DOOR: a form that asks about the project (what, when, budget when the owner wants it), confirming in words. Booking only if ON.",
    ],
    "trade": [
        "THE PHONE IS THE DOOR: when a phone is on file it is the primary action everywhere, including a pinned mobile call bar; the quote-request form is second.",
        "SERVICE AREA, STATED: the towns or radius served, only from the dossier or facts. Never a map of invented coverage.",
        "AVAILABILITY: hours on file, and whether emergency or same-day service exists, only if the owner said.",
        "LICENSED AND INSURED ONLY IF ON FILE: a credential line appears when THE FACTS or proven stats carry it, never as a default.",
        "BEFORE AND AFTER: real photos of finished work, captioned by what was done.",
        "THE QUOTE REQUEST: the form asks what needs doing and where, and confirms with what happens next.",
    ],
    "gathering": [
        "WHEN AND WHERE TO COME: service or meeting times and the address, when on file, above the fold; the address links to directions.",
        "NEW HERE: a short path for a first-time visitor (what to expect, where to park, who to ask for), from the owner's words.",
        "THE GIVE DOOR: when giving is ON, a devoted give action with its exact url; never if it is not.",
        "THE PEOPLE, NAMED: leadership or staff on file, with roles.",
        "WHAT IS HAPPENING: upcoming gatherings or programs when the modules carry them; nothing invented.",
    ],
    "store": [
        "PRODUCTS LEAD: the shop door and the featured products are the hero when the store is ON with items in it.",
        "HOW IT ARRIVES: shipping, pickup, or delivery facts only when the dossier states them.",
        "THE STORY BEHIND THE PRODUCTS: who makes them and why, from the owner's words.",
        "CONTACT FOR ORDERS: the channels on file, and the form for questions.",
    ],
    "product": [
        "WHAT IT DOES IN ONE LINE: the hero says the job the product does and for whom, from the owner's words.",
        "THE OFFER: plans and prices exactly as on file; a free tier or trial only if stated.",
        "SHOW IT: a real screenshot or demo when the inventory carries one; otherwise a directed drop slot, never a mock.",
        "THE SIGNUP DOOR: booking or the connected door when ON; otherwise the form, confirming with the next step.",
        "QUESTIONS PEOPLE ASK: an FAQ only from real records on file.",
    ],
    "generic": [
        "THE FIRST STEP, NAMED: how a stranger starts, with price and length when on file, as the primary action above the fold.",
        "HOURS AND PLACE: when on file, posted where a visitor looks first; the address links to directions.",
        "DURATION BESIDE EVERY PRICE: when the inventory carries duration_min, it shows beside the price.",
        "THE DOOR: booking or the connected door when ON; the form otherwise, confirming in words.",
    ],
}


def _norm(business_type: Optional[str]) -> str:
    return re.sub(r"[\s_\-]+", " ", (business_type or "").lower()).strip()


def family_for(business_type: Optional[str]) -> str:
    """The site family for a business type string: the type's own words
    first, the registry's canonical vertical second, generic last."""
    t = _norm(business_type)
    if not t:
        return "generic"
    padded = " " + t + " "
    for fam, words in _KEYWORDS:
        for w in words:
            if w in padded:
                return fam
    try:
        import vertical_registry
        canon = vertical_registry.resolve(business_type or "")
        return _CANONICAL_FAMILY.get(canon, "generic")
    except Exception:
        return "generic"


def features_for(business_type: Optional[str]) -> List[str]:
    return list(FEATURES.get(family_for(business_type), FEATURES["generic"]))


def block_for(business_type: Optional[str]) -> str:
    """The prompt block for the Director: what a site of this kind must
    decide. Every line is a decision to write into the spec, or to
    decline with a stated reason; none may invent a fact."""
    fam = family_for(business_type)
    label = FAMILY_LABEL.get(fam, FAMILY_LABEL["generic"])
    shown = (business_type or "").strip() or "business"
    lines = [
        f"== WHAT A SITE FOR {label.upper()} MUST DECIDE (this business is a {shown}) ==",
        "Each line below is a decision, not decoration. Write each one into the "
        "spec where it lands (section 3 or 4), or decline it in one sentence "
        "with the reason (\"no staff booking: one practitioner\"). An item that "
        "depends on a fact applies only when THE FACTS or the inventory carry "
        "that fact; never invent hours, prices, staff, credentials, or doors "
        "to satisfy a line.",
    ]
    for i, f in enumerate(FEATURES.get(fam, FEATURES["generic"]), 1):
        lines.append(f"{i}. {f}")
    return "\n".join(lines)
