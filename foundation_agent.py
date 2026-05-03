"""
foundation_agent.py — Foundation Track agent for the Solutionist System.

Drives the 7-phase legal/operational setup:
  1. Entity Formation
  2. EIN
  3. Tax Setup
  4. Operating Agreement
  5. Bank Account
  6. Licenses
  7. Insurance / Policies

When all 7 phases are marked complete the business gets the
"Business In The Clear" badge (businesses.in_the_clear = true).

All Anthropic calls happen here on the server (never in the client).
Outputs that touch legal/tax matters carry a not-legal-advice disclaimer
constant defined below.

Tables:
  foundation_progress (one row per business per phase)
  foundation_documents (artifacts: entity recs, OAs, policies, licenses)
  state_filing_data (50-state seed; only Michigan is verified)
  businesses.in_the_clear, businesses.in_the_clear_at
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from anthropic import Anthropic

logger = logging.getLogger("foundation_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] foundation: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


HTTP_TIMEOUT = 20.0
PHASES = [1, 2, 3, 4, 5, 6, 7]
PHASE_NAMES = {
    1: "Entity Formation",
    2: "EIN",
    3: "Tax Setup",
    4: "Operating Agreement",
    5: "Bank Account",
    6: "Licenses",
    7: "Insurance and Policies",
}

DISCLAIMER = (
    "This output is generated for informational purposes only. It is not legal, "
    "tax, or financial advice. Consult a licensed attorney or CPA before acting "
    "on any specific recommendation."
)

ANTHROPIC_MODEL = "claude-sonnet-4-5"
ANTHROPIC_MAX_TOKENS = 12000


# ──────────────────────────────────────────────────────────────
# Supabase helpers (mirrors sms_service.py pattern)
# ──────────────────────────────────────────────────────────────

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_anon() -> str:
    return os.environ.get("SUPABASE_ANON", "")


def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _sb_get(client: httpx.AsyncClient, path: str) -> Optional[Any]:
    try:
        r = await client.get(f"{_sb_url()}/rest/v1{path}",
                             headers=_sb_headers(), timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"sb GET {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb GET {path} failed: {e}")
        return None


async def _sb_post(client: httpx.AsyncClient, path: str, body: Any) -> Optional[Any]:
    try:
        r = await client.post(f"{_sb_url()}/rest/v1{path}",
                              headers=_sb_headers(),
                              content=json.dumps(body),
                              timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"sb POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb POST {path} failed: {e}")
        return None


async def _sb_patch(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> Optional[Any]:
    try:
        r = await client.patch(f"{_sb_url()}/rest/v1{path}",
                               headers=_sb_headers(),
                               content=json.dumps(body),
                               timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"sb PATCH {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb PATCH {path} failed: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# Progress: read, ensure rows, update
# ──────────────────────────────────────────────────────────────

async def ensure_progress_rows(business_id: str) -> None:
    """Make sure the 7 phase rows exist for this business. Idempotent."""
    async with httpx.AsyncClient() as client:
        existing = await _sb_get(
            client, f"/foundation_progress?business_id=eq.{business_id}&select=phase"
        )
        existing_phases = {row["phase"] for row in (existing or [])}
        missing = [p for p in PHASES if p not in existing_phases]
        if not missing:
            return
        rows = [
            {"business_id": business_id, "phase": p, "status": "not_started", "data": {}}
            for p in missing
        ]
        await _sb_post(client, "/foundation_progress", rows)


async def get_progress(business_id: str) -> Dict[str, Any]:
    """Return the full 7-phase progress shape + in_the_clear flag."""
    await ensure_progress_rows(business_id)
    async with httpx.AsyncClient() as client:
        rows = await _sb_get(
            client,
            f"/foundation_progress?business_id=eq.{business_id}"
            f"&select=phase,status,data,completed_at,updated_at&order=phase.asc",
        ) or []
        biz = await _sb_get(
            client,
            f"/businesses?id=eq.{business_id}&select=in_the_clear,in_the_clear_at",
        ) or []
    by_phase = {row["phase"]: row for row in rows}
    phases = []
    for p in PHASES:
        row = by_phase.get(p) or {"phase": p, "status": "not_started", "data": {}}
        phases.append({
            "phase": p,
            "name": PHASE_NAMES[p],
            "status": row.get("status") or "not_started",
            "data": row.get("data") or {},
            "completed_at": row.get("completed_at"),
            "updated_at": row.get("updated_at"),
        })
    completed = sum(1 for ph in phases if ph["status"] == "complete")
    biz_row = (biz or [{}])[0] if biz else {}
    return {
        "business_id": business_id,
        "phases": phases,
        "completed_count": completed,
        "total": len(PHASES),
        "in_the_clear": bool(biz_row.get("in_the_clear")),
        "in_the_clear_at": biz_row.get("in_the_clear_at"),
    }


async def update_phase(
    business_id: str,
    phase: int,
    status: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Patch a phase row. Recomputes in_the_clear if all 7 are complete."""
    if phase not in PHASES:
        return {"ok": False, "error": f"phase must be 1..7, got {phase}"}
    if status and status not in {"not_started", "in_progress", "complete", "skipped"}:
        return {"ok": False, "error": f"invalid status {status}"}
    await ensure_progress_rows(business_id)
    payload: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if status:
        payload["status"] = status
        if status == "complete":
            payload["completed_at"] = payload["updated_at"]
    if data is not None:
        payload["data"] = data
    async with httpx.AsyncClient() as client:
        await _sb_patch(
            client,
            f"/foundation_progress?business_id=eq.{business_id}&phase=eq.{phase}",
            payload,
        )
    await _recompute_in_the_clear(business_id)
    return {"ok": True, "phase": phase, "status": status}


