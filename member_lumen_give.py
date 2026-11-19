"""member_lumen_give.py — Give, Watch and Live in the member app's new look
("Lumen").

Kevin, 2026-11-18, on the member app: Give "looks generic and not top tier.
this should be update to be the best", and Live has "no wow factor". He
approved the "clean Lumen" mock (version 29, accent level 2); who sees it is
member_lumen.py (MEMBER_LUMEN), the look member_lumen_ui.py. These pages
port the mock's layout onto the data today's pages read; the mock's church
is made up, so nothing here is.

GIVE (/my/give, online giving on). The give page's own document
(giving_router.render_give_page, unchanged: the same amounts, funds,
frequencies, fee cover, card or bank, embedded Stripe Checkout and the
same script) with the Lumen frame around it and its form in the mock's
layout: "Give to <church>" over the amount in large serif type, the
amounts four across, the church's funds as chips, How often, the fee
cover as a switch, one big Give button, the lock and the Stripe line.
The form keeps every id, class and name the give script reads (a test
checks each one), and the fund chips set the same <select> the script
sends. Under it: Your giving (each gift and the statement, on Me) and
Recurring gifts (/my/gifts). Back from a gift (?thanks=1) the thank-you
opens as the mock's sheet: "Thank you, <first name>." and the same words
today's banner says. The member's name and email ride in the form as
today; with an email on record they fold under "Receipt to ...".
  Before online giving is on (render_give_off): the church's giving photo
  edge to edge, Every gift matters, Give online (the church's own page)
  when it has one, Your giving and In person.

WATCH (/my/sermons): Watch & listen; the next live gathering (or Live now)
on a soft church-colour row; the latest message's art edge to edge with
Watch, Listen (when it has audio) and Share; the series two across; every
message as a row. A series and a message keep today's pages.

LIVE (/my/live, the live room): the video edge to edge with a round Back
and "Live · N here" on it (N is the count the room already reads; left out
when that read failed), the title, I'm here and Prayer, the pinned message,
the chat with names over the words, and the box with the heart and Give
(Give stays with I'm here when the chat is closed). Every id the room's
script reads is kept, so instant send, hearts, the poll, the pin and the
sheets work as they do today. Between services: the church's photo, "No
service is live right now", the next service, the latest message, the
verse and prayer, in the shapes Home uses.

THE SHEET. CSS below is joined into /my/lumen.<hash>.css
(member_lumen_ui.templates); every rule sits under body.lm.

Pure functions, no I/O: every page reads exactly what today's reads.
"""
from __future__ import annotations

from datetime import date
from html import escape
from string import Template
from typing import Any, Callable, Dict, List, Optional


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def _chev() -> str:
    import member_lumen_ui as lm
    return lm.ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")


# ─── Give ────────────────────────────────────────────────────────────


def give_top(church: str, funds: List[str], *, preview: bool = False) -> str:
    """The head of the give screen: "Give to <church>", the amount the giver
    picked in large type (aria-hidden: the Give button says it), and the
    fund and how often under it (GIVE_JS keeps both in step)."""
    import giving_router as gr
    first = gr.fund_label(funds[0]) if len(funds) > 1 else ""
    sub = f"{first} · one time" if first else "One time"
    note = ('<p class="mp-flash mp-ok lm-gvprev" role="status">This is a preview, so Give won\'t charge anything.</p>'
            if preview else "")
    return (f'<header class="lm-gvhead"><h1 class="lm-eyebrow lm-gvto">Give to {_e(church)}</h1>'
            f'<p class="lm-amt is-empty" aria-hidden="true"><sup>$</sup><span data-amt>0</span></p>'
            f'<p class="lm-amtsub" data-amt-sub>{_e(sub)}</p></header>{note}')


