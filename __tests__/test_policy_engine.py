"""Action Ledger Stage 3 — the policy engine.

One evaluator answering "is this allowed, and under which rule", whose
answer becomes the ledger's sixth field. The headline behaviour change:
settings.autonomy.client_facing_autonomy has been seeded "disabled" for
every law / therapy / counselling business since launch_access shipped,
and NOTHING has ever read it. This is the first reader.
"""
from __future__ import annotations

import asyncio
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import policy_engine as pe  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    return fb


def _biz(btype="coach", autonomy=None, bid="b1"):
    settings = {}
    if autonomy is not None:
        settings["autonomy"] = {"client_facing_autonomy": autonomy}
    return {"id": bid, "type": btype, "owner_id": "owner1", "settings": settings}


# ─── The promise that was never kept ─────────────────────────────────

def test_regulated_vertical_blocks_unattended_client_contact(fake):
    """A therapist's account has carried
    client_facing_autonomy='disabled' since creation while the autopilot
    sweep could still email their clients. That gap closes here."""
    for btype in ("therapist", "lawyer", "counselor"):
        v = pe.evaluate("b1", verb="send_sms", surface="autopilot",
                        prompted=False, biz_row=_biz(btype))
        assert not v.allowed, f"{btype} must not send unattended"
        assert v.rule == "vertical:client_facing_disabled"


def test_the_practitioner_asking_is_never_blocked(fake):
    """The protection is about UNATTENDED contact. A therapist who asks
    Chief to text a client must not be obstructed doing their job."""
    v = pe.evaluate("b1", verb="send_sms", surface="chat",
                    prompted=True, biz_row=_biz("therapist"))
    assert v.allowed


def test_regulated_default_applies_without_the_settings_block(fake):
    """Businesses created before the seeding shipped have no autonomy
    block at all. They must not be LESS protected than newer ones."""
    v = pe.evaluate("b1", verb="draft_and_send", surface="autopilot",
                    prompted=False, biz_row=_biz("therapist", autonomy=None))
    assert not v.allowed
    assert v.rule == "vertical:client_facing_disabled"


def test_owner_can_switch_it_on(fake):
    """The setting is a real control, not decoration — an explicit
    'enabled' lets a regulated practice opt in."""
    v = pe.evaluate("b1", verb="send_sms", surface="autopilot",
                    prompted=False, biz_row=_biz("therapist", autonomy="enabled"))
    assert v.allowed


def test_unregulated_business_is_unaffected(fake):
    v = pe.evaluate("b1", verb="send_sms", surface="autopilot",
                    prompted=False, biz_row=_biz("coach"))
    assert v.allowed


def test_non_client_facing_work_still_runs_for_regulated(fake):
    """Bookkeeping is not client contact. Over-blocking would teach a
    therapist to switch the protection off."""
    for verb in ("create_invoice", "log_expense", "create_task"):
        v = pe.evaluate("b1", verb=verb, surface="scheduled",
                        prompted=False, biz_row=_biz("therapist"))
        assert v.allowed, f"{verb} is not client contact and must still run"


# ─── The rules that were already enforced, now in one place ──────────

def test_bulk_never_runs_unattended(fake):
    v = pe.evaluate("b1", verb="batch_email", surface="workflow",
                    prompted=False, biz_row=_biz())
    assert not v.allowed
    assert v.rule == "bulk:never-unattended"


def test_registry_drift_fails_closed(fake):
    v = pe.evaluate("b1", verb="not_a_real_verb", surface="chat",
                    prompted=True, biz_row=_biz())
    assert not v.allowed
    assert v.rule == "registry:unclassified"


def test_class_c_unattended_is_recorded_not_refused(fake):
    """Recurring invoices are a real feature. Whether they should keep
    firing unattended is Kevin's ruling; the ledger's job is to make the
    exposure visible, not to decide it in a helper."""
    v = pe.evaluate("b1", verb="create_invoice", surface="scheduled",
                    prompted=False, biz_row=_biz())
    assert v.allowed
    assert v.rule == "scheduled:C:unattended"


def test_reads_are_cheap_and_allowed(fake):
    v = pe.evaluate("b1", verb="check_goals", surface="agent",
                    prompted=False, biz_row=_biz())
    assert v.allowed and v.rule.endswith(":read")


# ─── Field 6 ─────────────────────────────────────────────────────────

def test_rule_is_greppable_not_prose(fake):
    """authorized_by has to survive being queried a year from now, so
    the rule is a stable token and the sentence lives in `reason`."""
    v = pe.evaluate("b1", verb="send_sms", surface="autopilot",
                    prompted=False, biz_row=_biz("therapist"))
    assert " " not in v.rule
    assert len(v.reason.split()) > 3


def test_client_facing_set_is_curated_from_real_verbs():
    """Hand-curated from action_registry's written reasons — the
    registry's own lesson is that this cannot be automated."""
    from chief_of_staff import ACTION_HANDLERS
    assert pe.CLIENT_FACING <= set(ACTION_HANDLERS)
    for outbound in ("send_sms", "draft_and_send", "batch_email",
                     "approve_draft", "send_invoice", "publish_post"):
        assert outbound in pe.CLIENT_FACING
    # Creating a bill is bookkeeping; SENDING it is the client-facing act.
    assert "create_invoice" not in pe.CLIENT_FACING


# ─── Wiring ──────────────────────────────────────────────────────────

def test_autopilot_consults_the_engine_before_its_own_level(monkeypatch):
    """Order matters: a regulated practice set to 'full' autopilot is
    exactly the dangerous case, so the policy check runs FIRST."""
    src = pathlib.Path(_here.parent / "chief_of_staff.py").read_text(encoding="utf-8")
    body = src.split("async def _should_auto_approve(")[1].split("async def ")[0]
    assert "policy_engine" in body
    assert body.index("policy_engine") < body.index("_autopilot_level"), \
        "the policy check must precede the autopilot level read"


def test_autopilot_blocks_a_regulated_send(fake, monkeypatch):
    import chief_of_staff as cos
    biz = _biz("therapist")
    biz["settings"]["autopilot"] = {"overall": "full"}
    ok, reason = asyncio.run(
        cos._should_auto_approve(None, biz, "nurture", {}, None))
    assert ok is False
    assert reason == "vertical:client_facing_disabled"


def test_chat_path_now_computes_the_seat_role():
    """No Chief code path ever called role_of. A viewer seat reached the
    LLM and died at insert time as a bare 'insert failed'."""
    src = pathlib.Path(_here.parent / "chief_of_staff.py").read_text(encoding="utf-8")
    body = src.split("async def _execute_actions(")[1].split("async def ")[0]
    assert "policy_engine.evaluate(" in body
    assert "user_id=user_id" in body
    assert '_authorized_by' in body


def test_scheduler_and_workflow_share_the_evaluator():
    for mod in ("chief_scheduler.py", "workflow_engine.py"):
        src = pathlib.Path(_here.parent / mod).read_text(encoding="utf-8")
        assert "policy_engine" in src, f"{mod} must use the shared evaluator"
        assert "action_registry.is_bulk" not in src, \
            f"{mod} should defer to the engine, not re-implement the rule"
