"""Free classes people join themselves (academy_join.py, phase 4b).

The database half (academy_course_open, academy_public_join,
academy_join_track) was rehearsed against production in a rolled-back
transaction (see the worklog). These tests hold the server's rules: the
form shows only on a free, open class; the class link goes to the inbox
and never onto the page; the page reads the same however the join went;
the owner hears about new people and about someone they took off.
"""
import asyncio
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import academy_join as aj
import email_layout
import public_site as ps
import rate_limit

BIZ = "00000000-0000-4000-8000-0000000000b1"
COURSE = "00000000-0000-4000-8000-0000000000c1"
CONTACT = "00000000-0000-4000-8000-0000000000d1"
ENROLLMENT = "00000000-0000-4000-8000-0000000000e1"
TOKEN = "00000000-0000-4000-8000-00000000f00d"
OPEN = {"id": COURSE, "business_id": BIZ, "title": "New Members", "status": "published",
        "self_join": True, "product_id": None}


# ─── The rule and the form ───────────────────────────────────────────

def test_only_a_published_free_class_its_owner_left_open_takes_sign_ups():
    assert aj.join_open(OPEN)
    assert not aj.join_open({**OPEN, "self_join": False})
    assert not aj.join_open({**OPEN, "status": "draft"})
    # a class with a product is joined by paying, even before its checkout link exists
    assert not aj.join_open({**OPEN, "product_id": "p1"})
    # a row read before the column existed counts as open (the column's default)
    assert aj.join_open({k: v for k, v in OPEN.items() if k != "self_join"})


def test_the_form_posts_to_the_class_page_and_carries_a_hidden_bot_field():
    box = aj.join_box(f"/academy/{COURSE}/join", "#C2125F", name='Dana "D"', error="Enter your name")
    assert f'method="post" action="/academy/{COURSE}/join"' in box
    assert 'name="name" required' in box and 'name="email" type="email" required' in box
    assert 'class="join-hp" aria-hidden="true"' in box and 'name="website" tabindex="-1"' in box
    assert 'value="Dana &quot;D&quot;"' in box and 'role="alert">Enter your name' in box
    assert ">Free<" in box and "Join the class" in box


def test_addresses_and_names_are_cleaned_before_anything_is_stored():
    assert aj.clean_name("  Dana \n  Smith ") == "Dana Smith"
    assert len(aj.clean_name("x" * 500)) == 120
    assert aj.valid_email("dana@example.com")
    for bad in ("dana", "dana@", "@x.com", "dana@x", "a b@x.com", "dana@x.com>evil"):
        assert not aj.valid_email(bad), bad
    # the shared rate window never holds the address itself
    assert "dana" not in aj._digest("dana@example.com")


def test_the_next_class_reads_like_a_person_wrote_it():
    assert aj._clock(datetime(2026, 10, 22, 19, 0)) == "Thursday, October 22 at 7 PM"
    assert aj._clock(datetime(2026, 10, 22, 18, 30)) == "Thursday, October 22 at 6:30 PM"
    assert aj._clock(datetime(2026, 10, 25, 0, 15)) == "Sunday, October 25 at 12:15 AM"
    assert aj._clock(datetime(2026, 10, 25, 12, 0)) == "Sunday, October 25 at 12 PM"


# ─── The class page ──────────────────────────────────────────────────

def _page_for(monkeypatch, course, product=None):
    async def fake_sb(client, path):
        if path.startswith("/academy_courses"):
            return [course]
        if path.startswith("/academy_lessons"):
            return [{"title": "Welcome Home", "duration_minutes": 30, "lesson_type": "text"}]
        if path.startswith("/products"):
            return [product] if product else []
        return []

    async def fake_brand(client, biz):
        return "Love City Church", "#C2125F", {}, {}

    monkeypatch.setattr(ps, "_sb_service", fake_sb)
    monkeypatch.setattr(ps, "_academy_brand", fake_brand)
    monkeypatch.setattr(ps, "_academy_skin", lambda *a: ("#C2125F", ""))
    monkeypatch.setattr(ps, "_inject_brand_meta", lambda html, biz: html)
    monkeypatch.setattr(aj, "next_class_line", lambda biz, cid: "Thursday, October 22 at 7 PM")
    resp = asyncio.run(ps._serve_academy(None, BIZ, f"/academy/{COURSE}", standalone=False))
    return resp.body.decode()


