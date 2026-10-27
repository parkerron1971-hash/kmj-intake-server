"""member_portal_checks.py — Get paid back, in the member app (Serve).

The Church Office Prototypes' "Check requests" tab (artifact
2vGqaUZUynRuiFVKuQEZWo), the phone beside the office: "On her phone, under
Serve, she taps Get paid back, takes a photo of the receipt, picks the
ministry and the amount." Kevin, 2026-10-27: "lets go with your list", and
"make sure that the design is top tier".

  GET  /my/paid-back                  the form, and their own requests (member_portal.serve)
  GET  /my/paid-back/<id>/receipt     the receipt on one of their own requests
  POST /my/paid-back                  multipart: receipt, amount, about, ministry

For someone who serves (church_checks.serves: a Sunday team, a church role,
a group they lead, a kids room, or a church login). The receipt is the
moment: one big tile that opens the phone's camera or its photos, shows the
picture at once, and shrinks it before it's sent (a phone photo is several
megabytes; the treasurer needs a readable page). Without the script the
plain file field still works. Their requests show where each stands, the
reason when one isn't approved, and the check number once it's paid. The
logic and the rules are church_checks.py; switched by CHURCH_CHECKS (owner:
only in the platform owner's own preview, where nothing saves).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import church_checks as cc

logger = logging.getLogger("member_portal_checks")
router = APIRouter(tags=["member-portal"])

_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
PATH = "/my/paid-back"

CK_CSS = """
.ck-lt{margin:4px 0 0;}
.ck-eb{margin:0;font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--h-ink);}
.ck-h{font-size:34px;font-weight:720;letter-spacing:-.035em;line-height:1.05;margin:2px 0 0;}
.ck-h em{font-family:var(--mb-serif);font-style:italic;font-weight:500;letter-spacing:-.02em;color:var(--h-ink);}
.ck-lede{margin:8px 0 0;font-size:15px;line-height:1.45;color:var(--fg2);max-width:34em;}
.ck-form{display:flex;flex-direction:column;gap:18px;margin-top:22px;}
.ck-shot{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;min-height:184px;
  padding:22px 18px;border-radius:var(--r-lg);border:1.5px dashed var(--fg3);background:var(--s1);color:var(--fg);cursor:pointer;
  text-align:center;overflow:hidden;font-weight:400;-webkit-user-select:none;user-select:none;}
