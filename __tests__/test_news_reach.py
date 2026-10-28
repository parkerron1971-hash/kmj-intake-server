# __tests__/test_news_reach.py
#
# An important post reaches the people without the app (news_reach.py,
# Kevin 2026-10-28: "texting only people without app alerts", important
# posts only, email for the rest). Pins:
#   1. who: the people it's for (its group, or the church's members, not
#      guests), never whoever posted it, never a known minor, never someone
#      whose phone rings for the app, never someone who chose Off
#   2. which way: a text only from the church's own name, only to a yes, only
#      while "Text me important news" isn't off, at most the month's texts;
#      everyone else with an address gets the email; a text that fails
#      becomes the email
#   3. once, in the church's day: quiet hours wait for the sweep, three a
#      day, a day and a half old lets it go, the church's switch, a failed
#      read puts it back for the sweep
#   4. the text: one plain part, the church's name and the STOP line fit
#   5. the office's line, the member's "Text me important news", their yes

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import news_alerts as na
import news_reach as nr
import test_member_portal_group_space as gs
from test_member_portal_group_space import ADULT, BIZ, G, MONIQUE, ROCHELLE, TASHA, TEEN

CHURCH = {"id": BIZ, "name": "Love City Church", "owner_id": "o1",
          "settings": {"member_portal": {"notifications": {"news": True}},
                       "availability": {"timezone": "America/Detroit"}}}
FRI_10 = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)      # Friday, 10 AM in Detroit
FRI_11PM = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)     # Friday, 11 PM in Detroit
P1 = "dddddddd-9999-0000-0000-000000000001"
PAT = "cccccccc-0000-0000-0000-000000000010"      # a member with only an email
OFFY = "cccccccc-0000-0000-0000-000000000011"     # a member who chose Off
M_PHONE, PAT_MAIL = "+15550000102", "pat@example.com"


def _split_top(v):
    """or=(a,b.in.(x,y)) → [a, b.in.(x,y)]: commas inside parentheses stay."""
    out, depth, cur = [], 0, ""
    for ch in v:
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    return out + [cur]


def _cond(row, key, expr):
    if expr.startswith("not.in."):
        return str(row.get(key)) not in expr[len("not.in."):].strip("()").split(",") and row.get(key) is not None
    return _cond0(row, key, expr)


_cond0 = gs._cond


class Fake(gs.Fake):
    def _rows(self, table, params):
        out = []
        for r in self.t.get(table, []):
            ok = True
            for k, v in params:
                if k in ("select", "order", "limit", "offset", "on_conflict"):
                    continue
                if k == "or":
                    parts = _split_top(v[1:-1])
                    if not any(_cond(r, p.split(".", 1)[0], p.split(".", 1)[1]) for p in parts):
                        ok = False
                    continue
                if not _cond(r, k, v):
                    ok = False
            if ok:
                out.append(r)
        return out


