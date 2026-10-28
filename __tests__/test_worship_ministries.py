# __tests__/test_worship_ministries.py
#
# Ministries send their own announcements (ChurchSavvy round 5, canvas
# boards 18 and 20; worship_ministries.py). Pins:
#   * the link: signed for one church and one ministry; edited, it fails; a
#     new link retires the old one; a ministry taken out closes its link
#   * the office (the plan's part) adds, changes and takes out ministries;
#     a member can't; two of the same name can't
#   * from the link, with no sign-in: the page's church and ministry; what's
#     sent waits for the office, from that ministry, on Sunday's slides and
#     the lobby only; a picture from anywhere but the church's library is
#     refused; ten waiting from one ministry is the most
#   * a picture from the link goes into the church's library, checked
#   * the office's answer reaches the leader by email, with its note; a
#     typed announcement or a second answer sends nothing
#   * Wednesday from 9 AM on the church's clock, each leader who wants it
#     hears once; not on Tuesday, not twice, not after "stop"

import html
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_worship_show_router as base
import worship_ministries as wm
from test_worship_show_router import BIZ, OTHER_BIZ, api  # noqa: E402,F401  (api is the fixture)


def _match(row, filters):
    """The fake database's filters, with the ones this module asks for: is.true,
    or=(x.is.null,x.lt.Y) and eq. on yes/no columns, as PostgREST reads them."""
    for k, v in filters:
        if k == "or":
            alts = v.strip("()").split(",")
            if not any(_match(row, [(a.split(".", 1)[0], a.split(".", 1)[1])]) for a in alts):
                return False
            continue
        cell = row.get(k)
        if v == "is.null":
            if cell is not None:
                return False
        elif v == "is.true":
            if cell is not True:
                return False
        elif v.startswith("eq."):
            if (str(cell).lower() if isinstance(cell, bool) else str(cell)) != v[3:]:
                return False
        elif v.startswith("lt."):
            if cell is None or str(cell) >= v[3:]:
                return False
        elif v.startswith("gte."):
            if cell is None or str(cell) < v[4:]:
                return False
        elif v.startswith("in.("):
            if str(cell) not in v[4:-1].split(","):
                return False
    return True


@pytest.fixture
def church(api, monkeypatch):
    db, as_, client = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setenv("APP_BASE_URL", "https://system.mysolutionist.app")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(base.FakeDb, "_match", staticmethod(_match))
    for t in ("worship_ministries", "worship_announcements", "worship_media"):
        db.t[t] = []
    import worship_announce_router as war
    client.app.include_router(war.router)
    client.app.include_router(wm.router)
    sent = []

    async def send_via_resend(**kw):
        sent.append(kw)
        return {"id": "e1"}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", send_via_resend)
    return db, as_, client, sent


def add(as_, who="owner", **kw):
    return as_(who).post("/worship/ministries", json={"business_id": BIZ, "name": "Women's ministry", "leader_name": "Gloria Hayes",
                                                      "leader_email": "gloria@lovecity.org", **kw})


def token_of(link):
    return link.rsplit("/send/", 1)[1]


