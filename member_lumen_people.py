"""member_lumen_people.py — the new look ("Lumen") for the member app's people
pages: Messages (the inbox and a conversation).

Kevin, 2026-11-18, on the approved "clean Lumen" mock (version 29, accent
level 2): messages "look generic. it should feel like text messages area".
Who sees it is member_lumen.py (MEMBER_LUMEN); the rest of the look is
member_lumen_ui.py. Every page here reads exactly what today's page reads:
these are only its markup, drawn when member_lumen.page() says so.

MESSAGES. The inbox is a list like a phone's: the church's conversation
pinned first on a soft church-colour band ("From your church"), then every
chat newest first (groups, the leaders' room, private chats) with its
unread count; a chat request sits above them with Accept and Ignore. A
conversation is a texting screen: the chat's face and name in the bar at
the top, bubbles (yours on the right in the church's colour), a line for
each day, and the box at the foot with a round send button. Instant send
(member_instant_send) keeps its hooks: the same form, list, box and error
ids, the same bubble markup it draws while a message is on its way.

THE SHEET. CSS_PEOPLE is one more part of the Lumen sheet (member_lumen_ui
.templates(): the hashed, immutable /my/lumen.<hash>.css), every rule under
body.lm. Nothing inline.

Pure functions, no I/O.
"""
from __future__ import annotations

from html import escape
from string import Template
from typing import Any, Optional

# Lumen's own icons for these pages (the rest are member_lumen_ui's).
ICONS = {
    "up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
}


def ic(name: str, size: int = 22) -> str:
    import member_lumen_ui as lm
    if name in ICONS:
        return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
                f'focusable="false">{ICONS[name]}</svg>')
    return lm.ic(name, size)


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def _initials(name: Any) -> str:
    import member_app_ui as ui
    return ui.initials(str(name or ""))


# ─── faces ───────────────────────────────────────────────────────────


def church_mark(name: str, logo: str = "", cls: str = "") -> str:
    """The church in a circle: its logo, else its initials in the serif on
    its colour."""
    inner = f'<img src="{_e(logo)}" alt="">' if logo else _e(_initials(name))
    return f'<span class="lm-av ch{" has-img" if logo else ""}{" " + cls if cls else ""}" aria-hidden="true">{inner}</span>'


def group_mark(name: str, cls: str = "") -> str:
    """A group in a circle: its initials in the serif on soft teal (the
    inbox reads no member's photo for a group)."""
    return f'<span class="lm-av gp{" " + cls if cls else ""}" aria-hidden="true">{_e(_initials(name))}</span>'


def face(photo: str, name: str, cls: str = "") -> str:
    """A person: their photo when the page already has one members may see,
    else their initials."""
    inner = f'<img src="{_e(photo)}" alt="" loading="lazy">' if photo else _e(_initials(name))
    return f'<span class="lm-av{" has-img" if photo else ""}{" " + cls if cls else ""}" aria-hidden="true">{inner}</span>'


def faces(marks: list, cls: str = "") -> str:
    """Two faces overlapping (a group in its conversation's bar): trusted
    markup from member_photos.avatar or face()."""
    return f'<span class="lm-cl{" " + cls if cls else ""}" aria-hidden="true">{"".join(marks[:2])}</span>'


# ─── the inbox ───────────────────────────────────────────────────────


def inbox_row(href: str, av: str, title: str, line: str, when: str, unread: int, *, pin: str = "") -> str:
    """One conversation in the inbox: its face, its name, when, how many are
    unread, and its last line. `pin` is the pinned row's label ("From your
    church"). `av` is trusted markup."""
    n = int(unread or 0)
    chip = f'<span class="lm-uchip" aria-label="{n} new">{n}</span>' if n else ""
    label = f'<span class="lm-pinl">{_e(pin)}</span>' if pin else ""
    cls = "lm-irow" + (" lm-pin" if pin else "") + (" is-new" if n else "")
    return (f'<li><a class="{cls}" href="{_e(href)}">{av}<span class="lm-it">{label}'
            f'<span class="lm-itop"><b>{_e(title)}</b><span class="lm-tr"><time>{_e(when)}</time>{chip}</span></span>'
            f'<span class="lm-prev">{_e(line)}</span></span></a></li>')


