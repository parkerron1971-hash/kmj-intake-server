"""What Chief knows: the owner's view of the business brain.

Layer Two, 2026-10-11. One read returns everything Chief carries for this
business (owner rules, other facts, open questions, the nightly digest, the
brain version and fingerprint, rule proposals waiting and the ones the owner
declined). The writes let the owner add, edit and remove rules directly.

Owner only (_require_owner, the canonical service-role owner check). Every
write lands in the ledger with the rule's words.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_supabase import AuthedUser, require_user
from business_profile_router import _require_owner
import business_brain
import business_learning as learning
import sb_clients

router = APIRouter(prefix="/brain", tags=["brain"])

DECLINED_DAYS = 90
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class RuleBody(BaseModel):
    statement: str = Field(min_length=1, max_length=learning.RULE_MAX_CHARS)
    polarity: Literal["do", "dont"]
    kind: Literal["preference", "voice", "workflow", "exception"] = "preference"
    scope: str = Field(default="", max_length=80)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _business(business_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type,owner_id,settings,"
        "subscription_plan,subscription_status,comp_tier&limit=1") or []
    if not rows:
        raise HTTPException(404, "Business not found.")
    return rows[0]


def _owner_voice(owner_id: Optional[str]) -> Dict[str, List[str]]:
    if not owner_id:
        return {"dos": [], "donts": []}
    rows = sb_clients.sb_get_as_service(
        f"/practitioner_profiles?owner_id=eq.{owner_id}&select=voice_dos,voice_donts&limit=1") or []
    row = rows[0] if isinstance(rows, list) and rows else {}
    return {"dos": list(row.get("voice_dos") or []), "donts": list(row.get("voice_donts") or [])}


@router.get("/{business_id}")
def read_brain(business_id: UUID, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    bid = str(business_id)
    _require_owner(bid, user)
    biz = _business(bid)
    try:
        row = learning.load(bid)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    profile = (row or {}).get("profile") or {}
    facts = profile.get("facts") or []
    latest = business_brain.latest(bid)
    since = _z(datetime.now(timezone.utc) - timedelta(days=DECLINED_DAYS))
    return {
        "ok": True,
        "revision": (row or {}).get("revision") or 0,
        "status": (row or {}).get("status"),
        "trade_label": profile.get("trade_label") or "",
        "summary": profile.get("summary") or "",
        "rules": [f for f in facts if f.get("polarity")],
        "facts": [{k: f.get(k) for k in ("key", "kind", "content", "basis")}
                  for f in facts if not f.get("polarity")],
        "gaps": profile.get("gaps") or [],
        "max_rules": learning.MAX_RULES,
        "brain": ({"version": latest.get("version"), "fingerprint": latest.get("fingerprint"),
                   "digest": latest.get("digest") or "", "since": latest.get("created_at"),
                   "reason": latest.get("reason") or ""} if latest else None),
        "pending": business_brain.rule_proposals(bid, status="draft"),
        "declined": business_brain.rule_proposals(bid, status="dismissed", since=since),
        "voice": _owner_voice(biz.get("owner_id")),
    }


def _ledger(bid: str, user: AuthedUser, verb: str, summary: str, payload: Dict[str, Any]) -> None:
    import audit_log
    audit_log.record(bid, actor_type="user", actor_id=str(user.id), verb=verb,
                     summary=summary[:200], payload=payload, source="desktop",
                     authorized_by="owner:brain_page")


def _save_rule(bid: str, body: RuleBody, user: AuthedUser, key: Optional[str]) -> Dict[str, Any]:
    _require_owner(bid, user)
    biz = _business(bid)
    try:
        row, fact = learning.adopt_rule(biz, statement=body.statement, polarity=body.polarity,
                                        kind=body.kind, scope=body.scope, key=key,
                                        origin="owner_page")
    except learning.RuleCapReached as e:
        raise HTTPException(409, str(e)) from e
    except learning.Conflict as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    brain = business_brain.stamp(biz, reason=f"rule {'edited' if key else 'added'} on page: {fact.key}")
    _ledger(bid, user, "adopt_business_rule",
            f"{'Edited' if key else 'Added'} rule: {fact.content}",
            {"key": fact.key, "polarity": fact.polarity, "scope": fact.scope,
             "statement": fact.content, "_ai": {"brain_v": brain.get("version"),
                                               "brain_fp": brain.get("fp")} if brain else {}})
    return {"ok": True, "rule": fact.model_dump(mode="json"), "brain": brain or None,
            "revision": (row or {}).get("revision")}


@router.post("/{business_id}/rules")
def add_rule(business_id: UUID, body: RuleBody, user: AuthedUser = Depends(require_user)):
    return _save_rule(str(business_id), body, user, None)


@router.put("/{business_id}/rules/{key}")
def edit_rule(business_id: UUID, key: str, body: RuleBody, user: AuthedUser = Depends(require_user)):
    if not _KEY.fullmatch(key or ""):
        raise HTTPException(422, "Unknown rule key.")
    bid = str(business_id)
    _require_owner(bid, user)
    row = learning.load(bid)
    current = [f for f in ((row or {}).get("profile") or {}).get("facts") or []
               if f.get("key") == key and f.get("polarity")]
    if not current:
        raise HTTPException(404, "That rule is no longer on file.")
    return _save_rule(bid, body, user, key)


@router.delete("/{business_id}/rules/{key}")
def delete_rule(business_id: UUID, key: str, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    _require_owner(bid, user)
    biz = _business(bid)
    try:
        row, fact = learning.remove_rule(bid, key)
    except learning.Conflict as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    brain = business_brain.stamp(biz, reason=f"rule removed on page: {key}")
    _ledger(bid, user, "remove_business_rule", f"Removed rule: {fact.content}",
            {"key": key, "statement": fact.content,
             "_ai": {"brain_v": brain.get("version"), "brain_fp": brain.get("fp")} if brain else {}})
    return {"ok": True, "removed": key, "brain": brain or None,
            "revision": (row or {}).get("revision")}


@router.get("/{business_id}/history")
def brain_history(business_id: UUID, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    _require_owner(bid, user)
    return {"ok": True, "versions": business_brain.history(bid)}
