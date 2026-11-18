"""The sample church, BE-5: the polish before the run-through (2026-11-15).

Kevin, 2026-11-14: "top tier, no cut corners". Pinned here:
  1. A sample's rooms and reports open as the Growing church plan's
     (feature_gates.opens_feature): the Funds, Givers and Giver history
     reports answer 200, the app's entitlements say allowed. It still has
     no plan, no allowance, no sends, no AI outside its own Chief, and it
     never counts as paying.
  2. A church that signs up into a sample gets the sample's welcome.
  3. One note on day 3 to a church still looking around, exactly once.
  4. A comp on ANY plan is full access (it was the public ladder only).
  5. The church pages say "Look around a sample church first" only while
     CHURCH_SAMPLE is on for everyone.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits  # noqa: E402
import brand_voice  # noqa: E402
import feature_gates as fg  # noqa: E402
import lifecycle_emails as le  # noqa: E402
import sample_church as sc  # noqa: E402
import usage_metering as um  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

ROOT = _here.parent
SAMPLE = "5a3b1e00-0000-4000-8000-00000000a005"
HOME = "5a3b1e00-0000-4000-8000-00000000b005"
PLAIN = "5a3b1e00-0000-4000-8000-00000000c005"
OWNER = "5a3b1e00-0000-4000-8000-00000000d005"
TESTER = "pastor@church.test"
OWNER_EMAILS = {OWNER: TESTER}
FOUNDING_OPEN = {"spots": 10, "left": 7, "ends": "2027-01-31"}
FOUNDING_WORDS = ("The first ten churches keep the founding price for as long as they stay. "
                  "The offer ends January 31.")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Reads(FakeSB):
    def __init__(self):
        super().__init__()
        self.reads = []

    def get(self, path):
        self.reads.append(path)
        return super().get(path)


@pytest.fixture
def world(monkeypatch):
    fb = _Reads()
    import church_founding
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, redact=False: fb.get(p))
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="return=representation": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: (fb.patch(p, b), [b])[1])
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("CHURCH_SAMPLE", "on")
    monkeypatch.delenv("CHURCH_SAMPLE_TESTERS", raising=False)
    monkeypatch.delenv("LIFECYCLE_EMAILS", raising=False)
    monkeypatch.delenv("SAMPLE_CHIEF_QUESTIONS", raising=False)
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: uid == "gf")
    monkeypatch.setattr(sc, "_owner_email", lambda owner: OWNER_EMAILS.get(owner))
    monkeypatch.setattr(church_founding, "public_state", lambda: None)
    sc._reset_for_tests()
    return fb


def _sample(**over):
    row = {"id": SAMPLE, "owner_id": OWNER, "name": sc.NAME, "type": "church",
           "is_sample": True, "sample_of": HOME, "is_active": False,
           "subscription_status": None, "subscription_plan": None, "comp_tier": None,
           "stripe_subscription_id": None, "trial_ends_at": None, "current_period_end": None,
           "created_at": _iso(_now() - timedelta(days=3, hours=2)),
           "settings": {sc.SETTINGS_KEY: {"status": "ready", "seeded_at": _iso(_now() - timedelta(days=3)),
                                          "created_at": _iso(_now() - timedelta(days=3))}}}
    row.update(over)
    return row


def _home(**over):
    row = {"id": HOME, "owner_id": OWNER, "name": "First Church", "type": "church",
           "is_sample": False, "sample_of": None, "is_active": True,
           "subscription_status": None, "subscription_plan": None, "comp_tier": None,
           "stripe_subscription_id": None, "trial_ends_at": None, "current_period_end": None,
           "created_at": _iso(_now() - timedelta(days=3, hours=2)),
           "settings": {"practitioner_name": "Pastor Sam Lee"}}
    row.update(over)
    return row


def _plain(**over):
    """A real church with no plan in good standing: the wall, as before."""
    return _home(id=PLAIN, owner_id="someone-else", name="Plain Church", **over)


# ═══ 1. The sample's rooms open as Growing's; nothing else changes ═══

GROWING = fg.plan_features(fg.SAMPLE_TOUR_PLAN)


def test_the_tour_plan_is_growing_and_has_the_church_reports():
    assert fg.SAMPLE_TOUR_PLAN == "church_growing"
    assert {"vertical_reports", "reports_full", "period_close", "general_ledger"} <= GROWING
    # what Growing doesn't carry stays shut in the sample too
    assert not {"audit_trail", "accountant_collaborator", "marketing_autopilot"} & GROWING


def test_a_sample_opens_every_growing_feature_and_no_more(world):
    row = _sample()
    for f in fg.FEATURE_MIN_PLAN:
        assert fg.opens_feature(row, f) is (f in GROWING), f
    # the plain church with no plan: the same wall as before
    for f in fg.FEATURE_MIN_PLAN:
        assert fg.opens_feature(_plain(), f) is False, f


def test_a_row_without_its_column_is_known_by_its_id(world):
    world.rows("businesses").append(_sample())
    narrow = {"id": SAMPLE, "subscription_status": None, "subscription_plan": None, "comp_tier": None}
    assert fg.opens_feature(narrow, "vertical_reports") is True
    world.rows("businesses").append(_plain())
    assert fg.opens_feature({"id": PLAIN, "subscription_status": None}, "vertical_reports") is False


def test_enforcement_off_is_unchanged(world, monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    assert fg.opens_feature(_plain(), "audit_trail") is True     # dormant: everything opens, as before
    assert "sample_features_of" not in fg.entitlements(_sample())


def test_the_sample_still_has_no_plan_and_has_feature_still_says_no(world):
    row = _sample()
    assert fg.plan_of(row) is None
    assert fg.monthly_credits(row) is None
    # has_feature's own callers (the website concierge, the outside-agent
    # connector, connected AI) keep refusing a sample
    for f in ("site_concierge", "agent_connector", "agent_connector_write", "vertical_reports"):
        assert fg.has_feature(row, f) is False, f
    # money spent unasked (the marketing suite's drafts and flyers) stays shut
    for f in ("marketing_suggestion", "marketing_week", "ai_clips"):
        assert fg.plan_includes(row, f) is False, f


def test_entitlements_open_the_rooms_but_say_no_plan(world):
    ent = fg.entitlements(_sample())
    assert ent["plan"] is None
    assert ent["sample_features_of"] == "church_growing"
    feats = ent["features"]
    assert feats["vertical_reports"] == {**feats["vertical_reports"], "allowed": True, "included_in_plan": False}
    assert feats["audit_trail"]["allowed"] is False
    assert all(v["included_in_plan"] is False for v in feats.values())
    plain = fg.entitlements(_plain())
    assert "sample_features_of" not in plain
    assert plain["features"]["vertical_reports"]["allowed"] is False


def test_require_feature_lets_a_sample_through_and_still_walls_a_plain_church(world):
    world.rows("businesses").extend([_sample(), _plain()])
    for f in ("vertical_reports", "reports_full", "period_close", "contractor_payments"):
        billing_limits.require_feature(SAMPLE, f)                     # no raise
    with pytest.raises(HTTPException) as e:
        billing_limits.require_feature(SAMPLE, "audit_trail")        # not on Growing
    assert e.value.status_code == 402
    with pytest.raises(HTTPException) as e:
        billing_limits.require_feature(PLAIN, "vertical_reports")
    assert e.value.status_code == 402 and e.value.detail["error"] == "feature_locked"


@pytest.fixture
def reports(world, monkeypatch):
    """The real /reports router over the fake, with the finance, reader and
    Giving-key gates (tested elsewhere) and the report bodies stood in."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import auth_supabase
    import giving_records
    import giving_reports
    import reports_router as rr
    world.rows("businesses").extend([_sample(), _plain()])
    monkeypatch.setattr(giving_records, "require_finance", lambda biz, user, need="see": None)
    monkeypatch.setattr(rr, "_owner_or_reader", lambda biz, user: {"id": biz, "settings": {}})
    monkeypatch.setattr(rr, "_giving_wall", lambda biz, user, need="see": None)
    monkeypatch.setattr(rr, "_fiscal_period", lambda row, p, f, t: (p, f, t))
    monkeypatch.setattr(giving_reports, "funds_report", lambda *a: {"ok": True, "report": "funds"})
    monkeypatch.setattr(giving_reports, "givers", lambda *a: {"ok": True, "givers": []})
    monkeypatch.setattr(giving_reports, "giver_history", lambda *a: {"ok": True, "gifts": []})
    app = FastAPI()
    app.include_router(rr.router)
    app.dependency_overrides[auth_supabase.require_user] = lambda: auth_supabase.AuthedUser(
        id=OWNER, email=TESTER, role="authenticated")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/reports/funds", "/reports/givers",
                                  "/reports/giver-history?contact_id=5a3b1e00-0000-4000-8000-0000000000aa"])
