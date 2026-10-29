"""member_portal_board.py — the Board tab, and the board's money yes, in the member app.

Kevin, 2026-10-28: "The 7 office logins are for the office only ...
Everyone else uses the member app, by role, on phone or computer", and
"build step 2 (the board member's yes from the member app, with a fresh code
on every approval) and then step 1 (a Board tab, with approvals inside it)
... build the Board tab for computers from the start". Then: "lets build
the board tab".

Elder Ruth is on the Elders board. Her Board tab opens on the next meeting:
when, where, the video link and the agenda the secretary set in Board &
minutes. Last month's minutes went out for approval, so she reads them
there, item by item with the motions and votes, before Thursday. The
decisions log answers "when did we approve the roof?". She never uses an
office login.

A $3,000 roof deposit has the treasurer's yes and the pastor's; it waits on
a board member. She gets an email, opens the Board tab on her laptop, sees
the request with its receipt and the yeses it has, and presses Approve: we
email her a fresh 6-digit code for that request alone, she types it in, and
her yes is the board's.

  GET  /my/board                        her boards: the meetings (?m=<id> opens one), who sits on it
                                        (?b=<id> picks a board when she's on several)
  GET  /my/board/decisions              what her boards decided (?q= words, ?b= a board)
  GET  /my/board/approvals              what waits on the board's yes (?r=<id> opens one)
  GET  /my/board/approvals/<id>/receipt its receipt (a board member it waits on, or who said yes)
  POST /my/board/approvals/<id>/code    email a fresh code for this request
  POST /my/board/approvals/<id>/approve {k: the code's id, code}: the yes

Who: the church's people on a board, matched by their person in Board &
minutes (church_board_members.contact_id, active, on a board that isn't
archived), and only the boards they sit on. The office keeps the pen: the
tab reads and never writes, except the money yes. Minutes show once the
secretary sends them for approval (or they're approved): a meeting still
being written shows its agenda, not its notes, votes or who came.

The tab follows the board's switch (CHURCH_BOARD: on shows it; owner and
off don't, so members never see a Board tab before the office has Board &
minutes). A member who also has the Serve tab finds the Board in the
sidebar on a computer and at the top of Serve on a phone: the phone's bar
holds six. The approvals follow check requests' switch (CHURCH_CHECKS:
owner shows them only in the platform owner's own preview, where nothing
saves) and the money levels; the rules are church_money_levels.py. A no is
the treasurer's, in the office, for now. Home stays as it is.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import church_money_levels as cml

logger = logging.getLogger("member_portal_board")
router = APIRouter(tags=["member-portal"])

HOME = "/my/board"
DECISIONS = "/my/board/decisions"
PATH = "/my/board/approvals"
_ID = re.compile(r"^[0-9a-fA-F-]{36}$")

BOARD_CSS = """
.bd-eb{margin:0;font-size:12.5px;font-weight:650;letter-spacing:.1em;text-transform:uppercase;color:var(--fg3);}
.bd-lede{margin:-6px 0 18px;font-size:15px;line-height:1.5;color:var(--fg2);max-width:40em;}
.bd-amt{margin:0;font-size:40px;font-weight:760;letter-spacing:-.04em;line-height:1;font-variant-numeric:tabular-nums;}
.bd-what{margin:4px 0 0;font-size:16px;color:var(--fg2);}
.bd-top{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;align-items:start;}
@media (min-width:1000px){.bd-top{grid-template-columns:minmax(0,1fr) 260px;}}
.bd-receipt{display:block;width:100%;max-height:360px;object-fit:contain;object-position:top;border-radius:var(--r-md);
  background:#fbf9f4;box-shadow:0 1px 0 rgba(0,0,0,.08),0 10px 30px -18px rgba(0,0,0,.5);}
.bd-pdf,.bd-none{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;min-height:150px;
  border-radius:var(--r-md);background:var(--s2);color:var(--fg2);font-size:14px;text-decoration:none;text-align:center;padding:12px;}
.bd-pdf b{color:var(--fg);font-size:15px;}
.bd-code{display:flex;flex-direction:column;gap:10px;}
.bd-code label{display:flex;flex-direction:column;gap:8px;font-size:14px;color:var(--fg2);}
.bd-code input{min-height:56px;border-radius:var(--r-sm);border:.5px solid var(--line);background:var(--s2);color:var(--fg);
  font:inherit;font-size:28px;font-weight:650;letter-spacing:.32em;text-align:center;font-variant-numeric:tabular-nums;}
.bd-code input:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (min-width:1000px){.bd-act .ld-btn,.bd-act .ld-ghost{max-width:360px;}}
.bd-flash{margin:0 0 14px;padding:12px 14px;border-radius:var(--r-md);background:var(--s1);font-size:15px;}
.bd-flash.ok{background:rgba(95,208,138,.12);}
.bd-flash.err{background:rgba(255,138,92,.12);}
.bd-sec{margin:18px 2px 8px;font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--fg3);}
.bd-empty{background:var(--s1);border-radius:var(--r-lg);padding:22px 20px;}
.bd-empty b{display:block;font-size:20px;font-weight:700;letter-spacing:-.02em;}
.bd-empty p{margin:6px 0 0;color:var(--fg2);font-size:15px;}
.bd-back{display:inline-flex;margin:0 0 4px;font-size:14.5px;font-weight:600;color:var(--acc);text-decoration:none;}
@media (min-width:1000px){.bd-back{display:none;}}
a.ld-btn,a.ld-ghost{text-decoration:none;}
.bd-boards{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px;}
.bd-boards a{display:inline-flex;align-items:center;min-height:40px;padding:0 16px;border-radius:999px;background:var(--s2);
  color:var(--fg);text-decoration:none;font-size:14.5px;font-weight:600;}
