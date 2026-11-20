# __tests__/test_member_posts_birthday.py
#
# Their birthday, asked once when they tap Post (member_posts; Kevin,
# 2026-11-20: "yes ask for the birthday when they tap post"):
#   - an adult with no birthdate on record is asked in the composer (only
#     while a group is picked), and Post saves the birthday and the post;
#   - it goes on their own record only (contacts.metadata.member_birthdate),
#     never contacts.birthdate, never anyone else's record;
#   - a teen's age gets the teen rules; under 13 isn't kept and doesn't post;
#   - once given it can't be changed from the app; the office's birthdate wins;
#   - it counts for posting only: it never opens messaging, and never makes
#     anyone one of a group's two approved adults;
#   - the owner's preview saves nothing; with the new look off nothing here
#     writes and the composer isn't there;
#   - the session's record carries it (no read of its own).

import copy
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_messaging_rules as rules
import member_portal_messaging as mpm
import member_posts as mpo
import test_member_messaging as tmm
from test_member_posts import _client, _page, _post, _posts, world  # noqa: F401  (fixture)
from test_member_group_chat import church as gchurch  # noqa: F401  (fixture)
from test_member_messaging import env  # noqa: F401  (fixture)

T = date.today()
ADULT = date(T.year - 35, 4, 12).isoformat()
TEEN_AGE = date(T.year - 15, 1, 1).isoformat()
CHILD = date(T.year - 10, 1, 1).isoformat()
NOBODY = tmm.NOBIRTH                                         # Nora: no birthdate on her record


def _nora(env):
    return next(c for c in env.t["contacts"] if c["id"] == NOBODY)


def _join(env, who=NOBODY, group=tmm.GRP, role="member"):
    env.t["group_members"].append({"group_id": group, "contact_id": who, "business_id": tmm.BIZ, "role": role})


def _given(env, who=NOBODY):
    c = next(x for x in env.t["contacts"] if x["id"] == who)
    return (c.get("metadata") or {}).get(mpo.BDAY_KEY)


def _say(env, text, birthday=None, who=NOBODY, **extra):
    data = {"type": "praise", "to": tmm.GRP, "body": text, **extra}
    if birthday is not None:
        data["birthday"] = birthday
    return _post(env, who, data)


# ─── asked, saved, posted ────────────────────────────────────────────


def test_an_adult_without_a_birthdate_is_asked_saves_and_posts(world):
    _join(world)
    html = _page(world, NOBODY, f"/my/post?group={tmm.GRP}").text
    assert 'name="birthday"' in html and "Your birthday" in html
    assert "We ask once. It keeps teens safe in groups." in html
    # Above Post, after the check's promise.
    assert html.index("Every post is checked") < html.index('name="birthday"') < html.index(">Post</button>")
    r = _say(world, "So thankful for this group", ADULT)
    assert r.status_code == 303 and r.headers["location"] == f"/my/groups/{tmm.GRP}?done=posted"
    assert _given(world) == ADULT and _nora(world)["birthdate"] is None     # never contacts.birthdate
    (p,) = _posts(world)
    assert p["posted_by"] == NOBODY and p["body"] == "So thankful for this group"
    # Asked once: the composer doesn't ask again.
    assert 'name="birthday"' not in _page(world, NOBODY, f"/my/post?group={tmm.GRP}").text


def test_someone_with_a_birthdate_on_record_is_never_asked(world):
    html = _page(world, tmm.ANA, f"/my/post?group={tmm.GRP}").text
    assert 'name="birthday"' not in html and "We ask once" not in html


def test_asked_only_while_a_group_is_on_offer(world):
    _join(world)
    world.biz["settings"].setdefault("member_portal", {})["member_posts"] = False
    html = _page(world, NOBODY, "/my/post").text
    assert 'name="birthday"' not in html                      # the whole church needs no birthday
    # The whole church takes no birthday and saves none.
    world.biz["settings"]["member_portal"].pop("member_posts")
    r = _post(world, NOBODY, {"type": "praise", "to": "church", "share_kind": "job", "body": "New job!", "birthday": ADULT})
    assert r.headers["location"] == "/my/post?done=shared" and _given(world) is None
    # The script shows the field only while a group is picked.
    assert "b.hidden=!!c" in mpo.POST_JS and "d.required=!c" in mpo.POST_JS


