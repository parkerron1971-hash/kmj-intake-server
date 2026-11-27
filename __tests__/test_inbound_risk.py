"""inbound_risk: one verdict for every door, with plain reasons.

The corpus holds the real shapes of the two cards that started this (the
"Tourist catalogue" campaign at Love City, 2026-11-22 and 11-26), with made-up
names and addresses, and the real seekers that must stay clear.
"""
import asyncio
import json

import pytest

import inbound_risk as R


@pytest.fixture(autouse=True)
def _salt(monkeypatch):
    monkeypatch.setenv("INBOUND_HASH_SALT", "test-salt")
    monkeypatch.delenv("INBOUND_RISK_WEIGHTS", raising=False)
    monkeypatch.delenv("INBOUND_HOLD_AT", raising=False)


CHURCH = {"examplechurch.org"}

# The second card's shape: a "follow-up" to an earlier offer, the church's own
# domain named, a catalogue, "write yes", a site to register on, a fake phone.
SOFIA = R.Card(
    door="connect_card", name="Sara Moreno", email="sara@tourist-sector.example.com", phone="1000000000",
    text=R.card_text("", {"visits": "This is my first time", "heard_from": "Facebook", "notes": (
        "Hello, I wrote to you a few days ago through your contact form. We would like to add examplechurch.org "
        "to Tourist, a catalogue of travel offers, free of charge. Write 'yes' to sara@tourist-sector.example.com "
        "and we will publish it. You can also register yourself: tourist-sector.example.com. "
        "Not interested? Just tell me.")}))
# The first card: the same campaign four days earlier, another name and domain.
JULIEN = R.Card(
    door="connect_card", name="Jules Marchand", email="jules@tourist-europe.example.net", phone="1000000000",
    text=R.card_text("", {"visits": "This is my first time", "heard_from": "Facebook", "notes": (
        "Earlier I sent you an offer to add you to the Tourist catalog. The registration link is "
        "tourist-europe.example.net and it is free!")}))


def facts(**kw):
    return R.Facts(own_domains=set(CHURCH), **kw)


def codes(v):
    return {r["code"] for r in v["reasons"]}


def test_the_second_card_needs_a_look_and_says_why():
    v = R.assess(SOFIA, facts())
    assert v["verdict"] == R.NEEDS_LOOK and v["hold"]
    assert {"junk_phone", "link", "sales", "reply_yes", "fake_follow_up"} <= codes(v)
    assert v["score"] == 7
    words = R.words_of(v)
    assert "The phone number isn't real" in words
    assert "Asks you to visit tourist-sector.example.com" in words
    assert "Reads like a sales pitch" in words


def test_the_second_card_scores_higher_once_the_first_one_was_held_here():
    v = R.assess(SOFIA, facts(seen_here=["text"]))
    assert v["score"] == 9 and "seen_here" in codes(v)


def test_the_first_card_needs_a_look_too():
    v = R.assess(JULIEN, facts())
    assert v["verdict"] == R.NEEDS_LOOK
    assert {"junk_phone", "link", "sales", "fake_follow_up"} <= codes(v)
    assert v["score"] == 6


def test_a_link_somewhere_other_than_the_senders_own_domain_weighs_more():
    card = R.Card(door="connect_card", name="Ann Lee", email="ann@gmail.com",
                  text="Please list your church on bestchurchdirectory.com")
    v = R.assess(card, facts())
    assert "link_foreign" in codes(v) and "Asks you to visit bestchurchdirectory.com" in R.words_of(v)


SEEKERS = [
    ("Loved the worship, my kids want to come back, found you on Facebook", "Facebook"),
    ("My cousin invited me", "A friend"),
    ("I'm new to town and looking for a church home. Do you have a kids program?", "Google"),
    ("Can I give through Zelle?", "A Love City member"),
    ("Please pray for my mom, she is in the hospital. Feel free to call me.", ""),
    ("Thanks for listening to me after service last Sunday.", ""),
    ("The traffic getting there was rough but we'll be back at 9 a.m. next week.", ""),
    ("We'd love to partner with you in ministry at the food pantry.", ""),
    ("My husband and I moved here from St.Louis. When is the next newcomers lunch?", ""),
    ("Is there a group for young adults? I saw your post on facebook.com/examplechurch", "Instagram"),
    ("Please confirm my baby's dedication date.", ""),
    ("I'm going through a hard time and I need someone to talk to.", ""),
    ("Signed up on examplechurch.org for the retreat, is there a deposit?", ""),
]


