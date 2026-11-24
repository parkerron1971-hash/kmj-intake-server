"""chief_church_sheet.py — Chief reads a person's sheet, knows the church's jobs,
and helps set up a job that isn't one of the ready-made ones.

Kevin, 2026-11-17, on "One sheet per person" (artifact WE3jy89EXadQSjz9t8A2FV):
"allow for chief to assist and help create description roles and
responsibility for ones that are not preset in the system", then "also allow
for permission to be given to a person to create roles like how my wife over
administration team".

    sheet_of ............ {who}: what one login can open and do, as its
                          sheet says it (church_sheet.compose): its job, its
                          areas, its duties, what is guarded, and what the
                          asker may change on it. The owner or an Admin,
                          anyone's; whoever sets up jobs and sheets, a
                          Manager login's or below; anyone, their own
    list_church_jobs .... the five starting jobs and the church's own (a
                          Manager seat and up)
    draft_church_job .... the building blocks for a new job: the eight
                          areas and what each holds, every duty with its
                          key, the login levels and the jobs there are.
                          Saves nothing. For whoever sets jobs up
    save_church_job ..... {label, does, description, role, areas, duties,
                          job?}: make one of the church's own jobs, or with
                          `job` (its key or title) change one
    remove_church_job ... {job}: take one off the list

Who writes: the owner, an Admin, or whoever the owner gave "Sets up jobs and
people's sheets" (church_job_defs.GRANT); the handlers ask
church_job_defs.editor, the routes' own check, so no lane widens it and an
Admin job stays the owner's. Chief has no verb that changes a person's sheet:
it says what it would set and opens the sheet (navigate operate/areas with
`sheet`: the login's id) for the person to save, with their password.

The chief_church_jobs pattern: someone signed in, never unattended, a church,
Logins & areas on. A write on a turn whose context held instruction-shaped
text from something Chief read (chief_of_staff.untrusted_taint: an uploaded
handbook, a pasted page) is held: it runs only when the person says it again.
Action tags for the writes, never native write tools; the reads are mid-turn
reads on the tool loop's 12,000-character list.
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import church_areas
import church_duties as cd
import church_job_defs as cj
import church_over as co
import church_sheet as cs

NAV = {"tab": "operate", "sub": "areas"}
NOT_ON = "Logins & areas isn't switched on here yet, so Chief can't read sheets or set up jobs."
WRITES = frozenset({"save_church_job", "remove_church_job"})
ME_WORDS = frozenset({"me", "myself", "i", "mine", "my own", "my sheet", "my"})
LEVELS = {"viewer": "Viewer: looks, changes nothing", "member": "Member: works its own records",
          "manager": "Manager: an office login that does duties and works its areas",
          "admin": "Admin: sees the whole church, money too (only the owner makes an Admin job)"}

TOOLS = [
    {"name": "sheet_of",
     "description": ("A church login's sheet: what one person can open and do. Their login level, their job, the "
                     "areas they work, the duties they do, what is guarded and whether it is open to them, and what "
                     "the signed-in person may change on it. \"What can Tasha open?\", \"can Jordan see giving?\", "
                     "\"what can I do here?\" (who: me). The owner or an Admin reads anyone's; whoever sets up jobs "
                     "and people's sheets, a Manager login's or below; anyone, their own."),
     "input_schema": {"type": "object", "properties": {"who": {"type": "string", "description": "A name, or me"}},
                      "required": ["who"]}},
    {"name": "list_money_asks",
     "description": ("The requests for giving access waiting for the church's owner: who asked, for whom, and for "
                     "what (See, Work or Lead, who gave, the bank and payouts). The owner reads all of them; "
                     "anyone else, the ones they sent. Read only: you never give giving access, ask for it or "
                     "answer a request. The owner answers on Logins & areas, with the password."),
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_church_jobs",
     "description": ("A church's jobs: the five starting ones and the ones the church made, each with its login "
                     "level, what it does, its areas and its duties. A job is a starting point for a person's "
                     "sheet. Read it before saying which job fits someone, and before save_church_job."),
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "draft_church_job",
     "description": ("The building blocks for a job that isn't one of the ready-made ones: the church's eight areas "
                     "and what each holds, every duty with its key, the login levels, and the jobs there already "
                     "are. Saves nothing. Read it, ask what the person does, who they answer to and what they "
                     "should be able to open, then write the job in the church's own words and read it back before "
                     "save_church_job. For the owner, an Admin, or whoever sets up jobs and people's sheets."),
     "input_schema": {"type": "object", "properties": {}}},
]


# ─── Small things ─────────────────────────────────────────────────────

def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _fold(v: Any) -> str:
    return _plain(v).casefold().replace("’", "'")


def _fail(atype: str, msg: str, **more: Any) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV, **more}


def _join(words: List[str]) -> str:
    return cs._join(words)


def _own(text: Any) -> str:
    """The asker's own words back to them: tags out, as written."""
    import untrusted_text
    return untrusted_text.defuse(_plain(text))


