"""
church_families.py — Chief suggests who lives together; the pastor accepts.

Shepherding is by family (Kevin, 2026-10-17; canvas 31su6kdYmYecH5b2NxjBJN,
board 2 "Families first"), and most churches arrive with none recorded:
Love City had 148 members and no families. Chief reads the members and
suggests who lives together. Nothing is saved until the pastor accepts it,
and an accepted family is the same family Kids check-in uses (households,
household_adults, children), so it is done once.

How Chief guesses:
  · the same last name and the same street: the surest sign;
  · a shared phone or email inside a last-name group: sure too;
  · the same last name with nothing to contradict it: likely (2–6 people);
  · seven or more sharing a last name, or two last names at one street:
    shown as a question, never joined on its own;
  · a member under 18 (by birthdate) is a child of the family.

A child joins as a `children` row linked to their member record
(children.contact_id), NEVER as a household adult: the kiosk lets any
household adult pick children up.

  suggestions(biz)            what the Families page shows
  accept(biz, body)           make one family (checked again on the server)
  accept_sure(biz)            make every "sure" one as suggested
  dismiss(biz, key)           "Not a family": Chief stops suggesting it
  surname(row) / is_child(row) / age(...)  shared with church_shepherding
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger("church_families")

CHILD_AGE = 18
LIKELY_MAX = 6
FAMILY_MAX = 20
_KEY = re.compile(r"^f_[0-9a-f]{12}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}
_STREET_WORDS = {"street": "st", "avenue": "ave", "av": "ave", "boulevard": "blvd", "drive": "dr", "road": "rd",
                 "lane": "ln", "court": "ct", "place": "pl", "circle": "cir", "parkway": "pkwy", "highway": "hwy",
                 "terrace": "ter", "north": "n", "south": "s", "east": "e", "west": "w", "apartment": "apt",
                 "suite": "ste", "unit": "apt", "#": "apt"}
_RANK = {"sure": 0, "likely": 1, "check": 2}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ─── reading a member ─────────────────────────────────────────────────

def _meta(row: Dict[str, Any]) -> Dict[str, Any]:
    m = row.get("metadata")
    return m if isinstance(m, dict) else {}


def age(birthdate: Any, today: Optional[date] = None) -> Optional[int]:
    if not birthdate:
        return None
    try:
        b = birthdate if isinstance(birthdate, date) else date.fromisoformat(str(birthdate)[:10])
    except ValueError:
        return None
    t = today or _today()
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    return years if 0 <= years < 130 else None


def is_child(row: Dict[str, Any], today: Optional[date] = None) -> bool:
    a = age(row.get("birthdate"), today)
    return a is not None and a < CHILD_AGE


def first_name(row: Dict[str, Any]) -> str:
    f = _plain(_meta(row).get("first_name"))
    return f or (_plain(row.get("name")).split(" ") or [""])[0] or "Someone"


def _surname_words(row: Dict[str, Any]) -> List[str]:
    last = _plain(_meta(row).get("last_name"))
    words = last.split(" ") if last else _plain(row.get("name")).split(" ")[1:]
    words = [w for w in words if w]
    while words and re.sub(r"[^a-z]", "", words[-1].casefold()) in _SUFFIX:
        words = words[:-1]
    return words


def _cased(word: str) -> str:
    """As written ("McCloud"), unless typed all one case ("brown", "BROWN")."""
    if word.islower() or word.isupper():
        return "-".join(p[:1].upper() + p[1:].lower() for p in word.split("-"))
    return word


def surname(row: Dict[str, Any]) -> str:
    """The last name as written ("McCloud"), suffixes (Jr, III) dropped."""
    words = _surname_words(row)
    return _cased(words[-1].strip(",.")) if words else ""


def surname_key(row: Dict[str, Any]) -> str:
    return re.sub(r"[^a-z]", "", surname(row).casefold().replace("’", "").replace("'", ""))


def _street_line(addr: str) -> str:
    return _plain(addr.split(",")[0])


def address_key(addr: Any) -> str:
    """The street line, normalized ("2948 Mason Blvd"): '' when it isn't a
    real address (one with a number, 8+ characters)."""
    text = _plain(addr)
    if len(text) < 8 or not re.search(r"\d", text):
        return ""
    line = _street_line(text).casefold()
    words = [_STREET_WORDS.get(w, w) for w in re.findall(r"[a-z0-9#]+", line)]
    key = " ".join(words)
    return key if re.search(r"\d", key) and len(key) >= 5 else ""


def _phone_key(v: Any) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d[-10:] if len(d) >= 10 else ""


def _email_key(v: Any) -> str:
    e = str(v or "").strip().casefold()
    return e if "@" in e else ""


def zip_of(addr: Any) -> str:
    m = re.findall(r"\b(\d{5})(?:-\d{4})?\b", str(addr or ""))
    return m[-1] if m else ""


def person(row: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    a = age(row.get("birthdate"), today)
    return {"contact_id": str(row["id"]), "name": _plain(row.get("name")) or "Someone",
            "first_name": first_name(row), "kind": "child" if a is not None and a < CHILD_AGE else "adult",
            "age": a if a is not None and a < CHILD_AGE else None}


def key_for(ids: Iterable[str]) -> str:
    return "f_" + hashlib.sha1(",".join(sorted(str(i) for i in ids)).encode()).hexdigest()[:12]


# ─── reads ────────────────────────────────────────────────────────────

_MEMBER_SELECT = "id,name,email,phone,birthdate,metadata,status"


def members(biz: str) -> Optional[List[Dict[str, Any]]]:
    return _rows(f"/contacts?business_id=eq.{_q(biz)}&status=eq.active&select={_MEMBER_SELECT}"
                 "&order=name.asc&limit=5000")


def in_families(biz: str) -> Optional[Set[str]]:
    """Everyone already in a family: its adults and its linked children."""
    adults = _rows(f"/household_adults?business_id=eq.{_q(biz)}&select=contact_id&limit=20000")
    kids = _rows(f"/children?business_id=eq.{_q(biz)}&select=contact_id&limit=20000")
    if adults is None or kids is None:
        return None
    return {str(a["contact_id"]) for a in adults} | {str(k["contact_id"]) for k in kids if k.get("contact_id")}


def _dismissed(biz: str) -> Optional[Set[str]]:
    rows = _rows(f"/church_family_dismissals?business_id=eq.{_q(biz)}&select=key&limit=5000")
    return None if rows is None else {str(r["key"]) for r in rows}


# ─── the guess ────────────────────────────────────────────────────────

def _family_name(rows: List[Dict[str, Any]]) -> str:
    names: List[str] = []
    for r in rows:
        s = surname(r)
        if s and s.casefold() not in {n.casefold() for n in names}:
            names.append(s)
    if not names:
        return "A family"
    return f"The {' and '.join(names[:2])} family"


def _shared(rows: List[Dict[str, Any]], fn) -> str:
    seen: Dict[str, int] = {}
    for r in rows:
        k = fn(r)
        if k:
            seen[k] = seen.get(k, 0) + 1
    return next((k for k, n in seen.items() if n > 1), "")


def _suggestion(rows: List[Dict[str, Any]], today: date, *, mixed: bool = False, loose: bool = False) -> Dict[str, Any]:
    addr = _shared(rows, lambda r: address_key(_meta(r).get("address")))
    phone = _shared(rows, lambda r: _phone_key(r.get("phone")))
    email = _shared(rows, lambda r: _email_key(r.get("email")))
    why: List[str] = []
    if not mixed:
        why.append("Same last name")
    if addr:
        shown = next(_street_line(_plain(_meta(r).get("address"))) for r in rows
                     if address_key(_meta(r).get("address")) == addr)
        why.append(f"Same street: {shown}")
    if phone:
        why.append("A shared phone")
    if email:
        why.append("A shared email")
    people = sorted((person(r, today) for r in rows), key=lambda p: (p["kind"] == "child", -(p["age"] or 0), p["name"]))
    kids = sum(1 for p in people if p["kind"] == "child")
    if kids:
        why.append(f"{kids} {'child' if kids == 1 else 'children'} by birthdate")
    ask = ""
    if mixed:
        sure = "check"
        ask = "Two last names at one address. One family?"
    elif len(rows) > LIKELY_MAX:
        sure = "check"
        ask = f"{len(rows)} people share this last name. Who lives together?"
    elif loose:
        # The same last name lives at two streets; these have no address.
        sure = "check"
        ask = "Others with this last name live at two addresses. Are these one family?"
    elif addr or phone or email:
        sure = "sure"
    else:
        sure = "likely"
    return {"key": key_for(r["id"] for r in rows), "name": _family_name(rows), "sure": sure, "why": why,
            "ask": ask, "people": people}


def guess(rows: List[Dict[str, Any]], dismissed: Set[str], today: Optional[date] = None
          ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(suggestions, singles) from members not yet in a family."""
    today = today or _today()
    rows = [r for r in rows if r.get("id")]
    out: List[Dict[str, Any]] = []
    placed: Set[str] = set()

    # Two last names at one street: its own question, never merged.
    by_addr: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        k = address_key(_meta(r).get("address"))
        if k:
            by_addr.setdefault(k, []).append(r)
    for group in by_addr.values():
        names = {surname_key(r) for r in group}
        if len(group) > 1 and len(names) > 1 and not all(is_child(r, today) for r in group):
            s = _suggestion(group, today, mixed=True)
            if s["key"] not in dismissed and len(group) <= FAMILY_MAX:
                out.append(s)
                placed |= {str(r["id"]) for r in group}

    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if str(r["id"]) in placed:
            continue
        by_name.setdefault(surname_key(r) or f"?{r['id']}", []).append(r)
    for group in by_name.values():
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        loose: List[Dict[str, Any]] = []
        for r in group:
            k = address_key(_meta(r).get("address"))
            (clusters.setdefault(k, []) if k else loose).append(r)
        if len(clusters) <= 1:
            parts = [(group, False)]
        else:
            parts = [(c, False) for c in clusters.values()] + ([(loose, True)] if loose else [])
        for part, unsure in parts:
            if len(part) < 2 or all(is_child(r, today) for r in part):
                continue
            s = _suggestion(part, today, loose=unsure)
            if s["key"] in dismissed:
                continue
            out.append(s)
            placed |= {str(r["id"]) for r in part}

    out.sort(key=lambda s: (_RANK[s["sure"]], s["name"].casefold()))
    singles = sorted((person(r, today) for r in rows if str(r["id"]) not in placed), key=lambda p: p["name"].casefold())
    return out, singles