def test_no_birthday_or_a_date_that_isnt_real_saves_nothing(world):
    _join(world)
    future = date(T.year + 1, 1, 1).isoformat()
    for given, code in (("", "post_birthday"), ("not a date", "post_birthday_bad"), (f"{T.year - 20}-02-30", "post_birthday_bad"),
                        (future, "post_birthday_bad"), (date(T.year - 111, 1, 1).isoformat(), "post_birthday_bad"),
                        ("01/02/1990", "post_birthday_bad")):
        r = _say(world, "Hello", given)
        assert f"err={code}&group={tmm.GRP}" in r.headers["location"], given
    assert _given(world) is None and not _posts(world)
    assert "birthday" in mpo.ERRORS["post_birthday"].lower()


# ─── teens and children ──────────────────────────────────────────────


def test_a_teens_age_gets_the_teen_rules(world):
    _join(world)
    r = _say(world, "Hi everyone", TEEN_AGE)
    # Saved, then the teen rules: messaging isn't on for her (it needs the
    # office's birthdate), so the existing teen wording, and nothing posts.
    assert "err=post_teen_off" in r.headers["location"] and _given(world) == TEEN_AGE and not _posts(world)
    html = _page(world, NOBODY, f"/my/post?err=post_teen_off&group={tmm.GRP}").text.replace("&#x27;", "'")
    assert mpo.ERRORS["post_teen_off"] in html and 'name="birthday"' not in html
    # She's a teen in the group now: it needs two adult leaders (it has one).
    r = _say(world, "Hello", who=tmm.ANA)
    assert "err=post_two_adults" in r.headers["location"] and not _posts(world)


def test_under_13_is_refused_and_nothing_is_kept(world):
    _join(world)
    r = _say(world, "Hi", CHILD)
    assert r.headers["location"] == f"/my/post?err=post_child&group={tmm.GRP}"
    assert _given(world) is None and not _posts(world)
    line = mpo.ERRORS["post_child"]
    assert "parent" in line and "church office" in line
    html = _page(world, NOBODY, f"/my/post?err=post_child&group={tmm.GRP}").text
    assert line in html.replace("&#x27;", "'") and 'name="birthday"' in html


# ─── asked once; the office wins ─────────────────────────────────────


def test_once_given_it_cant_be_changed_from_the_app(world):
    _join(world)
    assert "done=posted" in _say(world, "One", ADULT).headers["location"]
    r = _say(world, "Two", TEEN_AGE)                          # a different date, sent anyway
    assert "done=posted" in r.headers["location"] and _given(world) == ADULT
    assert mpo.save_birthdate(tmm.BIZ, NOBODY, TEEN_AGE) == "kept" and _given(world) == ADULT
    # Even a teen who'd like to be an adult: hers stays.
    _nora(world)["metadata"] = {mpo.BDAY_KEY: TEEN_AGE}
    assert mpo.save_birthdate(tmm.BIZ, NOBODY, ADULT) == "kept" and _given(world) == TEEN_AGE
    assert "err=post_teen_off" in _say(world, "Three", ADULT).headers["location"]


def test_the_office_birthdate_wins(world):
    _join(world)
    _nora(world)["metadata"] = {mpo.BDAY_KEY: ADULT}
    _nora(world)["birthdate"] = TEEN_AGE                       # the office says she's a teen
    # The teen rules (her messaging is on, so her group needs its two adult leaders).
    assert "err=post_two_adults" in _say(world, "Hi").headers["location"] and not _posts(world)
    _nora(world)["birthdate"] = "1980-05-05"                   # the office says adult; she'd typed a teen's
    _nora(world)["metadata"] = {mpo.BDAY_KEY: TEEN_AGE}
    assert "done=posted" in _say(world, "Hi").headers["location"]
    # With the office's on record, nothing is written.
    _nora(world)["metadata"] = {}
    assert mpo.save_birthdate(tmm.BIZ, NOBODY, ADULT) == "kept" and _given(world) is None
    assert mpo.posting_birthdate({"birthdate": "1980-05-05", "bday": TEEN_AGE}) == "1980-05-05"


# ─── posting only: never messaging ───────────────────────────────────