def give_form(biz: Dict[str, Any], me: Dict[str, Any], *, year: Optional[int] = None) -> Callable[..., str]:
    """The give form in the new look, for giving_router.render_give_page's
    app["form"]: called with the same arguments as giving_router._give_body
    and drawing the same controls with the same ids, classes and names (the
    give script, unchanged, reads them), in the mock's order."""
    import giving_router as gr
    import member_lumen_ui as lm
    import member_app_ui as ui
    from member_portal import first_name
    funds = gr.configured_funds(gr.giving_settings(biz.get("settings")))
    first = first_name(me.get("name") or "")
    year = year or date.today().year

    def form(preset_btns: str, fund_block: str, pay_note: str, name: str = "", email: str = "",
             pay_block: str = "", ways_block: str = "") -> str:
        n = preset_btns.count('class="gv-amt"')
        chips = ""
        if fund_block:
            chips = ('<p class="lm-lab" id="lm-fund-l">Give to</p>'
                     '<div class="lm-fchips" role="group" aria-labelledby="lm-fund-l">'
                     + "".join(f'<button type="button" class="lm-fchip{" on" if i == 0 else ""}" data-fund="{_e(f)}" '
                               f'aria-pressed="{"true" if i == 0 else "false"}">{_e(gr.fund_label(f))}</button>'
                               for i, f in enumerate(funds))
                     + f'</div><div class="lm-fundsel" hidden>{fund_block}</div>')
        fields = (f'<label class="gv-label" for="gv-nm">Name <span class="lm-opt">(optional)</span></label>'
                  f'<input type="text" id="gv-nm" class="gv-input" autocomplete="name" maxlength="120" value="{_e(name)}">'
                  f'<label class="gv-label" for="gv-em">Email <span class="lm-opt">(for your receipt)</span></label>'
                  f'<input type="email" id="gv-em" class="gv-input" autocomplete="email" maxlength="200" value="{_e(email)}">'
                  f'<p class="lm-whonote">Add your email to receive a receipt and your year-end giving statement.</p>')
        who = (f'<details class="lm-who"><summary><span>Receipt to <b>{_e(email)}</b></span>'
               f'<span class="lm-more">Change</span></summary>{fields}</details>' if email else
               f'<div class="lm-who is-open">{fields}</div>')
        thanks_h = f"Thank you, <em>{_e(first)}.</em>" if first else "Thank <em>you.</em>"
        return (
            '<div id="gv-canceled" class="gv-banner lm-gvnote">No gift was made. You\'re welcome to '
            'try again whenever you\'re ready.</div>'
            '<form class="gv-card lm-gvform" id="gv-form">'
            '<p class="mp-sr" id="lm-amt-l">Amount</p>'
            f'<div class="gv-grid lm-pre" role="group" aria-labelledby="lm-amt-l" style="--n:{n if n <= 4 else 3}">'
            f'{preset_btns}</div>'
            '<label class="mp-sr" for="gv-custom">Other amount</label>'
            '<input type="number" inputmode="decimal" min="1" step="0.01" id="gv-custom" class="gv-input" '
            'placeholder="Other amount ($)">'
            f'{chips}'
            '<p class="lm-lab" id="lm-freq-l">How often</p>'
            '<div class="gv-freq lm-seg" role="group" aria-labelledby="lm-freq-l">'
            '<button type="button" data-freq="once" class="on" aria-pressed="true">One time</button>'
            '<button type="button" data-freq="weekly" aria-pressed="false">Weekly</button>'
            '<button type="button" data-freq="biweekly" aria-pressed="false" aria-label="Every 2 weeks">2 weeks</button>'
            '<button type="button" data-freq="monthly" aria-pressed="false">Monthly</button></div>'
            f'{pay_block}'
            '<label class="gv-cover lm-toggle"><span id="gv-fee-txt">Add a little to cover the processing fee, so your '
            'whole gift arrives</span><input type="checkbox" id="gv-fee" role="switch"></label>'
            f'{who}'
            '<button type="submit" class="gv-give" id="gv-go">Give</button>'
            '<div class="gv-error" id="gv-err" role="alert"></div>'
            f'<p class="gv-note lm-pay">{ui.icon("lock", 15)}<span>{pay_note}</span></p>'
            '</form>'
            '<button type="button" class="gv-back" id="gv-back" hidden>&larr; Change my gift</button>'
            '<div class="gv-pay" id="gv-pay" hidden></div>'
            f'{ways_block}'
            f'<section class="lm-gtotal" aria-labelledby="lm-gt-h"><p class="lm-kicker" id="lm-gt-h">Your giving · {year}</p>'
            f'<a class="lm-gtlink" href="/my/me#mp-giving"><span>Each gift and your <em>statement</em></span>{_chev()}</a>'
            f'<a class="lm-linkrow" href="/my/gifts"><span><b>Recurring gifts</b><span>Change, pause or stop one</span></span>'
            f'{_chev()}</a></section>'
            f'<dialog class="lm-gave" id="lm-gave" aria-labelledby="lm-gave-h"><div class="lm-grab" aria-hidden="true"></div>'
            f'<span class="lm-okring" aria-hidden="true">{lm.ic("check", 30)}</span><h2 id="lm-gave-h" tabindex="-1" autofocus>{thanks_h}</h2>'
            '<div id="gv-thanks" class="gv-banner">Your gift has been received. If you shared your email, a receipt is on '
            'its way, and every gift lands on your year-end statement.</div>'
            '<form method="dialog"><button class="lm-btn lm-block" type="submit">Done</button></form></dialog>')
    return form


# The give screen's own few lines of script (after the page's own give
# script has filled the form from the link): the large amount and the line
# under it follow the giver's picks; a fund chip sets the form's <select>
# (the give script sends that); back from a gift, the thank-you sheet opens
# and Done takes ?thanks off the address.
GIVE_JS = ("<script>(function(){var d=document,sel=d.getElementById('gv-fund'),"
           "chips=[].slice.call(d.querySelectorAll('.lm-fchip')),num=d.querySelector('[data-amt]'),"
           "sub=d.querySelector('[data-amt-sub]'),big=d.querySelector('.lm-amt'),"
           "EVERY={once:'one time',weekly:'every week',biweekly:'every 2 weeks',monthly:'every month'};"
           "function cents(){var on=d.querySelector('.gv-amt.on');if(on)return parseInt(on.getAttribute('data-cents'),10)||0;"
           "var c=d.getElementById('gv-custom');return Math.round(parseFloat((c&&c.value)||'0')*100)||0;}"
           "function sync(){var c=cents(),f=d.querySelector('.gv-freq button.on'),w=EVERY[f?f.getAttribute('data-freq'):'once']||'';"
           "if(num)num.textContent=(c/100).toLocaleString(undefined,{minimumFractionDigits:c%100?2:0,maximumFractionDigits:2});"
           "if(big)big.classList.toggle('is-empty',!c);"
           "var o=sel&&sel.selectedIndex>=0?sel.options[sel.selectedIndex].textContent:'';"
           "if(sub)sub.textContent=o?o+' \\u00b7 '+w:w.charAt(0).toUpperCase()+w.slice(1);"
           "chips.forEach(function(b){var on=!!sel&&b.getAttribute('data-fund')===sel.value;b.classList.toggle('on',on);"
           "b.setAttribute('aria-pressed',on?'true':'false');});}"
           "chips.forEach(function(b){b.addEventListener('click',function(){if(!sel)return;sel.value=b.getAttribute('data-fund');"
           "sel.dispatchEvent(new Event('change',{bubbles:true}));sync();});});"
           "d.addEventListener('click',function(e){if(e.target.closest&&e.target.closest('.gv-amt,.gv-freq button'))sync();});"
           "d.addEventListener('input',function(e){if(e.target&&e.target.id==='gv-custom')sync();});"
           "d.addEventListener('DOMContentLoaded',function(){sync();var t=d.getElementById('gv-thanks'),g=d.getElementById('lm-gave');"
           "if(!t||!g||!t.classList.contains('show'))return;"
           "g.addEventListener('close',function(){try{history.replaceState(null,'',location.pathname);}catch(x){}});"
           "if(g.showModal)g.showModal();else g.setAttribute('open','');});})();</script>")


