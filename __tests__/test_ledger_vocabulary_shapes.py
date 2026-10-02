"""The ledger vocabulary reaches action_types, every boot.

PostgREST rejects a bulk insert whose rows carry different keys (PGRST102
"All object keys must match"). The vocabulary mixes three row shapes, so
one bulk upsert lost every verb on every boot (Sentry PYTHON-FASTAPI-1).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import audit_log
import sb_clients


def test_the_vocabulary_really_has_several_shapes():
    """The premise: if this ever becomes one shape, the split is moot."""
    shapes = {tuple(sorted(r)) for r in audit_log.vocabulary().values()}
    assert len(shapes) > 1


def test_every_request_is_uniform_and_every_verb_is_sent(monkeypatch):
    sent = []

    def fake_post(path, rows, prefer=None):
        assert len({tuple(sorted(r)) for r in rows}) == 1, "PGRST102: keys must match"
        sent.extend(rows)
        return [{"verb": r["verb"]} for r in rows]

    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake_post)
    published = audit_log.sync_action_types()
    vocab = audit_log.vocabulary()
    assert published == len(vocab)
    assert sorted(r["verb"] for r in sent) == sorted(vocab)


def test_one_shape_failing_reports_only_what_landed(monkeypatch):
    calls = {"n": 0}

    def fake_post(path, rows, prefer=None):
        calls["n"] += 1
        return None if calls["n"] == 1 else [{"verb": r["verb"]} for r in rows]

    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake_post)
    published = audit_log.sync_action_types()
    assert 0 < published < len(audit_log.vocabulary())
