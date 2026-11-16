"""No church gets the no-card trial (2026-11-16).

Kevin, the day the first real pastor signed up and was handed the business
trial (7 days on Professional, 500 credits): "make sure trial is only for
business side not church side", "top tier, no cut corners". Pinned here:

  1. no_card_trial.eligible() says "church" for any business whose kind is
     ministry, in every CHURCH_SAMPLE mode and whatever the trial's own
     switches say, so neither door (signup, /billing/access) starts one. A
     new church is locked / no_subscription: the app's plan screen. A church
     already on a trial keeps it. Businesses are unchanged.
  2. A church's FIRST subscription going live opens (or moves) its first-run
     arc once; a renewal, plan change or recovered payment never does.
  3. A church outside the sample gets a true welcome: plans first, the first
     month the day it chooses one, the founding line only while open, the
     promise. No free days, no trial.
  4. The tier mirror: the webhook writes the church plan key, and the
     migration lets businesses_tier_check / businesses_comp_tier_check hold
     every plan the server sells.
"""
from __future__ import annotations

import asyncio
import copy
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import brand_voice  # noqa: E402
import feature_gates as fg  # noqa: E402
import lifecycle_emails as le  # noqa: E402
import no_card_trial as nct  # noqa: E402
import sample_church as sc  # noqa: E402
import usage_metering as um  # noqa: E402

ROOT = _here.parent
BIZ = "c4a0c4a0-0000-4000-8000-00000000a016"
OWNER = "c4a0c4a0-0000-4000-8000-00000000b016"
PASTOR = "pastor@church.test"
NOW = datetime.now(timezone.utc)
FOUNDING_OPEN = {"spots": 10, "left": 9, "ends": "2027-01-31"}
FOUNDING_WORDS = ("The first ten churches keep the founding price for as long as they stay. "
                  "The offer ends January 31.")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _church(**over):
    """A church the moment onboarding created it."""
    row = {"id": BIZ, "owner_id": OWNER, "name": "First Church", "type": "church",
           "is_sample": False, "sample_of": None, "is_active": True,
           "settings": {"practitioner_name": "Pastor Sam Lee"},
           "subscription_status": None, "subscription_plan": None,
           "stripe_subscription_id": None, "trial_ends_at": None, "comp_tier": None,
           "created_at": _iso(NOW)}
    row.update(over)
    return row


def _business(**over):
    return _church(name="Northside Cuts", type="barber",
                   settings={"practitioner_name": "Kim Ortiz"}, **over)


def _church_on_trial(days_left=5, **over):
    """A church that signed up before 2026-11-16 and got the trial."""
    return _church(subscription_status="trialing",
                   trial_ends_at=_iso(NOW + timedelta(days=days_left)),
                   subscription_plan="price_pro", tier="professional",
                   settings={"practitioner_name": "Pastor Sam Lee",
                             nct.MARKER: {"started_at": _iso(NOW), "plan": "professional",
                                          "credits": 500, "source": "signup"}},
                   **over)