def give_off(biz: Dict[str, Any], site, me: Dict[str, Any], *, preview: bool = False) -> str:
    """The Give tab before the church takes gifts in the app, in the new
    look: the same words and ways as today's (member_portal.render_give_off)."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_lumen_ui as lm
    from member_portal import _shell
    church = (biz.get("name") or "").strip() or "the church"
    pool = photos.photos(biz, site)
    pic, look = photos.choose(biz, "give", pool, words=("giv", "basket", "offering"))
    online = photos.has_site_page(site, "give")
    lead = ("Give online on our website, or in person at any service." if online
            else "Give in person at any service. Giving in the app is on its way.")
    action = (f'<div class="lm-row2"><a class="lm-btn" href="/give">{ui.icon("give", 18)}Give online</a></div>'
              if online else "")
    hint = (ui.sample_hint("Online giving isn't on yet. Turn it on in Operate, Payments, and this tab takes gifts "
                           "right in the app, with the member's name and email filled in.") if preview else "")
    body = (f'<figure class="lm-bleed lm-hero">{ui.picture(pic, look, "giving", eager=True)}</figure>'
            f'<section class="lm-lead" aria-labelledby="lm-give-h"><p class="lm-eyebrow">Give to {_e(church)}</p>'
            f'<h1 class="lm-disp" id="lm-give-h">Every gift <em>matters</em></h1><p class="lm-meta">{_e(lead)}</p>'
            f'{action}</section>{hint}'
            f'<div class="lm-rooms">'
            f'{lm.row("/my/me#mp-giving", lm.round_icon("doc"), "Your giving", "This year, each gift and your statement", cls="lm-room")}'
            f'<div class="lm-room">{lm.round_icon("heart")}<span class="lm-wt"><b>In person</b>'
            f'<span>During any service at {_e(church)}</span></span></div></div>')
    return _shell(biz, site, "Give", body, tab="give", who=me)


# ─── Watch ───────────────────────────────────────────────────────────


def live_row(live: Optional[Dict[str, Any]], next_occ: Optional[Dict[str, Any]] = None) -> str:
    """Watch's first row, on a soft church-colour band: Live now while the
    church is live, else the next gathering; both open the live page."""
    import member_lumen_ui as lm
    if live:
        kick, title, line, cls = ('<span class="lm-dotlive" aria-hidden="true"></span>Live now',
                                  live.get("title") or "Live now", "Watch and chat with your church", " is-live")
    else:
        import member_portal_church as mpc
        when, title = "", "Live services"
        if next_occ:
            d = mpc._day(next_occ.get("date") or "")
            title = next_occ.get("title") or title
            if d:
                soon = mpc._in_days(d, date.today())
                when = soon if soon in ("Today", "Tomorrow") else f"{d.strftime('%A')} · {soon}"
        kick, line, cls = "Next live", when or "It plays right here", ""
    return (f'<a class="lm-nrow{cls}" href="/my/live"><span class="lm-halo">{lm.ic("live", 22)}</span>'
            f'<span class="lm-wt"><span class="lm-kicker">{kick}</span><b>{_e(title)}</b><span>{_e(line)}</span></span>'
            f'{_chev()}</a>')


def watch(biz: Dict[str, Any], site, who: Dict[str, Any], lib: Optional[Dict[str, Any]], *,
          live: Optional[Dict[str, Any]] = None, next_occ: Optional[Dict[str, Any]] = None,
          bible: str = "kjv") -> str:
    """Watch in the new look: the same library, live and next gathering
    today's Watch reads (member_portal_sermons.render_library)."""
    import member_app_photos as photos
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_ui as lm
    import member_portal_sermons as mps
    from member_portal import _shell, palette_for
    from sermons_public import day_label
    pal = palette_for(biz, site)
    pool = photos.photos(biz, site)
    # Lumen Next: a cinema (member_lumen_motion). The bar says whose it is;
    # the page opens on the next live, then the latest message edge to edge.
    parts = ['<h1 class="mp-sr">Watch &amp; listen</h1>', live_row(live, next_occ)]
    if lib is None:
        parts.append('<p class="mp-err" role="alert" style="margin-top:24px">Messages couldn\'t load just now. '
                     'Please try again in a moment.</p>')
        return _shell(biz, site, "Watch", "".join(parts), tab="watch", who=who)
    if not lib["sermons"]:
        import member_portal_lumen as mlp
        church = (biz.get("name") or "").strip() or "the church"
        parts.append(f'<section class="lm-soon" aria-labelledby="lm-soon-h"><p class="lm-eyebrow">Coming soon</p>'
                     f'<h2 class="lm-disp s" id="lm-soon-h">Messages are on the <em>way</em></h2>'
                     f'<p class="lm-meta">When {_e(church)} posts a message, it shows up here, ready to watch or listen, '
                     f'with the scripture and notes.</p></section>{mlp.verse_page(bible)}')
        return _shell(biz, site, "Watch", "".join(parts), tab="watch", who=who)
    used: set = set()
    titles = mps._titles(lib)
    s = lib["sermons"][0]
    sample = samples.is_sample(s)
    href = f"/my/sermons/{_e(s['id'])}"
    listen = (f'<a class="lm-btn ghost" href="{href}#listen">{ui.icon("headphones", 17)}Listen</a>'
              if (s.get("audio_url") or "").strip() else "")
    meta = " · ".join(x for x in (s.get("speaker") or "", s.get("scripture") or "") if x)
    parts.append(
        f'<section class="lm-feat" aria-labelledby="lm-feat-h">'
        f'{ui.sample_hint(samples.WHERE["sermons"]) if sample else ""}'
        f'<a class="lm-bleed lm-poster" href="{href}" tabindex="-1" aria-hidden="true">{mps._art(lib, s, pal, site, pool, used)}'
        f'{ui.sample_tag() if sample else ""}</a>'
        f'<p class="lm-eyebrow lm-featk"><span class="lm-dot"></span>Latest message · {_e(day_label(s.get("preached_on")))}</p>'
        f'<h2 class="lm-disp m" id="lm-feat-h"><a href="{href}">{lm.italic_last(s.get("title"))}</a></h2>'
        f'{f"<p class=lm-meta>{_e(meta)}</p>" if meta else ""}'
        f'<div class="lm-acts"><a class="lm-btn lm-light" href="{href}">{ui.icon("play", 15)}Watch</a>{listen}'
        f'<button class="lm-btn ghost lm-sq" type="button" data-share="/sermons/{_e(s["id"])}" data-title="{_e(s.get("title"))}" '
        f'aria-label="Share">{ui.icon("share", 18)}</button></div></section>')
    by_series: Dict[str, List[Dict[str, Any]]] = {}
    for x in lib["sermons"]:
        sid = str(x.get("series_id") or "")
        if sid in titles:
            by_series.setdefault(sid, []).append(x)
    order = sorted(by_series, key=lambda k: str(by_series[k][0].get("preached_on")), reverse=True)
    if order:
        # The series as posters on a rail: the art over the name in serif.
        tiles = "".join(
            f'<a class="lm-spost" href="/my/sermons?series={_e(sid)}"><span class="img">'
            f'{mps._art(lib, by_series[sid][0], pal, site, pool, used)}</span><span class="lm-sptx">'
            f'<span class="lm-kicker">{len(by_series[sid])} message{"" if len(by_series[sid]) == 1 else "s"}</span>'
            f'<span class="tt">{lm.italic_last(titles[sid])}</span></span></a>'
            for sid in order)
        parts.append(f'<section aria-labelledby="lm-ser-h">{lm.section("Series", hid="lm-ser-h")}'
                     f'<div class="lm-rail lm-sposts">{tiles}</div></section>')
    rows = "".join(
        f'<a class="lm-lrow" href="/my/sermons/{_e(x["id"])}"><span class="lm-th">{mps._art(lib, x, pal, site, pool)}</span>'
        f'<span class="lm-wt"><b>{_e(x.get("title"))}</b><span>{mps.meta(x)}</span></span>{_chev()}</a>'
        for x in lib["sermons"])
    parts.append(f'<section aria-labelledby="lm-all-h">{lm.section("All messages", hid="lm-all-h")}'
                 f'<div class="lm-list">{rows}</div></section>')
    return _shell(biz, site, "Watch", "".join(parts), tab="watch", who=who, script=mps.SHARE_SCRIPT)