def _turn_user() -> str:
    from chief_duties import _turn_user as tu
    return tu()


def _on(uid: str) -> Optional[bool]:
    """Whether Logins & areas is on for this person (church_areas.open_to).
    None when owner mode can't read who they are."""
    m = church_areas.mode()
    if m == "on":
        return True
    if m != "owner" or not uid:
        return False
    from chief_duties import _EMAILS
    if uid not in _EMAILS:
        try:
            import platform_suite
            _EMAILS[uid] = platform_suite._owner_email(uid) or ""
        except Exception:  # noqa: BLE001 — unread is not a yes
            return None
    return church_areas.open_to(SimpleNamespace(email=_EMAILS[uid]))


# ─── The gate ─────────────────────────────────────────────────────────

def _open(atype: str, biz: Any, action: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], str]:
    """(a refusal or None, the church's row, me). Signed in, not unattended,
    a church, Logins & areas on, a login here; a write on a tainted turn is
    held. A read that fails raises 503."""
    if action.get("_unattended"):
        return _fail(atype, "sheets and jobs are read and set up only when someone at the church asks."), {}, ""
    uid = _turn_user()
    if not uid:
        return _fail(atype, "sheets and jobs are for someone signed in to the church's office."), {}, ""
    if atype in WRITES:
        try:
            from chief_of_staff import untrusted_taint
            tainted = bool(untrusted_taint())
        except Exception:  # noqa: BLE001 — unread is not a yes
            tainted = True
        # A marked turn's write waits for the person's go-ahead, which runs exactly what they were shown
        # (chief_said_again): the job's level, its areas and its duties are each on their own line.
        import chief_said_again
        held = chief_said_again.gate(str((biz or {}).get("id") or ""), uid, atype, action, tainted=tainted, nav=NAV,
                                     heading={"save_church_job": "Save one of the church's own jobs",
                                              "remove_church_job": "Take one of the church's own jobs off the list"}[atype],
                                     # `job` is the one a change or a removal is of (never `key`, which the
                                     # handlers don't read); a save with no `job` makes a new one. What a save
                                     # leaves out is set, not kept: church_job_defs.clean.
                                     keys={"save_church_job": ("job", "label", "does", "description", "role", "areas",
                                                               "duties"),
                                           "remove_church_job": ("job",)}[atype],
                                     defaults={"save_church_job": {
                                         "job": "a new job (none is being changed)", "does": "nothing said (left empty)",
                                         "description": "none (left empty)", "role": "manager (a Manager login)",
                                         "areas": "none set on the job", "duties": "none"}}.get(atype))
        if held:
            return held, {}, ""
    on = _on(uid)
    if on is None:
        return _fail(atype, "whether Logins & areas is on couldn't be checked just now. Try again."), {}, ""
    if not on:
        return _fail(atype, NOT_ON), {}, ""
    try:
        business = cs._business(str((biz or {}).get("id") or ""))
    except HTTPException as e:
        if e.status_code == 404:
            return _fail(atype, "sheets and jobs are for a church's office."), {}, ""
        raise
    if not co.Church(business).role(uid):
        return _fail(atype, "sheets and jobs are for the church's own logins."), {}, ""
    return None, business, uid