def test_a_free_open_class_page_has_the_join_form_and_when_it_next_meets(monkeypatch):
    page = _page_for(monkeypatch, {**OPEN, "description": "Your first steps.", "drip_mode": "none"})
    assert f'action="/academy/{COURSE}/join"' in page and "Join the class" in page
    assert "Get in touch" not in page and "Enroll now" not in page
    assert "Next live class: Thursday, October 22 at 7 PM" in page
    assert ".join-fields" in page  # the form's own styles came with it


def test_a_class_its_owner_closed_still_says_get_in_touch(monkeypatch):
    page = _page_for(monkeypatch, {**OPEN, "self_join": False, "drip_mode": "none"})
    assert "Get in touch" in page and "/join" not in page


def test_a_paid_class_still_sells(monkeypatch):
    page = _page_for(monkeypatch, {**OPEN, "product_id": "p1", "drip_mode": "none"},
                     product={"price": 97, "stripe_payment_url": "https://buy.stripe.com/x"})
    assert "Enroll now" in page and "$97" in page and "/join" not in page


def test_a_standalone_academy_posts_to_its_own_course_address(monkeypatch):
    async def fake_sb(client, path):
        return [{**OPEN, "drip_mode": "none"}] if path.startswith("/academy_courses") else []

    async def fake_brand(client, biz):
        return "Rivera Bookkeeping", "#0F766E", {}, {}

    monkeypatch.setattr(ps, "_sb_service", fake_sb)
    monkeypatch.setattr(ps, "_academy_brand", fake_brand)
    monkeypatch.setattr(ps, "_academy_skin", lambda *a: ("#0F766E", ""))
    monkeypatch.setattr(ps, "_inject_brand_meta", lambda html, biz: html)
    monkeypatch.setattr(aj, "next_class_line", lambda biz, cid: "")
    page = asyncio.run(ps._serve_academy(None, BIZ, f"/course/{COURSE}", standalone=True)).body.decode()
    assert f'action="/course/{COURSE}/join"' in page and "Next live class" not in page


# ─── The join ────────────────────────────────────────────────────────

@pytest.fixture
def joined(monkeypatch):
    """A test client with the database and the mail out of reach."""
    calls = {"enroll": [], "after": [], "limits": []}
    state = {"course": dict(OPEN), "outcome": {"state": "joined", "token": TOKEN, "enrollment_id": ENROLLMENT,
                                                "contact_id": CONTACT, "known_as": "Dana Smith"},
             "allow": set()}

    def allow(bucket, key, **kw):
        calls["limits"].append((bucket, key))
        return bucket not in state["allow"]

    async def look(biz):
        return "Love City Church", "#C2125F", "<style></style>"

    def enroll(course, name, email):
        calls["enroll"].append((name, email))
        return state["outcome"]

    async def after(course, name, email, outcome):
        calls["after"].append((name, email, outcome["state"]))

    monkeypatch.setattr(rate_limit, "allow_strict", allow)
    monkeypatch.setattr(rate_limit, "trusted_client_ip", lambda r: "203.0.113.9")
    monkeypatch.setattr(aj, "_course", lambda cid: [state["course"]] if state["course"] else [])
    monkeypatch.setattr(aj, "_look", look)
    monkeypatch.setattr(aj, "enroll", enroll)
    monkeypatch.setattr(aj, "after_join", after)
    app = FastAPI()
    app.include_router(aj.router)
    return TestClient(app), calls, state


def _post(client, data, path=f"/academy/{COURSE}/join"):
    return client.post(path, data=data)