.bd-boards a[aria-current]{background:var(--fg);color:var(--bg);}
.bd-cal{width:44px;height:48px;border-radius:12px;background:var(--s3);display:flex;flex-direction:column;align-items:center;
  justify-content:center;flex:none;line-height:1;}
.bd-cal small{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--fg2);}
.bd-cal b{font-size:19px;font-weight:750;margin-top:3px;}
.bd-cal.next{background:var(--mb-fill);color:var(--mb-on-fill);}
.bd-cal.next small{color:inherit;opacity:.85;}
.bd-when{margin:0;font-size:24px;font-weight:720;letter-spacing:-.02em;line-height:1.2;}
.bd-where{margin:0;font-size:15px;color:var(--fg2);}
.bd-items{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;}
.bd-items>li{padding:14px 0;border-top:.5px solid var(--line);display:flex;flex-direction:column;gap:6px;}
.bd-items>li:first-child{border-top:0;padding-top:2px;}
.bd-it{display:flex;gap:10px;align-items:baseline;}
.bd-it b{font-size:16.5px;font-weight:650;flex:1;min-width:0;}
.bd-n{font-variant-numeric:tabular-nums;color:var(--fg3);font-weight:650;min-width:1.4em;}
.bd-notes,.bd-files{margin:0 0 0 calc(1.4em + 10px);font-size:14.5px;color:var(--fg2);white-space:pre-wrap;}
.bd-files{font-size:13px;color:var(--fg3);white-space:normal;}
.bd-min{margin:0 0 0 calc(1.4em + 10px);font-size:15.5px;line-height:1.55;white-space:pre-wrap;}
.bd-motion{margin:4px 0 0 calc(1.4em + 10px);padding:10px 12px;border-radius:var(--r-sm);background:var(--s2);font-size:14.5px;
  display:flex;flex-direction:column;gap:3px;}
.bd-motion small{color:var(--fg2);font-size:13px;}
.bd-res{font-weight:700;}
.bd-res.carried{color:#5fd08a;}
.bd-res.failed{color:#ff8a5c;}
.bd-who{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:10px;}
.bd-who li{display:flex;align-items:center;gap:10px;font-size:15px;}
.bd-who li span{display:flex;flex-direction:column;min-width:0;}
.bd-who small{color:var(--fg2);font-size:13px;}
.bd-who .ld-av{width:36px;height:36px;font-size:13px;}
.bd-search{display:flex;gap:8px;margin:0;}
.bd-search input{flex:1;min-width:0;min-height:46px;padding:0 16px;border-radius:999px;border:.5px solid var(--line);
  background:var(--s2);color:var(--fg);font:inherit;font-size:15px;}
.bd-search input:focus-visible,.bd-search button:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.bd-search button{min-height:46px;padding:0 18px;border:0;border-radius:999px;background:var(--mb-fill);color:var(--mb-on-fill);
  font:inherit;font-size:15px;font-weight:650;}
.bd-decs{display:flex;flex-direction:column;gap:10px;margin-top:14px;}
@media (min-width:1000px){.bd-decs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));}}
.bd-dec{display:flex;flex-direction:column;gap:4px;padding:14px 16px;border-radius:var(--r-md);background:var(--s1);
  text-decoration:none;color:var(--fg);}