def _post(**k):
    row = {"id": P1, "business_id": BIZ, "kind": "announcement", "title": "Service moves to 11 AM Sunday",
           "body": "Snow is coming. Stay warm.", "group_id": None, "posted_by": None, "office_user": "u1",
           "source": "office", "status": "posted", "important": True, "publish_at": None, "attach": {},
           "person_id": None, "created_at": "2026-10-23T13:30:00+00:00", "removed_at": None, "reached_at": None}
    row.update(k)
    return row


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(gs, "_cond", _cond)
    f = Fake()
    for c in f.t["contacts"]:
        c["phone"] = {MONIQUE: "(555) 000-0102", TASHA: "+15550000101"}.get(c["id"])
    f.t["contacts"] += [
        {"id": PAT, "business_id": BIZ, "name": "Pat Lee", "birthdate": ADULT, "email": PAT_MAIL, "phone": None,
         "status": "active", "metadata": {}},
        {"id": OFFY, "business_id": BIZ, "name": "Off Person", "birthdate": None, "email": "off@example.com",
         "phone": "+15550000111", "status": None, "metadata": {}}]
    f.t.update(church_posts=[], member_push_prefs=[{"business_id": BIZ, "contact_id": OFFY, "off": [], "news_level": "off"}],
               member_push_subscriptions=[{"id": "s1", "business_id": BIZ, "contact_id": TASHA}],
               businesses=[{**CHURCH}], sms_consents=[])
    import email_layout
    import email_sender
    import group_email
    import member_push
    import sb_clients
    import sms_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(member_push, "_later", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(group_email, "app_url", lambda biz: "https://lovecity.example")
    monkeypatch.setattr(nr, "TEXT_PACE", 0)
    f.yes = {M_PHONE}
    f.own = True
    f.texts, f.emails, f.fail_text = [], [], set()

    async def texting(biz, people):
        return (True, set(f.yes)) if f.own else (False, set())

    async def send_sms_core(client, *, business_id, to, message, contact_id=None, sent_by="practitioner"):
        if to in f.fail_text:
            raise sms_service.SmsSendError("no", 402)
        f.texts.append((to, message, contact_id))
        return {"status": "sent"}

    async def send_via_resend(**kw):
        f.emails.append(kw)
    monkeypatch.setattr(nr, "_texting", texting)
    monkeypatch.setattr(sms_service, "send_sms_core", send_sms_core)
    monkeypatch.setattr(email_sender, "send_via_resend", send_via_resend)
    monkeypatch.setattr(email_sender, "_unsubscribe_url", lambda e: f"https://x/unsub?e={e}")
    monkeypatch.setattr(email_layout, "render_html", lambda message, **kw: message)
    monkeypatch.setenv("NEWS_TEXTS_MONTH", "500")
    return f


def _ids(people):
    return sorted(str(p["id"]) for p in people)


# ── 1. who ───────────────────────────────────────────────────────────

def test_the_rest_of_the_church_texted_on_a_yes_and_emailed_otherwise(fake):
    who = nr.plan(CHURCH, _post(), FRI_10)
    assert _ids(who["texts"]) == [MONIQUE] and who["texts"][0]["phone"] == M_PHONE
    assert _ids(who["emails"]) == [PAT]
    # TASHA's phone rings for the app; TEEN is 15; ROCHELLE is a guest; OFFY chose Off
    assert who["phones"] == 1 and who["texting"] is True


def test_never_whoever_posted_it(fake):
    who = nr.plan(CHURCH, _post(posted_by=MONIQUE), FRI_10)
    assert MONIQUE not in _ids(who["texts"]) + _ids(who["emails"])


def test_a_group_post_reaches_only_its_group(fake):
    who = nr.plan(CHURCH, _post(group_id=G), FRI_10)
    assert _ids(who["texts"]) == [MONIQUE] and who["emails"] == []      # PAT isn't in the group


def test_someone_who_muted_news_hears_nothing(fake):
    fake.t["member_push_prefs"].append({"business_id": BIZ, "contact_id": PAT, "off": ["news"]})
    assert _ids(nr.plan(CHURCH, _post(), FRI_10)["emails"]) == []


# ── 2. which way ─────────────────────────────────────────────────────

def test_no_texts_without_the_churchs_own_name(fake):
    fake.own = False
    who = nr.plan(CHURCH, _post(), FRI_10)
    assert who["texts"] == [] and who["texting"] is False
    assert _ids(who["emails"]) == sorted([MONIQUE, PAT])      # she'd have had the text; the email instead


def test_no_text_without_a_yes(fake):
    fake.yes = set()
    assert nr.plan(CHURCH, _post(), FRI_10)["texts"] == []


def test_text_me_important_news_turned_off(fake):
    fake.t["member_push_prefs"].append({"business_id": BIZ, "contact_id": MONIQUE, "off": [], "news_texts": False})
    assert nr.plan(CHURCH, _post(), FRI_10)["texts"] == []


def test_the_months_texts_are_counted(fake, monkeypatch):
    monkeypatch.setenv("NEWS_TEXTS_MONTH", "3")
    fake.t["church_posts"].append(_post(id="p-old", reached_at="2026-10-05T15:00:00+00:00",
                                        reach={"texts": 3, "emails": 0}))
    who = nr.plan(CHURCH, _post(), FRI_10)
    assert who["texts"] == [] and who["used"] == 3 and who["cap"] == 3
    # last month's don't count
    fake.t["church_posts"][0]["reached_at"] = "2026-09-28T15:00:00+00:00"
    assert _ids(nr.plan(CHURCH, _post(), FRI_10)["texts"]) == [MONIQUE]


# ── 3. once ──────────────────────────────────────────────────────────

def test_it_goes_once_and_says_what_went(fake):
    fake.t["church_posts"].append(_post())
    got = nr.reach(CHURCH, _post(), FRI_10)
    assert got == {"texts": 1, "emails": 1, "why": ""}
    assert [t[0] for t in fake.texts] == [M_PHONE]
    assert fake.emails[0]["to_email"] == PAT_MAIL and fake.emails[0]["from_name"] == "Love City Church"
    assert fake.emails[0]["idempotency_key"] == f"church-news-reach-{P1}-{PAT}"
    row = fake.t["church_posts"][0]
    assert row["reached_at"] and row["reach"]["texts"] == 1 and row["reach"]["emails"] == 1
    assert nr.reach(CHURCH, row, FRI_10)["why"] == "not" and len(fake.texts) == 1


def test_only_important_posts(fake):
    fake.t["church_posts"].append(_post(important=False))
    assert nr.reach(CHURCH, _post(important=False), FRI_10)["why"] == "not"
    assert fake.texts == [] and fake.emails == []


def test_quiet_hours_wait_for_the_sweep(fake, monkeypatch):
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "on")          # conftest turns it off for the suite
    fake.t["church_posts"].append(_post(created_at="2026-10-24T02:50:00+00:00"))
    assert nr.reach(CHURCH, _post(created_at="2026-10-24T02:50:00+00:00"), FRI_11PM)["why"] == "later"
    assert fake.t["church_posts"][0]["reached_at"] is None and fake.texts == []