.ck-shot:focus-within{outline:2px solid var(--acc);outline-offset:3px;}
.ck-shot:active{transform:scale(.992);}
.ck-shot-ic{width:60px;height:60px;border-radius:50%;display:grid;place-items:center;background:var(--acc-soft);color:var(--acc);}
.ck-shot-ic .mb-ic{width:28px;height:28px;}
.ck-shot b{font-size:18px;font-weight:680;letter-spacing:-.02em;color:var(--fg);}
.ck-shot small{font-size:14px;color:var(--fg2);}
.ck-shot.has{border-style:solid;border-color:transparent;padding:0;min-height:0;background:var(--s2);}
.ck-shot-empty{display:contents;}
.ck-shot.has .ck-shot-empty{display:none;}
.ck-shot-img{display:block;width:100%;max-height:340px;object-fit:contain;background:var(--s2);}
.ck-shot-file{display:flex;align-items:center;gap:12px;width:100%;padding:18px;text-align:left;}
.ck-shot-file .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.ck-shot-file b{font-size:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.ck-again{position:absolute;top:10px;right:10px;display:inline-flex;align-items:center;gap:6px;min-height:36px;padding:0 14px;
  border-radius:999px;background:rgba(0,0,0,.62);color:#fff;font-size:14px;font-weight:600;-webkit-backdrop-filter:blur(10px);
  backdrop-filter:blur(10px);}
.ck-shot-file + .ck-again,.ck-shot.is-file .ck-again{position:static;margin:0 18px 16px auto;background:var(--s3);color:var(--fg);}
.ck-field{display:flex;flex-direction:column;gap:8px;margin:0;font-size:14px;font-weight:600;color:var(--fg2);}
.ck-money{position:relative;display:block;}
.ck-money span{position:absolute;left:16px;top:50%;transform:translateY(-52%);font-size:28px;font-weight:650;color:var(--fg3);pointer-events:none;}
.ck-money .mp-input{min-height:64px;padding-left:38px;font-size:30px;font-weight:700;letter-spacing:-.03em;font-variant-numeric:tabular-nums;}
.ck-picks{margin:0;padding:0;border:0;min-width:0;display:flex;flex-wrap:wrap;gap:8px;}
.ck-picks legend{padding:0;margin:0 0 8px;font-size:14px;font-weight:600;color:var(--fg2);}
.ck-pick{position:relative;display:inline-flex;}
.ck-pick input{position:absolute;inset:0;opacity:0;margin:0;cursor:pointer;}
.ck-pick span{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 16px;border-radius:999px;background:var(--s1);
  color:var(--fg);font-size:15px;font-weight:550;letter-spacing:-.01em;box-shadow:inset 0 0 0 1px var(--line);}
.ck-pick input:checked + span{background:var(--acc-soft);color:var(--acc);font-weight:650;box-shadow:inset 0 0 0 1.5px var(--acc);}
.ck-pick input:focus-visible + span{outline:2px solid var(--acc);outline-offset:2px;}
.ck-form .mp-go[disabled]{opacity:.6;}
.ck-note{display:flex;gap:8px;align-items:flex-start;margin:-4px 0 0;font-size:13.5px;line-height:1.45;color:var(--fg3);}
.ck-note .mb-ic{width:15px;height:15px;margin-top:2px;}
.ck-miss{margin:0;padding:12px 14px;border-radius:14px;background:var(--coral-deep,var(--s1));color:var(--coral-ink,var(--error));
  font-size:14.5px;font-weight:600;}
.ck-sec{margin-top:36px;}
.ck-sh{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:0 0 12px;}
.ck-sh h2{margin:0;font-size:21px;font-weight:700;letter-spacing:-.025em;}
.ck-sh span{font-size:14px;color:var(--fg3);}
.ck-card{border-radius:var(--r-md);background:var(--s1);}
.ck-row{position:relative;display:flex;align-items:flex-start;gap:14px;padding:14px 16px;}
.ck-row + .ck-row::before{content:"";position:absolute;top:0;left:76px;right:0;height:.5px;background:var(--line);}
.ck-thumb{position:relative;width:46px;height:46px;flex:none;border-radius:12px;overflow:hidden;display:grid;place-items:center;
  background:var(--s2);color:var(--fg2);text-decoration:none;}
.ck-thumb img{width:100%;height:100%;object-fit:cover;display:block;}
a.ck-thumb:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.ck-row .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}
.ck-row .top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;}
.ck-row .ti{min-width:0;font-size:16px;font-weight:650;letter-spacing:-.015em;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}
.ck-row .su{font-size:13.5px;color:var(--fg2);line-height:1.4;overflow-wrap:anywhere;}
.ck-why{display:block;margin:4px 0 0;padding:8px 12px;border-radius:12px;background:var(--bg);font-size:14px;line-height:1.4;color:var(--fg);
  overflow-wrap:anywhere;}
.ck-why b{display:block;font-size:12px;font-weight:650;letter-spacing:.04em;text-transform:uppercase;color:var(--fg3);margin-bottom:2px;}
.ck-st{flex:none;display:inline-flex;align-items:center;gap:5px;height:26px;padding:0 10px;border-radius:999px;font-size:12.5px;
  font-weight:650;white-space:nowrap;margin-top:1px;}
