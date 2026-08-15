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


def fill_w9(profile: Dict[str, Any], business_name: str = "") -> bytes:
    """The official blank, with our facts written into it.

    Raises FormUnavailable rather than ever returning a form whose boxes
    did not take."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as e:  # pragma: no cover - dependency is pinned
        raise FormUnavailable("pypdf is not installed") from e

    blank = _fetch(W9_URL)
    values = w9_values(profile, business_name)
    if not values:
        raise FormUnavailable("nothing recorded to fill this form with")

    try:
        reader = PdfReader(io.BytesIO(blank))
        present = set((reader.get_fields() or {}).keys())
    except Exception as e:
        raise FormUnavailable(f"could not read the form: {e}") from e

    # VERIFY BEFORE WRITING. A renamed field must not fill silently — the
    # download would be a pristine blank that looks answered.
    wanted = {W9_FIELDS[k] for k in values}
    missing = wanted - present
    if missing:
        logger.warning(
            "W-9 field names moved (revision change?): missing=%s", sorted(missing))
        raise FormUnavailable(
            "the IRS form changed shape — download the blank and fill it directly")

    writer = PdfWriter(clone_from=reader)
    page_values = {W9_FIELDS[k]: v for k, v in values.items()}
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
    # Line 3a checkbox accepted a write and stayed /Off, because each kid
    # widget has its own on-state. A form that returns 200 with empty
    # boxes is the worst outcome here — it looks answered all the way to
    # the funder — so the write is verified rather than assumed.
    try:
        back = PdfReader(io.BytesIO(out)).get_fields() or {}
    except Exception as e:
        raise FormUnavailable(f"could not verify the filled form: {e}") from e
    for key, intended in values.items():
        got = back.get(W9_FIELDS[key], {}).get("/V")
        if str(got or "") != str(intended):
            logger.warning("W-9 %s did not take: wrote %r, read %r",
                           key, intended, got)
            raise FormUnavailable(
                "the form did not accept our values — download the blank "
                "and fill it directly")
    return out