# ─── Live ────────────────────────────────────────────────────────────


def between(biz: Dict[str, Any], site, me: Dict[str, Any], *, flash: str, occasions, library,
            bible: str) -> str:
    """Live between services, in the new look: the same reads as today's
    (member_portal_live.render_live), in Home's shapes."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_lumen_ui as lm
    import member_portal_church as mpc
    import member_portal_lumen as mlp
    from member_portal import _shell, palette_for
    church = (biz.get("name") or "").strip() or "the church"
    pool = photos.photos(biz, site)
    pic, look = photos.choose(biz, "live", pool, words=("live", "stream", "stage", "worship"))
    nxt = ""
    first = (occasions or [None])[0]
    d = mpc._day((first or {}).get("date") or "")
    if first and d:
        soon = mpc._in_days(d, date.today())
        when = soon if soon in ("Today", "Tomorrow") else f"{d.strftime('%A')} · {soon}"
        nxt = (f'<section aria-labelledby="lm-next-h">{lm.section("Next service", "/my/events", "All events", hid="lm-next-h")}'
               f'<div class="lm-list">{lm.row("/my/events", lm.date_box(d), first.get("title") or "", when)}</div></section>')
    used = {pic} if pic else set()
    verse = mlp.verse_page(bible)
    verse = (f'<section aria-labelledby="lm-verse-h">{lm.section("Today", hid="lm-verse-h")}{verse}</section>'
             if verse else "")
    body = (f'<figure class="lm-bleed lm-hero">{ui.picture(pic, look, "worship", eager=True)}</figure>'
            f'<section class="lm-lead" aria-labelledby="lm-off-h"><p class="lm-eyebrow">Live</p>'
            f'<h1 class="lm-disp" id="lm-off-h">Between <em>services</em></h1>'
            f'<p class="lm-meta">No service is live right now. When {_e(church)} goes live, it plays right here, '
            f'with a chat for the church.</p></section>{flash}{nxt}'
            f'{mlp.message_tile(library, palette_for(biz, site), site=site, pool=pool, used=used)}'
            f'{verse}{mlp.prayer_row()}')
    return _shell(biz, site, "Live", body, tab="live", who=me, back=("/my/sermons", "Watch"))


def room_top(here_n: Optional[int]) -> str:
    """On the video: a round Back to Watch, and Live · N here (N is the
    count the room already read; the script keeps it fresh, and a failed
    read leaves it out, never "0 here")."""
    import member_app_ui as ui
    return (f'<div class="lm-lvtop"><a class="lm-lvback" href="/my/sermons" aria-label="Back to Watch">{ui.icon("back", 22)}</a>'
            f'<span class="lm-lvchip"><i class="lm-dotlive" aria-hidden="true"></i>Live'
            f'<span id="lv-herewrap"{" hidden" if here_n is None else ""}>· <b data-here-n>{here_n or 0}</b> here</span>'
            f'</span></div><div class="lm-rxl" id="lm-rxl" aria-hidden="true"></div>')


def room_watch(stack: str, here_n: Optional[int], boxed: bool) -> str:
    """Under the title (Lumen Next): how many are here, beside the faces of
    you once you're here and who spoke last (`stack`, the room's own); and,
    while the box is open, Amen · a heart · Praying (member_lumen_motion's
    ROOM_JS sends the room's own quick reply and heart; without a script
    the two words post like the quick replies)."""
    import member_app_ui as ui
    out = ""
    if here_n is not None:
        out += f'<p class="lm-watching">{stack}<span><b data-here-n>{here_n}</b> here with you</span></p>'
    if boxed:
        heart = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">'
                 '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 '
                 '2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>')
        out += (f'<form class="lm-rxbar" id="lm-rx" method="post" action="/my/live/chat" aria-label="Send a reaction">'
                f'<button class="lm-rxb" type="submit" name="body" value="Amen">Amen</button>'
                f'<button class="lm-rxb h" type="button" data-heart aria-label="Send a heart">{heart}</button>'
                f'<button class="lm-rxb p" type="submit" name="body" value="Praying">{ui.icon("pray", 20)}Praying</button>'
                f'</form><template id="lm-rx-tpl"><span data-k="heart">{heart}</span>'
                f'<span data-k="hands">{ui.icon("pray", 28)}</span></template>')
    return out


def room_give(opens: str) -> str:
    """Give in the room's box (the mock's), opening the same sheet."""
    return f'<a class="lm-lvgive" href="/my/give"{opens}>Give</a>'


# ─── the sheet ───────────────────────────────────────────────────────
# Accent level 2: the church colour on the big Give button, the amount
# picked, the switch, the live row's soft band and Your giving's surface.
CSS = Template("""
/* Give, Watch and Live (member_lumen_give) */
/* Give: the amount in large serif type, chips, a segmented How often, the fee as a switch */
.lm .gv-shell{max-width:600px;padding:0 20px calc(112px + env(safe-area-inset-bottom,0px));}
.lm .lm-gvhead{margin:8px 0 0;text-align:center;}
.lm .lm-gvto{justify-content:center;}
.lm .lm-amt{margin:22px 0 8px;font:300 92px/.9 var(--mb-serif);letter-spacing:-.05em;font-variant-numeric:tabular-nums;color:var(--fg);}
.lm .lm-amt sup{position:relative;top:10px;margin-right:2px;font:400 36px/1 var(--mb-serif);vertical-align:top;color:var(--fg3);}
.lm .lm-amt.is-empty{color:var(--fg3);}
.lm .lm-amtsub{margin:0;font:500 13.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lm-gvprev{margin:18px 0 0;}
.lm .gv-msg{margin:14px auto 0;max-width:330px;text-align:center;font:400 14px/1.5 var(--mb-ui);color:var(--fg2);}
.lm .lm-gvform{margin:0;}
.lm .lm-pre{display:grid;grid-template-columns:repeat(var(--n,4),minmax(0,1fr));gap:8px;margin:24px 0 0;}
.lm .lm-pre .gv-amt{height:50px;min-height:0;padding:0;border:0;border-radius:16px;background:var(--s1);color:var(--fg);
  font:650 16px/1 var(--mb-ui);letter-spacing:0;font-variant-numeric:tabular-nums;transition:background-color .25s,color .25s;}
.lm .lm-pre .gv-amt.on{background:var(--acc-fill);color:var(--on-acc);}
.lm .lm-gvform .gv-input{width:100%;height:50px;min-height:0;margin:8px 0 0;padding:0 16px;border:0;border-radius:14px;background:var(--s1);
  color:var(--fg);font:400 16px/1 var(--mb-ui);box-shadow:none;}
.lm .lm-gvform .gv-input:focus{outline:none;box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm .lm-gvform .gv-input::placeholder{color:var(--fg3);}
.lm .lm-gvform input[type=number]{-moz-appearance:textfield;appearance:textfield;}
.lm .lm-gvform input[type=number]::-webkit-inner-spin-button,.lm .lm-gvform input[type=number]::-webkit-outer-spin-button{-webkit-appearance:none;margin:0;}
.lm .lm-gvform #gv-custom{height:46px;text-align:center;}
.lm .lm-lab,.lm .lm-gvform .gv-label{display:block;margin:26px 0 10px;font:650 11px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg3);}
.lm .lm-opt{text-transform:none;letter-spacing:0;font-weight:400;}
.lm .lm-fchips{display:flex;gap:8px;overflow-x:auto;margin:0 -20px;padding:2px 20px 6px;scrollbar-width:none;}
.lm .lm-fchips::-webkit-scrollbar{display:none;}
.lm .lm-fchip{flex:none;height:38px;padding:0 16px;border:0;border-radius:19px;background:var(--s1);color:var(--fg2);font:650 13.5px/1 var(--mb-ui);
  cursor:pointer;transition:background-color .25s,color .25s;}
.lm .lm-fchip.on{background:var(--fg);color:var(--bg);}
.lm .lm-seg,.lm .lm-gvform .gv-paywith{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);grid-template-columns:none;gap:0;
  margin:0;padding:3px;border:0;border-radius:14px;background:var(--s1);overflow:visible;}