.ck-st .mb-ic{width:13px;height:13px;}
.ck-st.new{background:var(--gold-deep,var(--s2));color:var(--gold-ink,var(--fg));}
.ck-st.approved{background:var(--teal-deep,var(--s2));color:var(--teal-ink,var(--fg));}
.ck-st.paid{background:var(--teal-deep,var(--s2));color:var(--teal-ink,var(--fg));}
.ck-st.declined{background:var(--coral-deep,var(--s2));color:var(--coral-ink,var(--fg));}
.ck-empty{margin:0;padding:18px 16px;font-size:15px;line-height:1.45;color:var(--fg2);}
@media (prefers-reduced-motion:reduce){.ck-shot:active{transform:none;}}
"""

# The door on the Serve tab and My serving: one row, as the Safety room's.
DOOR_CSS = """
.ck-door{display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:var(--r-md);background:var(--s1);color:var(--fg);
  text-decoration:none;margin:0 0 14px;min-height:64px;}
.ck-door-ic{width:40px;height:40px;flex:none;border-radius:12px;display:grid;place-items:center;background:var(--acc-soft);color:var(--acc);}
.ck-door span.t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.ck-door b{font-size:16px;font-weight:650;}
.ck-door small{font-size:13.5px;color:var(--fg2);}
.ck-door:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
"""

DONE = {"sent": "Sent. The treasurer will look at it soon; you'll see here when it's approved and paid."}
ERRS = {"preview": "This is a preview, so nothing was saved.", "slow": "One moment, then try that again.",
        "error": "That didn't send. Please try again in a moment.", "big": "That file is too large. Choose one under 15 MB."}

STATUS = {"new": ("Waiting", "new"), "approved": ("Approved", "approved"), "paid": ("Paid", "paid"),
          "declined": ("Not approved", "declined")}


def _e(s: Any) -> str:
    from member_portal import _e as esc
    return esc(s)


def _ic(name: str, size: int = 20) -> str:
    import member_app_ui as ui
    return ui.icon(name, size)


def _usd(c: int) -> str:
    return cc.usd(c)


def _day(iso: Any) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return ""
    return f"{d.strftime('%b')} {d.day}" if d.year == date.today().year else f"{d.strftime('%b')} {d.day}, {d.year}"


def shown_here(request: Request, biz: Dict[str, Any]) -> bool:
    """Whether the switch shows Get paid back to this visit: on, or owner mode
    in the platform owner's own preview."""
    m = cc.mode()
    if m == "on":
        return True
    if m != "owner":
        return False
    from member_portal import _previewing
    try:
        claims = _previewing(request, biz)
    except Exception:  # noqa: BLE001 — no readable preview is no preview
        claims = None
    return bool(claims) and cc.is_platform_owner(claims.get("own"))


def door(request: Request, biz: Dict[str, Any]) -> str:
    """The Serve tab's and My serving's row into Get paid back, where the
    switch shows it. Whoever reaches those pages serves."""
    if not shown_here(request, biz):
        return ""
    return (f'<style>{DOOR_CSS}</style><a class="ck-door" href="{PATH}">'
            f'<span class="ck-door-ic" aria-hidden="true">{_ic("doc", 20)}</span>'
            f'<span class="t"><b>Get paid back</b><small>Send a receipt for what you bought for the church</small></span>'
            f'{_ic("chevron", 18)}</a>')


async def door_async(request: Request, biz: Dict[str, Any]) -> str:
    try:
        return await asyncio.to_thread(door, request, biz)
    except Exception:  # noqa: BLE001 — a page stands without its door
        logger.warning("get paid back: door skipped", exc_info=True)
        return ""


# ─── The page ────────────────────────────────────────────────────────