def test_the_church_reports_answer_200_in_the_sample(reports, path):
    join = "&" if "?" in path else "?"
    assert reports.get(f"{path}{join}biz={SAMPLE}").status_code == 200
    # the same report for a church with no plan is still the plan wall
    r = reports.get(f"{path}{join}biz={PLAIN}")
    assert r.status_code == 402 and r.json()["detail"]["error"] == "feature_locked"


def test_the_sample_still_has_no_allowance_and_is_refused_ai_sends_and_spend(world):
    world.rows("businesses").extend([_sample(), _home()])
    assert um.can_interact(SAMPLE) is False
    summary = um.usage_summary(SAMPLE)
    assert summary["allotment"] == 0 and summary["remaining"] == 0
    with pytest.raises(HTTPException) as e:
        billing_limits.require_units(SAMPLE)
    assert e.value.status_code == 409 and e.value.detail["error"] == "sample_church"
    for what in ("texts", "number", "bulk_email"):
        with pytest.raises(HTTPException) as e:
            billing_limits.require_card(SAMPLE, what)
        assert e.value.status_code == 409
    assert sc.send_refusal(SAMPLE) == "a sample church sends nothing"
    assert sc.spend_refused(SAMPLE) is True
    with sc.allow_sample_chief():
        assert sc.spend_refused(SAMPLE) is False                   # BE-4's own lane only