class _Db:
    """Records every read and PATCH; answers the owner-history read empty."""

    def __init__(self):
        self.reads = []
        self.patches = []

    def get(self, path, redact=False):
        self.reads.append(path)
        return []

    def patch(self, path, body):
        self.patches.append((path, body))
        return [{"id": BIZ, **body}]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "7")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    for k in ("PRICE_NO_CARD_TRIAL", "NO_CARD_TRIAL_PLAN", "PRICE_NO_CARD_FREE_WORKSPACE",
              "CHURCH_SAMPLE", "CHURCH_SAMPLE_TESTERS", "LIFECYCLE_EMAILS",
              "PLAN_CHURCH_FREE_WEEK", "CHURCH_FREE_WEEK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: uid == "gf")
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    monkeypatch.setattr(sc, "_owner_email", lambda owner: PASTOR)
    sc._reset_for_tests()


@pytest.fixture
def db(monkeypatch):
    fake = _Db()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    return fake


# ═══ 1. No trial for a church, ever ══════════════════════════════════

@pytest.mark.parametrize("mode,testers", [
    (None, None),                 # the switch unset: off
    ("off", None),
    ("test", None),               # the shipped default: test mode, nobody listed
    ("test", "someone.else@church.test"),
])
def test_a_church_outside_the_sample_is_refused_with_reason_church(db, monkeypatch, mode, testers):
    if mode:
        monkeypatch.setenv("CHURCH_SAMPLE", mode)
    if testers:
        monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", testers)
    assert nct.eligible(_church(), PASTOR) == "church"
    assert nct.start(_church(), "signup", PASTOR) is None
    assert db.patches == []


@pytest.mark.parametrize("mode", ["on", "test"])
def test_a_church_the_sample_takes_keeps_the_sample_reason_first(db, monkeypatch, mode):
    monkeypatch.setenv("CHURCH_SAMPLE", mode)
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", PASTOR)
    assert nct.eligible(_church(), PASTOR) == "church_sample"
    assert nct.eligible(_church(is_sample=True, sample_of="home"), PASTOR) == "sample"
    assert nct.start(_church(), "access", PASTOR) is None
    assert db.patches == []


@pytest.mark.parametrize("kind", ["church", "Church", "ministry", "faith-based", "synagogue",
                                  "mosque", "congregation"])
def test_every_kind_of_ministry_is_a_church(db, kind):
    assert nct.eligible(_church(type=kind), PASTOR) == "church"


@pytest.mark.parametrize("switch", [
    ("PRICE_NO_CARD_TRIAL", "0"),          # the trial switched off
    ("BILLING_ENFORCE", "off"),            # nothing locks
    ("BILLING_TRIAL_DAYS", "0"),
])
def test_the_answer_is_church_whatever_the_trials_own_switches_say(db, monkeypatch, switch):
    monkeypatch.setenv(*switch)
    assert nct.eligible(_church(), PASTOR) == "church"


def test_a_business_still_gets_the_trial(db):
    assert nct.eligible(_business(), "kim@cuts.test") is None
    out = nct.start(_business(), "signup", "kim@cuts.test")
    assert out and out["plan"] == "professional" and out["credits"] == 500
    (path, body), = db.patches
    assert body["subscription_status"] == "trialing" and body["tier"] == "professional"
    assert body["settings"][nct.MARKER]["source"] == "signup"


def test_a_row_without_its_type_is_read_once_and_an_unreadable_one_fails_closed(db, monkeypatch):
    import sb_clients
    row = _church()
    row.pop("type")
    reads = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, redact=False: reads.append(p) or [{"type": "church"}])
    assert nct.eligible(row, PASTOR) == "church"
    assert reads == [f"/businesses?id=eq.{BIZ}&select=type&limit=1"]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, redact=False: None)
    assert nct.eligible(row, PASTOR) == "type_unreadable"
    assert nct.start(row, "access", PASTOR) is None
    assert db.patches == []


def test_a_row_with_its_type_costs_no_read(db):
    nct.eligible(_church(), PASTOR)
    assert db.reads == []


def test_a_church_already_on_a_trial_keeps_it(db, monkeypatch):
    row = _church_on_trial()
    # never started again, never touched
    assert nct.eligible(row, PASTOR) == "church"
    assert nct.start(row, "access", PASTOR) is None
    assert db.patches == []
    # and it still reads as the trial it is
    assert nct.is_running(row)
    assert fg.access_state(row)["state"] == "full"
    assert nct.describe(row)["no_card_trial"] is True
    # when it ends unpaid, the reverse trial's free workspace still holds for it
    ended = _church_on_trial(days_left=-1)
    assert fg.access_state(ended) == {"state": "free", "reason": "trial_expired"}


def test_a_new_church_meets_its_plans_never_the_free_workspace():
    st = fg.access_state(_church())
    assert st == {"state": "locked", "reason": "no_subscription"}
    assert nct.describe(_church()) == {"no_card_trial": False}
    # the reverse trial only softens a no-card trial; a church never has one now
    assert fg._free_workspace({"state": "locked", "reason": "trial_expired"},
                              _church(subscription_status="canceled",
                                      trial_ends_at=_iso(NOW - timedelta(days=1)))
                              )["state"] == "locked"


def test_the_access_door_starts_no_trial_for_a_church(db, monkeypatch):
    import stripe_billing as sb
    from auth_supabase import AuthedUser
    row = _church()

    async def load(bid):
        return copy.deepcopy(row)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(um, "trial_credits_exhausted", lambda bid, b=None: False)
    out = asyncio.run(sb.billing_access(BIZ, AuthedUser(id=OWNER, email=PASTOR, role="authenticated")))
    assert out["state"] == "locked" and out["reason"] == "no_subscription"
    assert out["no_card_trial"] is False and out["plan"] is None
    assert db.patches == []


