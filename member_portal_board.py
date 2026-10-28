"""member_portal_board.py — the board's money yes, in the member app.

Kevin, 2026-10-28: "The 7 office logins are for the office only ...
Everyone else uses the member app, by role, on phone or computer", and
"build step 2 (the board member's yes from the member app, with a fresh code
on every approval) and then step 1 (a Board tab, with approvals inside it)
... build the Board tab for computers from the start".

Elder Ruth is on the Elders board. A $3,000 roof deposit has the
treasurer's yes and the pastor's; it waits on a board member. She gets an
email, opens Love City's member app on her laptop, sees the request with
its receipt and the yeses it has, and presses Approve: we email her a fresh
6-digit code for that request alone, she types it in, and her yes is the
board's. She never uses an office login.

  GET  /my/board/approvals              what waits on the board's yes (?r=<id> opens one)
  GET  /my/board/approvals/<id>/receipt its receipt (a board member it waits on, or who said yes)
  POST /my/board/approvals/<id>/code    email a fresh code for this request
  POST /my/board/approvals/<id>/approve {k: the code's id, code}: the yes

For the church's board members, matched by their person in Board & minutes
(church_board_members.contact_id): the rules are church_money_levels.py.
Switched with check requests (CHURCH_CHECKS: owner shows it only in the
platform owner's own preview, where nothing saves) and the money levels.
A no is the treasurer's, in the office, for now. The Board tab (meetings,
minutes) builds on this page; Home stays as it is.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import church_money_levels as cml

logger = logging.getLogger("member_portal_board")
router = APIRouter(tags=["member-portal"])

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
                      f'{_flash(request, view["email"])}{head}{body}</div>', tab="lead", who=person)
    items = "".join(_item(x, sel) for x in view["waiting"])
    done = "".join(_item(x, sel) for x in view["said"])
    lst = ((f'<p class="bd-sec">Waiting · {len(view["waiting"])}</p>{items}' if items else
            '<div class="bd-empty"><b>Nothing waits on you now.</b><p>What you said yes to is below.</p></div>')
           + (f'<p class="bd-sec">You said yes</p>{done}' if done else ""))
    pane = (_file(chosen, view["email"], code_id, person.get("name") or "") if chosen else
            '<div class="bd-empty"><b>Pick a request</b><p>Its receipt, who has said yes, and your yes show here.</p></div>')
    grid = f'<div class="ld-grid{" has-sel" if chosen else ""}"><div class="ld-list">{lst}</div><div class="ld-file">{pane}</div></div>'
    return _shell(biz, site, "Board approvals", f'<style>{LEAD_CSS}{BOARD_CSS}</style><div class="ld-wide">'
                  f'{_flash(request, view["email"])}{head}{grid}</div>', tab="lead", who=person)


# ─── GET (through member_portal.serve) ───────────────────────────────

async def serve(request: Request, church: Dict[str, Any], me: Dict[str, Any], sub: str, preview: bool = False):
    from member_portal import _page, _SECURE_HEADERS, _shell
    biz, site = church["business"], church.get("site")
    home = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if not shown_here(request, biz):
        return home
    if sub == "/my/board":
        return RedirectResponse(PATH, status_code=303, headers=_SECURE_HEADERS)
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
                            'Please try again in a moment.</p>', tab="lead", who=me), 503)
    return _page(render_page(biz, site, request, me, view))


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