def _run(atype: str, biz: Any, action: Any, body) -> Dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    try:
        refused, business, uid = _open(atype, biz, action)
        if refused:
            return refused
        import church_map
        with church_map.once():
            out = body(business, uid, action)
        return {"type": atype, "nav": NAV, **out}
    except HTTPException as e:
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        said = _plain(detail)
        return _fail(atype, f"{said.rstrip('.')}. Nothing changed." if atype in WRITES else said)


# ─── Naming a login, and a job ────────────────────────────────────────

def _pick_login(ch: co.Church, uid: str, raw: Any) -> str:
    """The login `raw` names, among the ones this person may read: "me"; a
    whole name; or one name word only one of them has (never the start of
    one). None or several: a 400 that says who it could be."""
    if not _plain(raw):
        raise HTTPException(400, "Whose sheet? Say their name, or me.")
    if _fold(raw) in ME_WORDS:
        return uid
    ed = cj.editor(ch.b, uid, ch.role(uid))
    everyone = ([ch.owner] if ch.owner else []) + sorted(ch.seats)
    if ed in ("owner", "admin"):
        mine = everyone
    elif ed == "holder":
        mine = [u for u in everyone if u == uid or ch.role(u) in cs.LOW]
    else:
        mine = [uid]
    names = {u: ch.login_name(u) for u in mine}
    said = _fold(raw)
    hits = [u for u, n in names.items() if _fold(n) == said]
    if not hits:
        words = set(re.findall(r"[\w']+", said))
        hits = [u for u, n in names.items() if words and words <= set(re.findall(r"[\w']+", _fold(n)))]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise HTTPException(400, f"“{_plain(raw)}” could be {_join(sorted(names[u] for u in hits)[:12])}: say which.")
    if mine == [uid]:
        raise HTTPException(403, cs.NOT_YOURS)
    raise HTTPException(400, f"“{_plain(raw)}” isn't a login whose sheet you can read here. They are: "
                             f"{_join(sorted(names.values())[:20])}.")


def _pick_job(business_id: str, raw: Any) -> Dict[str, Any]:
    """A job by its key or its title; a 400 that lists them otherwise."""
    said = _fold(raw)
    jobs = cj.jobs(business_id)
    hits = [j for j in jobs if said and (j["key"] == said or _fold(j["label"]) == said)]
    if len(hits) == 1:
        return hits[0]
    raise HTTPException(400, f"“{_plain(raw)}” isn't one of this church's jobs. They are: "
                             f"{_join([j['label'] for j in jobs])}.")


def _job_line(j: Dict[str, Any]) -> str:
    areas = "the whole church" if j["areas"] is None else (
        _join([church_areas.AREAS[a]["label"] for a in j["areas"]]) or "no area set")
    duties = _join([cd.CATALOG[k]["label"] for k in j["duties"]][:6])
    more = len(j["duties"]) - 6
    return (f"{j['label']} ({'the church made it' if j['custom'] else 'a starting job'}; {j['role'].title()} "
            f"login; key {j['key']}): {j['does'] or 'no line yet'}. Works in {areas}."
            + (f" Duties: {duties}{f' and {more} more' if more > 0 else ''}." if duties else " No duties set."))


# ─── The reads ────────────────────────────────────────────────────────