.bd-dec b{font-size:16px;font-weight:650;}
.bd-dec small{font-size:13px;color:var(--fg2);}
.bd-dec:focus-visible,.bd-boards a:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
"""


def _e(s: Any) -> str:
    import member_portal_checks as mpck
    return mpck._e(s)


def _usd(c: Any) -> str:
    return cml.usd(c)


def _day(iso: Any) -> str:
    import member_portal_checks as mpck
    return mpck._day(iso)


def shown_here(request: Request, biz: Dict[str, Any]) -> bool:
    """Where check requests show in the member app at all (CHURCH_CHECKS),
    with the money levels on."""
    import member_portal_checks as mpck
    return cml.on() and mpck.shown_here(request, biz)


# ─── Words ───────────────────────────────────────────────────────────

def _steps_line(row: Dict[str, Any], lv: Dict[str, Any]) -> str:
    needs = lv.get("needs") or []
    parts = [f"{cml.words(needs).capitalize()} {'says' if len(needs) == 1 else 'say'} yes."] if needs else []
    if lv.get("others_cents") and lv.get("counted_cents"):
        parts.append(f"With {_usd(lv['others_cents'])} more to the same payee this week, it counts as "
                     f"{_usd(lv['counted_cents'])}.")
    if lv.get("over_budget"):
        parts.append(f"It takes {row.get('ministry') or 'its ministry'} past this year's budget, so a board member "
                     "says yes too.")
    return " ".join(parts)


def _yes_words(row: Dict[str, Any], lv: Dict[str, Any]) -> str:
    return f"Approve {_usd(row.get('amount_cents'))}" if lv.get("missing") == ["board"] else "Say yes as a board member"


FLASH = {
    "sent": ("ok", "We emailed you a code. It works for {m} minutes, for this request only."),
    "approved": ("ok", "Approved. The treasurer pays it and marks it paid."),
    "yes": ("ok", "Your yes is in. It waits on {w}."),
}


def _flash(request: Request, email: str) -> str:
    q = request.query_params
    done, err = q.get("done") or "", q.get("err") or ""
    if err:
        msg = (q.get("msg") or "That didn't work. Please try again.")[:240]
        return f'<p class="bd-flash err" role="alert">{_e(msg)}</p>'
    if done in FLASH:
        kind, text = FLASH[done]
        text = text.format(m=cml.CODE_MINUTES, w=(q.get("w") or "the others")[:80])
        if done == "sent" and email:
            text = text.replace("emailed you", f"emailed {email}")
        return f'<p class="bd-flash {kind}" role="status">{_e(text)}</p>'
    return ""


# ─── The page ────────────────────────────────────────────────────────

def _item(x: Dict[str, Any], sel: str) -> str:
    r, lv = x["row"], x["levels"]
    rid = str(r["id"])
    if r.get("status") == "new":
        end = "Your yes is in" if x.get("mine") else "Waits on you"
        tone = "soon" if x.get("mine") else "new"
    else:
        end, tone = {"approved": ("Approved", "new"), "paid": ("Paid", "new"), "declined": ("Declined", "")}.get(
            r.get("status"), ("", ""))
    cur = ' aria-current="page" data-shown=""' if rid == sel else ""
    return (f'<a class="ld-p" href="{PATH}?{urlencode({"r": rid})}"{cur}>'
            f'<span class="ld-av new" aria-hidden="true">$</span>'
            f'<span class="t"><b>{_e(_usd(r.get("amount_cents")))} · {_e(r.get("ministry") or "")}</b>'
            f'<small>{_e(r.get("about") or "")} · {_e(r.get("payee") or x.get("who") or "")}</small></span>'
            f'<span class="ld-due {tone}">{_e(end)}</span></a>')


def _receipt(r: Dict[str, Any]) -> str:
    rid = str(r["id"])
    src = f"{PATH}/{rid}/receipt"
    if r.get("receipt_path") and r.get("receipt_type") == "pdf":
        return (f'<a class="bd-pdf" href="{src}" target="_blank" rel="noopener"><b>The receipt</b>'
                '<span>A PDF. Open it</span></a>')
    if r.get("receipt_path"):
        return (f'<a href="{src}" target="_blank" rel="noopener" aria-label="Open the receipt full size">'
                f'<img class="bd-receipt" src="{src}" alt="The receipt for {_e(r.get("about") or "this request")}" '
                'loading="lazy"></a>')
    return '<div class="bd-none"><b>No receipt</b><span>Ask the treasurer for one before you say yes.</span></div>'


def _steps(lv: Dict[str, Any], me_name: str) -> str:
    have = {h["step"]: h for h in lv.get("have") or []}
    rows = []
    for s in [x for x in cml.STEPS if x in (lv.get("needs") or [])]:
        h = have.get(s)
        if h:
            dot, said = '<span class="ld-dot done" aria-hidden="true">✓</span>', f"{h['by']}, {_day(h.get('at'))}"
        elif s == "board" and lv.get("mine") == "board":
            dot, said = '<span class="ld-dot now" aria-hidden="true"></span>', "Yours to give"
        else:
            dot, said = '<span class="ld-dot" aria-hidden="true"></span>', "Still to say yes"
        rows.append(f"<li>{dot}<span><b>{_e(cml.WORD[s].capitalize())}</b><small>{_e(said)}</small></span></li>")
    return f'<ol class="ld-steps" aria-label="Who says yes">{"".join(rows)}</ol>'


def _file(x: Dict[str, Any], email: str, code_id: str, me_name: str) -> str:
    r, lv = x["row"], x["levels"]
    rid = str(r["id"])
    facts = "".join(f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in (
        ("Pay", r.get("payee") or x.get("who") or "—"), ("Asked by", x.get("who") or "The office"),
        ("Sent", _day(r.get("created_at")))))
    top = (f'<section class="ld-card"><div class="bd-top"><div>'
           f'<p class="bd-amt">{_e(_usd(r.get("amount_cents")))}</p>'
           f'<p class="bd-what">{_e(r.get("ministry") or "")} · {_e(r.get("about") or "")}</p>'
           f'<dl class="ld-ans" style="margin-top:14px">{facts}</dl></div>'
           f'<div>{_receipt(r)}</div></div></section>')
    who = (f'<section class="ld-card"><h3>Who says yes</h3>{_steps(lv, me_name)}'
           f'<p class="ld-why">{_e(_steps_line(r, lv))}</p></section>')
    act = ""
    if r.get("status") == "new" and lv.get("mine") == "board":
        if code_id:
            act = (f'<form class="bd-code" method="post" action="{PATH}/{rid}/approve">'
                   f'<input type="hidden" name="k" value="{_e(code_id)}">'
                   f'<label for="bd-code">The 6-digit code we emailed{f" to {_e(email)}" if email else ""}'
                   '<input id="bd-code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="7" '
                   'pattern="[0-9 ]{6,7}" required></label>'
                   f'<button class="ld-btn" type="submit">{_e(_yes_words(r, lv))}</button></form>'
                   f'<form method="post" action="{PATH}/{rid}/code"><button class="ld-ghost" type="submit">'
                   'Send a new code</button></form>')
        else:
            act = (f'<form method="post" action="{PATH}/{rid}/code"><button class="ld-btn" type="submit">'
                   f'{_e(_yes_words(r, lv))}</button></form>'
                   f'<p class="ld-quiet">First we email a 6-digit code{f" to {_e(email)}" if email else ""}, '
                   'so we know it’s you.</p>')
    elif r.get("status") == "new" and lv.get("why_not"):
        act = f'<p class="ld-why">{_e(lv["why_not"])}</p>'
    if r.get("status") == "new":
        act += '<p class="ld-quiet">To say no, tell the treasurer: they decline it, with the reason the asker reads.</p>'
    acts = f'<section class="ld-card bd-act">{act}</section>' if act else ""
    return f'<a class="bd-back" href="{PATH}">All requests</a>{top}{who}{acts}'


def render_page(biz: Dict[str, Any], site, request: Request, person: Dict[str, Any], view: Dict[str, Any]) -> str:
    from member_portal import _shell
    from member_portal_lead import LEAD_CSS
    q = request.query_params
    every = view["waiting"] + view["said"]
    sel = q.get("r") or ""
    if not any(str(x["row"]["id"]) == sel for x in every):
        sel = str(view["waiting"][0]["row"]["id"]) if len(view["waiting"]) == 1 else ""
    chosen = next((x for x in every if str(x["row"]["id"]) == sel), None)
    code_id = (q.get("k") or "") if chosen and _ID.match(q.get("k") or "") else ""
    head = ('<header class="ld-head"><div><p class="bd-eb">The board · money going out</p>'
            '<h1 class="ld-hello">Waiting on <em>your yes</em></h1></div></header>'
            f'<p class="bd-lede">Over {_e(_usd(cml.BOARD_OVER_CENTS))}, or past a ministry’s budget, a check request '
            'needs a board member’s yes too. Each yes takes a fresh code we email you, for that request alone.</p>')
    if not every:
        body = ('<div class="bd-empty"><b>Nothing is waiting on the board.</b>'
                '<p>When a check request needs a board member’s yes, it shows here, and we email you.</p></div>')
        return _shell(biz, site, "Board approvals", f'<style>{LEAD_CSS}{BOARD_CSS}</style><div class="ld-wide">'
                      f'{_flash(request, view["email"])}{head}{body}</div>', tab="board", who=person,
                      back=_back())
    items = "".join(_item(x, sel) for x in view["waiting"])
    done = "".join(_item(x, sel) for x in view["said"])
    lst = ((f'<p class="bd-sec">Waiting · {len(view["waiting"])}</p>{items}' if items else
            '<div class="bd-empty"><b>Nothing waits on you now.</b><p>What you said yes to is below.</p></div>')
           + (f'<p class="bd-sec">You said yes</p>{done}' if done else ""))
    pane = (_file(chosen, view["email"], code_id, person.get("name") or "") if chosen else
            '<div class="bd-empty"><b>Pick a request</b><p>Its receipt, who has said yes, and your yes show here.</p></div>')
    grid = f'<div class="ld-grid{" has-sel" if chosen else ""}"><div class="ld-list">{lst}</div><div class="ld-file">{pane}</div></div>'
    return _shell(biz, site, "Board approvals", f'<style>{LEAD_CSS}{BOARD_CSS}</style><div class="ld-wide">'
                  f'{_flash(request, view["email"])}{head}{grid}</div>', tab="board", who=person, back=_back())


def _back():
    """The approvals sit inside the Board tab, while it's on."""
    return (HOME, "Board") if tab_on() else None