def _flash(request: Request) -> str:
    q = request.query_params
    err = ERRS.get(str(q.get("err") or "")) or (str(q.get("msg") or "")[:240] if q.get("err") == "said" else "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    done = DONE.get(str(q.get("done") or ""))
    return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else ""


def _thumb(r: Dict[str, Any]) -> str:
    href = f'{PATH}/{_e(r["id"])}/receipt'
    if r.get("receipt") == "image":
        return (f'<a class="ck-thumb" href="{href}" target="_blank" rel="noopener" aria-label="Open the receipt for {_e(_usd(r["amount_cents"]))}">'
                f'<img src="{href}" alt="" loading="lazy" decoding="async"></a>')
    if r.get("receipt") == "pdf":
        return (f'<a class="ck-thumb" href="{href}" target="_blank" rel="noopener" aria-label="Open the receipt for {_e(_usd(r["amount_cents"]))}">'
                f'{_ic("doc", 20)}</a>')
    return f'<span class="ck-thumb" aria-hidden="true">{_ic("doc", 20)}</span>'


def _row(r: Dict[str, Any]) -> str:
    word, tone = STATUS.get(r.get("status") or "", ("Waiting", "new"))
    sub = [x for x in (r.get("about"), _day(r.get("created_at"))) if x]
    if r.get("status") == "paid":
        how = (f'check #{r["check_number"]}' if r.get("paid_how") == "check" and r.get("check_number")
               else "check" if r.get("paid_how") == "check" else "bank transfer")
        sub = [x for x in (r.get("about"), f'Paid by {how}{", " + _day(r.get("paid_on")) if r.get("paid_on") else ""}') if x]
    elif r.get("status") == "approved":
        sub.append("Approved, on its way")
    why = (f'<span class="ck-why"><b>From the treasurer</b>{_e(r["decline_reason"])}</span>'
           if r.get("status") == "declined" and r.get("decline_reason") else "")
    mark = _ic("check", 13) if r.get("status") == "paid" else ""
    return (f'<div class="ck-row">{_thumb(r)}<span class="t"><span class="top">'
            f'<span class="ti">{_e(_usd(r["amount_cents"]))} · {_e(r.get("ministry") or "")}</span>'
            f'<span class="ck-st {tone}">{mark}{_e(word)}</span></span>'
            f'<span class="su">{_e(" · ".join(sub))}</span>{why}</span></div>')


def render_page(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], lines: List[str],
                mine: Optional[List[Dict[str, Any]]], *, lead: bool = False) -> str:
    """`mine` None: their list couldn't be read (the form still works).
    `lead`: they have the Serve tab, so the page sits under it."""
    from member_portal import _shell
    church = (biz.get("name") or "").strip() or "the church"
    picks = "".join(
        f'<label class="ck-pick"><input type="radio" name="ministry" value="{_e(n)}" required'
        f'{" checked" if len(lines) == 1 else ""}><span>{_e(n)}</span></label>' for n in lines)
    if mine is None:
        listing = '<p class="mp-err" role="alert">Your requests couldn\'t load just now. Please try again in a moment.</p>'
    elif mine:
        listing = f'<div class="ck-card">{"".join(_row(r) for r in mine)}</div>'
    else:
        listing = ('<div class="ck-card"><p class="ck-empty">Nothing yet. When you send a receipt, you\'ll see here when '
                   'it\'s approved and when it\'s paid.</p></div>')
    waiting = sum(1 for r in mine or [] if r.get("status") in ("new", "approved"))
    back = ("/my/lead", "Serve") if lead else ("/my", "Home")
    body = f"""<style>{CK_CSS}</style><a class="mb-back" href="{back[0]}">{_e(back[1])}</a>
<div class="ck-lt h-teal"><p class="ck-eb">Serve</p><h1 class="ck-h">Get paid <em>back</em></h1>
<p class="ck-lede">Spent your own money for {_e(church)}? Send the receipt, and the treasurer pays you back.</p></div>
{_flash(request)}
<form class="ck-form" id="ck-form" method="post" action="{PATH}" enctype="multipart/form-data" novalidate>
<label class="ck-shot" id="ck-shot" for="ck-file">
<input class="mp-sr" id="ck-file" type="file" name="receipt" accept="image/*,application/pdf">
<span class="ck-shot-empty"><span class="ck-shot-ic" aria-hidden="true">{_ic("camera", 28)}</span>
<b>Add the receipt</b><small>Take a photo, or choose one you have</small></span>
<img class="ck-shot-img" id="ck-img" alt="Your receipt" hidden>
<span class="ck-shot-file" id="ck-doc" hidden><span class="ck-thumb" aria-hidden="true">{_ic("doc", 20)}</span>
<span class="t"><b id="ck-doc-name">Receipt</b><small>Ready to send</small></span></span>
<span class="ck-again" id="ck-again" hidden>{_ic("camera", 16)}Retake</span>
</label>
<label class="ck-field" for="ck-amount">How much
<span class="ck-money"><span aria-hidden="true">$</span><input class="mp-input" id="ck-amount" name="amount" inputmode="decimal"
autocomplete="off" placeholder="0.00" required maxlength="12" aria-describedby="ck-miss"></span></label>
<label class="ck-field" for="ck-about">What it was for
<input class="mp-input" id="ck-about" name="about" maxlength="200" required autocomplete="off"
placeholder="Craft supplies for Bible school"></label>
<fieldset class="ck-picks"><legend>Ministry</legend>{picks}</fieldset>
<p class="ck-miss" id="ck-miss" role="alert" hidden></p>
<button class="mp-go" id="ck-send" type="submit">Send to the treasurer</button>
<p class="ck-note">{_ic("lock", 15)}<span>Only you and the people who handle {_e(church)}'s money see your receipt.</span></p>
</form>
<section class="ck-sec" aria-labelledby="ck-mine-h"><div class="ck-sh"><h2 id="ck-mine-h">Your requests</h2>
{f'<span>{waiting} on the way</span>' if waiting else ''}</div>{listing}</section>"""
    return _shell(biz, site, "Get paid back", body, tab="lead" if lead else "home", who=me, script=_SCRIPT)


