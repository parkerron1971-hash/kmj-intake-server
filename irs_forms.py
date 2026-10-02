"""
irs_forms.py — prefill the OFFICIAL IRS form, never a facsimile.

WHAT THIS IS AND IS NOT

  It fetches the real blank PDF from irs.gov and writes the
  organisation's own recorded facts into its form fields. That is the
  form's intended use, and it is what every vendor-onboarding tool does.

  It does NOT draw a W-9-shaped document. A facsimile is rejected by
  requesters who know what the form looks like, and producing one is a
  step toward manufacturing official paper. The bytes that come back are
  the IRS's own bytes with the boxes filled.

  It NEVER signs. The signature and date are left empty; the
  practitioner signs what they have read.

WHY W-9 AND NOT 990 OR 1023

  A W-9 never goes to the IRS. It goes to the funder or payer who asked
  for it, so "fill it in, download it, hand it over" is the real
  workflow rather than a workaround.

  Form 990 and 990-PF must be filed ELECTRONICALLY (Taxpayer First Act,
  tax years beginning after 1 July 2019). Forms 1023, 1024 and 1024-A
  must be filed through Pay.gov with a user fee. For those a filled PDF
  would not be filable at all, so the honest product is a link to where
  they are filed — never a download.

NEVER BUNDLE A COPY

  The IRS revises these. W-9 is on Rev. March 2024 with a June 2026
  revision in draft, and a requester can reject a superseded revision.
  irs.gov/pub/irs-pdf/fw9.pdf always serves whatever is current, so the
  blank is fetched and cached briefly rather than committed.

THE FAILURE THAT MATTERS

  Field names are opaque (f1_01 … f1_15) and are NOT stable across
  revisions. If a new revision renames them, a naive fill writes nothing
  and returns a pristine blank form that LOOKS filled until someone
  reads it — the worst possible failure, because it is silent and it
  reaches a funder.

  So every field is verified to exist BEFORE anything is written, and a
  mismatch raises rather than returning a blank. The caller falls back to
  handing the practitioner the plain form.
"""
from __future__ import annotations

import io
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("irs_forms")

# The stable path. Always the current official revision.
W9_URL = "https://www.irs.gov/pub/irs-pdf/fw9.pdf"

# irs.gov refuses a bare urllib agent often enough to be worth setting.
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Cache the blank for an hour: long enough not to hammer irs.gov on every
# download, short enough that a revision is picked up the same day.
_CACHE_TTL_SECONDS = 3600
_cache: Dict[str, Tuple[float, bytes]] = {}

# ── The W-9 field map ────────────────────────────────────────────────
#
# Derived from the widget geometry of the live form, not guessed: each
# name was matched to its box by position on the page.
#
#   f1_01  Line 1  Name of the entity
#   f1_02  Line 2  Business name / disregarded entity name
#   c1_1[6] + f1_04  Line 3a "Other" checkbox and its description
#   f1_07  Line 5  Address
#   f1_08  Line 6  City, state, ZIP
#   f1_14  Part I  EIN, first two digits
#   f1_15  Part I  EIN, remaining seven
#
# DELIBERATELY NOT FILLED: the exempt payee code and FATCA code (Line 4),
# the account numbers (Line 7), the requester block, the SSN boxes, and
# the signature. Those are either determinations the organisation must
# make or facts we do not hold, and a wrong exempt-payee code on a signed
# form is the organisation's problem, not ours to guess at.
_P = "topmostSubform[0].Page1[0]"

# Line 3a is ONE field with seven kid widgets, and each kid has its own
# "on" state rather than a shared /Yes: c1_1[0] turns on with /1 ...
# c1_1[6] with /7. Writing /1 to the Other box silently leaves it /Off,
# which is exactly the failure the readback below exists to catch — it
# was caught that way, not by reading the spec.
W9_OTHER_ON = "/7"
W9_FIELDS = {
    "name": f"{_P}.f1_01[0]",
    "business_name": f"{_P}.f1_02[0]",
    "other_desc": f"{_P}.Boxes3a-b_ReadOrder[0].f1_04[0]",
    "other_box": f"{_P}.Boxes3a-b_ReadOrder[0].c1_1[6]",
    "address": f"{_P}.Address_ReadOrder[0].f1_07[0]",
    "city_state_zip": f"{_P}.Address_ReadOrder[0].f1_08[0]",
    "ein_prefix": f"{_P}.f1_14[0]",
    "ein_rest": f"{_P}.f1_15[0]",
}