def inbox(rows: list) -> str:
    return f'<ul class="lm-inbox" role="list">{"".join(rows)}</ul>' if rows else ""


def request_row(tid: str, av: str, name: str) -> str:
    """Someone asked to chat: their face, "<name> wants to chat." (opens the
    chat, to read what they wrote), Accept and Ignore (messaging's own
    routes: Accept opens the chat, Ignore comes back here)."""
    t = _e(tid)
    return (f'<div class="lm-req">{av}<a class="lm-reqt" href="/my/messages/{t}"><b>{_e(name)}</b> wants to chat.</a>'
            f'<form method="post" action="/my/messages/{t}/accept"><button class="lm-btn sm" type="submit">Accept</button></form>'
            f'<form method="post" action="/my/messages/{t}/decline"><button class="lm-txtbtn" type="submit">Ignore</button></form>'
            f'</div>')


def note(text: str, *, err: bool = False) -> str:
    """A quiet line in the inbox or at the top of a conversation."""
    return f'<p class="lm-cnote{" err" if err else ""}">{_e(text)}</p>'


# ─── a conversation ──────────────────────────────────────────────────


def thead(av: str, title: str, sub: str = "") -> str:
    """The conversation's face and name, in the bar at the top (member_portal
    ._lumen_frame puts it there). `av` is trusted markup."""
    small = f"<small>{_e(sub)}</small>" if sub else ""
    return f'<div class="lm-thead">{av}<span><b>{_e(title)}</b>{small}</span></div>'


def send_button(cls: str = "") -> str:
    """The round send button inside the box."""
    return (f'<button class="lm-send{" " + cls if cls else ""}" type="submit" aria-label="Send">'
            f'{ic("up", 18)}</button>')


# Each day of a chat gets its line ("Today 6:12 PM"), on the phone's own
# clock: a private or group chat isn't read on the church's clock (that would
# be a read of its own). Messages carry data-at; one of yours still on its
# way (instant send) is now. Drawn again after each send (mb:sent).
DAYS_JS = """<script>(function(){var l=document.getElementById(__LIST__),f=document.getElementById(__FORM__);if(!l)return;
function lab(d){var n=new Date(),a=new Date(n.getFullYear(),n.getMonth(),n.getDate()),b=new Date(d.getFullYear(),d.getMonth(),d.getDate()),
k=Math.round((a-b)/864e5),t=d.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
return (k<=0?'Today':k===1?'Yesterday':k<7?d.toLocaleDateString([],{weekday:'long'}):d.toLocaleDateString([],{weekday:'short',month:'short',day:'numeric'}))+' '+t;}
function run(){var last='';Array.prototype.slice.call(l.querySelectorAll('.lm-day')).forEach(function(s){s.parentNode.removeChild(s);});
Array.prototype.slice.call(l.children).forEach(function(li){var a=li.getAttribute('data-at'),
d=a?new Date(a):(/(^|\\s)(mine|mb-mine)(\\s|$)/.test(li.className)?new Date():null);if(!d||isNaN(d.getTime()))return;
var k=d.toDateString();if(k===last)return;last=k;var s=document.createElement('li');s.className='lm-day';
s.setAttribute('role','separator');s.textContent=lab(d);l.insertBefore(s,li);});}
run();if(f)f.addEventListener('mb:sent',run);})();</script>"""


# A conversation opens at its newest message, and stays there as the page
# finishes drawing (fonts, photos, the day lines), unless they've scrolled.
BOTTOM_JS = ("<script>(function(){if(location.hash)return;var y=0;function go(){if(Math.abs(window.scrollY-y)>4)return;"
             "window.scrollTo(0,document.documentElement.scrollHeight);y=window.scrollY;}go();"
             "window.addEventListener('load',go);if(document.fonts&&document.fonts.ready)document.fonts.ready.then(go);"
             "})();</script>")


def days_script(list_id: str, form_id: str) -> str:
    """The chat's day lines, then the scroll to its newest message."""
    import json
    return DAYS_JS.replace("__LIST__", json.dumps(list_id)).replace("__FORM__", json.dumps(form_id)) + BOTTOM_JS


def ink(contact_id: Any) -> str:
    """A steady colour for a person's name over their bubbles (one of four
    inks), the same every time."""
    s = str(contact_id or "")
    return f"lm-k{sum(map(ord, s)) % 4}" if s else "lm-k0"


