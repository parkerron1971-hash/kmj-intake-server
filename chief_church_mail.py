"""chief_church_mail.py — Chief gives every admin and leader their church address.

Kevin, 2026-11-11: "I want to make sure chief knows how to get people there
email with the @domain name for each church"; 2026-11-13: "chief doesn't know
about it … can we build what is needed so this can go live right away?"

    church_email .............. read. Every address and who it reaches right
                                now (looked up live: church_mail.reach), who
                                has none yet with a suggested address, and
                                whether mail to the domain reaches the system
                                yet. Any login may ask ("what's my church
                                email?"); the suggestions and forward targets
                                are the owner's and Admins' only.
    give_church_email ......... write. Make an address or point one somewhere
                                new: a login, a leader, a role (it follows
                                whoever holds it), the prayer list, the office
                                box, or an outside address. The owner or an
                                Admin only. The person gets one note naming
                                their address once mail reaches the system.
    take_back_church_email .... write. Turn an address off; its mail goes to
                                the office box and its history is kept.
    switch_on_church_mail ..... write. The owner's: turn on receiving for the
                                church's domain at the mail service (Resend,
                                where Email Setup already put the domain) and
                                name the one MX record left to add at the DNS
                                host, with what it replaces. Asked again once
                                the record is in, it asks the mail service to
                                check it.

Handlers return `result` AND `label` per the house contract.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import church_mail

_GIVERS = {"owner", "admin"}

TOOL = {
    "name": "church_email",
    "description": (
        "The church's own email addresses (@its domain): each address and who it reaches right now (a person's own "
        "box, a role that follows whoever holds it, the prayer list, the office box, or a forward), which one gets "
        "mail for addresses with no box, whether mail to the domain reaches the system yet, and for the pastor or "
        "an Admin, who has no address yet with a suggested one and the exact `to` to give it. Use it before "
        "answering \"what's my church email?\", \"who gets prayer@?\" or \"does Tia have an address?\", and before "
        "give_church_email so the person and address are real."),
    "input_schema": {"type": "object", "properties": {}},
}


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}", "failed": True, "label": msg[:80], "nav": None}


def _caller() -> str:
    from chief_of_staff import _TURN_USER_ID
    return _TURN_USER_ID.get() or ""


def _role(business_id: str, uid: str) -> Optional[str]:
    if not uid:
        return None
    from business_users_router import role_of
    return role_of(business_id, uid)


def _switch_line(domain: str, live: Optional[bool]) -> str:
    if live:
        return f"Mail to @{domain} reaches the system now."
    if live is None:
        return f"I couldn't look up where mail to @{domain} goes just now."
    return (f"Mail to @{domain} doesn't reach the system yet: its MX record still points at the old mail. "
            "Nothing is copied to anyone until that one record is changed.")


async def handle_church_email(client, biz, action) -> Dict[str, Any]:
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("church_email", "no business on record")
    uid = _caller()
    role = await asyncio.to_thread(_role, business_id, uid)
    if role is None:
        return _fail("church_email", "church email is read for a signed-in login of this church")
    full = role in _GIVERS
    try:
        d = await asyncio.to_thread(church_mail.directory, biz, full=full)
    except church_mail.Unavailable:
        return _fail("church_email", "the church's addresses couldn't be read just now; try again in a moment")
    domain = d["domain"]
    if not domain:
        return {"type": "church_email", "domain": "", "boxes": [], "suggest": [],
                "result": ("This church has no verified email domain yet, so there are no church addresses. "
                           "The first step is Build → Email Setup, step 1."),
                "label": "No church email domain yet", "nav": {"tab": "build", "sub": "email-setup"}}
    live = await asyncio.to_thread(church_mail.receiving_live, domain)
    lines: List[str] = [_switch_line(domain, live)]
    if d["boxes"]:
        lines.append("Addresses (each looked up live, so a role change or someone leaving moves it at once):")
        for b in d["boxes"]:
            tail = " — also gets mail for any address with no box" if b["catch_all"] else ""
            lines.append(f"- {b['address']} ({b['label']}): {b['goes_to']}{tail}")
    else:
        lines.append("No church addresses yet.")
    if full and d["suggest"]:
        lines.append("Who has none yet (suggested address → pass `to` exactly to give_church_email):")
        for s in d["suggest"]:
            addr = f"{s['address']}@{domain}" if s.get("address") else "(pick an address)"
            extra = " · no email on record to copy to" if s.get("has_email") is False else ""
            ca = " · catch_all:true" if s.get("catch_all") else ""
            lines.append(f"- {s['name']} ({s['who']}): {addr} · to={s['to']}{ca}{extra}")
    if full:
        held = await asyncio.to_thread(church_mail.held_count, business_id)
        if held:
            lines.append(f"{held} message(s) this week were kept but not copied because their sender couldn't be "
                         "checked or they looked like spam.")
    lines.append("Until the Email room is built, each person gets a copy of their mail at their own email and "
                 "replies from there. Mail to a prayer address goes on the prayer list, never into anyone's inbox.")
    return {"type": "church_email", "domain": domain, "receiving": live, "boxes": d["boxes"],
            "suggest": d["suggest"] if full else [], "result": "\n".join(lines),
            "label": f"✉️ {len(d['boxes'])} church address{'es' if len(d['boxes']) != 1 else ''}",
            "nav": None}


async def handle_give_church_email(client, biz, action) -> Dict[str, Any]:
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("give_church_email", "no business on record")
    uid = _caller()
    role = await asyncio.to_thread(_role, business_id, uid)
    if role not in _GIVERS:
        return _fail("give_church_email", "only the pastor or an Admin can give out church email addresses")
    address = str(action.get("address") or "")
    to = str(action.get("to") or action.get("for") or "")
    share = action.get("share_with") or []
    if isinstance(share, str):
        share = [share]
    try:
        got = await asyncio.to_thread(church_mail.give, biz, uid, address, to, share_with=share,
                                      catch_all=bool(action.get("catch_all")))
    except ValueError as e:
        return _fail("give_church_email", str(e))
    except church_mail.Unavailable:
        return _fail("give_church_email", "that couldn't be saved just now; try again in a moment")
    domain = got["address"].split("@", 1)[1]
    live = await asyncio.to_thread(church_mail.receiving_live, domain)
    told = ""
    box = got["box"]
    if box.get("kind") == "person" and action.get("tell", True) is not False:
        if live and not box.get("told_at"):
            why_not = await church_mail.welcome(biz, box)
            told = (f" {got['name'] or 'They'} got a note naming the address." if why_not is None
                    else f" No note went out: {why_not}.")
        elif not live:
            told = " Once mail reaches the system, ask me again and I'll send them a note naming it."
    if not got["changed"]:
        head = f"{got['address']} already goes to {got['goes_to']}."
    elif got["moved_from"]:
        head = f"{got['address']} now goes to {got['goes_to']} (it went to {got['moved_from']})."
    else:
        head = f"Made {got['address']}: it goes to {got['goes_to']}."
    if box.get("kind") == "role":
        head += " It follows whoever holds the role, so it moves on its own when the role changes hands."
    if box.get("kind") == "prayer":
        head += (" Mail to it joins the prayer list and is handed out like every other request; words about "
                 "danger stay with the pastor.")
    return {"type": "give_church_email", "address": got["address"], "goes_to": got["goes_to"],
            "result": f"{head}{told} {_switch_line(domain, live)}".strip(),
            "label": f"✉️ {got['address']}", "nav": None}


async def handle_take_back_church_email(client, biz, action) -> Dict[str, Any]:
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("take_back_church_email", "no business on record")
    role = await asyncio.to_thread(_role, business_id, _caller())
    if role not in _GIVERS:
        return _fail("take_back_church_email", "only the pastor or an Admin can take back a church address")
    try:
        got = await asyncio.to_thread(church_mail.take_back, biz, str(action.get("address") or ""))
    except ValueError as e:
        return _fail("take_back_church_email", str(e))
    except church_mail.Unavailable:
        return _fail("take_back_church_email", "that couldn't be saved just now; try again in a moment")
    extra = (" It was the office box, so mail for addresses with no box now goes to the pastor until another "
             "office box is named.") if got["was_catch_all"] else ""
    return {"type": "take_back_church_email", "address": got["address"],
            "result": (f"{got['address']} is off. Mail sent to it now goes to {got['now']}. Its old mail is kept."
                       f"{extra}"),
            "label": f"Took back {got['address']}", "nav": None}


def _mx_words(rows) -> str:
    return ", ".join(f"{h} (priority {p})" for p, h in rows)


async def handle_switch_on_church_mail(client, biz, action) -> Dict[str, Any]:
    """Receiving on at the mail service, and the one DNS record left. The
    owner's alone: it changes where the church's mail goes."""
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("switch_on_church_mail", "no business on record")
    role = await asyncio.to_thread(_role, business_id, _caller())
    if role != "owner":
        return _fail("switch_on_church_mail", "only the church's owner can switch its mail over")
    domain = church_mail.church_domain(biz)
    import email_sender
    did = str(email_sender.email_domain_settings(biz.get("settings")).get("resend_domain_id") or "")
    if not domain or not did:
        return _fail("switch_on_church_mail",
                     "the church's email domain isn't verified yet (Build → Email Setup, step 1)")
    import email_domains_router as edr
    from fastapi import HTTPException
    try:
        await edr._resend("PATCH", f"/{did}", {"capabilities": {"receiving": "enabled"}})
        dom = await edr._resend("GET", f"/{did}")
    except HTTPException as e:
        return _fail("switch_on_church_mail", f"the mail service didn't take it: {e.detail}")
    if dom.get("__missing__"):
        return _fail("switch_on_church_mail",
                     "the mail service no longer has this domain; reconnect it in Email Setup")
    rec = church_mail.receiving_record(dom)
    if not rec or not rec["host"]:
        return _fail("switch_on_church_mail", "receiving is on, but the mail service hasn't given its record "
                                              "yet; ask me again in a minute")
    now = await asyncio.to_thread(church_mail.apex_mx, domain)
    live = await asyncio.to_thread(church_mail.receiving_live, domain)
    want = f"MX at @ (the domain itself) → {rec['host']}, priority {rec['priority']}"
    if live:
        verified = rec["status"] == "verified"
        if not verified:
            try:
                await edr._resend("POST", f"/{did}/verify")
            except HTTPException:
                pass
        church_mail.forget_domain(domain)
        church_mail._LIVE_CACHE.pop(domain, None)
        text = (f"Mail to @{domain} now comes to the system ({want}). "
                + ("The mail service has checked the record." if verified else
                   "I asked the mail service to check the record; mail is accepted once it shows verified, "
                   "usually within minutes.")
                + " Church addresses take it from here; anything sent to an address with no box goes to the "
                  "office box, or the pastor if there isn't one.")
        return {"type": "switch_on_church_mail", "domain": domain, "live": True, "record": rec,
                "result": text, "label": f"✉️ @{domain} mail is on", "nav": None}
    if now:
        before = f"Today @{domain}'s mail goes to {_mx_words(now)}."
    elif now == []:
        before = f"@{domain} receives no email today, so nothing is replaced."
    else:
        before = f"I couldn't look up where @{domain}'s mail goes today."
    step = (f"At the domain's DNS host, the MX records for @{domain} become just one: {want}. Remove the others "
            "in the same save (mail goes to the lowest priority number, so a second one splits it).")
    try:
        import email_domain_dns
        ns = await email_domain_dns.lookup_ns(domain)
        provider = email_domain_dns.detect_provider(ns).get("key")
    except Exception:
        provider = None
    if provider == "namecheap":
        step = (f"In Namecheap: Domain List → {domain} → Manage → Advanced DNS → Mail Settings, which should say "
                f"Custom MX. Delete every MX row there and add one: host @, value {rec['host']}, priority "
                f"{rec['priority']}. Then Save all changes.")
    cname = await asyncio.to_thread(church_mail.apex_cname, domain)
    first = ""
    if cname:
        # A website connected with "CNAME @" (kmjcreate.com, 11-13): mail records can't sit beside it.
        first = (f"First: @{domain} itself is a CNAME (to {cname}), and mail records can't sit beside a CNAME. "
                 + ("In Namecheap's Host Records, change the @ row's type from CNAME Record to ALIAS Record, same "
                    "value, and save; the website keeps working. " if provider == "namecheap" else
                    "At the DNS host, change the @ record from a CNAME to an ALIAS (some hosts call it ANAME or "
                    "CNAME flattening) with the same value; the website keeps working. ")
                 + "Then: ")
    warn = ""
    if now:
        warn = (f" Once it's in, the old mail service stops getting @{domain} mail and church addresses take "
                "over, so before you change it, every address people write to today should have a box here "
                "(a forward for any that just went to someone's own email).")
    return {"type": "switch_on_church_mail", "domain": domain, "live": False, "record": rec,
            "apex_cname": cname or None,
            "result": (f"Receiving is on for @{domain} at the mail service. One record is left. {before} "
                       f"{first}{step}{warn} Tell me when it's in and I'll check it."),
            "label": f"✉️ One record left for @{domain}", "nav": None}
