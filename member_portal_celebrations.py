"""
member_portal_celebrations.py — celebrations in the member app.

From the approved canvas "Church News & Celebrations" (Hfrz3Y174kbDmJv1G4puVq),
built to look as drawn:

  Home (board 1)   "Celebrating today": who the church celebrates today (a
                   birthday, an anniversary, a milestone), each in a gold
                   ring; tap one, then "Wish Keisha a happy birthday".
                   Above it, once, the church's question: "Want the church to
                   celebrate your birthday?" (when the office asks members),
                   and a spouse's "Celebrate our anniversary?" to say yes to.
  A celebration (board 4)  /my/news/<id> for a celebration: "Happy
                   birthday, Keisha!", quick wishes, your own words, the
                   wishes (comments, checked first), who else is celebrated
                   today, and why you see it.
  Me (board 6)     /my/me/celebrations: my birthday, our anniversary, my
                   milestones, and how it looks. Nothing shows until the
                   member turns it on.

POST (same-origin form, a live session, the per-person limit):
  /my/celebrate/answer        Home's question: yes or no (and the day, when
                              the record has no birthdate)
  /my/celebrate/prefs         Me: birthday, milestones, the day
  /my/celebrate/anniversary   Me: our anniversary with a spouse in the
                              household (my yes; theirs comes next)
  /my/celebrate/anniversary/answer   the spouse says yes, or not
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import celebrations as cel
import sb_clients

logger = logging.getLogger("member_portal_celebrations")
router = APIRouter(tags=["member-portal"])

UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DONE = {
    "cel_yes": "Thank you. The church will celebrate your birthday with you.",
    "cel_no": "Got it. Your birthday stays between you and the office.",
    "cel_saved": "Saved.",
    "ann_asked": "Asked. Your anniversary shows once they say yes too.",
    "ann_yes": "Thank you. The church will celebrate your anniversary with you.",
    "ann_no": "Got it. Your anniversary won't be shown.",
}
ERRORS = {
    "error": "That didn't save. Please try again.",
    "preview": "This is a preview, so nothing saves.",
    "slow": "That was a lot at once. Wait a moment and try again.",
    "cel_day": "Pick the month and the day.",
    "ann_who": "Choose who you're married to.",
    "ann_date": "Pick the day you were married.",
    "ann_gone": "That isn't there any more.",
}
WISHES = ("Happy birthday!", "Blessings on your new year", "Praying for you this year", "So glad you’re here")
CONGRATS = ("Happy anniversary!", "What a blessing", "Praying for many more years", "Congratulations!")
CHEERS = ("Congratulations!", "So proud of you", "Well done!", "Praying for what’s next")

CEL_CSS = """
.cl-card{border-radius:var(--r-lg);background:var(--gold-deep);padding:16px 16px 14px;display:flex;flex-direction:column;gap:14px;margin:0 0 4px;}
.cl-h{display:flex;align-items:center;justify-content:space-between;gap:10px;}
.cl-h h2{margin:0;font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--gold-ink);}
.cl-h a{font-size:14.5px;font-weight:600;color:var(--gold-ink);text-decoration:none;}
.cl-people{display:flex;gap:6px;}
.cl-p{flex:1 1 0;min-width:0;display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;padding:4px 2px 6px;border:0;background:none;
  font:inherit;color:inherit;cursor:pointer;border-radius:16px;}
.cl-p[aria-pressed=true]{background:rgba(127,127,127,.16);}
.cl-ring{position:relative;width:66px;height:66px;border-radius:50%;padding:3px;box-shadow:inset 0 0 0 2.5px var(--gold);flex:none;}
.cl-ring .nw-av,.cl-ring .cl-pair{width:60px;height:60px;font-size:19px;}
.cl-pair{display:flex;border-radius:50%;overflow:hidden;}
.cl-pair .nw-av{width:30px !important;height:60px;border-radius:0;font-size:13px;}
.cl-why{position:absolute;right:-4px;bottom:-4px;width:26px;height:26px;border-radius:50%;background:var(--gold);color:var(--on-gold);
  display:grid;place-items:center;box-shadow:0 0 0 2.5px var(--gold-deep);}
.cl-why .mb-ic{width:14px;height:14px;}
.cl-nm{font-size:13.5px;font-weight:650;line-height:1.2;}
.cl-wh{font-size:12px;color:var(--fg2);line-height:1.25;}
.cl-go{display:flex;align-items:center;justify-content:center;width:100%;min-height:48px;border-radius:16px;background:var(--gold);color:var(--on-gold);
  font-size:15.5px;font-weight:600;text-decoration:none;border:0;font-family:inherit;cursor:pointer;}
