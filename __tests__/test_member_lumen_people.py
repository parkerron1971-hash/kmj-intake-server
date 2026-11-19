# __tests__/test_member_lumen_people.py
#
# The member app's people pages in the new look ("Lumen": member_lumen_people,
# behind MEMBER_LUMEN). Kevin, on the approved mock: messages "look generic. it
# should feel like text messages area". Pins, for Messages:
#   - the inbox: the church's conversation pinned first ("From your church"),
#     then every chat newest first with its unread count, a chat request with
#     Accept and Ignore; the same reads as today's page;
#   - a conversation (the church's, a private chat, a group's chat, a group's
#     notes, the leaders' room): its face and name in the bar, no tab bar,
#     bubbles, the box at the foot, with instant send's form, list, box and
#     error ids, its script, and the bubble markup it draws while sending;
#   - a message just sent is drawn exactly as before (the JSON answer);
#   - off: today's markup, no Lumen class anywhere;
#   - the sheet: these rules are in the hashed Lumen file, under body.lm.

import pathlib
import re
import sys
from collections import Counter
from datetime import timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_ui as ui
import member_lumen_people as lp
import member_portal_threads as mpt
import test_church_threads as tct
import test_member_messaging as tmm
from test_church_threads import fake, screen  # noqa: F401  (fixtures)
from test_member_group_chat import _page as group_page, church as gchurch  # noqa: F401  (fixture)
from test_member_messaging import env  # noqa: F401  (fixture)

APP = {"accept": "application/json"}


@pytest.fixture(autouse=True)
def _fresh_caches():
    """What a page keeps per member (the bell's dot, the unread counts)
    never leaks into the next test, here or in another file."""
    import member_alerts
    member_alerts.forget()
    mpt._COUNTS.clear()
    yield
    member_alerts.forget()
    mpt._COUNTS.clear()


def _body_class(html):
    return re.search(r"<body( class=\"([^\"]*)\")?>", html).group(2) or ""


def _top(html):
    return html[html.index('<header class="mb-top'):html.index("</header>")]


@pytest.fixture
def threads(fake, monkeypatch):  # noqa: F811
    """Ana at a made-up church with church threads open, one group with a
    note, and the church's conversation over two days."""
    for i, n in ((tct.ANA, "Ana Rivera"), (tct.BEN, "Ben Stone")):
        fake.person(i, n)
    fake.biz[tct.BIZ]["name"] = "Grace Fellowship"
    fake.add("groups", id=tct.GROUP, business_id=tct.BIZ, name="Young Adults", active=True, chat_on=True)
    fake.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=tct.ANA, role="member")
    fake.note(contact_id=None, kind="announcements", title="Food Drive", body="Saturday at 9", url="/my/events",
              created_at=tct.iso(tct.NOW - timedelta(days=2)))
    fake.note(contact_id=tct.ANA, direction="member", kind="message", body="Can my teens help?", author_name="Ana",
              created_at=tct.iso(tct.NOW - timedelta(days=2) + timedelta(minutes=5)))
    fake.note(contact_id=tct.ANA, kind="reply", body="Yes! Ages 13 and up.", author_name="Maria",
              author_user_id=tct.CLERK, created_at=tct.iso(tct.NOW - timedelta(days=2) + timedelta(minutes=9)))
    fake.note(contact_id=tct.ANA, thread=f"group:{tct.GROUP}", kind="groups", title="Young Adults",
              body="Maya posted: bring a friend", url=f"/my/groups/{tct.GROUP}/board",
              created_at=tct.iso(tct.NOW - timedelta(hours=1)))
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    monkeypatch.setattr(mpt, "_zone", lambda biz: tct.timezone.utc)
    return fake


# ─── the sheet ───────────────────────────────────────────────────────


