"""church_sheet.py — one sheet per person: everything a login can see and do,
in one place (step one of the artifact "One sheet per person",
WE3jy89EXadQSjz9t8A2FV).

Kevin, 2026-11-17: "my wife suggested that we create a check list that would
work like they can uncheck and check certain things on the person they setup
and chief could see those checks and know the level of permission they have",
then "yes to all and build it".

Step one changes no rule. A login was described in six places (its level, its
areas, its lane, its duties, the keys, its job description); the sheet reads
them together and sets the first four through the writes they already had:

    its job ......... business_users.lane: one of the five starting jobs or
                      one of the church's own (church_job_defs). A label and a
                      starting point; it never changes anyone by itself
    its areas ....... business_users.areas (church_areas.set_login, the
                      Logins & areas write)
    its duties ...... church_duties.move, one duty at a time, logged there
    what's guarded .. read only here: who gave what and the bank, kids'
                      medical notes, pastors-only notes, inviting logins; who
                      holds each today and why (church_keys keeps the locks)
    its description . read only here (church_job_descriptions writes it)
    what Chief knows  plain sentences from the same scope Chief keeps to
                      (chief_areas): what it does for this login and what it
                      sends elsewhere

Who:
  read ...... the owner or an Admin, anyone's; whoever "sets up jobs and
              people's sheets" (church_job_defs.GRANT), a Manager login's or
              below; anyone, their own
  change .... the owner (anyone's but their own), an Admin or a holder (a
              Manager login's or below, never their own). A holder never
              switches on Giving & money or a money duty, never moves the
              lanes' oversight, and never gives or takes the grant; what a
              holder changes is told to the owner
  the grant . given and taken away by the owner or an Admin, to a Manager
              login, as a tick on the sheet's duties

  GET    /church/sheet?business_id=&user_id=
  PUT    /church/sheet        {business_id, user_id, job?, areas?, duties?: {add, remove}}
  GET    /church/sheet/jobs?business_id=      the jobs, always (see below)
  POST   /church/jobs         {business_id, label, does, description, role, areas, duties}
  PUT    /church/jobs/{key}   the same body (one of the church's own)
  DELETE /church/jobs/{key}?business_id=

GET /church/jobs is the job descriptions' roster (church_job_descriptions);
it carries `jobs` too, but only where that page opens, so /church/sheet/jobs
is the read that always answers. Widening a login (an area or a duty added, a
job given) asks for the password again, as an invite does; narrowing one
never does. Switched with Logins & areas (CHURCH_AREAS). A read that fails is
a 503, never an empty sheet.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

import church_areas
import church_duties as cd
import church_job_defs as cj
import church_over as co
import sb_clients
from auth_supabase import UserSession
from business_access import assert_access, business_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

LOW = ("manager", "member", "viewer")
NOT_CHURCH = "A person's sheet is for a church's office."
NOT_YOURS = ("A person's sheet is read by the owner, an Admin, or whoever sets up jobs and people's sheets. "
             "You can read your own.")
OWN_SHEET = "Nobody changes their own sheet. The owner or an Admin changes yours."
ADMINS_SHEET = "Only the owner changes an Admin's sheet."
OWNERS_SHEET = "The owner's sheet doesn't change: the owner sees and does everything."
NOT_AN_EDITOR = ("Only the owner, an Admin, or whoever sets up jobs and people's sheets changes a sheet. "
                 "Ask the owner to give you that.")
GIVING_LOCKED = "Giving & money opens only for an Admin login. Only the owner or an Admin can switch it on."
MONEY_DUTY = "A money job goes only to an Admin login. Only the owner or an Admin gives one."
GRANT_LOCKED = f"Only the owner or an Admin can give or take away “{cj.GRANT_LABEL}”."
OVERSIGHT_LOCKED = "Only the owner or an Admin moves the monthly report and Over the lanes."
ADMIN_JOB = "That job is an Admin login. Only the owner makes someone an Admin: invite them as an Admin."
KEEPS_ALL_WHY = "An Admin login sees the whole church and does every duty."
NO_OFFICE_JOBS = "A Member or Viewer login doesn't do office jobs. Make them a Manager login first."

# What Chief does for a login that works an area, and the same thing as what
# it sends elsewhere for a login that doesn't. Each names a verb placed in
# that area in chief_areas.VERBS (a test holds them together).
EXAMPLES: Tuple[Tuple[str, str, str], ...] = (
    ("worship_media", "publish_sermon", "Put Sunday's sermon up"),
    ("people_care", "create_contact", "Add a guest and follow up with them"),
    ("giving_money", "giving_statement", "Read what was given, or make a giving statement"),
    ("groups_classes", "create_course", "Start a class"),
    ("website_outreach", "edit_site_text", "Change the website"),
    ("office", "ask_into_role", "Ask someone into a role"),
)
EVERYONES = ("Add a task, a note or a meeting", "Draft an email or a text to someone")


def _q(v: Any) -> str:
    return church_areas._q(v)


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _join(words: List[str]) -> str:
    words = [w for w in words if w]
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _label(area: str) -> str:
    return church_areas.AREAS[area]["label"]


def _business(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The church couldn't be read just now. Try again.")
    if not rows:
        raise HTTPException(404, "business not found")
    import church_follow_up as cfu
    if not cfu.is_church(rows[0]):
        raise HTTPException(404, NOT_CHURCH)
    return rows[0]


# ─── Who may ──────────────────────────────────────────────────────────

def standing(ch: co.Church, viewer: str, target: str) -> Dict[str, Any]:
    """What `viewer` is to `target`'s sheet: {viewer_role, target_role,
    editor, is_self, can_read, can_edit, why_not}. 403 for someone with no
    login here; 404 for a sheet of someone who has none."""
    vrole, trole = ch.role(viewer), ch.role(target)
    if not vrole:
        raise HTTPException(403, NOT_YOURS)
    if not trole:
        raise HTTPException(404, "That login isn't on this church.")
    ed = cj.editor(ch.b, viewer, vrole)
    is_self = viewer == target
    can_read = is_self or ed in ("owner", "admin") or (ed == "holder" and trole in LOW)
    why = None
    if is_self:
        why = OWNERS_SHEET if vrole == "owner" else OWN_SHEET
    elif not ed:
        why = NOT_AN_EDITOR
    elif trole == "owner":
        why = OWNERS_SHEET
    elif trole == "admin" and ed != "owner":
        why = ADMINS_SHEET
    return {"viewer_role": vrole, "target_role": trole, "editor": ed, "is_self": is_self, "can_read": can_read,
            "can_edit": why is None, "why_not": why}


def locks(st: Dict[str, Any]) -> Dict[str, Any]:
    """What this editor may not toggle on this sheet: {locked_areas,
    locked_duties, locked_why, limits}. `limits` are the sentences a holder
    reads; the owner and the Admins read none."""
    trole, ed = st["target_role"], st["editor"]
    why: Dict[str, str] = {}
    money = [k for k, d in cd.CATALOG.items() if d["money"]]
    if not st["can_edit"]:
        said = st["why_not"] or NOT_AN_EDITOR
        why = {k: said for k in list(church_areas.AREA_ORDER) + list(cd.CATALOG) + [cj.GRANT]}
    elif trole in church_areas.KEEPS_ALL:
        why = {k: KEEPS_ALL_WHY for k in list(church_areas.AREA_ORDER) + list(cd.CATALOG) + [cj.GRANT]}
    else:
        why[church_areas.FINANCE_ONLY] = GIVING_LOCKED
        if trole != "manager":
            why.update({k: NO_OFFICE_JOBS for k in list(cd.CATALOG) + [cj.GRANT]})
        else:
            why.update({k: MONEY_DUTY for k in money})
            if ed == "holder":
                why.update({k: OVERSIGHT_LOCKED for k in cd.OVERSIGHT})
                why[cj.GRANT] = GRANT_LOCKED
    limits: List[str] = []
    if ed == "holder" and st["can_edit"]:
        limits = [GIVING_LOCKED, GRANT_LOCKED, OVERSIGHT_LOCKED,
                  "Only the owner makes someone an Admin or gives them an Admin job.",
                  "You can't change your own sheet, an Admin's or the owner's."]
    return {"locked_areas": [a for a in church_areas.AREA_ORDER if a in why],
            "locked_duties": [k for k in list(cd.CATALOG) + [cj.GRANT] if k in why],
            "locked_why": why, "limits": limits}


# ─── Reading one sheet ────────────────────────────────────────────────

def _person(ch: co.Church, st: Dict[str, Any], target: str) -> Dict[str, Any]:
    seat = ch.seats.get(target) or {}
    owner = target == ch.owner
    email = ""
    if owner:
        try:
            email = ch.owner_email
        except HTTPException:
            email = ""
    else:
        email = (seat.get("invited_email") or "").strip()
    return {"user_id": target, "name": ch.login_name(target), "email": email, "role": st["target_role"],
            "status": "active", "is_owner": owner, "is_self": st["is_self"]}


def _job(ch: co.Church, target: str, picked: Optional[List[str]]) -> Dict[str, Any]:
    seat = ch.seats.get(target) or {}
    key = seat.get("lane") or None
    if key:
        label = cj.label_of(ch.b, key)
        if label:
            return {"key": key, "label": label, "custom": key not in church_areas.LANES}
    key = church_areas.lane_of(seat.get("role"), picked)
    return {"key": key, "label": church_areas.LANES[key]["label"] if key else None, "custom": False}


def _areas(business: Dict[str, Any], ch: co.Church, target: str) -> Dict[str, Any]:
    if ch.role(target) in church_areas.KEEPS_ALL:
        return {"picked": None, "shown": None, "by": "all", "why": "Sees the whole church", "guess": []}
    seat = ch.seats.get(target) or {}
    raw = seat.get("areas")
    picked = [a for a in church_areas.AREA_ORDER if a in raw] if isinstance(raw, list) else None
    row = next((x for x in church_areas.build(business)["logins"] if x["user_id"] == target), None)
    if not row:
        raise HTTPException(503, "Their areas couldn't be read just now. Try again.")
    return {"picked": picked or None, "shown": row["areas"], "by": row["by"], "why": row["why"],
            "guess": row["guess"]}


def _duties(business: Dict[str, Any], ch: co.Church, target: str, names: bool = True) -> List[Dict[str, Any]]:
    """The whole catalog as this person's ticks, then the grant as one more.
    `names` false leaves out who else does each (a Member or Viewer login
    reading its own sheet: the duties page is a Manager's and up)."""
    page = cd.build(business)
    held = ch.held(target)
    out = []
    for d in page["duties"]:
        out.append({"key": d["key"], "label": d["label"], "area": d["area"], "held": d["key"] in held,
                    "others": [h["name"] for h in d["holders"]
                               if names and h["user_id"] != target and h.get("active")],
                    "money": bool(d["money"]), "follows_job": bool(d["follows_lanes"]), "does": d["does"]})
    holders = cj.grant_holders(ch.b)
    if holders is None:
        raise HTTPException(503, "Who sets up jobs couldn't be read just now. Try again.")
    trole = ch.role(target)
    managers = sorted(u for u in holders if ch.role(u) == "manager")
    out.append({"key": cj.GRANT, "label": cj.GRANT_LABEL, "area": "office",
                "held": trole in church_areas.KEEPS_ALL or target in managers,
                "others": [ch.login_name(u) for u in managers if names and u != target],
                "money": False, "follows_job": False, "does": cj.GRANT_DOES, "grant": True})
    return out


def _guarded(ch: co.Church, target: str, shown: Optional[List[str]]) -> List[Dict[str, Any]]:
    """What is guarded, whether this person holds it today, and why, in one
    sentence each. Read only: church_keys keeps the locks, and money opens to
    the owner, an Admin and the accountant (giving_records.require_finance)."""
    import church_keys
    trole = ch.role(target)
    first = ch.login_name(target).split(" ")[0] or "They"
    full = trole in church_areas.KEEPS_ALL
    try:
        rows = church_keys._keeper_rows(ch.b) if church_keys.mode() != "off" else []
    except HTTPException:
        rows = None

    def one(key: str, label: str, area: str, base: bool, open_to: str) -> Dict[str, Any]:
        if rows is None:
            return {"key": key, "label": label, "area": area, "holds": False,
                    "how": "Who keeps this couldn't be read just now."}
        keepers = church_keys.active_keepers(ch.b, area, rows) if area in church_keys.GUARDED else set()
        if keepers:
            names = _join(sorted(ch.login_name(u) for u in keepers))
            if target in keepers:
                return {"key": key, "label": label, "area": area, "holds": True,
                        "how": f"{first} keeps {_label(area)}, so it is open to them."}
            return {"key": key, "label": label, "area": area, "holds": False,
                    "how": f"{names} keeps {_label(area)}. {first} asks for a key, and a yes opens it for an hour."}
        return {"key": key, "label": label, "area": area, "holds": base,
                "how": f"Nobody keeps {_label(area)} yet, so it has no lock of its own: it is open to {open_to}."}

    def works(a: str) -> bool:
        return full or shown is None or a in shown

    money = "the owner, an Admin login and the church's accountant"
    return [
        one("who_gave", "Who gave, and how much", "giving_money", full, money),
        one("bank", "The bank and payouts", "giving_money", full, money),
        one("kids_medical", "Kids' medical and custody notes", "kids_youth", works("kids_youth"),
            "whoever can open Kids & youth"),
        one("pastors_notes", "Pastors-only notes and prayer", "people_care", works("people_care"),
            "whoever can open People & care"),
        {"key": "logins", "label": "Inviting and removing logins", "area": "office",
         "holds": trole in ("owner", "admin", "manager"),
         "how": ("A Manager login and up invites a login and removes one below its own level. Only the owner or "
                 "an Admin invites an Admin.")},
    ]


def _description(ch: co.Church, viewer: str, target: str) -> Dict[str, Any]:
    """Their written job description, where the viewer may read it. Read
    only here; a part that can't be read is left blank, never a failed sheet."""
    blank = {"title": None, "text": None, "written": False, "can_write": False}
    try:
        import church_job_descriptions as cjd
        if cjd.ready() is not True:
            return blank
        J = cjd.Jobs(ch)
        e = cjd.person(J, None, target)
        under = cjd.under_keys(ch, co.who(co.LOGIN, viewer))
        title, _written = cjd.title_of(ch, e)
        row = e["row"] if cjd.can_read(ch, viewer, e, under) else None
        return {"title": title or None, "text": (row or {}).get("description") or None, "written": bool(e["row"]),
                "can_write": cjd.can_write(ch, viewer, e, under)}
    except HTTPException:
        return blank
    except Exception:  # noqa: BLE001 — the sheet never fails for the description
        logger.warning("church sheet: a job description wasn't read (business %s)", ch.b[:8], exc_info=True)
        return blank


def chief_words(ch: co.Church, target: str, shown: Optional[List[str]], job: Dict[str, Any],
                duties: List[Dict[str, Any]], guarded: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """What Chief knows about this login, in plain sentences, from the same
    scope Chief keeps to (chief_areas.refusal reads a login's areas): what it
    does for them and what it sends to someone else."""
    import chief_areas
    name = ch.login_name(target)
    first = name.split(" ")[0] or name
    trole = ch.role(target)
    full = trole in church_areas.KEEPS_ALL or shown is None or chief_areas.mode() == "off"
    areas = list(church_areas.AREA_ORDER) if full else list(shown or [])
    summary: List[str] = []
    if trole == "owner":
        summary.append(f"{name} is the owner. Chief does everything for the owner.")
    elif trole == "admin":
        summary.append(f"{name} has an Admin login. Chief works across the whole church for them, money too.")
    elif full:
        summary.append(f"Nothing places {name} yet, so Chief keeps to no area for them. Give them their areas.")
    elif areas:
        summary.append(f"{name} works in {_join([_label(a) for a in areas])}.")
    else:
        summary.append(f"{name} has no area switched on. Chief helps with their own tasks, notes and meetings.")
    if job.get("label"):
        summary.append(f"Their job is {job['label']}.")
    mine = [d["label"] for d in duties if d["held"] and not d.get("grant")]
    if trole not in church_areas.KEEPS_ALL and mine:
        shown_d = mine[:4]
        more = len(mine) - len(shown_d)
        summary.append(f"{first} does {_join(shown_d)}" + (f" and {more} more duties." if more > 0 else "."))
    if trole not in church_areas.KEEPS_ALL and any(d.get("grant") and d["held"] for d in duties):
        summary.append(f"{first} sets up the church's jobs and people's sheets: never an Admin job, Giving & "
                       "money or their own sheet.")
    held = [g["label"] for g in guarded if g["holds"] and g["key"] != "logins"]
    summary.append(f"Guarded things open to {first}: {_join(held).lower()}." if held
                   else f"Nothing guarded is open to {first}.")
    money_ok = trole in church_areas.KEEPS_ALL
    will = list(EVERYONES)
    wont: List[str] = []
    for area, verb, words in EXAMPLES:
        needs = chief_areas.VERBS.get(verb) or ()
        ok = money_ok if area == "giving_money" else (full or any(a in areas for a in needs))
        if ok:
            will.append(words)
        elif area == "giving_money":
            wont.append(f"{words}: Giving & money opens only to the owner, an Admin and the accountant.")
        else:
            wont.append(f"{words}: that is {_label(area)}. Chief says who has it.")
    return {"summary": summary, "will": will, "wont": wont}


def compose(business: Dict[str, Any], viewer: str, target: str) -> Dict[str, Any]:
    """One person's sheet for one viewer. 403 when it isn't theirs to read."""
    import church_map
    ch = co.Church(business)
    st = standing(ch, viewer, target)
    if not st["can_read"]:
        raise HTTPException(403, NOT_YOURS)
    with church_map.once():
        areas = _areas(business, ch, target)
        duties = _duties(business, ch, target, names=st["viewer_role"] in ("owner", "admin", "manager"))
        job = _job(ch, target, areas["picked"])
        guarded = _guarded(ch, target, areas["shown"])
        return {
            "ok": True, "can_edit": st["can_edit"], "editor": st["editor"],
            "person": _person(ch, st, target), "job": job, "areas": areas, "duties": duties, "guarded": guarded,
            "description": _description(ch, viewer, target),
            "chief": chief_words(ch, target, areas["shown"], job, duties, guarded),
            "jobs": cj.jobs(ch.b), **locks(st),
        }


# ─── Changing one sheet ───────────────────────────────────────────────

def _duty_plan(ch: co.Church, business: Dict[str, Any], target: str, add: List[str], remove: List[str]
               ) -> List[Tuple[str, List[str]]]:
    """Who does each changed duty afterwards, as church_duties.move takes it:
    everyone who does it now, with this person added or taken out. A duty
    this person does by their job alone can't be taken from them here (naming
    nobody hands it back to the job): the Duties tab names who does it."""
    page = {d["key"]: d for d in cd.build(business)["duties"]}
    plan: List[Tuple[str, List[str]]] = []
    for key in add:
        d = page[key]
        now = [h["user_id"] for h in d["holders"] if h.get("active")]
        if target not in now:
            plan.append((key, sorted(set(now) | {target})))
    for key in remove:
        d = page[key]
        now = [h["user_id"] for h in d["holders"] if h.get("active")]
        if target not in now:
            continue
        rest = sorted(set(now) - {target})
        if not rest:
            raise HTTPException(400, f"{ch.login_name(target)} is the only one who does “{d['label']}”. Say who "
                                     "does it instead on the Duties tab, then take it off this sheet.")
        plan.append((key, rest))
    return plan


def change(business: Dict[str, Any], viewer: str, target: str, body: Dict[str, Any], *,
           widening=None) -> Dict[str, Any]:
    """Change a person's sheet: its job, its areas, its duties, each through
    the write it already had. Everything is checked before anything is
    written. Returns {widens, summary, changed}. `widening` is called once,
    before any write, when the change gives the login more (the route's
    password check, which raises); nothing is asked for a change that only
    takes away."""
    ch = co.Church(business)
    st = standing(ch, viewer, target)
    if not st["can_edit"]:
        raise HTTPException(403, st["why_not"] or NOT_AN_EDITOR)
    lk = locks(st)
    trole, ed = st["target_role"], st["editor"]
    seat = ch.seats.get(target) or {}
    name = ch.login_name(target)
    said: List[str] = []
    widens = False

    # The job.
    job_set = "job" in body
    job_key = None
    if job_set and body.get("job") is not None:
        job = cj.find(ch.b, body.get("job"))
        if not job:
            raise HTTPException(400, "That isn't one of this church's jobs.")
        if job["role"] == "admin" and trole != "admin":
            raise HTTPException(403 if ed == "holder" else 400, ADMIN_JOB)
        job_key = job["key"]
        if job_key != (seat.get("lane") or None):
            said.append(f"job: {job['label']}")
            widens = True
    elif job_set and seat.get("lane"):
        said.append("no job")

    # The areas.
    areas_set = "areas" in body
    areas = None
    if areas_set:
        if trole in church_areas.KEEPS_ALL:
            raise HTTPException(400, KEEPS_ALL_WHY)
        raw = body.get("areas")
        if isinstance(raw, list) and church_areas.FINANCE_ONLY in raw:
            raise HTTPException(403 if ed == "holder" else 400, GIVING_LOCKED)
        areas = church_areas.clean_login_areas(raw)
        had = [a for a in church_areas.AREA_ORDER if a in (seat.get("areas") or [])]
        new = areas or []
        plus, minus = [a for a in new if a not in had], [a for a in had if a not in new]
        if plus:
            said.append("added " + _join([_label(a) for a in plus]))
            widens = True
        if minus:
            said.append("took off " + _join([_label(a) for a in minus]))
        if areas is None and isinstance(seat.get("areas"), list):
            said.append("areas back to Chief's guess")

    # The duties, and the grant among them.
    duties = body.get("duties") if isinstance(body.get("duties"), dict) else {}
    add = [str(k) for k in (duties.get("add") or [])]
    remove = [str(k) for k in (duties.get("remove") or [])]
    known = set(cd.CATALOG) | {cj.GRANT}
    if any(k not in known for k in add + remove) or set(add) & set(remove):
        raise HTTPException(400, "One of those isn't a duty here.")
    grant = True if cj.GRANT in add else False if cj.GRANT in remove else None
    add, remove = [k for k in add if k != cj.GRANT], [k for k in remove if k != cj.GRANT]
    for k in add + remove + ([cj.GRANT] if grant is not None else []):
        if k in lk["locked_duties"]:
            raise HTTPException(403 if ed == "holder" else 400, lk["locked_why"][k])
    plan = _duty_plan(ch, business, target, add, remove) if add or remove else []
    for key, to in plan:
        why = cd._check(ch.b, business, to, key)
        if why:
            raise HTTPException(400, why)
        gave = target in to
        said.append(("gave" if gave else "took away") + f" “{cd.CATALOG[key]['label']}”")
        widens = widens or gave
    if grant is not None:
        if ed not in ("owner", "admin"):
            raise HTTPException(403, GRANT_LOCKED)
        if trole != "manager":
            raise HTTPException(400, "Give that to a Manager login. An Admin sets up jobs and sheets already, and "
                                     "a Member or Viewer login doesn't.")
        widens = widens or grant

    if widens and widening is not None:
        widening()

    # Everything checked: write each part through its own write.
    if job_set or areas_set:
        church_areas.set_login(ch.b, target, trole,
                               areas=areas if areas_set else church_areas.KEEP,
                               job=job_key if job_set else church_areas.KEEP)
    for key, to in plan:
        cd.move(business, key, to, viewer)
    if grant is not None and cj.set_grant(business, target, grant, viewer):
        said.append(("gave" if grant else "took away") + f" “{cj.GRANT_LABEL}”")
    try:
        import chief_areas
        chief_areas.forget(ch.b)
    except Exception:  # noqa: BLE001 — Chief reads the new sheet within the minute either way
        pass
    summary = f"changed {name}'s sheet: " + "; ".join(said) if said else ""
    if said:
        cj.changed(business, "sheet", viewer, ed or "", ch.login_name(viewer), summary, subject=target,
                   detail={"job": body.get("job") if job_set else None, "areas": areas if areas_set else None,
                           "duties": {"add": add, "remove": remove}, "grant": grant})
    return {"widens": widens, "summary": summary, "changed": bool(said)}


# ─── The jobs, for the people who set them up ─────────────────────────

def jobs_view(business: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """The jobs and what this login may do with them: {jobs, can_manage,
    can_make_admin_job}."""
    ch = co.Church(business)
    ed = cj.editor(ch.b, user_id, ch.role(user_id))
    return {"jobs": cj.jobs(ch.b), "can_manage": ed is not None, "can_make_admin_job": ed == "owner"}


def _jobs_editor(body_biz: Any, user: Any) -> Tuple[Dict[str, Any], str, str]:
    """(the church, the editor's kind, their name) for a write to the jobs;
    403 for a login that sets none up."""
    church_areas._gate(user)
    biz = _uuid(body_biz, "church")
    assert_access(biz, user, "member")
    business = _business(biz)
    ch = co.Church(business)
    ed = cj.editor(biz, str(user.id), ch.role(str(user.id)))
    if not ed:
        raise HTTPException(403, "Only the owner, an Admin, or whoever sets up jobs and people's sheets makes or "
                                 "changes a job. Ask the owner to give you that.")
    return business, ed, ch.login_name(str(user.id))


def save_job(business: Dict[str, Any], ed: str, by: str, by_name: str, body: Dict[str, Any],
             key: Optional[str] = None) -> Dict[str, Any]:
    """Make one of the church's own jobs, or change one (with `key`):
    the routes' and Chief's one path. Recorded; told to the owner when a
    holder did it."""
    got = cj.update(business, key, body, by, ed) if key else cj.create(business, body, by, ed)
    cj.changed(business, "job", by, ed, by_name, cj.summary_of("update" if key else "create", got["job"]),
               job_key=got["job"]["key"], detail={"before": got.get("before"), "after": got["job"]})
    return got


def remove_job(business: Dict[str, Any], ed: str, by: str, by_name: str, key: str) -> Dict[str, Any]:
    got = cj.remove(business, key, by, ed)
    cj.changed(business, "job", by, ed, by_name, cj.summary_of("remove", got["job"]), job_key=got["job"]["key"],
               detail={"before": got["job"], "after": None})
    return got


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/sheet")
def get_sheet(business_id: str, user_id: str, session: UserSession = Depends(sb_clients.authed_request),
              biz: Dict[str, Any] = Depends(business_access("viewer"))):
    """One person's sheet. The owner or an Admin reads anyone's; whoever sets
    up jobs and sheets, a Manager login's or below; anyone, their own."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    return compose(biz, str(session.user.id), _uuid(user_id, "login"))


@router.put("/sheet")
def put_sheet(body: Dict[str, Any], request: Request, session: UserSession = Depends(sb_clients.authed_request)):
    """Change a person's sheet, then answer with it as it is now. Giving
    someone more (an area, a duty, a job) asks for the password again, as an
    invite does; taking something away never does."""
    user = session.user
    church_areas._gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"), "church")
    target = _uuid(body.get("user_id"), "login")
    assert_access(biz, user, "member")
    business = _business(biz)
    import ledger_unlock
    got = change(business, str(user.id), target, body, widening=lambda: ledger_unlock.require_unlock(
        request, str(user.id), ledger_unlock.SCOPE_ACCESS))
    return {**compose(business, str(user.id), target), "changed": got["changed"], "summary": got["summary"]}


@router.get("/sheet/jobs")
def list_jobs(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
              biz: Dict[str, Any] = Depends(business_access("manager"))):
    """The starting jobs and the church's own, and whether this login may
    set them up. A Manager seat and up."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    return jobs_view(biz, str(session.user.id))


@router.post("/jobs")
def post_job(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """A new job of the church's own."""
    body = body or {}
    business, ed, name = _jobs_editor(body.get("business_id"), session.user)
    return {"ok": True, "job": save_job(business, ed, str(session.user.id), name, body)["job"]}


@router.put("/jobs/{key}")
def put_job(key: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Change one of the church's own jobs. Nobody who holds it changes."""
    body = body or {}
    business, ed, name = _jobs_editor(body.get("business_id"), session.user)
    return {"ok": True, "job": save_job(business, ed, str(session.user.id), name, body, key)["job"]}


@router.delete("/jobs/{key}")
def delete_job(key: str, business_id: str, session: UserSession = Depends(sb_clients.authed_request)):
    """Take one of the church's own jobs off the list. Whoever holds it keeps
    their areas and duties, and their job still reads as its title."""
    business, ed, name = _jobs_editor(business_id, session.user)
    remove_job(business, ed, str(session.user.id), name, key)
    return {"ok": True}