# ─── The Board tab ───────────────────────────────────────────────────

def tab_on() -> bool:
    """The Board tab follows Board & minutes' switch: on only."""
    import church_board as cb
    return cb.mode() == "on"


def boards_of(biz_id: str, person_id: str) -> Set[str]:
    """The boards this person sits on: an active member row with their person
    (church_board_members.contact_id), on a board that isn't archived. A
    read that fails raises (a 503), never "none"."""
    import church_board as cb
    if not _ID.match(person_id or ""):
        return set()
    rows = cb._need(f"/church_board_members?business_id=eq.{cb._q(biz_id)}&contact_id=eq.{cb._q(person_id)}"
                    "&active=eq.true&select=board_id&limit=50")
    ids = sorted({str(r["board_id"]) for r in rows if r.get("board_id")})
    if not ids:
        return set()
    return {str(b["id"]) for b in cb._need(
        f"/church_boards?business_id=eq.{cb._q(biz_id)}&id=in.({','.join(cb._q(i) for i in ids)})"
        "&archived=eq.false&select=id&limit=50")}


async def on_board(biz: Dict[str, Any], person: Optional[Dict[str, Any]]) -> bool:
    """Whether this member gets the Board tab. A read that fails gives no
    tab, the way a page stands without its door."""
    if not tab_on() or not person:
        return False
    try:
        return bool(await asyncio.to_thread(boards_of, str(biz["id"]), str(person.get("id") or "")))
    except Exception:  # noqa: BLE001
        logger.warning("board tab: membership read failed (business %s)", str(biz.get("id"))[:8])
        return False


def serve_door() -> str:
    """The Board's row at the top of Serve, for a board member who has Serve
    too: the phone's bar holds six, so the Board isn't a tab for them
    there (a computer's sidebar lists it under Your church)."""
    import member_spaces as msp
    ctx = msp.CURRENT.get() or {}
    if not (ctx.get("board") and ctx.get("lead")):
        return ""
    import member_portal_checks as mpck
    return (f'<style>{mpck.DOOR_CSS}</style><a class="ck-door" href="{HOME}">'
            f'<span class="ck-door-ic" aria-hidden="true">{mpck._ic("users", 20)}</span>'
            '<span class="t"><b>The board</b><small>Meetings, minutes, and what waits on your yes</small></span>'
            f'{mpck._ic("chevron", 18)}</a>')


def _board_me(biz: Dict[str, Any], mine: Set[str]) -> Dict[str, Any]:
    """A board member in the member app, as Board & minutes reads a login:
    only the boards they sit on, and no pen."""
    return {"biz": biz, "role": "viewer", "uid": "", "user": None, "boss": False, "mine": set(mine),
            "writer": False}


def minutes_out(m: Dict[str, Any]) -> bool:
    """A meeting's minutes are the board's to read once they're sent for
    approval, or approved."""
    return m.get("status") == "approved" or (m.get("status") == "drafted" and bool(m.get("sent_at")))


def _agenda_only(mp: Dict[str, Any]) -> Dict[str, Any]:
    """A meeting whose minutes aren't out: its agenda, without the notes
    taken, the votes or who came."""
    return {**mp, "items": [{**i, "minutes": "", "decisions": [], "follow_up": None} for i in mp["items"]],
            "roster": [{**p, "status": None} for p in mp["roster"]], "hidden": True}