def test_the_people_rules_are_in_the_lumen_file_under_body_lm():
    text = ui.sheet("lumen")[0]
    for cls in ("lm-irow", "lm-pinl", "lm-uchip", "lm-thead", "lm-cmp", "lm-cfield", "lm-send", "lm-day"):
        assert f".{cls}" in text, cls
    css = re.sub(r"/\*.*?\*/", "", lp.CSS_PEOPLE.template, flags=re.S)
    css = re.sub(r"@keyframes[^{]*\{[^}]*\}[^}]*\}\s*\}?", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    for sel in re.findall(r"(?:^|\})\s*([^{}]+)\{", css):
        for one in sel.split(","):
            if one.strip():
                assert one.strip().startswith("body.lm"), one
    assert "!important" not in css and "$" not in css


# ─── the inbox ───────────────────────────────────────────────────────


def test_the_inbox_pins_the_church_then_every_chat_with_its_count(threads, monkeypatch):
    html = tct._app(threads, monkeypatch, tct.ANA).get("/my/messages").text
    assert _body_class(html).split()[:2] == ["lm", "lm-push"]
    assert "<em>Messages</em>" in html
    inbox = html[html.index('<ul class="lm-inbox"'):]
    inbox = inbox[:inbox.index("</ul>")]
    rows = re.findall(r'<a class="(lm-irow[^"]*)" href="([^"]+)">', inbox)
    assert rows[0][1] == "/my/inbox/church" and "lm-pin" in rows[0][0]       # the church first
    assert "From your church" in inbox and "Grace Fellowship" in inbox
    assert f"/my/inbox/group/{tct.GROUP}" in [h for _, h in rows]            # the group (chats off here)
    assert re.search(r'class="lm-uchip" aria-label="\d+ new"', inbox)         # its unread count
    assert "<style>" not in html[html.index("<main"):]                        # nothing inline


def test_the_inbox_reads_what_todays_page_reads(threads, monkeypatch):
    c = tct._app(threads, monkeypatch, tct.ANA)
    c.get("/my/messages")
    threads.gets.clear()
    on = c.get("/my/messages").text
    reads_on = Counter(r.split("?")[0] for r in threads.gets)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c.get("/my/messages")
    threads.gets.clear()
    off = c.get("/my/messages").text
    reads_off = Counter(r.split("?")[0] for r in threads.gets)
    assert reads_on == reads_off
    assert "lm-irow" in on and "lm-irow" not in off and 'class="lm-' not in off


def _asked(env, tid):  # noqa: F811
    """Ben's chat is a request to Ana (someone who doesn't share a group)."""
    for p in env.t["msg_participants"]:
        if p["thread_id"] == tid and p["contact_id"] == tmm.ANA:
            p["state"] = "requested"


def test_a_chat_request_has_accept_and_ignore(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    tid = tmm._tid(tmm._start(env, tmm.BEN, tmm.ANA))
    tmm._send(env, tmm.BEN, tid, "Hi Ana")
    _asked(env, tid)
    html = tmm._member(env, tmm.ANA).get("/my/messages").text
    req = html[html.index('class="lm-req"'):]
    req = req[:req.index("</div>")]
    assert "wants to chat." in req and f'href="/my/messages/{tid}"' in req
    assert f'action="/my/messages/{tid}/accept"' in req and f'action="/my/messages/{tid}/decline"' in req
    assert ">Accept<" in req and ">Ignore<" in req


# ─── the church's conversation ───────────────────────────────────────


def test_the_church_conversation_is_a_texting_screen(threads, monkeypatch):
    html = tct._app(threads, monkeypatch, tct.ANA).get("/my/inbox/church").text
    assert _body_class(html).split()[:3] == ["lm", "lm-push", "lm-thread"]
    top = _top(html)
    assert 'class="mb-top lm-tbar"' in top and 'class="lm-thead"' in top
    assert "Grace Fellowship" in top and "The church office" in top
    assert 'href="/my/messages" data-back aria-label="Messages"' in top
    assert '<nav class="mb-nav' not in html                                  # no tab bar
    # Instant send's hooks: the same ids, its script, its bubble.
    for hook in ('id="ct-compose"', 'id="ct-chat"', 'id="ct-say"', 'action="/my/inbox/church/send"'):
        assert hook in html, hook
    assert '"form": "ct-compose"' in html and '"kind": "ct"' in html
    assert '<li class="mb-msg mb-mine"><span class="mb-msg-body">Can my teens help?</span>' in html
    # The church's notes and the office's replies beside its mark; a line for each day.
    assert html.count('class="mb-msg ct-note lm-them"') == 1 and html.count('class="mb-msg lm-them"') == 1
    assert '<span class="lm-nwho">Maria</span>' in html
    assert 'class="mb-msg ct-day" role="separator"' in html
    assert 'class="lm-send" type="submit" aria-label="Send"' in html


def test_a_message_just_sent_is_drawn_as_before(threads, monkeypatch, screen):  # noqa: F811
    c = tct._app(threads, monkeypatch, tct.ANA)
    for r in tct.notes(threads, direction="member"):
        r["created_at"] = tct.iso(tct.NOW - timedelta(days=3))
    x = c.post("/my/inbox/church/send", data={"body": "Hello"}, headers={**tct.ORIGIN, **APP},
               follow_redirects=False).json()
    assert x["ok"] and x["html"].startswith('<li class="mb-msg mb-mine"><span class="mb-msg-body">Hello</span>')
    assert "lm-" not in x["html"] and x["day_html"] == '<li class="mb-msg ct-day" role="separator">Today</li>'


def test_off_the_church_conversation_is_todays(threads, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = tct._app(threads, monkeypatch, tct.ANA).get("/my/inbox/church").text
    assert "lm" not in _body_class(html).split() and 'class="lm-' not in html and "lm-tbar" not in html
    assert '<form class="mb-compose ct-compose"' in html and f"<style>{mpt.THREAD_CSS}</style>" in html


def test_a_groups_notes_in_the_new_look(threads, monkeypatch):
    html = tct._app(threads, monkeypatch, tct.ANA).get(f"/my/inbox/group/{tct.GROUP}").text
    assert "lm-thread" in _body_class(html)
    top = _top(html)
    assert "Group news" in top and 'class="lm-av gp"' in top
    assert 'class="mb-msg ct-note lm-them"><span class="lm-av gp"' in html


# ─── a private chat ──────────────────────────────────────────────────


def test_a_private_chat_is_a_texting_screen(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    tmm._send(env, tmm.ANA, tid, "See you Tuesday")
    tmm._send(env, tmm.BEN, tid, "Will do")
    html = tmm._member(env, tmm.ANA).get(f"/my/messages/{tid}").text
    assert "lm-thread" in _body_class(html) and '<nav class="mb-nav' not in html
    top = _top(html)
    assert 'class="lm-thead"' in top and "Ben" in top
    for hook in ('id="mb-compose"', 'id="mb-chat"', 'id="mb-say"', 'id="mb-chat-err"', f'action="/my/messages/{tid}/send"'):
        assert hook in html, hook
    assert '"form": "mb-compose"' in html and '"kind": "mb"' in html
    # The box's first input is the message (the plain script reads it).
    form = html[html.index('id="mb-compose"'):]
    assert re.search(r"<input[^>]*>", form).group(0).startswith('<input id="mb-say"')
    # Bubbles carry their time for the day lines; no name over a private chat's.
    assert re.search(r'<li class="mb-msg mb-mine" data-id="[^"]+" data-at="[^"]+">', html)
    assert "mb-msg-who" not in html
    assert lp.days_script("mb-chat", "mb-compose") in html


def test_a_message_just_sent_in_a_chat_is_drawn_as_before(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    x = tmm._send(env, tmm.ANA, tid, "Bring chairs").json()
    assert x["ok"] and x["html"].startswith('<li class="mb-msg mb-mine" data-id=') and "data-at" not in x["html"]


def test_a_chat_request_page_has_accept_and_ignore_at_the_foot(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    tid = tmm._tid(tmm._start(env, tmm.BEN, tmm.ANA))
    tmm._send(env, tmm.BEN, tid, "Hi Ana")
    _asked(env, tid)
    html = tmm._member(env, tmm.ANA).get(f"/my/messages/{tid}").text
    foot = html[html.index('<div class="lm-cmp">'):]
    assert "wants to message you." in foot and f'action="/my/messages/{tid}/accept"' in foot
    assert 'id="mb-compose"' not in html


def test_off_a_private_chat_is_todays(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    tmm._send(env, tmm.ANA, tid, "See you Tuesday")
    html = tmm._member(env, tmm.ANA).get(f"/my/messages/{tid}").text
    assert 'class="lm-' not in html and "data-at" not in html and '<form class="mb-compose"' in html


def test_the_inbox_without_church_threads_in_the_new_look(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    tmm._send(env, tmm.BEN, tid, "Will do")
    html = tmm._member(env, tmm.ANA).get("/my/messages").text
    assert f'<a class="lm-irow is-new" href="/my/messages/{tid}">' in html
    assert "From your church" not in html                                    # no church conversation here


# ─── a group's chat ──────────────────────────────────────────────────


def test_a_groups_chat_is_a_texting_screen(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    tid = tmm._group_tid(gchurch, tmm.ANA, tmm.GRP)
    tmm._send(gchurch, tmm.BEN, tid, "Who's in?")
    tmm._send(gchurch, tmm.BEN, tid, "Doors at 7")
    tmm._send(gchurch, tmm.ANA, tid, "Me!")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/chat").text
    assert "lm-thread" in _body_class(html) and '<nav class="mb-nav' not in html and '<section class="gs-hero' not in html
    top = _top(html)
    assert re.search(r"<small>\d+ (person|people)</small>", top)
    assert f'href="/my/groups/{tmm.GRP}" data-back' in top                   # back to the group (or where they were)
    for hook in ('id="gc-compose"', 'id="gc-list"', 'id="gc-say"', 'id="gc-err"', f'action="/my/messages/{tid}/send"'):
        assert hook in html, hook
    assert '"form": "gc-compose"' in html and '"kind": "gc"' in html
    assert 'class="lm-send gc-send" type="submit"' in html                  # the plain script finds .gc-send
    # A run of one person's messages: the name once, the face at its foot.
    ben = re.findall(r'<li class="gc-m( [^"]*)?" id="m-[^"]+" data-at="[^"]+">', html)
    assert ben[:2] == [" lm-c2", " lm-c1"] and ben[2].startswith(" mine")
    assert re.search(r'class="gc-who lm-k\d"', html)
    assert lp.days_script("gc-list", "gc-compose") in html


def test_off_a_groups_chat_is_todays(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    tid = tmm._group_tid(gchurch, tmm.ANA, tmm.GRP)
    tmm._send(gchurch, tmm.BEN, tid, "Who's in?")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/chat").text
    assert 'class="lm-' not in html and "data-at" not in html and '<section class="gs-hero' in html
    assert '<form class="gc-compose" id="gc-compose"' in html


def test_runs_break_on_another_person_a_note_or_an_hour():
    from datetime import datetime, timezone
    import member_portal_groups as mpg
    t = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)
    seq = [("m", "a", t), ("m", "a", t + timedelta(minutes=2)), ("n", "", t + timedelta(minutes=3)),
           ("m", "a", t + timedelta(minutes=4)), ("m", "a", t + timedelta(hours=2)), ("m", "b", t + timedelta(hours=2))]
    assert mpg._runs(seq) == ["lm-c2", "lm-c1", "", "", "", ""]


# ─── Coming up and Prayer ────────────────────────────────────────────


def _occ(title, days, *, mine=None, roles=None, eid="00000000-0000-4000-8000-000000000301", full=False):
    from datetime import date
    d = date.today() + timedelta(days=days)
    return {"entry_id": eid, "module_id": "m", "title": title, "date": d.isoformat(),
            "date_label": f"{d.strftime('%A, %B')} {d.day}", "location": "Fellowship Hall", "capacity": None,
            "attending": 3, "spots_left": None, "full": full, "occasion_noun": "event", "mine": mine,
            "roles": roles or []}


@pytest.fixture
def calendar(fake, monkeypatch):  # noqa: F811
    import member_portal_church as mpc
    fake.person(tct.ANA, "Ana Rivera")
    fake.biz[tct.BIZ]["name"] = "Grace Fellowship"
    role = [{"id": "r1", "label": "Setup crew", "needed": 6, "filled": 3, "full": False}]
    occ = [_occ("Community Food Drive", 3, roles=role),
           _occ("Sunday Worship", 4, mine={"status": "yes", "role": None}, eid="00000000-0000-4000-8000-000000000302"),
           _occ("Prayer Night", 6, mine={"status": "yes", "role": "r1"}, roles=role,
                eid="00000000-0000-4000-8000-000000000303")]
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [dict(o) for o in occ])
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    return fake


def _church_app(fake, monkeypatch):  # noqa: F811
    import member_portal_church as mpc
    c = tct._app(fake, monkeypatch, tct.ANA)
    c.app.include_router(mpc.router)
    return c


def test_coming_up_is_a_list_with_each_day_in_the_margin(calendar, monkeypatch):
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/events").text
    assert "Coming <em>up</em>" in html and "At Grace Fellowship" in html
    rows = re.findall(r'<article class="lm-evc" aria-labelledby="(mp-occ-[^"]+)">', html)
    assert len(rows) == 3
    first = html[html.index(rows[0]):html.index(rows[1])]
    assert '<div class="lm-evd" aria-hidden="true"><small>' in first and "Community Food Drive" in first
    # The same forms today's cards post.
    assert first.count('action="/my/rsvp"') == 3                             # coming, can't, serve
    assert 'name="action" value="coming"' in first and 'name="action" value="cant"' in first
    assert 'name="back" value="/my/events"' in first
    assert '<details class="lm-serve"><summary>Sign up to serve' in first and 'name="role"' in first
    second = html[html.index(rows[1]):html.index(rows[2])]
    assert "You&#x27;re coming</span>" in second and 'value="coming"' not in second
    third = html[html.index(rows[2]):]
    assert "Serving: Setup crew" in third and "Just attend instead" in third


def test_off_coming_up_is_todays(calendar, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/events").text
    assert 'class="lm-' not in html and '<article class="mp-card mp-occ"' in html


def test_prayer_keeps_the_flame_and_chooses_nothing_for_them(calendar, monkeypatch):
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/prayer").text
    assert 'class="lm-eyebrow lm-flame"' in html and "How can we <em>pray</em> for you?" in html
    form = html[html.index('<form class="lm-pform"'):]
    form = form[:form.index("</form>")]
    assert 'action="/my/prayer"' in form and 'name="request"' in form and 'name="then" value="prayer"' in form
    assert 'name="share" value="team" required' in form and 'name="share" value="pastors"' in form
    assert "checked" not in form                                             # still none chosen for them
    assert 'name="wants_call" value="yes"' in form and "Send to the pastors" in form


def test_the_new_prayer_page_answers_on_its_own_page(calendar, monkeypatch):
    c = _church_app(calendar, monkeypatch)
    r = c.post("/my/prayer", data={"request": "Pray for my mom", "share": "team", "then": "prayer"},
               headers=tct.ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/prayer?done=prayer&s=team"
    assert len(calendar.t["ministry_care_requests"]) == 1
    page = c.get(r.headers["location"]).text
    assert "Your pastors <em>have it.</em>" in page and "Our prayer team may pray over it with you too." in page
    # Today's form (no then) still goes Home, as always.
    r = c.post("/my/prayer", data={"request": "Again", "share": "pastors"}, headers=tct.ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my?done=prayer"


def test_off_prayer_is_todays(calendar, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/prayer").text
    assert 'class="lm-' not in html and 'name="then"' not in html and '<form class="mp-form" method="post" action="/my/prayer">' in html


@pytest.mark.parametrize("path", ["/my/events", "/my/prayer"])
def test_coming_up_and_prayer_read_what_todays_pages_read(calendar, monkeypatch, path):
    c = tct._app(calendar, monkeypatch, tct.ANA)
    got = {}
    for mode in ("on", "off"):
        monkeypatch.setenv("MEMBER_LUMEN", mode)
        c.get(path)
        calendar.gets.clear()
        c.get(path)
        got[mode] = Counter(r.split("?")[0] for r in calendar.gets)
    assert got["on"] == got["off"]


# ─── a group's page, Me, My details, Your alerts, News ───────────────


def test_a_groups_page_is_a_serif_name_faces_and_one_segmented_control(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert '<header class="lm-ghead">' in html and '<section class="gs-hero' not in html
    assert re.search(r'<h1 class="lm-disp" id="gs-name">[^<]*<em>[^<]+</em></h1>', html)
    assert re.search(r"<span>\d+ (person|people)</span>", html)                 # a member sees how many
    seg = html[html.index('<nav class="lm-gseg"'):]
    seg = seg[:seg.index("</nav>")]
    hrefs = re.findall(r'<a href="([^"]+)"', seg)
    assert hrefs[0] == f"/my/groups/{tmm.GRP}" and f"/my/groups/{tmm.GRP}/people" in hrefs
    assert f'<a href="/my/groups/{tmm.GRP}" aria-current="page">Home' in seg
    assert '<nav class="gs-tabs"' not in html
    top = _top(html)
    assert 'href="/my/connect"' in top and "Connect" in top                      # pushed from Connect


def test_off_a_groups_page_is_todays(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert '<section class="gs-hero' in html and '<nav class="gs-tabs"' in html and 'class="lm-' not in html


def test_me_is_your_circle_your_giving_and_one_list(calendar, monkeypatch):
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/me").text
    assert 'class="mb-profile lm-prof"' in html and re.search(r"<h1>Ana Rive\w+</h1>", html)
    # The photo form and its script, as today.
    assert 'id="mb-photo-in"' in html and 'id="mb-photo-note"' in html and 'action="/my/photo"' in html
    assert '<section class="lm-megive"' in html and "Your giving · " in html
    doors = re.findall(r'<a class="lm-li" href="([^"]+)"><b>([^<]+)</b>', html)
    assert ("/my/events", "Coming up") in doors and ("/my/details", "My details") in doors
    assert ("/my/prayer", "Prayer") in doors
    assert 'action="/my/signout"' in html
    assert 'class="mb-back" href="/my" data-back' in _top(html)               # back to where it opened


def test_off_me_is_todays(calendar, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/me").text
    assert 'class="lm-' not in html and '<section class="mb-give-card"' in html


def test_my_details_keeps_its_form(calendar, monkeypatch):
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/details").text
    assert "My <em>details</em>" in html
    form = html[html.index('<form class="lm-dform" method="post" action="/my/details">'):]
    form = form[:form.index("</form>")]
    for k in ("phone", "line1", "line2", "city", "state", "postal"):
        assert f'id="mp-{k}" name="{k}"' in form and f'for="mp-{k}"' in form, k
    assert "Save my details" in form


def test_your_alerts_in_the_new_look(calendar, monkeypatch):
    import member_alerts
    import member_push
    from datetime import datetime, timezone
    monkeypatch.setattr(member_push, "ready", lambda: True)
    monkeypatch.setattr(member_push, "vapid_public", lambda: "BKkey")
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(member_alerts, "recent_alerts", lambda biz, cid, limit=None, **kw: [
        {"kind": "events", "label": "Event reminders", "title": "Tomorrow: Picnic", "body": "", "when": now.isoformat(),
         "link": "/my/events"}])
    monkeypatch.setattr(member_alerts, "seen_at", lambda biz, cid: "2026-01-01T00:00:00+00:00")
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/notifications").text
    assert "Your <em>alerts</em>" in html
    assert '<h2 id="al-recent" class="lm-h2">Recent <span class="lm-new" aria-hidden="true">NEW</span></h2>' in html
    assert html.index("Recent") < html.index("What reaches this phone") < html.index('name="k_live"')
    assert re.search(r'<input class="lm-sw" type="checkbox" name="k_live" checked>', html)
    for hook in ('id="np-state"', 'id="np-on"', 'id="np-off"', 'id="np-ios"', 'action="/my/notifications"'):
        assert hook in html, hook
    assert "/my/push/subscribe" in html and "Back to Me" not in html


def test_news_in_the_new_look(calendar, monkeypatch):
    import church_news as cn
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(cn, "feed", lambda b, me_id, filt="", today=None: [
        {"id": "00000000-0000-4000-8000-000000000811", "kind": "announcement", "title": "Food Drive", "body": "Saturday",
         "pinned": False, "created_at": now, "published_at": now, "reactions": {}, "mine": [], "comment_count": 0}])
    monkeypatch.setattr(cn, "can_post", lambda b, me_id: {})
    monkeypatch.setattr(cn, "mark_seen", lambda *a, **k: None)
    monkeypatch.setattr(cn, "comments_open", lambda b: False)
    html = tct._app(calendar, monkeypatch, tct.ANA).get("/my/news").text
    assert '<div class="lm-nwpage">' in html and "What&#x27;s <em>happening</em>" in html
    assert 'id="p-00000000-0000-4000-8000-000000000811"' in html and "Food Drive" in html


@pytest.mark.parametrize("path", ["/my/me", "/my/details", "/my/notifications", "/my/news"])
def test_me_details_alerts_and_news_read_what_todays_pages_read(calendar, monkeypatch, path):
    import member_alerts
    # The Recent list is the bell list's own reads, on main's new look as
    # here (member_alerts); the page's own reads are what's compared.
    monkeypatch.setattr(member_alerts, "shown", lambda: False)
    c = tct._app(calendar, monkeypatch, tct.ANA)
    got = {}
    for mode in ("on", "off"):
        monkeypatch.setenv("MEMBER_LUMEN", mode)
        c.get(path)
        calendar.gets.clear()
        c.get(path)
        got[mode] = Counter(r.split("?")[0] for r in calendar.gets)
    assert got["on"] == got["off"]
