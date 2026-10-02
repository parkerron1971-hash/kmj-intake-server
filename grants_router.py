"""
grants_router.py — THE FEDERAL LANE, endpoints (2026-08-28).

POST /grants/{business_id}/search/federal        run one federal search
GET  /grants/{business_id}/opportunity/{opp_id}  one opportunity, in full
GET  /grants/{business_id}/profile               what the lane knows about you

WHY THIS ONE IS NOT METERED, WHEN SOURCING IS
  The sourcing desk spends a model call per search and is metered and
  tier-gated accordingly. This lane spends an HTTP request to a public
  government API that asks for no key. There is nothing to bill, and
  billing it anyway would teach a practitioner that looking costs money
  — which is the opposite of the habit the whole arc needs.

  So the only guard is a rate limit, and it is a runaway guard rather
  than a ration: it exists so a retry loop cannot hammer a public
  service in our name.

THE APPLICANT TYPE IS READ, NEVER ACCEPTED
  Eligibility filtering keys off the organisation's applicant type, and
  that comes from `businesses.settings.funder_profile` — the record the
  practitioner filled in themselves. It is deliberately NOT a request
  parameter. A client that could pass its own applicant type could ask
  to be told it qualifies for things it does not, and the one job of
  this endpoint is to be trusted about exactly that.

AN EMPTY RESULT AND A BROKEN LANE ARE DIFFERENT ANSWERS
  grants_federal raises GrantsUnavailable rather than returning nothing
  when Grants.gov cannot be reached or refuses the search. That becomes
  a 503 with a plain sentence, never `{"matches": []}`. A practitioner
  told "no federal grants match you" when the truth is "the search did
  not run" concludes something false about their organisation, and stops
  looking.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import grants_federal
import rate_limit
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("grants_router")

router = APIRouter(prefix="/grants", tags=["grants"])

_KEYWORD_MAX = 200


def _reader(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner, active accountant, or a seated member.

    Reading is free here, so this is the wider gate rather than the
    owner-only one the sourcing desk uses for a search that spends money.

    select=* rather than a named column list — the sourcing desk took a
    platform-wide outage from naming a column this schema does not have
    (PostgREST answers an unknown column with a 400, which reads all the
    way up as "business not found")."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    from business_collaborators_router import is_active_accountant
    if is_active_accountant(business_id, str(user.id)):
        return row
    from business_users_router import require_role
    require_role(business_id, str(user.id), "viewer")
    return row


def funder_profile(biz_row: Dict[str, Any]) -> Dict[str, Any]:
    """The organisation profile the practitioner filled in on the
    frontend. Same blob, same key — see funderProfile.ts.

    Tolerant in exactly the same way the reader on that side is: an
    unknown shape reads as an empty profile rather than throwing, so a
    settings blob written by an older build can never take the lane
    down."""
    settings = biz_row.get("settings")
    if not isinstance(settings, dict):
        return {}
    profile = settings.get("funder_profile")
    if not isinstance(profile, dict):
        return {}
    return {k: v for k, v in profile.items() if isinstance(v, str) and v.strip()}


def _keywords_from_profile(profile: Dict[str, Any]) -> str:
    """A default search for an organisation that has not typed one.

    Built from what they do, not from their name — a funder has never
    heard of them, and searching their own name returns nothing and
    reads as "there is no money for us"."""
    for key in ("populations_served", "program_summary", "service_area"):
        value = (profile.get(key) or "").strip()
        if value:
            return value[:_KEYWORD_MAX]
    return ""


def _limited(business_id: str) -> None:
    if not rate_limit.allow("grants_search", business_id):
        raise HTTPException(429, {
            "error": "rate_limited",
            "retry_after": rate_limit.retry_after("grants_search"),
            "message": ("That is a lot of searches in one minute. Give it a "
                        "moment — Grants.gov is a public service and we do "
                        "not hammer it."),
        })


class FederalSearchBody(BaseModel):
    keyword: Optional[str] = None
    include_forecasts: bool = True
    rows: Optional[int] = None
    agencies: Optional[str] = None


@router.get("/{business_id}/profile")
def profile(business_id: str,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """What the lane will use, so the UI can say so before the search
    rather than after it."""
    biz_row = _reader(business_id, user)
    prof = funder_profile(biz_row)
    applicant_type = prof.get("applicant_type")
    codes = grants_federal.codes_for_applicant_type(applicant_type)
    return {
        "ok": True,
        "applicant_type": applicant_type,
        "gates_decided": bool(codes),
        "eligibility_codes": codes,
        "eligibility_labels": [
            grants_federal.ELIGIBILITY_LABELS.get(c, c) for c in codes
        ],
        "applicant_type_note": grants_federal.APPLICANT_TYPE_NOTES.get(
            applicant_type or ""),
        "default_keyword": _keywords_from_profile(prof),
    }


@router.post("/{business_id}/search/federal")
def search_federal(business_id: str, body: FederalSearchBody,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _reader(business_id, user)
    _limited(business_id)

    prof = funder_profile(biz_row)
    keyword = (body.keyword or "").strip() or _keywords_from_profile(prof)
    if len(keyword) > _KEYWORD_MAX:
        raise HTTPException(400, "that search is too long — trim it to the essentials")

    try:
        result = grants_federal.search(
            keyword=keyword,
            # Read from the profile, never from the request body.
            applicant_type=prof.get("applicant_type"),
            include_forecasts=bool(body.include_forecasts),
            rows=body.rows or grants_federal.DEFAULT_ROWS,
            agencies=(body.agencies or "").strip() or None,
        )
    except grants_federal.GrantsUnavailable as e:
        # 503, never an empty list. See the module header.
        raise HTTPException(503, {
            "error": "grants_gov_unavailable",
            "message": (f"{e} This is Grants.gov being unreachable, not a "
                        f"finding about your organization — try again shortly."),
        })

    result["ok"] = True
    result["keyword"] = keyword
    return result


@router.get("/{business_id}/opportunity/{opportunity_id}")
def opportunity(business_id: str, opportunity_id: str,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(business_id, user)
    _limited(business_id)

    if not opportunity_id.isdigit():
        raise HTTPException(400, "that is not a Grants.gov opportunity id")

    try:
        full = grants_federal.enrich(opportunity_id)
    except grants_federal.GrantsUnavailable as e:
        raise HTTPException(503, {
            "error": "grants_gov_unavailable",
            "message": f"{e} Try again shortly.",
        })
    return {"ok": True, "opportunity": full}