def test_the_sample_never_counts_as_paying(world):
    world.rows("businesses").extend([_sample(), _home()])
    # the owner's best plan (the business cap, the rehearsal) finds none
    assert billing_limits.owner_best_plan_row(OWNER) is None
    # MRR, the Money room and the founding count read plan_of / is_sample
    assert fg.plan_of(_sample()) is None
    assert fg.limit_for(_sample(), "texts_monthly") is None
    import platform_money
    src = (ROOT / "platform_money.py").read_text(encoding="utf-8")
    assert "is_sample=not.is.true" in src and platform_money


def test_opens_feature_is_only_asked_by_the_read_gates():
    """The narrow seam: only require_feature and entitlements ask it, so no
    allowance, spend or count path can ever see the tour plan."""
    callers = []
    for path in ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "opens_feature(" in text and path.name != "feature_gates.py":
            callers.append(path.name)
    assert callers == ["billing_limits.py"]
    src = (ROOT / "feature_gates.py").read_text(encoding="utf-8")
    assert src.count("opens_feature(") == 2          # its def, and entitlements' `allowed`
    assert "SAMPLE_TOUR_PLAN" not in src.split("def plan_of", 1)[1].split("def access_state", 1)[0]


# ═══ 2. The sample's welcome ═══════════════════════════════════════

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
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", m.send)

    async def lookup(owner_id):
        return OWNER_EMAILS.get(owner_id)
    monkeypatch.setattr(le, "_owner_email", lookup)
    return m


_NOT_CHURCH_WORDS = re.compile(r"\b(business(es)?|clients?|customers?|trial|free days|days free)\b", re.I)


def _voice_ok(text: str) -> None:
    assert "!" not in text
    assert not _NOT_CHURCH_WORDS.search(text), _NOT_CHURCH_WORDS.search(text).group(0)
    assert brand_voice.offenses(f"<p>{text}</p>") == []