class FormUnavailable(RuntimeError):
    """The official form could not be fetched, read, or reliably filled.

    Always means "hand them the plain form instead" — never "return
    something that might be blank"."""


def _fetch(url: str) -> bytes:
    hit = _cache.get(url)
    if hit and (time.time() - hit[0]) < _CACHE_TTL_SECONDS:
        return hit[1]
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as c:
            r = c.get(url, headers={"User-Agent": _UA})
        if r.status_code >= 400 or not r.content:
            raise FormUnavailable(f"irs.gov returned {r.status_code}")
        if not r.content.startswith(b"%PDF"):
            raise FormUnavailable("irs.gov did not return a PDF")
    except FormUnavailable:
        raise
    except Exception as e:  # network, DNS, TLS
        raise FormUnavailable(f"could not reach irs.gov: {e}") from e
    _cache[url] = (time.time(), r.content)
    return r.content


def _split_ein(raw: Optional[str]) -> Optional[Tuple[str, str]]:
    """XX-XXXXXXX across the form's two boxes.

    Returns None for anything that is not nine digits — a partial EIN on
    a signed W-9 is worse than an empty one, because it looks answered.
    """
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) != 9:
        return None
    return digits[:2], digits[2:]


def _city_state_zip(profile: Dict[str, Any]) -> str:
    city = (profile.get("address_city") or "").strip()
    state = (profile.get("address_state") or "").strip()
    zipc = (profile.get("address_zip") or "").strip()
    left = ", ".join(p for p in (city, state) if p)
    return " ".join(p for p in (left, zipc) if p).strip()


def w9_values(profile: Dict[str, Any], business_name: str = "") -> Dict[str, str]:
    """The boxes we will fill, from facts already recorded.

    Every value here came from the practitioner. Nothing is inferred
    except the Line 3a description, which restates the entity_type they
    chose — and even that is shown back to them before they sign.
    """
    out: Dict[str, str] = {}
    legal = (profile.get("legal_name") or "").strip()
    if legal:
        out["name"] = legal
    # Line 2 only when the trading name genuinely differs — repeating
    # Line 1 into Line 2 is a common way to make a form look wrong.
    dba = (business_name or "").strip()
    if dba and legal and dba.lower() != legal.lower():
        out["business_name"] = dba

    addr = " ".join(p for p in [(profile.get("address_line1") or "").strip(),
                                (profile.get("address_line2") or "").strip()] if p)
    if addr:
        out["address"] = addr
    csz = _city_state_zip(profile)
    if csz:
        out["city_state_zip"] = csz

    ein = _split_ein(profile.get("ein"))
    if ein:
        out["ein_prefix"], out["ein_rest"] = ein

    # Line 3a. A 501(c)(3) is not any of the five printed choices; the
    # instructions send exempt organisations to "Other". We restate what
    # they already told us rather than deciding anything new.
    if (profile.get("entity_type") or "").strip().lower() == "nonprofit":
        out["other_box"] = W9_OTHER_ON
        out["other_desc"] = "Nonprofit corporation exempt under section 501(c)(3)"
    return out


