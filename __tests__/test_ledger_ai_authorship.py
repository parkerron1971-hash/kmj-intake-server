"""The ledger records WHICH machine decided, not just that one did.

audit_log answers "who did what, when, and did it work". actor_type
tells an auditor a machine acted — 37 of the first 61 rows are
actor_type='chief' — but nothing recorded which model produced the
decision.

"An AI did it" is not a provenance claim. "claude-sonnet-5 did it, on
this date" is. By the time a practitioner disputes an action, the model
that made it will have been superseded twice, and the ledger is the only
place that could still say which one it was.

The distinction these tests protect hardest is NULL. NULL means NOT
RECORDED. It does not mean "no machine was involved" — that is
actor_type's job, and an audit trail that conflates the two has started
telling comfortable stories.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import audit_log
import authorship


@pytest.fixture(autouse=True)
def _clean():
    token = authorship._MODEL.set(None)
    yield
    authorship._MODEL.reset(token)


@pytest.fixture
def captured(monkeypatch):
    rows = []
    monkeypatch.setattr(audit_log.sb_clients, "sb_post_as_service",
                        lambda path, row, **kw: rows.append(row) or [{"id": "x"}])
    return rows


class TestTheContext:
    def test_starts_unrecorded(self):
        assert authorship.current_model() is None

    def test_set_and_read(self):
        authorship.set_model("claude-sonnet-5")
        assert authorship.current_model() == "claude-sonnet-5"

    def test_authored_by_restores_the_previous_model(self):
        """A scheduled job looping over tenants must not leak one turn's
        model into the next row it writes."""
        authorship.set_model("model-a")
        with authorship.authored_by("model-b"):
            assert authorship.current_model() == "model-b"
        assert authorship.current_model() == "model-a"

    def test_it_restores_even_when_the_body_raises(self):
        authorship.set_model("model-a")
        with pytest.raises(ValueError):
            with authorship.authored_by("model-b"):
                raise ValueError("boom")
        assert authorship.current_model() == "model-a"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_an_empty_model_does_not_overwrite(self, empty):
        """Human actions and scheduled jobs involve no model. They must
        stay NULL rather than inherit whichever model last ran."""
        authorship.set_model("model-a")
        authorship.set_model(empty)
        assert authorship.current_model() == "model-a"
        with authorship.authored_by(empty):
            assert authorship.current_model() == "model-a"


class TestTheLedgerStampsIt:
    def test_a_row_written_under_a_model_names_it(self, captured):
        authorship.set_model("claude-sonnet-5")
        audit_log.record(business_id="b1", verb="send_sms", actor_type="chief")
        assert captured, "no ledger row was written"
        assert captured[0]["ai_model"] == "claude-sonnet-5"

    def test_a_row_with_no_model_stays_null(self, captured):
        """NOT RECORDED, not invented. A human clicking a button must not
        acquire a model because one ran earlier in the process."""
        audit_log.record(business_id="b1", verb="update_contact",
                         actor_type="user", actor_id="u1")
        assert captured[0]["ai_model"] is None

    def test_authorship_is_independent_of_actor_type(self, captured):
        """The two answer different questions: actor_type is WHETHER a
        machine acted, ai_model is WHICH. A test that assumed one implies
        the other would hide exactly the case an auditor cares about."""
        authorship.set_model("claude-opus-4-8")
        audit_log.record(business_id="b1", verb="run_sweep", actor_type="system",
                         actor_id="scheduler")
        assert captured[0]["actor_type"] == "system"
        assert captured[0]["ai_model"] == "claude-opus-4-8"


class TestChiefDeclaresTheModelItUsed:
    def test_it_stamps_the_model_actually_selected(self):
        """Set after the ladder resolves `model`, not from the requested
        one. A row stamped with the model we asked for rather than the
        one that answered is a plausible-looking lie."""
        import inspect

        import chief_of_staff
        src = inspect.getsource(chief_of_staff._call_claude)
        assert "authorship.set_model(model)" in src
        # ...and after `model` has been resolved, not before.
        assert src.index("authorship.set_model(model)") > src.index("def _call_claude")

    def test_the_ledger_reads_it_rather_than_being_passed_it(self):
        """The point of the contextvar: a writer several frames away from
        the model choice does not have to be given it, so a new writer
        cannot forget to."""
        import inspect
        src = inspect.getsource(audit_log)
        assert "authorship.current_model()" in src