def board_view(biz: Dict[str, Any], person: Dict[str, Any], board_id: str = "", meeting_id: str = "") -> Dict[str, Any]:
    """One board of theirs: its meetings to come and the ones past, and one
    meeting opened (the one asked for, else the next, else the latest).
    403 for anyone on no board."""
    import church_board as cb
    mine = boards_of(str(biz["id"]), str(person.get("id") or ""))
    if not mine:
        raise HTTPException(403, "This is for the church's boards.")
    me = _board_me(biz, mine)
    pg = cb.page(me)
    if not pg["boards"]:
        raise HTTPException(403, "This is for the church's boards.")
    board = next((b for b in pg["boards"] if b["id"] == board_id), pg["boards"][0])
    meetings = [m for m in pg["meetings"] if m["board_id"] == board["id"]]
    coming = sorted((m for m in meetings if m["status"] in ("planned", "in_progress")),
                    key=lambda m: str(m.get("starts_at") or ""))
    past = [m for m in meetings if m["status"] in ("drafted", "approved")]
    asked = meeting_id if any(m["id"] == meeting_id for m in meetings) else ""
    pick = asked or (coming[0]["id"] if coming else past[0]["id"] if past else "")
    chosen = None
    if pick:
        chosen = cb.meeting_page(me, cb._meeting(me, pick))
        if not minutes_out(chosen["meeting"]):
            chosen = _agenda_only(chosen)
        # Earlier minutes this meeting approves: readable once they're out.
        chosen["read_first"] = [w for w in chosen.get("waiting") or [] if w.get("sent_at")]
    return {"boards": pg["boards"], "board": board, "coming": coming, "past": past, "chosen": chosen,
            "asked": bool(asked), "zone": cb._zone(me)}


def decisions_view(biz: Dict[str, Any], person: Dict[str, Any], q: str = "", board_id: str = "") -> Dict[str, Any]:
    """What their boards decided, newest first: only decisions whose minutes
    are out."""
    import church_board as cb
    mine = boards_of(str(biz["id"]), str(person.get("id") or ""))
    if not mine:
        raise HTTPException(403, "This is for the church's boards.")
    me = _board_me(biz, mine)
    log = cb.decisions_log(me, q=q[:120], board_id=board_id if board_id in mine else "")
    unsure = sorted({d["meeting_id"] for d in log["decisions"] if not d.get("approved")})
    out_ids: Set[str] = set()
    for chunk in cb._chunks(unsure):
        out_ids |= {str(m["id"]) for m in cb._need(
            f"/church_board_meetings?business_id=eq.{cb._q(biz['id'])}&id=in.({','.join(chunk)})"
            "&select=id,status,sent_at&limit=500") if minutes_out(m)}
    return {"decisions": [d for d in log["decisions"] if d.get("approved") or d["meeting_id"] in out_ids],
            "q": log["q"], "zone": cb._zone(me)}


# ─── The Board tab: words and pieces ─────────────────────────────────

ITEM_WORDS = {"done": "Done", "tabled": "Tabled", "follow_up": "Follow-up"}


def _local(iso: Any, zone):
    import church_board as cb
    d = cb._at(iso)
    return d.astimezone(zone) if d else None


def _short(iso: Any, zone) -> str:
    """'Thu, Oct 29 · 7:00 PM'."""
    d = _local(iso, zone)
    if not d:
        return ""
    return f"{d:%a}, {d:%b} {d.day} · {d.strftime('%I').lstrip('0') or '12'}:{d:%M} {d:%p}"


def _cal(iso: Any, zone, nxt: bool = False) -> str:
    d = _local(iso, zone)
    cls = "bd-cal next" if nxt else "bd-cal"
    if not d:
        return f'<span class="{cls}" aria-hidden="true"><b>·</b></span>'
    return f'<span class="{cls}" aria-hidden="true"><small>{d:%b}</small><b>{d.day}</b></span>'


def _state(m: Dict[str, Any]) -> tuple:
    s = m.get("status")
    if s == "drafted":
        return ("Minutes to read", "soon") if m.get("sent_at") else ("Minutes coming", "")
    return {"planned": ("Coming up", ""), "in_progress": ("Meeting now", "soon"),
            "approved": ("Approved", "new")}.get(s, ("", ""))


def _row(m: Dict[str, Any], board_id: str, zone, sel: str, nxt: bool = False, asked: bool = False) -> str:
    href = f'{HOME}?{urlencode({"b": board_id, "m": m["id"]})}'
    # The meeting opened beside the list on a computer is marked there only
    # (data-shown); a phone shows the list alone until one is picked.
    cur = "" if m["id"] != sel else ' aria-current="page" data-shown=""' if asked else ' data-shown=""'
    where = m.get("place") or ("A video call" if m.get("video_url") else "")
    word, tone = _state(m)
    return (f'<a class="ld-p" href="{href}"{cur}>{_cal(m.get("starts_at"), zone, nxt)}'
            f'<span class="t"><b>{_e(m.get("title") or "Board meeting")}</b>'
            f'<small>{_e(_short(m.get("starts_at"), zone))}{" · " + _e(where) if where else ""}</small></span>'
            f'<span class="ld-due {tone}">{_e(word)}</span></a>')