def test_three_a_day(fake):
    fake.t["church_posts"] += [_post(id=f"p{i}", reached_at="2026-10-23T13:00:00+00:00", reach={"texts": 0, "emails": 2})
                               for i in range(3)] + [_post()]
    assert nr.reach(CHURCH, _post(), FRI_10)["why"] == "full"
    assert fake.t["church_posts"][-1]["reach"] == {"why": "full"} and fake.emails == []


def test_a_day_and_a_half_old_is_let_go(fake):
    fake.t["church_posts"].append(_post(created_at="2026-10-21T10:00:00+00:00"))
    assert nr.reach(CHURCH, _post(created_at="2026-10-21T10:00:00+00:00"), FRI_10)["why"] == "old"
    assert fake.t["church_posts"][0]["reach"] == {"why": "old"}


def test_the_church_can_switch_it_off(fake):
    off = {**CHURCH, "settings": {**CHURCH["settings"], "news": {"reach_rest": False}}}
    fake.t["church_posts"].append(_post())
    assert nr.reach(off, _post(), FRI_10)["why"] == "off" and fake.texts == [] and fake.emails == []
    assert nr.church_on(off) is False and nr.church_on(CHURCH) is True


def test_a_failed_read_puts_it_back_for_the_sweep(fake):
    fake.t["church_posts"].append(_post())
    fake.fail.add("member_push_subscriptions")
    assert nr.reach(CHURCH, _post(), FRI_10)["why"] == "busy"
    assert fake.t["church_posts"][0]["reached_at"] is None and fake.texts == [] and fake.emails == []