.lm .lm-seg button,.lm .lm-gvform .gv-paywith button{height:36px;min-height:0;padding:0 4px;border:0;border-radius:11px;background:none;
  color:var(--fg2);font:650 13px/1.1 var(--mb-ui);cursor:pointer;transition:background-color .25s,color .25s;}
.lm .lm-seg button.on,.lm .lm-gvform .gv-paywith button.on{background:var(--bg);color:var(--fg);box-shadow:0 1px 3px var(--lm-shadow);}
.lm .lm-gvform .gv-paywith button{height:auto;min-height:36px;padding:6px 6px;}
.lm .lm-toggle{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:0;margin:14px 0 0;padding:18px 0;
  border-top:1px solid var(--lm-line);border-bottom:1px solid var(--lm-line);font:500 14px/1.4 var(--mb-ui);color:var(--fg);cursor:pointer;}
.lm .lm-toggle input{-webkit-appearance:none;appearance:none;position:relative;width:50px;height:30px;flex:none;margin:0;border-radius:15px;
  background:var(--s3);cursor:pointer;transition:background-color .25s;}
.lm .lm-toggle input::after{content:"";position:absolute;top:3px;left:3px;width:24px;height:24px;border-radius:50%;background:#fff;
  box-shadow:0 2px 6px rgba(0,0,0,.25);transition:transform .25s;}
