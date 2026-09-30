"""The member app (Broadcast look, 2026-09-30): Home, Sermons, Me, the
bottom bar, and the look's own guards."""
import member_app_ui as ui
import member_portal_church as mpc
import member_portal_sermons as mps
from public_form_theme import contrast

BIZ = {"id": "b1", "name": "First Light", "settings": {}}
ME = {"id": "c1", "name": "Ana Rivers", "email": "ana@example.com"}
S1 = "11111111-1111-1111-1111-111111111111"
S2 = "22222222-2222-2222-2222-222222222222"
K = "33333333-3333-3333-3333-333333333333"


def _lib():
    return {"series": [{"id": K, "title": "Kingdom Order", "description": "How God orders a life."}],
            "sermons": [
                {"id": S1, "series_id": K, "title": "God's order for families", "preached_on": "2026-09-27",
                 "speaker": "Pastor Ana", "scripture": "1 Corinthians 11:3", "summary": "Order is love.",
                 "questions": "Where is order missing?", "video_url": "https://youtu.be/abc123", "audio_url": "",
                 "published": True},
                {"id": S2, "series_id": None, "title": "Deliverance", "preached_on": "2026-09-13",
                 "speaker": "", "scripture": "Luke 11:20", "summary": "", "questions": "", "video_url": "",
                 "audio_url": "", "published": True},
            ]}


# ─── the look ────────────────────────────────────────────────────────


def test_a_dark_brand_accent_becomes_gold_and_a_bright_one_is_kept():
    assert ui.accent_for({"accent": "#0B2146"}) == ui.GOLD          # navy would vanish on the ground
    assert ui.accent_for({"accent": "#F4AE3D"}) == "#F4AE3D"
    assert contrast(ui.accent_for({"accent": "#334155"}), ui.GROUND) >= 3


def test_a_series_is_the_same_colour_everywhere():
    assert ui.poster_colour(K) == ui.poster_colour(K)
    assert ui.poster_colour(K) in ui.POSTERS


def test_the_bar_marks_the_current_tab_and_sign_in_has_none():
    import member_portal as mp
    page = mp._shell(BIZ, None, "Home", "<p>x</p>", tab="home", who=ME)
    assert 'href="/my" aria-current="page"' in page and 'aria-label="Main"' in page
    assert 'href="/my/me" aria-label="Me">AR<' in page
    assert 'aria-label="Main"' not in mp.render_signin(BIZ, None)


# ─── Home ────────────────────────────────────────────────────────────


def _occ(eid, title, mine=None, day="2026-10-04", roles=None):
    return {"entry_id": eid, "title": title, "date": day, "date_label": "Sunday, October 4", "location": "Sanctuary",
            "capacity": None, "full": False, "roles": roles or [], "mine": mine}


def test_your_week_is_what_i_said_yes_to_and_my_groups():
    occ = [_occ("e1", "Sunday Worship", {"status": "yes", "role": "greet"},
                roles=[{"id": "greet", "label": "Greeter", "needed": 2, "filled": 1, "full": False}]),
           _occ("e2", "Picnic", {"status": "no"}), _occ("e3", "Prayer night")]
    groups = {"mine": [{"id": "g1", "name": "Tuesday Night Group", "meets": "Tuesdays 7 pm", "location": ""}], "open": []}
    week = mpc.week_list(occ, groups)
    assert "Sunday Worship" in week and "You&#x27;re serving: Greeter" in week and "Tuesday Night Group" in week
    assert "Picnic" not in week and "Prayer night" not in week
    assert mpc.week_list([], {"mine": [], "open": []}) == ""


def test_coming_up_offers_only_what_i_havent_answered():
    occ = [_occ("e1", "Sunday Worship", {"status": "yes"}), _occ("e2", "Prayer night")]
    html = mpc.coming_up(occ)
    assert "Prayer night" in html and "Sunday Worship" not in html
    assert "answered everything" in mpc.coming_up([_occ("e1", "Sunday Worship", {"status": "yes"})])
    assert "couldn't load" in mpc.coming_up(None)
    assert mpc.next_strip(occ).count("Sunday Worship") == 1 and mpc.next_strip(None) == ""


def test_home_leads_with_the_latest_message():
    import member_portal as mp
    page = mp.render_home(BIZ, None, me=ME, occasions=[], groups={"mine": [], "open": []}, library=_lib(),
                          give_url="/give")
    assert "Hi, Ana" in page and "God&#x27;s order for families" in page and "Kingdom Order" in page
    assert "Pastor Ana · 1 Corinthians 11:3" in page and 'href="/give"' in page
    # Nothing published, or the read failed: Home simply has no message card.
    empty = mp.render_home(BIZ, None, me=ME, occasions=[], groups=None, library=None, give_url="")
    assert "Latest message" not in empty and 'href="/give"' not in empty


# ─── Sermons ─────────────────────────────────────────────────────────


def test_the_shelf_shows_series_posters_and_loose_messages():
    page = mps.render_library(BIZ, None, ME, _lib())
    assert f'href="/my/sermons?series={K}"' in page and "1 message · Now" in page
    assert "More messages" in page and "Deliverance" in page
    assert 'aria-current="page"' in page and 'href="/my/sermons" aria-current' in page


def test_a_failed_read_is_said_never_no_messages():
    page = mps.render_library(BIZ, None, ME, None)
    assert "couldn't load" in page and "No messages" not in page
    assert "No messages are posted yet" in mps.render_library(BIZ, None, ME, {"sermons": [], "series": []})


def test_one_series_and_one_message():
    series = mps.render_library(BIZ, None, ME, _lib(), K)
    assert "Kingdom Order" in series and "How God orders a life." in series and "Deliverance" not in series
    msg = mps.render_sermon(BIZ, None, ME, _lib(), S1)
    assert 'class="mb-video"' in msg and "youtube-nocookie.com/embed/abc123" in msg
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in msg
    assert "For your group this week" in msg and "Order is love." in msg
    assert mps.render_sermon(BIZ, None, ME, _lib(), "44444444-4444-4444-4444-444444444444") is None
    assert "isn't posted yet" in mps.render_sermon(BIZ, None, ME, _lib(), S2)


def test_only_published_messages_are_loaded(monkeypatch):
    rows = {"sermons": [dict(_lib()["sermons"][0]), {**_lib()["sermons"][1], "published": False}], "series": []}
    monkeypatch.setattr(mps.sb_clients, "sb_get_as_service",
                        lambda p: rows["sermons"] if p.startswith("/sermons") else rows["series"])
    lib = mps.load_library("b1")
    assert [s["id"] for s in lib["sermons"]] == [S1]
    monkeypatch.setattr(mps.sb_clients, "sb_get_as_service", lambda p: None)
    assert mps.load_library("b1") is None
