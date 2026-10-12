"""texting_registration.py — texting under each business's own name (ISV).

docs/plans/ISV_TEXTING_PLAN_2026-10-11.md (Kevin, 2026-10-11: "write up the
isv build plan and start it"). Twilio's rules for a platform like ours: each
business that texts is registered as its OWN brand with its own campaign,
because one campaign for many companies is rejected (error 30926).

Step 1, everything Twilio's reviewers check (no Twilio calls, no money):

  THE PAGES. Each business site serves /texting-terms and /texting-privacy in
  the business's own name: who texts, what about, how often, STOP and HELP,
  rates, and the privacy line reviewers look for. They are the campaign's
  terms and privacy URLs (required on every campaign since June 2026).

  THE WORDS. campaign_words(): the campaign as Twilio will read it, generated
  from the business: the use case (Low Volume Mixed: bookings, replies AND
  offers, so the use case never has to change), a description that says who
  sends, who receives and why, the message flow quoting the opt-in boxes,
  sample messages that name the business, and the keyword replies.

  THE ANSWERS. What only the owner knows (legal name, business type,
  industry, address, website, the person Twilio may contact), saved in
  texting_registrations. The EIN is NOT kept here: it lives once, with the
  business's other legal details (business_profiles.ein, the same place
  About Your Business and the 1099 panel keep it; Kevin, 2026-10-11: "we can
  store EIN numbers because we created a place to have them"). This table
  still refuses an "ein" key so it never becomes a second copy.

  READINESS. What a reviewer will look for, checked: the site is live,
  booking is live, the pages answer, the answers and the EIN are in.

Step 3, sending it and keeping the owner posted (texting_isv.py talks to
Twilio; a sub-account per business, Kevin's decision D3):

  SEND. POST /texting/registration/{biz}/send (owner): status `submitted`
  first (so a second press can't send twice), then in the background the
  sub-account, profile, trust product, brand and messaging service, and
  status `brand_pending`. Twilio's own check failing → `failed` with its
  reasons, and the owner can fix the details and send again.

  ALONG THE WAY. Twilio's status pings (POST /texting/twilio-status) and a sweep
  every 15 minutes ask Twilio where each registration stands: the campaign
  goes in once the brand is approved (`campaign_pending`), then `approved`,
  or `failed` with the carriers' reasons. A registration whose sending was
  cut short (a deploy, Twilio down) is picked up where it stopped.

  UPDATES. Every change is told to the owner in the app, by push and by
  email, in plain words, and shows on the registration screen.

Step 4, once approved: the business's number moves into (or is bought in)
its sub-account and joins its own messaging service (_give_number); the
sweep keeps trying until it's ready, then the owner hears the number.
twilio_sms follows sms_numbers.account_sid for sending, webhooks and release.

  OPEN. TEXTING_REGISTRATION_OPEN: unset = nobody can send yet (our primary
  profile must be "ISV Reseller or Partner" first, ticket #29903903), `*` =
  every business, or a comma list of business ids (the pilot).
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

import sb_clients
import texting_isv
from business_access import business_access

logger = logging.getLogger("texting_registration")

router = APIRouter(prefix="/texting", tags=["texting"])

USE_CASE = "LOW_VOLUME"            # Twilio's "Low Volume Mixed"
BUSINESS_TYPES = {"sole_proprietor": "Sole proprietor", "llc": "LLC", "corporation": "Corporation",
                  "partnership": "Partnership", "nonprofit": "Nonprofit"}
INDUSTRIES = texting_isv.INDUSTRIES
STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
             "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())
PRIVACY_LINE = ("We do not sell or share your mobile number or your SMS opt-in data and consent with third "
                "parties or affiliates for their marketing purposes.")
TERMS_PATH, PRIVACY_PATH = "/texting-terms", "/texting-privacy"

# The statuses an owner can still edit and send from.
EDITABLE = ("draft", "failed")
IN_FLIGHT = ("submitted", "brand_pending", "campaign_pending")
SWEEP_LIMIT = 50
STALL_MINUTES = 5      # a `submitted` row untouched this long is resumed by the sweep
POKE_SECONDS = 60      # Twilio's status pings, at most one check a minute per business


class Answers(BaseModel):
    """What the owner tells us for Twilio. extra="forbid": an "ein" key is
    refused, so a tax ID can never be saved here (it lives in the business's
    details; see PUT .../ein)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    legal_name: str = Field(min_length=2, max_length=120)
    business_type: str
    industry: Optional[str] = None
    has_ein: bool
    street: str = Field(min_length=3, max_length=120)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=2)
    postal_code: str
    website: Optional[str] = Field(default=None, max_length=200)
    rep_first_name: str = Field(min_length=1, max_length=60)
    rep_last_name: str = Field(min_length=1, max_length=60)
    rep_title: str = Field(min_length=2, max_length=80)
    rep_email: str = Field(min_length=5, max_length=200)
    rep_phone: str
    # Sole proprietors only: the owner's OWN cell, where Twilio texts the YES
    # confirmation (a real mobile, never a provider's number).
    mobile_phone: Optional[str] = None

    @staticmethod
    def _us_phone(raw: str) -> str:
        digits = re.sub(r"\D", "", raw or "")
        if len(digits) == 10:
            digits = "1" + digits
        if len(digits) != 11 or not digits.startswith("1"):
            raise ValueError("Use a US phone number, like (231) 555-0100.")
        return "+" + digits

    @model_validator(mode="after")
    def check(self):
        if self.business_type not in BUSINESS_TYPES:
            raise ValueError("Choose sole proprietor, LLC, corporation, partnership or nonprofit.")
        if self.industry is not None and self.industry not in INDUSTRIES:
            raise ValueError("Choose the industry closest to your business.")
        self.state = self.state.upper()
        if self.state not in STATES:
            raise ValueError("Use the two-letter state, like MI.")
        if not re.fullmatch(r"\d{5}(-\d{4})?", self.postal_code):
            raise ValueError("Use a five-digit ZIP code.")
        if self.website and not re.fullmatch(r"https://[^\s/]+\.[^\s]+", self.website):
            raise ValueError("Use the website's full address, starting with https://.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.rep_email):
            raise ValueError("That email address doesn't look right.")
        self.rep_phone = self._us_phone(self.rep_phone)
        if self.mobile_phone:
            self.mobile_phone = self._us_phone(self.mobile_phone)
        if self.business_type == "sole_proprietor" and self.has_ein:
            raise ValueError("A sole proprietor with an EIN registers as an LLC or the business type on the EIN.")
        if not self.has_ein and self.business_type != "sole_proprietor":
            raise ValueError("Every LLC, corporation, partnership and nonprofit has an EIN. Without one, "
                             "choose sole proprietor.")
        return self


class EinIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ein: str

    @model_validator(mode="after")
    def check(self):
        digits = re.sub(r"\D", "", self.ein)
        if len(digits) != 9 or self.ein.replace("-", "").replace(" ", "") != digits:
            raise ValueError("Use the nine-digit EIN, like 12-3456789.")
        self.ein = f"{digits[:2]}-{digits[2:]}"
        return self


def brand_path(answers: Optional[Dict[str, Any]]) -> Optional[str]:
    """Which Twilio brand the business takes: 'sole_proprietor' without an
    EIN (one number, the owner confirms by a code to their own mobile), else
    'low_volume_standard'. None until the answers say."""
    if not answers:
        return None
    return "low_volume_standard" if answers.get("has_ein") else "sole_proprietor"


# ── the words Twilio reads ────────────────────────────────────────────

def booking_box(name: str) -> str:
    """The booking page's booking-texts checkbox in the business's name (the
    words it shows once the business registers; plan step 3)."""
    return (f"I agree to receive text messages about my bookings (confirmations, reminders, updates) from {name}. "
            "Not required to book. Msg frequency varies. Msg & data rates may apply. Reply STOP to opt out, "
            "HELP for help.")


def offers_box(name: str) -> str:
    """The booking page's separate, optional offers checkbox."""
    return (f"Also text me about offers and openings from {name}. Optional, not required to book. Msg frequency "
            "varies. Msg & data rates may apply. Reply STOP to opt out.")


def campaign_words(name: str, origin: str, *, offer_code: str = "FALL10") -> Dict[str, Any]:
    """The campaign registration as Twilio's reviewers will read it, in the
    business's name. Follows Twilio's published rejection reasons: say who
    sends, who receives and why; samples that name the business; opt-in
    quoted word for word; marketing consent collected apart; no public URL
    shorteners (links are the business's own site)."""
    book = f"{origin}/book"
    return {
        "use_case": USE_CASE,
        "description": (f"{name} texts its own clients who opted in on its booking page or website: booking "
                        "confirmations, appointment reminders, replies to their questions, and, only to clients "
                        "who separately agreed to them, occasional offers and openings. The messages are from "
                        f"{name} about its own services."),
        "message_flow": (f"Clients opt in on {name}'s booking page ({book}) by checking an unchecked box that "
                         f"reads: \"{booking_box(name)}\" A separate, optional, unchecked box collects consent to "
                         f"offers: \"{offers_box(name)}\" Consent is never required to book. Texting terms: "
                         f"{origin}{TERMS_PATH}. Privacy policy: {origin}{PRIVACY_PATH}."),
        "samples": [
            f"{name}: Your appointment is confirmed for Tue, Oct 14 at 3:00 PM. Reply STOP to opt out.",
            f"Reminder from {name}: your appointment is tomorrow at 3:00 PM. Reply STOP to opt out.",
            f"{name}: Thanks for coming in! Book your next visit here: {book} Reply STOP to opt out.",
            f"{name}: This week only, $10 off your next visit with the code {offer_code}: "
            f"{book}?offer={offer_code} Reply STOP to opt out.",
        ],
        "opt_in_keywords": ["START", "YES", "UNSTOP"],
        "opt_in_message": (f"{name}: You're subscribed to texts about your bookings. Msg frequency varies. "
                           "Msg & data rates may apply. Reply HELP for help, STOP to opt out."),
        "opt_out_keywords": ["STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"],
        "opt_out_message": f"{name}: You're unsubscribed and won't get more texts from us. Reply START to resubscribe.",
        "help_keywords": ["HELP", "INFO"],
        "help_message": (f"{name}: For help, reply to this message or visit {origin}{TERMS_PATH}. "
                         "Msg & data rates may apply. Reply STOP to opt out."),
        "has_embedded_links": True,
        "has_embedded_phone": False,
        "terms_url": f"{origin}{TERMS_PATH}",
        "privacy_url": f"{origin}{PRIVACY_PATH}",
    }


# ── the pages ─────────────────────────────────────────────────────────

_PAGE_CSS = """
:root { color-scheme: light dark; --bg: #ffffff; --text: #16181d; --muted: #5b6070; --line: #dcdfe5; }
@media (prefers-color-scheme: dark) { :root { --bg: #111317; --text: #eceef2; --muted: #a3a8b5; --line: #2a2e36; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 720px; margin: 0 auto; padding: 40px 20px 64px; }
h1 { font-size: 28px; line-height: 1.25; margin: 0 0 6px; }
h2 { font-size: 18px; margin: 28px 0 6px; }
p, li { color: var(--text); }
.muted { color: var(--muted); font-size: 14px; }
a { color: inherit; }
footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line); }
"""


def _page(title: str, name: str, body: str, origin: str) -> str:
    n = html.escape(name)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} | {n}</title>
