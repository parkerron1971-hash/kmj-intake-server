"""The trial starts without a card (no_card_trial.py, 2026-10-03).

A new business gets a 500-credit trial with no card; a card added during
it keeps the same end date and lifts the tank to the full trial's. Texts,
phone numbers, bulk email and a second site build wait for the card.

The promise this has to keep (Kevin: "make sure that is true"): 500
credits builds a site AND still talks with Chief. It is only true because
the first build is free — a real build is charged 1,000-1,300 credits —
so that is pinned here as arithmetic, not left to a comment.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits  # noqa: E402
import feature_gates as fg  # noqa: E402
import no_card_trial as nct  # noqa: E402
import pricing_config as pc  # noqa: E402
import usage_metering as um  # noqa: E402


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


NOW = datetime.now(timezone.utc)


def _fresh(**over):
    """A business the moment onboarding created it."""
    row = {"id": "biz1", "owner_id": "u1", "settings": {"practitioner_name": "Ana"},
           "subscription_status": None, "stripe_subscription_id": None,
           "trial_ends_at": None, "comp_tier": None}
    row.update(over)
    return row


def _no_card(days_left=5, **over):
    row = _fresh(subscription_status="trialing",
                 trial_ends_at=_iso(NOW + timedelta(days=days_left)),
                 subscription_plan="price_pro",
                 settings={nct.MARKER: {"started_at": _iso(NOW), "plan": "professional",
                                        "credits": 500}})
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "7")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    for k in ("PRICE_TRIAL_CREDITS", "PRICE_TRIAL_CREDITS_NO_CARD", "PRICE_NO_CARD_TRIAL",
              "PRICE_CHAT_PRICE", "PRICE_TRIAL_BUILD_FREE", "NO_CARD_TRIAL_PLAN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: False)


class _Db:
    """Records PATCHes; answers the owner-history read."""

    def __init__(self, owner_history=(), patch_result="row"):
        self.owner_history = list(owner_history)
        self.patch_result = patch_result
        self.patches = []

    def get(self, path):
        if path.startswith("/businesses?owner_id="):
            return self.owner_history
        return []

    def patch(self, path, body):
        self.patches.append((path, body))
        return [{"id": "biz1", **body}] if self.patch_result == "row" else self.patch_result


@pytest.fixture
def db(monkeypatch):
    d = _Db()
    monkeypatch.setattr(nct.sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(nct.sb_clients, "sb_patch_as_service", d.patch)
    import first_run_arc
    monkeypatch.setattr(first_run_arc, "begin", lambda *a, **k: None)
    return d


# ─── The promise: a site AND a conversation ──────────────────────────

# Measured in production on 2026-10-03 (api_usage, last 30 days): a Chief
# turn costs 8.23c on average; the three builds on record cost $1.69,
# $2.88 and $3.25 of AI and were charged 1,000-1,300 credits.
CHAT_COST_CENTS_2026_10 = 8.23
BUILD_COST_CENTS_MAX = 325
BUILD_CREDITS_SMALLEST_REAL = 1000


def test_the_no_card_tank_is_five_hundred_by_default():
    assert pc.trial_credits_no_card() == 500
    assert pc.no_card_trial_enabled() is True


def test_five_hundred_credits_could_never_pay_for_a_build():
    """Why the free first build is load-bearing: without it, the no-card
    trial's whole tank is less than half of one real build."""
    assert pc.trial_credits_no_card() < BUILD_CREDITS_SMALLEST_REAL
    assert pc.trial_credits_no_card() < pc.build_base()
    assert pc.trial_build_free() is True


def test_with_the_free_build_the_tank_is_a_real_conversation():
    turns = pc.trial_credits_no_card() / pc.chat_price()
    assert turns >= 40, f"only {turns:.0f} Chief turns after the build"


def test_the_worst_case_cost_of_a_no_card_signup_is_bounded():
    """Every credit on chat, plus the dearest build on record."""
    turns = pc.trial_credits_no_card() / pc.chat_price()
    worst_cents = turns * CHAT_COST_CENTS_2026_10 + BUILD_COST_CENTS_MAX
    assert worst_cents < 800, f"${worst_cents / 100:.2f} per no-card signup"


def test_a_card_unlocks_the_rest_of_the_full_tank():
    assert pc.trial_credits() > pc.trial_credits_no_card()