def test_a_new_person_is_told_to_check_their_email_and_never_shown_the_link(joined):
    client, calls, state = joined
    r = _post(client, {"name": "  Dana   Smith ", "email": "Dana@Example.com "})
    assert r.status_code == 200 and "Check your email" in r.text
    assert "dana@example.com" in r.text and TOKEN not in r.text and "classroom" not in r.text
    assert calls["enroll"] == [("Dana Smith", "dana@example.com")]
    assert calls["after"] == [("Dana Smith", "dana@example.com", "joined")]
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    # the per-address limits are keyed on the business and a digest, never the address
    keys = [k for b, k in calls["limits"] if b.startswith("class_join_email")]
    assert keys and all(k.startswith(BIZ + "|") and "dana" not in k for k in keys)


def test_the_page_reads_the_same_whether_new_already_in_or_taken_off(joined):
    client, calls, state = joined
    pages = []
    for outcome in ({"state": "joined", "token": TOKEN}, {"state": "already", "token": TOKEN},
                    {"state": "dropped", "token": None}):
        state["outcome"] = {**outcome, "enrollment_id": ENROLLMENT, "contact_id": CONTACT, "known_as": "Dana Smith"}
        r = _post(client, {"name": "Dana Smith", "email": "dana@example.com"})
        assert r.status_code == 200
        pages.append(r.text)
    assert pages[0] == pages[1] == pages[2]


def test_a_bot_that_fills_the_hidden_field_gets_the_same_page_and_nothing_is_made(joined):
    client, calls, state = joined
    r = _post(client, {"name": "Dana", "email": "dana@example.com", "website": "http://spam.example"})
    assert r.status_code == 200 and "Check your email" in r.text
    assert calls["enroll"] == [] and calls["after"] == []


def test_a_missing_name_or_a_bad_address_comes_back_with_the_form(joined):
    client, calls, state = joined
    r = _post(client, {"name": "", "email": "dana@example.com"})
    assert r.status_code == 400 and "Enter your name and the email" in r.text
    assert f'action="/academy/{COURSE}/join"' in r.text and 'value="dana@example.com"' in r.text
    r = _post(client, {"name": "Dana", "email": "dana@nowhere"})
    assert r.status_code == 400 and calls["enroll"] == []


def test_a_closed_class_says_so_without_taking_anyone(joined):
    client, calls, state = joined
    state["course"] = {**OPEN, "self_join": False}
    r = _post(client, {"name": "Dana", "email": "dana@example.com"})
    assert "Sign-ups are closed here" in r.text and "Love City Church" in r.text
    assert calls["enroll"] == []
    # and a class closed between the page and the press (the database's own answer)
    state["course"] = dict(OPEN)
    state["outcome"] = {"state": "closed"}
    r = _post(client, {"name": "Dana", "email": "dana@example.com"})
    assert "Sign-ups are closed here" in r.text and calls["after"] == []


def test_the_limits_answer_before_anything_is_made(joined):
    client, calls, state = joined
    state["allow"] = {"class_join_email_minute"}
    r = _post(client, {"name": "Dana", "email": "dana@example.com"})
    assert r.status_code == 429 and "just sent" in r.text and calls["enroll"] == []
    state["allow"] = {"class_join_ip"}
    r = _post(client, {"name": "Dana", "email": "dana@example.com"})
    assert r.status_code == 429 and "this network" in r.text and calls["enroll"] == []


def test_when_storage_fails_the_person_is_asked_to_try_again_not_to_check_their_email(joined):
    client, calls, state = joined
    state["outcome"] = None
    r = _post(client, {"name": "Dana", "email": "dana@example.com"})
    assert r.status_code == 503 and "Nothing was saved" in r.text and "Check your email" not in r.text
    assert calls["after"] == []


def test_unknown_classes_and_bad_ids_are_not_found(joined):
    client, calls, state = joined
    assert _post(client, {"name": "D", "email": "d@x.com"}, "/academy/not-an-id/join").status_code == 404
    state["course"] = None
    assert _post(client, {"name": "D", "email": "d@x.com"}).status_code == 404


def test_a_standalone_academy_address_joins_the_same_way(joined):
    client, calls, state = joined
    r = _post(client, {"name": "Dana", "email": "dana@example.com"}, f"/course/{COURSE}/join")
    assert r.status_code == 200 and f'href="/course/{COURSE}"' in r.text


# ─── The contact and the one database step ───────────────────────────