@pytest.mark.parametrize("notes,heard", SEEKERS)
def test_real_seekers_stay_clear(notes, heard):
    card = R.Card(door="connect_card", name="Dana Rivers", email="dana.rivers@gmail.com", phone="(704) 555-0182",
                  text=R.card_text("", {"visits": "This is my first time", "heard_from": heard, "notes": notes}))
    v = R.assess(card, facts())
    assert v["verdict"] == R.CLEAR, (notes, v["reasons"])


def test_my_cousin_with_a_website_is_a_middle_card_not_a_hold():
    card = R.Card(door="connect_card", name="Dana Rivers", email="dana@gmail.com", phone="7045550182",
                  text="My cousin runs travelsite.com and invited me")
    v = R.assess(card, facts())
    assert v["verdict"] == R.CLEAR and v["mid"] and v["score"] == 2


def test_gift_cards_and_fees_are_held_on_their_own():
    card = R.Card(door="connect_card", name="Pat Doe", email="pat@gmail.com",
                  text="Pastor needs you to buy four gift cards for the outreach today, keep it quiet")
    v = R.assess(card, facts())
    assert v["verdict"] == R.NEEDS_LOOK and "Asks about money or gift cards" in R.words_of(v)
    card.text = "There is a customs clearance fee for your parcel"
    assert R.assess(card, facts())["verdict"] == R.NEEDS_LOOK


def test_someone_using_a_pastors_name_from_another_address():
    staff = [{"name": "Kevin Carter", "email": "kevin@examplechurch.org", "phone": "+17045550100"}]
    card = R.Card(door="contact_form", name="Kevin Carter", email="pastor.kevin.c@gmail.com",
                  text="Are you available? I need a favour")
    v = R.assess(card, facts(staff=staff))
    assert v["verdict"] == R.NEEDS_LOOK
    assert "Uses Kevin Carter's name from an address that isn't theirs" in R.words_of(v)
    card.email = "kevin@examplechurch.org"
    assert R.assess(card, facts(staff=staff))["verdict"] == R.CLEAR


def test_a_member_on_the_roll_is_trusted_and_a_real_before_always_wins():
    card = R.Card(door="connect_card", name="Dana Rivers", email="dana@gmail.com", phone="1000000000",
                  text="Do you have a catalogue of the classes?")
    assert R.assess(card, facts())["verdict"] == R.NEEDS_LOOK
    v = R.assess(card, facts(known_status="member"))
    assert v["verdict"] == R.CLEAR and "known" in codes(v)
    # Held now: being on the list as a held lead is no reason to trust them.
    assert R.assess(card, facts(known_status="member", held_now=True))["verdict"] == R.NEEDS_LOOK
    v = R.assess(SOFIA, facts(real_before=True, shared_hit=True))
    assert v["verdict"] == R.CLEAR and "shared_list" not in codes(v)


def test_the_shared_list_and_a_churchs_own_scam_are_signals():
    plain = R.Card(door="connect_card", name="Ann Lee", email="ann@gmail.com", text="Hi, I'm new")
    assert R.assess(plain, facts())["score"] == 0
    v = R.assess(plain, facts(shared_hit=True))
    assert v["verdict"] == R.NEEDS_LOOK and "Other churches marked this sender as a scam" in R.words_of(v)
    v = R.assess(plain, facts(scam_before=True))
    assert v["verdict"] == R.NEEDS_LOOK and "You marked this sender as a scam before" in R.words_of(v)
    v = R.assess(plain, facts(seen_elsewhere=3))
    assert "Sent the same thing to 4 churches this week" in R.words_of(v)


def test_throwaway_new_and_dead_domains():
    card = R.Card(door="contact_form", name="Ann Lee", email="ann@mailinator.com", text="hello")
    assert "disposable" in codes(R.assess(card, facts()))
    card.email = "ann@freshsite.example.com"
    v = R.assess(card, facts(no_mx=True, domain_age_days=12))
    assert {"no_mx", "new_domain"} <= codes(v) and v["verdict"] == R.NEEDS_LOOK
    assert "The email's web address is only 12 days old" in R.words_of(v)
    # Free mail is never looked up or counted.
    card.email = "ann@gmail.com"
    assert R.assess(card, facts(no_mx=True, domain_age_days=1))["score"] == 0