def test_the_dials_move_in_railway(monkeypatch):
    monkeypatch.setenv("PRICE_TRIAL_CREDITS_NO_CARD", "750")
    monkeypatch.setenv("PRICE_NO_CARD_TRIAL", "0")
    assert pc.trial_credits_no_card() == 750
    assert pc.no_card_trial_enabled() is False


# ─── Which tank ──────────────────────────────────────────────────────

def test_a_no_card_trial_draws_the_small_tank():
    assert nct.is_no_card(_no_card()) is True
    assert nct.tank(_no_card()) == 500


def test_a_card_ends_the_no_card_state_by_itself():
    """The webhook writes stripe_subscription_id; nothing else to clean up."""
    carded = _no_card(stripe_subscription_id="sub_123")
    assert nct.is_no_card(carded) is False
    assert nct.tank(carded) == pc.trial_credits()


def test_a_card_trial_and_a_platform_chief_trial_keep_the_full_tank():
    stripe_trial = {"id": "b", "subscription_status": "trialing",
                    "stripe_subscription_id": "sub_1", "settings": {},
                    "trial_ends_at": _iso(NOW + timedelta(days=3))}
    hand_given = {"id": "b", "subscription_status": "trialing", "settings": {},
                  "trial_ends_at": _iso(NOW + timedelta(days=3))}
    for row in (stripe_trial, hand_given):
        assert nct.is_no_card(row) is False
        assert nct.tank(row) == pc.trial_credits()


def test_a_row_without_the_subscription_column_is_never_read_as_no_card():
    """The marker stays after a card is added; only stripe_subscription_id
    tells the two apart. A row read without that column must take the
    full tank rather than guess — or a carded trial is measured against
    500 and mailed that it ended."""
    carded_but_unread = {k: v for k, v in _no_card().items()
                         if k != "stripe_subscription_id"}
    assert nct.is_no_card(carded_but_unread) is False
    assert nct.tank(carded_but_unread) == pc.trial_credits()


def test_a_comp_outranks_the_no_card_trial():
    comped = _no_card(comp_tier="practice")
    assert nct.is_no_card(comped) is False
    assert nct.tank(comped) == pc.trial_credits()


def test_the_trial_mail_sweep_reads_the_subscription_column():
    import lifecycle_emails
    assert "stripe_subscription_id" in lifecycle_emails._BIZ_SELECT


def test_a_spent_no_card_trial_is_mailed_for_a_card_not_told_it_ended(monkeypatch):
    import lifecycle_emails as le
    monkeypatch.setattr(le, "_tank_spent", lambda row: True)
    need = le._classify(_no_card(days_left=4), datetime.now(timezone.utc))
    assert need == {"kind": "trial_ended", "reason": "no_card_credits_spent"}
    body = le.trial_ended_body(business_name="Ana's Studio", first_name="Ana",
                               reason="no_card_credits_spent")
    assert "Add a card" in body and "500 more credits" in body
    assert "has ended" not in body


def test_the_meter_reports_the_small_tank(monkeypatch):
    row = _no_card()
    monkeypatch.setattr(um, "weighted_usage_since", lambda biz, since: 120)
    monkeypatch.setattr(um, "grant_units_this_month", lambda biz: 0)
    monkeypatch.setattr(um, "is_grandfathered_business", lambda biz, row=None: False)
    monkeypatch.setattr(um.credit_ledger, "sync_burn", lambda biz, n: 0)
    monkeypatch.setattr(um.credit_ledger, "balance", lambda biz: 0)
    s = um.usage_summary("biz1", row)
    assert s["on_trial"] is True
    assert s["allotment"] == 500
    assert s["remaining"] == 380


def test_the_free_build_applies_to_a_no_card_trial(monkeypatch):
    monkeypatch.setattr(um.sb_clients, "sb_get_as_service", lambda path: [])
    assert um.trial_first_build_is_free("biz1", _no_card()) is True


# ─── Who gets one ────────────────────────────────────────────────────

def test_a_fresh_business_is_eligible(db):
    assert nct.eligible(_fresh()) is None


@pytest.mark.parametrize("over,why", [
    ({"comp_tier": "practice"}, "comped"),
    ({"stripe_subscription_id": "sub_1"}, "has_subscription"),
    ({"trial_ends_at": _iso(NOW)}, "had_trial"),
    ({"settings": {nct.MARKER: {}}}, "had_trial"),
    ({"subscription_status": "canceled"}, "has_status"),
])
def test_only_a_business_that_never_had_a_trial_or_a_plan(db, over, why):
    assert nct.eligible(_fresh(**over)) == why