def test_an_existing_person_is_enrolled_as_themselves(monkeypatch):
    import lead_identity
    import sb_clients
    posts = []
    monkeypatch.setattr(lead_identity, "find", lambda *a, **k: {"id": CONTACT, "name": "Dana Smith"})
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, *a, **k: posts.append((path, body)) or {"state": "already", "token": TOKEN})
    out = aj.enroll(OPEN, "Dana", "dana@example.com")
    assert posts == [("/rpc/academy_public_join", {"p_course": COURSE, "p_contact": CONTACT})]
    assert out["state"] == "already" and out["known_as"] == "Dana Smith" and out["contact_id"] == CONTACT


def test_someone_new_becomes_a_contact_first(monkeypatch):
    import lead_identity
    import sb_clients
    posts = []

    def post(path, body, *a, **k):
        posts.append((path, body))
        return [{"id": CONTACT}] if path == "/contacts" else {"state": "joined", "token": TOKEN}

    monkeypatch.setattr(lead_identity, "find", lambda *a, **k: None)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    out = aj.enroll(OPEN, "Dana Smith", "dana@example.com")
    assert posts[0][0] == "/contacts"
    assert posts[0][1]["source"] == "class_signup" and posts[0][1]["business_id"] == BIZ
    assert posts[0][1]["source_detail"] == "Joined New Members" and posts[0][1]["status"] == "lead"
    assert out["state"] == "joined" and out["contact_id"] == CONTACT


def test_nothing_unconfirmed_is_reported_as_done(monkeypatch):
    import lead_identity
    import sb_clients

    def broken(*a, **k):
        raise RuntimeError("Contact lookup unavailable")

    monkeypatch.setattr(lead_identity, "find", broken)
    assert aj.enroll(OPEN, "Dana", "dana@example.com") is None
    monkeypatch.setattr(lead_identity, "find", lambda *a, **k: None)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: None)
    assert aj.enroll(OPEN, "Dana", "dana@example.com") is None
    monkeypatch.setattr(lead_identity, "find", lambda *a, **k: {"id": CONTACT})
    assert aj.enroll(OPEN, "Dana", "dana@example.com") is None  # the join step itself failed


# ─── After the page has answered ─────────────────────────────────────

def _after(monkeypatch, state, token=TOKEN):
    sent, told = [], []

    async def send(course, name, email, outcome, *, again):
        sent.append(again)

    async def tell(course, outcome):
        told.append(outcome["state"])

    monkeypatch.setattr(aj, "send_class_link", send)
    monkeypatch.setattr(aj, "tell_owner", tell)
    asyncio.run(aj.after_join(OPEN, "Dana", "dana@example.com",
                              {"state": state, "token": token, "enrollment_id": ENROLLMENT}))
    return sent, told


def test_new_people_get_their_link_and_the_owner_hears(monkeypatch):
    assert _after(monkeypatch, "joined") == ([False], ["joined"])


def test_people_already_in_get_their_own_link_again_quietly(monkeypatch):
    assert _after(monkeypatch, "already") == ([True], [])


def test_someone_taken_off_gets_no_link_and_the_owner_decides(monkeypatch):
    assert _after(monkeypatch, "dropped", token=None) == ([], ["dropped"])


def test_a_failed_email_still_tells_the_owner(monkeypatch):
    told = []

    async def send(*a, **k):
        raise RuntimeError("Resend 500")

    async def tell(course, outcome):
        told.append(outcome["state"])

    monkeypatch.setattr(aj, "send_class_link", send)
    monkeypatch.setattr(aj, "tell_owner", tell)
    asyncio.run(aj.after_join(OPEN, "Dana", "d@x.com", {"state": "joined", "token": TOKEN, "enrollment_id": ENROLLMENT}))
    assert told == ["joined"]


