"""
group_desk.py — the leader's desk, on a computer.

From the approved canvas "Church Groups, Together" (board Desk: "The
leader's desk": the leader's chats on the left, You lead · You're in · For
leaders, each with its last line and unread count; the group's chat in the
middle under its name, its tabs, Open video and Post to the board; the next
gathering, Needs you and the pinned post on the right).

  * My group (/my/lead/groups/<id>, group_lead) from 1240px wide becomes
    three columns. The phone keeps the page it has: the right column IS the
    page, with the next gathering on top (gathering())
  * the left and middle columns arrive after the page, from GET
    /my/lead/groups/<id>/desk (JSON), and only on a wide screen: a phone
    never pays for them, and the chat is marked read only when it's shown
  * left: inbox_rows grouped (You lead → that group's desk; You're in → the
    group's chat; For leaders → the room; Messages → the private chat)
  * middle: the group's chat (member_portal_groups.chat_view + _chat_body),
    its tabs, Open video and Post to the board; what's sent there comes back
    to the desk. Without the script the middle says where the chat is
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

WIDE = 1240


def side(rows: Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]], gid: str, led: List[str], *, esc, ic) -> str:
    """The leader's chats, grouped."""
    if rows is None:
        return '<p class="gd-err">Your chats couldn’t load just now.</p>'
    chats, _ = rows
    led_set = {str(x) for x in led}
    groups: Dict[str, List[str]] = {"You lead": [], "You’re in": [], "For leaders": [], "Messages": []}
    for r in chats:
        g = str(r.get("group_id") or "")
        if r["kind"] == "group" and g in led_set:
            key, href = "You lead", f"/my/lead/groups/{g}"
        elif r["kind"] == "group":
            key, href = "You’re in", f"/my/groups/{g}/chat"
        elif r["kind"] == "leaders":
            key, href = "For leaders", "/my/groups/leaders"
        else:
            key, href = "Messages", f"/my/messages/{r['id']}"
        if key == "Messages" and len(groups[key]) >= 6:
            continue
        now = r["kind"] == "group" and g == gid
        n = int(r.get("unread") or 0)
        badge = f'<span class="gd-n" aria-label="{n} unread">{n}</span>' if n and not now else ""
        mark = ic("users", 16) if r["kind"] != "direct" else esc("".join(w[:1] for w in str(r["title"]).split()[:2]).upper())
        groups[key].append(
            f'<a class="gd-chat{" on" if now else ""}" href="{esc(href)}"{" aria-current=page" if now else ""}>'
            f'<span class="gd-av">{mark}</span><span class="gd-t"><b>{esc(r["title"])}</b><small>{esc(r.get("preview") or "")}</small></span>'
            f'{badge}</a>')
    parts = [f'<p class="gd-h">{esc(k)}</p>{"".join(v)}' for k, v in groups.items() if v]
    more = '<a class="gd-all" href="/my/messages">All messages</a>'
    return "".join(parts) + more if parts else f'<p class="gd-err">No chats yet.</p>{more}'


def middle(biz: Dict[str, Any], request, me: Dict[str, Any], v: Dict[str, Any], cv: Dict[str, Any]) -> Tuple[str, str]:
    """(html, script): the group's chat with its name, tabs and buttons."""
    import group_gatherings as gg
    import member_portal_groups as mpg
    from member_portal import _e
    g, data = v["g"], v["data"]
    gid = str(g["id"])
    people = data["people"]
    mode = g.get("name_display") or "full"
    co = [mpg.display_name(p, mode).split(" ")[0] for p in people if p.get("role") == "leader" and str(p["id"]) != str(me["id"])]
    bits = [f'{len(people)} {"person" if len(people) == 1 else "people"}', gg.regular_text(g),
            "you lead" + (f" with {', '.join(co[:2])}" if co else "")]
    base = f"/my/groups/{_e(gid)}"
    buttons = [f'<a class="gs-btn sm ghost" href="{base}/board#post">{mpg._ic("megaphone", 15)}Post to the board</a>']
    if data.get("live"):
        buttons.insert(0, f'<a class="gs-btn sm" href="/my/groups/live/{_e(data["live"]["id"])}">{mpg._ic("video", 15)}Join the video</a>')
    elif data.get("host"):
        buttons.insert(0, f'<form method="post" action="/my/groups/live/start"><input type="hidden" name="group_id" value="{_e(gid)}">'
                          f'<input type="hidden" name="mode" value="meeting"><button class="gs-btn sm" type="submit">'
                          f'{mpg._ic("video", 15)}Open video</button></form>')
    tabs = "".join(f'<a href="{base}/{t}"{" aria-current=page" if t == "chat" else ""}>{label}</a>'
                   for t, label in (("chat", "Chat"), ("board", "Board"), ("prayer", "Prayer"), ("meet", "Meet"), ("people", "People")))
    head = (f'<header class="gd-top"><div><h2>{_e(g.get("name") or "Your group")}</h2>'
            f'<p>{_e(" · ".join(b for b in bits if b))}</p></div><div class="gd-btns">{"".join(buttons)}</div></header>'
            f'<nav class="gd-tabs" aria-label="{_e(g.get("name") or "Group")}">{tabs}</nav>')
    chat, script = mpg._chat_body(biz, request, me, g, cv, True, here=f"/my/lead/groups/{gid}")
    return head + chat, script