.cl-ask{border-radius:var(--r-lg);background:var(--gold-deep);padding:16px;display:flex;flex-direction:column;gap:12px;margin:0 0 4px;}
.cl-ask h2{margin:0;font-size:18px;font-weight:700;letter-spacing:-.02em;line-height:1.25;}
.cl-ask p{margin:0;font-size:14px;color:var(--fg2);line-height:1.45;}
.cl-ask form{margin:0;display:flex;flex-direction:column;gap:10px;}
.cl-day{display:flex;gap:8px;}
.cl-day select{flex:1;min-height:44px;border-radius:12px;border:0;background:var(--bg);color:var(--fg);font:inherit;font-size:16px;padding:0 12px;}
.cl-acts{display:flex;gap:8px;flex-wrap:wrap;}
.cl-btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 18px;border-radius:999px;border:0;font:inherit;
  font-size:15px;font-weight:600;cursor:pointer;background:var(--gold);color:var(--on-gold);}
.cl-btn.soft{background:rgba(127,127,127,.18);color:var(--fg);}
.cl-hero{border-radius:var(--r-lg);background:var(--gold-deep);padding:26px 18px 20px;display:flex;flex-direction:column;align-items:center;gap:10px;text-align:center;margin-top:6px;}
.cl-hero .cl-ring{width:112px;height:112px;padding:5px;box-shadow:inset 0 0 0 3px var(--gold);}
.cl-hero .cl-ring .nw-av,.cl-hero .cl-ring .cl-pair{width:102px;height:102px;font-size:32px;}
.cl-hero .cl-pair .nw-av{width:51px !important;height:102px;font-size:22px;}
.cl-hero .cl-why{width:36px;height:36px;right:0;bottom:0;box-shadow:0 0 0 3px var(--gold-deep);}
.cl-hero .cl-why .mb-ic{width:18px;height:18px;}
.cl-hero h1{margin:6px 0 0;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-size:36px;letter-spacing:-.02em;line-height:1.05;}
.cl-hero h1 em{color:var(--gold-ink);}
.cl-hero p{margin:0;font-size:14.5px;color:var(--fg2);line-height:1.45;max-width:30ch;}
.cl-hero p.cl-said{max-width:34ch;font-size:15px;color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;}
.cl-pics{margin-top:12px;}
.cl-seen{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--fg2);}
.cl-seen .nw-faces .nw-av{box-shadow:0 0 0 2px var(--gold-deep);}
.cl-lbl{display:block;margin:24px 0 10px;font-size:12.5px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;color:var(--fg3);}
.cl-wish{display:flex;gap:6px;flex-wrap:wrap;}
.cl-wish form{margin:0;display:inline-flex;width:auto;flex:none;}
.cl-wish button{display:inline-flex;align-items:center;min-height:40px;padding:0 12px;border-radius:999px;border:0;background:var(--s1);font:inherit;
  font-size:13.5px;font-weight:600;color:var(--fg);cursor:pointer;white-space:nowrap;}
.cl-say{margin:12px 0 0;display:flex;align-items:center;gap:8px;padding:6px 6px 6px 14px;border-radius:999px;background:var(--s1);}
.cl-say input{flex:1;min-width:0;background:transparent;border:0;outline:none;font:inherit;font-size:15.5px;color:var(--fg);min-height:40px;}
.cl-say input::placeholder{color:var(--fg3);}
.cl-say .nw-send{width:40px;height:40px;}
.cl-also{border-radius:var(--r-md);background:var(--s1);overflow:hidden;}
.cl-row{display:flex;align-items:center;gap:12px;padding:12px 14px;position:relative;color:inherit;text-decoration:none;}
.cl-row+.cl-row::before{content:"";position:absolute;top:0;left:14px;right:0;height:.5px;background:var(--line);}
.cl-row .cl-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
.cl-row .cl-t b{font-size:15.5px;font-weight:620;}
.cl-row .cl-t span{font-size:13px;color:var(--fg2);}
.cl-ring.s{width:46px;height:46px;padding:2px;box-shadow:inset 0 0 0 2px var(--gold);}
.cl-ring.s .nw-av,.cl-ring.s .cl-pair{width:42px;height:42px;font-size:14px;}
.cl-ring.s .cl-pair .nw-av{width:21px !important;height:42px;font-size:10.5px;}
.cl-pill{display:inline-flex;align-items:center;min-height:36px;padding:0 14px;border-radius:999px;background:var(--gold);color:var(--on-gold);
  font-size:14px;font-weight:600;flex:none;}
.cl-guard{display:flex;gap:12px;align-items:flex-start;padding:14px;border-radius:var(--r-md);background:var(--s1);font-size:13.5px;color:var(--fg2);
  line-height:1.45;margin-top:20px;}
