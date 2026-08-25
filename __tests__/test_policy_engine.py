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


def test_every_acting_path_shares_the_evaluator():
    """The pin that grew.

    It named the scheduler and the workflow runner, which is exactly the
    set that had been fixed at the time — and the trusted-autonomy sweep,
    which mails clients under a standing grant, was not on the list and so
    went on not calling the engine. A pin that lists only the paths
    already fixed cannot catch the next one."""
    for mod in ("chief_scheduler.py", "workflow_engine.py", "rules_router.py"):
        src = pathlib.Path(_here.parent / mod).read_text(encoding="utf-8")
        assert "policy_engine" in src, f"{mod} must use the shared evaluator"
        assert "action_registry.is_bulk" not in src, \
            f"{mod} should defer to the engine, not re-implement the rule"


# ─── The pause switch ────────────────────────────────────────────────
#
# settings.automations_paused was read by rules_engine and the trust
# sweep, and by nothing else. A practitioner who paused their automations
# still had the scheduler executing actions, workflows advancing, and
# autopilot sending mail.

def _paused_biz(btype="coach", paused=True, bid="b1"):
    return {"id": bid, "type": btype, "owner_id": "owner1",
            "settings": {"automations_paused": paused}}


def test_paused_business_stops_unattended_work(fake):
    v = pe.evaluate("b1", verb="create_task", surface="scheduled",
                    prompted=False, biz_row=_paused_biz())
    assert not v.allowed
    assert v.rule == "business:automations_paused"


def test_pause_does_not_touch_what_the_practitioner_asks_for(fake):
    """Pausing automations pauses what runs on its own. Someone who
    pauses automations and then tells Chief to do something has not
    contradicted themselves."""
    v = pe.evaluate("b1", verb="create_task", surface="chat",
                    prompted=True, biz_row=_paused_biz())
    assert v.allowed


def test_an_unpaused_business_is_unaffected(fake):
    v = pe.evaluate("b1", verb="create_task", surface="scheduled",
                    prompted=False, biz_row=_paused_biz(paused=False))
    assert v.allowed


def test_a_business_with_no_setting_is_not_paused(fake):
    v = pe.evaluate("b1", verb="create_task", surface="scheduled",
                    prompted=False, biz_row=_biz("coach"))
    assert v.allowed


def test_the_refusal_names_the_reason_the_practitioner_will_recognise(fake):
    """A paused business asked to run a BULK verb unattended breaks two
    rules at once. The one worth saying out loud is the one they can act
    on: they turned automations off. 'Bulk verbs cannot run unattended'
    is true and useless here."""
    v = pe.evaluate("b1", verb="bulk_approve", surface="scheduled",
                    prompted=False, biz_row=_paused_biz())
    assert not v.allowed
    assert v.rule == "business:automations_paused"


def test_reads_never_pay_for_the_pause_check(monkeypatch):
    """The business row is now fetched BEFORE the unattended rules,
    because the pause check needs it. A read must still return above all
    of that — otherwise every read-only action just acquired a database
    round trip, and reads are the common case."""
    def _boom(*a, **k):
        raise AssertionError("a read must not touch the database")
    monkeypatch.setattr(pe, "_biz", _boom)
    v = pe.evaluate("b1", verb="show_revenue", surface="scheduled",
                    prompted=False, biz_row=None)
    assert v.allowed
    assert v.rule == "scheduled:read"


def test_the_paths_that_cannot_ask_the_engine_read_the_flag_themselves():
    """campaigns_tick and the SMS reminder sweep send on a schedule but
    have no Chief verb to hand the evaluator, so they read the same
    predicate directly rather than being left out."""
    for mod in ("campaigns_router.py", "sms_alerts.py"):
        src = pathlib.Path(_here.parent / mod).read_text(encoding="utf-8")
        assert "business_paused" in src, \
            f"{mod} sends unattended and must honor automations_paused"


# ─── The trusted sweep's proposal mapping ────────────────────────────

def test_every_executable_proposal_type_names_an_equivalent_verb():
    """A proposal type the sweep can execute but cannot classify would
    reach policy_engine as an unregistered verb and be refused forever —
    a silent, total outage of the trust track."""
    import rules_router as rr
    missing = sorted(rr.EXECUTABLE_PROPOSAL_TYPES
                     - set(rr._PROPOSAL_EQUIVALENT_VERB))
    assert not missing, f"executable proposal types with no verb: {missing}"


def test_every_equivalent_verb_is_a_real_registered_verb():
    """The mapping's whole point is to reuse the one registry. A typo
    here fails closed and stops the sweep, so it fails loudly first."""
    import rules_router as rr
    import action_registry
    for ptype, verb in rr._PROPOSAL_EQUIVALENT_VERB.items():
        assert action_registry.classification(verb) is not None, \
            f"{ptype} maps to '{verb}', which is not in the registry"


def test_the_followup_email_is_classified_as_the_send_it_is():
    """_exec_send_template_email calls Resend directly — the mail is gone.
    Mapping it to anything gentler than a class-C client-facing verb
    would launder an unattended send through a proposal."""
    import rules_router as rr
    import action_registry
    import policy_engine
    verb = rr._PROPOSAL_EQUIVALENT_VERB["propose_followup_email"]
    assert action_registry.reversibility(verb) == "C"
    assert verb in policy_engine.CLIENT_FACING


def test_a_regulated_practice_is_not_mailed_by_the_trust_track(fake):
    """The grant is a standing one, not the practitioner asking for THIS
    send — so the regulated-vertical promise applies to it."""
    import rules_router as rr
    v = pe.evaluate("b1",
                    verb=rr._PROPOSAL_EQUIVALENT_VERB["propose_followup_email"],
                    surface="trust-track", prompted=False,
                    biz_row=_biz("therapist"))
    assert not v.allowed
    assert v.rule == "vertical:client_facing_disabled"


def test_the_trust_sweep_fails_closed_on_a_broken_check():
    """Matching chief_scheduler and workflow_engine: a safety check that
    cannot run is not permission to send."""
    src = pathlib.Path(_here.parent / "rules_router.py").read_text(encoding="utf-8")
    body = src.split("def _run_trusted_sweep_sync(")[1].split("\nasync def ")[0]
    assert "policy_engine.evaluate(" in body
    assert body.index("policy_engine.evaluate(") < body.index("_execute_proposal("), \
        "the policy check must precede execution, not follow it"


# ─── The unattended sender's ledger row ──────────────────────────────

def test_autopilot_writes_to_the_ledger():
    """_should_auto_approve's own docstring calls this path THE
    unattended sender. It was the only unattended dispatcher writing no
    audit_log row — an `events` row is not append-only and carries no
    authorized_by."""
    src = pathlib.Path(_here.parent / "chief_of_staff.py").read_text(encoding="utf-8")
    body = src.split("async def _process_autopilot_for_draft(")[1].split("\nasync def ")[0]
    assert "audit_log" in body, "the unattended sender must reach the ledger"
    assert "actor_id=\"autopilot\"" in body, \
        "actor_type is CHECK-constrained, so the identity rides actor_id"
    assert "authorized_by=" in body, \
        "the ledger's sixth field is the point of the row"