def test_the_access_door_still_starts_a_business_trial(db, monkeypatch):
    import stripe_billing as sb
    from auth_supabase import AuthedUser
    state = {"row": _business()}

    async def load(bid):
        return copy.deepcopy(state["row"])

    def patch(path, body):
        db.patches.append((path, body))
        state["row"].update(body)
        return [dict(state["row"])]
    import first_run_arc
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(first_run_arc, "begin", lambda biz, **kw: None)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(um, "trial_credits_exhausted", lambda bid, b=None: False)
    out = asyncio.run(sb.billing_access(BIZ, AuthedUser(id=OWNER, email="kim@cuts.test",
                                                        role="authenticated")))
    assert out["state"] == "full" and out["reason"] == "trialing"
    assert out["no_card_trial"] is True and len(db.patches) == 1


# ─── The signup door ─────────────────────────────────────────────────

class _Tasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


@pytest.fixture
def signup(monkeypatch):
    """create_business against a recording database; the real
    no_card_trial.start runs, first_run_arc.begin is recorded."""
    import billing_limits
    import first_run_arc
    import launch_access as la
    import sb_clients
    seen = {"patches": [], "arcs": []}
    monkeypatch.delenv("LAUNCH_INVITE_ONLY", raising=False)
    monkeypatch.setattr(la, "_attribution_from_funnel", lambda e: None)
    monkeypatch.setattr(billing_limits, "can_create_business", lambda uid: {"enforce": False})
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, **k: [{"id": BIZ, "is_sample": False, "subscription_status": None,
                                            "stripe_subscription_id": None, "trial_ends_at": None,
                                            "comp_tier": None, **b}])
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, redact=False: [])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: seen["patches"].append((p, b)) or [b])
    monkeypatch.setattr(first_run_arc, "begin", lambda biz, **kw: seen["arcs"].append((biz, kw)))

    def create(btype, name="First Church"):
        tasks = _Tasks()
        body = la.CreateBusinessBody(name=name, type=btype,
                                     settings={"practitioner_name": "Pastor Sam Lee"})
        out = la.create_business(body, AuthedUser(id=OWNER, email=PASTOR, role="authenticated"), tasks)
        return out, tasks
    from auth_supabase import AuthedUser
    seen["create"] = create
    return seen


def test_signing_up_a_church_starts_no_trial_but_still_opens_its_arc(signup):
    out, tasks = signup["create"]("church")
    assert out["ok"] is True and out["trial"] is None and "sample" not in out
    assert not [b for _, b in signup["patches"] if b.get("subscription_status") == "trialing"]
    # the signup door still opens the arc (a comped or grandfathered church
    # never reaches Stripe); the first paid subscription moves it later
    assert signup["arcs"] == [(BIZ, {"source": "signup"})]
    welcome = next(c for c in tasks.calls if c[0] is le.send_welcome)
    assert welcome[2] == {"church_sample": False}


# ═══ 2. The first week starts when a church pays ═════════════════════

def _sub(status, sub_id="sub_1", price="price_grow"):
    return {"id": sub_id, "status": status, "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": price}, "quantity": 1}]}}


@pytest.fixture
def hook(monkeypatch):
    """_apply_subscription_state against one row: the row before each event,
    every patch, every begin()."""
    import church_founding
    import first_run_arc
    import stripe_billing as sb
    world = {"row": _church(), "patches": [], "arcs": [], "refuse_tier": False,
             "real_begin": first_run_arc.begin}

    async def load(bid):
        return copy.deepcopy(world["row"])

    async def patch(bid, body, match=None):
        if world["refuse_tier"] and "tier" in body:
            raise HTTPException(400, "businesses_tier_check")
        world["patches"].append(dict(body))
        world["row"].update(body)

    async def no_claim(*a, **k):
        return None

    async def no_sample(*a, **k):
        return None
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setattr(church_founding, "claim", no_claim)
    monkeypatch.setattr(sc, "end", no_sample)
    monkeypatch.setattr(first_run_arc, "begin", lambda biz, **kw: world["arcs"].append((biz, kw)))

    def apply(sub, event="customer.subscription.updated"):
        asyncio.run(sb._apply_subscription_state(event, sub, BIZ))
    world["apply"] = apply
    return world


