"""
group_lead.py — "My group" on the member app's Lead tab, for a group's
leaders.

From the approved canvas "Church Groups, Together" (board Lead: "You lead
Sisters in the City. Good evening, Tasha."). Everything a leader does for
their group, in one place on their phone:

  * the group this month: how many people and who's asking to join; how
    many came last time and are coming next; how many saw the pinned post
  * Quick: post to the Board, take attendance (on the day), open video,
    the group chat
  * Needs you: asking to join (Say yes / Not now, right here); who hasn't
    been to the last three gatherings (and a way to reach them); that a
    request shared in the group went straight to a pastor (nothing to do)
  * Chief's draft of this week's questions, when one is waiting
  * your last post, and who saw it

A leader of more than one group switches between them. Group leaders get
the Lead tab even without a church role (member_portal). The routes are
GET /my/lead/groups and /my/lead/groups/<group id> (member_portal_lead).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def led_groups(business_id: str, me_id: str) -> Optional[List[Dict[str, Any]]]:
    """The active groups this person leads, by name; None on a failed read."""
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}&role=eq.leader&select=group_id&limit=200")
    if not isinstance(rows, list):
        return None
    ids = sorted({str(r["group_id"]) for r in rows})
    if not ids:
        return []
    gs = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{_q(business_id)}&id=in.({','.join(ids)})&active=eq.true&select=id,name&order=name.asc&limit=200")
    return gs if isinstance(gs, list) else None


def missing_lately(business_id: str, group_id: str, people: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """People absent from each of the group's last three gatherings who
    belonged before the first of them (the office's "missing lately")."""
    ms = sb_clients.sb_get_as_service(
        f"/group_meetings?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&select=id,met_on"
        f"&order=met_on.desc&limit=3")
    if not isinstance(ms, list):
        return None
    if len(ms) < 3:
        return []
    came = sb_clients.sb_get_as_service(
        f"/group_meeting_attendance?business_id=eq.{_q(business_id)}&meeting_id=in.({','.join(str(m['id']) for m in ms)})"
        f"&select=contact_id&limit=5000")
    if not isinstance(came, list):
        return None
    there = {str(c["contact_id"]) for c in came}
    oldest = str(ms[-1]["met_on"])[:10]
    return [p for p in people if p["id"] not in there and str(p.get("joined_on") or "")[:10] <= oldest]


def to_pastor_this_week(business_id: str, group_id: str, now: Optional[datetime] = None) -> Optional[int]:
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=7)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/group_prayers?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&to_pastor=is.true"
        f"&created_at=gte.{_q(since)}&select=id&limit=100")
    return len(rows) if isinstance(rows, list) else None


def view(biz: Dict[str, Any], me: Dict[str, Any], group_id: str = "") -> Optional[Dict[str, Any]]:
    """{'groups': [led groups], 'g': the one shown, 'data': its page data,
    'meet', 'study', 'missing', 'to_pastor'}; {} when they lead no group;
    None on a failed read."""
    import group_gatherings as gg
    import group_study as gy
    import member_portal_groups as mpg
    biz_id, me_id = str(biz["id"]), str(me["id"])
    groups = led_groups(biz_id, me_id)
    if groups is None:
        return None
    if not groups:
        return {}
    pick = next((g for g in groups if str(g["id"]) == group_id), groups[0])
    data = mpg.space(biz_id, str(pick["id"]), me)
    if not data or data.get("role") != "leader":
        return None if data is None else {}
    meet = gg.view(biz, data["group"], me_id, data["people"])
    study = gy.view(biz, data["group"], leader=True)
    missing = missing_lately(biz_id, str(pick["id"]), [p for p in data["people"] if p["id"] != me_id])
    to_pastor = to_pastor_this_week(biz_id, str(pick["id"]))
    if meet is None or study is None or missing is None or to_pastor is None:
        return None
    return {"groups": groups, "g": data["group"], "data": data, "meet": meet, "study": study,
            "missing": missing, "to_pastor": to_pastor}


# ─── the page ────────────────────────────────────────────────────────

