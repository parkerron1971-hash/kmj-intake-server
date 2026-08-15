"""
test_chief_missions.py — Chief executes plans, and the plans obey the
same law as everything else.

The Jarvis arc, step 3. What must hold:

  1. A PROPOSAL EXECUTES NOTHING. The draft is the proposal; the
     practitioner's word (start_mission) is the release.
  2. VALIDATION FAILS CLOSED. Unknown verbs, unclassified verbs, mission
     recursion, window dressing, >12 steps — refused at proposal time,
     never discovered mid-run.
  3. STEPS GO THROUGH THE DOOR. Every step dispatches via
     _execute_actions — the mission engine never touches a handler
     directly, so the Class-C gate and the ledger apply for free.
  4. CLASS-C STEPS PAUSE. The mission stops as awaiting_approval BEFORE
     an irreversible step; advance runs it and continues. Class-A steps
     run straight through.
  5. FAILURE PAUSES, HONESTLY. A failed step pauses the mission with the
     failure in the report — never a silent skip, never "completed".
  6. STATE SURVIVES. Progress is saved after every step, and a refused
     save is a loud failure (the _sb-returns-None class).

House rules: sync tests + asyncio.run (no pytest-asyncio in CI).
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_missions as cm
import chief_of_staff as cos


_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}}


class _MissionDB:
    """In-memory chief_missions table speaking _sb's dialect."""

    def __init__(self):
        self.rows = {}
        self.n = 0
        self.refuse_writes = False

    async def sb(self, client, method, path, body=None):
        if "/chief_missions" not in path:
            return []
        if method == "POST":
            if self.refuse_writes:
                return None
            self.n += 1
            row = dict(body, id=f"m-{self.n}", report="", updated_at="t0")
            self.rows[row["id"]] = row
            return [row]
        if method == "PATCH":
            if self.refuse_writes:
                return None
            mid = path.split("?id=eq.")[1].split("&")[0]
            self.rows[mid].update(body)
            return [self.rows[mid]]
        # GET — honor id / status filters crudely. The id marker must be
        # "&id=eq." — a bare "id=eq." also matches inside business_id=eq.
        out = list(self.rows.values())
        if "&id=eq." in path:
            mid = path.split("&id=eq.")[1].split("&")[0]
            out = [r for r in out if r["id"] == mid]
        if "status=in.(" in path:
            allowed = path.split("status=in.(")[1].split(")")[0].split(",")
            out = [r for r in out if r["status"] in allowed]
        return out


@pytest.fixture
def db(monkeypatch):
    d = _MissionDB()
    monkeypatch.setattr(cos, "_sb", d.sb)
    return d


@pytest.fixture
def executed(monkeypatch):
    """Spy on _execute_actions — proves steps go through THE DOOR and
    scripts per-verb results."""
    log = []
    fail_verbs = set()

    async def fake_execute(client, biz, actions, user_id=None):
        out = []
        for a in actions:
            log.append({"verb": a.get("type"), "user_id": user_id, "action": a})
            if a.get("type") in fail_verbs:
                out.append({"type": a.get("type"), "result": "Failed: nope",
                            "label": "✗ nope", "failed": True})
            else:
                out.append({"type": a.get("type"), "result": "ok",
                            "label": f"did {a.get('type')}"})
        return out

    monkeypatch.setattr(cos, "_execute_actions", fake_execute)
    fake_execute.log = log
    fake_execute.fail_verbs = fail_verbs
    return fake_execute


def _steps(*verbs, **kw):
    approval = kw.get("approval") or set()
    return [{"title": f"do {v}", "action": {"type": v},
             **({"approval": True} if v in approval else {})}
            for v in verbs]


def _propose(db, steps, title="Collect the invoices"):
    return asyncio.run(cm.handle_propose_mission(
        None, _BIZ, {"type": "propose_mission", "title": title,
                     "goal": "collect", "steps": steps}))


# ─────────────────────────────────────────────────────────────────────
# 1 + 2. Proposal: inert, and fail-closed
# ─────────────────────────────────────────────────────────────────────

def test_a_proposal_executes_nothing(db, executed):
    r = _propose(db, _steps("check_goals", "create_contact"))
    assert not cos._action_failed(r)
    assert executed.log == [], "the draft is the proposal — nothing runs"
    assert db.rows and list(db.rows.values())[0]["status"] == "draft"
    assert r.get("result") and r.get("label")


