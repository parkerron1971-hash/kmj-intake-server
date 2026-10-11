"""The business brain: which version of Chief acted for a business.

Layer Two, 2026-10-11. A brain is three things Chief carries for one business:
its private operating profile (facts and the owner's rules, by revision), the
nightly digest written by the brain pass, and the model lanes it runs on. They
are hashed into a fingerprint. Each distinct fingerprint is one row in
business_brain_versions, so "which Chief did this?" has a stored answer:
ledger rows name the version that acted, and the ledger's anchoring makes that
record tamper-evident.

Nothing here calls a model or acts. Reads and the occasional version insert
only; every failure degrades to "no stamp", never to a failed turn.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("business_brain")

# The lanes that shape what Chief says and does for a business. A change to
# any of them is a change of brain.
BRAIN_LANES = ("chat", "voice", "draft", "review", "repair", "fast", "background", "deep")

DIGEST_MAX_CHARS = 1600

_probe: Dict[str, Any] = {"ok": None, "at": 0.0}
_PROBE_TTL_S = 600


def table_ready() -> bool:
    """Does business_brain_versions exist yet? Probed at most every ten
    minutes, never without a Supabase URL (tests, scripts)."""
    if not os.environ.get("SUPABASE_URL"):
        return False
    if _probe["ok"] is not None and time.monotonic() - _probe["at"] < _PROBE_TTL_S:
        return bool(_probe["ok"])
    try:
        ok = isinstance(sb_clients.sb_get_as_service(
            "/business_brain_versions?select=id&limit=1"), list)
    except Exception:
        ok = False
    if not ok:
        print("[brain] business_brain_versions not found; apply "
              "supabase/APPLY-2026-10-11-layer-two-foundation.sql", flush=True)
    _probe.update(ok=ok, at=time.monotonic())
    return ok


_col_probe: Dict[str, Any] = {}


def has_columns(table: str, cols) -> bool:
    """Do these columns exist yet? Same cached probe as table_ready, keyed by
    table and columns, for code that must run before and after a migration."""
    if not os.environ.get("SUPABASE_URL"):
        return False
    key = f"{table}:{','.join(cols)}"
    hit = _col_probe.get(key)
    if hit and time.monotonic() - hit[1] < _PROBE_TTL_S:
        return hit[0]
    try:
        ok = isinstance(sb_clients.sb_get_as_service(f"/{table}?select={','.join(cols)}&limit=1"), list)
    except Exception:
        ok = False
    _col_probe[key] = (ok, time.monotonic())
    return ok


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lanes_for(plan: Optional[str] = None) -> Dict[str, str]:
    import chief_models
    return {lane: chief_models.model_for(lane, plan) for lane in BRAIN_LANES}


def rules_sha(profile: Optional[Dict[str, Any]]) -> str:
    import business_learning
    if not profile:
        return _sha("[]")
    rules = sorted(
        ({"key": f.key, "polarity": f.polarity, "scope": f.scope, "content": f.content}
         for f in business_learning.rules(profile)),
        key=lambda r: r["key"])
    return _sha(json.dumps(rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def fingerprint(*, profile_revision: int, profile: Optional[Dict[str, Any]],
                digest: str, lanes: Dict[str, str]) -> str:
    """Stable across processes and replicas: canonical JSON, no timestamps.
    Profile revision covers every fact; the rules hash is included again so a
    rule change is visible on its own in the stored row."""
    material = {
        "v": 1,
        "profile_revision": int(profile_revision or 0),
        "profile_sha": _sha(json.dumps(profile or {}, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False)),
        "rules_sha": rules_sha(profile),
        "digest_sha": _sha(digest or ""),
        "lanes": dict(sorted((lanes or {}).items())),
    }
    return _sha(json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def latest(business_id: str) -> Optional[Dict[str, Any]]:
    if not business_id or not table_ready():
        return None
    try:
        rows = sb_clients.sb_get_as_service(
            f"/business_brain_versions?business_id=eq.{business_id}"
            "&select=version,fingerprint,profile_revision,digest,digest_sha,created_at,reason"
            "&order=version.desc&limit=1")
    except Exception as e:
        logger.warning(f"[brain] latest read failed: {e}")
        return None
    return rows[0] if isinstance(rows, list) and rows else None


def digest_for(business_id: str) -> str:
    """The latest nightly digest, for the prompt. Empty when there is none."""
    row = latest(business_id)
    return str((row or {}).get("digest") or "")


def _plan_of(business: Dict[str, Any]) -> Optional[str]:
    try:
        import feature_gates
        return feature_gates.plan_of(business)
    except Exception:
        return None


def stamp(business: Dict[str, Any], *, digest: Optional[str] = None,
          reason: str = "") -> Dict[str, Any]:
    """Record (if new) and return the current brain: {"version", "fp"}.

    `digest` replaces the carried-forward digest (the nightly pass); None
    keeps the latest one. Returns {} when the table is missing or anything
    fails: a missing stamp never blocks an action or a reply."""
    bid = str((business or {}).get("id") or "")
    if not bid or not table_ready():
        return {}
    try:
        import business_learning
        try:
            row = business_learning.load(bid)
        except (RuntimeError, ValueError):
            row = None
        profile = (row or {}).get("profile")
        revision = int((row or {}).get("revision") or 0)
        prev = latest(bid)
        if digest is None:
            text = str((prev or {}).get("digest") or "")
        else:
            text = str(digest)[:DIGEST_MAX_CHARS]
        lanes = lanes_for(_plan_of(business))
        fp = fingerprint(profile_revision=revision, profile=profile, digest=text, lanes=lanes)
        if prev and prev.get("fingerprint") == fp:
            return {"version": int(prev["version"]), "fp": fp}
        version = int((prev or {}).get("version") or 0) + 1
        res = sb_clients.sb_post_as_service("/business_brain_versions", {
            "business_id": bid, "version": version, "fingerprint": fp,
            "profile_revision": revision, "rules_sha": rules_sha(profile),
            "digest": text, "digest_sha": _sha(text), "lanes": lanes,
            "reason": (reason or ("nightly digest" if digest is not None
                                  else f"profile revision {revision}"))[:200],
        })
        if isinstance(res, list) and res:
            return {"version": version, "fp": fp}
        # Another replica wrote this version first (unique business_id+version):
        # read back whatever is current now.
        again = latest(bid)
        if again and again.get("fingerprint") == fp:
            return {"version": int(again["version"]), "fp": fp}
        return {}
    except Exception as e:
        logger.warning(f"[brain] stamp failed for {bid[:8]}: {e}")
        return {}


def rule_proposals(business_id: str, *, status: str,
                   since: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Queue rows proposing an owner rule, read back through the same spec
    parser approval uses, so what shows here is exactly what Approve runs.

    None when the read failed: "could not check" is never "there are none",
    or the nightly pass could re-propose a rule the owner declined."""
    import action_proposals
    path = (f"/agent_queue?business_id=eq.{business_id}&channel=eq.{action_proposals.CHANNEL}"
            f"&status=eq.{status}&select=id,subject,body,ai_reasoning,created_at,reviewed_at"
            "&order=created_at.desc&limit=50")
    if since:
        path += f"&created_at=gte.{since}"
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        spec = action_proposals.spec_from_body(r.get("body") or "")
        action = (spec or {}).get("action") or {}
        if action.get("type") != "adopt_business_rule":
            continue
        out.append({"id": r.get("id"), "statement": action.get("statement"),
                    "polarity": action.get("polarity"), "scope": action.get("scope") or "",
                    "kind": action.get("kind") or "preference", "why": r.get("ai_reasoning") or "",
                    "created_at": r.get("created_at"), "reviewed_at": r.get("reviewed_at")})
    return out


def history(business_id: str, limit: int = 20) -> list:
    if not business_id or not table_ready():
        return []
    try:
        rows = sb_clients.sb_get_as_service(
            f"/business_brain_versions?business_id=eq.{business_id}"
            "&select=version,fingerprint,profile_revision,reason,created_at,lanes"
            f"&order=version.desc&limit={int(limit)}")
        return rows if isinstance(rows, list) else []
    except Exception:
        return []