GL_CSS = """
.gl-eb{margin:0;font-size:12.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--teal-ink,var(--acc));}
.gl-pick{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px;}
.gl-pick a{display:inline-flex;align-items:center;min-height:38px;padding:0 14px;border-radius:999px;background:var(--s1);color:var(--fg2);
  font-size:14px;font-weight:600;text-decoration:none;}
.gl-pick a[aria-current]{background:var(--teal-deep);color:var(--teal-ink);}
.gl-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 0 6px;}
.gl-stat{border-radius:var(--r-md);background:var(--s1);padding:14px;display:flex;flex-direction:column;gap:4px;min-width:0;}
.gl-stat b{font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1;font-variant-numeric:tabular-nums;}
.gl-stat b span{font-size:15px;color:var(--fg3);font-weight:600;}
.gl-stat small{font-size:12.5px;color:var(--fg2);line-height:1.35;}
.gl-stat.first{background:var(--teal-deep);}
.gl-stat.first b{color:var(--teal-ink);}
.gl-quick{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:8px;}
.gl-quick a,.gl-quick button{display:flex;flex-direction:column;align-items:center;gap:8px;padding:14px 6px;border-radius:var(--r-md);background:var(--s1);
  color:var(--fg2);font:inherit;font-size:12.5px;font-weight:600;text-align:center;text-decoration:none;border:0;cursor:pointer;width:100%;}
.gl-quick form{margin:0;display:flex;}
.gl-quick .gs-disc{width:40px;height:40px;}
.gl-need{border-radius:var(--r-lg);background:var(--s1);overflow:hidden;margin-bottom:10px;}
.gl-need-h{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 6px;}
.gl-need-h b{font-size:15.5px;font-weight:660;}
.gl-faces{display:flex;flex-wrap:wrap;gap:8px 12px;padding:6px 16px 4px;}
.gl-face{display:flex;align-items:center;gap:8px;font-size:14.5px;}
.gl-face a{font-size:13.5px;font-weight:600;color:var(--teal-ink,var(--acc));text-decoration:none;}
.gl-note{padding:4px 16px 16px;margin:0;font-size:13.5px;color:var(--fg2);line-height:1.45;}
.gl-draft{padding:0 16px 16px;margin:0;}
.gl-row{display:flex;align-items:center;gap:12px;padding:14px 16px;}
.gl-row .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.gl-row .gs-t b{font-size:15px;font-weight:650;}
.gl-row .gs-t span{font-size:13px;color:var(--fg2);line-height:1.4;}
.gl-post{border-radius:var(--r-lg);background:var(--s1);padding:16px;display:flex;flex-direction:column;gap:6px;}
.gl-post b{font-size:16px;font-weight:660;}
.gl-post p{margin:0;font-size:14px;color:var(--fg2);line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.gl-post small{font-size:12.5px;color:var(--fg3);}
@media (max-width:420px){.gl-stats{grid-template-columns:minmax(0,1fr) minmax(0,1fr);}.gl-stats .gl-stat:last-child{grid-column:1/-1;}}
@media (min-width:1000px){.gl-cols{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:22px;align-items:start;}}
"""


def hello(biz: Dict[str, Any], me: Dict[str, Any], now: Optional[datetime] = None) -> str:
    """"Good evening, <em>Tasha.</em>" on the church's clock (escaped)."""
    from html import escape
    import group_gatherings as gg
    tz = gg.zone(biz)
    hour = (now or datetime.now(timezone.utc)).astimezone(tz).hour if tz else 12
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    first = (me.get("name") or "").strip().split(" ")[0] or "friend"
    return f"Good {part}, <em>{escape(first)}.</em>"


