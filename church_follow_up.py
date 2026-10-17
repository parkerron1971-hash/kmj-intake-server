"""church_follow_up.py — every card becomes someone's job.

Kevin, 2026-10-17: "connect the information that we gain from these cards
and assign them to a person to be able to work on. Leader, minister etc...
chief … assigned them properly … inserted into a workflow so no person
gets left behind." Design canvas LG4Q97HqtEM4ByyXmmSrCP; "build it".

    a member holds a role ............ church_leader_roles (the role is the
                                       church's own: church_roles, its title
                                       on a job)
    a card comes in .................. on_intake_form / on_connect_card
      → Chief picks the leader ....... choose() — the church's roles, what
                                       each job takes, and the answers
      → a follow-up with a path ...... church_follow_ups (steps + a clock)
    the leader works it .............. leader_* (member page, Lead tab)
    the office sees it all ........... board / reassign / office_note
    nobody waits ..................... sweep(): tell the leader, then on the
                                       day a nudge, a day late the role they
                                       answer to, three days late one more
                                       step up (the chain, church_roles)

Chief assigns on its own (Kevin's pick over suggest-and-confirm): the rules
are the church's roles and what the person wrote. It never reads a prayer
request: private care forms stop in intake before they reach here (prayer
shared with the prayer team is church_prayer's).

The tables are server-only (APPLY-2026-10-17-church-leaders.sql); this
module is the one door to them, through the service role, always scoped
by business_id.
"""
from __future__ import annotations

import html
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger(__name__)

# The four roles of the first version. A church's roles are now its own
# (church_roles: its title on a job); these are the names its holders'
# keys fall back to before its library is filled.
ROLE_LABELS: Dict[str, str] = {
    "pastor": "Pastor",
    "baptism_minister": "Baptism minister",
    "welcome_lead": "Welcome Team lead",
    "team_leader": "Team leader",
}
ROLE_ORDER = tuple(ROLE_LABELS)

# How a conversation went. "note" is the office's plain note.
OUTCOMES: Dict[str, str] = {
    "talked": "Talked",
    "message": "Left a message",
    "noanswer": "No answer",
    "notnow": "Not right now",
    "note": "Note",
}
# A conversation that reached the person finishes "Reach out".
REACHED = ("talked", "message")

# Each card's path: the steps in order, and how many days each may take.
PATHS: Dict[str, List[Dict[str, Any]]] = {
    "baptism": [
        {"title": "Reach out", "rule": "within 2 days", "days": 2},
        {"title": "Talk it through", "rule": "faith, and what baptism means", "days": 7},
        {"title": "Set the date", "rule": "a Sunday service", "days": 14},
        {"title": "Baptized", "rule": "celebrate them", "days": 30},
    ],
    "serve": [
        {"title": "Reach out", "rule": "within 2 days", "days": 2},
        {"title": "Meet the team lead", "rule": "before or after a service", "days": 10},
        {"title": "First Sunday serving", "rule": "with someone beside them", "days": 21},
    ],
    "visit": [
        {"title": "Reach out", "rule": "before their Sunday", "days": 2},
        {"title": "Greet on Sunday", "rule": "meet them at the door", "days": 7},
        {"title": "Call that week", "rule": "within 5 days", "days": 5},
    ],
    "connect": [
        {"title": "Reach out", "rule": "within 2 days", "days": 2},
        {"title": "Invite to a next step", "rule": "a class, a group, or a team", "days": 14},
    ],
    "general": [
        {"title": "Reach out", "rule": "within 2 days", "days": 2},
    ],
}

# The late ladder: (days past due, level, note kind). On the day the leader
# is reminded; a day late the role they answer to is told; three days late
# one more step up (Kevin, 2026-10-17: "up the chain"). An empty role is
# passed over, and at the top the senior role is asked to hand them on.
LATE_LADDER = ((0, 1, "nudged"), (1, 2, "overseer_told"), (3, 3, "next_up"))

# Answers that are who they are, not what they said: the contact holds those.
_IDENTITY = re.compile(r"^(your )?(full |first |last )?(name|e-?mail( address)?|phone( number)?|mobile|website)$")
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
MAX_ANSWERS = 12
MAX_ANSWER = 600
MAX_NOTE = 2000


# ─── Small helpers ────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _uid(value: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _q(value: Any) -> str:
    return quote(str(value), safe="")


def _plain(value: Any) -> str:
    return " ".join(str(value or "").split())


def _norm(text: str) -> str:
    return _plain(text).replace("’", "'").replace("‘", "'").casefold()


def initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", _plain(name)) if p and p[0].isalnum()]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def first_name(name: str) -> str:
    return (_plain(name).split(" ") or [""])[0] or "Someone"


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


# ─── Which path, and what they said ───────────────────────────────────

def kind_for_form(form: Dict[str, Any]) -> Optional[str]:
    """The path a card starts, or None for a card that starts none (an
    event registration or a permission slip: those are records, not
    people waiting for someone)."""
    name = _norm(form.get("name") or "")
    ftype = _norm(form.get("form_type") or "")
    if ftype in ("event", "registration") or "registration" in name or "permission" in name:
        return None
    if "baptis" in name:
        return "baptism"
    if ftype == "volunteer" or "serve" in name or "volunteer" in name:
        return "serve"
    if "visit" in name:
        return "visit"
    if ftype == "connect_card" or "connect" in name:
        return "connect"
    return "general"


def _answer_text(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(_plain(v) for v in value if _plain(v))
    elif isinstance(value, bool):
        value = "Yes" if value else "No"
    return _plain(value)[:MAX_ANSWER]


def answers_from_form(form: Dict[str, Any], submission: Dict[str, Any]) -> List[Dict[str, str]]:
    """[{q, a}] in the card's own order: the question as the person read
    it and what they wrote. Name, email and phone stay on the contact."""
    out: List[Dict[str, str]] = []
    for f in form.get("fields") or []:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "").strip()
        label = _plain(f.get("label") or name)
        if not name or name in ("sol-hp", "_hp", "website") or _IDENTITY.match(_norm(label)) or _IDENTITY.match(_norm(name)):
            continue
        a = _answer_text((submission or {}).get(name))
        if a:
            out.append({"q": label[:200], "a": a})
        if len(out) >= MAX_ANSWERS:
            break
    return out


_CONNECT_QUESTIONS = {
    "visits": "Have you been here before?",
    "interests": "I’m interested in",
    "heard_from": "How did you hear about us?",
    "notes": "Anything else?",
}


