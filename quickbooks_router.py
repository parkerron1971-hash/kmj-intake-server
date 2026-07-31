"""
quickbooks_router.py — Rails Arc 1: the QuickBooks bridge.

The bridge is PUSH-ONLY by ruling: we send clean entries out; we never
run a live two-way sync (that is where reconciliation nightmares come
from). The one thing built well here is the MAPPING LAYER — our chart
of accounts → their chart of accounts, configured once per business.
Every export (IIF today, QBO API journal pushes in Arc 1b) resolves
account names through it.

This pass (Arc 1a — no Intuit credentials needed):
  GET /quickbooks/mappings?biz=   — our COA joined with any mappings,
                                    plus the business's book-of-record
  PUT /quickbooks/mappings?biz=   — upsert mappings (list of
                                    {account_code, external_name});
                                    empty external_name deletes

Arc 1b adds: /connect/quickbooks OAuth, fetching the real QBO account
list (external_id), and the journal push. QB_CLIENT_ID/QB_CLIENT_SECRET
are already on Railway waiting for it.

Book-of-record (source-of-truth ruling, set per business):
  businesses.settings.financial.book_of_record = 'solutionist' (default)
  | 'quickbooks'. Smaller clients: we are the record and QB is optional;
  bigger clients already living in QB: they are the record, we sync out.
  Stored in settings by the frontend; surfaced here so one GET paints
  the whole admin section.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("quickbooks_router")

router = APIRouter(prefix="/quickbooks", tags=["quickbooks"])

PROVIDER = "quickbooks"


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def get_mappings(biz: str) -> Dict[str, Dict[str, Any]]:
    """account_code -> mapping row. The export path calls this directly."""
    rows = sb_clients.sb_get_as_service(
        f"/coa_external_mappings?business_id=eq.{biz}&provider=eq.{PROVIDER}"
        f"&select=account_code,external_name,external_id,external_type&limit=500") or []
    return {r["account_code"]: r for r in rows}


@router.get("/mappings")
def list_mappings(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    b = _owner(biz, user)
    accounts = sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{biz}"
        f"&select=code,name,type,profit_first_bucket&order=code.asc&limit=500") or []
    mapped = get_mappings(biz)
    book_of_record = (((b.get("settings") or {}).get("financial") or {})
                      .get("book_of_record") or "solutionist")
    return {
        "book_of_record": book_of_record,
        "accounts": [
            {
                "code": a["code"],
                "name": a.get("name") or a["code"],
                "type": a.get("type"),
                "external_name": (mapped.get(a["code"]) or {}).get("external_name"),
                "external_id": (mapped.get(a["code"]) or {}).get("external_id"),
            }
            for a in accounts
        ],
        "mapped_count": len(mapped),
    }


class MappingItem(BaseModel):
    account_code: str
    external_name: str = ""


class PutMappingsBody(BaseModel):
    mappings: List[MappingItem]


@router.put("/mappings")
def put_mappings(biz: str, body: PutMappingsBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Upsert the business's mappings. An empty external_name clears the
    mapping (the export falls back to our account name)."""
    _owner(biz, user)
    valid_codes = {a["code"] for a in (sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{biz}&select=code&limit=500") or [])}

    saved, cleared, skipped = 0, 0, []
    for item in body.mappings:
        code = (item.account_code or "").strip()
        name = (item.external_name or "").strip()
        if code not in valid_codes:
            skipped.append(code)
            continue
        if not name:
            sb_clients.sb_delete_as_service(
                f"/coa_external_mappings?business_id=eq.{biz}"
                f"&provider=eq.{PROVIDER}&account_code=eq.{code}")
            cleared += 1
            continue
        sb_clients.sb_post_as_service(
            "/coa_external_mappings?on_conflict=business_id,provider,account_code",
            {"business_id": biz, "provider": PROVIDER,
             "account_code": code, "external_name": name[:120],
             "updated_at": datetime.now(timezone.utc).isoformat()},
            prefer="resolution=merge-duplicates,return=representation")
        saved += 1

    logger.info(f"[qb] mappings updated biz={biz[:8]} saved={saved} "
                f"cleared={cleared} skipped={len(skipped)}")
    return {"ok": True, "saved": saved, "cleared": cleared, "skipped": skipped}