.lm .lm-toggle input:checked{background:var(--acc-fill);}
.lm .lm-toggle input:checked::after{transform:translateX(20px);}
.lm .lm-toggle input:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.lm .lm-who{border-bottom:1px solid var(--lm-line);}
.lm .lm-who summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 0;list-style:none;cursor:pointer;
  font:500 14px/1.35 var(--mb-ui);color:var(--fg2);}
.lm .lm-who summary::-webkit-details-marker{display:none;}
.lm .lm-who summary b{font-weight:650;color:var(--fg);overflow-wrap:anywhere;}
.lm .lm-who[open] summary .lm-more{visibility:hidden;}
.lm .lm-who[open],.lm .lm-who.is-open{padding-bottom:16px;}
.lm .lm-who .gv-label:first-of-type{margin-top:4px;}
.lm .lm-whonote{margin:10px 0 0;font:400 12.5px/1.45 var(--mb-ui);color:var(--fg3);}
.lm .lm-gvform .gv-give{display:block;width:100%;height:56px;min-height:0;margin:22px 0 0;padding:0;border:0;border-radius:18px;
  background:var(--acc-fill);color:var(--on-acc);font:650 16px/1 var(--mb-ui);letter-spacing:-.01em;cursor:pointer;transition:transform .15s ease;}
.lm .lm-gvform .gv-give:active{transform:scale(.98);}
.lm .lm-gvform .gv-give:focus-visible{outline:2px solid var(--acc);outline-offset:3px;}
.lm .lm-gvform .gv-error{margin:12px 0 0;font:500 13.5px/1.4 var(--mb-ui);color:var(--error);text-align:center;}
.lm .lm-pay{display:flex;align-items:flex-start;justify-content:center;gap:8px;margin:14px 0 0;font:500 12.5px/1.45 var(--mb-ui);color:var(--fg3);text-align:left;}
.lm .lm-pay .mb-ic{flex:none;margin-top:1px;}
.lm .gv-banner.lm-gvnote{margin:18px 0 0;padding:14px 16px;border:0;border-radius:14px;background:var(--s1);color:var(--fg);font:500 14px/1.45 var(--mb-ui);}
.lm .gv-back{margin:18px 0 6px;padding:10px 0;color:var(--acc);font:650 15px/1 var(--mb-ui);}
.lm .gv-pay{margin-top:4px;border-radius:16px;}
.lm .gv-ways{margin-top:34px;}
.lm .gv-ways-h{margin:0 0 12px;font:650 11px/1 var(--mb-ui);letter-spacing:.14em;color:var(--fg3);}
.lm .gv-way{margin:0;padding:14px 0;border:0;border-bottom:1px solid var(--lm-line);border-radius:0;font:400 14.5px/1.35 var(--mb-ui);}
.lm .gv-way-name{font-weight:650;}
.lm .gv-copy{border:0;border-radius:15px;background:var(--s1);color:var(--fg);font:650 12.5px/1 var(--mb-ui);}
.lm .gv-ways .gv-note{text-align:left;}
/* Your giving: a soft church-colour surface, edge to edge */
.lm .lm-gtotal{margin:36px -20px 0;padding:22px 20px 18px;background:var(--lm-tint);}
.lm .lm-gtotal .lm-kicker{margin:0;}
.lm .lm-gtlink{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:10px;color:var(--fg);text-decoration:none;
  font:300 28px/1.1 var(--mb-serif);letter-spacing:-.02em;}
.lm .lm-gtlink em{font-style:italic;color:var(--acc);}
.lm .lm-linkrow{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:16px;padding-top:16px;
  border-top:1px solid var(--lm-line);color:var(--fg);text-decoration:none;}
.lm .lm-linkrow b{display:block;font:650 14px/1.2 var(--mb-ui);}
.lm .lm-linkrow b+span{display:block;margin-top:4px;font:400 12.5px/1.2 var(--mb-ui);color:var(--fg2);}
/* the thank-you, the mock's sheet */
.lm dialog.lm-gave{position:fixed;inset:auto 0 0 0;width:100%;max-width:600px;margin:0 auto;padding:12px 22px calc(28px + env(safe-area-inset-bottom,0px));
  border:0;border-radius:28px 28px 0 0;background:var(--bg);color:var(--fg);text-align:center;}