def answers_from_connect(fields: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for key, value in (fields or {}).items():
        k = str(key or "").strip()
        if not k or _IDENTITY.match(_norm(k.replace("_", " "))) or k in ("first_name", "last_name", "website"):
            continue
        a = _answer_text(value)
        if a:
            out.append({"q": _CONNECT_QUESTIONS.get(k, k.replace("_", " ").capitalize()), "a": a})
        if len(out) >= MAX_ANSWERS:
            break
    return out


# ─── Chief picks the leader ───────────────────────────────────────────

def _holders(roles: Iterable[Dict[str, Any]], role: str, load: Dict[str, int],
             scope: Optional[str] = None) -> List[Dict[str, Any]]:
    """Active holders of a role (for a team, its leader), the one carrying
    the fewest open follow-ups first."""
    want = _norm(scope) if scope is not None else None
    found = [r for r in roles if r.get("status") == "active" and r.get("role") == role
             and (want is None or _norm(r.get("scope") or "") == want)]
    return sorted(found, key=lambda r: (load.get(str(r["contact_id"]), 0), _norm(r.get("name") or "")))


_PASTOR_ASK = re.compile(r"talk (with|to) a pastor|pastoral care")
# Whole words only: "Hospitality Team" is a team, not a hospital.
_CARE_NEED = re.compile(r"\b(hospital|hospitali[sz]ed|in the hospital|surgery|sick|illness|cancer|grief|grieving|"
                        r"funeral|bereaved|bereavement|meal|meals|homebound|shut[- ]?in|benevolence|"
                        r"need food|visit me)\b")


def stream_for(kind: str, answers: List[Dict[str, str]]) -> Tuple[str, str]:
    """(stream, why): what a card asks for, in the words the reason uses.
    Asking for a pastor comes first. A Baptism, Serve or Plan your visit
    card is its own kind. On a connect card (or a card with no kind) a care
    need, in the person's words, comes before the card's kind; anything
    else is what no one else holds."""
    text = " · ".join(_norm(a["a"]) for a in answers)
    if _PASTOR_ASK.search(text):
        return "pastor_ask", ("They asked to talk with a pastor." if "pastoral care" not in text
                              else "They asked for pastoral care.")
    if kind in ("baptism", "serve", "visit"):
        return kind, ""
    if _CARE_NEED.search(text):
        return "care_need", "Their card mentions a care need."
    if kind == "connect":
        return "connect", ""
    return "leftover", "Cards without their own leader go to the senior pastor."


def _effective_defs(all_defs: Optional[List[Dict[str, Any]]], roles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The church's roles, plus the first version's four for any key its
    holders carry that its library doesn't have yet (a church whose page
    was never opened still routes as it did)."""
    import church_roles as cr
    out = list(all_defs or [])
    have = {d["key"] for d in out}
    for k in sorted({str(r.get("role") or "") for r in roles}):
        if k and k not in have and k in cr.LEGACY:
            leg = cr.LEGACY[k]
            out.append({"id": f"legacy:{k}", "key": k, "title": leg["title"], "job": leg["job"],
                        "covers": leg["covers"], "reports_to": None, "oversees_teams": [],
                        "handles": cr.clean_handles(leg["job"], leg["handles"]), "sees": [], "status": "active"})
    return out


def _team_answer(answers: List[Dict[str, str]]) -> str:
    for a in answers:
        q = _norm(a["q"])
        if "serve" in q or "team" in q or "ministry" in q:
            return a["a"]
    return ""


_STREAM_WORDS = {"baptism": "Baptism cards", "visit": "Plan your visit cards", "connect": "Connect cards",
                 "pastor_ask": "Those", "care_need": "Care needs"}


def choose(kind: str, answers: List[Dict[str, str]], roles: List[Dict[str, Any]],
           load: Optional[Dict[str, int]] = None, all_defs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """{leader: holder row or None, role: its key, reason}. The church's own
    roles decide: the ones whose job takes what the card asks for (its
    stream), the holder with the fewest open follow-ups first. A team's
    sign-up goes to its leader, else the role with the team under it, else
    up the chain. Nobody for it: the senior role, else the office. The
    reason is said to the leader and shown to the office, so it names what
    decided it."""
    import church_roles as cr
    load = load or {}
    defs = _effective_defs(all_defs, roles)
    held = [r for r in roles if r.get("status") == "active"]
    stream, why = stream_for(kind, answers)

    def best(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(rows, key=lambda r: (load.get(str(r["contact_id"]), 0), _norm(r.get("name") or "")))

    def to(rows: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
        pick = best(rows)[0]
        return {"leader": pick, "role": pick["role"], "reason": reason}

    seniors = [d for d in defs if d["job"] == "senior" and d.get("status", "active") == "active"]
    top = [r for r in held if r["role"] in {d["key"] for d in seniors}]
    senior_title = seniors[0]["title"] if seniors else "Pastor"

    def fallback(said: str) -> Dict[str, Any]:
        if top:
            return to(top, f"{said} It’s with {best(top)[0].get('name') or 'the pastor'} until someone is named.")
        return {"leader": None, "role": "",
                "reason": f"{said} No one is named {senior_title} yet, so it’s with the office."}

    def takers(s: str, team: str = "") -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
        out = []
        for d in defs:
            if d.get("status", "active") != "active" or s not in (d.get("handles") or []):
                continue
            if s == "serve" and d.get("covers") == "team":
                rows = [r for r in held if r["role"] == d["key"] and _norm(r.get("scope") or "") == _norm(team)]
            elif s == "serve":
                if not any(_norm(t) == _norm(team) for t in d.get("oversees_teams") or []):
                    continue
                rows = [r for r in held if r["role"] == d["key"]]
            else:
                rows = [r for r in held if r["role"] == d["key"]]
            if rows:
                out.append((d, rows))
        return out

    if stream == "serve":
        team = _team_answer(answers)
        if not team:
            return fallback("They didn’t pick a team.")
        leads = [t for t in takers("serve", team) if t[0].get("covers") == "team"]
        if leads:
            rows = [r for _d, rs in leads for r in rs]
            return to(rows, f"They picked {team}, and {first_name(best(rows)[0].get('name') or '')} leads it.")
        over = takers("serve", team)
        if over:
            d, rows = over[0]
            return to(rows, f"They picked {team}, which has no leader yet; it’s under the {d['title']}.")
        team_role = next((d for d in defs if d.get("covers") == "team" and d["job"] == "team"), None)
        up = cr.chain_above(team_role, defs,
                            cr.active_holders(held), team=team) if team_role else []
        up = [(d, rows) for d, rows in up if d["job"] != "senior"]
        if up:
            d, rows = up[0]
            return to(rows, f"{team} has no leader yet, so it goes to the {d['title']}.")
        return fallback(f"{team} has no leader yet.")
    if stream == "leftover":
        return to(top, why) if top else {"leader": None, "role": "",
                                         "reason": f"No one is named {senior_title} yet, so it’s with the office."}
    found = takers(stream)
    if found:
        # The role made for this (handling the fewest streams) before a
        # broader one: a Baptism minister before Ministers who also take
        # pastor requests, a Welcome Team lead before a pastor.
        word = stream.split("_")[0][:6]
        found.sort(key=lambda t: (t[0]["job"] == "senior", len(t[0].get("handles") or []),
                                  word not in (t[0]["key"] + " " + t[0]["title"].casefold())))
        d, rows = found[0]
        if stream == "pastor_ask":
            return to(rows, why)
        what = _STREAM_WORDS.get(stream, "Those")
        return to(rows, f"{why} {what} go to the {d['title']}." if why else f"{what} go to the {d['title']}.")
    return fallback(why or f"No one holds a role that takes {_STREAM_WORDS.get(stream, 'these').lower()} yet.")


# ─── Reads ────────────────────────────────────────────────────────────

def _contacts(biz: str, ids: Iterable[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    rows = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})"
                 "&select=id,name,email,phone")
    if rows is None:
        return None
    return {str(r["id"]): {"id": str(r["id"]), "name": _plain(r.get("name")) or "Someone",
                           "email": r.get("email") or "", "phone": r.get("phone") or ""} for r in rows}


def roles(business_id: str) -> Optional[List[Dict[str, Any]]]:
    """Every role row, with the member's name, email and phone."""
    biz = str(business_id)
    rows = _rows(f"/church_leader_roles?business_id=eq.{_q(biz)}&status=neq.declined"
                 "&select=id,contact_id,role,scope,status,invited_at,answered_at,term_ends_at&order=invited_at.asc")
    if rows is None:
        return None
    people = _contacts(biz, (r["contact_id"] for r in rows))
    if people is None:
        return None
    out = []
    for r in rows:
        p = people.get(str(r["contact_id"]))
        if not p:
            continue
        out.append({**r, "id": str(r["id"]), "contact_id": str(r["contact_id"]), "name": p["name"],
                    "email": p["email"], "phone": p["phone"], "scope": r.get("scope") or ""})
    return out


def _load(biz: str) -> Optional[Dict[str, int]]:
    rows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&status=eq.open&select=leader_contact_id")
    if rows is None:
        return None
    load: Dict[str, int] = {}
    for r in rows:
        if r.get("leader_contact_id"):
            k = str(r["leader_contact_id"])
            load[k] = load.get(k, 0) + 1
    return load


def teams(business_id: str) -> Optional[List[str]]:
    """The team names a Serve card offers, in its own order: the choices a
    team leader's role can name."""
    rows = _rows(f"/intake_forms?business_id=eq.{_q(business_id)}&select=name,form_type,fields")
    if rows is None:
        return None
    out: List[str] = []
    for f in rows:
        if kind_for_form(f) != "serve":
            continue
        for fld in f.get("fields") or []:
            label = _norm((fld or {}).get("label") or "")
            if isinstance(fld, dict) and ("serve" in label or "team" in label) and fld.get("options"):
                for o in fld["options"]:
                    o = _plain(o)
                    if o and o not in out:
                        out.append(o)
    return out


# ─── A card comes in ──────────────────────────────────────────────────

def _note(biz: str, fid: str, author_kind: str, kind: str, body: str = "", *, pastors_only: bool = False,
          author_contact_id: Optional[str] = None, author_user_id: Optional[str] = None,
          author_name: str = "") -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_post_as_service("/church_follow_up_notes", {
        "business_id": biz, "follow_up_id": fid, "author_kind": author_kind, "kind": kind,
        "body": (body or "")[:4000], "pastors_only": bool(pastors_only),
        "author_contact_id": author_contact_id, "author_user_id": author_user_id,
        "author_name": (author_name or "")[:120],
    })
    return rows[0] if isinstance(rows, list) and rows else None


def start(business_id: str, contact_id: str, *, card_key: str, card_name: str, kind: str,
          answers: List[Dict[str, str]], source_event: str = "") -> Optional[Dict[str, Any]]:
    """Open a follow-up for this person and hand it to a leader. Returns the
    row, or None when it already exists (a retried card) or could not be
    saved. Never raises: a card is saved whether or not this works."""
    biz, cid = str(business_id), str(contact_id)
    try:
        # Every read here decides something, so a read that failed stops the
        # hand-off rather than reading as "nothing there": a Supabase blip
        # must never hand a card to the office as "no pastor named", nor let
        # a second follow-up through. The card itself is already saved.
        if source_event:
            had = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&source_event=eq.{_q(source_event)}&select=id&limit=1")
            if had is None:
                logger.warning("church follow-up skipped: duplicate check failed (business %s)", biz[:8])
                return None
            if had:
                return None
        # The same person filling in the same card again while someone is
        # already on it: one follow-up, with what they wrote this time.
        open_one = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                         f"&card_key=eq.{_q(card_key[:80])}&status=in.(open,handed_back)&select=id&limit=1")
        if open_one is None:
            logger.warning("church follow-up skipped: open check failed (business %s)", biz[:8])
            return None
        if open_one:
            said = "; ".join(f"{a['q']} {a['a']}" for a in answers)[:1500]
            _note(biz, str(open_one[0]["id"]), "chief", "note",
                  "Filled in the card again." + (f" {said}" if said else ""))
            return None
        # The church's roles as they stand. A card never fills the library
        # (the office's first visit to Leaders & roles does); before then
        # the first version's roles its holders carry decide, as they did.
        import church_roles as cr
        all_roles, load, all_defs = roles(biz), _load(biz), cr.defs(biz)
        if all_roles is None or load is None or all_defs is None:
            logger.warning("church follow-up skipped: roles could not be read (business %s)", biz[:8])
            return None
        pick = choose(kind, answers, all_roles, load, all_defs)
        steps = PATHS.get(kind) or PATHS["general"]
        now = _now()
        leader = pick["leader"]
        rows = sb_clients.sb_post_as_service("/church_follow_ups", {
            "business_id": biz, "contact_id": cid, "card_key": card_key[:80], "card_name": (card_name or "")[:120],
            "path_kind": kind, "answers": answers, "steps": steps, "step": 0,
            "leader_contact_id": leader["contact_id"] if leader else None,
            "leader_role": pick["role"], "reason": pick["reason"][:400], "assigned_by": "chief",
            "assigned_at": _iso(now), "due_at": _iso(now + timedelta(days=int(steps[0]["days"]))),
            "status": "open", "source_event": (source_event or "")[:80],
        })
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        _note(biz, str(row["id"]), "chief", "assigned",
              (f"Handed to {leader.get('name')}. " if leader else "") + pick["reason"])
        return row
    except Exception:
        logger.warning("church follow-up not started for business %s", biz[:8], exc_info=True)
        return None