def test_bots():
    assert R.assess(R.Card(door="connect_card", honeypot="x"), facts())["verdict"] == R.BOT
    assert R.assess(R.Card(door="connect_card", elapsed_s=1.2), facts())["verdict"] == R.BOT
    assert R.assess(R.Card(door="connect_card", elapsed_s=8.0), facts())["verdict"] == R.CLEAR


@pytest.mark.parametrize("phone,junk", [
    ("1000000000", True), ("+1 (000) 000-0000", True), ("123-456-7890", True), ("5555555555", True),
    ("555-12", True), ("555-1234", False), ("0123456789", True), ("", False), ("(704) 555-0182", False),
    ("+1 704 555 0182", False), ("+44 20 7946 0958", False),
])
def test_junk_phones(phone, junk):
    assert R.junk_phone(phone) is junk


def test_links_ignore_abbreviations_and_the_churchs_own_site():
    assert R.links_in("Moved from St.Louis at 9 a.m., e.g. last week") == []
    assert R.links_in("see https://www.Example.com/x and bad-site.net, mail me at a@b.com") == [
        "example.com", "bad-site.net"]
    card = R.Card(door="connect_card", name="Ann", email="ann@gmail.com", text="I saw examplechurch.org/events")
    assert R.assess(card, facts())["score"] == 0


def test_name_email_mismatch():
    assert R.name_email_mismatch("Sara Moreno", "mike.jones@x.com")
    assert not R.name_email_mismatch("Sara Moreno", "sara@x.com")
    assert not R.name_email_mismatch("Tom Smith", "jennysmith@gmail.com")
    assert not R.name_email_mismatch("Tom Smith", "ts@gmail.com")
    assert not R.name_email_mismatch("Tom Smith", "info@smithfamily.com")
    assert not R.name_email_mismatch("Tom Smith", "jenny123@gmail.com")


def test_fingerprints_are_salted_hashes_and_catch_a_rotated_template():
    p1 = R.fingerprints(SOFIA)
    blob = json.dumps(p1)
    assert "sara" not in blob and "tourist" not in blob and "1000000000" not in blob
    # A junk phone is never a fingerprint, and nor is a domain unless it's a
    # throwaway or on the curated abusive list (review must-fix 2).
    assert set(p1) == {"email", "text"}
    assert all(len(h) == 64 for h in p1.values())
    other = R.Card(door="connect_card", name="Lena Brooks", email="lena@other-tourist.example.org", phone="1",
                   text=SOFIA.text.replace("examplechurch.org", "gracechapel.org")
                   .replace("sara@tourist-sector.example.com", "lena@other-tourist.example.org")
                   .replace("tourist-sector.example.com", "other-tourist.example.org"))
    assert R.fingerprints(other)["text"] == p1["text"]
    assert R.fingerprints(other)["email"] != p1["email"]
    gmail = R.Card(door="connect_card", name="Ann", email="Ann@Gmail.com", phone="(704) 555-0182")
    assert "domain" not in R.fingerprints(gmail) and "phone" in R.fingerprints(gmail)
    assert R.fingerprints(gmail)["email"] == R.salted("email", "ann@gmail.com")