@pytest.mark.parametrize("bad,why", [
    ([{"title": "x", "action": {"type": "summon_unicorns"}}], "unknown"),
    ([{"title": "x", "action": {"type": "start_mission"}}], "recursion"),
    ([{"title": "x", "action": {"type": "propose_mission"}}], "recursion"),
    ([{"title": "x", "action": {"type": "navigate", "tab": "grow"}}], "dressing"),
    ([{"title": "x"}], "no action"),
    ([], "empty"),
])
def test_bad_plans_are_refused_at_proposal_time(db, executed, bad, why):
    r = _propose(db, bad)
    assert cos._action_failed(r), why
    assert not db.rows, "a refused plan must not leave a row behind"


def test_thirteen_steps_is_too_many(db, executed):
    r = _propose(db, _steps(*(["check_goals"] * 13)))
    assert cos._action_failed(r)


def test_class_c_steps_are_gated_at_proposal(db, executed):
    # send_invoice is registry class C — the plan must carry the gate.
    import action_registry as ar
    assert ar.reversibility("send_invoice") == "C", "premise"
    _propose(db, _steps("create_contact", "send_invoice"))
    steps = list(db.rows.values())[0]["steps"]
    assert steps[0]["gate"] is False, "class-A runs free once the plan is approved"
    assert steps[1]["gate"] is True, "class-C always pauses"


def test_the_proposer_can_force_a_gate_on_anything(db, executed):
    _propose(db, _steps("create_contact", approval={"create_contact"}))
    assert list(db.rows.values())[0]["steps"][0]["gate"] is True


# ─────────────────────────────────────────────────────────────────────
# 3 + 4. Execution: through the door, pausing at gates
# ─────────────────────────────────────────────────────────────────────

def _start(db):
    return asyncio.run(cm.handle_start_mission(None, _BIZ, {"type": "start_mission"}))


def _advance(db):
    return asyncio.run(cm.handle_advance_mission(None, _BIZ, {"type": "advance_mission"}))


def test_start_runs_ungated_steps_through_execute_actions(db, executed):
    _propose(db, _steps("check_goals", "create_contact"))
    r = _start(db)
    assert [e["verb"] for e in executed.log] == ["check_goals", "create_contact"], (
        "every step must go through _execute_actions — the same door as chat"
    )
    assert r["status"] == "completed"
    assert list(db.rows.values())[0]["status"] == "completed"


def test_the_mission_pauses_before_an_irreversible_step(db, executed):
    _propose(db, _steps("create_contact", "send_invoice", "check_goals"))
    r = _start(db)
    assert [e["verb"] for e in executed.log] == ["create_contact"], (
        "send_invoice must NOT have run — the gate comes first"
    )
    assert r["status"] == "awaiting_approval"
    assert "needs your OK" in r["result"]
    row = list(db.rows.values())[0]
    assert row["status"] == "awaiting_approval"
    assert row["steps"][1]["status"] == "awaiting"


def test_advance_lifts_the_gate_and_finishes(db, executed):
    _propose(db, _steps("create_contact", "send_invoice", "check_goals"))
    _start(db)
    executed.log.clear()
    r = _advance(db)
    assert [e["verb"] for e in executed.log] == ["send_invoice", "check_goals"]
    assert r["status"] == "completed"


def test_advance_with_nothing_waiting_is_an_honest_no(db, executed):
    r = _advance(db)
    assert cos._action_failed(r)


def test_start_without_a_draft_is_an_honest_no(db, executed):
    r = _start(db)
    assert cos._action_failed(r)


# ─────────────────────────────────────────────────────────────────────
# 5. Failure pauses, honestly
# ─────────────────────────────────────────────────────────────────────

def test_a_failed_step_pauses_with_the_failure_in_the_report(db, executed):
    executed.fail_verbs.add("create_contact")
    _propose(db, _steps("check_goals", "create_contact", "check_inventory"))
    r = _start(db)
    assert r["status"] == "paused"
    row = list(db.rows.values())[0]
    assert row["status"] == "paused"
    assert row["steps"][1]["status"] == "failed"
    assert row["steps"][2]["status"] == "pending", "never silently skip past a failure"
    assert "Paused at step 2" in row["report"]


def test_advance_retries_the_failed_step(db, executed):
    executed.fail_verbs.add("create_contact")
    _propose(db, _steps("create_contact", "check_goals"))
    _start(db)
    executed.fail_verbs.clear()
    executed.log.clear()
    r = _advance(db)
    assert [e["verb"] for e in executed.log] == ["create_contact", "check_goals"]
    assert r["status"] == "completed"


