"""
business_identity.py — one read/write path for who a business legally IS.

Before this module the same facts lived in up to four unconnected stores, so
a practitioner who entered their EIN in Foundation Phase 2 still saw
"— add your EIN in the 1099 panel —" on a 1099 draft.

Canonical store is `business_profiles` (one row per business, already keyed on
business_id and already holding governing_state). Reads fall back to the legacy
`businesses.settings.financial.payer` blob so nothing breaks for rows the
backfill has not touched; writes always go to the profile.

Everything here delegates to business_profile_agent so the JWT/RLS context
handling stays in exactly one place.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import business_profile_agent

logger = logging.getLogger(__name__)

# Columns added by APPLY-2026-08-07-business-identity.sql, plus governing_state
# which predates it.
IDENTITY_FIELDS = (
    "legal_name",
    "entity_type",
    "formation_state",
    "formed_on",
    "ein",
    "address_line1",
    "address_line2",
    "address_city",
    "address_state",
    "address_zip",
    "phone",
    "governing_state",
)

# The enum the DB CHECK constraint allows.
ENTITY_TYPES = (
    "sole_prop",
    "single_member_llc",
    "multi_member_llc",
    "partnership",
    "s_corp",
    "c_corp",
    "nonprofit",
)

# recommend_entity() asks the model for free text ("S-Corp election on LLC"),
# so anything stored has to come through here first.
_ENTITY_ALIASES = {
    "sole_prop": "sole_prop",
    "sole_proprietor": "sole_prop",
    "sole_proprietorship": "sole_prop",
    "soleprop": "sole_prop",
    "dba": "sole_prop",
    "single_member_llc": "single_member_llc",
    "single member llc": "single_member_llc",
    "smllc": "single_member_llc",
    "single-member llc": "single_member_llc",
    "multi_member_llc": "multi_member_llc",
    "multi member llc": "multi_member_llc",
    "multi-member llc": "multi_member_llc",
    "mmllc": "multi_member_llc",
    "partnership": "partnership",
    "general partnership": "partnership",
    "limited partnership": "partnership",
    "lp": "partnership",
    "llp": "partnership",
    "s_corp": "s_corp",
    "s corp": "s_corp",
    "s-corp": "s_corp",
    "scorp": "s_corp",
    "s corporation": "s_corp",
    "c_corp": "c_corp",
    "c corp": "c_corp",
    "c-corp": "c_corp",
    "ccorp": "c_corp",
    "c corporation": "c_corp",
    "corporation": "c_corp",
    "inc": "c_corp",
    "nonprofit": "nonprofit",
    "non-profit": "nonprofit",
    "501c3": "nonprofit",
    "501(c)(3)": "nonprofit",
}


def normalize_entity_type(raw: Any, member_count: Optional[int] = None) -> Optional[str]:
    """
    Map free text to the stored enum. Returns None when the text does not name
    an entity form we can act on — an unrecognized string must not be stored,
    because downstream tax math reads this field.

    A bare "LLC" is genuinely ambiguous, so it resolves only when member_count
    disambiguates it. Guessing single-member would be the same silent
    assumption this module exists to remove.
    """
    if not raw:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None

    if text in _ENTITY_ALIASES:
        return _ENTITY_ALIASES[text]

    # "S-Corp election on LLC" / "LLC taxed as an S-Corp" -> the election is
    # what drives the tax treatment, so it wins over the bare LLC mention.
    if re.search(r"\bs[\s\-_]?corp", text):
        return "s_corp"
    if re.search(r"\bc[\s\-_]?corp", text):
        return "c_corp"
    if "nonprofit" in text or "non-profit" in text or "501" in text:
        return "nonprofit"
    if "sole propriet" in text:
        return "sole_prop"

    if re.search(r"\bsingle[\s\-]?member\b", text):
        return "single_member_llc"
    if re.search(r"\bmulti[\s\-]?member\b", text):
        return "multi_member_llc"

    if re.search(r"\bllc\b", text):
        if member_count is not None:
            try:
                return "single_member_llc" if int(member_count) <= 1 else "multi_member_llc"
            except (TypeError, ValueError):
                return None
        return None

    if "partnership" in text:
        return "partnership"

    return None


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _legacy_payer(biz_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The pre-consolidation 1099 payer blob, if the caller handed us a row."""
    if not biz_row:
        return {}
    financial = ((biz_row.get("settings") or {}).get("financial") or {})
    return financial.get("payer") or {}