.cl-guard .mb-ic{color:var(--gold-ink);flex:none;margin-top:1px;}
.cl-guard b{color:var(--fg);font-weight:650;}
.cl-opts{border-radius:var(--r-md);background:var(--s1);overflow:hidden;}
.cl-opt{display:flex;align-items:center;gap:14px;padding:12px 16px;position:relative;}
.cl-opt+.cl-opt::before{content:"";position:absolute;top:0;left:72px;right:0;height:.5px;background:var(--line);}
.cl-opt .cl-disc{width:40px;height:40px;border-radius:50%;flex:none;display:grid;place-items:center;}
.cl-opt .cl-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.cl-opt .cl-t b{font-size:15.5px;font-weight:620;}
.cl-opt .cl-t small{font-size:13px;color:var(--fg2);line-height:1.35;}
.cl-opt form{margin:0;}
.cl-tg{width:51px;height:31px;border-radius:999px;background:var(--s3);padding:2px;display:flex;flex:none;border:0;cursor:pointer;}
.cl-tg i{width:27px;height:27px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.25);display:block;transition:transform .15s;}
.cl-tg[aria-checked=true]{background:var(--acc-fill);}
.cl-tg[aria-checked=true] i{transform:translateX(20px);}
.cl-more{padding:0 16px 14px 70px;display:flex;flex-direction:column;gap:10px;}
.cl-more form{margin:0;display:flex;flex-direction:column;gap:10px;}
.cl-more select,.cl-more input[type=date]{min-height:44px;border-radius:12px;border:0;background:var(--bg);color:var(--fg);font:inherit;font-size:16px;padding:0 12px;}
.cl-check{display:flex;align-items:center;gap:10px;min-height:40px;font-size:14.5px;}
.cl-check input{width:20px;height:20px;accent-color:var(--acc-fill);}
.cl-pv{border-radius:var(--r-lg);background:var(--gold-deep);padding:14px;display:flex;align-items:center;gap:12px;}
.cl-pv.none{background:var(--s1);}
.cl-pv .cl-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.cl-pv .cl-t b{font-size:15.5px;font-weight:660;}
.cl-pv .cl-t small{font-size:13px;color:var(--fg2);}
"""

_ICONS = {
    "cake": ('<path d="M20 21v-8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8"/><path d="M4 16s.5-1 2-1 2.5 2 4 2 2.5-2 4-2 2.5 2 4 2 2-1 2-1"/>'
             '<path d="M2 21h20"/><path d="M7 8v3M12 8v3M17 8v3"/>'),
    "rings": ('<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5'
              'c0 2.3 1.5 4.05 3 5.5l7 7Z"/>'),
    "award": ('<path d="m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1'
              '-.81-.469l1.514-8.526"/><circle cx="12" cy="8" r="6"/>'),
    "party": ('<path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M11 13c1.93 1.93 2.83 4.17 2 5-.83.83-3.07-.07-5-2-1.93-1.93-2.83-4.17-2-5'
              ' .83-.83 3.07.07 5 2Z"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6'
              '-1.76 1.44L14 10"/><path d="M4 3h.01M22 8h.01M15 2h.01M22 20h.01"/>'),
}


def _ic(name: str, size: int = 18) -> str:
    import member_portal_news as mpn
    if name in _ICONS:
        return (f'<svg class="mb-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>')
    return mpn._ic(name, size)


def _e(v: Any) -> str:
    from member_portal import _e as esc
    return esc(v)


def _first(person: Dict[str, Any]) -> str:
    import member_portal_news as mpn
    return (mpn._person_name(person).split(" ")[0] if person.get("name") else "") or "Someone"


def _ring(p: Dict[str, Any], cls: str = "cl-ring") -> str:
    """The person (or the couple, side by side) in a gold ring, with why."""
    import member_portal_news as mpn
    sub = p.get("sub")
    face = (f'<span class="cl-pair">{mpn._face(p.get("person") or {})}{mpn._face(p.get("partner") or {})}</span>'
            if sub == "anniversary" else mpn._face(p.get("person") or {}))
    why = {"birthday": "cake", "anniversary": "rings"}.get(sub or "", "award")
    share = str((p.get("attach") or {}).get("share") or "") if sub == "good_news" else ""
    if share:
        # What the good news was (member_portal_share's icons).
        import member_portal_share as mps
        if share in mps.ICONS:
            return f'<span class="{cls}">{face}<span class="cl-why" aria-hidden="true">{mps._ic(share, 14)}</span></span>'
    return f'<span class="{cls}">{face}<span class="cl-why" aria-hidden="true">{_ic(why, 14)}</span></span>'


def name_of(p: Dict[str, Any]) -> str:
    """'Keisha', 'Darnell & Lisa', 'Alicia'."""
    if p.get("sub") == "anniversary":
        return f"{_first(p.get('person') or {})} & {_first(p.get('partner') or {})}"
    return _first(p.get("person") or {})


def full_name(p: Dict[str, Any]) -> str:
    import member_portal_news as mpn
    a = mpn._person_name(p.get("person") or {})
    if p.get("sub") == "anniversary":
        b = mpn._person_name(p.get("partner") or {})
        la, lb = a.split(" ")[-1], b.split(" ")[-1]
        if la == lb and " " in a:
            return f"{a.split(' ')[0]} & {b.split(' ')[0]} {la}"
        return f"{a} & {b}"
    return a


def why_of(p: Dict[str, Any]) -> str:
    sub = p.get("sub")
    if sub == "birthday":
        return "Birthday"
    if sub == "anniversary":
        years = (p.get("attach") or {}).get("years")
        return f"{years} years married" if years else "Anniversary"
    t = p.get("title") or ""
    if " finished " in t:
        return "Finished " + t.split(" finished ", 1)[1]
    if sub == "good_news":
        import news_share as ns
        return ns.LABEL.get(str((p.get("attach") or {}).get("share") or ""), "Good news")
    return "A milestone"


def cta_of(p: Dict[str, Any]) -> str:
    sub = p.get("sub")
    if sub == "birthday":
        return f"Wish {name_of(p)} a happy birthday"
    if sub == "anniversary":
        return f"Congratulate {name_of(p).replace(' & ', ' and ')}"
    return f"Cheer {name_of(p)} on"


# ─── Home ────────────────────────────────────────────────────────────

STRIP_JS = """<script>(function(){var c=document.getElementById('cl-today');if(!c)return;
c.addEventListener('click',function(ev){var b=ev.target.closest('.cl-p');if(!b)return;
c.querySelectorAll('.cl-p').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
var go=document.getElementById('cl-go');if(go){go.setAttribute('href',b.getAttribute('data-href'));go.textContent=b.getAttribute('data-cta');}});
})();</script>"""


def home_strip(posts: Optional[List[Dict[str, Any]]]) -> str:
    """'Celebrating today' (board 1): up to three people; nothing at all on
    a day with nobody."""
    if not posts:
        return ""
    shown = posts[:3]
    people = "".join(
        f'<button class="cl-p" type="button" aria-pressed="{"true" if i == 0 else "false"}" '
        f'data-href="/my/news/{_e(p["id"])}" data-cta="{_e(cta_of(p))}">{_ring(p)}'
        f'<span class="cl-nm">{_e(name_of(p))}</span><span class="cl-wh">{_e(why_of(p))}</span></button>'
        for i, p in enumerate(shown))
    first = shown[0]
    return (f'<section class="cl-card" aria-labelledby="cl-today-h" id="cl-today"><div class="cl-h">'
            f'<h2 id="cl-today-h">Celebrating today</h2><a href="/my/news?f=celebrations">All</a></div>'
            f'<div class="cl-people">{people}</div>'
            f'<a class="cl-go" id="cl-go" href="/my/news/{_e(first["id"])}">{_e(cta_of(first))}</a></section>')


def _day_picker(prefix: str = "") -> str:
    months = "".join(f'<option value="{i:02d}">{calendar.month_name[i]}</option>' for i in range(1, 13))
    days = "".join(f'<option value="{i:02d}">{i}</option>' for i in range(1, 32))
    return (f'<div class="cl-day"><label class="mp-sr" for="cl-m{prefix}">Month</label><select id="cl-m{prefix}" name="month" required>'
            f'<option value="">Month</option>{months}</select><label class="mp-sr" for="cl-d{prefix}">Day</label>'
            f'<select id="cl-d{prefix}" name="day" required><option value="">Day</option>{days}</select></div>')


def ask_card(business: Dict[str, Any], me: Dict[str, Any], mine: Optional[Dict[str, Any]],
             asks: Optional[List[Dict[str, Any]]]) -> str:
    """Once: the church's question about my birthday (when the office asks
    members), and a spouse asking me to say yes to our anniversary."""
    import member_portal_news as mpn
    out = []
    for a in asks or []:
        other = a.get("other") or {}
        try:
            wed = date.fromisoformat(str(a["married_on"])[:10])
            when = f"{wed.strftime('%B')} {wed.day}"
        except ValueError:
            when = "your wedding day"
        out.append(
            f'<section class="cl-ask" aria-label="Your anniversary"><h2>{_e(mpn._person_name(other).split(" ")[0] or "Your spouse")} '
            f'would like the church to celebrate your anniversary.</h2><p>{_e(when)}. It shows only when you both say yes, '
            f'and you can change your mind any time in Me.</p>'
            f'<form method="post" action="/my/celebrate/anniversary/answer"><input type="hidden" name="id" value="{_e(a["id"])}">'
            f'<div class="cl-acts"><button class="cl-btn" type="submit" name="yes" value="1">Yes, celebrate it</button>'
            f'<button class="cl-btn soft" type="submit" name="yes" value="0">Not now</button></div></form></section>')
    st = cel.news_settings(business)
    if mine is not None and st["ask_members"] and st["celebrate"] == "ask" and mine.get("birthday") is None and not mine.get("stopped"):
        has_day = bool(me.get("birthdate") or mine.get("birthday_md"))
        picker = "" if has_day else _day_picker()
        out.append(
            f'<section class="cl-ask" aria-labelledby="cl-ask-h"><h2 id="cl-ask-h">Want the church to celebrate your birthday?</h2>'
            f'<p>On your day, the church sees it on Home and News and can wish you well. We show the day, never the year or your age.</p>'
            f'<form method="post" action="/my/celebrate/answer">{picker}<div class="cl-acts">'
            f'<button class="cl-btn" type="submit" name="yes" value="1">Yes, celebrate me</button>'
            f'<button class="cl-btn soft" type="submit" name="yes" value="0" formnovalidate>No thanks</button></div></form></section>')
    return "".join(out)


# ─── a celebration's page (board 4) ─────────────────────────────────


def render_celebration(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], p: Dict[str, Any],
                       today: List[Dict[str, Any]], open_: bool) -> str:
    """The body of /my/news/<id> for a celebration (the page's shell, the
    back link and the flash are member_portal_news's)."""
    import member_portal_news as mpn
    pid = str(p["id"])
    sub = p.get("sub") or "birthday"
    name = name_of(p)
    if sub == "birthday":
        head, line, wishes, verb = (f'Happy birthday, <em>{_e(name)}!</em>',
                                    "Today the whole church gets to celebrate with them.", WISHES, "wished them well")
    elif sub == "anniversary":
        years = (p.get("attach") or {}).get("years")
        head = f'Happy anniversary, <em>{_e(name)}!</em>'
        line = f"{years} years married today." if years else "They're celebrating their marriage today."
        wishes, verb = CONGRATS, "congratulated them"
    else:
        head = f'Congratulations, <em>{_e(name)}!</em>'
        line = p.get("body") or p.get("title") or ""
        wishes, verb = CHEERS, "cheered them on"
    thread = p.get("thread") or []
    n = sum(1 for c in thread if c.get("status") == "shown")
    faces = "".join(mpn._face(c.get("person") or {}) for c in [c for c in thread if c.get("status") == "shown"][-3:])
    seen = (f'<span class="cl-seen"><span class="nw-faces" aria-hidden="true">{faces}</span>'
            f'<span>{n} {"person has" if n == 1 else "people have"} {verb}</span></span>') if n else ""
    shared = sub == "good_news" and p.get("source") == "member"
    # Good news a member shared carries their photo (news_share).
    pics = mpn._attachments(p, {}) if shared else ""
    hero = (f'<section class="cl-hero" aria-label="{_e(full_name(p))}">{_ring(p)}<h1>{head}</h1>'
            f'<p{" class=cl-said" if shared else ""}>{_e(line)}</p>{seen}</section>'
            f'{f"<div class=cl-pics>{pics}</div>" if pics else ""}')
    can_say = open_ and p.get("comments") == "on"
    if can_say:
        chips = "".join(
            f'<form method="post" action="/my/news/comment"><input type="hidden" name="id" value="{_e(pid)}">'
            f'<input type="hidden" name="body" value="{_e(w)}"><button type="submit">{_e(w)}</button></form>' for w in wishes)
        say = (f'<span class="cl-lbl">Send a wish</span><div class="cl-wish" role="group" aria-label="Quick wishes">{chips}</div>'
               f'<form class="cl-say" method="post" action="/my/news/comment"><input type="hidden" name="id" value="{_e(pid)}">'
               f'<label class="mp-sr" for="cl-own">Write your own wish</label>'
               f'<input id="cl-own" type="text" name="body" maxlength="1000" required placeholder="Or write your own…">'
               f'<button class="nw-send" type="submit" aria-label="Send wish">{mpn._ic("plane", 16)}</button></form>')
    else:
        say = (f'<p class="nw-closed">{mpn._ic("lock", 16)}<span>Wishes open when comments do at '
               f'{_e(biz.get("name") or "your church")}. You can still celebrate with a tap above.</span></p>')
    rx = "".join(mpn._rx_button(p, k, f"/my/news/{pid}") for k in ("cheer", "love"))
    rxbar = f'<div class="nw-rxs" role="group" aria-label="React" style="justify-content:center;margin-top:12px">{rx}</div>'
    shown = list(reversed([c for c in thread]))
    cms = "".join(mpn._comment(biz, c, pid, can_take_down=False) for c in shown)
    listing = (f'<div class="nw-ch" id="comments"><h2>Wishes</h2><span>newest first</span></div>'
               f'<div class="nw-cmts" id="nw-cmts">{cms}</div>') if cms else ""
    others = [o for o in today if str(o["id"]) != pid]
    also = ""
    if others:
        rows = "".join(
            f'<a class="cl-row" href="/my/news/{_e(o["id"])}">{_ring(o, "cl-ring s")}<span class="cl-t">'
            f'<b>{_e(full_name(o))}</b><span>{_e(why_of(o))}</span></span>'
            f'<span class="cl-pill">{"Congratulate" if o.get("sub") == "anniversary" else "Wish them well" if o.get("sub") == "birthday" else "Cheer"}</span></a>'
            for o in others)
        also = f'<div class="mb-sh"><h2>Also today</h2></div><div class="cl-also">{rows}</div>'
    who = "They" if sub != "anniversary" else "They both"
    church = _e(biz.get("name") or "the church")
    if shared:
        groups = p.get("for_groups") or []
        reach = (f"the people in {_e(' and '.join(groups))}" if groups and len(groups) <= 2
                 else "the people in their groups" if (p.get("attach") or {}).get("groups")
                 else f"signed-in members of {church}")
        guard = (f'<p class="cl-guard">{mpn._ic("shield", 18)}<span><b>{_e(name)} shared this, and a pastor read it first.</b> '
                 f'Only {reach} see it.</span></p>')
    else:
        guard = (f'<p class="cl-guard">{mpn._ic("shield", 18)}<span><b>{who} said yes to this in the app.</b> '
                 f'{"We show the day, never the year or an age, " if sub == "birthday" else ""}'
                 f'only to signed-in members of {church}. They can turn it off any time.</span></p>')
    return f'{hero}{rxbar}{say}{listing}{also}{guard}'


# ─── Me → Celebrations (board 6) ────────────────────────────────────


def render_me(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], mine: Optional[Dict[str, Any]],
              anns: Optional[List[Dict[str, Any]]], spouses: Optional[List[Dict[str, Any]]],
              names: Dict[str, Dict[str, Any]]) -> Tuple[str, int]:
    import member_portal_news as mpn
    from member_portal import _shell
    head = '<a class="mb-back" href="/my/me">Me</a>'
    if mine is None or anns is None or spouses is None:
        body = f'{head}<p class="mp-err" role="alert">This couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "Celebrations", f"<style>{mpn.NEWS_CSS}{CEL_CSS}</style>{body}", tab="me", who=me), 503
    md = cel._md_of(me.get("birthdate"), mine.get("birthday_md"))
    day_txt = f"{calendar.month_name[md[0]]} {md[1]}" if md else "Add your birthday"
    bday_on = mine.get("birthday") is True
    ms_on = bool(mine.get("milestones"))
    stopped = bool(mine.get("stopped"))

    def toggle(field: str, on: bool, label: str) -> str:
        return (f'<form method="post" action="/my/celebrate/prefs"><input type="hidden" name="{field}" value="{"0" if on else "1"}">'
                f'<button class="cl-tg" type="submit" role="switch" aria-checked="{"true" if on else "false"}" aria-label="{_e(label)}">'
                f'<i></i></button></form>')
    bday_more = ""
    if not md:
        bday_more = (f'<div class="cl-more"><form method="post" action="/my/celebrate/prefs"><input type="hidden" name="birthday" value="1">'
                     f'{_day_picker("-me")}<button class="cl-btn" type="submit">Save my birthday</button></form></div>')
    a = (anns or [None])[0]
    if a:
        other_id = str(a["b_id"] if str(a["a_id"]) == str(me["id"]) else a["a_id"])
        other = names.get(other_id) or {}
        mine_yes = a["a_yes"] if str(a["a_id"]) == str(me["id"]) else a["b_yes"]
        theirs_yes = a["b_yes"] if str(a["a_id"]) == str(me["id"]) else a["a_yes"]
        wed = date.fromisoformat(str(a["married_on"])[:10])
        oname = mpn._person_name(other).split(" ")[0] or "your spouse"
        ann_sub = (f"{wed.strftime('%B')} {wed.day} · {oname} said yes too" if mine_yes and theirs_yes else
                   f"{wed.strftime('%B')} {wed.day} · waiting for {oname} to say yes" if mine_yes else
                   f"{wed.strftime('%B')} {wed.day} · {oname} asked; say yes to celebrate it")
        ann_ctl = (f'<form method="post" action="/my/celebrate/anniversary/answer"><input type="hidden" name="id" value="{_e(a["id"])}">'
                   f'<input type="hidden" name="back" value="me">'
                   f'<input type="hidden" name="yes" value="{"0" if mine_yes else "1"}"><button class="cl-tg" type="submit" role="switch" '
                   f'aria-checked="{"true" if mine_yes else "false"}" aria-label="Celebrate our anniversary"><i></i></button></form>')
        ann_more = ""
    else:
        ann_sub = "Both of you say yes before it shows"
        ann_ctl = ""
        if spouses:
            opts = "".join(f'<option value="{_e(s["id"])}">{_e(mpn._person_name(s))}</option>' for s in spouses)
            ann_more = (f'<div class="cl-more"><form method="post" action="/my/celebrate/anniversary">'
                        f'<label class="mp-sr" for="cl-who">Married to</label><select id="cl-who" name="with" required>'
                        f'<option value="">Married to…</option>{opts}</select>'
                        f'<label class="mp-sr" for="cl-wed">Wedding day</label><input id="cl-wed" type="date" name="married_on" required '
                        f'max="{date.today().isoformat()}">'
                        f'<label class="cl-check"><input type="checkbox" name="show_years" value="1">Show how many years</label>'
                        f'<button class="cl-btn" type="submit">Ask them to say yes</button></form></div>')
        else:
            ann_more = ('<div class="cl-more"><p class="mp-muted" style="margin:0;font-size:13.5px">Your husband or wife isn\'t in your family '
                        'on the church\'s records yet. Ask the church office to add them, then come back.</p></div>')
    parts = []
    if bday_on:
        parts.append("your birthday")
    if a and a.get("a_yes") and a.get("b_yes"):
        parts.append("your anniversary")
    if ms_on:
        parts.append("your milestones")
    any_on = bool(parts) and not stopped
    first = (me.get("name") or "").split(" ")[0] or "you"
    pv_title = (f"Happy birthday, {first}!" if bday_on else "Happy anniversary!" if "your anniversary" in parts
                else f"{first} finished a class") if any_on else "Nothing about you shows on News"
    pv_sub = (f"On News and Home on the day: {', '.join(parts)}" if any_on
              else "Turn one on above and you'll see how it looks")
    import member_photos as ph
    me_face = ph.avatar(me, show=True, cls="nw-av")
    stop_note = (f'<p class="cl-guard">{mpn._ic("shield", 18)}<span>The church office has paused celebrations for you. '
                 f'Talk to them if that should change.</span></p>') if stopped else ""
    body = f"""{head}{mpn_flash(request)}
<div class="nw-head"><p class="nw-eb">You choose</p><h1 class="nw-lt">Let the church <em>celebrate you.</em></h1></div>
<p class="mp-muted" style="margin:8px 0 0">Nothing here shows until you turn it on, and you can change your mind any time.</p>
<span class="cl-lbl">What we celebrate</span>
<div class="cl-opts">
  <div class="cl-opt"><span class="cl-disc" style="background:var(--gold-deep);color:var(--gold-ink)">{_ic("cake", 18)}</span>
    <span class="cl-t"><b>My birthday</b><small>{_e(day_txt)} · we show the day, never the year</small></span>{toggle("birthday", bday_on, "Celebrate my birthday") if md else ""}</div>
  {bday_more}
  <div class="cl-opt"><span class="cl-disc" style="background:var(--acc-deep);color:var(--acc)">{_ic("rings", 18)}</span>
    <span class="cl-t"><b>Our anniversary</b><small>{_e(ann_sub)}</small></span>{ann_ctl}</div>
  {ann_more}
  <div class="cl-opt"><span class="cl-disc" style="background:var(--teal-deep);color:var(--teal-ink)">{_ic("award", 18)}</span>
    <span class="cl-t"><b>My milestones</b><small>Finishing a class. A pastor looks first.</small></span>{toggle("milestones", ms_on, "Celebrate my milestones")}</div>
</div>
<span class="cl-lbl">How it looks</span>
<div class="cl-pv{'' if any_on else ' none'}"><span class="cl-ring s">{me_face}</span><span class="cl-t"><b>{_e(pv_title)}</b><small>{_e(pv_sub)}</small></span></div>
{stop_note}
<p class="nw-foot">{mpn._ic("lock", 16)}<span>Only signed-in members of {_e(biz.get("name") or "the church")} see celebrations.</span></p>"""
    return _shell(biz, site, "Celebrations", f"<style>{mpn.NEWS_CSS}{CEL_CSS}</style>{body}", tab="me", who=me), 200