def gathering(g: Dict[str, Any], v: Dict[str, Any], *, esc, ic) -> str:
    """The next gathering, for the right column and the phone alike."""
    import group_gatherings as gg
    meet, people = v.get("meet") or {}, v["data"]["people"]
    nxt = meet.get("next")
    if not nxt:
        return ""
    gid = esc(str(g["id"]))
    ans = list((meet.get("rsvps") or {}).values())
    counts = [("going", ans.count("going")), ("maybe", ans.count("maybe")), ("can’t", ans.count("no")),
              ("no answer", max(0, len(people) - len(ans)))]
    when = gg.when_text(g, nxt)
    clock = when.split(" · ")[1] if " · " in when else ""
    today = bool(meet.get("today"))
    act = (f'<a class="gs-btn sm" href="/my/groups/{gid}/meet">{ic("check", 15)}Take attendance</a>' if today
           else f'<a class="gs-mini" href="/my/groups/{gid}/meet">Meet</a>')
    return (f'<section class="gd-meet" aria-label="Next gathering"><div class="gd-mh"><b>{"Today" if today else esc(gg.DAYS[nxt.weekday()])}</b>{act}</div>'
            f'<div class="gd-mrow"><span class="gd-day"><small>{esc(gg.DAYS[nxt.weekday()][:3].upper())}</small><b>{nxt.day}</b></span>'
            f'<span class="gd-mt"><b>{esc(g.get("meet_address") or g.get("location") or "")}</b><small>{esc(clock)}</small></span></div>'
            f'<div class="gd-counts">{"".join(f"<span><b>{n}</b>{esc(k)}</span>" for k, n in counts)}</div></section>')


def script(gid: str) -> str:
    """On a wide screen, fetch the left and middle columns; never on a phone."""
    import json
    return (f"<script>(function(){{if(!window.matchMedia||!matchMedia('(min-width:{WIDE}px)').matches)return;"
            f"var s=document.getElementById('gd-side'),m=document.getElementById('gd-mid');if(!s||!m)return;"
            f"fetch('/my/lead/groups/'+{json.dumps(gid)}+'/desk'+location.search,{{credentials:'same-origin',headers:{{'Accept':'application/json'}}}})"
            f".then(function(r){{return r.ok?r.json():null;}}).then(function(d){{if(!d)return;s.innerHTML=d.side;m.innerHTML=d.middle;"
            f"if(d.script){{var x=document.createElement('script');x.textContent=d.script;document.body.appendChild(x);}}}})"
            f".catch(function(){{}});}})();</script>")


def shell(gid: str, rail: str, *, esc, ic) -> str:
    """The three columns around My group (the rail)."""
    fallback = (f'<p class="gd-wait">{ic("chat", 18)}<span>The group chat opens here. '
                f'<a href="/my/groups/{esc(gid)}/chat">Open the chat</a></span></p>')
    return (f'<div class="gd"><aside class="gd-side" id="gd-side" aria-label="Your chats"></aside>'
            f'<section class="gd-mid" id="gd-mid" aria-label="Group chat">{fallback}</section>'
            f'<div class="gd-rail">{rail}</div></div>')