def test_no_salt_means_no_fingerprints(monkeypatch):
    monkeypatch.delenv("INBOUND_HASH_SALT", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert R.fingerprints(SOFIA) == {}


def test_weights_and_threshold_are_tunable(monkeypatch):
    monkeypatch.setenv("INBOUND_RISK_WEIGHTS", '{"sales": 0, "junk_phone": 0}')
    assert R.assess(JULIEN, facts())["score"] == 2
    monkeypatch.setenv("INBOUND_HOLD_AT", "2")
    assert R.assess(JULIEN, facts())["verdict"] == R.NEEDS_LOOK


def test_the_switch(monkeypatch):
    import member_asks
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample", lambda b: False)
    monkeypatch.setattr(member_asks, "platform_church", lambda b: b == "11111111-1111-4111-8111-111111111111")
    own, other = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    monkeypatch.delenv("INBOUND_SAFETY", raising=False)
    assert R.mode() == "off" and not R.switched_on(own) and not R.checked(own)
    monkeypatch.setenv("INBOUND_SAFETY", "watch")
    assert not R.switched_on(own) and R.checked(other)
    monkeypatch.setenv("INBOUND_SAFETY", "owner")
    assert R.switched_on(own) and not R.switched_on(other)
    monkeypatch.setenv("INBOUND_SAFETY", "on")
    assert R.switched_on(other)
    monkeypatch.setenv("INBOUND_SAFETY", other)
    assert R.mode() == "ids" and R.switched_on(other) and not R.switched_on(own)
    monkeypatch.setenv("INBOUND_SAFETY", "nonsense")
    assert R.mode() == "off"
    monkeypatch.setenv("INBOUND_SAFETY", "on")
    monkeypatch.setattr(sample_church, "is_sample", lambda b: True)
    assert not R.switched_on(other)


def test_check_is_none_while_off(monkeypatch):
    monkeypatch.setenv("INBOUND_SAFETY", "off")
    assert asyncio.run(R.check("b", door="connect_card", name="x", email="x@y.com")) is None


def _check_env(monkeypatch, said, calls):
    monkeypatch.setenv("INBOUND_SAFETY", "on")
    monkeypatch.setattr(R, "switched_on", lambda b: True)
    monkeypatch.setattr(R, "gather", lambda b, card, prints=None, now=None: facts())

    async def opinion(biz, card):
        calls.append(card.door)
        return said
    monkeypatch.setattr(R, "second_opinion", opinion)


def test_a_middle_card_gets_a_second_opinion_that_can_only_raise_it(monkeypatch):
    calls = []
    _check_env(monkeypatch, "pitch", calls)
    v = asyncio.run(R.check("b", door="connect_card", name="Dana", email="dana@gmail.com",
                            message="My cousin runs travelsite.com and invited me"))
    assert calls == ["connect_card"] and v["verdict"] == R.NEEDS_LOOK and v["second_opinion"] == "pitch"
    assert "A second read says it looks like a sales pitch, not someone reaching out" in v["reasons"][-1]["words"]
    assert v["enforce"] and set(v["prints"]) >= {"email"}
    calls.clear()
    _check_env(monkeypatch, "person", calls)
    v = asyncio.run(R.check("b", door="connect_card", name="Dana", email="dana@gmail.com",
                            message="My cousin runs travelsite.com and invited me"))
    assert v["verdict"] == R.CLEAR
    # A clear card with nothing in it is never sent to the model; nor is a held one.
    calls.clear()
    asyncio.run(R.check("b", door="connect_card", name="Dana", email="dana@gmail.com", message="Hi, I'm new"))
    asyncio.run(R.check("b", door="connect_card", name=SOFIA.name, email=SOFIA.email, phone=SOFIA.phone,
                        message=SOFIA.text))
    assert calls == []


def test_a_prayer_request_never_goes_to_the_model(monkeypatch):
    calls = []
    _check_env(monkeypatch, "scam", calls)
    v = asyncio.run(R.check("b", door="prayer_request", name="Dana", email="dana@gmail.com",
                            message="Please pray, my cousin runs travelsite.com"))
    assert calls == [] and v["verdict"] == R.CLEAR


def test_the_second_opinion_itself_refuses_a_prayer_request(monkeypatch):
    import llm_call
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    async def never(*a, **kw):
        raise AssertionError("a prayer request went to the model")
    monkeypatch.setattr(llm_call, "apost", never)
    assert asyncio.run(R.second_opinion("b", R.Card(door="prayer_request", text="x"))) is None


def test_the_second_opinion_falls_back_on_a_timeout(monkeypatch):
    import llm_call
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(R, "SECOND_OPINION_TIMEOUT", 0.05)

    async def slow(*a, **kw):
        await asyncio.sleep(2)
    monkeypatch.setattr(llm_call, "apost", slow)
    assert asyncio.run(R.second_opinion("b", R.Card(door="connect_card", text="hello"))) is None


def test_the_second_opinion_reads_the_models_verdict_and_meters_through_the_seam(monkeypatch):
    import llm_call
    import spend_guard
    seen = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda b=None: False)

    class Resp:
        status_code = 200

        def json(self):
            return {"content": [{"type": "text", "text": '{"verdict": "scam"}'}], "stop_reason": "end_turn"}

    async def apost(client, payload, timeout=None, task=None, business_id=None):
        seen.update(task=task, business_id=business_id, model=payload["model"])
        return Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    assert asyncio.run(R.second_opinion("biz-1", R.Card(door="connect_card", text="gift cards"))) == "scam"
    assert seen == {"task": "inbound_second_opinion", "business_id": "biz-1", "model": R.SECOND_OPINION_MODEL}
    # Over the day's spend: not asked.
    monkeypatch.setattr(spend_guard, "over_budget", lambda b=None: True)
    seen.clear()
    assert asyncio.run(R.second_opinion("biz-1", R.Card(door="connect_card", text="x"))) is None and not seen


