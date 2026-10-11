"""
voice_depth_router.py — HTTP surface for Pass 2.5b Brand Voice Depth.

All endpoints live under /voice. Registered before public_site_router
in kmj_intake_automation.py (which still owns /{path:path}).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Depends
from auth_supabase import require_user, AuthedUser
from fastapi.responses import JSONResponse

import voice_depth_agent

router = APIRouter(prefix="/voice", tags=["voice-depth"])
logger = logging.getLogger("voice_depth_router")


def _audit_rule_change(owner_id: str, verb: str, summary: str,
                       payload: Dict[str, Any]) -> None:
    """Ledger row for a voice-rule change made on a settings screen.

    The chat path is audited by record_chief_turn; these REST routes wrote
    nothing, so a rule added or removed in Brand Studio left no trace.
    Voice rules belong to the OWNER and shape every one of their
    businesses, so the row goes to each business they own (almost always
    one). Best-effort: a ledger hiccup never fails the owner's edit.
    """
    try:
        import audit_log
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/businesses?owner_id=eq.{owner_id}&select=id&limit=10") or []
        for r in rows:
            bid = (r or {}).get("id")
            if bid:
                audit_log.record(bid, actor_type="user", actor_id=owner_id,
                                 verb=verb, ok=True, summary=summary[:500],
                                 payload=payload, source="desktop")
    except Exception as e:
        logger.warning(f"voice rule audit failed: {e}")


def _short(rule: str, n: int = 80) -> str:
    rule = " ".join(str(rule or "").split())
    return rule if len(rule) <= n else rule[: n - 1].rstrip() + "…"


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "voice-depth"})


@router.get("/depth/{owner_id}")
def depth(owner_id: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    return JSONResponse({"ok": True, "voice": voice_depth_agent.get_voice_depth(owner_id)})


@router.post("/depth/{owner_id}/sample")
def save_sample(owner_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    """Body: {slot: 'discovery_followup'|'launch_announcement'|'casual_nurture', text: '...'}"""
    slot = (body or {}).get("slot")
    text = (body or {}).get("text")
    if not slot or not text:
        raise HTTPException(status_code=400, detail="Missing slot or text")
    result = voice_depth_agent.update_voice_sample(owner_id, slot, text)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "save failed"))
    return JSONResponse(result)


@router.post("/depth/{owner_id}/style")
def save_style(owner_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    """Body: {field: 'greeting_style'|'signoff_style', value: '...'}"""
    field = (body or {}).get("field")
    value = (body or {}).get("value")
    if not field or value is None:
        raise HTTPException(status_code=400, detail="Missing field or value")
    result = voice_depth_agent.update_voice_style(owner_id, field, value)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "save failed"))
    return JSONResponse(result)


@router.post("/depth/{owner_id}/rule/add")
def add_rule(owner_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    """Body: {list: 'voice_dos'|'voice_donts', rule: '...'}"""
    list_name = (body or {}).get("list")
    rule = (body or {}).get("rule")
    if not list_name or not rule:
        raise HTTPException(status_code=400, detail="Missing list or rule")
    result = voice_depth_agent.add_voice_rule(owner_id, list_name, rule)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "add failed"))
    if not result.get("duplicate"):
        kind = "do" if list_name == "voice_dos" else "don't"
        _audit_rule_change(owner_id, "add_voice_rule",
                           f"Added voice {kind}: {_short(rule)}",
                           {"list": list_name, "rule": str(rule)[:500]})
    return JSONResponse(result)


@router.post("/depth/{owner_id}/rule/remove")
def remove_rule(owner_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    """Body: {list: 'voice_dos'|'voice_donts', idx: 0, rule?: '<exact text>'}

    `rule` makes the removal name the rule by text; idx alone still works.
    """
    list_name = (body or {}).get("list")
    idx = (body or {}).get("idx")
    rule = (body or {}).get("rule")
    rule = rule.strip() if isinstance(rule, str) else ""
    if list_name is None or (idx is None and not rule):
        raise HTTPException(status_code=400, detail="Missing list or idx")
    idx_int = None
    if idx is not None:
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="idx must be an integer")
    result = voice_depth_agent.remove_voice_rule(owner_id, list_name, idx_int, rule or None)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "remove failed"))
    removed = str(result.get("removed") or "")
    _audit_rule_change(owner_id, "remove_voice_rule",
                       f"Voice rule removed: {_short(removed)}" if removed else "Voice rule removed",
                       {"list": list_name, "rule": removed[:500]})
    return JSONResponse(result)


# ─── The voice lab (Brand Studio phase 5) — see voice_lab.py ───────────
# Both read the owner's own samples and SUGGEST; neither writes anything.

@router.post("/lab/{owner_id}/analyze")
def lab_analyze(owner_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    """Body: {tone_words?: [...]} — words already chosen, so they aren't suggested again."""
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    import voice_lab
    try:
        return JSONResponse(voice_lab.analyze_voice(owner_id, (body or {}).get("tone_words") or []))
    except voice_lab.VoiceLabError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/lab/{owner_id}/test")
def lab_test(owner_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    """Body: {scenario: 'after_first_call'|'no_show'|'invite', business_name?, tone_words?}"""
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    import voice_lab
    b = body or {}
    try:
        return JSONResponse(voice_lab.test_voice(
            owner_id, str(b.get("scenario") or ""), str(b.get("business_name") or ""),
            b.get("tone_words") or []))
    except voice_lab.VoiceLabError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/depth/{owner_id}/observe")
def observe(owner_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    """Frontend calls when the user edits a Chief draft and sends it.
    Body: {original_pattern, edited_pattern, context, kind}.
    Silent — never errors, never toasts. Just records."""
    body = body or {}
    result = voice_depth_agent.record_edit_observation(
        owner_id,
        body.get("original_pattern", ""),
        body.get("edited_pattern", ""),
        body.get("context", ""),
        body.get("kind", "dont"),
    )
    return JSONResponse(result)


@router.post("/depth/{owner_id}/clear-observations")
def clear_observations(owner_id: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    if user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not your voice profile")
    """Called after the user accepts a proposed rule, so Chief doesn't
    re-propose the same pattern."""
    return JSONResponse(voice_depth_agent.clear_observations_after_rule(owner_id))