# The receipt tile: the picture at once, a big photo shrunk before it's
# sent, the form checked before it goes, one send.
_SCRIPT = """<script>(function(){
var f=document.getElementById('ck-form');if(!f)return;
var file=document.getElementById('ck-file'),shot=document.getElementById('ck-shot'),img=document.getElementById('ck-img'),
doc=document.getElementById('ck-doc'),docName=document.getElementById('ck-doc-name'),again=document.getElementById('ck-again'),
miss=document.getElementById('ck-miss'),send=document.getElementById('ck-send'),url=null;
function shrink(src,orig){
 if(orig.size<1200000||!window.DataTransfer||!HTMLCanvasElement.prototype.toBlob)return;
 var im=new Image();im.onload=function(){
  var s=Math.min(1,2000/Math.max(im.naturalWidth,im.naturalHeight)),c=document.createElement('canvas');
  c.width=Math.round(im.naturalWidth*s);c.height=Math.round(im.naturalHeight*s);
  c.getContext('2d').drawImage(im,0,0,c.width,c.height);
  c.toBlob(function(b){if(!b||b.size>=orig.size)return;try{var dt=new DataTransfer();
   dt.items.add(new File([b],'receipt.jpg',{type:'image/jpeg'}));file.files=dt.files;}catch(e){}},'image/jpeg',.85);
 };im.src=src;}
file.addEventListener('change',function(){
 var x=file.files&&file.files[0];if(!x)return;
 shot.classList.add('has');again.hidden=false;miss.hidden=true;
 if(/pdf/i.test(x.type)||/\\.pdf$/i.test(x.name)){img.hidden=true;doc.hidden=false;shot.classList.add('is-file');
  docName.textContent=x.name||'Receipt';again.lastChild.textContent='Choose again';return;}
 shot.classList.remove('is-file');doc.hidden=true;again.lastChild.textContent='Retake';
 if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(x);
 img.onerror=function(){img.hidden=true;doc.hidden=false;docName.textContent=x.name||'Photo added';};
 img.src=url;img.hidden=false;shrink(url,x);});
function say(t,el){miss.textContent=t;miss.hidden=false;if(el)el.focus();}
f.addEventListener('submit',function(e){
 if(f.dataset.sending){e.preventDefault();return;}
 var a=(f.amount.value||'').replace(/[$,\\s]/g,'');
 if(!(file.files&&file.files.length)){e.preventDefault();say('Add the receipt first: tap the box at the top.',file);return;}
 if(!/^\\d+(\\.\\d{1,2})?$/.test(a)||!(parseFloat(a)>0)){e.preventDefault();say('Enter how much it was, like 34.50.',f.amount);return;}
 if(!f.about.value.trim()){e.preventDefault();say('Say what it was for.',f.about);return;}
 if(!f.querySelector('input[name=ministry]:checked')){e.preventDefault();
  say('Pick the ministry it was for.',f.querySelector('input[name=ministry]'));return;}
 f.dataset.sending='1';send.disabled=true;send.textContent='Sending\\u2026';});
})();</script>"""