def _fill_official(url: str, field_map: Dict[str, str], values: Dict[str, str],
                   label: str) -> bytes:
    """The official blank at `url`, with `values` written into `field_map`.

    Shared by every form here so each one gets the same two guarantees:
    every field is verified to EXIST before anything is written, and every
    value is READ BACK afterwards. Raises FormUnavailable rather than ever
    returning a form whose boxes did not take."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as e:  # pragma: no cover - dependency is pinned
        raise FormUnavailable("pypdf is not installed") from e

    blank = _fetch(url)
    if not values:
        raise FormUnavailable("nothing recorded to fill this form with")

    try:
        reader = PdfReader(io.BytesIO(blank))
        present = set((reader.get_fields() or {}).keys())
    except Exception as e:
        raise FormUnavailable(f"could not read the form: {e}") from e

    # VERIFY BEFORE WRITING. A renamed field must not fill silently — the
    # download would be a pristine blank that looks answered.
    wanted = {field_map[k] for k in values}
    missing = wanted - present
    if missing:
        logger.warning(
            "%s field names moved (revision change?): missing=%s", label, sorted(missing))
        raise FormUnavailable(
            "the IRS form changed shape — download the blank and fill it directly")

    writer = PdfWriter(clone_from=reader)
    page_values = {field_map[k]: v for k, v in values.items()}
    try:
        for page in writer.pages:
            if page.get("/Annots"):
                writer.update_page_form_field_values(page, page_values)
        # Keep it fillable: the practitioner may need to correct a box,
        # and they still have to sign it.
        writer.set_need_appearances_writer(True)
    except Exception as e:
        raise FormUnavailable(f"could not fill the form: {e}") from e

    buf = io.BytesIO()
    writer.write(buf)
    out = buf.getvalue()
    if not out.startswith(b"%PDF"):
        raise FormUnavailable("filled form came back malformed")

    # READ IT BACK. Existence of a field is not proof a value took: the
    # W-9's Line 3a checkbox accepted a write and stayed /Off, because each
    # kid widget has its own on-state. A form that returns 200 with empty
    # boxes is the worst outcome here — it looks answered all the way to
    # whoever receives it — so the write is verified rather than assumed.
    try:
        back = PdfReader(io.BytesIO(out)).get_fields() or {}
    except Exception as e:
        raise FormUnavailable(f"could not verify the filled form: {e}") from e
    for key, intended in values.items():
        got = back.get(field_map[key], {}).get("/V")
        if str(got or "") != str(intended):
            logger.warning("%s %s did not take: wrote %r, read %r",
                           label, key, intended, got)
            raise FormUnavailable(
                "the form did not accept our values — download the blank "
                "and fill it directly")
    return out


def fill_w9(profile: Dict[str, Any], business_name: str = "") -> bytes:
    """The official W-9, with our facts written into it."""
    return _fill_official(W9_URL, W9_FIELDS, w9_values(profile, business_name), "W-9")


# ══════════════════════════════════════════════════════════════════════
# FORM SS-4 — Application for Employer Identification Number
# ══════════════════════════════════════════════════════════════════════
#
# WHY A FILLED SS-4 AT ALL. The fastest route to an EIN is the IRS online
# application, and the About Your Business EIN step sends people there
# with their answers laid out. But the online application is closed to
# anyone without an SSN/ITIN, has opening hours, and times out after 15
# idle minutes; for those the SS-4 goes by fax or mail. It goes to the
# IRS itself, so — unlike the 990 — a filled paper form IS filable.
#
# THE FIELD MAP (Rev. December 2025), matched to each printed line by
# widget position on the live form, and the two Yes/No pairs confirmed by
# rendering the page (the words "Yes"/"No" are drawn, not text, so a
# text-position match alone could not tell the boxes apart):
#
#   f1_2         Line 1   Legal name of entity
#   f1_3         Line 2   Trade name (if different)
#   f1_5 / f1_6  Line 4a/4b  Mailing address / city, state, ZIP
#   f1_10        Line 7a  Name of responsible party
#   c1_1[0]/[1]  Line 8a  Is this an LLC?  Yes = /1, No = /2
#   f1_12        Line 8b  Number of LLC members
#   c1_2[0]      Line 8c  LLC organised in the United States?  Yes = /1
#   f1_31        Line 11  Date business started
#   f1_38        Line 17  Principal line of services provided
#   f1_44        Name and title (type or print)
#   f1_45        Applicant's telephone number
#
# DELIBERATELY NEVER FILLED:
#   7b (SSN/ITIN)  — the system never holds it and never asks for it.
#   9a (entity type for tax), 10 (reason for applying), 12 (closing month),
#   13-15 (employees and wages), 16 (principal activity box), 18 (prior
#   EIN) — each is a determination the owner or their accountant makes.
#   How an LLC is taxed in particular is not ours to guess.
#   The third-party designee block, the signature and the date.
SS4_URL = "https://www.irs.gov/pub/irs-pdf/fss4.pdf"
_S = "topmostSubform[0].Page1[0]"
SS4_YES = "/1"
SS4_NO = "/2"
SS4_FIELDS = {
    "legal_name": f"{_S}.f1_2[0]",
    "trade_name": f"{_S}.f1_3[0]",
    "mail_address": f"{_S}.Line4ReadOrder[0].f1_5[0]",
    "mail_city_state_zip": f"{_S}.Line4ReadOrder[0].f1_6[0]",
    "responsible_name": f"{_S}.f1_10[0]",
    "llc_yes": f"{_S}.c1_1[0]",
    "llc_no": f"{_S}.c1_1[1]",
    "llc_members": f"{_S}.f1_12[0]",
    "llc_in_us": f"{_S}.c1_2[0]",
    "date_started": f"{_S}.f1_31[0]",
    "services": f"{_S}.f1_38[0]",
    "signer": f"{_S}.f1_44[0]",
    "phone": f"{_S}.f1_45[0]",
}

_US_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
    "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
    "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "GU", "VI", "AS", "MP",
}

# Entity types that are unambiguously NOT an LLC. s_corp and nonprofit are
# absent on purpose: an LLC can elect S-corp status, and a nonprofit can be
# an LLC, so for those Line 8a is the owner's to answer.
_NOT_LLC = {"sole_prop", "partnership", "c_corp"}


def _us_date(iso: Any) -> Optional[str]:
    s = str(iso or "").strip()[:10]
    parts = s.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    y, m, d = parts
    return f"{m}/{d}/{y}"


def ss4_values(identity: Dict[str, Any], practitioner: Optional[Dict[str, Any]] = None,
               business_name: str = "", profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """The SS-4 boxes we will fill, from facts the practitioner recorded.

    `identity` is business_identity.get_identity(); `practitioner` the
    practitioner_profiles row; `profile` the business_profiles row (for
    what the business provides)."""
    pp = practitioner or {}
    bp = profile or {}
    out: Dict[str, str] = {}

    # Line 1 — only a REAL legal name. The display name stands in for a
    # missing legal name elsewhere; on an EIN application it would be a
    # wrong answer that looks right.
    legal = (identity.get("legal_name") or "").strip()
    if legal and not identity.get("legal_name_is_fallback"):
        out["legal_name"] = legal
        dba = (business_name or "").strip()
        if dba and dba.lower() != legal.lower():
            out["trade_name"] = dba

    addr = " ".join(p for p in [(identity.get("address_line1") or "").strip(),
                                (identity.get("address_line2") or "").strip()] if p)
    if addr:
        out["mail_address"] = addr
    csz = _city_state_zip(identity)
    if csz:
        out["mail_city_state_zip"] = csz

    who = (pp.get("full_legal_name") or "").strip()
    if who:
        out["responsible_name"] = who
        title = (pp.get("preferred_title") or "").strip()
        out["signer"] = f"{who}, {title}" if title else who

    et = (identity.get("entity_type") or "").strip().lower()
    formed_in = (identity.get("formation_state") or "").strip().upper()
    if et in ("single_member_llc", "multi_member_llc"):
        out["llc_yes"] = SS4_YES
        if et == "single_member_llc":
            out["llc_members"] = "1"
        if formed_in in _US_CODES:
            out["llc_in_us"] = SS4_YES
    elif et in _NOT_LLC:
        out["llc_no"] = SS4_NO

    started = _us_date(identity.get("formed_on"))
    if started:
        out["date_started"] = started

    services = (bp.get("business_subtype") or bp.get("deliverables_description") or "").strip()
    if services:
        out["services"] = services[:90]

    phone = (identity.get("phone") or "").strip()
    if phone:
        out["phone"] = phone
    return out


def fill_ss4(identity: Dict[str, Any], practitioner: Optional[Dict[str, Any]] = None,
             business_name: str = "", profile: Optional[Dict[str, Any]] = None) -> bytes:
    """The official SS-4, prefilled, unsigned and still fillable."""
    return _fill_official(SS4_URL, SS4_FIELDS,
                          ss4_values(identity, practitioner, business_name, profile), "SS-4")