def test_a_short_phone_is_its_own_smaller_signal():
    card = R.Card(door="connect_card", name="Dana Rivers", email="dana@gmail.com", phone="555-0182")
    v = R.assess(card, facts())
    assert v["score"] == 1 and "The phone number looks incomplete" in R.words_of(v)
    assert R.short_phone("555-0182") and not R.junk_phone("555-0182")


# The review's false positives (should-fix 4): each is a real seeker.
REVIEW_SEEKERS = [
    dict(text="Found you on Google Maps, we just moved here", email="bigmike72@gmail.com", phone="(704) 555-0182"),
    dict(text="Following up on my visit last Sunday, when is the next newcomers lunch?", email="dana@gmail.com",
         phone="555-0182"),
    dict(text="I saw your advertisement in the paper and would like to visit", email="dana@gmail.com",
         phone="555-0182"),
    dict(text="Can you send me the registration link for VBS?", email="dana@gmail.com", phone="(704) 555-0182"),
]


@pytest.mark.parametrize("c", REVIEW_SEEKERS)
def test_the_reviews_seekers_stay_clear(c):
    card = R.Card(door="connect_card", name="Dana Rivers", **c)
    v = R.assess(card, facts())
    assert v["verdict"] == R.CLEAR, v["reasons"]
    assert "sales" not in codes(v)


@pytest.mark.parametrize("domain", [
    "yahoo.co.uk", "btinternet.com", "nc.rr.com", "triad.rr.com", "juno.com", "aim.com", "centurylink.net",
    "bigpond.com", "optusnet.com.au", "co.uk", "com.au",
])
def test_shared_mail_is_never_a_fingerprint_or_looked_up(domain, monkeypatch):
    assert R.shared_mail(domain)
    assert not R.curated_domain(domain)
    card = R.Card(door="connect_card", name="Ann Lee", email=f"ann@{domain}", text="hello there")
    assert "domain" not in R.fingerprints(card)
    called = []
    monkeypatch.setattr(R, "_no_mx", lambda d: called.append(d) or True)
    assert R.domain_facts(domain) == (False, None) and called == []


def test_only_a_throwaway_or_curated_domain_is_a_fingerprint(monkeypatch):
    throwaway = R.Card(door="connect_card", name="Ann", email="ann@mailinator.com")
    assert "domain" in R.fingerprints(throwaway)
    company = R.Card(door="connect_card", name="Ann", email="ann@acme-widgets.com")
    assert "domain" not in R.fingerprints(company)
    monkeypatch.setenv("INBOUND_ABUSIVE_DOMAINS", "acme-widgets.com")
    assert "domain" in R.fingerprints(company)


def test_the_registrable_name_respects_two_part_suffixes():
    assert R._root("news.bbc.co.uk") == "bbc.co.uk"
    assert R._root("www.example.com") == "example.com"
    # Two different .co.uk sites are not one sender's own site.
    card = R.Card(door="connect_card", name="Ann", email="ann@smith-plumbing.co.uk", text="see bestdeals.co.uk")
    assert "link_foreign" in codes(R.assess(card, facts()))


def test_a_churchs_own_real_is_never_sent_to_the_second_opinion():
    v = R.assess(JULIEN, facts(real_before=True))
    assert v["verdict"] == R.CLEAR and v["mid"] is False


def test_the_text_fingerprint_is_their_own_words_not_the_ticked_choices():
    a = R.Card(door="connect_card", name="Ann Lee", email="ann@gmail.com",
               text=R.card_text("", {"visits": "This is my first time", "heard_from": "Facebook",
                                     "interests": ["Kids", "Small groups", "Serving"], "notes": "Hi!"}),
               print_text=R.own_words("", {"visits": "This is my first time", "notes": "Hi!"}))
    assert "text" not in R.fingerprints(a)          # "Hi!" is too short to be a template
    assert R.own_words("Hello", {"notes": "My note", "heard_from": "Facebook"}) == "Hello" + chr(10) + "My note"


def test_rdap_is_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv("INBOUND_RDAP", raising=False)
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("rdap called")))
    assert R._domain_age("freshsite.example.com") is None