def test_a_typed_birthday_never_unlocks_messaging(world):
    _join(world)
    assert "done=posted" in _say(world, "Hi", ADULT).headers["location"]
    nora = dict(_nora(world), bday=ADULT)                      # as the session's record carries it
    # Messaging reads contacts.birthdate alone: still "no birthdate".
    full = mpm._me_profile(tmm.BIZ, nora)
    assert full["enabled"] and not rules.can_message(full) and rules.why_not(full) == "no_birthdate"
    assert not rules.can_message(nora | {"enabled": True})
    ok, why = rules.direct(full, mpm._me_profile(tmm.BIZ, {"id": tmm.BEN}), guardians_of={}, blocked=set(), share_group=True)
    assert not ok and why == "sender_off"
    # Her messages page and a chat with Ana both still say so.
    page = tmm._member(world, NOBODY).get("/my/messages").text
    assert "birthdate" in page
    loc = tmm._member(world, NOBODY).get(f"/my/messages/to/{tmm.ANA}", follow_redirects=False).headers.get("location", "")
    assert not world.t["msg_threads"] and "/my/messages/0" not in loc
    # Nor one of a group's two approved adults: a leader with only a typed
    # adult birthday doesn't open a teen's group.
    _join(world, NOBODY, tmm.YOUTH, "leader")
    r = _post(world, tmm.TEEN, {"type": "praise", "to": tmm.YOUTH, "body": "Hi"})
    assert "err=post_two_adults" in r.headers["location"]
    people = [mpo._as_posting(dict(p, enabled=True, role=p.get("role"))) for p in
              [dict(_nora(world), role="leader"), dict(next(c for c in world.t["contacts"] if c["id"] == tmm.CARL), role="leader"),
               next(c for c in world.t["contacts"] if c["id"] == tmm.TEEN)]]
    assert rules.group_chat(people) == (False, "two_adults")


# ─── whose record ────────────────────────────────────────────────────


def test_another_members_row_is_never_written(world):
    _join(world)
    before = {c["id"]: copy.deepcopy(c) for c in world.t["contacts"] if c["id"] != NOBODY}
    r = _say(world, "Hi", ADULT, contact_id=tmm.ANA, id=tmm.BEN, me=tmm.CARL)
    assert "done=posted" in r.headers["location"] and _given(world) == ADULT
    assert {c["id"]: c for c in world.t["contacts"] if c["id"] != NOBODY} == before
    # The write names her own record and church, guarded by updated_at.
    seen = []
    import sb_clients
    real = sb_clients.sb_patch_as_service

    def spy(path, body):
        seen.append(path)
        return real(path, body)
    sb_clients.sb_patch_as_service = spy
    try:
        _nora(world)["metadata"] = {}
        mpo.save_birthdate(tmm.BIZ, NOBODY, ADULT)
    finally:
        sb_clients.sb_patch_as_service = real
    assert seen == [f"/contacts?id=eq.{NOBODY}&business_id=eq.{tmm.BIZ}&updated_at=is.null"]


# ─── the preview, the switch ─────────────────────────────────────────


def test_the_preview_saves_nothing(world):
    _join(world)
    r = _client(world, NOBODY, preview=True).post("/my/post", data={"type": "praise", "to": tmm.GRP, "body": "Hi",
                                                                    "birthday": ADULT},
                                                  headers=tmm.ORIGIN, follow_redirects=False)
    assert "err=preview" in r.headers["location"] and _given(world) is None and not _posts(world)


def test_with_the_new_look_off_nothing_changes(world, monkeypatch):
    _join(world)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = _say(world, "Hi", ADULT)
    assert r.headers["location"] == "/my" and _given(world) is None and not _posts(world)
    r = _page(world, NOBODY, f"/my/post?group={tmm.GRP}")
    assert r.status_code == 303 and r.headers["location"] == "/my"


# ─── the session's record carries it ─────────────────────────────────


def test_the_sessions_record_reads_it_with_no_read_of_its_own(monkeypatch):
    import member_portal as mp
    import member_portal_preview as pv
    import sb_clients
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: seen.append(path) or [])
    mp.contacts_for_email(tmm.BIZ, "nora@example.com")
    mp.contacts_for_phone(tmm.BIZ, "555-010-2030")
    pv.load_contact(tmm.BIZ, NOBODY)
    assert len(seen) == 3 and all("bday:metadata-%3Emember_birthdate" in p or "bday:metadata->member_birthdate" in p
                                  for p in seen)
    assert mpo.given_birthdate({"bday": ADULT}) == ADULT
    assert mpo.given_birthdate({"metadata": {mpo.BDAY_KEY: ADULT}}) == ADULT
    assert mpo.given_birthdate({"bday": "1900-01-01"}) is None and mpo.given_birthdate({"bday": "soon"}) is None
    assert mpo.check_birthdate(ADULT) == (ADULT, "") and mpo.check_birthdate(CHILD) == ("", "post_child")
