"""
brand_engine_router.py — HTTP surface for Brand Engine v1.

All endpoints live under /brand. Registered before public_site_router
in kmj_intake_automation.py (which still owns the catch-all /{path:path}).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
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


# ─── Brand Assets (Pass 2.5a) ──────────────────────────────────

@router.post("/asset/upload")
async def upload_brand_asset(
    business_id: str = Form(...),
    variant: str = Form(...),
    file: UploadFile = File(...),
) -> JSONResponse:
    """Upload an asset variant. Multipart form: business_id, variant, file.
    Variants: primary, logo_light, logo_dark, square, favicon, social_card."""
    file_bytes = await file.read()
    result = brand_engine.upload_asset(
        business_id=business_id,
        variant=variant,
        file_bytes=file_bytes,
        filename=file.filename or "upload.png",
        content_type=file.content_type or "image/png",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Upload failed"))
    return JSONResponse(result)


@router.post("/asset/remove/{business_id}")
def remove_brand_asset(business_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Body: {variant: 'primary' | 'logo_dark' | ...}"""
    variant = (body or {}).get("variant") if isinstance(body, dict) else None
    if not variant:
        raise HTTPException(status_code=400, detail="Missing variant")
    result = brand_engine.remove_asset(business_id, variant)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Remove failed"))
    return JSONResponse(result)