def test_once_per_person_not_per_business(db):
    db.owner_history = [{"id": "other-biz"}]
    assert nct.eligible(_fresh()) == "owner_had_trial"


def test_an_unreadable_owner_history_keeps_the_card_door(monkeypatch, db):
    monkeypatch.setattr(nct.sb_clients, "sb_get_as_service", lambda path: None)
    assert nct.eligible(_fresh()) == "owner_history_unreadable"


def test_grandfathered_accounts_never_need_one(monkeypatch, db):
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: True)
    assert nct.eligible(_fresh()) == "grandfathered"


def test_nothing_starts_while_enforcement_is_off(monkeypatch, db):
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    assert nct.eligible(_fresh()) == "enforcement_off"


def test_the_kill_switch(monkeypatch, db):
    monkeypatch.setenv("PRICE_NO_CARD_TRIAL", "0")
    assert nct.eligible(_fresh()) == "disabled"


def test_no_trial_without_a_configured_plan_price(monkeypatch, db):
    monkeypatch.delenv("STRIPE_PRICE_ID_PROFESSIONAL")
    assert nct.eligible(_fresh()) == "plan_not_configured"


# ─── Starting it ─────────────────────────────────────────────────────

def test_start_writes_the_trial_row_the_rest_of_the_system_knows(db):
    out = nct.start(_fresh())
    assert out and out["credits"] == 500 and out["plan"] == "professional"
    path, body = db.patches[-1]
    # Conditional: a racing second start, or a Stripe webhook that landed
    # first, matches nothing.
    assert "stripe_subscription_id=is.null" in path and "trial_ends_at=is.null" in path
    assert body["subscription_status"] == "trialing"
    assert body["subscription_plan"] == "price_pro"
    assert body["tier"] == "professional"
    ends = datetime.fromisoformat(body["trial_ends_at"])
    assert 6.9 < (ends - NOW).total_seconds() / 86400 < 7.1
    # The settings it found are kept; the marker is added beside them.
    assert body["settings"]["practitioner_name"] == "Ana"
    assert body["settings"][nct.MARKER]["credits"] == 500


def test_a_lost_race_reports_no_trial(db):
    db.patch_result = []
    assert nct.start(_fresh()) is None


def test_start_never_raises(monkeypatch, db):
    def _boom(*a, **k):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(nct.sb_clients, "sb_patch_as_service", _boom)
    assert nct.start(_fresh()) is None


def test_an_ineligible_business_is_left_alone(db):
    assert nct.start(_fresh(stripe_subscription_id="sub_1")) is None
    assert db.patches == []


def test_signup_starts_the_trial():
    import launch_access
    src = inspect.getsource(launch_access.create_business)
    assert "no_card_trial.start(" in src


def test_the_access_check_is_the_second_door():
    import stripe_billing
    src = inspect.getsource(stripe_billing.billing_access)
    assert "no_card_trial.start" in src
    assert "no_card_trial.describe" in src


# ─── Adding a card ───────────────────────────────────────────────────

def test_a_card_mid_trial_keeps_the_trial_end():
    row = _no_card(days_left=5)
    out = nct.checkout_trial(row)
    end = datetime.fromtimestamp(out["trial_end"], tz=timezone.utc)
    assert abs((end - datetime.fromisoformat(row["trial_ends_at"].replace("Z", "+00:00"))).total_seconds()) < 2


def test_stripe_gets_its_48_hours_near_the_end():
    out = nct.checkout_trial(_no_card(days_left=1))
    end = datetime.fromtimestamp(out["trial_end"], tz=timezone.utc)
    assert (end - datetime.now(timezone.utc)) >= timedelta(hours=48)


def test_after_the_trial_a_card_starts_a_plain_subscription():
    ended = _no_card(days_left=-1, subscription_status="canceled")
    assert nct.checkout_trial(ended) == {}


def test_checkout_subscription_data_for_each_case():
    import stripe_billing
    user = type("U", (), {"id": "u1"})()
    running = stripe_billing._subscription_data(_no_card(days_left=5), user)
    assert "trial_end" in running and "trial_period_days" not in running
    ended = stripe_billing._subscription_data(
        _no_card(days_left=-1, subscription_status="canceled"), user)
    assert "trial_end" not in ended and "trial_period_days" not in ended
    first = stripe_billing._subscription_data(_fresh(), user)
    assert first["trial_period_days"] == 7
    pay_now = stripe_billing._subscription_data(_no_card(days_left=5), user, skip_trial=True)
    assert "trial_end" not in pay_now and "trial_period_days" not in pay_now