<style>{_PAGE_CSS}</style></head>
<body><main>
<p class="muted">{n}</p>
<h1>{html.escape(title)}</h1>
{body}
<footer class="muted"><a href="{html.escape(origin)}{TERMS_PATH}">Texting terms</a> ·
<a href="{html.escape(origin)}{PRIVACY_PATH}">Texting privacy</a> ·
<a href="{html.escape(origin)}/book">Book</a></footer>
</main></body></html>"""


def terms_html(name: str, origin: str, contact_email: Optional[str] = None) -> str:
    """/texting-terms: the business's text messaging terms."""
    n = html.escape(name)
    contact = (f' or email <a href="mailto:{html.escape(contact_email)}">{html.escape(contact_email)}</a>'
               if contact_email else "")
    body = f"""
<p>{n} sends text messages to clients who agree to receive them. These terms explain what you get and how to stop.</p>
<h2>What we text</h2>
<ul>
<li><strong>About your bookings:</strong> confirmations, appointment reminders, updates, and replies to your messages. You agree to these with the box on our booking page or website.</li>
<li><strong>Offers and openings:</strong> occasional offers, only if you separately agree with the optional offers box when you book.</li>
</ul>
<p>Agreeing to texts is never required to book or buy anything.</p>
<h2>How often</h2>
<p>Message frequency varies with your bookings and activity. Message and data rates may apply.</p>
<h2>How to stop or get help</h2>
<p>Reply <strong>STOP</strong> to any text to stop all texts from {n}; you'll get one message confirming it. Reply <strong>START</strong> to sign up again. Reply <strong>HELP</strong> for help{contact}.</p>
<p>Carriers are not liable for delayed or undelivered messages.</p>
<h2>Privacy</h2>
<p>{html.escape(PRIVACY_LINE)} See our <a href="{html.escape(origin)}{PRIVACY_PATH}">texting privacy policy</a>.</p>"""
    return _page("Text messaging terms", name, body, origin)