def get_identity(business_id: str,
                 biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Identity slice for a business. Profile values win; the legacy payer blob
    fills gaps so un-backfilled rows keep working.

    `biz_row` is optional — pass it when the caller already fetched the
    business (reports_router does) to avoid a second round trip. Without it
    the legacy fallback is simply skipped.
    """
    profile = {}
    if business_id:
        try:
            profile = business_profile_agent.get_profile(business_id) or {}
        except Exception as e:  # noqa: BLE001 — identity must never 500 a report
            logger.warning(f"get_identity profile fetch failed for {business_id}: {e}")
            profile = {}

    payer = _legacy_payer(biz_row)
    legacy_map = {
        "legal_name": payer.get("name"),
        "ein": payer.get("ein"),
        "address_line1": payer.get("line1"),
        "address_line2": payer.get("line2"),
        "address_city": payer.get("city"),
        "address_state": payer.get("state"),
        "address_zip": payer.get("zip"),
        "phone": payer.get("phone"),
    }

    out: Dict[str, Any] = {}
    for field in IDENTITY_FIELDS:
        out[field] = _clean(profile.get(field)) or _clean(legacy_map.get(field))

    # The display name is the last resort for a legal name — flagged so callers
    # can tell a real filed name from a fallback.
    out["legal_name_is_fallback"] = False
    if not out["legal_name"] and biz_row:
        out["legal_name"] = _clean(biz_row.get("name"))
        out["legal_name_is_fallback"] = bool(out["legal_name"])

    return out


def set_identity(business_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """
    Write identity fields to business_profiles. Unknown keys are dropped and
    None values are left alone (upsert_profile already ignores them), so a
    caller can send only what it collected.

    entity_type is normalized here rather than at the call site, so every
    writer gets the same treatment.
    """
    if not business_id:
        return None

    payload: Dict[str, Any] = {}
    member_count = fields.pop("member_count", None)

    for key, value in fields.items():
        if key not in IDENTITY_FIELDS:
            logger.debug(f"set_identity ignoring unknown field {key!r}")
            continue
        if value is None:
            continue
        if key == "entity_type":
            normalized = normalize_entity_type(value, member_count=member_count)
            if normalized is None:
                logger.info(
                    f"set_identity: entity_type {value!r} not recognized — not stored")
                continue
            payload[key] = normalized
        elif key in ("governing_state", "formation_state", "address_state"):
            cleaned = _clean(value)
            payload[key] = cleaned.upper()[:2] if cleaned else None
        else:
            payload[key] = _clean(value)

    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        return None

    try:
        return business_profile_agent.upsert_profile(business_id, payload)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"set_identity write failed for {business_id}: {e}")
        return None


def payer_block(business_id: str, biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Payer identity for 1099 drafts, assembled from the canonical store.
    Shape is unchanged from the original _payer_block so callers and the PDF
    writer need no changes.
    """
    ident = get_identity(business_id, biz_row)

    city_state_zip = ", ".join(
        p for p in [ident.get("address_city"), ident.get("address_state")] if p)
    if ident.get("address_zip"):
        city_state_zip = f"{city_state_zip} {ident['address_zip']}".strip(", ")

    return {
        "name": ident.get("legal_name") or "",
        "ein": ident.get("ein") or "",
        "line1": ident.get("address_line1") or "",
        "line2": ident.get("address_line2") or "",
        "city_state_zip": city_state_zip,
        "phone": ident.get("phone") or "",
        "complete": bool(ident.get("ein") and ident.get("address_line1")),
    }