def test_a_church_in_a_sample_gets_the_sample_welcome(world, mail, monkeypatch):
    import church_founding
    monkeypatch.setattr(church_founding, "public_state", lambda: dict(FOUNDING_OPEN))
    world.rows("businesses").append(_home())
    out = asyncio.run(le.send_welcome(_home(), TESTER, "Pastor Sam Lee", church_sample=True))
    assert out == {"sent": True, "kind": "sample_church"}
    assert len(mail.sent) == 1
    m = mail.sent[0]
    assert m["to_email"] == TESTER and m["reply_to"]
    assert "business_id" not in m                          # the platform's own mail, to the owner
    assert m["subject"] == "Welcome. Look around a sample church before First Church starts"
    body = m["body"]
    assert body.startswith("Hi Pastor Sam,\n\n")
    for line in ("Grace Street Fellowship, a sample church that is already set up",
                 "nothing you do there is saved or sent",
                 "Chief answers 10 questions about it.",
                 'press "Start your church" at the top of the screen and choose your plan',
                 FOUNDING_WORDS,
                 "No contract. Leave any time, and your records go with you.",
                 le.app_base_url()):
        assert line in body, line
    _voice_ok(m["subject"] + "\n" + body)
    stamps = world.rows("businesses")[0]["settings"][le.SETTINGS_KEY]
    assert stamps["welcome_at"]
    # one welcome: the stamp holds a second try
    again = asyncio.run(le.send_welcome(world.rows("businesses")[0], TESTER, "Pastor Sam Lee",
                                        church_sample=True))
    assert again["sent"] is False and len(mail.sent) == 1


@pytest.mark.parametrize("state,line", [
    (None, None),                                                       # off, past its date, unreadable
    ({"spots": 10, "left": 0, "ends": "2027-01-31"}, None),             # full
    ({"spots": 10, "left": 3, "ends": None},
     "The first ten churches keep the founding price for as long as they stay."),
    ({"spots": 1, "left": 1, "ends": "2027-01-31"},
     "The first church keeps the founding price for as long as it stays. The offer ends January 31."),
    (FOUNDING_OPEN, FOUNDING_WORDS),
])
def test_the_founding_line_only_while_a_place_is_open(monkeypatch, state, line):
    import church_founding
    monkeypatch.setattr(church_founding, "public_state", lambda: dict(state) if state else None)
    assert le.founding_line() == (line or "")
    body = le.sample_welcome_body(church_name="First Church", first_name="Ana")
    assert ("founding" in body.lower()) is bool(line)
    if line:
        assert line in body


def test_the_founding_line_reads_the_offers_own_end_day(monkeypatch):
    import church_founding
    monkeypatch.setenv("FOUNDING_CHURCHES_UNTIL", "2027-02-28")
    monkeypatch.setattr(church_founding, "public_state", lambda: dict(FOUNDING_OPEN))
    assert le.founding_line().endswith("The offer ends February 28.")


def test_the_retry_works_the_sample_out_itself(world, mail, monkeypatch):
    world.rows("businesses").append(_home())
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", TESTER)
    out = asyncio.run(le.send_welcome(_home(), TESTER, "Ana"))
    assert out["kind"] == "sample_church" and "Grace Street Fellowship" in mail.sent[0]["body"]


def test_everyone_else_keeps_todays_welcome(world, mail, monkeypatch):
    # the shipped default: test mode, nobody listed. No read for the answer.
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    barber = _home(id="b-1", type="barber", name="Northside Cuts")
    world.rows("businesses").append(barber)
    before = len(world.reads)
    out = asyncio.run(le.send_welcome(barber, TESTER, "Kim Ortiz"))
    assert out == {"sent": True}
    assert mail.sent[0]["subject"] == "Northside Cuts is set up. Three moves for your first week"
    assert "Grace Street" not in mail.sent[0]["body"]
    # only send_welcome's own first-business read and the stamp's fresh read
    assert [p for p in world.reads[before:] if "select=*" in p] == []