def privacy_html(name: str, origin: str, contact_email: Optional[str] = None) -> str:
    """/texting-privacy: the business's privacy policy for text messages."""
    n = html.escape(name)
    contact = (f' To ask about your information, email <a href="mailto:{html.escape(contact_email)}">'
               f'{html.escape(contact_email)}</a>.' if contact_email else "")
    body = f"""
<p>This policy covers the mobile number and messages you share with {n} when you agree to receive texts.</p>
<h2>What we collect</h2>
<p>Your mobile number, your consent (when and where you gave it), and the messages we exchange.</p>
<h2>How we use it</h2>
<p>Only to send the texts you agreed to (about your bookings and, if you chose, offers and openings), to answer your messages, and to honor STOP and HELP.</p>
<h2>Sharing</h2>
<p><strong>{html.escape(PRIVACY_LINE)}</strong> We use service providers (our booking software and its text messaging provider) only to deliver our messages to you.</p>
<h2>Your choices</h2>
<p>Reply <strong>STOP</strong> to any text to stop all texts from {n}, or <strong>HELP</strong> for help.{contact}</p>
<p>See our <a href="{html.escape(origin)}{TERMS_PATH}">text messaging terms</a>.</p>"""
    return _page("Text messaging privacy policy", name, body, origin)


# ── the answers, the EIN and readiness ────────────────────────────────

