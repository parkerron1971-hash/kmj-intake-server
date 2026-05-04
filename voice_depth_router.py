"""
voice_depth_router.py — HTTP surface for Pass 2.5b Brand Voice Depth.

All endpoints live under /voice. Registered before public_site_router
in kmj_intake_automation.py (which still owns /{path:path}).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import voice_depth_agent

router = APIRouter(prefix="/voice", tags=["voice-depth"])
logger = logging.getLogger("voice_depth_router")


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "voice-depth"})


@router.get("/depth/{owner_id}")
def depth(owner_id: str) -> JSONResponse:
    return JSONResponse({"ok": True, "voice": voice_depth_agent.get_voice_depth(owner_id)})


@router.post("/depth/{owner_id}/sample")
def save_sample(owner_id: str, body: Dict[str, Any]) -> JSONResponse:
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
def save_style(owner_id: str, body: Dict[str, Any]) -> JSONResponse:
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
def add_rule(owner_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Body: {list: 'voice_dos'|'voice_donts', rule: '...'}"""
    list_name = (body or {}).get("list")
    rule = (body or {}).get("rule")
    if not list_name or not rule:
        raise HTTPException(status_code=400, detail="Missing list or rule")
    result = voice_depth_agent.add_voice_rule(owner_id, list_name, rule)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "add failed"))
    return JSONResponse(result)


@router.post("/depth/{owner_id}/rule/remove")
def remove_rule(owner_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Body: {list: 'voice_dos'|'voice_donts', idx: 0}"""
    list_name = (body or {}).get("list")
    idx = (body or {}).get("idx")
    if list_name is None or idx is None:
        raise HTTPException(status_code=400, detail="Missing list or idx")
    try:
        idx_int = int(idx)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="idx must be an integer")
    result = voice_depth_agent.remove_voice_rule(owner_id, list_name, idx_int)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "remove failed"))
    return JSONResponse(result)


@router.post("/depth/{owner_id}/observe")
def observe(owner_id: str, body: Dict[str, Any]) -> JSONResponse:
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
def clear_observations(owner_id: str) -> JSONResponse:
    """Called after the user accepts a proposed rule, so Chief doesn't
    re-propose the same pattern."""
    return JSONResponse(voice_depth_agent.clear_observations_after_rule(owner_id))
