"""One FAQ (business_faq.py): saved once, listed where the owner looks, and
never promised somewhere it can't be seen.

Love City, 2026-11-07. Kevin gave Chief six answers. All six saved, to a
list the FAQ screen in Settings never read, and every receipt said "live on
the website FAQ" about a hand-built site with no FAQ. Asked "did you add the
list we made to the FAQ?", Chief drafted the right answer and the answer
check withheld it, because Chief's FAQ was a block the check was never given.
Each test here is one of those steps failing the other way.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

import business_faq  # noqa: E402
import chief_of_staff as chief  # noqa: E402
import chief_strategy_actions as actions  # noqa: E402
import chief_truth as truth  # noqa: E402
import public_site  # noqa: E402
import site_concierge as sc  # noqa: E402

KIDS = {"q": "Is there something for my kids?",
        "a": "Yes. Children's Church runs on Sundays during the morning service. "
             "Teens are welcome at our teen Bible study on the 2nd and 4th Tuesday."}
PARKING = {"q": "Is there parking?", "a": "Yes, in the church parking lot."}


def _user(uid):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


def _settings(*rows, **extra):
    return {"business_picture": {"faq": [dict(r) for r in rows]}, **extra}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    # PostgREST answers a PATCH with the rows it changed; none means no save.
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: (fb.patch(path, body), fb.get(path))[1])
    monkeypatch.delenv("BILLING_ENFORCE", raising=False)
    monkeypatch.setattr("site_composer.refresh_if_composed_async", lambda business_id: None)
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "owner1", "name": "Love City Church", "type": "ministry",
        "settings": {"concierge": {"enabled": True}}, "subscription_status": None,
        "subscription_plan": None, "comp_tier": None, "stripe_account_id": None})
    fb.rows("business_sites").append({
        "id": "s1", "business_id": "b1", "slug": "love-city-church", "status": "published",
        "html_content": "<html>home</html>",
        "site_config": {"html_source": "manual", "generated_pages": {"visit": business_faq.SLOT}}})
    return fb


def _biz(fake):
    return fake.get("/businesses?id=eq.b1&limit=1")[0]


# ─── one list ───────────────────────────────────────────────────────

def test_what_chief_saves_is_the_list_the_settings_screen_shows(fake):
    """The heart of it: Kevin opened this screen and it was empty."""
    biz = _biz(fake)
    out = _run(actions.handle_add_faq(None, biz, {"type": "add_faq",
                                                  "question": KIDS["q"], "answer": KIDS["a"]}))
    assert not out.get("failed")
    assert sc.get_concierge("b1", _user("owner1"))["faq"] == [KIDS]


def test_a_row_saved_in_the_screens_old_list_is_still_read_then_folded_in():
    settings = {"business_picture": {"faq": [dict(KIDS)]},
                "concierge": {"enabled": True, "faq": [dict(PARKING), {"q": "kids?", "a": "x"}]}}
    assert business_faq.rows(settings) == [KIDS, PARKING, {"q": "kids?", "a": "x"}]
    assert business_faq.put(settings, "What should I wear?", "Come as you are.") == "added"
    assert [r["q"] for r in settings["business_picture"]["faq"]] == [
        KIDS["q"], PARKING["q"], "kids?", "What should I wear?"]
    assert settings["concierge"] == {"enabled": True}


def test_the_same_question_asked_twice_is_one_row():
    settings = _settings(KIDS, {"q": "is there something for my kids", "a": "older"})
    assert business_faq.rows(settings) == [KIDS]


def test_a_new_answer_to_the_same_question_keeps_its_place():
    settings = _settings(KIDS, PARKING)
    assert business_faq.put(settings, "IS THERE PARKING", "Out back.") == "updated"
    assert business_faq.put(settings, KIDS["q"], "Yes, on Sundays.") == "updated"
    assert settings["business_picture"]["faq"] == [
        {"q": KIDS["q"], "a": "Yes, on Sundays."}, {"q": PARKING["q"], "a": "Out back."}]


def test_a_full_list_refuses_instead_of_dropping_the_oldest_answer():
    """add_faq kept "the newest 12", so a thirteenth answer quietly deleted
    the first and the receipt said added."""
    full = [{"q": f"Question {i}?", "a": "yes"} for i in range(business_faq.FAQ_LIMIT)]
    settings = _settings(*full)
    assert business_faq.put(settings, "One more?", "no") == "full"
    assert settings["business_picture"]["faq"] == full
    assert business_faq.put(settings, "Question 3?", "changed") == "updated"


def test_rows_survive_a_malformed_settings_blob():
    assert business_faq.rows(None) == []
    assert business_faq.rows({"business_picture": "x", "concierge": ["y"]}) == []
    assert business_faq.rows(_settings({"q": "", "a": "x"}, {"q": "x", "a": ""}, KIDS)) == [KIDS]
    assert business_faq.rows({"business_picture": {"faq": ["x", 3, KIDS]}}) == [KIDS]


def test_public_rows_are_the_policies_then_the_faq_and_the_faq_answer_wins():
    settings = {"business_picture": {
        "policies": {"deposit": "Half up front.", "lateness": "Call us.", "made_up": "no"},
        "faq": [{"q": "do you require a deposit", "a": "No deposit."}, PARKING]}}
    assert business_faq.public_rows(settings) == [
        {"q": "Do you require a deposit?", "a": "No deposit."},
        {"q": "What if I'm running late?", "a": "Call us."}, PARKING]


# ─── the Settings screen ────────────────────────────────────────────

def test_saving_the_screen_writes_the_one_list_and_a_removed_row_stays_gone(fake):
    fake.rows("businesses")[0]["settings"]["business_picture"] = {"faq": [KIDS, PARKING],
                                                                  "policies": {"deposit": "None."}}
    out = sc.patch_concierge("b1", sc.ConciergeSettingsPatch(faq=[KIDS, {"q": "", "a": "x"}]),
                             _user("owner1"))
    assert out["faq"] == [KIDS]
    saved = _biz(fake)["settings"]
    assert saved["business_picture"] == {"faq": [KIDS], "policies": {"deposit": "None."}}
    assert "faq" not in saved["concierge"]
    assert sc.get_concierge("b1", _user("owner1"))["faq"] == [KIDS]


def test_the_switch_alone_leaves_the_faq_alone(fake):
    fake.rows("businesses")[0]["settings"]["business_picture"] = {"faq": [KIDS]}
    sc.patch_concierge("b1", sc.ConciergeSettingsPatch(enabled=False), _user("owner1"))
    assert _biz(fake)["settings"]["business_picture"]["faq"] == [KIDS]


def test_a_save_that_did_not_land_is_an_error_not_a_green_toast(fake, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: [])
    with pytest.raises(HTTPException) as e:
        sc.patch_concierge("b1", sc.ConciergeSettingsPatch(faq=[KIDS]), _user("owner1"))
    assert e.value.status_code == 502


def test_the_website_assistant_answers_from_the_one_list(fake, monkeypatch):
    monkeypatch.setitem(sc._knowledge_cache, "b1", (0, {}))
    fake.rows("businesses")[0]["settings"]["business_picture"] = {"faq": [KIDS]}
    biz = sc._biz_row("b1")
    assert sc.assemble_knowledge("b1", biz_row=biz)["faq"] == [KIDS]


# ─── Chief's saves ──────────────────────────────────────────────────

def test_the_receipt_carries_the_answer_and_says_where_it_shows(fake):
    out = _run(actions.handle_add_faq(None, _biz(fake), {
        "type": "add_faq", "question": KIDS["q"], "answer": KIDS["a"]}))
    assert out["answer"] == KIDS["a"] and out["question"] == KIDS["q"]
    assert "Settings → Website concierge" in out["result"]
    assert "website assistant is on" in out["result"]
    assert "Your website shows it." in out["result"]


def test_no_receipt_promises_a_page_this_site_does_not_have(fake):
    """Love City's first five receipts, on a site with no FAQ."""
    fake.rows("business_sites")[0]["site_config"]["generated_pages"] = {"visit": "<html></html>"}
    out = _run(actions.handle_add_faq(None, _biz(fake), {
        "type": "add_faq", "question": PARKING["q"], "answer": PARKING["a"]}))
    assert "doesn't show an FAQ" in out["result"]
    assert "live" not in out["result"].lower()
    policy = _run(actions.handle_set_business_policy(None, _biz(fake), {
        "type": "set_business_policy", "policy": "deposit", "text": "None."}))
    assert "doesn't show an FAQ" in policy["result"]
    assert "appears in the website" not in policy["result"]