def _read(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise RuntimeError("read failed")
    return rows


def registration(business_id: str) -> Optional[Dict[str, Any]]:
    """The business's texting_registrations row, or None. Raises on a failed read."""
    rows = _read(f"/texting_registrations?business_id=eq.{business_id}&select=*&limit=1")
    return rows[0] if rows else None


def site_origin(business_id: str) -> Optional[str]:
    """The business's site address (custom domain first), or None. Raises on
    a failed read."""
    import business_marketing_links as links
    site = links.site_for(business_id)
    return links.origin(site) if site else None


def ein_for(business_id: str, business: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The business's EIN from where it already keeps it (business_profiles,
    with the legacy 1099 payer blob as the fallback), or None."""
    import business_identity
    ein = business_identity.get_identity(business_id, business).get("ein") or ""
    digits = re.sub(r"\D", "", ein)
    return f"{digits[:2]}-{digits[2:]}" if len(digits) == 9 else None


# About Your Business's entity types → the form's business types. An S-corp
# is an election an LLC or a corporation makes, so it leaves the type to the
# owner.
ABOUT_TYPES = {"sole_prop": "sole_proprietor", "single_member_llc": "llc", "multi_member_llc": "llc",
               "partnership": "partnership", "c_corp": "corporation", "nonprofit": "nonprofit"}


def from_about(ident: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The form's starting answers from what About Your Business already keeps
    (Kevin, 2026-10-12: "make the form start from About Your Business"), so
    the owner doesn't type the legal name and address twice. Only filed facts:
    never the display name standing in for a legal name, and never the EIN
    itself (has_ein says whether one is on file). None when there's nothing."""
    if not ident:
        return None
    out: Dict[str, Any] = {}
    if ident.get("legal_name") and not ident.get("legal_name_is_fallback"):
        out["legal_name"] = str(ident["legal_name"])[:120]
    kind = ABOUT_TYPES.get(str(ident.get("entity_type") or ""))
    if kind:
        out["business_type"] = kind
    if len(re.sub(r"\D", "", str(ident.get("ein") or ""))) == 9:
        out["has_ein"] = True
    elif kind == "sole_proprietor":
        out["has_ein"] = False
    street = ", ".join(str(p).strip() for p in (ident.get("address_line1"), ident.get("address_line2"))
                       if p and str(p).strip())
    if street:
        out["street"] = street[:120]
    if ident.get("address_city"):
        out["city"] = str(ident["address_city"]).strip()[:80]
    state = str(ident.get("address_state") or "").strip().upper()
    if len(state) == 2:
        out["state"] = state
    zip5 = re.sub(r"\D", "", str(ident.get("address_zip") or ""))[:5]
    if len(zip5) == 5:
        out["postal_code"] = zip5
    return out or None


def about_for(business_id: str, business: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    import business_identity
    return from_about(business_identity.get_identity(business_id, business))


def is_open(business_id: str) -> bool:
    """Whether this business can send its registration (see OPEN above)."""
    raw = (os.environ.get("TEXTING_REGISTRATION_OPEN") or "").strip()
    if raw == "*":
        return True
    return str(business_id) in {x.strip() for x in raw.split(",") if x.strip()}


def readiness(business: Dict[str, Any], *, answers: Optional[Dict[str, Any]], origin: Optional[str],
              bookable: Optional[bool], ein_on_file: Optional[bool] = None) -> List[Dict[str, Any]]:
    """What Twilio's reviewers look for, each {key, ok, label, fix}. A check
    that couldn't be read is ok None (never a guess)."""
    out = [
        {"key": "site", "ok": bool(origin), "label": "Your website is live",
         "fix": "Publish your site in Build, My Site: reviewers open it."},
        {"key": "booking", "ok": bookable, "label": "Your booking page takes bookings",
         "fix": "Publish your booking page with at least one service: it's where clients agree to texts."},
        {"key": "pages", "ok": bool(origin),
         "label": "Your texting terms and privacy pages are up" + (f" ({origin}{TERMS_PATH})" if origin else ""),
         "fix": "They go up with your website."},
        {"key": "answers", "ok": bool(answers), "label": "Your business details for the registration",
         "fix": "Add your legal business name, address and the person the reviewers can contact."},
    ]
    if answers and answers.get("has_ein"):
        if answers.get("business_type") != "nonprofit":
            out.append({"key": "industry", "ok": answers.get("industry") in INDUSTRIES,
                        "label": "Your industry", "fix": "Choose the industry closest to your business."})
        out.append({"key": "ein", "ok": ein_on_file, "label": "Your EIN is on file",
                    "fix": "Add your EIN below. It's kept with your business's legal details."})
    elif answers:
        out.append({"key": "mobile", "ok": bool(answers.get("mobile_phone")),
                    "label": "Your own cell phone, for the verification text",
                    "fix": "Add your own cell number: a verification text comes to it once, and you reply YES."})
    return out


def _stage(status: str, twilio: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The steps the owner watches, each done / now / next. A sole proprietor
    has one more: replying YES to Twilio's text."""
    t = twilio or {}
    sole = texting_isv.sole_prop(t)
    order = ["business", "confirm", "campaign", "live"] if sole else ["business", "campaign", "live"]
    labels = {"business": "Your business is verified (minutes to a few days)",
              "confirm": "You reply YES to the verification text on your cell",
              "campaign": "The phone companies review how you text (usually about 2 weeks)",
              "live": "You text under your own name"}
    at = {"submitted": 0, "brand_pending": 0, "campaign_pending": order.index("campaign"),
          "approved": len(order)}.get(status)
    if sole and status == "brand_pending" and t.get("confirm_told"):
        at = order.index("confirm")
    out = []
    for i, key in enumerate(order):
        state = "next"
        if at is not None:
            state = "done" if i < at else ("now" if i == at else "next")
        out.append({"key": key, "label": labels[key], "state": state})
    return out


async def overview(business: Dict[str, Any]) -> Dict[str, Any]:
    bid = str(business["id"])
    try:
        row = await asyncio.to_thread(registration, bid)
    except RuntimeError:
        raise HTTPException(503, "Your texting registration couldn't be read just now. Try again in a minute.")
    try:
        origin = await asyncio.to_thread(site_origin, bid)
    except Exception as e:
        logger.warning("texting registration: site unread for %s: %s", bid[:8], e)
        origin = None
    bookable: Optional[bool] = None
    try:
        import business_marketing_links as links
        bookable = await asyncio.to_thread(links.bookable, bid, business)
    except Exception as e:
        logger.warning("texting registration: booking unread for %s: %s", bid[:8], e)
    ein: Optional[str] = None
    ein_known = True
    try:
        ein = await asyncio.to_thread(ein_for, bid, business)
    except Exception as e:
        logger.warning("texting registration: EIN unread for %s: %s", bid[:8], e)
        ein_known = False
    answers = (row or {}).get("answers") or None
    # Until the owner saves their own answers, the form starts from About
    # Your Business.
    about: Optional[Dict[str, Any]] = None
    if not answers:
        try:
            about = await asyncio.to_thread(about_for, bid, business)
        except Exception as e:
            logger.warning("texting registration: business details unread for %s: %s", bid[:8], e)
    name = str((answers or {}).get("legal_name") or business.get("name") or "Your business")
    shown_name = str(business.get("name") or name)
    status = (row or {}).get("status") or "not_started"
    checks = readiness(business, answers=answers, origin=origin, bookable=bookable,
                       ein_on_file=bool(ein) if ein_known else None)
    open_ = is_open(bid)
    ready = all(c["ok"] is True for c in checks)
    twilio = (row or {}).get("twilio") or {}
    rejected = bool(twilio.get("rejected_after_review"))
    sendable = bool(open_ and ready and status in EDITABLE and not rejected and answers)
    waiting_yes = bool(texting_isv.sole_prop(twilio) and status == "brand_pending" and twilio.get("confirm_told"))
    mobile = str((answers or {}).get("mobile_phone") or "")
    return {
        "status": status,
        "answers": answers,
        "from_about": about,
        "brand_path": brand_path(answers),
        "readiness": checks,
        "words": campaign_words(shown_name, origin) if origin else None,
        "pages": {"terms": f"{origin}{TERMS_PATH}", "privacy": f"{origin}{PRIVACY_PATH}"} if origin else None,
        "business_types": BUSINESS_TYPES,
        "industries": INDUSTRIES,
        "ein": {"on_file": bool(ein), "last4": ein[-4:] if ein else None} if ein_known else None,
        "open": open_,
        "can_send": sendable,
        "steps": _stage(status, twilio),
        # A sole proprietor's YES text: where it went and from whom, and
        # whether a new one can be sent now.
        "confirm": {"waiting": True, "to_last4": mobile[-4:] or None, "from": texting_isv.OTP_FROM,
                    "can_resend": _can_resend(twilio)} if waiting_yes else None,
        "failure": (row or {}).get("failure") if status == "failed" else None,
        "rejected_after_review": rejected,
        "sent_at": twilio.get("sent_at"),
    }


@router.get("/registration/{business_id}")
async def get_registration(business_id: str, biz: dict = Depends(business_access("owner"))):
    """The owner's texting registration: answers, readiness, the words Twilio
    will read, and where it stands. Owner only (it holds the representative's
    details)."""
    return {"ok": True, **await overview(biz)}


@router.put("/registration/{business_id}")
async def save_registration(business_id: str, body: Answers, biz: dict = Depends(business_access("owner"))):
    """Save the answers (never an EIN). Nothing is sent to Twilio."""
    bid = str(UUID(str(biz["id"])))
    row = {"business_id": bid, "answers": body.model_dump(mode="json"),
           "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        current = await asyncio.to_thread(registration, bid)
    except RuntimeError:
        raise HTTPException(503, "Your details couldn't be saved just now. Nothing changed.") from None
    if current and current.get("status") not in (None, *EDITABLE):
        raise HTTPException(409, "Your registration has been sent for approval, so these details can't change here. "
                                 "If something is wrong, tell us and we'll update it.")
    saved = await asyncio.to_thread(
        sb_clients.sb_post_as_service, "/texting_registrations?on_conflict=business_id",
        {**row, "status": (current or {}).get("status") or "draft"}, "resolution=merge-duplicates,return=representation")
    if not saved:
        raise HTTPException(503, "Your details couldn't be saved just now. Nothing changed.")
    return {"ok": True, **await overview(biz)}


@router.put("/registration/{business_id}/ein")
async def save_ein(business_id: str, body: EinIn, biz: dict = Depends(business_access("owner"))):
    """Keep the EIN with the business's legal details (business_profiles.ein,
    the one place it lives). Owner only; never written to the registration."""
    bid = str(UUID(str(biz["id"])))
    import business_identity
    written = await asyncio.to_thread(business_identity.set_identity, bid, ein=body.ein)
    if not written:
        raise HTTPException(503, "Your EIN couldn't be saved just now. Nothing changed.")
    return {"ok": True, **await overview(biz)}


# ── sending it, and where it stands ───────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _patch(business_id: str, fields: Dict[str, Any], *, when: Optional[tuple] = None) -> Optional[List[Any]]:
    """Update the row; with `when`, only from those statuses. The rows
    changed, [] when the status had moved on, None when the write failed."""
    path = f"/texting_registrations?business_id=eq.{business_id}"
    if when:
        path += f"&status=in.({','.join(when)})"
    res = sb_clients.sb_patch_as_service(path, {**fields, "updated_at": _now().isoformat()})
    return res if isinstance(res, list) else None


def _saver(business_id: str):
    """Save the Twilio ids as each step lands, so a cut-short send resumes."""
    def save(t: Dict[str, Any]) -> None:
        if _patch(business_id, {"twilio": {**t, "touched_at": _now().isoformat()}}) is None:
            raise texting_isv.TwilioDown("the registration couldn't be saved")
    return save


UPDATES = {
    "brand_pending": ("Your texting registration is sent",
                      "Solutionist sent {name}'s registration. First your business is verified (minutes to a few "
                      "days), then the phone companies review how you text (usually about 2 weeks). We'll tell you "
                      "at each step."),
    "campaign_pending": ("{name} is verified",
                         "Next, the phone companies review how {name} texts its clients. That usually takes about "
                         "2 weeks."),
    "approved": ("{name} can text under its own name",
                 "The phone companies approved {name}'s texting. Solutionist is setting up your number under your own "
                 "name now."),
    "confirm": ("Reply YES to the verification text",
                "{name} is verified. To finish, reply YES to the verification text just sent to your cell from "
                f"{texting_isv.OTP_FROM}, within 24 hours. If it didn't come or ran out, open Operate, "
                "Text, Your name on texts and send a new one."),
    "number_ready": ("Your texts now go out under {name}",
                     "{number} is now {name}'s own registered number. Your texts go out from it under your "
                     "own name."),
    "failed": ("Your texting registration needs a fix",
               "{reasons} Open Operate, Text, Your name on texts to see what to change."),
}


async def _tell_owner(business: Dict[str, Any], status: str, reasons: Optional[List[str]] = None,
                      number: Optional[str] = None) -> Dict[str, bool]:
    """In the app, by push and by email; each best-effort, none can undo the
    status change."""
    if status not in UPDATES:
        return {}
    name = str(business.get("name") or "Your business")
    title, body = (s.format(name=name, reasons=" ".join(reasons or []) or "It came back without a reason.",
                            number=_pretty(number) if number else "Your number")
                   for s in UPDATES[status])
    out = {"in_app": False, "push": False, "email": False}
    bid = str(business.get("id"))
    try:
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/chief_notifications", {
            "business_id": bid, "type": "alert" if status == "failed" else "info",
            "title": title[:120], "body": body[:600], "priority": "high" if status == "failed" else "normal",
            "status": "unread",
            "data": {"kind": f"texting_registration_{status}", "nav": {"tab": "operate", "sub": "sms"}}})
        out["in_app"] = True
    except Exception as e:
        logger.warning("texting update in-app failed for %s: %s", bid[:8], e)
    try:
        import push_notifications
        out["push"] = bool(await asyncio.to_thread(push_notifications.send_to_business, bid, title=title,
                                                   body=body[:180], nav="operate:sms",
                                                   tag=f"texting-registration-{status}"))
    except Exception as e:
        logger.warning("texting update push failed for %s: %s", bid[:8], e)
    try:
        import email_domain_monitor
        import email_sender
        to_email = await email_domain_monitor._owner_email(str(business.get("owner_id") or ""))
        if to_email:
            await email_sender.send_via_resend(
                to_email=to_email, to_name=None,
                from_email=os.environ.get("RESEND_FROM_EMAIL") or email_sender.DEFAULT_FROM_EMAIL,
                from_name=email_sender.DEFAULT_FROM_NAME, subject=title, body=body, reply_to=None)
            out["email"] = True
    except Exception as e:
        logger.warning("texting update email failed for %s: %s", bid[:8], e)
    return out


RESEND_MINUTES = 10   # a new YES text at most this often


def _can_resend(t: Dict[str, Any]) -> bool:
    last = t.get("code_sent_at") or t.get("confirm_told_at")
    if not last:
        return True
    try:
        return _now() - datetime.fromisoformat(str(last).replace("Z", "+00:00")) >= timedelta(minutes=RESEND_MINUTES)
    except ValueError:
        return True


def _pretty(number: str) -> str:
    d = re.sub(r"\D", "", number or "")[-10:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else (number or "")


def _platform_line(business_id: str) -> Optional[Dict[str, Any]]:
    """The number the business already has on our main account, if any."""
    rows = _read(f"/sms_numbers?business_id=eq.{business_id}&status=in.(active,suspended)"
                 f"&account_sid=is.null&select=id,phone_number,provider_sid,area_code&limit=1")
    return rows[0] if rows else None


async def _give_number(business: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """Step 4, once approved: the business's number in its own sub-account
    and campaign. The number it already has with us moves (its clients keep
    it); otherwise one is bought in its area code. Recorded in sms_numbers
    (account_sid set), so sending, replies and releasing all follow it.
    True when the number is ready; False to try again on the next sweep."""
    bid = str(business["id"])
    t = dict(row.get("twilio") or {})
    if t.get("number_ready"):
        return True
    save = _saver(bid)
    try:
        line = await asyncio.to_thread(_platform_line, bid)
        pn = (line or {}).get("provider_sid")
        if pn and not t.get("number_sid"):
            import twilio_sms
            await asyncio.to_thread(twilio_sms.detach_from_service, pn)   # off our shared pool first
        phone = re.sub(r"\D", "", ((row.get("answers") or {}).get("rep_phone") or ""))
        got = await asyncio.to_thread(texting_isv.ensure_number, t, platform_sid=pn,
                                      area_code=phone[1:4] if len(phone) == 11 else None, save=save)
    except texting_isv.TwilioRefused as e:
        logger.warning("texting number for %s refused: %s", bid[:8], e)
        return False
    except (texting_isv.TwilioDown, RuntimeError) as e:
        logger.warning("texting number for %s paused: %s", bid[:8], e)
        return False
    now = _now().isoformat()
    fields = {"account_sid": t["account_sid"], "messaging_service_sid": t["service_sid"],
              "provider_sid": got["sid"], "updated_at": now}
    if line:
        written = await asyncio.to_thread(sb_clients.sb_patch_as_service, f"/sms_numbers?id=eq.{line['id']}", fields)
    else:
        written = await asyncio.to_thread(sb_clients.sb_post_as_service, "/sms_numbers", {
            **fields, "business_id": bid, "phone_number": got["phone_number"], "status": "active",
            "provider": "twilio", "area_code": re.sub(r"\D", "", got["phone_number"] or "")[1:4] or None,
            "purchased_at": now})
    if not written:
        logger.warning("texting number for %s ready but not recorded; retrying", bid[:8])
        return False
    t.update(number_ready=True, number=got["phone_number"])
    save(t)
    await _tell_owner(business, "number_ready", number=got["phone_number"])
    return True


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = _read(f"/businesses?id=eq.{UUID(str(business_id))}&select=*&limit=1")
    return rows[0] if rows else None


async def _send(business: Dict[str, Any], row: Dict[str, Any]) -> str:
    """Steps 0 to 4 for one business, from wherever it stopped. Returns the
    status it ends in."""
    bid = str(business["id"])
    answers = row.get("answers") or {}
    t = dict(row.get("twilio") or {})
    try:
        ein = await asyncio.to_thread(ein_for, bid, business) if answers.get("has_ein") else None
        if answers.get("has_ein") and not ein:
            raise texting_isv.NeedsFix(["Add your EIN: it's needed to register the business."])
        origin = await asyncio.to_thread(site_origin, bid)
        if not origin:
            raise texting_isv.NeedsFix(["Publish your website: the reviewers open it."])
        shown = str(business.get("name") or answers.get("legal_name"))
        t.setdefault("campaign_words", campaign_words(shown, origin))
        t.setdefault("sent_at", _now().isoformat())
        await asyncio.to_thread(
            texting_isv.send, t, business_id=bid, name=shown, answers=answers, ein=ein,
            website=answers.get("website") or origin,
            callback=f"{texting_isv.webhook_base()}/texting/twilio-status", save=_saver(bid))
    except texting_isv.NeedsFix as e:
        await asyncio.to_thread(_patch, bid, {"status": "failed", "failure": " ".join(e.reasons)[:1000]},
                                when=("submitted",))
        await _tell_owner(business, "failed", e.reasons)
        return "failed"
    except texting_isv.TwilioRefused as e:
        logger.warning("texting registration refused for %s: %s", bid[:8], e)
        reasons = [f"The registration came back: {e.message}"]
        await asyncio.to_thread(_patch, bid, {"status": "failed", "failure": reasons[0][:1000]}, when=("submitted",))
        await _tell_owner(business, "failed", reasons)
        return "failed"
    except (texting_isv.TwilioDown, RuntimeError) as e:
        # Nothing wrong with the business: the sweep picks it up again.
        logger.warning("texting registration for %s paused: %s", bid[:8], e)
        return "submitted"
    moved = await asyncio.to_thread(_patch, bid, {"status": "brand_pending", "failure": None}, when=("submitted",))
    if moved:
        await _tell_owner(business, "brand_pending")
    return "brand_pending"


async def _check(business: Dict[str, Any], row: Dict[str, Any]) -> str:
    """Ask Twilio where a sent registration stands and move it along."""
    bid = str(business["id"])
    t = dict(row.get("twilio") or {})
    status = str(row.get("status"))
    try:
        res = await asyncio.to_thread(texting_isv.check, t, _saver(bid))
    except texting_isv.TwilioRefused as e:
        logger.warning("texting check refused for %s: %s", bid[:8], e)
        return status
    except (texting_isv.TwilioDown, RuntimeError) as e:
        logger.warning("texting check for %s paused: %s", bid[:8], e)
        return status
    if res["stage"] == "confirm":
        # A sole proprietor's brand is approved; Twilio has texted the owner's
        # cell and waits for YES. Told once (the screen shows it until then).
        if not t.get("confirm_told"):
            t.update(confirm_told=True, confirm_told_at=_now().isoformat())
            if await asyncio.to_thread(_patch, bid, {"twilio": t}, when=(status,)):
                await _tell_owner(business, "confirm")
        return status
    new = {"brand": "brand_pending", "campaign": "campaign_pending", "approved": "approved",
           "failed": "failed"}[res["stage"]]
    if new == status:
        return status
    fields: Dict[str, Any] = {"status": new}
    if new == "failed":
        # Sent back after review: resending the same registration can't fix
        # it, so the owner isn't offered that (see send_registration).
        fields["failure"] = " ".join(res["reasons"])[:1000]
        fields["twilio"] = {**t, "rejected_after_review": True}
    moved = await asyncio.to_thread(_patch, bid, fields, when=(status,))
    if moved:
        await _tell_owner(business, new, res.get("reasons"))
    return new


async def advance(business_id: str) -> Optional[str]:
    """Move one registration along: resume a cut-short send, or ask Twilio
    where it stands. Returns the status it ends in."""
    try:
        row = await asyncio.to_thread(registration, business_id)
        business = await asyncio.to_thread(_business, business_id)
    except RuntimeError:
        return None
    if not row or not business:
        return None
    status = row.get("status")
    if status == "submitted":
        # Every step a send takes saves the row, so updated_at is its heartbeat.
        try:
            fresh = _now() - datetime.fromisoformat(str(row.get("updated_at")).replace("Z", "+00:00")) \
                < timedelta(minutes=STALL_MINUTES)
        except ValueError:
            fresh = False
        if fresh:
            return status      # a send is (or just was) running
        return await _send(business, row)
    if status in ("brand_pending", "campaign_pending") and (row.get("twilio") or {}).get("brand_sid"):
        new = await _check(business, row)
        if new != "approved":
            return new
        try:
            row = await asyncio.to_thread(registration, business_id) or row
        except RuntimeError:
            return new
        status = new
    if status == "approved" and not (row.get("twilio") or {}).get("number_ready"):
        await _give_number(business, row)
    return status


@router.post("/registration/{business_id}/send")
async def send_registration(business_id: str, biz: dict = Depends(business_access("owner"))):
    """Send the registration to Twilio. Owner only, once: the status turns
    `submitted` before anything leaves, so a second press is refused."""
    bid = str(UUID(str(biz["id"])))
    view = await overview(biz)
    if not view["open"]:
        raise HTTPException(409, "Registration isn't open for your business yet. We'll tell you when it is.")
    if view["status"] not in EDITABLE:
        raise HTTPException(409, "Your registration has been sent already.")
    if view["rejected_after_review"]:
        raise HTTPException(409, "Your registration came back after review. Sending the same one again won't "
                                 "fix it, so Solutionist is looking into it and will tell you what happens.")
    missing = [c["fix"] for c in view["readiness"] if c["ok"] is not True]
    if missing:
        raise HTTPException(400, " ".join(missing))
    moved = await asyncio.to_thread(_patch, bid, {"status": "submitted", "failure": None}, when=EDITABLE)
    if moved is None:
        raise HTTPException(503, "Your registration couldn't be sent just now. Nothing was sent.")
    if not moved:
        raise HTTPException(409, "Your registration is being sent already.")
    _background(_send(biz, moved[0]))
    return {"ok": True, **await overview(biz)}


@router.post("/registration/{business_id}/resend-code")
async def resend_code(business_id: str, biz: dict = Depends(business_access("owner"))):
    """A new YES text to a sole proprietor's cell (Twilio's first one lasts 24
    hours). Owner only; at most one every ten minutes."""
    bid = str(UUID(str(biz["id"])))
    try:
        row = await asyncio.to_thread(registration, bid)
    except RuntimeError:
        raise HTTPException(503, "Your registration couldn't be read just now. Try again in a minute.") from None
    t = dict((row or {}).get("twilio") or {})
    if not (row and row.get("status") == "brand_pending" and texting_isv.sole_prop(t)
            and t.get("brand_sid") and t.get("confirm_told")):
        raise HTTPException(409, "There's no confirmation text waiting for you right now.")
    if not _can_resend(t):
        raise HTTPException(429, "A new text went out a few minutes ago. Give it a minute to arrive.")
    try:
        await asyncio.to_thread(texting_isv.resend_code, t)
    except (texting_isv.TwilioRefused, texting_isv.TwilioDown, RuntimeError) as e:
        logger.warning("texting resend code for %s failed: %s", bid[:8], e)
        raise HTTPException(502, "A new verification text couldn't be sent just now. Try again in a few minutes.") from None
    t["code_sent_at"] = _now().isoformat()
    await asyncio.to_thread(_patch, bid, {"twilio": t})
    return {"ok": True, **await overview(biz)}


_TASKS: set = set()


def _background(coro) -> None:
    """Run it after the response, holding a reference so it isn't collected
    mid-send (a deploy can still cut it short; the sweep resumes it)."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


_POKED: Dict[str, float] = {}
_SID = re.compile(r"^(AC|BU)[0-9a-f]{32}$")


def _registration_for(sids: List[str]) -> Optional[str]:
    """The business whose registration holds one of these Twilio ids."""
    keys = [("account_sid", s) for s in sids if s.startswith("AC")] + \
           [(k, s) for s in sids if s.startswith("BU") for k in ("profile_sid", "trust_sid")]
    if not keys:
        return None
    ors = ",".join(f"twilio->>{k}.eq.{s}" for k, s in keys)
    rows = _read(f"/texting_registrations?or=({ors})&select=business_id&limit=1")
    return str(rows[0]["business_id"]) if rows else None


@router.post("/twilio-status")
async def twilio_status(request: Request):
    """Twilio's status ping for a business's profile or trust product. Never
    trusted for what it says: it only names which registration to ask Twilio
    about ourselves, at most once a minute per business. Nothing matched →
    nothing happens (the sweep runs every 15 minutes anyway)."""
    try:
        form = await request.form()
        sids = [str(v) for k, v in form.items()
                if k.lower().replace("_", "") in ("accountsid", "bundlesid", "customerprofilesid", "trustproductsid")
                and _SID.match(str(v))]
        bid = await asyncio.to_thread(_registration_for, sids)
    except Exception as e:
        logger.warning("texting status ping unread: %s", e)
        return Response(status_code=204)
    now = time.monotonic()
    if bid and now - _POKED.get(bid, 0.0) >= POKE_SECONDS:
        _POKED[bid] = now
        _background(advance(bid))
    return Response(status_code=204)


async def sweep_tick() -> Dict[str, Any]:
    """Every 15 minutes: each registration on its way, moved along."""
    try:
        # On its way, or approved with its number not set up yet (step 4).
        rows = await asyncio.to_thread(
            _read, f"/texting_registrations?or=(status.in.({','.join(IN_FLIGHT)}),"
                   f"and(status.eq.approved,twilio->>number_ready.is.null))"
                   f"&select=business_id,status&order=updated_at.asc&limit={SWEEP_LIMIT}")
    except RuntimeError:
        return {"read": False}
    moved = 0
    for r in rows:
        try:
            if await advance(str(r["business_id"])) != r.get("status"):
                moved += 1
        except Exception as e:
            logger.warning("texting sweep failed for %s: %s", str(r.get("business_id"))[:8], e)
    return {"checked": len(rows), "moved": moved}


# ── the public pages (public_site serves them on the business's site) ──

async def page_for(business_id: str, kind: str) -> Optional[str]:
    """The HTML for /texting-terms or /texting-privacy, or None when the
    business can't be read."""
    try:
        rows = await asyncio.to_thread(
            _read, f"/businesses?id=eq.{UUID(str(business_id))}&select=id,name,settings&limit=1")
        origin = await asyncio.to_thread(site_origin, str(business_id))
    except Exception as e:
        logger.warning("texting page unread for %s: %s", str(business_id)[:8], e)
        return None
    if not rows or not origin:
        return None
    name = str(rows[0].get("name") or "This business")
    try:
        import public_site
        email = public_site._business_public_email(rows[0].get("settings") or {}) or None
    except Exception:
        email = None
    return terms_html(name, origin, email) if kind == "terms" else privacy_html(name, origin, email)