.lm dialog.lm-gave::backdrop{background:rgba(0,0,0,.4);}
.lm .lm-grab{width:40px;height:5px;margin:0 auto 18px;border-radius:3px;background:var(--s3);}
.lm .lm-okring{width:84px;height:84px;margin:4px auto 24px;border-radius:50%;display:grid;place-items:center;color:var(--acc);
  box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm .lm-gave h2{margin:0 0 8px;font:400 36px/1 var(--mb-serif);letter-spacing:-.02em;}
.lm .lm-gave h2:focus{outline:none;}
.lm .lm-gave h2 em{font-style:italic;color:var(--acc);}
.lm .lm-gave .gv-banner{display:block;max-width:290px;margin:0 auto 22px;padding:0;border:0;background:none;color:var(--fg2);font:400 15px/1.5 var(--mb-ui);}
.lm .lm-btn.lm-block{width:100%;height:56px;border-radius:18px;font-size:16px;}
@media (prefers-reduced-motion:no-preference){
  .lm dialog.lm-gave[open]{animation:lmup .45s cubic-bezier(.2,.9,.2,1) both;}
  .lm dialog.lm-gave[open] .lm-okring{animation:lmring .6s cubic-bezier(.2,1.2,.4,1) both;}
}
@keyframes lmup{from{transform:translateY(100%)}to{transform:none}}
@keyframes lmring{from{transform:scale(.6);opacity:0}to{transform:none;opacity:1}}

/* Watch: the next live on a soft band, the latest edge to edge, series two across */
.lm .lm-nrow{display:flex;align-items:center;gap:14px;margin:14px -20px 0;padding:16px 20px;color:var(--fg);text-decoration:none;
  background:var(--lm-tint-6);border-top:1px solid var(--lm-line);border-bottom:1px solid var(--lm-line);}
.lm .lm-nrow .lm-kicker{display:flex;align-items:center;gap:7px;color:var(--lm-violet);}
.lm .lm-nrow.is-live .lm-kicker{color:var(--acc);}
.lm .lm-nrow .lm-wt b{margin-top:6px;}
.lm .lm-halo{width:42px;height:42px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--lm-violet);background:var(--lm-tint);}
.lm .lm-feat{margin-top:24px;}
.lm .lm-poster{display:block;aspect-ratio:16/9;}
.lm .lm-poster>.mb-ph,.lm .lm-poster>.mb-art,.lm .lm-th>.mb-ph,.lm .lm-th>.mb-art,.lm .lm-stile .img>.mb-art{position:absolute;inset:0;
  width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm .lm-poster .mb-art{padding:18px;}
.lm .lm-poster .mb-art-title{font:400 40px/.98 var(--mb-serif);letter-spacing:-.02em;}
.lm .lm-poster .mb-titled b{padding:40px 18px 16px;font:400 36px/1 var(--mb-serif);letter-spacing:-.02em;}
.lm .lm-featk{margin:18px 0 0;}
.lm .lm-tl{margin:6px 0 0;font:700 24px/1.2 var(--mb-ui);letter-spacing:-.015em;}
.lm .lm-tl a{color:inherit;text-decoration:none;}
.lm .lm-feat .lm-meta{margin-top:4px;}
.lm .lm-acts{display:flex;gap:10px;margin-top:16px;}
.lm .lm-acts .lm-btn:first-child{flex:1;}
.lm .lm-btn.lm-sq{width:46px;padding:0;flex:none;}
.lm .lm-grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px 14px;}
.lm .lm-stile .img{height:auto;aspect-ratio:16/9;}
.lm .lm-stile .tt{font-size:16px;}
.lm .lm-stile .mb-art{padding:10px 12px;}
.lm .lm-stile .mb-art-title{font:400 22px/1 var(--mb-serif);letter-spacing:-.015em;}
.lm .lm-stile .mb-titled b{padding:24px 12px 10px;font:400 20px/1 var(--mb-serif);letter-spacing:-.01em;}
.lm .lm-lrow{display:flex;align-items:center;gap:14px;padding:12px 0;color:var(--fg);text-decoration:none;border-bottom:1px solid var(--lm-line);}
.lm .lm-lrow .lm-wt b{font:650 15px/1.25 var(--mb-ui);}
.lm .lm-lrow .lm-wt>span{font-size:12.5px;line-height:1.3;}
.lm .lm-th{position:relative;width:80px;height:45px;flex:none;overflow:hidden;border-radius:10px;background:var(--s2);}
.lm .lm-th .mb-art{padding:5px 7px;}
.lm .lm-th .mb-art-title{font:400 12px/1 var(--mb-serif);letter-spacing:0;}
.lm .lm-th .mb-titled b{padding:12px 6px 4px;font:600 10.5px/1 var(--mb-ui);letter-spacing:-.01em;}
.lm .lm-soon{margin:24px -20px 0;padding:22px 20px;background:var(--lm-tint);}
.lm .lm-soon+.lm-page{margin-top:24px;}

/* Live: the room. The video edge to edge with Back and Live · N here on it; names over the words */
.lm .lv-stage{position:relative;}
.lm .lm-lvtop{position:absolute;z-index:3;left:12px;right:12px;top:10px;display:flex;align-items:center;justify-content:space-between;
  gap:10px;pointer-events:none;}
.lm .lm-lvback{width:38px;height:38px;flex:none;border-radius:50%;display:grid;place-items:center;background:rgba(0,0,0,.5);color:#fff;
  pointer-events:auto;}