def _motion(d: Dict[str, Any]) -> str:
    import church_board as cb
    who = ", ".join(x for x in (f"Moved by {d['moved_by_name']}" if d.get("moved_by_name") else "",
                                f"seconded by {d['seconded_by_name']}" if d.get("seconded_by_name") else "") if x)
    res = d.get("result") or ""
    return (f'<div class="bd-motion"><span><b>Motion:</b> {_e(d.get("motion") or "")}</span>'
            f'<small>{_e(who + ". " if who else "")}{_e(cb.vote_words(d))} '
            f'<span class="bd-res {_e(res)}">{_e(cb.RESULT_WORDS.get(res, res))}</span></small></div>')


def _agenda(mp: Dict[str, Any]) -> str:
    rows = []
    for n, i in enumerate(mp["items"], start=1):
        word = ITEM_WORDS.get(i.get("status") or "") if not mp.get("hidden") else ""
        tag = f'<span class="ld-tag">{_e(word)}</span>' if word else ""
        files = [d.get("name") or (d.get("path") or "").rsplit("/", 1)[-1] for d in i.get("documents") or []]
        rows.append(
            f'<li><span class="bd-it"><span class="bd-n">{n}.</span><b>{_e(i.get("title") or "")}</b>{tag}</span>'
            + (f'<p class="bd-notes">{_e(i["notes"])}</p>' if i.get("notes") else "")
            + (f'<p class="bd-files">Files: {_e(", ".join(f for f in files if f))}. The office has them.</p>'
               if any(files) else "")
            + (f'<p class="bd-min">{_e(i["minutes"])}</p>' if i.get("minutes") else "")
            + "".join(_motion(d) for d in i.get("decisions") or [])
            + "</li>")
    if not rows:
        return '<p class="ld-why">The agenda isn’t set yet. The secretary adds it before the meeting.</p>'
    return f'<ol class="bd-items">{"".join(rows)}</ol>'


def _came(mp: Dict[str, Any]) -> str:
    if mp.get("hidden"):
        return ""
    by = {s: [p["name"] for p in mp["roster"] if p.get("status") == s] for s in ("present", "absent", "excused")}
    if not any(by.values()):
        return ""
    q = mp["quorum"]
    lines = "".join(f'<div><dt>{w}</dt><dd>{_e(", ".join(by[s]))}</dd></div>'
                    for s, w in (("present", "Present"), ("absent", "Absent"), ("excused", "Excused")) if by[s])
    met = "The quorum was met" if q["met"] else "The quorum was not met"
    return (f'<section class="ld-card"><h3>Who came</h3><dl class="ld-ans">{lines}</dl>'
            f'<p class="ld-why">{q["present"]} of {q["total"]} present, {q["needed"]} needed. {met}.</p></section>')


def _pane(view: Dict[str, Any]) -> str:
    import church_board as cb
    mp, zone, board = view["chosen"], view["zone"], view["board"]
    m = mp["meeting"]
    live = m.get("status") in ("planned", "in_progress")
    join = (f'<a class="ld-btn" href="{_e(m["video_url"])}" target="_blank" rel="noopener noreferrer">'
            'Join the video call</a>' if live and m.get("video_url") else "")
    word, _tone = _state(m)
    top = (f'<section class="ld-card"><h3>{_e(board["name"])} · {_e(word)}</h3>'
           f'<p class="bd-when">{_e(cb.when_words(m.get("starts_at"), zone))}</p>'
           + (f'<p class="bd-where">{_e(m["title"])}</p>' if m.get("title") else "")
           + (f'<p class="bd-where">{_e(m["place"])}</p>' if m.get("place") else "")
           + (f'<div class="bd-act">{join}</div>' if join else "") + "</section>")
    first = ""
    if live and mp.get("read_first"):
        links = "".join(f'<a class="ld-p" href="{HOME}?{urlencode({"b": board["id"], "m": str(w["id"])})}">'
                        f'{_cal(w.get("starts_at"), zone)}<span class="t"><b>The minutes of '
                        f'{_e(cb.when_words(w.get("starts_at"), zone).split(" at ")[0])}</b>'
                        '<small>This meeting approves them</small></span>'
                        '<span class="ld-due soon">Read</span></a>' for w in mp["read_first"])
        first = f'<section class="ld-card"><h3>Read before this meeting</h3>{links}</section>'
    heading = "The agenda" if mp.get("hidden") else ("The minutes" if m.get("status") == "approved"
                                                      else "The minutes, for approval")
    note = ""
    if mp.get("hidden") and m.get("status") != "planned":
        note = '<p class="ld-quiet">The minutes show here once the secretary sends them for approval.</p>'
    elif m.get("status") == "drafted":
        note = ('<p class="ld-quiet">A draft: the board approves it at a later meeting. Corrections go to the '
                'secretary.</p>')
    body = f'<section class="ld-card"><h3>{heading}</h3>{_agenda(mp)}{note}</section>'
    back = f'<a class="bd-back" href="{HOME}?{urlencode({"b": board["id"]})}">All meetings</a>'
    return f'{back}{top}{first}{body}{_came(mp)}'


def _members_card(board: Dict[str, Any]) -> str:
    import member_app_ui as ui
    rows = []
    for x in board.get("members") or []:
        title = f'<small>{_e(x["title"])}</small>' if x.get("title") else ""
        rows.append(f'<li><span class="ld-av" aria-hidden="true">{_e(ui.initials(x.get("name")))}</span>'
                    f'<span><b>{_e(x.get("name") or "")}</b>{title}</span></li>')
    who = "".join(rows)
    return (f'<section class="ld-card"><h3>Who sits on {_e(board["name"])}</h3><ul class="bd-who">{who}</ul>'
            f'<p class="ld-why">Quorum: {_e(board.get("quorum_words") or "")}.</p></section>')


