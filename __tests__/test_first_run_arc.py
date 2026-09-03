"""The day-one arc opens once, from either door, and day one only moves
while nothing has been said yet.

Two facts about the real signup order drive every test here:

  · Business creation runs during onboarding; checkout runs LATER, from
    the paywall, once the practitioner is already in the workspace. So
    the signup door almost always fires first.
  · Comped, invited and grandfathered accounts never reach Stripe, so no
    `trialing` webhook ever fires for them at all.

Together those mean the arc cannot simply be "opened by the Stripe
webhook", and it cannot simply be "first door wins" either — the person
who signs up in March and subscribes in April would be told it is day 22
of their first week.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import first_run_arc as fra  # noqa: E402


BIZ = "11111111-1111-1111-1111-111111111111"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class FakeDB:
    """A one-table stand-in for PostgREST that enforces the one thing the
    real schema enforces: a unique index on business_id."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.patches = []
        self.refuse_insert = False
        self.refuse_patch = False

    # ── the three sb_clients entry points this module uses ──
    def get(self, path):
        if not path.startswith("/first_run_arc"):
            raise AssertionError(f"unexpected read: {path}")
        biz = path.split("business_id=eq.")[1].split("&")[0]
        return [r for r in self.rows if r["business_id"] == biz]

    def post(self, path, body, prefer="return=representation"):
        if self.refuse_insert:
            return None
        if any(r["business_id"] == body["business_id"] for r in self.rows):
            return None          # unique index violation -> sb_* returns None
        row = {
            "id": "arc-1", "status": "pending_intro", "intro_delivered_at": None,
            "completed_steps": [], "shared_links": [],
            "last_beat_day": 0, "last_beat_at": None, "trial_ends_at": None,
            **body,
        }
        self.rows.append(row)
        return [row]

    def patch(self, path, body):
        self.patches.append((path, body))
        if self.refuse_patch:
            return None
        biz = path.split("business_id=eq.")[1].split("&")[0]
        for r in self.rows:
            if r["business_id"] == biz:
                r.update(body)
        return []


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(fra.sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(fra.sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(fra.sb_clients, "sb_patch_as_service", fake.patch)
    return fake


# ─── Opening the arc ─────────────────────────────────────────────────

def test_either_door_opens_the_arc(db):
    assert fra.begin(BIZ, source="signup") is not None
    assert len(db.rows) == 1
    assert db.rows[0]["source"] == "signup"


def test_the_subscription_door_records_the_trial_end(db):
    ends = _iso(datetime.now(timezone.utc) + timedelta(days=7))
    row = fra.begin(BIZ, source="subscription", trial_ends_at=ends)
    assert row["trial_ends_at"] == ends
    assert row["source"] == "subscription"


def test_a_second_call_never_opens_a_second_arc(db):
    fra.begin(BIZ, source="signup")
    fra.begin(BIZ, source="signup")
    fra.begin(BIZ, source="subscription")
    assert len(db.rows) == 1


def test_a_lost_race_is_success_not_failure(db, monkeypatch):
    """Both doors fire in the same second. The insert loses to the unique
    index and comes back None — but an arc exists, which is the outcome
    begin() was asked for."""
    db.rows.append({"business_id": BIZ, "source": "signup",
                    "started_at": _iso(datetime.now(timezone.utc)),
                    "trial_ends_at": None, "intro_delivered_at": None})
    row = fra.begin(BIZ, source="signup")
    assert row is not None
    assert len(db.rows) == 1


def test_an_unknown_source_is_refused_not_stored(db):
    assert fra.begin(BIZ, source="webhook") is None
    assert db.rows == []


# ─── When day one is allowed to move ─────────────────────────────────

def test_subscribing_later_moves_day_one_to_the_trial(db):
    """Signed up in March, subscribed in April. Their first week starts
    when the trial does — not when the account was made."""
    march = datetime.now(timezone.utc) - timedelta(days=21)
    db.rows.append({"business_id": BIZ, "source": "signup",
                    "started_at": _iso(march), "trial_ends_at": None,
                    "intro_delivered_at": None})

    ends = _iso(datetime.now(timezone.utc) + timedelta(days=7))
    row = fra.begin(BIZ, source="subscription", trial_ends_at=ends)

    assert fra.day_of(row) == 1, "the trial just started; this is day one"
    assert row["trial_ends_at"] == ends
    assert row["source"] == "subscription"


def test_a_repeat_trialing_webhook_does_not_move_day_one_again(db):
    """Stripe sends `updated` with status `trialing` for ANY change during
    a trial. Without the source latch, a plan tweak on day three would
    quietly put them back on day one — the introduction hasn't landed
    yet, so the outer freeze wouldn't catch it."""
    started = datetime.now(timezone.utc) - timedelta(days=3)
    db.rows.append({"business_id": BIZ, "source": "signup",
                    "started_at": _iso(started), "trial_ends_at": None,
                    "intro_delivered_at": None})

    first = fra.begin(BIZ, source="subscription")
    assert fra.day_of(first) == 1          # the real trial just started

    second = fra.begin(BIZ, source="subscription")
    assert second["started_at"] == first["started_at"]
    assert fra.day_of(second) == 1         # still day one, not re-stamped
    assert len(db.patches) == 1, "the second webhook should write nothing"


def test_day_one_freezes_once_chief_has_introduced_herself(db):
    """A re-subscribe, a plan change or a replayed webhook must never
    restart someone's week or replay an introduction they already had."""
    started = datetime.now(timezone.utc) - timedelta(days=4)
    db.rows.append({"business_id": BIZ, "source": "subscription",
                    "started_at": _iso(started),
                    "trial_ends_at": _iso(started + timedelta(days=7)),
                    "intro_delivered_at": _iso(started)})

    row = fra.begin(BIZ, source="subscription",
                    trial_ends_at=_iso(datetime.now(timezone.utc)
                                       + timedelta(days=30)))

    assert row["started_at"] == _iso(started)
    assert fra.day_of(row) == 5
    assert db.patches == [], "nothing should have been written"


def test_the_signup_door_never_moves_an_existing_arc(db):
    started = datetime.now(timezone.utc) - timedelta(days=2)
    db.rows.append({"business_id": BIZ, "source": "subscription",
                    "started_at": _iso(started), "trial_ends_at": None,
                    "intro_delivered_at": None})
    row = fra.begin(BIZ, source="signup")
    assert row["started_at"] == _iso(started)
    assert db.patches == []


def test_a_known_trial_end_is_not_overwritten(db):
    """Only a HOLE gets filled. An end date already on the row is the
    one the practitioner was told about."""
    first = _iso(datetime.now(timezone.utc) + timedelta(days=7))
    db.rows.append({"business_id": BIZ, "source": "subscription",
                    "started_at": _iso(datetime.now(timezone.utc)),
                    "trial_ends_at": first, "intro_delivered_at": None})
    row = fra.begin(BIZ, source="subscription",
                    trial_ends_at=_iso(datetime.now(timezone.utc)
                                       + timedelta(days=99)))
    assert row["trial_ends_at"] == first


# ─── Counting the days ───────────────────────────────────────────────

def test_the_day_it_opens_is_day_one(db):
    row = fra.begin(BIZ, source="subscription")
    assert fra.day_of(row) == 1


def test_the_count_is_uncapped_past_the_end_of_the_beats():
    """Day 12 of a 7-day trial is a real thing that happens, and the
    caller — not this function — decides how to say it."""
    started = datetime.now(timezone.utc) - timedelta(days=11)
    assert fra.day_of({"started_at": _iso(started)}) == 12


def test_an_unreadable_start_says_it_does_not_know():
    assert fra.day_of(None) == 0
    assert fra.day_of({}) == 0
    assert fra.day_of({"started_at": "not a date"}) == 0


# ─── Nothing here raises ─────────────────────────────────────────────

def test_a_refused_insert_returns_none_rather_than_raising(db):
    db.refuse_insert = True
    assert fra.begin(BIZ, source="signup") is None


def test_a_refused_alignment_keeps_the_arc_usable(db):
    """The patch fails; the caller still gets the row it already had,
    because a webhook must not die over a side table."""
    started = datetime.now(timezone.utc) - timedelta(days=9)
    db.rows.append({"business_id": BIZ, "source": "signup",
                    "started_at": _iso(started), "trial_ends_at": None,
                    "intro_delivered_at": None})
    db.refuse_patch = True
    row = fra.begin(BIZ, source="subscription", trial_ends_at="whenever")
    assert row is not None
    assert row["started_at"] == _iso(started)


def test_a_dead_database_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("supabase is down")
    monkeypatch.setattr(fra.sb_clients, "sb_get_as_service", boom)
    monkeypatch.setattr(fra.sb_clients, "sb_post_as_service", boom)
    assert fra.state(BIZ) is None
    assert fra.begin(BIZ, source="signup") is None


def test_a_missing_business_id_is_a_no_op(db):
    assert fra.begin(None, source="signup") is None
    assert fra.begin("", source="signup") is None
    assert fra.state(None) is None
    assert db.rows == []


# ─── Door one: the Stripe webhook ────────────────────────────────────

@pytest.fixture
def opened(monkeypatch):
    """Records every begin() the entry points make."""
    calls = []
    monkeypatch.setattr(fra, "begin",
                        lambda biz, **kw: calls.append((biz, kw)) or {"ok": True})
    return calls


def _subscription(status, trial_end=None):
    return {"id": "sub_1", "status": status,
            "items": {"data": [{"price": {"id": "price_pro"}}]},
            **({"trial_end": trial_end} if trial_end else {})}


def _apply(event_type, sub, monkeypatch):
    import asyncio
    import stripe_billing as sb
    monkeypatch.setattr(sb, "_patch_business", _noop_patch)
    return asyncio.run(sb._apply_subscription_state(event_type, sub, BIZ))


async def _noop_patch(business_id, body):
    return None


def test_a_trialing_subscription_opens_the_arc(opened, monkeypatch):
    trial_end = int((datetime.now(timezone.utc)
                     + timedelta(days=7)).timestamp())
    _apply("customer.subscription.created",
           _subscription("trialing", trial_end), monkeypatch)
    assert len(opened) == 1
    biz, kw = opened[0]
    assert biz == BIZ
    assert kw["source"] == "subscription"
    assert kw["trial_ends_at"] is not None


def test_an_out_of_order_update_still_opens_the_arc(opened, monkeypatch):
    """Stripe can deliver `updated` before `created`. The gate is the
    STATUS, not the event name — begin() dedupes the loser."""
    _apply("customer.subscription.updated",
           _subscription("trialing"), monkeypatch)
    assert len(opened) == 1


def test_an_active_or_cancelled_subscription_opens_nothing(opened, monkeypatch):
    _apply("customer.subscription.updated", _subscription("active"), monkeypatch)
    _apply("customer.subscription.deleted", _subscription("active"), monkeypatch)
    _apply("customer.subscription.updated", _subscription("past_due"), monkeypatch)
    assert opened == []


def test_the_webhook_survives_a_broken_arc(monkeypatch):
    """The billing patch is what this webhook exists for. A day-one arc
    that throws must not cost us the event."""
    def boom(*a, **k):
        raise RuntimeError("arc table missing")
    monkeypatch.setattr(fra, "begin", boom)
    _apply("customer.subscription.created",
           _subscription("trialing"), monkeypatch)   # must not raise


# ─── Door two: business creation ─────────────────────────────────────

def test_creating_a_business_opens_the_arc(opened, monkeypatch):
    """The only door comped, invited and grandfathered accounts have."""
    import launch_access as la
    monkeypatch.setattr(la.usage_metering, "is_grandfathered_user", lambda u: True)
    monkeypatch.setattr(la, "_attribution_from_funnel", lambda e: None)
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service",
                        lambda p, b, **k: [{"id": BIZ, **b}])

    la.create_business(la.CreateBusinessBody(name="Shear Genius", type="barber"),
                       type("U", (), {"id": "u1", "email": None})())

    assert opened == [(BIZ, {"source": "signup"})]


def test_a_broken_arc_never_blocks_a_signup(monkeypatch):
    import launch_access as la
    monkeypatch.setattr(la.usage_metering, "is_grandfathered_user", lambda u: True)
    monkeypatch.setattr(la, "_attribution_from_funnel", lambda e: None)
    monkeypatch.setattr(la.sb_clients, "sb_post_as_service",
                        lambda p, b, **k: [{"id": BIZ, **b}])

    def boom(*a, **k):
        raise RuntimeError("arc table missing")
    monkeypatch.setattr(fra, "begin", boom)

    out = la.create_business(
        la.CreateBusinessBody(name="Shear Genius", type="barber"),
        type("U", (), {"id": "u1", "email": None})())
    assert out["ok"] is True