def mpn_flash(request: Request) -> str:
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


async def serve_me(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any]) -> Tuple[str, int]:
    business_id, me_id = str(biz["id"]), str(me["id"])
    mine, anns, spouses = await asyncio.gather(asyncio.to_thread(cel.prefs, business_id, me_id),
                                               asyncio.to_thread(cel.anniversaries_of, business_id, me_id),
                                               asyncio.to_thread(cel.spouses_for, business_id, me_id))
    ids = []
    for a in anns or []:
        ids += [a["a_id"], a["b_id"]]
    import church_news as cn
    names = await asyncio.to_thread(cn._people, business_id, ids) if ids else {}
    return render_me(biz, site, request, me, mine, anns, spouses, names or {})


def home_asks(business: Dict[str, Any], me: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """(my choices, a spouse's anniversary asks waiting on my yes) for Home."""
    import church_news as cn
    business_id, me_id = str(business["id"]), str(me["id"])
    mine = cel.prefs(business_id, me_id)
    anns = cel.anniversaries_of(business_id, me_id) or []
    asks = []
    for a in anns:
        i_am_a = str(a["a_id"]) == me_id
        if (a["b_yes"] if i_am_a else a["a_yes"]) and not (a["a_yes"] if i_am_a else a["b_yes"]):
            other = str(a["b_id"] if i_am_a else a["a_id"])
            people = cn._people(business_id, [other]) or {}
            asks.append({**a, "other": people.get(other) or {}})
    return mine, asks


# ─── routes ──────────────────────────────────────────────────────────


def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target not in ("/my", "/my/me/celebrations"):
        target = "/my"
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


async def _who(request: Request, back: str):
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return None, None, None, _go(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return None, None, None, mpc._back("/my")
    if not mpc._allowed(church, me):
        return None, None, None, _go(back, err="slow")
    return church, me, await request.form(), None


def _md_from(form) -> Optional[str]:
    m, d = str(form.get("month") or ""), str(form.get("day") or "")
    v = f"{m}-{d}"
    if not cel.MD.match(v):
        return None
    try:
        date(2000, int(m), int(d))
    except ValueError:
        return None
    return v


@router.post("/my/celebrate/answer", include_in_schema=False)
async def answer_route(request: Request):
    church, me, form, stop = await _who(request, "/my")
    if stop:
        return stop
    yes = str(form.get("yes") or "") == "1"
    biz_id = str(church["business"]["id"])
    changes: Dict[str, Any] = {"birthday": yes, "answered_at": cel._now().isoformat()}
    if yes and not me.get("birthdate"):
        mine = await asyncio.to_thread(cel.prefs, biz_id, str(me["id"]))
        if not (mine or {}).get("birthday_md"):
            md = _md_from(form)
            if not md:
                return _go("/my", err="cel_day")
            changes["birthday_md"] = md
    ok = await asyncio.to_thread(cel.save_prefs, biz_id, str(me["id"]), **changes)
    return _go("/my", **({"done": "cel_yes" if yes else "cel_no"} if ok else {"err": "error"}))


@router.post("/my/celebrate/prefs", include_in_schema=False)
async def prefs_route(request: Request):
    church, me, form, stop = await _who(request, "/my/me/celebrations")
    if stop:
        return stop
    changes: Dict[str, Any] = {}
    for field in ("birthday", "milestones"):
        if field in form:
            changes[field] = str(form.get(field)) == "1"
    if "month" in form:
        md = _md_from(form)
        if not md:
            return _go("/my/me/celebrations", err="cel_day")
        if not me.get("birthdate"):
            changes["birthday_md"] = md
    if "birthday" in changes:
        changes["answered_at"] = cel._now().isoformat()
    ok = bool(changes) and await asyncio.to_thread(cel.save_prefs, str(church["business"]["id"]), str(me["id"]), **changes)
    return _go("/my/me/celebrations", **({"done": "cel_saved"} if ok else {"err": "error"}))


@router.post("/my/celebrate/anniversary", include_in_schema=False)
async def anniversary_route(request: Request):
    church, me, form, stop = await _who(request, "/my/me/celebrations")
    if stop:
        return stop
    biz_id = str(church["business"]["id"])
    other = str(form.get("with") or "")
    spouses = await asyncio.to_thread(cel.spouses_for, biz_id, str(me["id"])) or []
    if other not in {str(s["id"]) for s in spouses}:
        return _go("/my/me/celebrations", err="ann_who")
    try:
        wed = date.fromisoformat(str(form.get("married_on") or ""))
    except ValueError:
        return _go("/my/me/celebrations", err="ann_date")
    if wed > date.today() or wed.year < 1901:
        return _go("/my/me/celebrations", err="ann_date")
    row = await asyncio.to_thread(sb_clients.sb_post_as_service, "/member_anniversaries", {
        "business_id": biz_id, "a_id": str(me["id"]), "b_id": other, "married_on": wed.isoformat(),
        "a_yes": True, "b_yes": False, "show_years": str(form.get("show_years") or "") == "1"})
    return _go("/my/me/celebrations", **({"done": "ann_asked"} if isinstance(row, list) and row else {"err": "error"}))


@router.post("/my/celebrate/anniversary/answer", include_in_schema=False)
async def anniversary_answer_route(request: Request):
    church, me, form, stop = await _who(request, "/my")
    if stop:
        return stop
    biz_id = str(church["business"]["id"])
    aid = str(form.get("id") or "")
    back = "/my/me/celebrations" if str(form.get("back") or "") == "me" else "/my"
    if not UUID.match(aid):
        return _go(back, err="ann_gone")
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/member_anniversaries?id=eq.{cel._q(aid)}&business_id=eq.{cel._q(biz_id)}&select=id,a_id,b_id&limit=1")
    if not rows or str(me["id"]) not in (str(rows[0]["a_id"]), str(rows[0]["b_id"])):
        return _go(back, err="ann_gone")
    yes = str(form.get("yes") or "") == "1"
    field = "a_yes" if str(rows[0]["a_id"]) == str(me["id"]) else "b_yes"
    ok = await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                 f"/member_anniversaries?id=eq.{cel._q(aid)}&business_id=eq.{cel._q(biz_id)}", {field: yes})
    return _go(back, **({"done": "ann_yes" if yes else "ann_no"} if ok is not None else {"err": "error"}))