def test_a_text_that_fails_becomes_the_email(fake):
    fake.t["contacts"][1]["email"] = "monique@example.com"
    fake.t["church_posts"].append(_post())
    fake.fail_text = {M_PHONE}
    got = nr.reach(CHURCH, _post(), FRI_10)
    assert got["texts"] == 0 and sorted(e["to_email"] for e in fake.emails) == ["monique@example.com", PAT_MAIL]


def test_the_sweep_finds_what_waited(fake):
    fake.t["church_posts"] += [_post(), _post(id="p-later", publish_at="2026-10-30T14:00:00+00:00")]
    out = nr.sweep_tick(FRI_10)
    assert out == {"posts": 1, "texts": 1, "emails": 1}
    assert fake.t["church_posts"][1]["reached_at"] is None          # its time hasn't come


def test_an_important_post_going_up_reaches_the_rest(fake, monkeypatch):
    got = []
    monkeypatch.setattr(na, "alert_post", lambda b, p, now=None: None)
    monkeypatch.setattr(nr, "reach", lambda b, p, now=None: got.append(p["id"]))
    na.alert_later(CHURCH, _post(important=False))
    na.alert_later(CHURCH, _post())
    assert got == [P1]


# ── 4. the text ──────────────────────────────────────────────────────

def test_one_plain_part_with_the_name_and_stop_line(fake):
    import sms_service
    import twilio_sms
    long = _post(title="🎉 Big news — our building fund hit its goal and we’re breaking ground on the new "
                       "fellowship hall this Sunday after both services, come celebrate with us")
    words = nr.text_for(CHURCH, long, "https://lovecity.example")
    whole = sms_service.compose_outbound_body("Love City Church", words, include_optout=True)
    assert twilio_sms.is_gsm7(whole) and twilio_sms.segments(whole) == 1
    assert words.endswith(f"https://lovecity.example/my/news/{P1}") and "..." in words and "🎉" not in words
    assert whole.startswith("Love City Church: Big news - our building fund")


def test_a_short_title_goes_whole(fake):
    assert nr.text_for(CHURCH, _post(), None) == "Service moves to 11 AM Sunday. Open the church app to read it."
    assert nr.text_for(CHURCH, _post(title="Pray for the Lees!"), None) == "Pray for the Lees! Open the church app to read it."


# ── 5. the office, the member ────────────────────────────────────────

def test_the_office_sees_what_an_important_post_would_do(fake, monkeypatch):
    import church_news as cn
    monkeypatch.setattr(cn, "_need", lambda biz, user, minimum: biz)
    out = cn.reach_preview(business_id=BIZ, group_id=None, user=None)
    assert out == {"on": True, "phones": 1, "texts": 1, "emails": 1, "texting": True, "used": 0, "cap": 500}


def test_text_me_important_news_on_the_members_page(fake):
    import member_portal_celebrations as mpcel
    html = mpcel._hear({**na._pref(None), "phone": False, "celebrations": True, "texting": True, "texts": False,
                        "tail": "0102"})
    assert "Text me important news" in html and "ending 0102" in html
    assert "Msg &amp; data rates may apply" in html and 'href="/texting-terms"' in html
    assert "Text me important news" not in mpcel._hear({**na._pref(None), "phone": False, "celebrations": True})


def test_the_switch_saves_only_when_the_page_showed_it(fake):
    na.save_prefs(BIZ, MONIQUE, "important", True, True, False)
    assert "news_texts" not in fake.writes[-1][2]
    na.save_prefs(BIZ, MONIQUE, "important", True, True, False, False)
    assert fake.writes[-1][2]["news_texts"] is False


def test_their_yes_is_kept_like_every_other(fake):
    assert nr.record_yes(BIZ, {"id": MONIQUE, "name": "Monique Brown", "phone": "(555) 000-0102"}, "1.2.3.4", "UA")
    row = fake.t["sms_consents"][-1]
    assert row["phone"] == M_PHONE and row["source"] == "member_app" and row["business_id"] == BIZ
    assert not nr.record_yes(BIZ, {"id": PAT, "phone": None})
