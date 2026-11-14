"""The sample church, BE-1 (sample_church.py, 2026-11-15).

A church that signs up gets no working trial: it looks around a private copy
of a made-up church (Grace Street Fellowship) where nothing is saved or sent,
and choosing a plan starts the real church and deletes the sample. Kevin,
2026-11-14: "top tier, no cut corners". This PR must change NOTHING for real
users while CHURCH_SAMPLE sits at its shipped default (test, nobody listed).

What is pinned here:
  · the switch (off / test / on, testers) and the column probe;
  · applies(), the whole truth table, and that the default costs no read;
  · both trial doors refuse a sample and a church in one;
  · signup answers sample pending, skips the trial and the first-run arc;
  · access_state 'sample' for a sample row and a home; the gates' 409s;
  · GET /billing/access's sample block, made lazily;
  · ensure() makes one row under a real race;
  · checkout, credits, Connect, numbers, registration and domains refuse;
  · the webhook ends the sample and opens the arc; a home's delete takes it;
  · the migration and its ledger row.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
import threading
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits  # noqa: E402
import feature_gates as fg  # noqa: E402
import no_card_trial as nct  # noqa: E402
import sample_church as sc  # noqa: E402
import usage_metering as um  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

ROOT = _here.parent
HOME, SAMPLE, OWNER = "home-1", "sample-1", "owner-1"
TESTER = "tester@church.test"
PASTOR = AuthedUser(id=OWNER, email=TESTER, role="authenticated")


def _home(**over):
    """A church the moment onboarding created it (select=* shape)."""
    row = {"id": HOME, "owner_id": OWNER, "name": "First Church", "type": "church",
           "settings": {"practitioner_name": "Ana", "availability": {"timezone": "America/Chicago"}},
           "subscription_status": None, "stripe_subscription_id": None,
           "trial_ends_at": None, "comp_tier": None, "is_sample": False, "sample_of": None,
           "is_active": True}
    row.update(over)
    return row


def _sample_row(**over):
    row = {"id": SAMPLE, "owner_id": OWNER, "name": sc.NAME, "type": "church",
           "settings": {sc.SETTINGS_KEY: {"version": 0, "status": "pending"}},
           "subscription_status": None, "stripe_subscription_id": None,
           "trial_ends_at": None, "comp_tier": None, "is_sample": True, "sample_of": HOME,
           "is_active": False}
    row.update(over)
    return row


class _Counting(FakeSB):
    """FakeSB that counts reads and keeps one sample per home, like the
    unique index: a second insert for the same home is refused (None)."""

    def __init__(self):
        super().__init__()
        self.reads = []

    def get(self, path):
        self.reads.append(path)
        return super().get(path)

    def post(self, path, body, prefer="rep"):
        if path.startswith("/businesses") and body.get("sample_of"):
            if any(r.get("sample_of") == body["sample_of"] for r in self.rows("businesses")):
                return None
        return super().post(path, body, prefer)


@pytest.fixture
def db(monkeypatch):
    fb = _Counting()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="return=representation": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("CHURCH_SAMPLE", "on")
    monkeypatch.delenv("CHURCH_SAMPLE_TESTERS", raising=False)
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: False)
    monkeypatch.setattr(sc, "_owner_email", lambda owner: TESTER)
    sc._reset_for_tests()
    return fb


# ─── The switch ───────────────────────────────────────────────────────

def test_the_shipped_default_is_test_with_nobody_listed(monkeypatch):
    monkeypatch.delenv("CHURCH_SAMPLE", raising=False)
    monkeypatch.delenv("CHURCH_SAMPLE_TESTERS", raising=False)
    assert sc.mode() == "test"
    assert sc.testers() == frozenset()


@pytest.mark.parametrize("raw,mode", [("off", "off"), ("ON", "on"), (" test ", "test"),
                                      ("yes", "off"), ("1", "off"), ("", "test")])
def test_the_switch_reads_three_words_and_anything_else_is_off(monkeypatch, raw, mode):
    monkeypatch.setenv("CHURCH_SAMPLE", raw)
    assert sc.mode() == mode


def test_testers_are_a_comma_list_of_emails(monkeypatch):
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", " A@x.test, b@y.test ,,not-an-email")
    assert sc.testers() == {"a@x.test", "b@y.test"}


def test_the_default_changes_nothing_and_reads_nothing(db, monkeypatch):
    """CHURCH_SAMPLE=test with nobody listed: every church signs up exactly
    as before, and applies() answers before touching the database."""
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    monkeypatch.setattr(sc, "_columns_ready", lambda: pytest.fail("probed the columns"))
    monkeypatch.setattr(sc, "_owner_email", lambda owner: pytest.fail("read an email"))
    assert sc.applies(_home()) is False
    assert db.reads == []
    assert nct.eligible(_home(), TESTER) not in ("church_sample", "sample")


def test_off_is_nobody(db, monkeypatch):
    monkeypatch.setenv("CHURCH_SAMPLE", "off")
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", TESTER)
    assert sc.applies(_home(), TESTER) is False


def test_test_mode_is_only_the_listed_owners(db, monkeypatch):
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", TESTER)
    assert sc.applies(_home(), TESTER) is True
    assert sc.applies(_home(), "someone@else.test") is False
    # Without the signer's email in hand, the owner's sign-in email decides.
    assert sc.applies(_home()) is True
    monkeypatch.setattr(sc, "_owner_email", lambda owner: "someone@else.test")
    assert sc.applies(_home()) is False
    # An unreadable email is "no", never a guess.
    monkeypatch.setattr(sc, "_owner_email", lambda owner: None)
    assert sc.applies(_home()) is False


def test_on_is_every_new_church(db):
    assert sc.applies(_home(), "anyone@church.test") is True


# ─── Who gets one: the truth table ────────────────────────────────────

NOW = datetime.now(timezone.utc)


@pytest.mark.parametrize("over,expect", [
    ({}, True),
    ({"type": "ministry"}, True),
    ({"type": "coach"}, False),                                    # a business keeps its trial
    ({"type": "barber"}, False),
    ({"trial_ends_at": (NOW + timedelta(days=5)).isoformat(),
      "subscription_status": "trialing"}, False),                  # a church already on a trial
    ({"trial_ends_at": (NOW - timedelta(days=5)).isoformat(),
      "subscription_status": "canceled"}, False),                  # one whose trial ended
    ({"comp_tier": "church_growing"}, False),                      # comped
    ({"stripe_subscription_id": "sub_1"}, False),                  # subscribed
    ({"subscription_status": "active"}, False),
    ({"subscription_status": "past_due"}, False),
    ({"is_sample": True, "sample_of": "other"}, False),            # a sample is never a home
])
def test_applies_truth_table(db, over, expect):
    assert sc.applies(_home(**over)) is expect


def test_a_grandfathered_owner_keeps_today(db, monkeypatch):
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: True)
    assert sc.applies(_home()) is False
    assert sc.applies(_home(), grandfathered=True) is False


def test_nothing_while_billing_is_not_enforced(db, monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    assert sc.applies(_home()) is False


def test_a_narrow_row_is_read_whole_once(db):
    """A select that left columns out (usage_metering._biz_row has no type)
    is read whole, and the answer is the same."""
    db.rows("businesses").append(_home())
    narrow = {"id": HOME, "owner_id": OWNER, "subscription_status": None,
              "stripe_subscription_id": None, "trial_ends_at": None, "comp_tier": None}
    assert sc.applies(narrow) is True
    assert len([p for p in db.reads if p.startswith(f"/businesses?id=eq.{HOME}")]) == 1


def test_a_row_ruled_out_by_what_it_carries_is_never_read(db):
    sc.applies({"id": HOME, "subscription_status": "active"})
    sc.applies({"id": HOME, "type": "coach"})
    assert db.reads == []


def test_applies_never_raises(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    assert sc.applies({"id": HOME}) is False


# ─── Columns missing: everything behaves as off ───────────────────────

def test_without_the_columns_nothing_is_a_sample(db, monkeypatch):
    monkeypatch.setattr(sc, "_columns_ready", lambda: False)
    db.rows("businesses").extend([_home(), _sample_row()])
    assert sc.applies(_home()) is False
    assert sc.is_sample(SAMPLE) is False
    assert sc.sample_for(HOME) is None
    assert sc.home_of(SAMPLE) is None
    assert sc.ensure(_home()) is None
    assert asyncio.run(sc.end(HOME)) is None
    assert sc.open_to_all() is False


def test_the_probe_is_the_shared_schema_probe(monkeypatch):
    import schema_probe
    seen = []
    monkeypatch.setattr(schema_probe, "has_columns", lambda t, c: seen.append((t, tuple(c))) or True)
    assert sc._columns_ready() is True
    assert seen == [("businesses", ("is_sample", "sample_of"))]


def test_no_supabase_means_no_columns(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    import schema_probe
    schema_probe.reset()
    assert sc._columns_ready() is False


# ─── What is a sample ─────────────────────────────────────────────────

def test_is_sample_is_read_once_and_kept(db):
    db.rows("businesses").extend([_home(), _sample_row()])
    assert sc.is_sample(SAMPLE) is True
    assert sc.is_sample(HOME) is False
    before = len(db.reads)
    assert sc.is_sample(SAMPLE) is True and sc.is_sample(HOME) is False
    assert len(db.reads) == before


def test_an_unreadable_answer_is_no_and_asked_again(db, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: None)
    assert sc.is_sample(SAMPLE) is False
    assert SAMPLE not in sc._KIND


def test_a_row_in_hand_answers_from_its_own_column(db):
    assert sc.row_is_sample(_sample_row()) is True
    assert sc.row_is_sample(_home()) is False
    assert sc.skip(_sample_row()) is True and sc.skip(_home()) is False
    assert db.reads == []


def test_sample_for_and_home_of(db):
    db.rows("businesses").extend([_home(), _sample_row()])
    assert sc.sample_for(HOME)["id"] == SAMPLE
    assert sc.home_of(SAMPLE) == HOME
    assert sc.home_of(HOME) is None
    assert sc.sample_for(SAMPLE) is None


# ─── The trial doors ──────────────────────────────────────────────────

def test_eligible_refuses_a_sample_and_a_church_in_one(db, monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    assert nct.eligible(_sample_row(), TESTER) == "sample"
    assert nct.eligible(_home(), TESTER) == "church_sample"
    # First, whatever the trial's own switches say.
    monkeypatch.setenv("PRICE_NO_CARD_TRIAL", "0")
    assert nct.eligible(_sample_row()) == "sample"
    assert nct.eligible(_home()) == "church_sample"


def test_eligible_is_unchanged_for_a_business(db, monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "7")
    monkeypatch.delenv("PRICE_NO_CARD_TRIAL", raising=False)
    coach = _home(type="coach")
    assert nct.eligible(coach, "coach@biz.test") is None


def test_start_never_writes_a_trial_on_either(db, monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    assert nct.start(_home(), email=TESTER) is None
    assert nct.start(_sample_row()) is None
    assert db.rows("businesses") == []


# ─── Signup ───────────────────────────────────────────────────────────

class _Tasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


@pytest.fixture
def signup(db, monkeypatch):
    import first_run_arc
    import launch_access
    calls = {"start": [], "begin": []}
    monkeypatch.setattr(nct, "start", lambda row, source="signup", email=None:
                        calls["start"].append(row["id"]) or {"trial_ends_at": "x"})
    monkeypatch.setattr(first_run_arc, "begin",
                        lambda biz, **kw: calls["begin"].append((biz, kw)))
    monkeypatch.delenv("LAUNCH_INVITE_ONLY", raising=False)
    calls["la"] = launch_access
    return calls


def _create(signup, btype="church", user=PASTOR):
    la = signup["la"]
    tasks = _Tasks()
    out = la.create_business(la.CreateBusinessBody(name="First Church", type=btype), user, tasks)
    return out, tasks


def test_a_church_signs_up_into_a_sample(signup, db):
    out, tasks = _create(signup)
    assert out["ok"] and out["sample"] == {"pending": True}
    assert out["trial"] is None
    assert signup["start"] == []                      # no trial
    assert signup["begin"] == []                      # no first week yet
    assert sc.ensure in [fn for fn, _, _ in tasks.calls]   # the sample, after the response
    import lifecycle_emails
    assert lifecycle_emails.send_welcome in [fn for fn, _, _ in tasks.calls]  # still welcomed


def test_the_background_ensure_makes_the_row(signup, db):
    out, tasks = _create(signup)
    fn, a, k = next(c for c in tasks.calls if c[0] is sc.ensure)
    made = fn(*a, **k)
    assert made and made["sample_of"] == out["business"]["id"]


def test_a_business_signs_up_exactly_as_before(signup, db):
    out, _ = _create(signup, btype="coach")
    assert "sample" not in out
    assert out["trial"] == {"trial_ends_at": "x"}
    assert len(signup["start"]) == 1 and len(signup["begin"]) == 1


def test_a_church_not_listed_in_test_mode_signs_up_as_before(signup, db, monkeypatch):
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", "someone@else.test")
    out, _ = _create(signup)
    assert "sample" not in out
    assert len(signup["start"]) == 1 and len(signup["begin"]) == 1


def test_the_signup_source_keeps_the_trial_door(signup):
    import inspect
    src = inspect.getsource(signup["la"].create_business)
    assert "no_card_trial.start(" in src and "sample_church.applies(" in src


# ─── Making the sample ────────────────────────────────────────────────

def test_ensure_makes_one_quiet_inactive_row(db):
    made = sc.ensure(_home())
    rows = [r for r in db.rows("businesses") if r.get("is_sample")]
    assert len(rows) == 1 and made["id"] == rows[0]["id"]
    r = rows[0]
    assert r["name"] == "Grace Street Fellowship"
    assert r["type"] == "church" and r["owner_id"] == OWNER
    assert r["is_active"] is False and r["is_sample"] is True and r["sample_of"] == HOME
    s = r["settings"]
    assert s["sample_church"]["version"] == 0 and s["sample_church"]["status"] == "pending"
    # Every send the system already knows how to switch off, off.
    assert s["automations_paused"] is True
    assert s["autonomy"]["client_facing_autonomy"] == "disabled"
    assert s["autopilot"] == {"overall": "manual", "per_team": {}}
    assert s["sms_alerts"] == {"confirmations": False, "reminders": False}
    # The home's clock and pastor.
    assert s["practitioner_name"] == "Ana"
    assert s["availability"] == {"timezone": "America/Chicago"}


def test_ensure_is_idempotent(db):
    first = sc.ensure(_home())
    again = sc.ensure(_home())
    assert first["id"] == again["id"]
    assert len([r for r in db.rows("businesses") if r.get("is_sample")]) == 1


def test_two_racing_ensures_make_one_row(db, monkeypatch):
    """Both callers read 'no sample yet' at the same moment and both insert;
    the unique index lets one through and the other reads the winner."""
    gate = threading.Barrier(2, timeout=5)
    inner = db.get
    first_reads = {"n": 0}
    lock = threading.Lock()

    def racing_get(path):
        out = inner(path)
        if path.startswith(f"/businesses?sample_of=eq.{HOME}"):
            with lock:
                first_reads["n"] += 1
                hold = first_reads["n"] <= 2
            if hold:
                gate.wait()                 # both saw nothing before either inserts
        return out

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", racing_get)
    got = [None, None]

    def run(i):
        got[i] = sc.ensure(_home())

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    samples = [r for r in db.rows("businesses") if r.get("is_sample")]
    assert len(samples) == 1
    assert got[0] and got[1] and got[0]["id"] == got[1]["id"] == samples[0]["id"]


@pytest.mark.parametrize("home", [_home(type="coach"), _sample_row(), _home(owner_id=None),
                                  _home(id=None)])
def test_ensure_holds_what_makes_a_sample_a_sample(db, home):
    assert sc.ensure(home) is None
    assert db.rows("businesses") == []


def test_ensure_hands_a_pending_sample_to_the_seed(db, monkeypatch):
    seen = []
    monkeypatch.setattr(sc, "seed_hook", lambda sample, home: seen.append((sample["id"], home["id"])))
    made = sc.ensure(_home())
    assert seen == [(made["id"], HOME)]
    # A ready sample is not seeded again.
    made["settings"]["sample_church"]["status"] = "ready"
    sc.ensure(_home())
    assert len(seen) == 1


def test_a_failing_seed_never_fails_ensure(db, monkeypatch):
    def boom(sample, home):
        raise RuntimeError("seed broke")
    monkeypatch.setattr(sc, "seed_hook", boom)
    assert sc.ensure(_home())["is_sample"] is True


# ─── Access state ─────────────────────────────────────────────────────

def test_a_sample_row_is_sample_whatever_enforcement_says(monkeypatch):
    for enforce in ("on", "off"):
        monkeypatch.setenv("BILLING_ENFORCE", enforce)
        assert fg.access_state(_sample_row()) == {"state": "sample", "reason": "sample_church"}


def test_a_home_in_a_sample_is_sample(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    assert fg.access_state(_home(), church_sample=True) == {"state": "sample", "reason": "church_sample"}
    # Not told, it is what it is underneath: the same wall.
    assert fg.access_state(_home()) == {"state": "locked", "reason": "no_subscription"}


@pytest.mark.parametrize("over", [{"subscription_status": "active"},
                                  {"subscription_status": "trialing",
                                   "trial_ends_at": (NOW + timedelta(days=3)).isoformat()},
                                  {"comp_tier": "church_small"}])
def test_a_careless_true_never_lifts_a_live_church_into_sample(monkeypatch, over):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    assert fg.access_state(_home(**over), church_sample=True) == fg.access_state(_home(**over))
    assert fg.access_state(_home(**over), church_sample=True)["state"] != "sample"


def test_sample_counts_as_locked_everywhere():
    assert fg.LOCKED_STATES == ("locked", "sample")


# ─── The gates ────────────────────────────────────────────────────────

def _detail(e):
    return e.value.detail


@pytest.mark.parametrize("call", [
    lambda: billing_limits.require_live_access(SAMPLE),
    lambda: billing_limits.require_units(SAMPLE),
    lambda: billing_limits.require_card(SAMPLE, "texts"),
])
def test_a_sample_gets_a_409_not_a_402(db, monkeypatch, call):
    db.rows("businesses").append(_sample_row())
    for enforce in ("on", "off"):
        monkeypatch.setenv("BILLING_ENFORCE", enforce)
        sc._reset_for_tests()
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409
        assert _detail(e)["error"] == "sample_church"
        assert _detail(e)["message"] == ("This is a sample church, so nothing here is saved or "
                                          "sent. Start your church to do this for real.")


def test_require_card_names_what_was_refused(db):
    db.rows("businesses").append(_sample_row())
    with pytest.raises(HTTPException) as e:
        billing_limits.require_card(SAMPLE, "number")
    assert _detail(e)["what"] == "number"


def test_a_home_in_a_sample_is_locked_with_its_own_words(db):
    db.rows("businesses").append(_home())
    with pytest.raises(HTTPException) as e:
        billing_limits.require_live_access(HOME)
    assert e.value.status_code == 402
    assert _detail(e)["error"] == "subscription_locked"
    assert _detail(e)["reason"] == "church_sample"
    assert "start" in _detail(e)["message"].lower() and "trial" not in _detail(e)["message"].lower()


def test_a_home_out_of_units_is_told_to_start_its_church(db, monkeypatch):
    db.rows("businesses").append(_home())
    monkeypatch.setattr(billing_limits, "chief_can_send", lambda bid: False)
    with pytest.raises(HTTPException) as e:
        billing_limits.require_units(HOME)
    assert e.value.status_code == 402
    assert _detail(e)["message"] == billing_limits._locked_message("church_sample", None)


def test_everyone_else_keeps_their_402(db, monkeypatch):
    db.rows("businesses").append(_home(id="biz-x", type="coach", subscription_status="canceled"))
    with pytest.raises(HTTPException) as e:
        billing_limits.require_live_access("biz-x")
    assert e.value.status_code == 402
    assert _detail(e)["reason"] == "canceled"
    monkeypatch.setattr(billing_limits, "chief_can_send", lambda bid: False)
    with pytest.raises(HTTPException) as e:
        billing_limits.require_units("biz-x")
    assert e.value.status_code == 402 and _detail(e)["error"] == "out_of_units"


def test_a_paying_church_passes(db):
    db.rows("businesses").append(_home(subscription_status="active", stripe_subscription_id="sub_1",
                                       subscription_plan="price_x"))
    billing_limits.require_live_access(HOME)
    billing_limits.require_card(HOME, "texts")


def test_the_church_sample_words_are_in_the_voice():
    import brand_voice
    words = billing_limits._locked_message("church_sample", None).lower()
    for avoid in brand_voice.AVOID:
        assert str(avoid).lower() not in words, avoid


# ─── GET /billing/access ──────────────────────────────────────────────

@pytest.fixture
def access(db, monkeypatch):
    import church_billing
    import pricing_config
    import stripe_billing as sb

    async def load(bid):
        rows = [r for r in db.rows("businesses") if r["id"] == bid]
        if not rows:
            raise HTTPException(404, "Business not found")
        return dict(rows[0])

    starts = []
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(um, "trial_credits_exhausted", lambda bid, row=None: False)
    monkeypatch.setattr(nct, "start", lambda *a, **k: starts.append(a[0]["id"]) or None)
    monkeypatch.setattr(church_billing, "_founding_taken", lambda: 2)
    monkeypatch.setattr(pricing_config, "founding_church_moves", lambda: 5)
    return {"sb": sb, "starts": starts}


def _access(access, bid, user=PASTOR):
    return asyncio.run(access["sb"].billing_access(bid, user=user))


def test_a_home_gets_its_sample_block_and_its_sample_made(access, db):
    import church_site
    db.rows("businesses").append(_home())
    out = _access(access, HOME)
    assert out["state"] == "sample" and out["reason"] == "church_sample"
    block = out["sample"]
    made = [r for r in db.rows("businesses") if r.get("is_sample")]
    assert len(made) == 1                                  # made lazily, here
    assert block["business_id"] == made[0]["id"]
    assert block["home_business_id"] == HOME
    assert block["ready"] is False                         # BE-2 seeds it
    assert block["questions_left"] == 10 and block["questions_of"] == 10
    assert block["read_posts"] == []
    assert block["promise"] == church_site.PROMISE
    assert block["free_moves_left"] == 3                   # 5 moves, 2 taken
    assert access["starts"] == []                          # no trial started
    # Asked again, the same sample.
    assert _access(access, HOME)["sample"]["business_id"] == made[0]["id"]
    assert len([r for r in db.rows("businesses") if r.get("is_sample")]) == 1


def test_only_the_owners_own_load_makes_the_sample(access, db):
    """Any signed-in person may ask /billing/access; only the owner's load
    writes. Someone else sees the state, and no row is made."""
    db.rows("businesses").append(_home())
    other = AuthedUser(id="team-1", email="team@church.test", role="authenticated")
    out = _access(access, HOME, user=other)
    assert out["state"] == "sample"
    assert out["sample"]["business_id"] is None
    assert [r for r in db.rows("businesses") if r.get("is_sample")] == []
    assert _access(access, HOME)["sample"]["business_id"]          # the owner's load makes it
    assert _access(access, HOME, user=other)["sample"]["business_id"]


def test_questions_left_counts_the_persons_questions(access, db):
    db.rows("businesses").append(_home())
    for n in (1, 2, 3):
        db.rows("sample_church_questions").append({"id": f"q{n}", "user_id": OWNER, "n": n})
    db.rows("sample_church_questions").append({"id": "qx", "user_id": "someone-else", "n": 1})
    assert _access(access, HOME)["sample"]["questions_left"] == 7


def test_ten_asked_is_none_left(access, db):
    db.rows("businesses").append(_home())
    for n in range(1, 11):
        db.rows("sample_church_questions").append({"id": f"q{n}", "user_id": OWNER, "n": n})
    assert _access(access, HOME)["sample"]["questions_left"] == 0


def test_the_sample_itself_says_whose_it_is(access, db):
    db.rows("businesses").extend([_home(), _sample_row(settings={"sample_church": {"status": "ready"}})])
    out = _access(access, SAMPLE)
    assert out["state"] == "sample" and out["reason"] == "sample_church"
    assert out["sample"]["business_id"] == SAMPLE
    assert out["sample"]["home_business_id"] == HOME
    assert out["sample"]["ready"] is True
    assert access["starts"] == []


def test_a_business_sees_no_sample_block(access, db):
    db.rows("businesses").append(_home(id="biz-x", type="coach"))
    out = _access(access, "biz-x")
    assert "sample" not in out
    assert out["state"] == "locked"
    assert access["starts"] == ["biz-x"]                   # the trial's second door, as before


def test_an_unreadable_founding_count_is_none(access, db, monkeypatch):
    import church_billing
    monkeypatch.setattr(church_billing, "_founding_taken", lambda: None)
    db.rows("businesses").append(_home())
    assert _access(access, HOME)["sample"]["free_moves_left"] is None


def test_the_access_source_keeps_the_trial_door(access):
    import inspect
    src = inspect.getsource(access["sb"].billing_access)
    assert "no_card_trial.start" in src and "sample_church.applies" in src


def test_access_open_says_whether_every_church_gets_one(db, monkeypatch):
    import launch_access
    assert launch_access.access_open()["church_sample"] is True
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", TESTER)
    assert launch_access.access_open()["church_sample"] is False   # testers see the usual words
    monkeypatch.setenv("CHURCH_SAMPLE", "on")
    monkeypatch.setattr(sc, "_columns_ready", lambda: False)
    assert launch_access.access_open()["church_sample"] is False


# ─── Money and sends a sample can't reach ─────────────────────────────

@pytest.fixture
def stripe(db, monkeypatch):
    import stripe_billing as sb
    db.rows("businesses").extend([_home(stripe_customer_id="cus_1"), _sample_row()])
    posted = []

    async def load(bid):
        return dict(next(r for r in db.rows("businesses") if r["id"] == bid))

    async def post(path, data):
        posted.append(path)
        return {"id": "cs_1", "url": "https://checkout.stripe.test/x"}

    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_stripe_post", post)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setattr(fg, "price_to_plan", lambda: {"price_pro": "professional"})
    return {"sb": sb, "posted": posted}


def test_checkout_refuses_a_sample(stripe):
    sb = stripe["sb"]
    with pytest.raises(HTTPException) as e:
        asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id=SAMPLE, plan="professional"),
                                       user=PASTOR))
    assert e.value.status_code == 409 and _detail(e)["error"] == "sample_church"
    assert stripe["posted"] == []


def test_checkout_for_the_home_works_as_today(stripe):
    sb = stripe["sb"]
    out = asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id=HOME, plan="professional"),
                                         user=PASTOR))
    assert out["url"]
    assert "/checkout/sessions" in stripe["posted"]


def test_a_stranger_still_gets_403_before_the_sample_answer(stripe):
    sb = stripe["sb"]
    stranger = AuthedUser(id="stranger", email="x@y.test", role="authenticated")
    with pytest.raises(HTTPException) as e:
        asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id=SAMPLE, plan="professional"),
                                       user=stranger))
    assert e.value.status_code == 403


def test_credit_packs_refuse_a_sample(stripe):
    sb = stripe["sb"]
    import credit_ledger
    pack = sorted(credit_ledger.credit_packs())[0]
    with pytest.raises(HTTPException) as e:
        asyncio.run(sb.create_credit_checkout(sb.CreditCheckoutBody(business_id=SAMPLE, pack=pack),
                                              user=PASTOR))
    assert e.value.status_code == 409
    assert stripe["posted"] == []


def test_a_number_is_never_bought_for_a_sample(db):
    import sms_numbers_router
    db.rows("businesses").append(_sample_row())
    with pytest.raises(HTTPException) as e:
        asyncio.run(sms_numbers_router.provision_core(None, SAMPLE, area_code="512"))
    assert e.value.status_code == 409 and _detail(e)["what"] == "number"


@pytest.mark.parametrize("endpoint", ["stripe_connect_create_account", "stripe_connect_account_session"])
def test_payments_onboarding_refuses_a_sample(db, endpoint):
    import stripe_connect_router as scr
    db.rows("businesses").append(_sample_row())
    with pytest.raises(HTTPException) as e:
        asyncio.run(getattr(scr, endpoint)({"business_id": SAMPLE}, user=PASTOR))
    assert e.value.status_code == 409 and _detail(e)["what"] == "payments"


def test_payments_oauth_start_refuses_a_sample(db):
    import stripe_connect_router as scr
    db.rows("businesses").append(_sample_row())
    with pytest.raises(HTTPException) as e:
        scr.stripe_connect_start({"business_id": SAMPLE}, user=PASTOR)
    assert e.value.status_code == 409


def test_texting_registration_is_never_sent_for_a_sample(db):
    import texting_registration
    db.rows("businesses").append(_sample_row())
    sample_id = "00000000-0000-4000-8000-000000000001"
    db.rows("businesses")[-1]["id"] = sample_id
    with pytest.raises(HTTPException) as e:
        asyncio.run(texting_registration.send_registration(sample_id, biz={"id": sample_id}))
    assert e.value.status_code == 409


def test_a_sample_claims_no_domain(db, monkeypatch):
    import email_domains_router
    import site_composer
    db.rows("businesses").append(_sample_row())
    monkeypatch.setattr(email_domains_router, "_require_owner_biz", lambda bid, user: {"id": bid})
    with pytest.raises(HTTPException) as e:
        asyncio.run(email_domains_router.connect_domain(
            SAMPLE, email_domains_router.ConnectBody(domain="grace.test", from_local_part="hello"),
            user=PASTOR))
    assert e.value.status_code == 409 and _detail(e)["what"] == "domain"
    monkeypatch.setattr(site_composer, "_require_owner", lambda bid, uid: None)
    session = type("S", (), {"user": PASTOR})()
    with pytest.raises(HTTPException) as e:
        site_composer.connect_domain(site_composer.DomainConnectBody(business_id=SAMPLE,
                                                                     domain="grace.test"), session)
    assert e.value.status_code == 409


# ─── Ending a sample ──────────────────────────────────────────────────

@pytest.fixture
def deleted(monkeypatch):
    import account_lifecycle
    gone = []

    async def fake_delete(client, biz):
        gone.append(biz["id"])
        return {"businesses": 1}

    monkeypatch.setattr(account_lifecycle, "_delete_business", fake_delete)
    return gone


def test_end_marks_and_deletes_only_the_sample(db, deleted):
    db.rows("businesses").extend([_home(), _sample_row()])
    assert asyncio.run(sc.end(HOME, wait=True)) == SAMPLE
    assert deleted == [SAMPLE]
    sample = next(r for r in db.rows("businesses") if r["id"] == SAMPLE)
    assert sample["settings"]["sample_church"]["status"] == "ending"
    home = next(r for r in db.rows("businesses") if r["id"] == HOME)
    assert home == _home()                                  # never touched


def test_end_in_the_background_finishes(db, deleted):
    db.rows("businesses").extend([_home(), _sample_row()])

    async def go():
        sid = await sc.end(HOME)
        await asyncio.gather(*list(sc._TASKS))
        return sid
    assert asyncio.run(go()) == SAMPLE
    assert deleted == [SAMPLE]


def test_end_is_idempotent_and_a_home_without_one_is_a_no_op(db, deleted):
    db.rows("businesses").append(_home())
    assert asyncio.run(sc.end(HOME, wait=True)) is None
    assert asyncio.run(sc.end(None)) is None
    assert deleted == []


def test_end_never_deletes_a_row_that_stopped_being_a_sample(db, deleted, monkeypatch):
    db.rows("businesses").extend([_home(), _sample_row()])
    real_get = db.get

    def flipped(path):
        rows = real_get(path)
        if "is_sample=is.true&select=id,is_sample,sample_of" in path:
            return [dict(r, is_sample=False) for r in rows]
        return rows
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", flipped)
    asyncio.run(sc.end(HOME, wait=True))
    assert deleted == []


def test_end_refuses_a_row_that_is_not_this_homes_sample():
    assert sc._safe(_sample_row(), HOME) is True
    assert sc._safe(_sample_row(sample_of="other"), HOME) is False
    assert sc._safe(_sample_row(is_sample=False), HOME) is False
    assert sc._safe(_sample_row(id=HOME), HOME) is False


def test_a_failed_delete_never_raises(db, monkeypatch):
    import account_lifecycle

    async def boom(client, biz):
        raise HTTPException(502, "delete failed")
    monkeypatch.setattr(account_lifecycle, "_delete_business", boom)
    db.rows("businesses").extend([_home(), _sample_row()])
    assert asyncio.run(sc.end(HOME, wait=True)) == SAMPLE


# ─── The webhook ──────────────────────────────────────────────────────

@pytest.fixture
def webhook(monkeypatch):
    import first_run_arc
    import stripe_billing as sb
    seen = {"end": [], "begin": [], "ended": None}

    async def noop_patch(business_id, body, match=None):
        return None

    async def fake_end(home_id, wait=False):
        seen["end"].append(home_id)
        return seen["ended"]

    monkeypatch.setattr(sb, "_patch_business", noop_patch)
    monkeypatch.setattr(sc, "end", fake_end)
    monkeypatch.setattr(first_run_arc, "begin", lambda biz, **kw: seen["begin"].append((biz, kw)))
    seen["apply"] = lambda status: asyncio.run(sb._apply_subscription_state(
        "customer.subscription.updated",
        {"id": "sub_1", "status": status, "items": {"data": [{"price": {"id": "price_x"}}]}}, HOME))
    return seen


def test_a_paid_plan_ends_the_sample_and_opens_day_one(webhook):
    webhook["ended"] = SAMPLE
    webhook["apply"]("active")
    assert webhook["end"] == [HOME]
    assert len(webhook["begin"]) == 1
    biz, kw = webhook["begin"][0]
    assert biz == HOME and kw["source"] == "subscription"


def test_an_active_business_with_no_sample_opens_nothing(webhook):
    webhook["apply"]("active")
    assert webhook["end"] == [HOME]
    assert webhook["begin"] == []


def test_a_trial_ends_the_sample_and_opens_the_arc_once(webhook):
    webhook["ended"] = SAMPLE
    webhook["apply"]("trialing")
    assert webhook["end"] == [HOME]
    assert len(webhook["begin"]) == 1


@pytest.mark.parametrize("status", ["past_due", "canceled", "incomplete"])
def test_a_lapse_ends_nothing(webhook, status):
    webhook["apply"](status)
    assert webhook["end"] == [] and webhook["begin"] == []


def test_a_broken_end_never_fails_the_webhook(webhook, monkeypatch):
    async def boom(home_id, wait=False):
        raise RuntimeError("db down")
    monkeypatch.setattr(sc, "end", boom)
    webhook["apply"]("active")
    assert webhook["begin"] == []


def test_the_real_end_runs_inside_the_webhook(db, deleted, monkeypatch):
    import first_run_arc
    import stripe_billing as sb
    db.rows("businesses").extend([_home(), _sample_row()])
    opened = []

    async def noop_patch(business_id, body, match=None):
        return None
    monkeypatch.setattr(sb, "_patch_business", noop_patch)
    monkeypatch.setattr(first_run_arc, "begin", lambda biz, **kw: opened.append(biz))

    async def go():
        await sb._apply_subscription_state(
            "customer.subscription.created",
            {"id": "sub_1", "status": "active", "items": {"data": [{"price": {"id": "price_x"}}]}}, HOME)
        await asyncio.gather(*list(sc._TASKS))
    asyncio.run(go())
    assert deleted == [SAMPLE] and opened == [HOME]


# ─── Deleting a home ──────────────────────────────────────────────────

def test_deleting_a_home_deletes_its_sample_first(monkeypatch, deleted):
    import account_lifecycle as al
    owned = [_home(), _sample_row(), _home(id="other-church"),
             _sample_row(id="other-sample", sample_of="other-church")]

    async def mine(client, uid):
        return [dict(b) for b in owned]
    monkeypatch.setattr(al, "_owned_businesses", mine)
    monkeypatch.setattr(al.ledger_unlock, "require_unlock", lambda *a, **k: None)
    out = asyncio.run(al.delete_business(HOME, request=None, user=PASTOR))
    assert out["deleted_business"] == HOME
    assert deleted == [SAMPLE, HOME]                      # the sample, then the home; nothing else


def test_a_sample_that_wont_delete_never_stops_the_home(monkeypatch):
    import account_lifecycle as al
    gone = []

    async def flaky(client, biz):
        if biz["id"] == SAMPLE:
            raise HTTPException(502, "nope")
        gone.append(biz["id"])
        return {}

    async def mine(client, uid):
        return [_home(), _sample_row()]
    monkeypatch.setattr(al, "_delete_business", flaky)
    monkeypatch.setattr(al, "_owned_businesses", mine)
    monkeypatch.setattr(al.ledger_unlock, "require_unlock", lambda *a, **k: None)
    asyncio.run(al.delete_business(HOME, request=None, user=PASTOR))
    assert gone == [HOME]


def test_the_export_leaves_the_sample_out(monkeypatch):
    import account_lifecycle as al

    async def mine(client, uid):
        return [_home(), _sample_row()]

    async def nothing(client, table, bid):
        return [], True
    monkeypatch.setattr(al, "_owned_businesses", mine)
    monkeypatch.setattr(al, "_fetch_table", nothing)
    out = asyncio.run(al.export_account(user=PASTOR))
    assert [b["business"]["id"] for b in out["businesses"]] == [HOME]


def test_the_questions_go_with_the_person_and_not_in_the_export():
    import account_lifecycle as al
    assert "sample_church_questions" in al.USER_CHILD_TABLES
    assert len(al.EXPORT_EXCLUDED["sample_church_questions"]) > 15
    assert "sample_church_questions" not in al.BUSINESS_CHILD_TABLES


# ─── The migration ────────────────────────────────────────────────────

MIGRATION = ROOT / "supabase" / "APPLY-2026-11-15-sample-church.sql"


def _sql():
    """The file's statements, comments stripped."""
    return "\n".join(line.split("--", 1)[0] for line in MIGRATION.read_text(encoding="utf-8").splitlines())