async def phase_completed(business_id: str, phase: int) -> Dict[str, Any]:
    return await update_phase(business_id, phase, status="complete")


async def _recompute_in_the_clear(business_id: str) -> None:
    """Set businesses.in_the_clear=true when all 7 phases are complete."""
    async with httpx.AsyncClient() as client:
        rows = await _sb_get(
            client,
            f"/foundation_progress?business_id=eq.{business_id}&select=phase,status",
        ) or []
        complete = {r["phase"] for r in rows if r.get("status") == "complete"}
        all_done = all(p in complete for p in PHASES)
        biz = await _sb_get(
            client,
            f"/businesses?id=eq.{business_id}&select=in_the_clear",
        ) or []
        currently = bool((biz or [{}])[0].get("in_the_clear")) if biz else False
        if all_done and not currently:
            await _sb_patch(
                client,
                f"/businesses?id=eq.{business_id}",
                {"in_the_clear": True, "in_the_clear_at": datetime.now(timezone.utc).isoformat()},
            )
        elif (not all_done) and currently:
            await _sb_patch(
                client,
                f"/businesses?id=eq.{business_id}",
                {"in_the_clear": False, "in_the_clear_at": None},
            )


# ──────────────────────────────────────────────────────────────
# Entity recommendation (Phase 1) — Claude-backed
# ──────────────────────────────────────────────────────────────

def is_foreign_entity(situation: Dict[str, Any]) -> bool:
    """True if the entity has a non-US owner (BOI Beneficial Ownership applies)."""
    if not situation:
        return False
    if situation.get("foreign_owner") is True:
        return True
    owners = situation.get("owners") or []
    for o in owners:
        if isinstance(o, dict) and o.get("country") and o.get("country") != "US":
            return True
        if isinstance(o, dict) and o.get("foreign") is True:
            return True
    return False


def _entity_prompt(situation: Dict[str, Any]) -> str:
    return (
        "You are advising a small US business owner on entity formation. "
        "Recommend the most appropriate entity type (Sole Proprietor, LLC, "
        "Single-Member LLC, Multi-Member LLC, S-Corp election on LLC, C-Corp). "
        "Be specific to this owner's situation. Output strict JSON only with the "
        "shape: {\"recommended\": \"LLC\", \"reasoning\": \"...\", \"alternatives\": "
        "[{\"type\": \"Sole Proprietor\", \"why_not\": \"...\"}], \"next_steps\": "
        "[\"...\"]}.\n\n"
        f"Owner situation:\n{json.dumps(situation, indent=2)}\n"
    )


