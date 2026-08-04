"""
conflicts_router.py — the conflict-of-interest check.

For a lawyer this is mandatory professional conduct: before taking a
new client or matter, sweep the practice's records for the new client
AND the adverse parties — a current client on the other side, a former
client whose confidences are in the files, a name that's both. For a
consultant it's "have we worked with the other side?"; for any vertical
it's "does this name already live somewhere in my records?" One rubric,
every business type — the vertical decides how much it matters, not
whether it exists.

Surface:
  POST /conflicts/check   {business_id, names: [1..10]}
    → per-name hits across the searchable corpus, graded
      exact / strong / possible, PLUS a `conflict_check` event on the
      spine — running the check is itself the professional-conduct
      artifact ("we checked, here's when, here's what came back"), so
      the record writes whether or not anything was found.

Corpus (v1):
  - contacts — every status, deliberately: FORMER clients are the heart
    of a conflicts sweep. name / email / phone / tags / role.
  - module_entries — matters, jobs, engagements, bookings: every string
    value in each entry's jsonb data, walked generically (stage names
    and party fields differ per archetype; the walker doesn't care).

Deliberately NOT an LLM call: a conflicts sweep must be exhaustive,
deterministic, and reproducible — a generative "I didn't see anything"
is worthless as a record. No units gate for the same reason (it's a
read, not an AI action).

Matching ladder (normalize → casefold, strip accents + punctuation):
  exact    — whole normalized strings equal; or email/phone-digits equal
  strong   — every token of the query appears as a whole word in the
             candidate (or vice versa): "John Smith" ↔ "John A. Smith"
  possible — fuzzy full-string ratio ≥ 0.84 ("Jon Smyth"), a fuzzy
             token hit, or a single-token whole-word hit ("Smith" →
             every Smith in the book; surname sweeps are the point)
Single short/common tokens never fuzzy-match ("Lee" must not hit
"fleet") — whole-word only below two tokens.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("conflicts_router")

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

_MAX_NAMES = 10
_MAX_CONTACTS = 2000
_MAX_ENTRIES = 3000
_FULL_RATIO = 0.84
_TOKEN_RATIO = 0.86


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


# ─── Normalization + matching ────────────────────────────────────────

def _norm(s: str) -> str:
    """casefold, strip accents, collapse punctuation to spaces."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s@.]", " ", s.casefold())
    return re.sub(r"\s+", " ", s).strip()


def _tokens(norm: str) -> List[str]:
    return [t for t in norm.split(" ") if t]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def match_strength(query: str, candidate: str) -> Optional[str]:
    """The ladder. Returns 'exact' | 'strong' | 'possible' | None."""
    qn, cn = _norm(query), _norm(candidate)
    if not qn or not cn:
        return None
    if qn == cn:
        return "exact"

    qt, ct = _tokens(qn), _tokens(cn)
    cset = set(ct)

    # Multi-token containment either direction: "John Smith" ↔ "John A. Smith".
    if len(qt) >= 2 and all(t in cset for t in qt):
        return "strong"
    if len(ct) >= 2 and all(t in set(qt) for t in ct):
        return "strong"

    # Single-token query: whole-word hit — a surname sweep, graded
    # possible because there may be many Smiths and zero conflicts —
    # or a fuzzy token hit for a misspelled surname ("Whitfeild").
    # Never substrings: "Lee" must not hit "fleet".
    if len(qt) == 1:
        if qt[0] in cset:
            return "possible"
        if len(qt[0]) >= 4:
            for c in ct:
                if len(c) >= 4 and SequenceMatcher(None, qt[0], c).ratio() >= _TOKEN_RATIO:
                    return "possible"
        return None

    # Fuzzy full string ("Jon Smyth" vs "John Smith").
    if SequenceMatcher(None, qn, cn).ratio() >= _FULL_RATIO:
        return "possible"

    # Fuzzy token: a distinctive query token nearly matching a candidate
    # token (misspelled surname inside a longer entry title).
    for t in qt:
        if len(t) < 4:
            continue
        for c in ct:
            if len(c) >= 4 and SequenceMatcher(None, t, c).ratio() >= _TOKEN_RATIO:
                return "possible"
    return None


_STRENGTH_RANK = {"exact": 0, "strong": 1, "possible": 2}