DESK_CSS = f"""
.gd-side,.gd-mid{{display:none;}}
.gd-meet{{border-radius:var(--r-md);background:var(--s1);padding:14px;display:flex;flex-direction:column;gap:12px;margin:0 0 16px;}}
.gd-mh{{display:flex;align-items:center;justify-content:space-between;gap:10px;}}
.gd-mh b{{font-size:15px;}}
.gd-mrow{{display:flex;align-items:center;gap:12px;}}
.gd-day{{width:52px;height:56px;border-radius:12px;background:var(--teal-deep);color:var(--teal-ink);display:flex;flex-direction:column;
  align-items:center;justify-content:center;flex:none;}}
.gd-day small{{font-size:11px;font-weight:700;letter-spacing:.08em;}}
.gd-day b{{font-size:22px;line-height:1;}}
.gd-mt{{display:flex;flex-direction:column;gap:2px;min-width:0;}}
.gd-mt b{{font-size:15px;}}
.gd-mt small{{font-size:13px;color:var(--fg2);}}
.gd-counts{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;}}
.gd-counts span{{display:flex;flex-direction:column;align-items:center;gap:2px;padding:8px 4px;border-radius:10px;background:var(--s2);
  font-size:11.5px;color:var(--fg2);text-align:center;}}
.gd-counts b{{font-size:18px;color:var(--fg);font-variant-numeric:tabular-nums;}}
@media (min-width:{WIDE}px){{
  body:has(.gd) .mb-top,body:has(.gd) .mp-shell{{max-width:1500px;}}
  body:has(.gd) .mp-shell.mb-has-nav,body:has(.mb-has-nav .gd) .mb-top{{margin-left:max(92px,calc((100vw - 1500px) / 2));}}
  .gd{{display:grid;grid-template-columns:240px minmax(0,1fr) 320px;gap:22px;align-items:start;}}
  .gd-side,.gd-mid{{display:block;}}
  .gd-side{{position:sticky;top:70px;max-height:calc(100vh - 90px);overflow:auto;display:flex;flex-direction:column;gap:4px;}}
  .gd-mid{{position:sticky;top:70px;display:flex;flex-direction:column;min-width:0;border-radius:var(--r-lg);background:var(--s1);
    padding:16px 16px 0;height:calc(100vh - 90px);}}
  .gd-mid .gc{{display:flex;flex-direction:column;flex:1;min-height:0;}}
  .gd-mid .gc-list{{flex:1;min-height:0;overflow:auto;padding-right:4px;}}
  .gd-mid .gc-compose{{position:static;margin:0 -16px;padding:10px 16px 14px;background:var(--s1);border-radius:0 0 var(--r-lg) var(--r-lg);}}
  .gd-mid .gc-b,.gd-mid .gc-q,.gd-mid .gc-poll,.gd-mid .gc-acts{{background:var(--s2);}}
  .gd-rail .gl-stats{{grid-template-columns:repeat(3,minmax(0,1fr));}}
  .gd-rail .ld-hello{{font-size:26px;}}
}}
.gd-h{{margin:12px 8px 4px;font-size:11.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--fg3);}}
.gd-h:first-child{{margin-top:0;}}
.gd-chat{{display:flex;align-items:center;gap:10px;padding:9px 8px;border-radius:12px;color:var(--fg);text-decoration:none;}}
.gd-chat:hover{{background:var(--s1);}}
.gd-chat.on{{background:var(--teal-deep);}}
.gd-av{{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:var(--s2);color:var(--teal-ink);flex:none;
  font-size:12.5px;font-weight:700;}}
.gd-t{{display:flex;flex-direction:column;min-width:0;flex:1;}}
.gd-t b{{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.gd-t small{{font-size:12.5px;color:var(--fg3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.gd-n{{min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:var(--acc-fill);color:var(--on-acc);font-size:11.5px;
  font-weight:700;display:grid;place-items:center;box-sizing:border-box;}}
.gd-all{{margin:10px 8px 0;font-size:13px;font-weight:600;color:var(--acc);text-decoration:none;}}
.gd-err,.gd-wait{{margin:8px;font-size:13.5px;color:var(--fg3);}}
.gd-wait{{display:flex;gap:8px;align-items:flex-start;}}
.gd-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;}}
.gd-top h2{{margin:0;font-size:22px;letter-spacing:-.02em;}}
.gd-top p{{margin:4px 0 0;font-size:13.5px;color:var(--fg2);}}
.gd-btns{{display:flex;gap:8px;flex-wrap:wrap;}}
.gd-btns form{{margin:0;}}
.gd-btns .gs-btn.ghost{{background:var(--s2);color:var(--fg);}}
.gd-tabs{{display:flex;gap:4px;margin:12px 0 10px;border-bottom:1px solid var(--line);}}
.gd-tabs a{{padding:8px 12px;font-size:14px;font-weight:600;color:var(--fg2);text-decoration:none;border-bottom:2px solid transparent;margin-bottom:-1px;}}
.gd-tabs a[aria-current]{{color:var(--fg);border-bottom-color:var(--teal-ink);}}
"""