def _sheet(business: Dict[str, Any], uid: str, action: Dict[str, Any]) -> Dict[str, Any]:
    ch = co.Church(business)
    target = _pick_login(ch, uid, action.get("who"))
    s = cs.compose(business, uid, target)
    p = s["person"]
    me = p["is_self"]
    who = "You" if me else p["name"]
    lines = [f"{p['name']}'s sheet" + (" (yours)" if me else "") + f": {p['role'].title()} login."]
    if s["job"]["label"]:
        lines.append(f"Job: {s['job']['label']}" + (" (one the church made)." if s["job"]["custom"] else "."))
    a = s["areas"]
    if a["shown"] is None:
        lines.append("Areas: the whole church." if a["by"] == "all" else
                     "Areas: nothing places them yet, so their menu shows the whole church. Give them their areas.")
    else:
        lines.append(f"Areas: {_join([church_areas.AREAS[x]['label'] for x in a['shown']])} ({a['why']}).")
    held = [d["label"] for d in s["duties"] if d["held"] and not d.get("grant")]
    if p["role"] in church_areas.KEEPS_ALL:
        lines.append("Duties: every duty, money ones too.")
    elif held:
        lines.append(f"Duties ({len(held)}): {_join(held)}.")
    else:
        lines.append("Duties: none.")
    if p["role"] not in church_areas.KEEPS_ALL and any(d.get("grant") and d["held"] for d in s["duties"]):
        lines.append(f"{who} set{'' if me else 's'} up the church's jobs and people's sheets (given by the owner or "
                     "an Admin): never an Admin job, Giving & money, or their own sheet.")
    for g in s["guarded"]:
        lines.append(f"{g['label']}: {'open to them' if g['holds'] else 'not open to them'}. {g['how']}")
    # Giving as its own tick (church_money_ticks): there only while it is
    # switched on for this church. Chief reads it; only the owner gives it.
    m = s.get("money")
    if m:
        waiting = ""
        if m.get("pending"):
            waiting = (f" A request is waiting for the owner: {m['pending']['wants_words']}, asked by "
                       f"{m['pending']['asked_by_name'] or 'someone in the office'}.")
        lines.append(f"Giving: {m['words']}.{waiting} Only the owner gives giving access, on the person's sheet, "
                     "with the password. You never give it, ask for it or answer a request.")
    d = s["description"]
    if d["written"]:
        lines.append("A job description is written for them (job_of reads it).")
    if s["can_edit"]:
        lines.append("You may change this sheet. You don't change it from here: say what you would set, then open "
                     f"it for them to save with their password (navigate tab operate, sub areas, sheet {target}).")
        lines += [f"Limit: {x}" for x in s["limits"]]
    elif not me:
        lines.append("You can read this sheet but not change it.")
    else:
        lines.append("Nobody changes their own sheet: the owner or an Admin changes yours.")
    return {"result": "\n".join(lines), "label": f"{p['name']}'s sheet"[:80], "who": p["name"],
            "nav": {**NAV, "sheet": target}}