def test_a_churchs_first_paid_subscription_opens_its_first_week_once(hook):
    hook["apply"](_sub("active"))
    assert hook["arcs"] == [(BIZ, {"source": "subscription", "trial_ends_at": None})]
    # the renewal, the invoice.paid replay, a plan change: nothing more
    hook["apply"](_sub("active"))
    hook["apply"](_sub("active", price="price_other"))
    assert len(hook["arcs"]) == 1


def test_a_card_that_needed_a_second_step_opens_it_when_it_goes_through(hook):
    hook["apply"](_sub("incomplete"))
    assert hook["arcs"] == []
    hook["apply"](_sub("active"))
    assert len(hook["arcs"]) == 1


def test_a_church_that_had_the_trial_and_then_pays_asks_too_and_begin_stands_down(hook):
    # before 2026-11-16 a church got the trial (its arc opened then, from the
    # subscription door, so begin()'s latch keeps day one where it is)
    hook["row"] = _church_on_trial()
    hook["apply"](_sub("active"))
    assert len(hook["arcs"]) == 1


@pytest.mark.parametrize("before", [
    {"stripe_subscription_id": "sub_1", "subscription_status": "active"},      # a renewal
    {"stripe_subscription_id": "sub_1", "subscription_status": "past_due"},    # a payment recovered
    {"stripe_subscription_id": "sub_old", "subscription_status": "canceled"},  # a second subscription
    {"stripe_subscription_id": "sub_1", "subscription_status": "trialing"},    # the free week ending
])
def test_a_church_that_was_already_started_is_never_handed_a_first_week(hook, before):
    hook["row"] = _church(**before)
    hook["apply"](_sub("active"))
    assert hook["arcs"] == []


def test_a_business_paying_straight_away_is_unchanged(hook):
    hook["row"] = _business()
    hook["apply"](_sub("active", price="price_pro"))
    assert hook["arcs"] == []
    hook["apply"](_sub("trialing", sub_id="sub_2", price="price_pro"))   # a trial still opens it
    assert len(hook["arcs"]) == 1


def test_an_unreadable_row_never_costs_the_webhook(hook, monkeypatch):
    import stripe_billing as sb

    async def broken(bid):
        raise HTTPException(500, "down")
    monkeypatch.setattr(sb, "_load_business", broken)
    hook["apply"](_sub("active"))
    assert hook["arcs"] == [] and hook["patches"][0]["subscription_status"] == "active"