def _search(q: str = "", board_id: str = "") -> str:
    keep = f'<input type="hidden" name="b" value="{_e(board_id)}">' if board_id else ""
    return (f'<form class="bd-search" method="get" action="{DECISIONS}" role="search">{keep}'
            f'<input name="q" value="{_e(q)}" maxlength="120" aria-label="Search what the board decided" '
            'placeholder="Search what the board decided"><button type="submit">Search</button></form>')


def _money_door(waiting: Optional[int]) -> str:
    """Into the board's approvals, while check requests show here."""
    if waiting is None:
        return ""
    import member_portal_checks as mpck
    word = (f"{waiting} check request{'s' if waiting != 1 else ''} {'wait' if waiting != 1 else 'waits'} on your yes"
            if waiting else "Board approvals")
    small = ("Each yes takes a fresh code we email you" if waiting else
             f"Over {_usd(cml.BOARD_OVER_CENTS)}, or past a ministry’s budget, a board member says yes too")
    return (f'<style>{mpck.DOOR_CSS}</style><a class="ck-door" href="{PATH}">'
            f'<span class="ck-door-ic" aria-hidden="true">{mpck._ic("check", 20)}</span>'
            f'<span class="t"><b>{_e(word)}</b><small>{_e(small)}</small></span>{mpck._ic("chevron", 18)}</a>')


def render_board(biz: Dict[str, Any], site, person: Dict[str, Any], view: Dict[str, Any],
                 waiting: Optional[int] = None) -> str:
    from member_portal import _shell
    from member_portal_lead import LEAD_CSS
    board, zone = view["board"], view["zone"]
    chips = ""
    if len(view["boards"]) > 1:
        here = ' aria-current="page"'
        chips = '<nav class="bd-boards" aria-label="Your boards">' + "".join(
            f'<a href="{HOME}?{urlencode({"b": b["id"]})}"{here if b["id"] == board["id"] else ""}>'
            f'{_e(b["name"])}</a>' for b in view["boards"]) + "</nav>"
    head = ('<header class="ld-head"><div><p class="bd-eb">The board</p>'
            f'<h1 class="ld-hello">{_e(board["name"])}</h1></div></header>'
            '<p class="bd-lede">Your meetings, the agenda, the minutes and what the board decided. Only the '
            'board’s members see this.</p>')
    sel = view["chosen"]["meeting"]["id"] if view["chosen"] else ""
    asked = view["asked"]
    coming = "".join(_row(m, board["id"], zone, sel, nxt=(n == 0), asked=asked) for n, m in enumerate(view["coming"]))
    past = "".join(_row(m, board["id"], zone, sel, asked=asked) for m in view["past"][:24])
    lst = ((f'<p class="bd-sec">Coming up</p>{coming}' if coming else
            '<div class="bd-empty"><b>No meeting is set.</b><p>When the secretary sets the next one, it shows here '
            'with its agenda.</p></div>')
           + (f'<p class="bd-sec">Past meetings</p>{past}' if past else "")
           + f'<p class="bd-sec">Decisions</p>{_search(board_id=board["id"])}'
           + _members_card(board))
    pane = (_pane(view) if view["chosen"] else
            '<div class="bd-empty"><b>No meetings yet</b><p>The agenda and the minutes show here.</p></div>')
    grid = (f'<div class="ld-grid{" has-sel" if view["asked"] else ""}"><div class="ld-list">{lst}</div>'
            f'<div class="ld-file">{pane}</div></div>')
    return _shell(biz, site, "Board", f'<style>{LEAD_CSS}{BOARD_CSS}</style><div class="ld-wide">'
                  f'{chips}{head}{_money_door(waiting)}{grid}</div>', tab="board", who=person)


def render_decisions(biz: Dict[str, Any], site, person: Dict[str, Any], view: Dict[str, Any],
                     board_id: str = "") -> str:
    import church_board as cb
    from member_portal import _shell
    from member_portal_lead import LEAD_CSS
    zone, q = view["zone"], view["q"]
    rows = []
    for d in view["decisions"][:200]:
        day = cb.when_words(d.get("meeting_starts_at"), zone).split(" at ")[0] if d.get("meeting_starts_at") else ""
        res = d.get("result") or ""
        href = f'{HOME}?{urlencode({"b": d["board_id"], "m": d["meeting_id"]})}'
        rows.append(f'<a class="bd-dec" href="{href}"><b>{_e(d.get("motion") or "")}</b>'
                    f'<small>{_e(d.get("item_title") or "")}{" · " if d.get("item_title") else ""}{_e(d.get("board") or "")}'
                    f'{", " + _e(day) if day else ""}</small>'
                    f'<small>{_e(cb.vote_words(d))} <span class="bd-res {_e(res)}">{_e(cb.RESULT_WORDS.get(res, res))}'
                    '</span></small></a>')
    if rows:
        body = f'<div class="bd-decs">{"".join(rows)}</div>'
    elif q:
        body = f'<div class="bd-empty" style="margin-top:14px"><b>Nothing matches “{_e(q)}”.</b><p>Try fewer words.</p></div>'
    else:
        body = ('<div class="bd-empty" style="margin-top:14px"><b>No decisions yet.</b>'
                '<p>Motions show here once their minutes go out.</p></div>')
    head = ('<header class="ld-head"><div><p class="bd-eb">The board</p>'
            '<h1 class="ld-hello">What the board <em>decided</em></h1></div></header>')
    return _shell(biz, site, "Decisions", f'<style>{LEAD_CSS}{BOARD_CSS}</style><div class="ld-wide">'
                  f'{head}{_search(q, board_id)}{body}</div>', tab="board", who=person, back=(HOME, "Board"))


# ─── GET (through member_portal.serve) ───────────────────────────────