def render_body(biz: Dict[str, Any], me: Dict[str, Any], v: Dict[str, Any], *, ic, esc, face, name) -> str:
    """The "My group" page body (inside the Lead tab's shell)."""
    import group_gatherings as gg
    import group_study as gy
    import member_portal_messaging as mpm
    g, data, meet = v["g"], v["data"], v["meet"]
    gid = str(g["id"])
    me_id = str(me["id"])
    people = data["people"]
    size = len(people)
    reqs = data.get("requests") or []
    base = f"/my/groups/{esc(gid)}"
    parts: List[str] = []
    if len(v["groups"]) > 1:
        parts.append('<nav class="gl-pick" aria-label="Your groups">' + "".join(
            f'<a href="/my/lead/groups/{esc(x["id"])}"{" aria-current=page" if str(x["id"]) == gid else ""}>{esc(x["name"])}</a>'
            for x in v["groups"]) + "</nav>")
    # This month.
    nxt = meet.get("next")
    going = sum(1 for a in (meet.get("rsvps") or {}).values() if a == "going")
    past = meet.get("past") or []
    if past:
        last_day = gg.DAYS[datetime.fromisoformat(str(past[0]["met_on"])[:10]).weekday()]
        came = (f'<b>{past[0]["n"]}</b><small>came {esc(last_day)}' + (f" · {going} going next time" if nxt else "") + "</small>")
    elif nxt:
        came = f'<b>{going}</b><small>going {esc(gg.when_text(g, nxt).split(" · ")[0])}</small>'
    else:
        came = "<b>—</b><small>no gatherings logged yet</small>"
    posts = data.get("posts") or []
    pinned = next((p for p in posts if p.get("pinned") and not p.get("church")), None)
    mine = next((p for p in posts if str(p.get("posted_by") or "") == me_id and not p.get("church")), None)
    shown = pinned or mine
    seen = (f'<b>{shown.get("seen_n", 0)}<span>/{size}</span></b><small>saw your {"pinned " if shown is pinned else ""}post</small>'
            if shown else '<b>—</b><small>no post yet</small>')
    parts.append(f'<div class="gl-stats" aria-label="This month">'
                 f'<div class="gl-stat first"><b>{size}</b><small>{"person" if size == 1 else "people"}'
                 f'{f" · {len(reqs)} asking to join" if reqs else ""}</small></div>'
                 f'<div class="gl-stat">{came}</div><div class="gl-stat">{seen}</div></div>')
    # Quick.
    quick = [f'<a href="{base}/board#post"><span class="gs-disc">{ic("megaphone", 20)}</span><span>Post to the Board</span></a>',
             f'<a href="{base}/meet"><span class="gs-disc coral">{ic("check" if meet.get("today") else "calendar", 20)}</span>'
             f'<span>{"Take attendance" if meet.get("today") else "Gatherings"}</span></a>']
    if data.get("live"):
        quick.append(f'<a href="/my/groups/live/{esc(data["live"]["id"])}"><span class="gs-disc violet">{ic("video", 20)}</span><span>Join the video</span></a>')
    elif data.get("host"):
        quick.append(f'<form method="post" action="/my/groups/live/start"><input type="hidden" name="group_id" value="{esc(gid)}">'
                     f'<input type="hidden" name="mode" value="meeting"><button type="submit"><span class="gs-disc violet">{ic("video", 20)}</span>'
                     f'<span>Open video</span></button></form>')
    if mpm.turned_on(biz) and g.get("chat_on") is not False:
        quick.append(f'<a href="{base}/chat"><span class="gs-disc gold">{ic("chat", 20)}</span><span>Group chat</span></a>')
    else:
        quick.append(f'<a href="{base}/prayer"><span class="gs-disc gold">{ic("hand-heart", 20)}</span><span>Prayer wall</span></a>')
    parts.append(f'<div class="mb-sh"><h2>Quick</h2></div><div class="gl-quick">{"".join(quick)}</div>')
    # Needs you.
    needs: List[str] = []
    if reqs:
        import member_portal_groups as mpg
        needs.append(mpg._requests_block(reqs, g, back=f"/my/lead/groups/{gid}"))
    missing = v.get("missing") or []
    if missing:
        import member_messaging_rules as rules
        talk = mpm.turned_on(biz)
        # A teen can't get a private message from an adult who isn't their parent.
        faces = "".join(
            f'<span class="gl-face">{face(p)}<span>{esc(name(p))}</span>'
            + (f' <a href="/my/messages/to/{esc(p["id"])}">Message</a>' if talk and not rules.is_teen(p) else "") + "</span>"
            for p in missing[:8])
        n = len(missing)
        # Chief drafts a note to each; the leader sends them (group_care).
        adults = sum(1 for p in missing if not rules.is_teen(p))
        draft = (f'<form method="post" action="/my/lead/groups/notes" class="gl-draft"><input type="hidden" name="group_id" value="{esc(gid)}">'
                 f'<button class="gs-btn sm" type="submit">{ic("sparkles", 15)}Draft a note to {"each" if adults > 1 else "them"}</button></form>'
                 if talk and adults else "")
        needs.append(f'<section class="gl-need" aria-labelledby="gl-miss"><div class="gl-need-h"><b id="gl-miss">Haven’t been in a while</b>'
                     f'<span class="gs-n">{n}</span></div><div class="gl-faces">{faces}</div>'
                     f'<p class="gl-note">Missed each of the last three gatherings. A call or a note this week goes a long way.</p>{draft}</section>')
    if v.get("to_pastor"):
        k = v["to_pastor"]
        needs.append(f'<section class="gl-need"><div class="gl-row"><span class="gs-disc">{ic("shield", 20)}</span><span class="gs-t">'
                     f'<b>A pastor has {"one request" if k == 1 else f"{k} requests"}</b>'
                     f'<span>Something shared in your group this week went straight to a pastor. You don’t need to do anything.</span>'
                     f'</span></div></section>')
    parts.append('<div class="mb-sh"><h2>Needs you</h2></div>' + ("".join(needs) or '<p class="gs-empty">Nothing needs you right now.</p>'))
    # Chief: this week's questions, waiting.
    st = v.get("study")
    if st and st.get("study") and not st["study"].get("posted_at"):
        parts.append(gy.render(g, st, leader=True, people=people, next_day=nxt, ic=ic, esc=esc, name=name))
    # Your last post.
    if mine:
        bits = [f"Seen by {mine.get('seen_n', 0)} of {size}"]
        if mine.get("ask_ack"):
            bits.append(f"{mine.get('acked_n', 0)} pressed Got it")
        if mine.get("emailed"):
            bits.append(f"{mine['emailed']} got it by email")
        parts.append(f'<div class="mb-sh"><h2>Your last post</h2><a href="{base}/board">Board</a></div>'
                     f'<a class="gl-post" href="{base}/board" style="text-decoration:none;color:inherit">'
                     f'<b>{esc(mine.get("title") or "Your post")}</b><p>{esc(mine.get("body") or "")}</p>'
                     f'<small>{esc(" · ".join(bits))}</small></a>')
    return "".join(parts)