def test_signup_tells_the_welcome_which_one(world, monkeypatch):
    import first_run_arc
    import launch_access
    import no_card_trial
    monkeypatch.setattr(no_card_trial, "start", lambda row, source="signup", email=None: None)
    monkeypatch.setattr(first_run_arc, "begin", lambda biz, **kw: None)
    monkeypatch.delenv("LAUNCH_INVITE_ONLY", raising=False)
    from auth_supabase import AuthedUser

    class _Tasks:
        def __init__(self):
            self.calls = []

        def add_task(self, fn, *a, **k):
            self.calls.append((fn, a, k))

    def create(btype):
        tasks = _Tasks()
        body = launch_access.CreateBusinessBody(name="First Church", type=btype,
                                                settings={"practitioner_name": "Pastor Sam Lee"})
        launch_access.create_business(body, AuthedUser(id=OWNER, email=TESTER, role="authenticated"), tasks)
        return next(c for c in tasks.calls if c[0] is le.send_welcome)

    fn, args, kw = create("church")
    assert kw == {"church_sample": True} and args[1] == TESTER and args[2] == "Pastor Sam Lee"
    world.t["businesses"] = []
    fn, args, kw = create("barber")
    assert kw == {"church_sample": False}
    src = (ROOT / "launch_access.py").read_text(encoding="utf-8")
    assert "TODO(sample church" not in src


def test_the_greeting_matches_chiefs():
    import chief_of_staff  # noqa: F401 - chief_prompt is imported through it
    import chief_prompt
    assert le._GREETING_TITLES == frozenset(chief_prompt._GREETING_TITLES)
    for name in ("Pastor Kevin McCloud", "Dre Carter", "Rev. Ana Diaz", "Ana", "", None):
        assert le._greeting(name) == (chief_prompt.greeting_name(name) or "there")


# ═══ 3. The day-3 note ═══════════════════════════════════════════════

def _seed_world(world, *, home=None, sample=None):
    world.rows("businesses").extend([home or _home(), sample or _sample()])


def test_the_day_three_note_goes_once(world, mail, monkeypatch):
    import church_founding
    monkeypatch.setattr(church_founding, "public_state", lambda: dict(FOUNDING_OPEN))
    _seed_world(world)
    world.rows("sample_church_questions").extend([{"user_id": OWNER, "n": 1}, {"user_id": OWNER, "n": 2}])
    out = asyncio.run(le.sample_follow_up_tick())
    assert out["sent"] == 1 and out["failed"] == 0, out
    m = mail.sent[0]
    assert m["to_email"] == TESTER and "business_id" not in m
    assert m["subject"] == "Ready to start First Church?"
    body = m["body"]
    assert body.startswith("Hi Pastor Sam,\n\n")
    for line in ("Grace Street Fellowship, the sample church, is still there for you to look around",
                 "Chief has 8 of your 10 questions left to answer about it.",
                 'press "Start your church"', FOUNDING_WORDS,
                 "No contract. Leave any time, and your records go with you."):
        assert line in body, line
    _voice_ok(m["subject"] + "\n" + body)
    home = next(r for r in world.rows("businesses") if r["id"] == HOME)
    assert home["settings"][le.SETTINGS_KEY][le.SAMPLE_FOLLOW_UP_KEY]
    assert home["settings"]["practitioner_name"] == "Pastor Sam Lee"      # merged, not replaced
    # nothing written to the sample
    sample = next(r for r in world.rows("businesses") if r["id"] == SAMPLE)
    assert le.SETTINGS_KEY not in sample["settings"]
    # the next hour: stamped, so nothing
    assert asyncio.run(le.sample_follow_up_tick())["sent"] == 0
    # even with the stamp lost, the delivery key holds it to one email
    home["settings"].pop(le.SETTINGS_KEY)
    asyncio.run(le.sample_follow_up_tick())
    assert len(mail.sent) == 1


@pytest.mark.parametrize("left,line", [
    (10, "Chief still has all 10 of your questions to answer about it."),
    (0, "You've asked Chief all 10 of your questions. In your own church, Chief keeps going."),
    (None, "Chief answers 10 questions about it."),
])
def test_the_note_says_where_the_questions_stand(monkeypatch, left, line):
    body = le.sample_follow_up_body(church_name="First Church", first_name="Ana",
                                    questions_left=left, founding="")
    assert line in body
    assert "founding" not in body.lower()
    _voice_ok(body)