def test_with_the_assistant_off_the_receipt_says_so(fake):
    fake.rows("businesses")[0]["settings"]["concierge"]["enabled"] = False
    out = _run(actions.handle_add_faq(None, _biz(fake), {
        "type": "add_faq", "question": PARKING["q"], "answer": PARKING["a"]}))
    assert "website assistant is off" in out["result"]
    assert "answers visitors" not in out["result"]


def test_a_write_that_did_not_land_never_says_added(fake, monkeypatch):
    """RLS on businesses lets an owner or admin through; for a manager the
    PATCH came back empty and the receipt still said added."""
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: [])
    biz = _biz(fake)
    out = _run(actions.handle_add_faq(None, biz, {
        "type": "add_faq", "question": KIDS["q"], "answer": KIDS["a"]}))
    assert out.get("failed") and "didn't save" in out["result"]
    assert "business_picture" not in biz["settings"]


def test_a_saved_answer_stays_saved_when_the_site_cannot_be_read(fake, monkeypatch):
    real = actions.sb_clients.sb_get_as_service

    def get(path):
        if path.startswith("/business_sites"):
            raise RuntimeError("no site read")
        return real(path)
    monkeypatch.setattr(actions.sb_clients, "sb_get_as_service", get)
    out = _run(actions.handle_add_faq(None, _biz(fake), {
        "type": "add_faq", "question": KIDS["q"], "answer": KIDS["a"]}))
    assert not out.get("failed")
    assert "Your FAQ is listed" in out["result"] and "website shows" not in out["result"]
    assert _biz(fake)["settings"]["business_picture"]["faq"] == [KIDS]