async def serve(request: Request, church: Dict[str, Any], me: Dict[str, Any], sub: str, preview: bool = False):
    from member_portal import _page, _SECURE_HEADERS, _shell
    biz, site = church["business"], church.get("site")
    home = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if sub in (HOME, HOME + "/", DECISIONS):
        if not tab_on():
            # Before the Board tab, the board's approvals were all there was.
            return (RedirectResponse(PATH, status_code=303, headers=_SECURE_HEADERS)
                    if sub != DECISIONS and shown_here(request, biz) else home)
        return await _tab(request, biz, site, me, sub)
    if not shown_here(request, biz):
        return home
    rest = sub[len(PATH):].strip("/") if sub.startswith(PATH) else None
    if rest is None:
        return home
    if rest:
        rid = rest[:-len("/receipt")] if rest.endswith("/receipt") else ""
        if not _ID.match(rid):
            return Response(status_code=404, headers=_SECURE_HEADERS)
        try:
            got = await asyncio.to_thread(cml.member_receipt, biz, me, rid)
        except HTTPException as e:
            return Response(status_code=404 if e.status_code in (400, 403, 404) else 503, headers=_SECURE_HEADERS)
        got.headers["X-Frame-Options"] = "DENY"
        return got
    try:
        view = await asyncio.to_thread(cml.member_view, biz, me)
    except HTTPException as e:
        if e.status_code in (403, 404):
            return home
        logger.warning("board approvals: didn't load (%s, business %s)", e.status_code, str(biz.get("id"))[:8])
        return _page(_shell(biz, site, "Board approvals", '<a class="mb-back" href="/my">Home</a>'
                            '<p class="mp-err" role="alert">The board’s approvals couldn’t load just now. '
                            'Please try again in a moment.</p>', tab="board", who=me), 503)
    return _page(render_page(biz, site, request, me, view))


def _waiting_on(view: Dict[str, Any]) -> int:
    return sum(1 for x in view["waiting"] if not x.get("mine"))


async def _tab(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str):
    """GET /my/board and /my/board/decisions. Anyone on no board goes Home."""
    from member_portal import _page, _SECURE_HEADERS, _shell
    q = request.query_params
    b = q.get("b") or ""
    b = b if _ID.match(b) else ""
    try:
        if sub == DECISIONS:
            view = await asyncio.to_thread(decisions_view, biz, me, (q.get("q") or "").strip(), b)
            return _page(render_decisions(biz, site, me, view, b))
        m = q.get("m") or ""
        view = await asyncio.to_thread(board_view, biz, me, b, m if _ID.match(m) else "")
    except HTTPException as e:
        if e.status_code in (400, 403, 404):
            return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
        logger.warning("board tab: didn't load (%s, business %s)", e.status_code, str(biz.get("id"))[:8])
        return _page(_shell(biz, site, "Board", '<p class="mp-err" role="alert">The board’s pages couldn’t load '
                            'just now. Please try again in a moment.</p>', tab="board", who=me), 503)
    waiting = None
    if shown_here(request, biz):
        try:
            waiting = _waiting_on(await asyncio.to_thread(cml.member_view, biz, me))
        except Exception:  # noqa: BLE001 — the board stands without its approvals row
            waiting = None
    return _page(render_board(biz, site, me, view, waiting))


# ─── POST ────────────────────────────────────────────────────────────

def _go(**q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    qs = urlencode({k: v for k, v in q.items() if v})
    return RedirectResponse(f"{PATH}?{qs}" if qs else PATH, status_code=303, headers=_SECURE_HEADERS)


async def _who(request: Request, rid: str):
    """(church, person) for a board POST, or the redirect to send instead."""
    import member_portal as mp
    from member_portal_church import _signed_in
    if not _ID.match(rid or ""):
        return None, _go()
    if not mp._same_origin(request):
        return None, Response(status_code=403, headers=mp._SECURE_HEADERS)
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return None, _go(r=rid, err="1", msg="In the preview nothing saves." if unavailable == "preview"
                         else "That didn't work. Please try again in a moment.")
    if not me or not shown_here(request, church["business"]):
        return None, RedirectResponse("/my", status_code=303, headers=mp._SECURE_HEADERS)
    import rate_limit
    if not rate_limit.allow_strict("member_action", f"{church['business']['id']}|{me['id']}"):
        return None, _go(r=rid, err="1", msg="That's a lot at once. Wait a moment and try again.")
    return (church, me), None


def _said(e: HTTPException) -> str:
    d = e.detail
    if isinstance(d, dict):
        d = d.get("message")
    return str(d or "That didn't work. Please try again.")[:240]


@router.post(PATH + "/{rid}/code", include_in_schema=False)
async def ask_code(rid: str, request: Request):
    """Email a fresh code for this request to the board member asking."""
    got, out = await _who(request, rid)
    if out is not None:
        return out
    church, me = got
    try:
        sent = await asyncio.to_thread(cml.send_code, church["business"], me, rid)
    except HTTPException as e:
        return _go(r=rid, err="1", msg=_said(e))
    return _go(r=rid, k=sent["code_id"], done="sent")


@router.post(PATH + "/{rid}/approve", include_in_schema=False)
async def approve(rid: str, request: Request):
    """The code they were sent, and with it their yes."""
    got, out = await _who(request, rid)
    if out is not None:
        return out
    church, me = got
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 — an unreadable form is a form with nothing in it
        form = {}
    k = str(form.get("k") or "")
    try:
        done = await asyncio.to_thread(cml.confirm_code, church["business"], me, rid, k, str(form.get("code") or ""))
    except HTTPException as e:
        keep = k if e.status_code == 400 and "isn't right" in _said(e) else ""
        return _go(r=rid, k=keep, err="1", msg=_said(e))
    if done.get("approved"):
        return _go(r=rid, done="approved")
    return _go(r=rid, done="yes", w=cml.words(done.get("missing") or []))