# ─────────────────────────────────────────────────────────────────────
# 6. State + reads + abandonment
# ─────────────────────────────────────────────────────────────────────

def test_progress_is_saved_after_every_step(db, executed, monkeypatch):
    saves = []
    real_save = cm._save

    async def counting_save(client, mission):
        saves.append(mission["current_step"])
        return await real_save(client, mission)
    monkeypatch.setattr(cm, "_save", counting_save)
    _propose(db, _steps("check_goals", "create_contact"))
    _start(db)
    assert len(saves) >= 2, (
        "a deploy restart mid-mission must not forget which steps ran"
    )


def test_a_refused_save_fails_loudly_on_abandon(db, executed):
    _propose(db, _steps("check_goals"))
    db.refuse_writes = True
    r = asyncio.run(cm.handle_abandon_mission(None, _BIZ, {"type": "abandon_mission"}))
    assert cos._action_failed(r), "_sb returned None — success would be a lie"


def test_mission_status_tells_per_step_truth(db, executed):
    _propose(db, _steps("create_contact", "send_invoice"))
    _start(db)
    r = asyncio.run(cm.handle_mission_status(None, _BIZ, {"type": "mission_status"}))
    assert r["signal"] == {"open": 1, "awaiting": 1}
    m = r["missions"][0]
    assert m["steps"][0]["status"] == "done"
    assert m["steps"][1]["status"] == "awaiting"
    assert "WAITING ON YOU" in r["speak"]


def test_mission_status_with_nothing_open_is_plainly_empty(db, executed):
    r = asyncio.run(cm.handle_mission_status(None, _BIZ, {"type": "mission_status"}))
    assert not cos._action_failed(r)
    assert r["signal"]["open"] == 0


def test_abandon_leaves_run_steps_run(db, executed):
    _propose(db, _steps("create_contact", "send_invoice"))
    _start(db)
    r = asyncio.run(cm.handle_abandon_mission(None, _BIZ, {"type": "abandon_mission"}))
    assert not cos._action_failed(r)
    assert list(db.rows.values())[0]["status"] == "abandoned"


def test_open_mission_cap(db, executed):
    for i in range(cm.MAX_OPEN_MISSIONS):
        r = _propose(db, _steps("check_goals"), title=f"m{i}")
        assert not cos._action_failed(r)
    r = _propose(db, _steps("check_goals"), title="one too many")
    assert cos._action_failed(r)


# ─────────────────────────────────────────────────────────────────────
# Integration seams
# ─────────────────────────────────────────────────────────────────────

def test_the_prompt_documents_every_mission_verb():
    src = pathlib.Path(cos.__file__).read_text(encoding="utf-8")
    flat = src.replace("{{", "{").replace(" ", "")
    for v in ("propose_mission", "start_mission", "advance_mission",
              "abandon_mission", "mission_status"):
        assert f'"type":"{v}"' in flat, f"{v} undocumented — the verb doesn't exist"
    assert "ACTIVE MISSIONS" in src, "open missions must reach the context"


def test_active_missions_render_into_the_context_block():
    ctx = {
        "business": _BIZ, "contacts_total": 0, "contacts_by_status": {},
        "avg_health": 0, "at_risk": [], "queue": [], "sessions": [],
        "insights": [], "modules": [], "events": [], "memories": [],
        "notifications": [], "recent_queue_24h": [], "projects": [],
        "products": [], "contacts_lookup": [], "open_invoices": [],
        "site": None, "strategy_track": None, "business_track": None,
        "email_replies": [], "sms_messages": [],
        "open_missions": [{
            "id": "m-1", "title": "Collect the invoices",
            "status": "awaiting_approval", "current_step": 1,
            "steps": [{"title": "draft", "status": "done"},
                      {"title": "send the reminders", "status": "awaiting"}],
        }],
    }
    block = cos._format_context_for_prompt(ctx)
    assert "Collect the invoices" in block
    assert "WAITING ON THE PRACTITIONER: 'send the reminders'" in block


def test_mission_verbs_are_registered_and_classified():
    import action_registry as ar
    assert ar.effect("mission_status") == ar.READ
    assert ar.reversibility("start_mission") == "C"
    assert ar.reversibility("advance_mission") == "C"
    assert ar.reversibility("propose_mission") == "A"
    assert ar.reversibility("abandon_mission") == "A"