def test_a_switch_turned_on_during_the_turn_is_not_undone_by_the_save(fake):
    """Kevin turned the assistant on at 07:53:18 between two turns. A turn
    holding the older copy of settings wrote the whole object back."""
    biz = _biz(fake)
    biz["settings"] = {"concierge": {"enabled": False}}
    fake.rows("businesses")[0]["settings"] = {"concierge": {"enabled": True}}
    _run(actions.handle_add_faq(None, biz, {
        "type": "add_faq", "question": KIDS["q"], "answer": KIDS["a"]}))
    saved = _biz(fake)["settings"]
    assert saved["concierge"]["enabled"] is True and saved["business_picture"]["faq"] == [KIDS]
    assert biz["settings"]["business_picture"]["faq"] == [KIDS]


def test_a_full_faq_tells_the_owner_and_writes_nothing(fake, monkeypatch):
    full = [{"q": f"Question {i}?", "a": "yes"} for i in range(business_faq.FAQ_LIMIT)]
    fake.rows("businesses")[0]["settings"]["business_picture"] = {"faq": full}
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: pytest.fail("a full list must not write"))
    out = _run(actions.handle_add_faq(None, _biz(fake), {
        "type": "add_faq", "question": "One more?", "answer": "no"}))
    assert out.get("failed") and "full at 24" in out["result"]


def test_a_composed_site_showing_the_faq_refreshes_and_a_hand_built_one_does_not(fake, monkeypatch):
    refreshed = []
    monkeypatch.setattr("site_composer.refresh_if_composed_async", refreshed.append)
    _run(actions.handle_add_faq(None, _biz(fake), {
        "type": "add_faq", "question": KIDS["q"], "answer": KIDS["a"]}))
    assert refreshed == []
    fake.rows("business_sites")[0]["site_config"] = {
        "html_source": "module-composer", "page_spec": {"sections": [{"module": "faq"}]}}
    _run(actions.handle_add_faq(None, _biz(fake), {
        "type": "add_faq", "question": PARKING["q"], "answer": PARKING["a"]}))
    assert refreshed == ["b1"]