def _money_asks(business: Dict[str, Any], uid: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """The requests for giving access waiting at this church, as words.
    Reading only: nothing here gives, asks or answers."""
    import church_money_ticks as cmt
    if not cmt.open_for(business.get("id")):
        return {"result": "Giving as its own switch on a person's sheet isn't on for this church yet. Giving opens "
                          "for the owner and Admin logins.", "label": "Not switched on"}
    ch = co.Church(business)
    if not ch.role(uid):
        raise HTTPException(403, "That is read by the church's own logins.")
    asks = cmt.open_asks(business, uid)
    if asks is None:
        raise HTTPException(503, "The requests couldn't be read just now.")
    owner = str(business.get("owner_id") or "") == uid
    if not asks:
        return {"result": ("No request for giving access is waiting." if owner
                           else "You have no request for giving access waiting for the owner."),
                "label": "No requests waiting"}
    lines = [f"{len(asks)} request{'' if len(asks) == 1 else 's'} for giving access "
             f"{'is' if len(asks) == 1 else 'are'} waiting for the owner:"]
    for a in asks:
        lines.append(f"- {a['name']}: {a['wants_words']}, asked by {a['asked_by_name'] or 'someone in the office'} "
                     f"on {str(a.get('asked_at') or '')[:10]}; it runs out {str(a.get('expires_at') or '')[:10]}.")
    lines.append("Nothing is open until the owner says yes. The owner answers on Logins & areas, with the "
                 "password. You never answer one." if owner else
                 "Nothing is open until the owner says yes. You can take a request back on the person's sheet.")
    return {"result": "\n".join(lines), "label": f"{len(asks)} waiting",
            "nav": {"tab": "operate", "sub": "areas"}}


def _jobs(business: Dict[str, Any], uid: str, action: Dict[str, Any]) -> Dict[str, Any]:
    ch = co.Church(business)
    if ch.role(uid) not in ("owner", "admin", "manager"):
        raise HTTPException(403, "The church's jobs are read by its office seats: a Manager and up.")
    jobs = cj.jobs(ch.b)
    view = cs.jobs_view(business, uid)
    lines = [f"{business.get('name') or 'This church'} has {len(jobs)} jobs:"] + ["- " + _job_line(j) for j in jobs]
    lines.append("A job is a starting point for a person's sheet: changing one never changes anyone who holds it.")
    lines.append("You may make, change and remove the church's own jobs"
                 + ("." if view["can_make_admin_job"] else ", except an Admin job: that is the owner's.")
                 if view["can_manage"] else
                 "Only the owner, an Admin, or whoever sets up jobs and people's sheets makes or changes a job.")
    return {"result": "\n".join(lines), "label": f"{len(jobs)} jobs"}


def _blocks(business: Dict[str, Any], uid: str, action: Dict[str, Any]) -> Dict[str, Any]:
    ch = co.Church(business)
    ed = cj.editor(ch.b, uid, ch.role(uid))
    if not ed:
        raise HTTPException(403, "Only the owner, an Admin, or whoever sets up jobs and people's sheets makes a job. "
                                 "The owner can give you that on your sheet.")
    lines = ["The pieces of a job. Ask what the person does, who they answer to and what they should be able to "
             "open; then write it in the church's own words and read it back before saving.",
             "AREAS (key: what it holds):"]
    for k in church_areas.AREA_ORDER:
        a = church_areas.AREAS[k]
        lines.append(f"- {k}: {a['label']}: {_join(a['holds'])}."
                     + (" Only with an Admin job." if k == church_areas.FINANCE_ONLY else ""))
    lines.append("DUTIES (key: the duty, its area):")
    for k, d in cd.CATALOG.items():
        if d["money"] and ed != "owner":
            continue                    # a money duty goes only in an Admin job, which is the owner's to make
        if k in cd.OVERSIGHT and ed == "holder":
            continue
        lines.append(f"- {k}: {d['label']} ({church_areas.AREAS[d['area']]['label']})"
                     + (", money: only in an Admin job" if d["money"] else ""))
    lines.append("LOGIN LEVELS: " + "; ".join(LEVELS[r] for r in (
        ("viewer", "member", "manager", "admin") if ed == "owner" else ("viewer", "member", "manager"))) + ".")
    lines.append("THE JOBS THERE ARE: " + "; ".join(f"{j['label']} ({j['key']})" for j in cj.jobs(ch.b)) + ".")
    lines.append("RULES: a title of 60 letters at most; one line of what it does; a description of the "
                 "responsibilities; a Member or Viewer job has no duties; pay never goes in a job; a job is a "
                 "starting point and never changes anyone who already holds it."
                 + ("" if ed == "owner" else " An Admin job is the owner's alone to make."))
    return {"result": "\n".join(lines), "label": "The pieces of a job"}


# ─── The writes ───────────────────────────────────────────────────────

def _editor(business: Dict[str, Any], uid: str) -> Tuple[co.Church, str]:
    ch = co.Church(business)
    ed = cj.editor(ch.b, uid, ch.role(uid))
    if not ed:
        raise HTTPException(403, "Only the owner, an Admin, or whoever sets up jobs and people's sheets makes or "
                                 "changes a job. The owner can give you that on your sheet")
    return ch, ed


def _save(business: Dict[str, Any], uid: str, action: Dict[str, Any]) -> Dict[str, Any]:
    ch, ed = _editor(business, uid)
    key = None
    if _plain(action.get("job")):
        job = _pick_job(ch.b, action.get("job"))
        if not job["custom"]:
            raise HTTPException(400, cj.PRESET)
        key = job["key"]
    body = {k: action.get(k) for k in ("label", "does", "description", "role", "areas", "duties")}
    if key and not _plain(body.get("label")):
        body["label"] = job["label"]                 # a change that doesn't rename it
    got = cs.save_job(business, ed, uid, ch.login_name(uid), body, key)
    j = got["job"]
    said = (f"{'Changed' if key else 'Saved'} the job “{_own(j['label'])}”: {_job_line(j)}"
            + (f" Its description: “{_own(j['description'][:600])}”" if j["description"] else ""))
    said += (" Nobody who already holds it changed." if key else
             " It is on the list for a person's sheet and for an invite. To give it to someone, open their sheet "
             "and they save it with their password.")
    return {"result": said, "label": f"{'Changed' if key else 'Saved'} the job {j['label']}"[:80], "job": j["key"],
            "created": bool(got.get("created")), "changed": True}


def _remove(business: Dict[str, Any], uid: str, action: Dict[str, Any]) -> Dict[str, Any]:
    ch, ed = _editor(business, uid)
    if not _plain(action.get("job")):
        raise HTTPException(400, "Which job? Say its title.")
    job = _pick_job(ch.b, action.get("job"))
    if not job["custom"]:
        raise HTTPException(400, cj.PRESET)
    cs.remove_job(business, ed, uid, ch.login_name(uid), job["key"])
    return {"result": (f"Took the job “{_own(job['label'])}” off the list. Anyone who holds it keeps their areas and "
                       "duties, and their job still reads as it. Saying it again by its title makes a new one."),
            "label": f"Removed the job {job['label']}"[:80], "job": job["key"], "changed": True}


# ─── The handlers ─────────────────────────────────────────────────────

def _handler(atype: str, body):
    async def handle(client, biz, action) -> Dict[str, Any]:
        return await asyncio.to_thread(_run, atype, biz, action or {}, body)
    handle.__name__ = f"handle_{atype}"
    handle.__qualname__ = handle.__name__
    return handle


handle_sheet_of = _handler("sheet_of", _sheet)
handle_list_church_jobs = _handler("list_church_jobs", _jobs)
handle_list_money_asks = _handler("list_money_asks", _money_asks)
handle_draft_church_job = _handler("draft_church_job", _blocks)
handle_save_church_job = _handler("save_church_job", _save)
handle_remove_church_job = _handler("remove_church_job", _remove)

HANDLERS = {
    "sheet_of": handle_sheet_of, "list_church_jobs": handle_list_church_jobs,
    "list_money_asks": handle_list_money_asks,
    "draft_church_job": handle_draft_church_job, "save_church_job": handle_save_church_job,
    "remove_church_job": handle_remove_church_job,
}
PROGRESS = {
    "sheet_of": "reading their sheet", "list_church_jobs": "looking at the church's jobs",
    "list_money_asks": "looking at the requests for giving access",
    "draft_church_job": "getting the pieces of a job", "save_church_job": "saving the job",
    "remove_church_job": "removing the job",
}


def grant_line(business_id: Any, user_id: Any) -> Optional[str]:
    """One line for a login's own prompt block when the owner or an Admin
    gave it the grant (chief_areas._jobs); None otherwise, and when it
    couldn't be read."""
    try:
        # One read for nearly everyone: most logins were never given it.
        if str(user_id) not in (cj.grant_holders(business_id) or set()):
            return None
        import business_users_router
        if business_users_router.role_of(str(business_id), str(user_id)) != "manager":
            return None
    except Exception:  # noqa: BLE001 — a line left out, never a turn lost
        return None
    return ("This login also sets up the church's jobs and people's sheets (the owner or an Admin gave it that): it "
            "may make, change and remove the church's own jobs (save_church_job, remove_church_job) and change the "
            "sheet of a Manager login or below. Never its own sheet, an Admin's or the owner's, never Giving & "
            "money or a money duty, never an Admin job, and never who else sets jobs up: those are the owner's or "
            "an Admin's.")