def test_with_the_real_arc_day_one_moves_to_the_day_the_church_paid_once(hook, monkeypatch):
    import first_run_arc as fra
    arc = {"business_id": BIZ, "source": "signup", "started_at": _iso(NOW - timedelta(days=9)),
           "trial_ends_at": None, "intro_delivered_at": None, "status": "pending_intro"}
    rows = [arc]
    moved = []

    def get(path, redact=False):
        return [dict(r) for r in rows if path.startswith("/first_run_arc")]

    def patch(path, body):
        moved.append(body)
        arc.update(body)
        return [dict(arc)]
    monkeypatch.setattr(fra, "begin", hook["real_begin"])     # the real door, not the recorder
    monkeypatch.setattr(fra.sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(fra.sb_clients, "sb_patch_as_service", patch)
    hook["apply"](_sub("active"))
    assert arc["source"] == "subscription" and fra.day_of(arc) == 1
    hook["apply"](_sub("active"))           # a renewal: never moved again
    assert len(moved) == 1


# ═══ 3. A church's welcome, true without a trial ═════════════════════

class _Mail:
    def __init__(self):
        self.sent = []

    async def send(self, **kw):
        self.sent.append(kw)
        return {"id": f"m{len(self.sent)}"}


@pytest.fixture
def mail(monkeypatch):
    from lifecycle_delivery_fake import install_delivery_fake
    install_delivery_fake(monkeypatch)
    m = _Mail()
    import church_founding
    import email_sender
    import sb_clients
    monkeypatch.setattr(email_sender, "send_via_resend", m.send)
    monkeypatch.setattr(church_founding, "public_state", lambda: None)
    rows = {"row": None}

    def get(path, redact=False):
        if "owner_id=eq." in path:
            return [{"id": rows["row"]["id"]}]
        return [{"id": rows["row"]["id"], "settings": dict(rows["row"].get("settings") or {})}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [b])
    m.rows = rows
    return m


_NOT_TRUE_FOR_A_CHURCH = re.compile(
    r"\b(business(es)?|clients?|customers?|trial|free|days free)\b", re.I)


def _voice_ok(text: str) -> None:
    assert "!" not in text
    hit = _NOT_TRUE_FOR_A_CHURCH.search(text)
    assert not hit, hit.group(0) if hit else ""
    assert brand_voice.offenses(f"<p>{text}</p>") == []


def _send(mail, row, name="Pastor Sam Lee", **kw):
    mail.rows["row"] = row
    return asyncio.run(le.send_welcome(row, PASTOR, name, **kw))


def test_a_church_outside_the_sample_gets_a_welcome_with_no_trial_in_it(mail, monkeypatch):
    import church_founding
    monkeypatch.setattr(church_founding, "public_state", lambda: dict(FOUNDING_OPEN))
    out = _send(mail, _church(), church_sample=False)
    assert out == {"sent": True, "kind": "church"}
    m, = mail.sent
    assert m["subject"] == "Welcome. First Church starts the day you choose its plan"
    body = m["body"]
    assert body.startswith("Hi Pastor Sam,\n\n")
    for line in ("The next step is choosing a plan for First Church.",
                 "The plans go by how many people come on a Sunday",
                 "Your first month starts the day you choose your plan.",
                 "From then, Chief is ready to welcome First Church, and the Move-in list walks "
                 "you through bringing in your people, your Sundays and your giving",
                 FOUNDING_WORDS,
                 "No contract. Leave any time, and your records go with you.",
                 "A person reads it.",
                 le.app_base_url()):
        assert line in body, line
    _voice_ok(m["subject"] + "\n" + body)
    # the order a church reads it in: what to do, when it starts, the deal, the promise
    assert (body.index("choosing a plan") < body.index("Your first month")
            < body.index(FOUNDING_WORDS) < body.index("No contract"))


@pytest.mark.parametrize("state", [None, {"spots": 10, "left": 0, "ends": "2027-01-31"}])
def test_the_founding_line_only_while_a_place_is_open(mail, monkeypatch, state):
    import church_founding
    monkeypatch.setattr(church_founding, "public_state", lambda: dict(state) if state else None)
    _send(mail, _church(), church_sample=False)
    assert "founding" not in mail.sent[0]["body"].lower()
    _voice_ok(mail.sent[0]["body"])


def test_the_retry_works_it_out_itself(mail):
    out = _send(mail, _church())                 # church_sample None, as welcome_retry_tick sends
    assert out["kind"] == "church" and "choose its plan" in mail.sent[0]["subject"]


@pytest.mark.parametrize("row,owner", [
    (_church(comp_tier="church_growing"), OWNER),                     # comped by Kevin
    (_church(owner_id="gf"), "gf"),                                    # a grandfathered owner
    (_church(subscription_status="active", subscription_plan="price_grow",
             stripe_subscription_id="sub_1"), OWNER),                   # paid before a retry sent
])
def test_a_church_that_already_has_its_way_in_is_not_told_to_choose_a_plan(mail, row, owner):
    out = _send(mail, row)
    assert out["kind"] == "church"
    m = mail.sent[0]
    assert m["subject"] == "Welcome. First Church is ready"
    assert "choose" not in m["body"].lower() and "first month" not in m["body"].lower()
    assert "First Church is set up. Chief is ready to welcome you, and the Move-in list" in m["body"]
    _voice_ok(m["subject"] + "\n" + m["body"])


def test_with_the_free_week_back_it_says_when_the_free_days_are(mail, monkeypatch):
    monkeypatch.setenv("PLAN_CHURCH_FREE_WEEK", "1")
    _send(mail, _church(), church_sample=False)
    assert ("The first 7 days are free once you choose your plan, and your first month "
            "starts after them.") in mail.sent[0]["body"]


def test_the_sample_welcome_and_the_business_welcome_are_unchanged(mail):
    out = _send(mail, _church(), church_sample=True)
    assert out["kind"] == "sample_church"
    assert mail.sent[0]["subject"].startswith("Welcome. Look around a sample church")
    mail.sent.clear()
    out = _send(mail, _business(id="b-cuts"), "Kim Ortiz", church_sample=False)
    assert out == {"sent": True}
    assert mail.sent[0]["subject"] == "Northside Cuts is set up. Three moves for your first week"
    assert "Your first 7 days on any plan are free." in mail.sent[0]["body"]


# ═══ 4. The tier mirror ══════════════════════════════════════════════

def test_the_webhook_mirrors_the_church_plan_key(hook):
    hook["apply"](_sub("active"))
    assert hook["patches"][0]["tier"] == "church_growing"
    assert hook["row"]["tier"] == "church_growing"


def test_a_refused_mirror_still_saves_the_billing_and_says_so(hook, capsys):
    hook["refuse_tier"] = True
    hook["apply"](_sub("active"))
    saved = hook["patches"][0]
    assert "tier" not in saved and saved["subscription_status"] == "active"
    assert saved["subscription_plan"] == "price_grow"
    assert "[billing] tier mirror refused" in capsys.readouterr().out


MIGRATION = ROOT / "supabase" / "APPLY-2026-11-16-tier-all-plans.sql"
LEGACY_TIERS = {"pro", "enterprise", "founder", "free"}


def _code(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _check_list(sql: str, constraint: str) -> set:
    m = re.search(rf"ADD CONSTRAINT {constraint}\s+CHECK\s*\((.*?)\);", _code(sql), re.S | re.I)
    assert m, constraint
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def test_the_migration_lets_the_columns_hold_every_plan_the_server_sells():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert _check_list(sql, "businesses_tier_check") == set(fg.ALL_PLANS) | LEGACY_TIERS
    assert _check_list(sql, "businesses_comp_tier_check") == set(fg.ALL_PLANS)
    for plan in fg.CHURCH_PLANS:
        assert f"'{plan}'" in sql


def test_the_newest_tier_check_always_covers_every_plan():
    """The day a new plan is sold, this fails until a migration lists it:
    a refused mirror is silent (the webhook drops `tier` and moves on)."""
    newest = {}
    for f in sorted((ROOT / "supabase").glob("APPLY-*.sql")):
        sql = f.read_text(encoding="utf-8", errors="ignore")
        for name in ("businesses_tier_check", "businesses_comp_tier_check"):
            if f"add constraint {name}" in _code(sql).lower():
                newest[name] = _check_list(sql, name)
    assert set(fg.ALL_PLANS) <= newest["businesses_tier_check"]
    assert set(fg.ALL_PLANS) <= newest["businesses_comp_tier_check"]


def test_the_re_mirror_is_guarded_and_separate_from_the_checks():
    sql = MIGRATION.read_text(encoding="utf-8")
    body = _code(sql)
    assert body.count("BEGIN;") == 2 and body.count("COMMIT;") == 2
    checks, remirror = body.split("COMMIT;", 1)
    assert "UPDATE" not in checks.upper()
    assert "IF n > 10 THEN" in remirror and "RAISE EXCEPTION" in remirror
    # only rows whose live price is the one their founding place was claimed on
    assert "b.subscription_plan = b.settings->'founding_church'->>'price_id'" in remirror
    assert "b.tier IS DISTINCT FROM b.settings->'founding_church'->>'plan'" in remirror
    assert "subscription_status IN ('active', 'trialing')" in remirror
    import church_founding
    assert church_founding.FOUNDING == "founding_church"


def test_the_ledger_lists_it_not_applied():
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    line = next(ln for ln in ledger.splitlines() if "APPLY-2026-11-16-tier-all-plans.sql" in ln)
    assert "**NOT APPLIED**" in line


def test_a_comp_the_database_refuses_is_not_reported_as_saved(monkeypatch):
    import launch_access as la
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: None)
    with pytest.raises(HTTPException) as e:
        la.set_comp_tier(BIZ, la.TierBody(comp_tier="church_growing"), _owner=None)
    assert e.value.status_code == 502
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [])
    with pytest.raises(HTTPException) as e:
        la.set_comp_tier(BIZ, la.TierBody(comp_tier="church_growing"), _owner=None)
    assert e.value.status_code == 404
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [{"id": BIZ, **b}])
    out = la.set_comp_tier(BIZ, la.TierBody(comp_tier="church_growing"), _owner=None)
    assert out == {"ok": True, "business_id": BIZ, "comp_tier": "church_growing"}