# ─── When it ends ────────────────────────────────────────────────────

def test_a_closed_no_card_trial_reads_as_a_trial_that_ended():
    ended = _no_card(days_left=-1, subscription_status="canceled")
    # The reverse trial (test_reverse_trial.py): free, not locked.
    assert fg.access_state(ended) == {"state": "free", "reason": "trial_expired"}


def test_a_canceled_paid_subscription_still_reads_as_canceled():
    paid = {"subscription_status": "canceled", "stripe_subscription_id": "sub_1",
            "trial_ends_at": _iso(NOW - timedelta(days=40))}
    assert fg.access_state(paid)["reason"] == "canceled"


def test_the_spent_message_asks_for_a_card_not_a_plan():
    msg = billing_limits._locked_message("trial_credits_spent", _no_card())
    assert "Add a card" in msg and "500 more" in msg
    assert "nothing is charged" in msg


# ─── What waits for a card ───────────────────────────────────────────

def test_require_card_refuses_a_no_card_trial(monkeypatch):
    monkeypatch.setattr(um, "_biz_row", lambda biz: _no_card())
    with pytest.raises(HTTPException) as ei:
        billing_limits.require_card("biz1", "texts")
    assert ei.value.status_code == 402
    assert ei.value.detail["error"] == "card_required"
    assert "Settings → Billing" in ei.value.detail["message"]


def test_require_card_passes_everyone_else(monkeypatch):
    for row in (_no_card(stripe_subscription_id="sub_1"), _fresh(), None):
        monkeypatch.setattr(um, "_biz_row", lambda biz, r=row: r)
        billing_limits.require_card("biz1", "texts")


def test_require_card_fails_open(monkeypatch):
    def _boom(biz):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(um, "_biz_row", _boom)
    billing_limits.require_card("biz1", "texts")


def test_the_refusal_says_what_adding_a_card_does():
    msg = nct.card_message("texts", _no_card(days_left=5))
    assert "nothing is charged until your trial ends" in msg
    assert "500 more credits" in msg


def _verified(**over):
    m = {"started_at": _iso(NOW), "plan": "professional", "credits": 500,
         "phone_hash": "h", "phone_verified_at": _iso(NOW)}
    return _no_card(settings={nct.MARKER: m}, **over)


class _BuildDb:
    """api_usage markers for THIS business, and today's free builds."""

    def __init__(self, own_markers=(), today=(), today_biz=()):
        self.own, self.today, self.today_biz = list(own_markers), list(today), list(today_biz)

    def get(self, path):
        if path.startswith("/api_usage?business_id="):
            return self.own
        if path.startswith("/api_usage?task_type=eq.site_build_marker&units=eq.0"):
            return self.today
        if path.startswith("/businesses?id=in."):
            return self.today_biz
        return []


def _build_env(monkeypatch, row, db):
    monkeypatch.setattr(um, "_biz_row", lambda biz: row)
    monkeypatch.setattr(nct.sb_clients, "sb_get_as_service", db.get)


def test_the_second_build_waits_for_a_card(monkeypatch):
    _build_env(monkeypatch, _verified(), _BuildDb(own_markers=[{"id": "m1"}]))
    with pytest.raises(nct.CardRequired) as ei:
        nct.check_build("biz1")
    assert ei.value.what == "rebuild"
    assert "one site build" in ei.value.message


def test_the_free_build_waits_for_a_verified_phone(monkeypatch):
    _build_env(monkeypatch, _no_card(), _BuildDb())
    with pytest.raises(nct.PhoneRequired) as ei:
        nct.check_build("biz1")
    assert ei.value.detail()["error"] == "phone_required"


def test_a_verified_phone_gets_the_free_build(monkeypatch):
    _build_env(monkeypatch, _verified(), _BuildDb())
    nct.check_build("biz1")