def _over_days(days):
    return {"created_at": _iso(_now() - timedelta(days=days))}


@pytest.mark.parametrize("home,sample,why", [
    ({"subscription_status": "active", "stripe_subscription_id": "sub_1"}, {}, "started"),
    ({"subscription_status": "trialing", "trial_ends_at": _iso(_now() + timedelta(days=4))}, {}, "trialing"),
    ({"comp_tier": "church_growing"}, {}, "comped"),
    ({"is_active": False}, {}, "deleted"),
    ({"type": "barber"}, {}, "not a church"),
    ({"owner_id": "gf"}, {}, "grandfathered"),
    (_over_days(2.5), {}, "too early"),
    (_over_days(6.5), {}, "too late"),
    ({}, None, "no sample"),
    ({}, {"settings": {sc.SETTINGS_KEY: {"status": "ending", "seeded_at": "x"}}}, "ending"),
    ({}, {"settings": {sc.SETTINGS_KEY: {"status": "pending"}}}, "never seeded"),
    ({}, {"is_sample": False, "sample_of": None, "id": "other"}, "not a sample"),
    ({"settings": {le.SETTINGS_KEY: {le.SAMPLE_FOLLOW_UP_KEY: "2026-11-14T00:00:00Z"}}}, {}, "stamped"),
])
def test_no_note_when_it_isnt_true(world, mail, home, sample, why):
    OWNER_EMAILS.setdefault("gf", "gf@church.test")
    rows = [_home(**home)]
    if sample is not None:
        rows.append(_sample(**sample))
    world.rows("businesses").extend(rows)
    out = asyncio.run(le.sample_follow_up_tick())
    assert out["ok"] and out["failed"] == 0, (why, out)       # it ran, and chose not to
    assert out["sent"] == 0 and mail.sent == [], why


def test_test_mode_writes_only_to_testers(world, mail, monkeypatch):
    _seed_world(world)
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", "someone@else.test")
    assert asyncio.run(le.sample_follow_up_tick())["sent"] == 0
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", f"someone@else.test,{TESTER}")
    assert asyncio.run(le.sample_follow_up_tick())["sent"] == 1


@pytest.mark.parametrize("env,reason", [
    ({"CHURCH_SAMPLE": "off"}, "switch_off"),
    ({"CHURCH_SAMPLE": "test"}, "switch_off"),                 # the shipped default: nobody listed
    ({"LIFECYCLE_EMAILS": "off"}, "disabled"),
    ({"BILLING_ENFORCE": "off"}, "enforcement_off"),
])
def test_switched_off_it_reads_nothing(world, mail, monkeypatch, env, reason):
    _seed_world(world)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    before = len(world.reads)
    out = asyncio.run(le.sample_follow_up_tick())
    assert out["reason"] == reason and out["sent"] == 0
    assert world.reads[before:] == []
    assert mail.sent == []


def test_it_never_reads_a_sample_as_a_candidate(world, mail):
    _seed_world(world)
    asyncio.run(le.sample_follow_up_tick())
    first = next(p for p in world.reads if p.startswith("/businesses?select="))
    assert "is_sample=is.false" in first and "is_active=eq.true" in first


def test_a_church_that_starts_just_before_the_send_gets_nothing(world, mail, monkeypatch):
    """The candidate list is read first; the home is read again right before
    the send, so a church that chose its plan in between is let be."""
    _seed_world(world)
    real = le._fresh_home

    def started(bid):
        row = real(bid)
        row.update(subscription_status="active", stripe_subscription_id="sub_1")
        return row
    monkeypatch.setattr(le, "_fresh_home", started)
    assert asyncio.run(le.sample_follow_up_tick())["sent"] == 0


def test_the_note_is_scheduled_like_the_other_lifecycle_mail():
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("sample_follow_up", _lifecycle.sample_follow_up_tick)' in src
    block = src[src.index("import lifecycle_emails as _lifecycle"):]
    block = block[:block.index("except Exception as e:")]
    assert 'id="sample_follow_up"' in block


# ═══ 4. A comp on any plan is full access ════════════════════════════