def test_the_migration_is_present_and_in_the_ledger():
    assert MIGRATION.exists()
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(line for line in ledger.splitlines() if "APPLY-2026-11-15-sample-church.sql" in line)
    assert "NOT APPLIED" in row


def test_the_migration_is_one_safe_transaction():
    sql = _sql().lower()
    assert sql.strip().startswith("begin;") and sql.strip().endswith("commit;")
    assert "set local lock_timeout = '5s'" in sql
    assert "add column if not exists is_sample boolean not null default false" in sql
    assert re.search(r"add column if not exists sample_of uuid null references public\.businesses\(id\) "
                     r"on delete set null", sql)
    assert re.search(r"create unique index if not exists businesses_one_sample_per_home\s+"
                     r"on public\.businesses \(sample_of\) where sample_of is not null", sql)
    assert "create table if not exists public.sample_church_questions" in sql
    assert "unique (user_id, n)" in sql and "check (n between 1 and 50)" in sql


def test_the_guard_refuses_the_apps_logins_on_every_write():
    sql = _sql().lower()
    fn = sql[sql.index("create or replace function public.businesses_guard_sample()"):]
    fn = fn[:fn.index("end $$;")]
    assert "security definer" not in fn                    # current_user must be the caller
    assert "current_user not in ('anon', 'authenticated')" in fn
    assert "tg_op = 'insert'" in fn and "old.is_sample" in fn
    assert "new.sample_of is distinct from old.sample_of" in fn
    code = re.sub(r"'(?:[^']|'')*'", "''", fn).replace("distinct from", "")
    assert not re.search(r"\b(from|join)\b", code)        # reads no table: no 42P17 risk
    assert re.search(r"before insert or update or delete on public\.businesses\s+for each row", sql)


def test_the_questions_are_read_by_their_owner_and_written_by_the_server():
    sql = _sql().lower()
    assert "alter table public.sample_church_questions enable row level security" in sql
    assert "revoke all on public.sample_church_questions from anon, authenticated" in sql
    assert "grant select on public.sample_church_questions to authenticated" in sql
    assert re.search(r"for select to authenticated using \(user_id = \(select auth\.uid\(\)\)\)", sql)
    assert "using (true)" not in sql
    for verb in ("insert", "update", "delete"):
        assert f"for {verb}" not in sql


def test_the_rollback_is_written_and_commented_out():
    text = MIGRATION.read_text(encoding="utf-8")
    tail = text[text.index("-- Rollback"):]
    assert "drop trigger if exists businesses_guard_sample" in tail
    assert "drop column if exists sample_of, drop column if exists is_sample" in tail
    assert all(line.startswith("--") for line in tail.splitlines() if line.strip())