async def recommend_entity(business_id: str, situation: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not configured"}
    foreign = is_foreign_entity(situation)
    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            messages=[{"role": "user", "content": _entity_prompt(situation)}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            parsed = json.loads(text[start:end + 1]) if start >= 0 and end > start else {"raw": text}
    except Exception as e:
        logger.error(f"recommend_entity Anthropic call failed: {e}")
        return {"ok": False, "error": str(e)}

    parsed["disclaimer"] = DISCLAIMER
    parsed["foreign_entity"] = foreign
    parsed["boi_required"] = foreign

    async with httpx.AsyncClient() as client:
        await _sb_post(client, "/foundation_documents", {
            "business_id": business_id,
            "phase": 1,
            "kind": "entity_recommendation",
            "title": f"Entity recommendation: {parsed.get('recommended', 'unspecified')}",
            "content": json.dumps(parsed, indent=2),
            "metadata": {"situation": situation, "foreign_entity": foreign},
        })
    await update_phase(business_id, 1, status="in_progress", data={"recommendation": parsed})
    return {"ok": True, "recommendation": parsed}


# ──────────────────────────────────────────────────────────────
# State filing data (Phase 1)
# ──────────────────────────────────────────────────────────────

async def get_state_filing_info(state_code: str) -> Dict[str, Any]:
    state_code = (state_code or "").strip().upper()
    if not state_code:
        return {"ok": False, "error": "state_code required"}
    async with httpx.AsyncClient() as client:
        rows = await _sb_get(
            client,
            f"/state_filing_data?state_code=eq.{state_code}",
        ) or []
    if not rows:
        return {"ok": False, "error": f"state {state_code} not found"}
    row = rows[0]
    row["disclaimer"] = DISCLAIMER
    if not row.get("verified"):
        row["warning"] = (
            f"Filing data for {row.get('state_name', state_code)} has not been "
            "verified. Confirm fees and URLs at the state's official Secretary "
            "of State website before filing."
        )
    return {"ok": True, "state": row}


# ──────────────────────────────────────────────────────────────
# Document generators (Phases 4 and 7)
# ──────────────────────────────────────────────────────────────
# These are working stubs — they produce real, usable plain-text
# documents and persist them to foundation_documents. PDF rendering
# is intentionally deferred to v2.
# TODO(foundation-track-v2): render these to PDF via reportlab/weasyprint
# and upload to Supabase Storage. For now we store the source text and
# the frontend renders it inline.

def _operating_agreement_text(business_name: str, state_code: str, members: List[Dict[str, Any]]) -> str:
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    lines: List[str] = []
    lines.append(f"OPERATING AGREEMENT OF {business_name.upper()}, LLC")
    lines.append("")
    lines.append(f"This Operating Agreement (the \"Agreement\") of {business_name}, LLC, ")
    lines.append(f"a {state_code} limited liability company (the \"Company\"), is entered ")
    lines.append(f"into and effective as of {today}, by and among the persons listed as ")
    lines.append("Members in this Agreement.")
    lines.append("")
    lines.append("ARTICLE 1 - FORMATION")
    lines.append(f"1.1 Name. The name of the Company is {business_name}, LLC.")
    lines.append(f"1.2 State of Formation. The Company is formed under the laws of {state_code}.")
    lines.append("1.3 Purpose. The Company is formed for any lawful purpose.")
    lines.append("")
    lines.append("ARTICLE 2 - MEMBERS AND OWNERSHIP")
    total = sum(float(m.get("ownership_pct") or 0) for m in members) or 100.0
    for m in members:
        name = m.get("name") or "Unnamed Member"
        pct = m.get("ownership_pct")
        if pct is None and len(members) > 0:
            pct = round(100.0 / len(members), 4)
        lines.append(f"  Member: {name} - Ownership: {pct}%")
    if abs(total - 100.0) > 0.5 and total != 0:
        lines.append(f"  (Note: ownership percentages provided sum to {total}%, not 100%.)")
    lines.append("")
    lines.append("ARTICLE 3 - MANAGEMENT")
    if len(members) == 1:
        lines.append("3.1 Member-Managed. The Company is managed by its sole Member.")
    else:
        lines.append("3.1 Member-Managed. The Company is managed by its Members in proportion to ownership unless otherwise agreed.")
    lines.append("")
    lines.append("ARTICLE 4 - CAPITAL CONTRIBUTIONS")
    lines.append("4.1 Initial Contributions. Each Member's initial contribution is recorded in the Company's books.")
    lines.append("4.2 Additional Contributions. No Member is required to make additional contributions absent unanimous consent.")
    lines.append("")
    lines.append("ARTICLE 5 - DISTRIBUTIONS")
    lines.append("5.1 Distributions are made pro rata in accordance with each Member's Ownership Percentage.")
    lines.append("")
    lines.append("ARTICLE 6 - DISSOLUTION")
    lines.append("6.1 The Company may be dissolved by unanimous consent of the Members or as required by law.")
    lines.append("")
    lines.append("ARTICLE 7 - GOVERNING LAW")
    lines.append(f"7.1 This Agreement is governed by the laws of the State of {state_code}.")
    lines.append("")
    lines.append("SIGNATURES")
    for m in members:
        name = m.get("name") or "Unnamed Member"
        lines.append(f"  ____________________________   {name}")
    lines.append("")
    lines.append("---")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


async def generate_operating_agreement(
    business_id: str,
    business_name: str,
    state_code: str,
    members: List[Dict[str, Any]],
) -> Dict[str, Any]:
    # Brand Engine v1: pull canonical legal name + governing state from
    # the bundle. Operating agreements MUST use the practitioner's full
    # legal name on the signature line — refuse to generate otherwise.
    bundle = None
    try:
        from brand_engine import get_bundle as _be_get_bundle
        bundle = _be_get_bundle(business_id)
    except Exception as _e:
        bundle = None

    if bundle:
        legal_name = (bundle.get("practitioner") or {}).get("full_legal_name")
        if not legal_name:
            return {
                "ok": False,
                "error": (
                    "I need your full legal name before I can draft an operating "
                    "agreement — tell me what name should appear on legal documents."
                ),
                "missing_field": "practitioner.full_legal_name",
            }
        canonical_state = (bundle.get("legal") or {}).get("governing_state") or state_code
        canonical_business = (bundle.get("business") or {}).get("name") or business_name
        # Promote the practitioner as the first signing member if the
        # caller didn't already pass one. Caller-supplied members win.
        members = members or [{"name": legal_name, "ownership_pct": 100}]
        state_code = canonical_state
        business_name = canonical_business

    text = _operating_agreement_text(business_name or "Your Company", state_code or "MI", members or [])
    async with httpx.AsyncClient() as client:
        saved = await _sb_post(client, "/foundation_documents", {
            "business_id": business_id,
            "phase": 4,
            "kind": "operating_agreement",
            "title": f"Operating Agreement - {business_name}",
            "content": text,
            "metadata": {"state": state_code, "members": members},
        })
    await update_phase(business_id, 4, status="in_progress", data={"has_draft": True})
    return {
        "ok": True,
        "document_id": (saved or [{}])[0].get("id") if saved else None,
        "content": text,
        "disclaimer": DISCLAIMER,
    }


def _policy_prompt(kind: str, business_data: Dict[str, Any]) -> str:
    label = "Privacy Policy" if kind == "privacy_policy" else "Terms of Service"
    return (
        f"Draft a {label} for the business below. Use plain English, US small-business "
        "norms, and standard structural sections. Do not use placeholder bracket "
        "tokens like [INSERT NAME] - fill what you can from the data. Output the "
        "policy text only - no preamble, no markdown fences.\n\n"
        f"Business data:\n{json.dumps(business_data, indent=2)}\n"
    )


async def _generate_policy(business_id: str, kind: str, business_data: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not configured"}

    # Brand Engine v1: enrich business_data with canonical bundle fields so
    # privacy policies and TOS reflect the actual legal name, governing
    # state, contact email, and full required-disclaimer set. Caller-
    # supplied keys still win — bundle only fills gaps.
    try:
        from brand_engine import get_bundle as _be_get_bundle, DISCLAIMER_PHRASES as _DPH
        _bundle = _be_get_bundle(business_id) or {}
        _legal = _bundle.get("legal") or {}
        _practitioner = _bundle.get("practitioner") or {}
        _footer = _bundle.get("footer") or {}
        _biz = _bundle.get("business") or {}
        business_data = dict(business_data or {})
        business_data.setdefault("business_name", _biz.get("name"))
        business_data.setdefault("governing_state", _legal.get("governing_state"))
        business_data.setdefault("contact_email", _footer.get("contact_email"))
        business_data.setdefault("legal_name", _practitioner.get("full_legal_name"))
        required = _legal.get("required_disclaimers") or []
        if required:
            business_data.setdefault(
                "required_disclaimers",
                [_DPH.get(d, d) for d in required],
            )
    except Exception as _e:
        logger.warning(f"_generate_policy: bundle enrichment skipped: {_e}")

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            messages=[{"role": "user", "content": _policy_prompt(kind, business_data)}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.error(f"_generate_policy {kind} failed: {e}")
        return {"ok": False, "error": str(e)}

    full = text.rstrip() + "\n\n---\n" + DISCLAIMER
    title = "Privacy Policy" if kind == "privacy_policy" else "Terms of Service"
    async with httpx.AsyncClient() as client:
        saved = await _sb_post(client, "/foundation_documents", {
            "business_id": business_id,
            "phase": 7,
            "kind": kind,
            "title": title,
            "content": full,
            "metadata": {"business_data": business_data},
        })
    await update_phase(business_id, 7, status="in_progress", data={f"has_{kind}": True})
    return {
        "ok": True,
        "document_id": (saved or [{}])[0].get("id") if saved else None,
        "content": full,
        "disclaimer": DISCLAIMER,
    }


async def generate_privacy_policy(business_id: str, business_data: Dict[str, Any]) -> Dict[str, Any]:
    return await _generate_policy(business_id, "privacy_policy", business_data)


async def generate_terms_of_service(business_id: str, business_data: Dict[str, Any]) -> Dict[str, Any]:
    return await _generate_policy(business_id, "terms_of_service", business_data)


# ──────────────────────────────────────────────────────────────
# Chief context block — injected into the Chief system prompt
# ──────────────────────────────────────────────────────────────

async def chief_context_block(business_id: str) -> str:
    """Return a markdown block describing Foundation Track state.
    The Chief uses this to give grounded answers about legal setup status.
    Returns empty string when there's nothing useful to say.
    """
    if not business_id:
        return ""
    try:
        progress = await get_progress(business_id)
    except Exception as e:
        logger.warning(f"chief_context_block failed: {e}")
        return ""
    phases = progress.get("phases") or []
    if not phases:
        return ""
    lines: List[str] = []
    lines.append("## Foundation Track")
    if progress.get("in_the_clear"):
        lines.append("This business is BUSINESS IN THE CLEAR - all 7 phases complete.")
    else:
        lines.append(
            f"Progress: {progress.get('completed_count', 0)} of "
            f"{progress.get('total', 7)} phases complete."
        )
    for ph in phases:
        marker = {
            "complete": "[x]",
            "in_progress": "[~]",
            "skipped": "[-]",
            "not_started": "[ ]",
        }.get(ph.get("status", "not_started"), "[ ]")
        lines.append(f"  {marker} Phase {ph['phase']}: {ph['name']} ({ph['status']})")
    lines.append(
        "When the user asks about legal setup, entity formation, EIN, taxes, "
        "operating agreements, bank accounts, licenses, or insurance/policies, "
        "use this state to ground your answer. Suggest they open Foundation Track "
        "for guided help. Never give specific legal or tax advice - always defer to "
        "a licensed attorney or CPA for binding decisions."
    )
    return "\n".join(lines)