def test_the_daily_ceiling_holds_free_builds(monkeypatch):
    monkeypatch.setenv("LIMIT_NO_CARD_FREE_BUILDS_PER_DAY", "2")
    others = [{"business_id": f"b{i}"} for i in range(2)]
    others_rows = [_no_card(id=f"b{i}") for i in range(2)]
    _build_env(monkeypatch, _verified(), _BuildDb(today=others, today_biz=others_rows))
    with pytest.raises(nct.CardRequired) as ei:
        nct.check_build("biz1")
    assert ei.value.what == "builds_full"
    assert "try again tomorrow" in ei.value.message


def test_card_trials_free_builds_do_not_count_against_the_ceiling(monkeypatch):
    monkeypatch.setenv("LIMIT_NO_CARD_FREE_BUILDS_PER_DAY", "1")
    carded = [_no_card(id="b0", stripe_subscription_id="sub_1")]
    _build_env(monkeypatch, _verified(),
               _BuildDb(today=[{"business_id": "b0"}], today_biz=carded))
    nct.check_build("biz1")


def test_an_unreadable_count_fails_closed(monkeypatch):
    """The one gate that fails CLOSED: an unreadable count must not
    become unlimited free builds on Kevin's money."""
    class _Db(_BuildDb):
        def get(self, path):
            if "units=eq.0" in path:
                return None
            return super().get(path)
    _build_env(monkeypatch, _verified(), _Db())
    with pytest.raises(nct.CardRequired):
        nct.check_build("biz1")


def test_zero_free_builds_means_the_build_waits_for_a_card(monkeypatch):
    monkeypatch.setenv("LIMIT_NO_CARD_FREE_BUILDS_PER_DAY", "0")
    _build_env(monkeypatch, _verified(), _BuildDb())
    with pytest.raises(nct.CardRequired):
        nct.check_build("biz1")


def test_a_card_trial_builds_as_before(monkeypatch):
    _build_env(monkeypatch, _no_card(stripe_subscription_id="sub_1"),
               _BuildDb(own_markers=[{"id": "m1"}]))
    nct.check_build("biz1")


def test_blueprint_drafts_wait_for_the_phone_too(monkeypatch):
    monkeypatch.setattr(um, "_biz_row", lambda biz: _no_card())
    with pytest.raises(nct.PhoneRequired):
        nct.check_phone("biz1")
    monkeypatch.setattr(um, "_biz_row", lambda biz: _verified())
    nct.check_phone("biz1")


def test_every_paid_build_passes_the_build_check():
    import site_composer
    src = inspect.getsource(site_composer.compose_site)
    assert "check_build" in src.split("CANVAS PROTECTION")[0]


def test_the_free_build_skips_the_offer_page():
    import site_composer
    src = inspect.getsource(site_composer.compose_site)
    offer = src[src.index("_offer_built = False"):src.index("build_offer_page(")]
    assert "not _no_card" in offer


def test_the_app_build_door_refuses_up_front():
    """The app starts every build through /agents/chief/jobs/rebuild; the
    refusal must be a 402 there, not a queued job that fails later."""
    import chief_jobs
    assert "_no_card_gate(no_card_build=True" in inspect.getsource(chief_jobs.rebuild_site_endpoint)
    assert "_no_card_gate(no_card_build=False" in inspect.getsource(chief_jobs.author_spec_endpoint)


# ─── The phone check ─────────────────────────────────────────────────

class _PhoneDb:
    def __init__(self, row, taken=False):
        self.row, self.taken, self.patches = row, taken, []

    def get(self, path):
        if "phone_hash=eq." in path:
            return [{"id": "other"}] if self.taken else []
        if path.startswith("/businesses?id=eq."):
            return [{"settings": self.row.get("settings")}]
        return []

    def patch(self, path, body):
        self.patches.append(body)
        return [body]


@pytest.fixture
def phone_env(monkeypatch):
    import rate_limit
    import twilio_sms
    sent = []
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key: True)
    monkeypatch.setattr(twilio_sms, "send_sms",
                        lambda to, body, from_number=None: sent.append((to, body)) or "SM1")
    monkeypatch.setattr(twilio_sms, "platform_number", lambda: "+12165550000")
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    return sent


def _code_from(sent):
    import re
    return re.search(r"(\d{6})", sent[-1][1]).group(1)


