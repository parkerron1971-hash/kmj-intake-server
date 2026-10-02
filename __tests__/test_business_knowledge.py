"""
business_knowledge — the page and the coach read what is REALLY on file.

The regression these pin: the Business Track said "Not covered yet" on all
eight areas for a business with a 95% profile, seven offerings, eleven
clients and payments connected, because it only read the coach's notes.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import business_knowledge as bk
import business_track_actions as bta
import business_track_router as btr
import sb_clients


BIZ = {"id": "b1", "owner_id": "u1", "name": "KMJ Creative Solutions", "type": "consultant",
       "settings": {}, "stripe_account_id": None,
       "voice_profile": {"description": "Warm, blends ministry and business",
                         "audience_note": "Entrepreneurs from all walks of life"}}

OFFERINGS = [
    {"id": "o1", "name": "Coaching Session", "category": "session", "current_price": 35, "duration_min": 60},
    {"id": "o2", "name": "Free Consultation", "category": "session", "current_price": 0, "duration_min": 60},
    {"id": "o3", "name": "Initial Consultation", "category": "session", "current_price": None, "duration_min": 60},
    {"id": "o4", "name": "Embrace the Shift Workshop", "category": "event", "current_price": 0},
    {"id": "o5", "name": "Embrace the Shift", "category": "product", "current_price": 25,
     "image_url": "https://x/y.png", "requires_shipping": True},
    {"id": "o6", "name": "Group Cohort (90 Days)", "category": "package", "current_price": 750},
    {"id": "o7", "name": "Individual 90-Day Intensive", "category": "package", "current_price": 3000},
]


def _fake_db(tables):
    """Route a PostgREST path to fixture rows by its table name."""
    def get(path):
        table = path.lstrip("/").split("?")[0]
        val = tables.get(table, [])
        if isinstance(val, Exception):
            raise val
        return val
    return get


@pytest.fixture
def kmj(monkeypatch):
    tables = {
        "practitioner_profiles": [{"full_legal_name": "Kevin McCloud Jr.", "preferred_title": "Founder/Owner",
                                   "timezone": "America/Detroit", "working_hours_start": "07:00",
                                   "working_hours_end": "16:00", "primary_accountant_name": "N/A",
                                   "primary_attorney_name": "N/A", "primary_mentor_name": "n/a"}],
        "business_profiles": [{"business_type": "consultant",
                               "business_subtype": "Faith-driven business coaching",
                               "service_models": ["one_on_one", "group_program"],
                               "typical_engagement_length": "package_3_12_months",
                               "pricing_models": ["package", "tiered"],
                               "governing_state": "MI", "international_clients": True,
                               "profile_completeness": 0.95}],
        "business_tracks": [],
        "offerings": OFFERINGS,
        "contacts": [{"id": f"c{i}"} for i in range(11)],
        "invoices": [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}],
        "businesses": [{"settings": {}, "stripe_account_id": None}],
    }
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_db(tables))
    done = {"payments", "bank", "quickbooks", "site", "site_domain", "email_domain",
            "availability", "concierge"}
    monkeypatch.setattr(btr, "_probe", lambda key, biz: key in done)
    return tables


def _area(k, area_id):
    return next(a for a in k["areas"] if a["id"] == area_id)


def test_a_business_set_up_elsewhere_reads_as_known(kmj):
    k = bk.knowledge_for(BIZ)
    assert [a["id"] for a in k["areas"]] == list(bk.AREA_ORDER)
    for area_id in ("owner", "business", "offerings", "clients", "money", "operations"):
        assert _area(k, area_id)["status"] == bk.KNOWN, area_id
    assert _area(k, "growth")["status"] == bk.OPEN
    assert _area(k, "plan")["status"] == bk.OPEN
    assert k["known_count"] == 6 and k["total"] == 8


def test_facts_are_plain_sentences_from_the_records(kmj):
    k = bk.knowledge_for(BIZ)
    owner = " | ".join(_area(k, "owner")["facts"])
    assert "Kevin McCloud Jr., Founder/Owner" in owner
    assert "Detroit time, works 7 am to 4 pm" in owner
    sell = " | ".join(_area(k, "offerings")["facts"])
    assert "7 offerings: 3 sessions, 2 packages" in sell
    assert "From free to $3,000" in sell
    assert "11 on your list" in _area(k, "clients")["facts"][0]
    assert "3 unpaid invoices out" in " | ".join(_area(k, "money")["facts"])
    assert _area(k, "business")["pct"] == 95


def test_catalog_gaps_are_grouped_and_ranked_first(kmj):
    k = bk.knowledge_for(BIZ)
    keys = [g["key"] for g in k["gaps"]]
    assert keys[0] == "no_delivery_path"
    first = k["gaps"][0]["title"]
    assert "Group Cohort (90 Days)" in first and "Individual 90-Day Intensive" in first
    assert "growth" in keys
    assert _area(k, "offerings")["gap_count"] >= 1


def test_na_is_not_a_person(kmj):
    # "N/A" typed into the accountant field answered the form; it is not
    # an accountant. It must surface as a question, not as known.
    k = bk.knowledge_for(BIZ)
    assert "key_people" in [g["key"] for g in k["gaps"]]


def test_goals_are_read_from_settings_where_the_app_stores_them(kmj):
    # There is no goals table: create_goal writes settings.goals.active_goals.
    # Reading a table 404'd and left this area "Not yet" for everyone.
    biz = {**BIZ, "settings": {"goals": {"active_goals": [
        {"id": "g1", "title": "Reach $10,000 a month", "created_at": "2026-09-01T00:00:00Z"},
        {"id": "g2", "title": "20 coaching clients", "created_at": "2026-09-20T00:00:00Z"},
        {"id": "g3", "title": "", "created_at": "2026-09-21T00:00:00Z"},
    ]}}}
    k = bk.knowledge_for(biz)
    growth = _area(k, "growth")
    assert growth["status"] == bk.KNOWN
    assert growth["facts"][:2] == ["20 coaching clients", "Reach $10,000 a month"]
    assert growth["goal_count"] == 2
    assert "growth" not in [g["key"] for g in k["gaps"]]


def test_an_empty_business_is_all_open_and_the_coach_gets_the_full_interview(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_db({}))
    monkeypatch.setattr(btr, "_probe", lambda key, biz: False)
    k = bk.knowledge_for({**BIZ, "voice_profile": {}})
    assert k["known_count"] == 0
    assert all(a["status"] == bk.OPEN for a in k["areas"])
    assert bk.known_block_for_coach(k) == ""


def test_a_failed_read_makes_an_area_less_known_never_a_crash(kmj, monkeypatch):
    kmj["offerings"] = RuntimeError("postgrest down")
    kmj["business_profiles"] = RuntimeError("postgrest down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_db(kmj))
    k = bk.knowledge_for(BIZ)
    assert _area(k, "offerings")["status"] == bk.OPEN
    assert _area(k, "business")["status"] != bk.KNOWN
    assert _area(k, "owner")["status"] == bk.KNOWN


def test_the_coach_is_told_to_skip_what_is_on_file(kmj):
    k = bk.knowledge_for(BIZ)
    ctx = {"business": BIZ, "business_track": {}, "business_knowledge": k}
    p = bta.build_business_coach_prompt(ctx, False)
    assert "ALREADY ON FILE FROM THEIR RECORDS" in p
    assert "SKIP THESE AREAS: owner, business, offerings, clients, money, operations" in p
    assert "7 offerings" in p


def test_the_first_greeting_promises_a_shorter_talk_when_much_is_known(kmj):
    k = bk.knowledge_for(BIZ)
    with_records = bta.build_business_coach_prompt(
        {"business": BIZ, "business_track": {}, "business_knowledge": k}, True)
    without = bta.build_business_coach_prompt({"business": BIZ, "business_track": {}}, True)
    assert "first area that is NOT known" in with_records
    assert "first area that is NOT known" not in without


def test_the_endpoint_is_mounted():
    paths = {getattr(r, "path", "") for r in btr.router.routes}
    assert "/business-track/{business_id}/knowledge" in paths
    assert "/business-track/{business_id}/plugins" in paths


def test_the_assistant_name_follows_the_setting_and_falls_back_to_chief(kmj):
    # Kevin renames his assistant (Kai today). Nothing here may hardcode
    # a name: a rename, or clearing it, must land on the next read.
    named = {**BIZ, "settings": {"chief_preferences": {"assistant_name": "Kai"}}}
    k = bk.knowledge_for(named)
    assert k["assistant_name"] == "Kai"
    growth_gap = next(g for g in k["gaps"] if g["key"] == "growth")
    assert "so Kai can pace" in growth_gap["detail"]

    renamed = {**BIZ, "settings": {"chief_preferences": {"assistant_name": "Nova"}}}
    assert "so Nova can pace" in next(
        g for g in bk.knowledge_for(renamed)["gaps"] if g["key"] == "growth")["detail"]

    cleared = {**BIZ, "settings": {"chief_preferences": {"assistant_name": "  "}}}
    assert bk.knowledge_for(cleared)["assistant_name"] == "Chief"


def test_profile_enum_keys_never_reach_the_page(kmj):
    # The profile stores keys like package_3_12_months; the card must say
    # words. A raw key on screen reads as a broken page.
    k = bk.knowledge_for(BIZ)
    business = " | ".join(_area(k, "business")["facts"])
    assert "1-on-1 and group programs, usually 3 to 12 month packages" in business
    assert "Governed in Michigan, serves internationally" in business
    money = " | ".join(_area(k, "money")["facts"])
    assert "Payments, bank and QuickBooks connected" in money
    assert "Package and tiered pricing" in money
    for a in k["areas"]:
        for f in a["facts"]:
            assert "_" not in f, f


def test_long_notes_end_at_a_sentence_or_a_word_never_mid_word():
    # Live on KMJ the audience note read "...Whatever your contex…".
    note = ("I work with entrepreneurs from all walks of life, some coming from a faith "
            "background, others not. Whatever your context, the coaching is the same: "
            "practical strategy paired with real accountability.")
    assert bk._clip(note, 120) == ("I work with entrepreneurs from all walks of life, some coming "
                                   "from a faith background, others not.")
    no_stop = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    out = bk._clip(no_stop, 30)
    assert out.endswith("…")
    assert out[:-1] in no_stop and no_stop[len(out) - 1] == " ", out
    assert bk._clip("short", 30) == "short"