def is_church(business: Dict[str, Any]) -> bool:
    try:
        import vertical_registry
        return vertical_registry.resolve((business or {}).get("type")) == "ministry"
    except Exception:
        return False


def on_intake_form(business: Dict[str, Any], form: Dict[str, Any], submission: Dict[str, Any],
                   contact_id: str, source_event: str = "") -> Optional[Dict[str, Any]]:
    """intake_endpoint's hook, after the card's form_submit event."""
    if not is_church(business) or not contact_id:
        return None
    kind = kind_for_form(form)
    if not kind:
        return None
    return start(str(business["id"]), str(contact_id), card_key=f"form:{form.get('id')}",
                 card_name=_plain(form.get("name")) or "Card", kind=kind,
                 answers=answers_from_form(form, submission or {}), source_event=source_event)


def on_connect_card(business_id: str, contact_id: str, data: Dict[str, Any], receipt: str = "") -> Optional[Dict[str, Any]]:
    """public_site's hook, after a website connect card is stored."""
    if not contact_id:
        return None
    return start(str(business_id), str(contact_id), card_key="web:connect_card", card_name="Connect card",
                 kind="connect", answers=answers_from_connect((data or {}).get("fields") or {}),
                 source_event=str(receipt or ""))


# ─── One follow-up ────────────────────────────────────────────────────

def _one(biz: str, fid: str) -> Dict[str, Any]:
    rows = _rows(f"/church_follow_ups?id=eq.{_q(fid)}&business_id=eq.{_q(biz)}&select=*&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn’t be loaded. Try again in a moment.")
    if not rows:
        raise HTTPException(404, "That follow-up isn’t here")
    return rows[0]


