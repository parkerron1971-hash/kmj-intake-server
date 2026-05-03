"""
brand_engine_router.py — HTTP surface for Brand Engine v1.

All endpoints live under /brand. Registered before public_site_router
in kmj_intake_automation.py (which still owns the catch-all /{path:path}).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import brand_engine

router = APIRouter(prefix="/brand", tags=["brand"])
logger = logging.getLogger("brand_engine_router")


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "brand-engine"})


@router.get("/bundle/{business_id}")
def bundle(business_id: str) -> JSONResponse:
    try:
        b = brand_engine.get_bundle(business_id)
        return JSONResponse({"ok": True, "bundle": b})
    except Exception as e:
        logger.warning(f"bundle composition failed: {e}")
        raise HTTPException(status_code=500, detail=f"bundle composition failed: {e}")


@router.post("/save/{business_id}")
def save(business_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Body: {kit: {...}}"""
    kit = body.get("kit") if isinstance(body, dict) else None
    if not isinstance(kit, dict):
        raise HTTPException(status_code=400, detail="missing or invalid kit in body")
    bundle = brand_engine.save_brand_kit(business_id, kit)
    return JSONResponse({"ok": True, "bundle": bundle})


@router.post("/snapshot/restore/{business_id}")
def restore(business_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Body: {snapshot_idx: 0|1}"""
    try:
        idx = int((body or {}).get("snapshot_idx", 0))
    except (TypeError, ValueError):
        idx = 0
    bundle = brand_engine.restore_snapshot(business_id, idx)
    return JSONResponse({"ok": True, "bundle": bundle})


@router.post("/generate-from-context/{business_id}")
def generate(business_id: str) -> JSONResponse:
    result = brand_engine.generate_from_context(business_id)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.post("/learn-from-url/{business_id}")
def learn(business_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Body: {url: "https://..."}"""
    url = (body or {}).get("url") if isinstance(body, dict) else None
    if not url:
        raise HTTPException(status_code=400, detail="missing url")
    result = brand_engine.learn_from_url(business_id, url)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)