.lm .lm-lvchip{display:inline-flex;align-items:center;gap:7px;height:30px;padding:0 12px;border-radius:15px;background:rgba(0,0,0,.55);
  color:#fff;font:650 12.5px/1 var(--mb-ui);white-space:nowrap;}
.lm .lm-lvchip b{font-weight:650;font-variant-numeric:tabular-nums;}
.lm .lm-lvchip>span{margin-left:-3px;}
.lm .lv-info{padding:14px 20px 0;}
.lm .lv-t h1{font:650 17px/1.25 var(--mb-ui);letter-spacing:-.015em;}
.lm .lv-t p{margin-top:3px;font:400 13px/1.3 var(--mb-ui);color:var(--fg3);}
.lm .lv-acts{display:flex;gap:8px;padding:12px 20px 14px;border-bottom:1px solid var(--lm-line);}
.lm .lv-pill{width:auto;height:38px;padding:0 16px;border-radius:19px;background:var(--s1);color:var(--fg);box-shadow:none;
  font:650 13.5px/1 var(--mb-ui);letter-spacing:0;}
.lm .lv-pill.is-go{background:var(--acc-fill);color:var(--on-acc);}
.lm .lv-pill.is-here{background:transparent;color:var(--acc);box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm .lv-chat{margin-top:0;box-shadow:none;}
.lm .lv-pin{margin:0 20px;padding:14px 0;gap:12px;border-radius:0;background:none;border-bottom:1px solid var(--lm-line);}
.lm .lv-pin .lv-av{width:34px;height:34px;font-size:0;background:var(--lm-tint);color:var(--lm-violet);}
.lm .lv-pin .lv-av>*{display:none;}
.lm .lv-pin .lv-av::before{content:"";width:15px;height:15px;background:currentColor;
  -webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 17v5M5 17h14l-2-4V5H7v8z'/%3E%3C/svg%3E") center/contain no-repeat;
  mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 17v5M5 17h14l-2-4V5H7v8z'/%3E%3C/svg%3E") center/contain no-repeat;}
.lm .lv-pin .lv-tag{display:none;}
.lm .lv-pin .lv-who{display:block;margin-bottom:4px;font:700 10px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--lm-violet);}
.lm .lv-pin .lv-who::before{content:"Pinned \\00b7  ";}
.lm .lv-pin p{font:500 14.5px/1.4 var(--mb-ui);}
.lm .lv-list{gap:12px;padding:12px 20px 10px;}
.lm .lv-msg{gap:10px;}
.lm .lv-msg p{padding-top:1px;font:400 14.5px/1.4 var(--mb-ui);color:var(--fg);}
.lm .lv-av{width:30px;height:30px;font-size:11px;}
.lm .lv-msg .lv-who{display:block;margin-bottom:3px;font:650 13.5px/1.1 var(--mb-ui);}
.lm .lv-msg.is-mine{margin:0;padding:0;border-radius:0;background:none;}
.lm .lv-msg.is-mine .lv-who{color:var(--acc);}
.lm .lv-msg.is-host .lv-tag{display:none;}
.lm .lv-msg.is-host .lv-who::after{content:"Host";display:inline-block;margin-left:6px;padding:2px 6px;border-radius:5px;background:var(--lm-tint-12);
  color:var(--acc);font:700 9.5px/1 var(--mb-ui);letter-spacing:.08em;text-transform:uppercase;vertical-align:1px;}
.lm .lv-empty{font:400 14px/1.4 var(--mb-ui);}
.lm .lv-foot{padding:10px 12px calc(10px + env(safe-area-inset-bottom,0px));background:var(--bg);border-top:1px solid var(--lm-line);}
.lm .lv-quick{margin:0 -12px 10px;padding:0 12px;}
.lm .lv-quick button{height:32px;padding:0 14px;border-radius:16px;background:var(--s1);box-shadow:none;color:var(--fg2);font:650 13px/1 var(--mb-ui);}
.lm .lv-compose{gap:8px;}
.lm .lv-input{height:42px;padding:0 16px;border-radius:21px;background:var(--s1);box-shadow:none;font:400 16px/1 var(--mb-ui);}
.lm .lv-input:focus{box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm .lv-send{width:42px;height:42px;background:var(--s1);color:#ff5c8a;transition:background-color .2s,color .2s;}
.lm .has-text .lv-send{background:var(--acc-fill);color:var(--on-acc);}
.lm .lm-lvgive{height:42px;width:64px;flex:none;border-radius:21px;display:grid;place-items:center;background:var(--acc-fill);color:var(--on-acc);
  font:650 13.5px/1 var(--mb-ui);text-decoration:none;}
.lm .lv-compose:has(.lm-lvgive) .lv-hearts{right:72px;}
.lm .lv-heart{background:var(--s1);color:#ff5c8a;}
.lm .lv-heart.is-mine{background:#ff5c8a;color:#fff;}
.lm .lv-note{border-top:1px solid var(--lm-line);}
.lm .lv-toast{background:var(--fg);color:var(--bg);box-shadow:0 10px 30px rgba(0,0,0,.25);}
.lm dialog.lv-sheet{border-radius:28px 28px 0 0;background:var(--bg);box-shadow:0 -12px 40px rgba(0,0,0,.18);}
.lm dialog.lv-sheet::backdrop{background:rgba(0,0,0,.4);}
.lm .lv-grab{width:40px;background:var(--s3);}
.lm .lv-sheet-h h2{font:400 26px/1.1 var(--mb-serif);letter-spacing:-.015em;}
.lm .lv-x{background:var(--s1);}
.lm .lv-sheet textarea,.lm .lv-other{background:var(--s1);box-shadow:none;}
.lm .lv-seg{background:var(--s1);}
.lm .lv-seg input:checked+span{background:var(--bg);box-shadow:0 1px 3px var(--lm-shadow);}
.lm .lv-amts span{height:50px;border-radius:16px;background:var(--s1);box-shadow:none;font:650 16px/1 var(--mb-ui);}
.lm .lv-amts input:checked+span{background:var(--acc-fill);color:var(--on-acc);}
.lm .lv-go{height:56px;border-radius:18px;}
.lm .lv-done-ic{background:none;color:var(--acc);box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm .lm-lvback:focus-visible,.lm .lm-lvgive:focus-visible,.lm .lm-fchip:focus-visible,.lm .lm-nrow:focus-visible,.lm .lm-lrow:focus-visible,
.lm .lm-gtlink:focus-visible,.lm .lm-linkrow:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (max-width:999px){
  /* a phone: the room starts at the video (the mock's), Back sits on it */
  .lm:has(.lv-room) .mb-top{display:none;}
  .lm .lv-stage{padding-top:env(safe-area-inset-top,0px);}
  .lm:has(.lv-room) .mp-shell.mb-has-nav{padding:0;}
}
@media (max-width:999px) and (orientation:landscape) and (max-height:520px){
  .lm .lv-info{top:60px;}
  .lm .lm-lvtop{position:fixed;z-index:32;left:max(12px,env(safe-area-inset-left,0px));right:auto;}
}
@media (min-width:1000px){
  .lm .lm-lvback{display:none;}
  .lm .lv-acts{border-bottom:0;padding:16px 0 0;}
  .lm .lv-info{padding:18px 0 0;}
  .lm .lv-t h1{font:400 34px/1.05 var(--mb-serif);letter-spacing:-.02em;}
  .lm .lv-pin{margin:0 16px;}
}
@media (prefers-reduced-motion:no-preference){
  .lm .lm-nrow,.lm .lm-lrow,.lm .lm-fchip,.lm .lm-pre .gv-amt{transition:transform .15s ease,background-color .25s,color .25s;}
  .lm .lm-nrow:active,.lm .lm-lrow:active{transform:scale(.985);}
  .lm .lm-pre .gv-amt:active,.lm .lm-fchip:active{transform:scale(.96);}
}
""")