def test_nothing_chief_is_told_says_an_answer_is_live_on_the_website():
    import chief_prompt
    import mcp_server
    source = inspect.getsource(actions)
    assert "live on the website" not in source and "appears in the" not in source
    assert "Live on the website" not in mcp_server.WRITE_TOOL_SCHEMAS["add_faq"][0]
    assert "Goes on the website FAQ" not in mcp_server.WRITE_TOOL_SCHEMAS["set_business_policy"][0]
    text = inspect.getsource(chief_prompt)
    assert "they render as the website's" not in text
    assert 'Where the FAQ shows' in text


# ─── what the answer check can see ──────────────────────────────────

def _ctx(settings, **site):
    return {"business": {"id": "b1", "name": "Love City Church", "type": "ministry",
                         "settings": settings},
            "site": {"status": "published", "site_config": {
                "html_source": "manual", "generated_pages": {"visit": business_faq.SLOT}}, **site}}


def test_the_answer_check_reads_the_faq_chief_reads():
    """The withheld reply: `claim number has no evidence :: Where the church
    meets: 1084 Allen Avenue, Muskegon.`"""
    where = {"q": "Where does Love City Church meet?", "a": "1084 Allen Avenue, Muskegon, Michigan."}
    sources = truth.evidence_for_review(_ctx(_settings(where, KIDS)), None, [])
    source = sources["context:business_picture"]
    assert "1084 Allen Avenue" in source["text"]
    assert "teen Bible study" in source["text"]
    assert source["kind"] == "context" and source["complete"] is True


def test_what_a_record_holds_is_a_fact_and_proves_nothing_else():
    """"Did you add...?" could never get a yes on a later turn: an action
    claim needs a receipt from this turn. What the record holds now is a
    fact about the record, and only that."""
    assert "What a saved record holds now" in truth.REVIEW_SYSTEM
    assert "nothing else" in truth.REVIEW_SYSTEM
    assert "Every executed action claim needs a matching receipt" in truth.REVIEW_SYSTEM


def test_cutting_the_sentence_that_led_into_a_list_leaves_no_stray_colon():
    claim = "Your FAQ has all of it"
    reply = (f"{claim}:\n- Is there parking? Yes, in the church parking lot.\n"
             "- What should I wear? Come as you are.\n"
             "- Where do you meet? In the church building, across from the park.")
    sources = {"result:0": {"kind": "receipt", "effect": "write", "complete": True, "text": "saved"}}
    review = json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "action", "source_id": "", "quote": ""}]})
    reason = truth._claim_fail(truth.ACTION_WITHOUT_RECEIPT, claim)
    out = truth._trim_unsupported(review, reply, sources, reason)
    assert out is not None
    assert out[0].startswith("- Is there parking?")


def test_the_check_and_the_prompt_read_the_same_lines():
    ctx = _ctx(_settings(KIDS, concierge={"enabled": True}))
    lines = chief.business_picture_lines(ctx["business"], ctx["site"])
    assert lines[0] == f"  - Q: {KIDS['q']} — A: {KIDS['a']}"
    assert "\n".join(lines) == truth.evidence_for_review(ctx, None, [])["context:business_picture"]["text"]


def test_chief_can_say_whether_the_assistant_is_on():
    """"My tools don't include a switch-status check for the website
    assistant.\""""
    on = chief.business_picture_lines({"settings": {"concierge": {"enabled": True}}}, None)
    off = chief.business_picture_lines({"settings": {}}, None)
    assert "website assistant is on" in on[-1] and "website assistant is off" in off[-1]


def test_every_answer_reaches_chief_not_only_the_first_twelve():
    rows = [{"q": f"Question {i}?", "a": "yes"} for i in range(20)]
    lines = chief.business_picture_lines({"settings": _settings(*rows)}, None)
    assert sum(" — A: " in line for line in lines) == 20