def _patch(biz: str, fid: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    patch = dict(patch, updated_at=_iso(_now()))
    rows = sb_clients.sb_patch_as_service(f"/church_follow_ups?id=eq.{_q(fid)}&business_id=eq.{_q(biz)}", patch)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn’t save. Nothing was changed — try again.")
    return rows[0]


def _advanced(row: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """The patch that moves a follow-up past its current step."""
    steps = row.get("steps") or []
    nxt = int(row.get("step") or 0) + 1
    if nxt >= len(steps):
        return {"step": len(steps), "status": "done", "done_at": _iso(now), "late_level": 0}
    return {"step": nxt, "late_level": 0,
            "due_at": _iso(now + timedelta(days=int(steps[nxt].get("days") or 7)))}


def advance(business_id: str, follow_up_id: str, *, author_kind: str, author_name: str = "",
            author_contact_id: Optional[str] = None, author_user_id: Optional[str] = None) -> Dict[str, Any]:
    biz, fid = _uid(business_id, "business"), _uid(follow_up_id, "follow-up")
    row = _one(biz, fid)
    if row.get("status") != "open":
        raise HTTPException(400, "This one is already finished")
    steps = row.get("steps") or []
    step = int(row.get("step") or 0)
    title = steps[step]["title"] if step < len(steps) else "The path"
    out = _patch(biz, fid, _advanced(row, _now()))
    _note(biz, fid, author_kind, "done" if out.get("status") == "done" else "step", f"{title}: done.",
          author_contact_id=author_contact_id, author_user_id=author_user_id, author_name=author_name)
    return out


# ─── The office ───────────────────────────────────────────────────────

def _view(row: Dict[str, Any], people: Dict[str, Dict[str, Any]], notes: List[Dict[str, Any]],
          role_of: Dict[str, str], now: datetime) -> Dict[str, Any]:
    person = people.get(str(row["contact_id"])) or {"id": str(row["contact_id"]), "name": "Someone", "email": "", "phone": ""}
    lid = str(row.get("leader_contact_id") or "")
    leader = people.get(lid) if lid else None
    due = _parse(row.get("due_at"))
    return {
        "id": str(row["id"]),
        "person": {"id": person["id"], "name": person["name"], "initials": initials(person["name"]),
                   "email": person.get("email") or "", "phone": person.get("phone") or ""},
        "card_name": row.get("card_name") or "", "card_key": row.get("card_key") or "",
        "path_kind": row.get("path_kind"), "answers": row.get("answers") or [], "steps": row.get("steps") or [],
        "step": int(row.get("step") or 0), "status": row.get("status"), "late_level": int(row.get("late_level") or 0),
        "late": bool(row.get("status") == "open" and due and due < now),
        "due_at": row.get("due_at"), "created_at": row.get("created_at"), "assigned_at": row.get("assigned_at"),
        "done_at": row.get("done_at"), "reason": row.get("reason") or "",
        "leader": ({"id": lid, "name": leader["name"], "initials": initials(leader["name"]),
                    "role": row.get("leader_role") or role_of.get(lid, "")} if leader else None),
        "notes": [{"id": str(n["id"]), "author_kind": n.get("author_kind"), "author_name": n.get("author_name") or "",
                   "kind": n.get("kind"), "body": n.get("body") or "", "pastors_only": bool(n.get("pastors_only")),
                   "created_at": n.get("created_at")} for n in notes],
    }


def _notes_for(biz: str, ids: List[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    if not ids:
        return {}
    rows = _rows(f"/church_follow_up_notes?business_id=eq.{_q(biz)}&follow_up_id=in.({','.join(ids)})"
                 "&select=id,follow_up_id,author_kind,author_contact_id,author_name,kind,body,pastors_only,created_at"
                 "&order=created_at.desc&limit=2000")
    if rows is None:
        return None
    out: Dict[str, List[Dict[str, Any]]] = {}
    for n in rows:
        out.setdefault(str(n["follow_up_id"]), []).append(n)
    return out


def board(business_id: str, *, done_days: int = 30) -> Optional[Dict[str, Any]]:
    """The office's Follow-up board: everyone in follow-up, who has them,
    where they are on their path, and every note (pastors-only ones too:
    the office is the pastors' side). None when a read failed."""
    biz = str(business_id)
    now = _now()
    since = _iso(now - timedelta(days=done_days))
    rows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}"
                 f"&or=(status.in.(open,handed_back),done_at.gte.{_q(since)})"
                 "&select=*&order=created_at.desc&limit=500")
    if rows is None:
        return None
    all_roles = roles(biz)
    if all_roles is None:
        return None
    ids = {str(r["contact_id"]) for r in rows} | {str(r["leader_contact_id"]) for r in rows if r.get("leader_contact_id")}
    people = _contacts(biz, ids)
    notes = _notes_for(biz, [str(r["id"]) for r in rows])
    if people is None or notes is None:
        return None
    import church_roles as cr
    all_defs = cr.defs(biz) or []
    role_of = {r["contact_id"]: r["role"] for r in all_roles if r["status"] == "active"}
    items = [_view(r, people, notes.get(str(r["id"]), []), role_of, now) for r in rows]
    for i in items:
        if i["leader"]:
            i["leader"]["role_title"] = cr.title_of(i["leader"]["role"], all_defs)
    live = [i for i in items if i["status"] in ("open", "handed_back")]
    load: Dict[str, Dict[str, Any]] = {}
    for r in all_roles:
        if r["status"] != "active":
            continue
        e = load.setdefault(r["contact_id"], {"contact_id": r["contact_id"], "name": r["name"],
                                              "initials": initials(r["name"]), "roles": [], "open": 0})
        e["roles"].append({"role": r["role"], "label": cr.title_of(r["role"], all_defs), "scope": r["scope"]})
    for i in live:
        if i["leader"] and i["leader"]["id"] in load and i["status"] == "open":
            load[i["leader"]["id"]]["open"] += 1
    return {
        "follow_ups": items,
        "counts": {"open": sum(1 for i in live if i["status"] == "open"),
                   "with_no_one": sum(1 for i in live if not i["leader"] or i["status"] == "handed_back"),
                   "late": sum(1 for i in live if i["late"]),
                   "done": sum(1 for i in items if i["status"] == "done")},
        "leaders": sorted(load.values(), key=lambda e: (-e["open"], _norm(e["name"]))),
        "done_days": done_days,
    }


def _active_holder(biz: str, contact_id: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/church_leader_roles?business_id=eq.{_q(biz)}&contact_id=eq.{_q(contact_id)}"
                 "&status=eq.active&select=role&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    return rows[0] if rows else None


def reassign(business_id: str, follow_up_id: str, leader_contact_id: Optional[str], *,
             by_user: str, by_name: str = "") -> Dict[str, Any]:
    """The office hands a follow-up to someone else (any member holding an
    active role), or takes it back (leader_contact_id None)."""
    biz, fid = _uid(business_id, "business"), _uid(follow_up_id, "follow-up")
    row = _one(biz, fid)
    if row.get("status") in ("done", "closed"):
        raise HTTPException(400, "This one is already finished")
    now = _now()
    steps = row.get("steps") or []
    step = min(int(row.get("step") or 0), max(len(steps) - 1, 0))
    patch: Dict[str, Any] = {"status": "open", "late_level": 0, "assigned_by": (by_user or "office")[:60],
                             "assigned_at": _iso(now), "leader_told_at": None,
                             "due_at": _iso(now + timedelta(days=int((steps[step] if steps else {}).get("days") or 2)))}
    if leader_contact_id:
        lid = _uid(leader_contact_id, "leader")
        role = _active_holder(biz, lid)
        if not role:
            raise HTTPException(400, "That person doesn’t hold a role yet. Name them on Leaders & roles first.")
        patch.update(leader_contact_id=lid, leader_role=role["role"], reason="Handed on by the office.")
    else:
        patch.update(leader_contact_id=None, leader_role="", reason="Taken back by the office.")
    out = _patch(biz, fid, patch)
    people = _contacts(biz, [leader_contact_id] if leader_contact_id else []) or {}
    who = (people.get(str(leader_contact_id)) or {}).get("name") if leader_contact_id else ""
    _note(biz, fid, "office", "reassigned", f"Handed to {who}." if who else "Taken back by the office.",
          author_user_id=by_user, author_name=by_name)
    return out


def office_note(business_id: str, follow_up_id: str, text: str, *, pastors_only: bool,
                by_user: str, by_name: str = "") -> Dict[str, Any]:
    biz, fid = _uid(business_id, "business"), _uid(follow_up_id, "follow-up")
    body = (text or "").strip()
    if not body:
        raise HTTPException(400, "Write the note first")
    _one(biz, fid)
    note = _note(biz, fid, "office", "note", body[:MAX_NOTE], pastors_only=pastors_only,
                 author_user_id=by_user, author_name=by_name)
    if not note:
        raise HTTPException(503, "That note didn’t save. Try again.")
    return note


def close(business_id: str, follow_up_id: str, *, by_user: str, by_name: str = "") -> Dict[str, Any]:
    biz, fid = _uid(business_id, "business"), _uid(follow_up_id, "follow-up")
    if _one(biz, fid).get("status") in ("done", "closed"):
        raise HTTPException(400, "This one is already finished")
    out = _patch(biz, fid, {"status": "closed", "done_at": _iso(_now())})
    _note(biz, fid, "office", "done", "Closed by the office.", author_user_id=by_user, author_name=by_name)
    return out


# ─── Roles ────────────────────────────────────────────────────────────

def _role_def(biz: str, role: str) -> Dict[str, Any]:
    """The church's role a request names, by its id or its key."""
    import church_roles as cr
    all_defs = cr.defs(biz, with_drafts=True)
    if all_defs is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    d = next((x for x in all_defs if x["id"] == str(role) or x["key"] == str(role)), None)
    if not d and str(role) in cr.LEGACY:
        leg = cr.LEGACY[str(role)]
        d = {"id": "", "key": leg["key"], "title": leg["title"], "job": leg["job"], "covers": leg["covers"],
             "definition": cr.definition_for(leg["job"], leg["title"]), "status": "active",
             "term_months": None, "needs_class": None, "reports_to": None}
    if not d:
        raise HTTPException(400, "That isn’t one of your roles")
    d["reports_to_title"] = next((x["title"] for x in all_defs if x["id"] == d.get("reports_to")), "")
    return d


def add_role(business_id: str, contact_id: str, role: str, scope: str = "", *, by_user: str) -> Dict[str, Any]:
    """Ask a member to take a role (the church's role, by id or key). It
    starts 'invited'; the member says yes on their member page. A declined
    role asked again is asked again."""
    biz, cid = _uid(business_id, "business"), _uid(contact_id, "member")
    d = _role_def(biz, role)
    if d.get("status") == "draft":
        raise HTTPException(400, "That role is a draft. Save it first.")
    if d["job"] == "office":
        raise HTTPException(400, "Office roles work with an office login. Give one in Settings → Team.")
    if d["job"] == "kids":
        raise HTTPException(400, "Kids and youth leaders are approved on Kids check-in, with their background check.")
    role = d["key"]
    scope = _plain(scope)[:120] if d.get("covers") == "team" else ""
    if d.get("covers") == "team" and not scope:
        raise HTTPException(400, "Pick the team they’ll lead")
    people = _contacts(biz, [cid])
    if people is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    if cid not in people:
        raise HTTPException(400, "That person isn’t one of your members")
    if d.get("needs_class"):
        done = _rows(f"/academy_enrollments?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                     f"&course_id=eq.{_q(d['needs_class'])}&completed_at=not.is.null&select=id&limit=1")
        if done is None:
            raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
        if not done:
            course = _rows(f"/academy_courses?id=eq.{_q(d['needs_class'])}&select=title&limit=1") or [{}]
            raise HTTPException(400, f"{first_name(people[cid]['name'])} hasn’t finished "
                                     f"{_plain(course[0].get('title')) or 'the class this role needs'} yet")
    had = _rows(f"/church_leader_roles?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}&role=eq.{_q(role)}"
                f"&scope=eq.{_q(scope)}&select=*&limit=1")
    if had is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    now = _iso(_now())
    if had:
        if had[0].get("status") != "declined":
            return {**had[0], "already": True}
        rows = sb_clients.sb_patch_as_service(
            f"/church_leader_roles?id=eq.{_q(had[0]['id'])}&business_id=eq.{_q(biz)}",
            {"status": "invited", "invited_by": by_user, "invited_at": now, "answered_at": None, "updated_at": now})
    else:
        rows = sb_clients.sb_post_as_service("/church_leader_roles", {
            "business_id": biz, "contact_id": cid, "role": role, "scope": scope,
            "status": "invited", "invited_by": by_user, "invited_at": now})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn’t save. Try again.")
    return {**rows[0], "person": people[cid], "def": d}


def role_name(role_row: Dict[str, Any]) -> str:
    """What someone is asked to lead, as a sentence says it: "the
    Hospitality Team", "the Youth Ministry (YWD) team", "Intercessor
    leader"."""
    scope = _plain(role_row.get("scope"))
    d = role_row.get("def") or {}
    if (d.get("covers") == "team" or role_row.get("role") == "team_leader") and scope:
        return f"the {scope}" if re.search(r"\bteam\b", scope, re.I) else f"the {scope} team"
    return d.get("title") or role_row.get("label") or ROLE_LABELS.get(role_row.get("role"), "a leader")


def _ask_line(d: Dict[str, Any], what: str, church: str) -> str:
    """"Will you be Love City's Intercessor leader?" / "Will you lead the
    Hospitality Team at Love City?" """
    if d.get("covers") == "team":
        return f"Will you lead {what} at {church}?"
    return f"Will you be {church}’s {what}?"


async def send_invite(business: Dict[str, Any], role_row: Dict[str, Any]) -> bool:
    """Email the member that they were asked to lead, with what the role is
    (its definition, in the church's words) and who they'd answer to.
    Their member page (Lead tab) is where they say yes, with a code."""
    import asyncio
    import church_roles as cr
    person = role_row.get("person") or {}
    if not person.get("email"):
        return False
    origin = await asyncio.to_thread(site_origin, str(business["id"]))
    church = _plain(business.get("name")) or "your church"
    d = role_row.get("def") or {}
    what = role_name(role_row)
    job = cr.JOBS.get(d.get("job") or "", {})
    lines = [f"Hi {html.escape(first_name(person.get('name') or ''))},",
             f"{html.escape(church)} asked you to {'lead' if d.get('covers') == 'team' else 'be their'} "
             f"<b>{html.escape(what)}</b>."]
    if d.get("definition"):
        lines.append(f"<i>{html.escape(d['definition'])}</i>")
    if job:
        lines.append(f"You’d get: {html.escape(job['gets'])} You’d never see: {html.escape(job['never'])}")
    if d.get("reports_to_title"):
        lines.append(f"You’d answer to the {html.escape(d['reports_to_title'])}.")
    lines.append("Say yes on your member page and a Lead tab appears. You sign in the same way as always, with a code.")
    return await _email(business, person["email"], person.get("name") or "", _ask_line(d, what, church),
                        _mail_html(lines, f"{origin}/my/lead" if origin else "", "See the invitation"),
                        f"cfu-invite-{role_row.get('id')}-{role_row.get('invited_at')}")


def remove_role(business_id: str, role_id: str) -> Dict[str, Any]:
    """Take a role away. Someone who no longer leads anything can't open
    their Lead tab, so the people handed to them go back to the office
    (the sweep alerts it), never left with a leader who can't reach them."""
    biz, rid = _uid(business_id, "business"), _uid(role_id, "role")
    row = _rows(f"/church_leader_roles?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&select=contact_id&limit=1")
    if row is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    if not sb_clients.sb_delete_as_service(f"/church_leader_roles?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "That didn’t save. Try again.")
    if not row:
        return {"returned": 0}
    lid = str(row[0]["contact_id"])
    still = _rows(f"/church_leader_roles?business_id=eq.{_q(biz)}&contact_id=eq.{_q(lid)}&status=eq.active&select=id&limit=1")
    if still is None or still:
        return {"returned": 0}
    mine = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&leader_contact_id=eq.{_q(lid)}"
                 "&status=in.(open,handed_back)&select=id") or []
    people = _contacts(biz, [lid]) or {}
    who = (people.get(lid) or {}).get("name") or "Their leader"
    for f in mine:
        sb_clients.sb_patch_as_service(
            f"/church_follow_ups?id=eq.{_q(f['id'])}&business_id=eq.{_q(biz)}",
            {"leader_contact_id": None, "leader_role": "", "leader_told_at": None, "status": "open",
             "reason": f"{who} no longer leads, so they’re with the office.", "updated_at": _iso(_now())})
        _note(biz, str(f["id"]), "chief", "reassigned", f"{who} no longer leads. Back with the office.")
    # Prayer they hadn't prayed over yet goes back to Prayer & care too.
    prayers = _rows(f"/ministry_care_requests?business_id=eq.{_q(biz)}&leader_contact_id=eq.{_q(lid)}"
                    "&leader_prayed_at=is.null&select=id") or []
    for p in prayers:
        sb_clients.sb_patch_as_service(
            f"/ministry_care_requests?id=eq.{_q(p['id'])}&business_id=eq.{_q(biz)}",
            {"leader_contact_id": None, "leader_role": "", "leader_told_at": None, "leader_due_at": None,
             "leader_late_level": 0, "updated_at": _iso(_now())})
    return {"returned": len(mine), "prayer_returned": len(prayers)}


# ─── The leader (their member page) ───────────────────────────────────

def roles_for(business_id: str, contact_id: str) -> Optional[List[Dict[str, Any]]]:
    """This member's roles, invited and active (declined ones are gone)."""
    rows = _rows(f"/church_leader_roles?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
                 "&status=in.(invited,active)&select=id,role,scope,status,invited_at&order=invited_at.asc")
    if rows is None:
        return None
    import church_roles as cr
    all_defs = cr.defs(str(business_id)) or []
    by = cr.by_key(all_defs)
    ids = {d["id"]: d for d in all_defs}
    out = []
    for r in rows:
        d = by.get(r["role"]) or {}
        up = ids.get(d.get("reports_to") or "") if d else None
        out.append({**r, "id": str(r["id"]), "label": cr.title_of(r["role"], all_defs), "scope": r.get("scope") or "",
                    "job": d.get("job") or (cr.LEGACY.get(r["role"]) or {}).get("job") or "",
                    "definition": d.get("definition") or "", "covers": d.get("covers") or "church",
                    "handles": d.get("handles") or [], "reports_to_title": up["title"] if up else "",
                    "term_months": d.get("term_months")})
    return out


def answer_invite(business_id: str, contact_id: str, role_id: str, yes: bool) -> bool:
    """Yes or not now. A yes to a role with a term starts the term today."""
    rid = _uid(role_id, "role")
    now = _now()
    patch: Dict[str, Any] = {"status": "active" if yes else "declined", "answered_at": _iso(now), "updated_at": _iso(now)}
    if yes:
        held = _rows(f"/church_leader_roles?id=eq.{_q(rid)}&business_id=eq.{_q(business_id)}&select=role&limit=1") or []
        if held:
            import church_roles as cr
            d = cr.by_key(cr.defs(str(business_id)) or []).get(held[0]["role"]) or {}
            if d.get("term_months"):
                patch["term_ends_at"] = _iso(now + timedelta(days=round(30.44 * int(d["term_months"]))))
    rows = sb_clients.sb_patch_as_service(
        f"/church_leader_roles?id=eq.{_q(rid)}&business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
        "&status=eq.invited", patch)
    return isinstance(rows, list) and bool(rows)


def _leader_notes(notes: List[Dict[str, Any]], leader_contact_id: str) -> List[Dict[str, Any]]:
    """What a leader may read: everything on their follow-up except another
    person's pastors-only notes."""
    return [n for n in notes if not n.get("pastors_only") or str(n.get("author_contact_id") or "") == leader_contact_id]


def leader_view(business_id: str, leader_contact_id: str) -> Optional[Dict[str, Any]]:
    """The Lead tab: the follow-ups handed to this member, open first, and
    the ones they finished in the last 30 days (the count only)."""
    biz, lid = str(business_id), str(leader_contact_id)
    now = _now()
    rows = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&leader_contact_id=eq.{_q(lid)}"
                 f"&or=(status.eq.open,done_at.gte.{_q(_iso(now - timedelta(days=30)))})"
                 "&select=*&order=due_at.asc&limit=200")
    if rows is None:
        return None
    open_rows = [r for r in rows if r.get("status") == "open"]
    people = _contacts(biz, {str(r["contact_id"]) for r in open_rows} | {lid})
    notes = _notes_for(biz, [str(r["id"]) for r in open_rows])
    if people is None or notes is None:
        return None
    items = [_view(r, people, _leader_notes(notes.get(str(r["id"]), []), lid), {}, now) for r in open_rows]
    return {"follow_ups": items, "done_30": sum(1 for r in rows if r.get("status") == "done")}


def _leader_one(biz: str, fid: str, lid: str) -> Dict[str, Any]:
    row = _one(biz, _uid(fid, "follow-up"))
    if str(row.get("leader_contact_id") or "") != lid or row.get("status") != "open":
        raise HTTPException(404, "That follow-up isn’t handed to you")
    return row


def leader_note(business_id: str, leader: Dict[str, Any], follow_up_id: str, outcome: str, text: str,
                pastors_only: bool) -> Dict[str, Any]:
    """A leader logs a conversation. One that reached the person finishes
    "Reach out" on its own, so nobody has to tick it as well."""
    biz, lid = str(business_id), str(leader["id"])
    row = _leader_one(biz, follow_up_id, lid)
    kind = outcome if outcome in OUTCOMES and outcome != "note" else "talked"
    body = (text or "").strip()[:MAX_NOTE]
    note = _note(biz, str(row["id"]), "leader", kind, body, pastors_only=pastors_only,
                 author_contact_id=lid, author_name=_plain(leader.get("name")))
    if not note:
        raise HTTPException(503, "That note didn’t save. Try again.")
    if kind in REACHED and int(row.get("step") or 0) == 0:
        advance(biz, str(row["id"]), author_kind="leader", author_contact_id=lid,
                author_name=_plain(leader.get("name")))
    return note


def leader_advance(business_id: str, leader: Dict[str, Any], follow_up_id: str) -> Dict[str, Any]:
    biz, lid = str(business_id), str(leader["id"])
    row = _leader_one(biz, follow_up_id, lid)
    return advance(biz, str(row["id"]), author_kind="leader", author_contact_id=lid,
                   author_name=_plain(leader.get("name")))


def leader_hand_back(business_id: str, leader: Dict[str, Any], follow_up_id: str, text: str = "") -> Dict[str, Any]:
    biz, lid = str(business_id), str(leader["id"])
    row = _leader_one(biz, follow_up_id, lid)
    out = _patch(biz, str(row["id"]), {"status": "handed_back"})
    _note(biz, str(row["id"]), "leader", "handed_back", (text or "").strip()[:MAX_NOTE] or "Handed back to the office.",
          author_contact_id=lid, author_name=_plain(leader.get("name")))
    return out


# ─── Nobody waits: the sweep ──────────────────────────────────────────

def late_step(row: Dict[str, Any], now: datetime) -> Optional[Tuple[int, str]]:
    """(new level, note kind) when this follow-up has climbed a rung of the
    late ladder since the last sweep, else None. Only the highest rung due
    is taken, so a sweep that missed a day doesn't send three messages."""
    if row.get("status") != "open":
        return None
    due = _parse(row.get("due_at"))
    if not due or now < due:
        return None
    level = int(row.get("late_level") or 0)
    best = None
    for days, lvl, kind in LATE_LADDER:
        if now >= due + timedelta(days=days) and lvl > level:
            best = (lvl, kind)
    return best


def site_origin(business_id: str) -> str:
    """The church's own address (custom domain, else its subdomain)."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/business_sites?business_id=eq.{_q(business_id)}&select=slug,site_config&limit=1") or []
        if rows:
            cfg = rows[0].get("site_config") if isinstance(rows[0].get("site_config"), dict) else {}
            custom = str((cfg or {}).get("custom_domain") or "").strip().lower().strip("/")
            slug = str(rows[0].get("slug") or "").strip()
            if custom:
                return f"https://{custom}"
            if slug:
                return f"https://{slug}.mysolutionist.app"
    except Exception:
        logger.info("church follow-up: site address lookup skipped", exc_info=True)
    return ""


def _mail_html(lines: List[str], link: str, label: str) -> str:
    body = "".join(f"<p>{line}</p>" for line in lines)
    if link:
        body += (f'<p><a href="{html.escape(link)}" style="display:inline-block;padding:12px 20px;border-radius:999px;'
                 f'background:#111;color:#fff;text-decoration:none;font-weight:600">{html.escape(label)}</a></p>')
    return body


async def _email(biz: Dict[str, Any], to_email: str, to_name: str, subject: str, body: str, key: str) -> bool:
    if not to_email:
        return False
    import os
    from email_sender import send_via_resend
    try:
        await send_via_resend(
            to_email=to_email, to_name=to_name or None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=_plain(biz.get("name")) or "Your church", subject=subject, body=body,
            reply_to=None, business_id=str(biz["id"]), idempotency_key=key[:120])
        return True
    except Exception as e:
        logger.warning("church follow-up email failed (%s) for business %s", type(e).__name__, str(biz.get("id"))[:8])
        return False


async def _office_alert(biz_id: str, title: str, body: str, key: str, person_id: Optional[str]) -> bool:
    """True when the office's alert was raised (or already stands: it is
    deduplicated on `key`); False when it could not be, so the caller
    tries again on the next sweep instead of recording it as said."""
    try:
        import httpx
        import notification_engine
        async with httpx.AsyncClient(timeout=20) as client:
            await notification_engine.create_urgent_alert(
                client, biz_id, title, body, dedup_key=key, dedup_hours=24 * 7,
                suggested_action="Open the Follow-up board", related_contact_id=person_id)
        return True
    except Exception:
        logger.warning("church follow-up office alert failed for business %s", biz_id[:8], exc_info=True)
        return False


async def sweep(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every few minutes, across churches:
      · a new follow-up's leader is told it's theirs (once), or the office
        when there is no one to hand it to;
      · someone at "Reach out" who has had an email or text from the
        church since they were handed on moves on by themselves;
      · a late follow-up climbs the leader's chain: they're reminded on
        the day, the role they answer to is told a day late, and three
        days late one more step up, with the office asked to hand them on;
      · a leader whose term ended is the office's to ask again (once);
      · prayer handed to a member who leads gets the same (church_prayer)."""
    import asyncio
    now = now or _now()
    stats = {"told": 0, "office": 0, "reached": 0, "nudged": 0, "overseer_told": 0, "next_up": 0, "terms": 0}
    rows = await asyncio.to_thread(
        _rows, "/church_follow_ups?status=eq.open"
               f"&or=(leader_told_at.is.null,due_at.lt.{_q(_iso(now))},step.eq.0)&select=*&limit=500")
    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows or []:
        by_biz.setdefault(str(r["business_id"]), []).append(r)
    for biz_id, items in by_biz.items():
        try:
            await _sweep_church(biz_id, items, now, stats)
        except Exception:
            logger.warning("church follow-up sweep failed for business %s", biz_id[:8], exc_info=True)
    try:
        stats["terms"] = await _sweep_terms(now)
    except Exception:
        logger.warning("church role terms sweep failed", exc_info=True)
    try:
        import church_prayer
        stats["prayer"] = await church_prayer.sweep(now)
    except Exception:
        logger.warning("church prayer sweep failed", exc_info=True)
    return stats


async def _sweep_terms(now: datetime) -> int:
    """A leader whose term ended: the office is asked, once, whether to ask
    them again. The role stays theirs until someone changes it."""
    import asyncio
    import church_roles as cr
    rows = await asyncio.to_thread(
        _rows, f"/church_leader_roles?status=eq.active&term_ends_at=lt.{_q(_iso(now))}&term_told_at=is.null"
               "&select=id,business_id,contact_id,role,scope&limit=200") or []
    n = 0
    for r in rows:
        biz_id = str(r["business_id"])
        people = await asyncio.to_thread(_contacts, biz_id, [str(r["contact_id"])]) or {}
        name = (people.get(str(r["contact_id"])) or {}).get("name") or "A leader"
        title = cr.title_of(r["role"], await asyncio.to_thread(cr.defs, biz_id) or [])
        ok = await _office_alert(biz_id, f"{name}’s term as {title} has ended",
                                 "Ask them again, or name someone new on Leaders & roles. Nothing changes until you do.",
                                 f"church-role-term-{r['id']}", str(r["contact_id"]))
        if ok:
            await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                    f"/church_leader_roles?id=eq.{_q(r['id'])}&business_id=eq.{_q(biz_id)}",
                                    {"term_told_at": _iso(now)})
            n += 1
    return n


async def _sweep_church(biz_id: str, items: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    import asyncio
    bizs = await asyncio.to_thread(_rows, f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type&limit=1")
    if not bizs:
        return
    biz = bizs[0]
    ids = {str(r["contact_id"]) for r in items} | {str(r["leader_contact_id"]) for r in items if r.get("leader_contact_id")}
    import church_roles as cr
    all_roles = await asyncio.to_thread(roles, biz_id)
    all_defs = await asyncio.to_thread(cr.defs, biz_id)
    if all_roles is None or all_defs is None:
        return  # the chain can't be read today; next sweep
    held = cr.active_holders(all_roles)
    defs = _effective_defs(all_defs, all_roles)
    dmap = cr.by_key(defs)
    people = await asyncio.to_thread(_contacts, biz_id, ids)
    if people is None:
        return
    origin = await asyncio.to_thread(site_origin, biz_id)
    lead_link = f"{origin}/my/lead" if origin else ""
    church = _plain(biz.get("name")) or "Your church"

    # Someone already reached at "Reach out" moves on by themselves.
    first = [r for r in items if int(r.get("step") or 0) == 0 and r.get("leader_contact_id") and r.get("assigned_at")]
    if first:
        import church_reads
        since = min(_parse(r["assigned_at"]) or now for r in first)
        evs = await asyncio.to_thread(
            _rows, f"/events?business_id=eq.{_q(biz_id)}"
                   f"&contact_id=in.({','.join(_q(r['contact_id']) for r in first)})"
                   f"&event_type=in.({','.join(church_reads.REACH_OUT_EVENTS)})"
                   f"&created_at=gt.{_q(_iso(since))}&select=contact_id,created_at&limit=500") or []
        reached: Dict[str, datetime] = {}
        for e in evs:
            t = _parse(e.get("created_at"))
            if t:
                k = str(e["contact_id"])
                reached[k] = max(reached.get(k, t), t)
        for r in first:
            t = reached.get(str(r["contact_id"]))
            if t and t > (_parse(r["assigned_at"]) or now):
                await asyncio.to_thread(_patch, biz_id, str(r["id"]), _advanced(r, now))
                await asyncio.to_thread(_note, biz_id, str(r["id"]), "chief", "step",
                                        "Reach out: done. An email or text from the church reached them.")
                r.update(_advanced(r, now))
                stats["reached"] += 1

    for r in items:
        if r.get("status") != "open":
            continue
        fid, person = str(r["id"]), people.get(str(r["contact_id"])) or {"name": "Someone"}
        pname = person["name"]
        lid = str(r.get("leader_contact_id") or "")
        leader = people.get(lid) if lid else None
        steps = r.get("steps") or []
        step = int(r.get("step") or 0)
        step_title = steps[step]["title"] if step < len(steps) else ""
        pid = str(r["contact_id"])
        # Said only once it was said: a leader is "told" when their email
        # went out, or — with no leader, or none we can email — when the
        # office's alert was raised. A failed send is tried again next sweep.
        if not r.get("leader_told_at"):
            if leader and leader.get("email"):
                told = await _email(biz, leader["email"], leader["name"],
                                    f"{pname} is yours to follow up",
                                    _mail_html([f"Hi {html.escape(first_name(leader['name']))},",
                                                f"{html.escape(pname)} filled in the <b>{html.escape(r.get('card_name') or 'card')}</b> "
                                                f"at {html.escape(church)}, and Chief handed them to you. {html.escape(r.get('reason') or '')}",
                                                f"First step: <b>{html.escape(step_title)}</b>, "
                                                f"{html.escape((steps[step] if step < len(steps) else {}).get('rule') or '')}."],
                                               lead_link, "Open your Lead tab"),
                                    f"cfu-told-{fid}")
                stats["told"] += int(told)
            elif leader:
                told = await _office_alert(biz_id, f"Tell {leader['name']} about {pname}",
                                           f"Chief handed {pname} ({r.get('card_name') or 'a card'}) to {leader['name']}, "
                                           "who has no email on file, so they haven’t been told.",
                                           f"church-fu-noemail-{fid}", pid)
                stats["office"] += int(told)
            else:
                told = await _office_alert(biz_id, f"{pname} has no one yet",
                                           f"{r.get('card_name') or 'A card'}: {r.get('reason') or ''}",
                                           f"church-fu-none-{fid}", pid)
                stats["office"] += int(told)
            if told:
                await asyncio.to_thread(_patch, biz_id, fid, {"leader_told_at": _iso(now)})
        rung = late_step(r, now)
        if not rung:
            continue
        level, kind = rung
        delivered = True
        if kind == "nudged":
            if leader and leader.get("email"):
                delivered = await _email(biz, leader["email"], leader["name"], f"{pname} is waiting to hear from you",
                                         _mail_html([f"Hi {html.escape(first_name(leader['name']))},",
                                                     f"<b>{html.escape(step_title)}</b> for {html.escape(pname)} is due today. "
                                                     "When you’ve talked, jot a quick note on your Lead tab."],
                                                    lead_link, "Open your Lead tab"),
                                         f"cfu-nudge-{fid}-{r.get('due_at')}")
            else:
                delivered = await _office_alert(biz_id, f"{pname} is due today",
                                                f"“{step_title}” is due. {leader['name'] + ' has them, with no email on file' if leader else 'No one has them'}.",
                                                f"church-fu-due-{fid}-{r.get('due_at')}", pid)
        told_names = ""
        if kind in ("overseer_told", "next_up"):
            # Up the leader's own chain: a day late, the role they answer to;
            # three days late, one more step up. An empty role is passed
            # over; with no one above, the senior role is asked to hand them
            # on. No leader at all: the senior role from the start.
            who = leader["name"] if leader else "No one"
            role = dmap.get(r.get("leader_role") or "") if leader else None
            team = next((h.get("scope") or "" for h in all_roles
                         if h["contact_id"] == lid and h["role"] == (r.get("leader_role") or "")), "")
            above = cr.chain_above(role, defs, held,
                                   team=team, skip={lid} if lid else ())
            n = 0 if kind == "overseer_told" else 1
            rung_role, rung_people = above[min(n, len(above) - 1)] if above else (None, [])
            top = bool(rung_role and rung_role["job"] == "senior")
            late = "a day" if kind == "overseer_told" else "three days"
            for p in rung_people:
                await _email(biz, p.get("email") or "", p.get("name") or "",
                             f"{pname} hasn’t been reached" if kind == "overseer_told" else f"Hand {pname} to someone else?",
                             _mail_html([f"{html.escape(pname)} ({html.escape(r.get('card_name') or 'a card')}) is {late} past "
                                         f"<b>{html.escape(step_title)}</b>. {html.escape(who)} has them"
                                         + (f", and answers to you." if kind == "overseer_told" else ".")
                                         + (" Hand them to someone else on the Follow-up board?" if kind == "next_up" and top else "")],
                                        "", ""),
                             f"cfu-{kind}-{fid}-{r.get('due_at')}-{p['contact_id']}")
            told_names = ", ".join(p["name"] for p in rung_people)
            label = f" ({rung_role['title']})" if rung_role else ""
            if kind == "overseer_told":
                delivered = await _office_alert(biz_id, f"{pname} hasn’t been reached",
                                                f"A day past “{step_title}”. {who} has them. Told: "
                                                f"{told_names or 'no one above them'}{label}.",
                                                f"church-fu-late-{fid}-{r.get('due_at')}", pid)
            else:
                delivered = await _office_alert(biz_id, f"Hand {pname} to someone else?",
                                                f"Three days past “{step_title}” with {who}. Told: "
                                                f"{told_names or 'no one above them'}{label}.",
                                                f"church-fu-reassign-{fid}-{r.get('due_at')}", pid)
        if not delivered:
            continue  # the rung is climbed when its message goes out; next sweep tries again
        await asyncio.to_thread(_patch, biz_id, fid, {"late_level": level})
        await asyncio.to_thread(_note, biz_id, fid, "chief", kind, {
            "nudged": f"Nudged {leader['name'] if leader else 'the office'}: {step_title} is due.",
            "overseer_told": f"A day late. Told {told_names or 'the office'}.",
            "next_up": f"Three days late. Told {told_names or 'the office'}, and asked the office to hand them on.",
        }[kind])
        stats[kind] = stats.get(kind, 0) + 1