def _phone_db(monkeypatch, row, taken=False):
    db = _PhoneDb(row, taken=taken)
    monkeypatch.setattr(um, "_biz_row", lambda biz: row)
    monkeypatch.setattr(nct.sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(nct.sb_clients, "sb_patch_as_service", db.patch)
    return db


def test_a_code_texts_and_verifies(monkeypatch, phone_env):
    db = _phone_db(monkeypatch, _no_card())
    out = nct.send_phone_code("biz1", "(216) 555-0100")
    assert out["ok"] and out["token"] and phone_env[-1][0] == "+12165550100"
    code = _code_from(phone_env)
    assert nct.verify_phone_code("biz1", "216-555-0100", code, out["token"])["verified"]
    saved = db.patches[-1]["settings"][nct.MARKER]
    assert saved["phone_hash"] == nct.phone_hash("+12165550100")
    assert saved["phone_verified_at"]
    assert saved["credits"] == 500          # the marker around it survives


def test_a_wrong_code_is_refused(monkeypatch, phone_env):
    db = _phone_db(monkeypatch, _no_card())
    out = nct.send_phone_code("biz1", "2165550100")
    wrong = "000000" if _code_from(phone_env) != "000000" else "111111"
    with pytest.raises(nct.PhoneError):
        nct.verify_phone_code("biz1", "2165550100", wrong, out["token"])
    assert db.patches == []


def test_a_code_for_one_number_does_not_verify_another(monkeypatch, phone_env):
    _phone_db(monkeypatch, _no_card())
    out = nct.send_phone_code("biz1", "2165550100")
    with pytest.raises(nct.PhoneError):
        nct.verify_phone_code("biz1", "2165550199", _code_from(phone_env), out["token"])


def test_an_expired_code_is_refused(monkeypatch, phone_env):
    _phone_db(monkeypatch, _no_card())
    code, exp = "123456", 1000
    token = f"{exp}.{nct._code_sig('biz1', '+12165550100', code, exp)}"
    with pytest.raises(nct.PhoneError) as ei:
        nct.verify_phone_code("biz1", "2165550100", code, token)
    assert "expired" in str(ei.value)


def test_us_and_canada_numbers_only(monkeypatch, phone_env):
    """OTP forms are the SMS-pumping target; premium international
    numbers are how it pays."""
    _phone_db(monkeypatch, _no_card())
    for bad in ("+447700900123", "+2348012345678", "12345", ""):
        with pytest.raises(nct.PhoneError):
            nct.send_phone_code("biz1", bad)
    assert phone_env == []


def test_one_phone_one_free_build_across_the_platform(monkeypatch, phone_env):
    _phone_db(monkeypatch, _no_card(), taken=True)
    with pytest.raises(nct.PhoneError) as ei:
        nct.send_phone_code("biz1", "2165550100")
    assert "another account" in str(ei.value)
    assert phone_env == []


def test_sending_is_rate_limited(monkeypatch, phone_env):
    import rate_limit
    _phone_db(monkeypatch, _no_card())
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key: False)
    with pytest.raises(nct.PhoneError):
        nct.send_phone_code("biz1", "2165550100")
    assert phone_env == []


def test_the_phone_buckets_are_registered():
    """An unregistered bucket silently falls to the 60-a-minute default."""
    import rate_limit
    assert rate_limit._LIMITS["trial_phone_send"][0] <= 5
    assert rate_limit._LIMITS["trial_phone_check"][0] <= 10


def test_the_endpoints_are_owner_only():
    import stripe_billing
    for fn in (stripe_billing.trial_phone_send, stripe_billing.trial_phone_verify):
        assert "_require_owner_of(user, biz)" in inspect.getsource(fn)


# ─── Throwaway emails ────────────────────────────────────────────────

def test_throwaway_inboxes_get_no_free_trial(db):
    assert nct.eligible(_fresh(), "someone@mailinator.com") == "disposable_email"
    assert nct.eligible(_fresh(), "ana@gmail.com") is None


def test_more_throwaway_domains_from_railway(monkeypatch, db):
    monkeypatch.setenv("DISPOSABLE_EMAIL_DOMAINS", "junk.example, other.test")
    assert nct.eligible(_fresh(), "x@junk.example") == "disposable_email"


# ─── Preview-only until a card ───────────────────────────────────────

def test_a_no_card_site_is_hidden_and_a_carded_one_is_live(monkeypatch):
    nct._hidden_cache.clear()
    monkeypatch.setattr(nct.sb_clients, "sb_as_service", _async_rows(_no_card()))
    assert asyncio.run(nct.site_hidden(object(), "biz1")) is True
    nct.forget("biz1")
    monkeypatch.setattr(nct.sb_clients, "sb_as_service",
                        _async_rows(_no_card(stripe_subscription_id="sub_1")))
    assert asyncio.run(nct.site_hidden(object(), "biz1")) is False