def test_a_failed_state_read_costs_the_state_line_never_the_faq(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gate")
    monkeypatch.setattr(business_faq, "where_it_shows", boom)
    assert chief.business_picture_lines({"settings": _settings(KIDS)}, None) == [
        f"  - Q: {KIDS['q']} — A: {KIDS['a']}"]


# ─── where it shows ─────────────────────────────────────────────────

@pytest.mark.parametrize("site,shows", [
    (None, False),
    ({}, False),
    ({"status": "draft", "site_config": {"html_source": "manual",
                                         "generated_pages": {"visit": business_faq.SLOT}}}, False),
    ({"status": "published", "site_config": {"html_source": "manual",
                                             "generated_pages": {"visit": "<p>no slot</p>"}}}, False),
    ({"status": "published", "site_config": {"html_source": "manual",
                                             "generated_pages": {"visit": business_faq.SLOT}}}, True),
    ({"status": "published", "html_content": business_faq.SLOT,
      "site_config": {"html_source": "manual"}}, True),
    ({"status": "published", "site_config": {"html_source": "module-composer",
                                             "page_spec": {"sections": [{"module": "faq"}]}}}, True),
    ({"status": "published", "site_config": {"html_source": "module-composer",
                                             "page_spec": {"sections": [{"module": "hero"}]}}}, False),
    ({"status": "published", "site_config": {"html_source": "module-composer", "page_spec": {},
                                             "generated_pages": {"about": '<div class="sxm-faq">'}}}, True),
    ({"status": "published", "site_config": {"html_source": "canvas"}}, False),
])
def test_site_shows(site, shows):
    assert business_faq.site_shows(site) is shows


def test_an_unknown_site_goes_unmentioned_rather_than_guessed():
    assert not any("website shows" in s or "website doesn't" in s
                   for s in business_faq.where_it_shows({"settings": {}}, None))


# ─── the hand-built page ────────────────────────────────────────────

SECTION = ('<main><!--solutionist:faq-section--><section><h2>Good to know</h2>'
           f'<div>{business_faq.SLOT}</div></section><!--/solutionist:faq-section-->'
           '<p>after</p></main>')


def test_the_slot_fills_with_every_answer_escaped():
    html = business_faq.fill_slots(SECTION, _settings(
        {"q": "Kids & teens?", "a": "<script>alert(1)</script> yes"}, PARKING))
    assert '<summary>Kids &amp; teens?</summary>' in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert PARKING["a"] in html and "Good to know" in html
    assert business_faq.SLOT not in html


@pytest.mark.parametrize("settings", [{}, None, _settings()])
def test_with_nothing_to_show_the_heading_comes_out_too(settings):
    html = business_faq.fill_slots(SECTION, settings)
    assert html == "<main><p>after</p></main>"


def test_a_page_without_the_slot_pays_for_no_read():
    async def read(*a, **k):
        pytest.fail("no slot, no read")

    original = public_site._sb_service
    public_site._sb_service = read
    try:
        assert _run(public_site._fill_faq_slot(None, "b1", "<p>hi</p>")) == "<p>hi</p>"
    finally:
        public_site._sb_service = original


def test_the_served_page_reads_the_list_each_time_and_a_failed_read_hides_the_section(monkeypatch):
    async def read(client, path):
        return [{"settings": _settings(KIDS)}]
    monkeypatch.setattr(public_site, "_sb_service", read)
    assert KIDS["q"] in _run(public_site._fill_faq_slot(None, "b1", SECTION))

    async def failed(client, path):
        raise RuntimeError("down")
    monkeypatch.setattr(public_site, "_sb_service", failed)
    assert _run(public_site._fill_faq_slot(None, "b1", SECTION)) == "<main><p>after</p></main>"


def test_both_ways_a_hand_built_page_is_served_fill_the_slot():
    """Miss one and the subdomain and the custom domain disagree."""
    assert inspect.getsource(public_site).count("await _fill_faq_slot(") == 2