def _best(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a is None:
        return b
    if b is None:
        return a
    return a if _STRENGTH_RANK[a] <= _STRENGTH_RANK[b] else b


def _walk_strings(value: Any, depth: int = 0) -> List[str]:
    """Every string inside an entry's jsonb data, shallow-walked —
    archetypes disagree about field names; the walker doesn't care."""
    if depth > 3:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [v[:300]] if v else []
    if isinstance(value, dict):
        out: List[str] = []
        for v in value.values():
            out.extend(_walk_strings(v, depth + 1))
        return out
    if isinstance(value, list):
        out = []
        for v in value[:50]:
            out.extend(_walk_strings(v, depth + 1))
        return out
    return []


def _entry_label(data: Dict[str, Any]) -> str:
    for key in ("title", "name", "client_name", "customer", "subject", "description"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:120]
    strings = _walk_strings(data)
    return (strings[0][:120] if strings else "(untitled entry)")


# ─── The sweep ───────────────────────────────────────────────────────

def _sweep(business_id: str, names: List[str]) -> List[Dict[str, Any]]:
    contacts = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}"
        f"&select=id,name,email,phone,role,status,tags&limit={_MAX_CONTACTS}") or []

    # ALL modules, deliberately including inactive ones — a retired
    # pipeline still holds former matters, and former is the point.
    modules = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}"
        "&select=id,name,archetype&limit=200") or []
    mod_name = {m["id"]: (m.get("name") or m.get("archetype") or "module")
                for m in modules}
    entries: List[Dict[str, Any]] = []
    if modules:
        ids = ",".join(str(m["id"]) for m in modules)
        entries = sb_clients.sb_get_as_service(
            f"/module_entries?module_id=in.({ids})"
            f"&select=id,module_id,status,data&limit={_MAX_ENTRIES}") or []

    results: List[Dict[str, Any]] = []
    for raw_name in names:
        hits: List[Dict[str, Any]] = []
        q_digits = _digits(raw_name)

        for c in contacts:
            strength: Optional[str] = None
            matched_on: List[str] = []
            s = match_strength(raw_name, c.get("name") or "")
            if s:
                strength, matched_on = _best(strength, s), matched_on + ["name"]
            if "@" in raw_name and _norm(raw_name) == _norm(c.get("email") or ""):
                strength, matched_on = _best(strength, "exact"), matched_on + ["email"]
            if len(q_digits) >= 7 and q_digits == _digits(c.get("phone") or ""):
                strength, matched_on = _best(strength, "exact"), matched_on + ["phone"]
            for extra_field in ("role", "tags"):
                val = c.get(extra_field)
                text = " ".join(val) if isinstance(val, list) else (val or "")
                s = match_strength(raw_name, text)
                if s:
                    strength = _best(strength, "possible")
                    matched_on.append(extra_field)
            if strength:
                hits.append({
                    "source": "contact", "id": c.get("id"),
                    "label": c.get("name") or c.get("email") or "(unnamed)",
                    "detail": " · ".join(x for x in (
                        c.get("role"), c.get("status")) if x) or None,
                    "strength": strength, "matched_on": matched_on,
                })

        for e in entries:
            data = e.get("data") if isinstance(e.get("data"), dict) else {}
            strength = None
            snippet = None
            for text in _walk_strings(data):
                s = match_strength(raw_name, text)
                if s and (strength is None
                          or _STRENGTH_RANK[s] < _STRENGTH_RANK[strength]):
                    strength, snippet = s, text
                    if s == "exact":
                        break
            if strength:
                hits.append({
                    "source": "entry", "id": e.get("id"),
                    "label": _entry_label(data),
                    "detail": " · ".join(x for x in (
                        mod_name.get(e.get("module_id")), e.get("status")) if x) or None,
                    "strength": strength,
                    "matched_on": [snippet[:120]] if snippet else [],
                })

        hits.sort(key=lambda h: _STRENGTH_RANK[h["strength"]])
        results.append({"query": raw_name, "hits": hits[:25]})
    return results


# ─── Endpoint ────────────────────────────────────────────────────────

class CheckBody(BaseModel):
    business_id: str
    names: List[str]


@router.post("/check")
async def conflicts_check(body: CheckBody,
                          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(body.business_id, user)
    names = [n.strip() for n in (body.names or []) if n and n.strip()]
    if not names:
        raise HTTPException(400, "give at least one name to check")
    if len(names) > _MAX_NAMES:
        raise HTTPException(400, f"at most {_MAX_NAMES} names per check")

    results = _sweep(body.business_id, names)

    total = sum(len(r["hits"]) for r in results)
    by_strength: Dict[str, int] = {}
    for r in results:
        for h in r["hits"]:
            by_strength[h["strength"]] = by_strength.get(h["strength"], 0) + 1

    # The check IS the record — log it whether or not anything was found.
    logged = True
    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": body.business_id,
            "event_type": "conflict_check",
            "data": {"queries": names, "total_hits": total,
                     "by_strength": by_strength},
            "source": "conflicts_router",
        })
    except Exception as e:
        logged = False
        logger.warning(f"conflict_check event write failed: {e}")

    return {"ok": True, "results": results, "total_hits": total,
            "by_strength": by_strength, "logged": logged}