def test_the_hidden_answer_is_cached_briefly(monkeypatch):
    nct._hidden_cache.clear()
    calls = []

    async def _count(client, method, path, body=None):
        calls.append(path)
        return [_no_card()]
    monkeypatch.setattr(nct.sb_clients, "sb_as_service", _count)
    for _ in range(3):
        asyncio.run(nct.site_hidden(object(), "biz1"))
    assert len(calls) == 1


def test_both_public_doors_show_coming_soon():
    import public_site
    for fn in (public_site._serve_site_by_slug, public_site._serve_site_by_custom_domain):
        assert "site_hidden" in inspect.getsource(fn), fn.__name__


def test_the_coming_soon_page_says_so(monkeypatch):
    import public_site

    async def _no_rows(client, path):
        return []
    monkeypatch.setattr(public_site, "_sb", _no_rows)
    resp = asyncio.run(public_site._render_offline_page(object(), None, coming_soon=True))
    body = resp.body.decode("utf-8")
    assert "Coming soon" in body and "right back" not in body
    assert resp.status_code == 503


def test_a_card_lifts_the_preview_at_once():
    import stripe_billing
    assert "no_card_trial.forget(business_id)" in inspect.getsource(
        stripe_billing._apply_subscription_state)


def _async_rows(row):
    async def _fake(client, method, path, body=None):
        return [row] if row else []
    return _fake


def test_texts_stop_at_the_sender_seam(monkeypatch):
    import sms_service
    monkeypatch.setattr(nct.sb_clients, "sb_as_service", _async_rows(_no_card()))
    with pytest.raises(nct.CardRequired):
        asyncio.run(sms_service.sender_for(object(), "biz1"))


def test_a_pressed_send_gets_a_402_with_its_words(monkeypatch):
    import sms_service
    monkeypatch.setattr(nct.sb_clients, "sb_as_service", _async_rows(_no_card()))
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)
    with pytest.raises(sms_service.SmsSendError) as ei:
        asyncio.run(sms_service.send_sms_core(object(), business_id="biz1",
                                              to="+12165550100", message="hi"))
    assert ei.value.status == 402
    assert "card" in str(ei.value)


def test_the_bulk_and_sending_surfaces_ask_for_a_card():
    import campaigns_router
    import sms_numbers_router
    import sms_routing
    assert "require_card" in inspect.getsource(campaigns_router.launch_campaign_core)
    assert "require_card" in inspect.getsource(sms_numbers_router.provision_core)
    assert "require_card" in inspect.getsource(sms_routing.broadcast)


def test_chief_says_it_in_the_turn_before_the_trust_gate():
    import chief_of_staff
    for verb in ("send_sms", "provision_sms_number", "batch_email",
                 "bulk_approve", "launch_campaign"):
        assert verb in chief_of_staff._CARD_GATED_VERBS
    src = inspect.getsource(chief_of_staff._execute_actions)
    assert src.index("_CARD_GATED_VERBS") < src.index("_gate_class_c(")


def test_one_to_one_mail_stays_open():
    """A booking confirmation, an invoice, a reply to one client: how a
    practitioner tries the product. None of them may wait for a card."""
    import chief_of_staff
    for verb in ("draft_and_send", "send_invoice", "approve_draft", "send_email"):
        assert verb not in chief_of_staff._CARD_GATED_VERBS


# ─── The front door can say it ───────────────────────────────────────

def test_access_open_says_no_card_only_when_signup_will_start_one(monkeypatch):
    import launch_access
    out = launch_access.access_open()
    assert out["no_card_trial"] is True and out["trial_credits"] == 500
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    assert launch_access.access_open()["no_card_trial"] is False
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("PRICE_NO_CARD_TRIAL", "0")
    assert launch_access.access_open()["no_card_trial"] is False


def test_describe_tells_the_app_what_a_card_adds():
    assert nct.describe(_no_card()) == {"no_card_trial": True, "trial_credits": 500,
                                        "card_trial_credits": 1000,
                                        "phone_verified": False, "site_live": False}
    assert nct.describe(_verified())["phone_verified"] is True
    assert nct.describe(_fresh()) == {"no_card_trial": False}