# ─── GET (through member_portal.serve) ───────────────────────────────


async def serve(request: Request, church: Dict[str, Any], me: Dict[str, Any], sub: str, preview: bool = False):
    """`preview`: the owner's preview of this member, which shows the page
    whoever they are (nothing saves there)."""
    from member_portal import _page, _SECURE_HEADERS, _shell
    biz, site = church["business"], church.get("site")
    home = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if not shown_here(request, biz):
        return home
    import member_spaces as msp
    ctx = msp.CURRENT.get() or {}
    if not preview and not await asyncio.to_thread(cc.serves, biz, me):
        return home
    rest = sub[len(PATH):].strip("/")
    if rest:
        rid = rest[:-len("/receipt")] if rest.endswith("/receipt") else ""
        if not _ID.match(rid):
            return Response(status_code=404, headers=_SECURE_HEADERS)
        try:
            got = await asyncio.to_thread(cc.member_receipt, biz, me, rid)
        except HTTPException as e:
            return Response(status_code=404 if e.status_code in (400, 404) else 503, headers=_SECURE_HEADERS)
        got.headers["X-Frame-Options"] = "DENY"
        return got
    lead = bool(ctx.get("lead"))
    try:
        lines = await asyncio.to_thread(cc.member_lines, biz)
    except HTTPException:
        logger.warning("get paid back: the ministries didn't load (business %s)", str(biz.get("id"))[:8])
        return _page(_shell(biz, site, "Get paid back", '<a class="mb-back" href="/my">Home</a>'
                            '<p class="mp-err" role="alert">Get paid back couldn\'t load just now. Please try again in a moment.</p>',
                            tab="home", who=me), 503)
    try:
        mine = await asyncio.to_thread(cc.member_requests, biz, me)
    except HTTPException:
        mine = None
    return _page(render_page(biz, site, request, me, lines, mine, lead=lead))


# ─── POST ────────────────────────────────────────────────────────────


def _go(**q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in q.items() if v})
    return RedirectResponse(f"{PATH}?{qs}" if qs else PATH, status_code=303, headers=_SECURE_HEADERS)


@router.post(PATH, include_in_schema=False)
async def send(request: Request):
    """A volunteer's receipt, the amount, what it was for and the ministry."""
    from member_portal import _SECURE_HEADERS
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _go(err="preview" if unavailable == "preview" else "error")
    home = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if not me:
        return home
    biz = church["business"]
    if not shown_here(request, biz) or not await asyncio.to_thread(cc.serves, biz, me):
        return home
    import rate_limit
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|{me['id']}"):
        return _go(err="slow")
    try:
        form = await request.form()
        upload = form.get("receipt")
        raw = await upload.read(cc.RECEIPT_MAX_BYTES + 1) if hasattr(upload, "read") else b""
    except Exception:  # noqa: BLE001 — an unreadable form is a form with nothing in it
        form, raw = {}, b""
    if len(raw) > cc.RECEIPT_MAX_BYTES:
        return _go(err="big")
    try:
        await asyncio.to_thread(cc.member_ask, biz, me, str(form.get("amount") or ""), str(form.get("about") or ""),
                                str(form.get("ministry") or ""), raw)
    except HTTPException as e:
        if e.status_code == 400:
            return _go(err="said", msg=str(e.detail))
        logger.warning("get paid back: didn't save (%s)", e.status_code)
        return _go(err="error")
    return _go(done="sent")
