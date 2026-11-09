"""church_history: Chief's church hand-offs on the History page.

History is the audit log, and any active seat reads it, so a line names
the leader and the kind of card and never who it's about. Each module's
own tests check its lines (test_church_follow_up, test_church_prayer,
test_church_shepherding, test_church_shepherd_signals); this checks the
helper itself."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import audit_log  # noqa: E402
import church_history  # noqa: E402


def test_every_church_verb_is_in_historys_vocabulary_and_no_other():
    v = audit_log.vocabulary()
    assert {k for k in v if k.startswith("church:")} == set(church_history.VERBS)
    assert all(v[k]["namespace"] == "church" for k in church_history.VERBS)


def test_a_card_is_named_once():
    assert church_history.card_words("Connect card") == "a Connect card"
    assert church_history.card_words("Plan your visit") == "a Plan your visit card"
    assert church_history.card_words("  ") == "a card"


def test_a_line_is_chiefs_and_a_failure_never_raises(monkeypatch):
    seen = []
    monkeypatch.setattr(audit_log, "record", lambda biz, **kw: seen.append((biz, kw)) or True)
    assert church_history.note("b1", "church:card_handed", "Handed a Connect card to Tasha Williams",
                               target_type="church_follow_up", target_id="f1")
    biz, kw = seen[0]
    assert biz == "b1" and kw["actor_type"] == "chief" and kw["actor_id"] == "church"
    assert kw["verb"] == "church:card_handed" and kw["target_id"] == "f1" and kw["source"] == "church"

    def down(*a, **k):
        raise RuntimeError("ledger down")
    monkeypatch.setattr(audit_log, "record", down)
    assert church_history.note("b1", "church:card_handed", "x") is False