def test_the_email_is_in_plain_words_with_one_button(monkeypatch):
    import email_sender
    import sb_clients
    sent = {}

    async def resend(**kw):
        sent.update(kw)
        return {"id": "m1"}

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: [{
        "name": "Love City Church",
        "settings": {"brand_kit": {"colors": {"primary": "#C2125F"}}}}])
    monkeypatch.setattr(aj, "next_class_line", lambda biz, cid: "Thursday, October 22 at 7 PM")
    monkeypatch.setattr(email_sender, "send_via_resend", resend)
    monkeypatch.setattr(email_sender, "build_routed_reply_to", lambda biz, cid: "reply+b+c@in.example")
    asyncio.run(aj.send_class_link(OPEN, "Dana Smith", "dana@example.com",
                                   {"token": TOKEN, "enrollment_id": ENROLLMENT, "contact_id": CONTACT}, again=False))
    body = sent["body"]
    assert sent["to_email"] == "dana@example.com" and sent["from_name"] == "Love City Church"
    assert sent["subject"] == "You’re in: New Members" and sent["business_id"] == BIZ
    assert sent["reply_to"] == "reply+b+c@in.example"
    assert body.lstrip().lower().startswith("<!doctype")  # kept as built, not re-laid-out
    assert f'href="https://system.mysolutionist.app/classroom/{TOKEN}"' in body and "Open your class" in body
    assert "Hi Dana," in body and "The next class is Thursday, October 22 at 7 PM." in body
    assert "background:#C2125F" in body


def test_the_link_again_email_says_so():
    subject, message, lead = aj.class_link_email("Love City Church", "New Members", "", "x", "", again=True)
    assert subject == "Your link to New Members" and message.startswith("Hi,\n\nHere’s your way back")
    assert "next class" not in message


def test_the_owner_notice_names_the_person_and_opens_classes(monkeypatch):
    import notification_engine
    seen = []

    async def alert(client, biz, title, body, **kw):
        seen.append((biz, title, body, kw))

    monkeypatch.setattr(notification_engine, "create_urgent_alert", alert)
    asyncio.run(aj.tell_owner(OPEN, {"state": "joined", "enrollment_id": ENROLLMENT, "contact_id": CONTACT,
                                     "known_as": "Dana Smith"}))
    asyncio.run(aj.tell_owner(OPEN, {"state": "dropped", "enrollment_id": ENROLLMENT, "contact_id": CONTACT,
                                     "known_as": "Dana Smith"}))
    (b1, t1, _, k1), (b2, t2, body2, k2) = seen
    assert b1 == BIZ and t1 == "Dana Smith joined New Members" and k1["priority"] == "normal"
    assert k1["notification_id"]  # one notice per enrollment, however often the task retries
    assert k1["action_payload"] == {"type": "navigate", "tab": "build", "sub": "course-studio"}
    assert t2 == "Dana Smith asked to join New Members again" and "no link was sent" in body2
    assert k2["dedup_key"] == f"class-rejoin:{ENROLLMENT}" and k2["dedup_hours"] == 24


# ─── The pieces it rides on ──────────────────────────────────────────

def test_the_email_button_is_optional_and_readable_on_the_brand_colour():
    brand = email_layout.brand_of({"brand_kit": {"colors": {"primary": "#F5C542"}}})
    with_cta = email_layout.render_html("Hello.", business_name="Gold", brand=brand, cta=("Open your class", "https://x.test/a?b=1&c=2"))
    assert 'href="https://x.test/a?b=1&amp;c=2"' in with_cta and "color:#111827" in with_cta
    dark = email_layout.render_html("Hello.", business_name="Plum", brand=email_layout.brand_of(
        {"brand_kit": {"colors": {"primary": "#1C0B1F"}}}), cta=("Go", "https://x.test"))
    assert "color:#ffffff;text-decoration:none" in dark
    assert "Open your class" not in email_layout.render_html("Hello.", business_name="Gold", brand=brand)


def test_the_limits_are_registered_and_the_routes_are_mounted():
    for bucket in ("class_join_ip", "class_join_email_minute", "class_join_email_day"):
        assert bucket in rate_limit._LIMITS
    assert rate_limit._LIMITS["class_join_email_minute"] == (1, 60)
    paths = {r.path for r in aj.router.routes}
    assert {"/academy/{course_id}/join", "/course/{course_id}/join"} <= paths
    src = open("kmj_intake_automation.py", encoding="utf-8").read()
    assert src.index("app.include_router(academy_join_router)") < src.index("app.include_router(public_site_router)")