# ─── the sheet ───────────────────────────────────────────────────────

CSS_PEOPLE = Template("""
/* the people pages (member_lumen_people) */
/* Messages: the inbox, like a phone's */
body.lm .lm-inbox{list-style:none;margin:6px 0 0;padding:0;}
body.lm .lm-irow{display:grid;grid-template-columns:52px minmax(0,1fr);gap:10px;align-items:center;padding:12px 0 12px 20px;color:var(--fg);
  text-decoration:none;border-bottom:1px solid var(--lm-line);}
body.lm .lm-irow.lm-pin{margin:0 -20px;padding:14px 20px 14px 40px;background:var(--lm-tint-6);}
body.lm .lm-av{width:52px;height:52px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:var(--s1);
  color:var(--fg);font:700 16px/1 var(--mb-ui);box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .lm-av img{width:100%;height:100%;object-fit:cover;display:block;}
body.lm .lm-av.has-img{background:var(--s2);box-shadow:none;}
body.lm .lm-av.ch{background:var(--acc-fill);color:var(--on-acc);font:italic 500 19px/1 var(--mb-serif);box-shadow:none;}
body.lm .lm-av.ch.has-img{background:#fff;box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .lm-av.ch.has-img img{object-fit:contain;}
body.lm .lm-av.gp{background:#DCF0EA;color:#0b4a40;font:italic 500 19px/1 var(--mb-serif);box-shadow:none;}
body.lm .lm-it{display:block;min-width:0;}
body.lm .lm-pinl{display:block;margin-bottom:4px;font:700 10px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--acc);}
body.lm .lm-itop{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}
body.lm .lm-itop b{min-width:0;font:650 16px/1.2 var(--mb-ui);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
body.lm .lm-tr{display:inline-flex;align-items:center;gap:8px;flex:none;}
body.lm .lm-tr time{font:500 12.5px/1 var(--mb-ui);color:var(--fg3);font-variant-numeric:tabular-nums;}
body.lm .lm-uchip{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;padding:0 6px;border-radius:10px;
  background:var(--lm-tint-12);color:var(--acc);font:700 11px/1 var(--mb-ui);}
body.lm .lm-prev{display:-webkit-box;margin-top:3px;font:400 14px/1.35 var(--mb-ui);color:var(--fg2);-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;overflow-wrap:anywhere;}
body.lm .is-new .lm-itop b{font-weight:700;}
body.lm .is-new .lm-prev{color:var(--fg);}
body.lm .lm-req{display:flex;align-items:center;gap:12px;padding:14px 0;margin-top:16px;border-top:1px solid var(--lm-line);
  border-bottom:1px solid var(--lm-line);}
body.lm .lm-req .lm-av{width:40px;height:40px;font-size:13px;}
body.lm .lm-reqt{flex:1;min-width:0;font:500 14px/1.35 var(--mb-ui);color:var(--fg);text-decoration:none;}
body.lm .lm-reqt b{font-weight:650;}
body.lm .lm-req+.lm-req{margin-top:0;border-top:0;}
body.lm .lm-gate{flex-wrap:wrap;}
body.lm .lm-gate .lm-reqt{flex:1 1 100%;margin:0;color:var(--fg2);}
body.lm .lm-list .lm-av{width:40px;height:40px;font-size:13px;}
body.lm .lm-cnote{margin:14px 0 0;font:400 13px/1.45 var(--mb-ui);color:var(--fg3);}
body.lm .lm-cnote.err{color:var(--error,var(--fg2));}
body.lm .lm-req+.lm-inbox{margin-top:6px;}
body.lm .lm-irow:focus-visible,body.lm .lm-reqt:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-irow{transition:background-color .2s;}
  body.lm .lm-irow:active{background:var(--lm-tint-6);}
}

/* a conversation: its face and name in the bar, no tab bar, the box at the foot */
body.lm .lm-tbar .mb-top-l{flex:0 0 44px;}
body.lm .lm-tbar .mb-back{width:40px;height:40px;justify-content:center;margin-left:-6px;padding:0;}
body.lm .lm-tbar .mb-top-right{width:44px;}
body.lm .lm-thead{flex:1;min-width:0;display:flex;align-items:center;justify-content:center;gap:10px;}
body.lm .lm-thead>span:last-child{min-width:0;}
body.lm .lm-thead b{display:block;font:650 15px/1.15 var(--mb-ui);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
body.lm .lm-thead small{display:block;margin-top:2px;font:500 11.5px/1.2 var(--mb-ui);color:var(--fg3);}
body.lm .lm-thead .lm-av{width:34px;height:34px;font-size:14px;}
body.lm .lm-cl{position:relative;width:36px;height:36px;flex:none;}
body.lm .lm-cl>*{position:absolute;width:25px;height:25px;border-radius:50%;overflow:hidden;box-shadow:0 0 0 2px var(--bg);font-size:10px;}
body.lm .lm-cl>*:first-child{left:0;top:0;}
body.lm .lm-cl>*:last-child{right:0;bottom:0;}
body.lm .lm-cl>*:only-child{position:static;width:34px;height:34px;box-shadow:none;}
body.lm.lm-thread .mp-shell{display:flex;flex-direction:column;min-height:calc(100vh - 58px - env(safe-area-inset-top,0px));
  min-height:calc(100dvh - 58px - env(safe-area-inset-top,0px));padding-bottom:0;}
body.lm.lm-thread .mp-foot{display:none;}
body.lm.lm-thread .mb-thread,body.lm.lm-thread .lm-gthread{flex:1;display:flex;flex-direction:column;}
body.lm.lm-thread .mb-thread .mb-chat,body.lm.lm-thread .lm-gthread .gc-list{flex:1;}
body.lm .lm-tnotes{display:flex;flex-direction:column;align-items:center;gap:6px;margin:10px 0 2px;text-align:center;}
body.lm .lm-tnotes p,body.lm .lm-tnotes .gc-note{max-width:300px;margin:0;justify-content:center;font:500 12px/1.4 var(--mb-ui);color:var(--fg3);}
body.lm .lm-tnotes .gc-note .mb-ic{flex:none;margin-top:1px;}
body.lm .lm-tnotes form{margin:0;}
body.lm .lm-tnotes .mp-link{border:0;background:none;padding:4px 6px;color:var(--fg3);font:600 12px/1 var(--mb-ui);text-decoration:underline;cursor:pointer;}
body.lm .lm-tnotes .gn{margin:0;}

/* the bubbles: the church's conversation and a private chat (the markup instant send draws too) */
body.lm .mb-thread .mb-chat{max-height:none;min-height:0;margin:0;padding:6px 0 14px;background:none;border-radius:0;overflow:visible;gap:0;}
body.lm .mb-chat .mb-msg{max-width:none;align-self:stretch;display:flex;flex-direction:column;align-items:flex-start;gap:0;margin:3px 0;padding:0;
  background:none;border-radius:0;color:var(--fg3);}
body.lm .mb-chat .mb-msg.mb-mine{align-items:flex-end;background:none;color:var(--fg3);}
body.lm .mb-chat .mb-msg-body{display:block;max-width:76%;padding:10px 14px;border-radius:20px 20px 20px 6px;background:var(--s2);color:var(--fg);
  font:400 15.5px/1.38 var(--mb-ui);white-space:pre-line;overflow-wrap:anywhere;}
body.lm .mb-chat .mb-mine .mb-msg-body{border-radius:20px 20px 6px 20px;background:var(--acc-fill);color:var(--on-acc);}
body.lm .mb-chat .mb-msg-who{margin:9px 0 4px;padding:0 4px;font:650 11.5px/1 var(--mb-ui);color:var(--fg2);}
body.lm .mb-chat .mb-msg-held{margin:4px 4px 0;font:500 11.5px/1.3 var(--mb-ui);font-style:normal;color:var(--lm-coral);}
body.lm .mb-chat .mb-mine .ct-at{display:none;}
body.lm .mb-chat .mb-report-btn{padding:5px 4px 0;font:600 11px/1 var(--mb-ui);color:var(--fg3);text-decoration:none;}
body.lm .mb-chat .mis-st{margin:3px 4px 0;font:600 11px/1 var(--mb-ui);color:var(--fg3);}
body.lm .mb-chat .mb-msg.has-av{margin-left:0;padding-left:38px;position:relative;}
body.lm .mb-chat .mb-msg-av{left:0;bottom:0;}
body.lm .mb-chat .ct-day,body.lm .lm-day{align-self:center;list-style:none;margin:14px 0 8px;padding:0;background:none;text-align:center;
  font:600 11.5px/1 var(--mb-ui);letter-spacing:0;color:var(--fg3);}
body.lm .mb-chat .mb-chat-empty{align-self:center;margin:auto 0;padding:24px 10px;max-width:300px;text-align:center;font:400 14px/1.45 var(--mb-ui);
  color:var(--fg3);background:none;}
/* the church's notes and the office's replies: a card beside the church's mark */
body.lm .mb-chat .mb-msg.lm-them{flex-direction:row;align-items:flex-end;gap:8px;}
body.lm .lm-them>.lm-av{width:30px;height:30px;font-size:12px;flex:none;}
body.lm .lm-note{display:flex;flex-direction:column;max-width:84%;min-width:0;padding:14px 16px;border-radius:20px 20px 20px 6px;background:var(--s1);
  color:var(--fg);}
body.lm .lm-note strong{display:block;margin-bottom:4px;font:650 15px/1.25 var(--mb-ui);letter-spacing:0;}
body.lm .lm-note .lm-nwho{display:block;margin-bottom:4px;font:650 11.5px/1 var(--mb-ui);color:var(--acc);}
body.lm .lm-note .mb-msg-body{max-width:none;padding:0;border-radius:0;background:none;font:400 14.5px/1.45 var(--mb-ui);}
body.lm .lm-note .ct-at{display:block;margin-top:8px;font:500 11.5px/1 var(--mb-ui);color:var(--fg3);opacity:1;}
body.lm .lm-note .ct-open{display:inline-flex;align-items:center;gap:4px;align-self:flex-start;margin-top:10px;padding:7px 12px;border-radius:14px;
  background:var(--bg);color:var(--acc);font:620 13.5px/1 var(--mb-ui);text-decoration:none;box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .lm-note .ct-open .mb-ic{width:14px;height:14px;}

/* a group's chat: names in colour over the bubbles, faces at the foot of a run */
body.lm .lm-gthread .gc-list{gap:0;padding:6px 0 14px;}
body.lm .gc-m{align-items:flex-end;gap:8px;margin:3px 0;}
body.lm .gc-m .gs-av.m{width:30px;height:30px;font-size:11px;}
body.lm .gc-m.lm-c2 .gs-av{visibility:hidden;}
body.lm .gc-m.lm-c1 .gc-who{display:none;}
body.lm .gc-col{max-width:76%;gap:4px;}
body.lm .gc-d{gap:0;}
body.lm .gc-d[open]{gap:6px;}
body.lm .gc-who{margin-top:9px;padding:0 4px;font:650 11.5px/1 var(--mb-ui);color:var(--fg2);}
body.lm .gc-who.lm-k0{color:var(--lm-violet);}
body.lm .gc-who.lm-k1{color:var(--lm-coral);}
body.lm .gc-who.lm-k2{color:var(--lm-teal);}
body.lm .gc-who.lm-k3{color:var(--lm-gold);}
body.lm .gc-b{padding:10px 14px;border-radius:20px 20px 20px 6px;background:var(--s2);color:var(--fg);font:400 15.5px/1.38 var(--mb-ui);}
body.lm .gc-m.mine .gc-b{border-radius:20px 20px 6px 20px;background:var(--acc-fill);color:var(--on-acc);}
body.lm .gc-q{padding:7px 10px;border-radius:12px;background:var(--bg);box-shadow:inset 0 0 0 1px var(--lm-line);font:400 12.5px/1.35 var(--mb-ui);}
body.lm .gc-q b{font:650 11.5px/1.2 var(--mb-ui);}
body.lm .gc-rx{gap:5px;}
body.lm .gc-chip{min-height:24px;padding:0 9px;background:var(--bg);color:var(--fg2);font:650 11px/1 var(--mb-ui);box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .gc-chip.on{background:var(--lm-tint-10);color:var(--acc);box-shadow:inset 0 0 0 1px var(--lm-ring);}
body.lm .gc-pk.on{background:var(--lm-tint-12);color:var(--acc);}
body.lm .gc-held{font:500 11.5px/1.3 var(--mb-ui);color:var(--lm-coral);}
body.lm .gc-col .mis-st{font:600 11px/1 var(--mb-ui);}
body.lm .gc-nc{margin:8px 0;}
body.lm .gc-nc-in{border-radius:20px;background:var(--s1);box-shadow:none;}
body.lm .gc-nc-k{color:var(--lm-teal);}
body.lm .lm-gthread .gs-empty{list-style:none;margin:auto 0;padding:24px 10px;background:none;text-align:center;color:var(--fg3);}

/* the box at the foot: a round +, the field with its send button inside */
body.lm .lm-cmp{position:sticky;bottom:0;z-index:6;display:flex;flex-direction:column;gap:8px;margin:0 -20px;
  padding:10px 12px calc(12px + env(safe-area-inset-bottom,0px));background:var(--bar);border-top:1px solid var(--lm-line);
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);box-shadow:none;}
body.lm .lm-cmp .gc-row,body.lm .lm-cbox{display:flex;align-items:flex-end;gap:8px;}
body.lm .lm-cfield{flex:1;min-width:0;display:flex;align-items:flex-end;min-height:42px;padding:0 5px 0 16px;border-radius:21px;background:var(--s1);}
body.lm .lm-cfield input,body.lm .lm-cfield textarea{flex:1;min-width:0;min-height:42px;height:auto;margin:0;padding:10px 0;border:0;border-radius:0;
  background:none;box-shadow:none;outline:none;color:var(--fg);font:400 16px/1.38 var(--mb-ui);resize:none;}
body.lm .lm-cfield textarea{max-height:160px;}
body.lm .lm-cfield input::placeholder,body.lm .lm-cfield textarea::placeholder{color:var(--fg3);}
body.lm .lm-send{width:32px;height:32px;flex:none;margin:5px 0;padding:0;border:0;border-radius:50%;display:grid;place-items:center;
  background:var(--acc-fill);color:var(--on-acc);cursor:pointer;transition:opacity .2s;}
body.lm .lm-cfield :placeholder-shown+.lm-send{opacity:.35;}
body.lm .lm-cmp .gc-tray>summary{width:42px;height:42px;background:var(--s1);color:var(--fg);}
body.lm .lm-cmp .gc-tray[open]>summary{background:var(--lm-tint-12);color:var(--acc);}
body.lm .lm-cmp .gc-tray-in{background:var(--bg);box-shadow:0 0 0 1px var(--lm-line),0 14px 36px var(--lm-shadow);}
body.lm .lm-cmp .gc-tray-in .gc-disc{background:var(--lm-tint-10);color:var(--acc);}
body.lm .lm-cmp .gc-reply{padding:0 4px;}
body.lm .lm-cmp .gc-ah{padding:0 4px;}
body.lm .lm-cmp .mp-err,body.lm .lm-cmp .mis-err{margin:0 4px;}
body.lm .lm-cdoor{align-items:center;}
body.lm .lm-cfine{margin:0;text-align:center;font:500 11.5px/1.3 var(--mb-ui);color:var(--fg3);}
body.lm .lm-cmp .mb-request{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0;}
body.lm .lm-cmp .mb-request p{flex:1 1 100%;margin:0 4px;font:500 14px/1.35 var(--mb-ui);color:var(--fg);}
body.lm .lm-cmp .lm-cnote{margin:4px;text-align:center;}
body.lm .mis-notice{margin:10px 0;}
body.lm .lm-send:focus-visible,body.lm .lm-cmp .gc-tray>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}

/* Coming up: each occasion with its day in the margin */
body.lm .lm-evs{margin-top:14px;border-top:1px solid var(--lm-line);}
body.lm .lm-evc{display:grid;grid-template-columns:62px minmax(0,1fr);gap:14px;padding:20px 0;border-bottom:1px solid var(--lm-line);}
body.lm .lm-evd small{display:block;font:700 10.5px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--lm-coral);}
body.lm .lm-evd b{display:block;margin-top:4px;font:400 40px/.9 var(--mb-serif);letter-spacing:-.04em;color:var(--fg);}
body.lm .lm-evt{min-width:0;}
body.lm .lm-evt h2{margin:2px 0 4px;font:700 18px/1.25 var(--mb-ui);letter-spacing:-.015em;color:var(--fg);}
body.lm .lm-evp{margin:0;font:400 14px/1.4 var(--mb-ui);color:var(--fg2);}
body.lm .lm-evst{margin:8px 0 0;font:500 13.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-evrow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:14px;}
body.lm .lm-evrow .lm-btn.going .lm-ic{margin-left:-2px;}
body.lm .lm-evt .mpe{margin-top:12px;}
body.lm .lm-serve{margin-top:12px;}
body.lm .lm-serve>summary{display:inline-flex;align-items:center;gap:6px;min-height:32px;list-style:none;cursor:pointer;
  font:650 13.5px/1 var(--mb-ui);color:var(--lm-coral);}
body.lm .lm-serve>summary::-webkit-details-marker{display:none;}
body.lm .lm-serve[open]>summary .lm-ic{transform:rotate(90deg);}
body.lm .lm-serveform{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px;}
body.lm .lm-serveform select{flex:1 1 180px;min-width:0;height:42px;padding:0 12px;border:0;border-radius:12px;background:var(--s1);color:var(--fg);
  font:500 14.5px/1 var(--mb-ui);}
body.lm .lm-serve>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}

/* Prayer: the flame, the request in the serif's italic, who prays with you as two cards */
body.lm .lm-flame i{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;background:var(--lm-tint-10);color:var(--acc);
  font-style:normal;}
body.lm .lm-pform{margin:0;}
body.lm .lm-ta{display:block;width:100%;min-height:170px;margin-top:22px;padding:18px;border:0;border-radius:16px;resize:vertical;background:var(--s1);
  color:var(--fg);font:italic 400 20px/1.45 var(--mb-serif);outline:none;box-sizing:border-box;transition:box-shadow .25s;}
body.lm .lm-ta:focus{box-shadow:inset 0 0 0 1.5px var(--lm-teal);}
body.lm .lm-ta::placeholder{color:var(--fg3);}
body.lm .lm-choice{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0 0;padding:0;border:0;min-width:0;}
body.lm .lm-choice legend{grid-column:1 / -1;float:left;width:100%;margin:8px 0 10px;padding:0;}
body.lm .lm-ch{position:relative;display:block;padding:14px 38px 14px 14px;border-radius:14px;background:var(--s1);color:var(--fg);cursor:pointer;
  transition:box-shadow .25s;}
body.lm .lm-ch input{position:absolute;top:13px;right:12px;width:18px;height:18px;margin:0;accent-color:var(--lm-teal);}
body.lm .lm-ch:has(input:checked){box-shadow:inset 0 0 0 1.5px var(--lm-teal);}
body.lm .lm-ch:has(input:focus-visible){outline:2px solid var(--acc);outline-offset:2px;}
body.lm .lm-ch b{display:block;font:650 14px/1.2 var(--mb-ui);}
body.lm .lm-ch span{display:block;margin-top:5px;font:400 12px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-check{display:flex;align-items:center;gap:10px;margin:18px 0 20px;font:500 14.5px/1.3 var(--mb-ui);color:var(--fg);cursor:pointer;}
body.lm .lm-check input{width:22px;height:22px;margin:0;flex:none;accent-color:var(--acc-fill);}
body.lm .lm-pform .lm-btn.block{margin-top:18px;}
body.lm .lm-check+.lm-btn.block{margin-top:0;}
body.lm .lm-btn.block{display:flex;width:100%;height:56px;border-radius:18px;font-size:16px;}
body.lm .lm-sent{padding:48px 10px 10px;text-align:center;}
body.lm .lm-pring{width:84px;height:84px;margin:0 auto 24px;border-radius:50%;display:grid;place-items:center;color:var(--lm-teal);
  box-shadow:inset 0 0 0 1.5px var(--lm-teal);}
body.lm .lm-sent .lm-disp{margin:0 0 8px;}
body.lm .lm-sent .lm-disp em{color:var(--lm-teal);}
body.lm .lm-sent p{max-width:280px;margin:0 auto;font:400 15px/1.5 var(--mb-ui);color:var(--fg2);}
body.lm .lm-sent .lm-btn{margin-top:26px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-pring{animation:lmring .6s cubic-bezier(.2,1.2,.4,1) both;}
}
@keyframes lmring{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}
""")
