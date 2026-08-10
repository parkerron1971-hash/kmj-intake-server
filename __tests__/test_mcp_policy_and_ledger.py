"""The agent surface answers to the policy engine and appears in the ledger.

Two gaps, both invisible from outside.

The MCP surface authorised itself from the action registry alone —
may_expose_to_agent() — and never consulted policy_engine.evaluate(),
the thing that decides whether an action is allowed for THIS business,
unprompted, right now. Every exposed verb is a read today so the verdict
is always allow; the gate goes in before it matters, on the same
argument the scope check two functions up already makes about itself:
"a system that is only wired up when it starts mattering is one that
gets wired up wrong".

And MCP wrote only to agent_runs — its own operational log. The ACTION
LEDGER is the trust artifact: append-only in the database, hash-chained,
anchored on Hedera. An agent could read a practitioner's whole business
and leave no trace in the one place an auditor is told to look.
"Everything Chief does is in the ledger" was true; "everything an AGENT
does is" was not, and nothing in the ledger said so.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import mcp_server

SRC = inspect.getsource(mcp_server._call_tool)


class TestThePolicyEngineIsConsulted:
    def test_evaluate_is_called_on_this_surface(self):
        assert "policy_engine.evaluate(" in SRC

    def test_it_declares_the_agent_surface(self):
        assert 'surface="agent"' in SRC

    def test_it_is_never_marked_prompted(self):
        """prompted=True is the exemption the engine grants a human who
        asked for THIS action, now. Nobody is sitting in front of an MCP
        call — a token is. Passing True would hand the agent surface the
        one exemption it must never have."""
        assert "prompted=False" in SRC
        assert "prompted=True" not in SRC

    def test_a_denial_is_returned_as_not_allowed(self):
        assert "if not verdict.allowed:" in SRC

    def test_an_unavailable_policy_fails_CLOSED(self):
        """An authorisation check that cannot run is not permission to
        proceed — the posture the engine itself takes on registry drift.
        The dangerous version of this except-block returns True."""
        i = SRC.index("policy evaluation failed")
        after = SRC[i:i + 400]
        assert "return False, False" in after, (
            "a policy failure must refuse, not fall through to the handler")

    def test_the_check_runs_before_the_handler(self):
        assert SRC.index("policy_engine.evaluate(") < SRC.index("await handler(")


class TestTheLedgerSeesTheAgent:
    LED = inspect.getsource(mcp_server._ledger)

    def test_it_writes_the_action_ledger_not_only_agent_runs(self):
        assert "audit_log.record(" in self.LED

    def test_it_uses_the_tables_own_actor_vocabulary(self):
        """actor_type has a CHECK constraint allowing only
        user/chief/agent/system. A row that violates it is rejected and
        the trace is lost silently."""
        assert 'actor_type="agent"' in self.LED

    def test_authorized_by_carries_the_POLICY_REASON(self):
        """The spec's sixth field is which rule permitted the action, not
        who ran it — the caller is already in actor_id."""
        assert "authorized_by=reason" in self.LED

    def test_refusals_are_recorded_too(self):
        """The refused calls are the rows worth reading. A ledger that
        only holds successes describes a system that never says no."""
        assert SRC.count("_ledger(") >= 3
        assert "allowed=False" in SRC

    def test_a_handler_failure_is_recorded_before_it_propagates(self):
        i = SRC.index("except Exception as e:", SRC.index("await handler("))
        assert "_ledger(" in SRC[i:i + 300]
        assert "raise" in SRC[i:i + 400], "the error must still reach the caller"

    def test_the_ledger_write_can_never_take_down_the_surface(self):
        assert "except Exception" in self.LED
        assert "non-fatal" in self.LED


class TestItDidNotLoseWhatWasThere:
    def test_agent_runs_is_still_written(self):
        """The operational log keeps arg names, duration and scope — the
        ledger is an addition, not a replacement."""
        assert "agent_runs" in inspect.getsource(mcp_server._audit)

    def test_the_registry_check_still_guards_the_surface(self):
        assert "may_expose_to_agent" in SRC