def test_the_link(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    t = wm.sign(BIZ, "m-1", 1)
    assert wm.verify(t) == {"v": 1, "biz": BIZ, "m": "m-1", "n": 1}
    payload, sig = t.split(".")
    # Edited to name another church, it fails its own signature; so does a broken one.
    other = wm.sign(OTHER_BIZ, "m-1", 1).split(".")[0]
    assert wm.verify(f"{other}.{sig}") is None and wm.verify(t + "x") is None and wm.verify("nothing") is None


def test_the_office_keeps_its_ministries(church):
    db, as_, _, _ = church
    r = add(as_)
    assert r.status_code == 200, r.text
    m = r.json()["ministry"]
    assert (m["name"], m["leader_name"], m["remind"]) == ("Women's ministry", "Gloria Hayes", True)
    assert m["link"].startswith("https://system.mysolutionist.app/churchsavvy/send/")
    assert add(as_).status_code == 409                                   # one link per ministry name
    assert add(as_, "member", name="Men's ministry").status_code == 403
    assert add(as_, name="").status_code == 400 and add(as_, name="Youth", leader_email="not-an-email").status_code == 400
    listed = as_("owner").get(f"/worship/ministries?business_id={BIZ}").json()
    assert [x["name"] for x in listed["ministries"]] == ["Women's ministry"] and listed["due"] == "Thursday"
    assert as_("member").get(f"/worship/ministries?business_id={BIZ}").status_code == 403
    saved = as_("owner").put(f"/worship/ministries/{m['id']}", json={"business_id": BIZ, "remind": False})
    assert saved.json()["ministry"]["remind"] is False


def test_a_new_link_and_taking_one_out(church):
    db, as_, _, _ = church
    m = add(as_).json()["ministry"]
    old = token_of(m["link"])
    assert as_("stranger").get(f"/worship/send/{old}").status_code == 200
    fresh = as_("owner").post(f"/worship/ministries/{m['id']}/new-link", json={"business_id": BIZ}).json()["ministry"]
    assert as_("stranger").get(f"/worship/send/{old}").status_code == 410
    new = token_of(fresh["link"])
    assert as_("stranger").get(f"/worship/send/{new}").status_code == 200
    as_("owner").delete(f"/worship/ministries/{m['id']}?business_id={BIZ}")
    assert as_("stranger").get(f"/worship/send/{new}").status_code == 410
    assert as_("stranger").get("/worship/send/made.up").status_code == 410


def form(**kw):
    return {"title": "Women's brunch", "when": "10 AM", "where": "Fellowship Hall", "body": "Brunch and a word from Sister Hayes.",
            "event_on": "2026-11-14", "show_from": "2026-11-01", "shows": {"room": True, "lobby": False, "phones": True, "online": True}, **kw}


def test_a_ministry_sends_one(church):
    db, as_, _, _ = church
    m = add(as_).json()["ministry"]
    t = token_of(m["link"])
    page = as_("stranger").get(f"/worship/send/{t}").json()
    assert (page["church"]["name"], page["ministry"], page["leader"], page["due"]) == ("Love City Church", "Women's ministry", "Gloria", "Thursday")
    r = as_("stranger").post(f"/worship/send/{t}", json={**form(), "business_id": "22222222-2222-4222-8222-222222222222"})
    assert r.status_code == 200, r.text
    row = db.t["worship_announcements"][-1]
    # It waits for the office, from this ministry, at this church (whatever the caller says), room only.
    assert (row["business_id"], row["status"], row["source"], row["source_ref"]) == (BIZ, "waiting", "ministry", m["id"])
    assert row["shows"] == {"room": True, "lobby": False, "online": False, "phones": False}
    assert row["show_until"] == "2026-11-14" and row["sent_by"]["name"] == "Gloria Hayes" and row["sent_by"]["ministry"] == "Women's ministry"
    # The office sees it in Waiting for you.
    board = as_("owner").get(f"/worship/announcements?business_id={BIZ}&day=2026-11-02").json()
    assert board["counts"]["wait"] == 1
    for bad, code in [(form(title=""), 400), (form(shows={"phones": True}), 400),
                      (form(image_url="https://elsewhere.example/flyer.jpg"), 400)]:
        assert as_("stranger").post(f"/worship/send/{t}", json=bad).status_code == code
    for _ in range(wm.MAX_WAITING - 1):
        assert as_("stranger").post(f"/worship/send/{t}", json=form()).status_code == 200
    assert as_("stranger").post(f"/worship/send/{t}", json=form()).status_code == 429


def test_a_picture_from_the_link_goes_to_the_library(church, monkeypatch):
    db, as_, _, _ = church
    import worship_media_router as wmr
    monkeypatch.setattr(wmr, "upload_token", lambda name: "upload-token")
    monkeypatch.setattr(wmr, "resumable_endpoint", lambda: "https://x.supabase.co/storage/v1/upload/resumable")
    monkeypatch.setattr(wmr, "stored_size", lambda name: 2048)
    monkeypatch.setattr(wmr, "read_start", lambda name, limit: b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(wmr, "picture_opens", lambda data: True)
    t = token_of(add(as_).json()["ministry"]["link"])
    assert as_("stranger").post(f"/worship/send/{t}/picture", json={"mime": "video/mp4", "bytes": 2048}).status_code == 400
    assert as_("stranger").post(f"/worship/send/{t}/picture", json={"mime": "image/png", "bytes": 11 * 1024 * 1024}).status_code == 400
    r = as_("stranger").post(f"/worship/send/{t}/picture", json={"mime": "image/png", "bytes": 2048, "name": "brunch"})
    assert r.status_code == 200, r.text
    mid = r.json()["media_id"]
    assert r.json()["upload"]["object_name"] == f"{BIZ}/worship-{mid}.png"
    assert db.t["worship_media"][-1]["name"] == "Women's ministry: brunch"
    done = as_("stranger").post(f"/worship/send/{t}/picture/{mid}")
    assert done.status_code == 200, done.text
    url = done.json()["url"]
    assert url.startswith(wm.picture_prefix(BIZ)) and db.t["worship_media"][-1]["status"] == "ready"
    assert as_("stranger").post(f"/worship/send/{t}", json=form(image_url=url)).status_code == 200
    # Exactly a picture in this church's library: a path that walks to another church's is refused (PR review).
    walk = f"{wm.picture_prefix(BIZ)}../{OTHER_BIZ}/worship-{mid}.png"
    assert as_("stranger").post(f"/worship/send/{t}", json=form(image_url=walk)).status_code == 400
    assert as_("stranger").post(f"/worship/send/{t}", json=form(image_url=url + "?x=1")).status_code == 400
    # A link passed around can't fill the library with half-sent pictures (PR review).
    now = datetime.now(timezone.utc).isoformat()
    db.t["worship_media"] += [{"id": f"u{k}", "business_id": BIZ, "status": "uploading", "archived_at": None, "created_at": now}
                              for k in range(wm.MAX_UPLOADING)]
    assert as_("stranger").post(f"/worship/send/{t}/picture", json={"mime": "image/png", "bytes": 2048}).status_code == 429


def test_the_leader_hears_the_answer(church):
    db, as_, _, sent = church
    t = token_of(add(as_).json()["ministry"]["link"])
    as_("stranger").post(f"/worship/send/{t}", json=form(shows={"room": True, "lobby": True}))
    aid = db.t["worship_announcements"][-1]["id"]
    r = as_("owner").post(f"/worship/announcements/{aid}/decide", json={"business_id": BIZ, "decision": "on", "note": "  Love this. "})
    assert r.status_code == 200 and r.json()["told"] is True
    mail = sent[-1]
    assert mail["to_email"] == "gloria@lovecity.org" and mail["from_name"] == "Love City Church"
    assert mail["subject"] == "“Women's brunch” is on the screens"
    words = html.unescape(mail["body"])          # the email's HTML, read as a person reads it
    assert "on Sunday's slides and in the lobby" in words and "Love this." in words
    assert mail["unsubscribe_url"].endswith(f"/worship/send/{t}/stop")
    # A second answer (it isn't waiting any more) sends nothing.
    again = as_("owner").post(f"/worship/announcements/{aid}/decide", json={"business_id": BIZ, "decision": "declined"})
    assert again.json()["told"] is False and len(sent) == 1
    # Not this time, with the office's note.
    as_("stranger").post(f"/worship/send/{t}", json=form(title="Men's breakfast"))
    aid2 = db.t["worship_announcements"][-1]["id"]
    as_("owner").post(f"/worship/announcements/{aid2}/decide", json={"business_id": BIZ, "decision": "declined", "note": "Can you send a picture?"})
    assert sent[-1]["subject"] == "“Men's breakfast” isn't on the screens this time" and "Can you send a picture?" in html.unescape(sent[-1]["body"])
    assert as_("owner").post(f"/worship/announcements/{aid2}/decide", json={"business_id": BIZ, "decision": "on", "note": "x" * 301}).status_code == 400


def test_wednesdays_reminder(church, monkeypatch):
    db, as_, client, sent = church
    import worship_announce_router as war
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(war, "church_zone", lambda biz: ZoneInfo("America/New_York"))
    t = token_of(add(as_).json()["ministry"]["link"])
    add(as_, name="Men's ministry", leader_email="", leader_name="Ray Ellis")          # no email: nobody to remind
    tuesday = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)                         # 10 AM in New York
    wed_early = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)                       # 7 AM
    wed = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)                             # 10 AM
    assert wm.sweep_tick(tuesday)["reminded"] == 0 and wm.sweep_tick(wed_early)["reminded"] == 0
    assert wm.sweep_tick(wed)["reminded"] == 1
    mail = sent[-1]
    words = html.unescape(mail["body"])
    assert mail["subject"] == "Anything for Sunday?" and "Hi Gloria, anything from Women's ministry" in words
    assert "Send it by Thursday" in words
    assert wm.sweep_tick(wed)["reminded"] == 0                                         # once a week
    # "Stop these reminders" from the email: next Wednesday, nothing.
    assert client.post(f"/worship/send/{t}/stop").status_code == 200
    assert wm.sweep_tick(datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc))["reminded"] == 0
    # Started again from the page: it comes back.
    assert client.post(f"/worship/send/{t}/reminders", json={"on": True}).json()["remind"] is True
    assert wm.sweep_tick(datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc))["reminded"] == 1
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert wm.sweep_tick(datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)) == {"reminded": 0, "failed": 0}
    assert client.get(f"/worship/send/{t}").status_code == 404


def test_a_reminder_that_fails_is_tried_again(church, monkeypatch):
    """The weekly claim goes back when the email fails, so the next sweep tries (PR review)."""
    db, as_, client, sent = church
    import email_sender
    import worship_announce_router as war
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(war, "church_zone", lambda biz: ZoneInfo("America/New_York"))
    add(as_)
    real = email_sender.send_via_resend

    async def down(**kw):
        raise RuntimeError("Resend is down")

    monkeypatch.setattr(email_sender, "send_via_resend", down)
    wed = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
    assert wm.sweep_tick(wed) == {"reminded": 0, "failed": 1}
    assert db.t["worship_ministries"][0]["reminded_on"] is None
    monkeypatch.setattr(email_sender, "send_via_resend", real)
    assert wm.sweep_tick(datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc))["reminded"] == 1


def test_the_link_is_a_gate_the_ownership_sweep_sees():
    import ownership_sweep
    gaps = [h for h in ownership_sweep.sweep()["unguarded"] if h["file"] == "worship_ministries.py"]
    assert gaps == []


def test_mounted_before_the_public_site_catch_all():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.index("include_router(worship_ministries_router)") < src.index("include_router(public_site_router)")
    assert 'id="ministry_reminders"' in src