def suggestions(biz_id: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    biz = str(biz_id)
    today = today or _today()
    rows = members(biz)
    taken = in_families(biz)
    dismissed = _dismissed(biz)
    if rows is None or taken is None or dismissed is None:
        return None
    free = [r for r in rows if str(r["id"]) not in taken]
    sugg, singles = guess(free, dismissed, today)
    return {
        "members": len(rows),
        "children": sum(1 for r in rows if is_child(r, today)),
        "with_address": sum(1 for r in rows if address_key(_meta(r).get("address"))),
        "in_families": sum(1 for r in rows if str(r["id"]) in taken),
        "suggestions": sugg,
        "singles": singles,
    }


# ─── writes ───────────────────────────────────────────────────────────

def _ids(values: Iterable[Any], what: str) -> List[str]:
    out: List[str] = []
    for v in values or []:
        s = str(v or "").strip()
        if not _UUID.match(s):
            raise HTTPException(400, f"That {what} isn't valid")
        if s.lower() not in out:
            out.append(s.lower())
    return out


def accept(biz_id: str, body: Dict[str, Any], *, today: Optional[date] = None) -> Dict[str, Any]:
    """Make one family from members not yet in one. Adults become household
    adults; children (under 18 by birthdate) become children linked to their
    record. All or nothing."""
    biz = str(biz_id)
    today = today or _today()
    name = _plain(body.get("name"))[:120]
    if not name:
        raise HTTPException(400, "Give the family a name.")
    adults = _ids(body.get("adults") or [], "person")
    kids = _ids(body.get("children") or [], "child")
    if set(adults) & set(kids):
        raise HTTPException(400, "Someone is in that family twice.")
    if not adults:
        raise HTTPException(400, "A family needs at least one adult.")
    if len(adults) + len(kids) > FAMILY_MAX:
        raise HTTPException(400, f"A family can have {FAMILY_MAX} people at most.")
    ids = adults + kids
    rows = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})&select={_MEMBER_SELECT}")
    taken = in_families(biz)
    if rows is None or taken is None:
        raise HTTPException(503, "Families couldn't be loaded. Nothing was saved. Try again in a moment.")
    found = {str(r["id"]).lower(): r for r in rows}
    for i in ids:
        r = found.get(i)
        if not r or r.get("status") != "active":
            raise HTTPException(400, "Someone in that family isn't a member here.")
        if i in {t.lower() for t in taken}:
            raise HTTPException(409, f"{_plain(r.get('name')) or 'Someone'} is already in a family.")
    for i in adults:
        if is_child(found[i], today):
            raise HTTPException(400, f"{first_name(found[i])} is under 18, so they join as a child.")
    for i in kids:
        if not is_child(found[i], today):
            raise HTTPException(400, f"{first_name(found[i])} is 18 or older, so they join as an adult.")
    made = sb_clients.sb_post_as_service("/households", {"business_id": biz, "name": name})
    if not isinstance(made, list) or not made:
        raise HTTPException(503, "That family didn't save. Try again in a moment.")
    hid = str(made[0]["id"])
    rel = "parent" if kids else "other"
    ok = True
    for i in adults:
        saved = sb_clients.sb_post_as_service("/household_adults", {"household_id": hid, "contact_id": i,
                                                                    "business_id": biz, "relationship": rel})
        ok = ok and isinstance(saved, list) and bool(saved)
    for i in kids:
        r = found[i]
        saved = sb_clients.sb_post_as_service("/children", {
            "business_id": biz, "household_id": hid, "contact_id": i,
            "first_name": first_name(r)[:80], "last_name": " ".join(_cased(w) for w in _surname_words(r))[:80],
            "birthdate": str(r.get("birthdate"))[:10] if r.get("birthdate") else None})
        ok = ok and isinstance(saved, list) and bool(saved)
    if not ok:
        # All or nothing: a half-made family is worse than none.
        sb_clients.sb_delete_as_service(f"/households?id=eq.{_q(hid)}&business_id=eq.{_q(biz)}")
        raise HTTPException(503, "That family didn't save. Nothing was kept. Try again in a moment.")
    return {"household_id": hid, "name": name}


def accept_sure(biz_id: str, *, today: Optional[date] = None) -> int:
    """Every suggestion Chief is sure of, as suggested. Returns how many."""
    data = suggestions(biz_id, today)
    if data is None:
        raise HTTPException(503, "Families couldn't be loaded. Try again in a moment.")
    made = 0
    for s in data["suggestions"]:
        if s["sure"] != "sure":
            continue
        try:
            accept(biz_id, {"name": s["name"],
                            "adults": [p["contact_id"] for p in s["people"] if p["kind"] == "adult"],
                            "children": [p["contact_id"] for p in s["people"] if p["kind"] == "child"]}, today=today)
            made += 1
        except HTTPException as e:
            if e.status_code >= 500:
                raise
    return made


def dismiss(biz_id: str, key: str) -> None:
    k = str(key or "").strip()
    if not _KEY.match(k):
        raise HTTPException(400, "That suggestion isn't valid")
    saved = sb_clients.sb_post_as_service("/church_family_dismissals?on_conflict=business_id,key",
                                          {"business_id": str(biz_id), "key": k},
                                          prefer="return=representation,resolution=ignore-duplicates")
    if saved is None:
        raise HTTPException(503, "That didn't save. Try again in a moment.")