@pytest.mark.parametrize("plan", fg.ALL_PLANS)
def test_a_comp_on_any_plan_is_full_access(monkeypatch, plan):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    row = {"id": "c-1", "type": "church", "comp_tier": plan, "subscription_status": None}
    assert fg.access_state(row) == {"state": "full", "reason": f"comp_{plan}"}
    assert fg.plan_of(row) == plan                   # the two agree, as they always should have
    # a careless church_sample=True can't pull a comped church into a sample
    assert fg.access_state(row, church_sample=True)["state"] == "full"


@pytest.mark.parametrize("comp", ["", "  ", "gold", "church_huge"])
def test_a_comp_that_names_no_plan_is_no_comp(monkeypatch, comp):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    assert fg.access_state({"comp_tier": comp}) == {"state": "locked", "reason": "no_subscription"}


def test_a_church_comp_passes_require_live_access(world, monkeypatch):
    world.rows("businesses").append(_plain(comp_tier="church_large"))
    billing_limits.require_live_access(PLAIN)        # no 402
    world.rows("businesses")[0]["comp_tier"] = None
    with pytest.raises(HTTPException) as e:
        billing_limits.require_live_access(PLAIN)
    assert e.value.status_code == 402


# ═══ 5. The church pages' trial line ═════════════════════════════════

@pytest.fixture
def site(monkeypatch):
    import church_founding
    import marketing_pages as mp
    import stripe_billing
    monkeypatch.setenv("CHURCH_SITE", "on")
    monkeypatch.delenv("HOME_EDITION", raising=False)
    monkeypatch.delenv("PLAN_CHURCH_FREE_WEEK", raising=False)
    monkeypatch.delenv("CHURCH_FREE_WEEK", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    monkeypatch.setattr(church_founding, "public_state", lambda: None)
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    import church_site
    return church_site


def test_the_trial_line_says_look_around_first_only_when_sample_is_on(site, monkeypatch):
    monkeypatch.setenv("CHURCH_SAMPLE", "off")
    before = site._trial_tokens(church=True)
    coach_before = site._trial_tokens(church=False)
    assert site.SAMPLE_LINE not in str(before)
    # test mode, testers listed: the testers alone get a sample, so the public words stay
    monkeypatch.setenv("CHURCH_SAMPLE", "test")
    monkeypatch.setenv("CHURCH_SAMPLE_TESTERS", TESTER)
    assert site._trial_tokens(church=True) == before
    # on for everyone
    monkeypatch.setenv("CHURCH_SAMPLE", "on")
    on = site._trial_tokens(church=True)
    assert on == {
        "CTA_START": "Start free, no card",
        "TRIAL_LINE": f"Look around a sample church first, no card needed. {site.PROMISE}",
        "TRIAL_FINE": ("Look around a sample church first, no card needed · "
                       "your first month starts the day you choose your plan"),
    }
    assert site._trial_tokens(church=False) == coach_before       # the coach pages keep theirs


def test_every_church_page_says_it_when_on_and_none_when_off(site, monkeypatch):
    monkeypatch.setenv("CHURCH_SAMPLE", "on")
    for slug in site.PAGES:
        html = site.render(slug)
        assert site.SAMPLE_LINE in html, slug
        assert site.PROMISE in html, slug
        low = html.lower()
        assert "days free" not in low and "free trial" not in low, slug
        assert brand_voice.offenses(html) == [], slug
    monkeypatch.setenv("CHURCH_SAMPLE", "off")
    for slug in site.PAGES:
        assert site.SAMPLE_LINE not in site.render(slug), slug


def test_with_the_free_week_back_it_says_when_the_free_days_start(site, monkeypatch):
    import pricing_config
    monkeypatch.setenv("CHURCH_SAMPLE", "on")
    monkeypatch.setattr(pricing_config, "church_free_week", lambda: True)
    import marketing_pages as mp
    free = mp._trial_free_phrase()
    on = site._trial_tokens(church=True)
    assert on["TRIAL_LINE"] == f"Look around a sample church first, no card needed. {free} once you choose your plan."
    assert on["TRIAL_FINE"].endswith(f"· {free} once you choose your plan")
