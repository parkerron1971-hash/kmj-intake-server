"""L4 — the portal agent. A GUIDE, never a NARRATOR.

Someone opens the ledger because they think something went wrong. They
don't know a verb name or a sequence number; they know "the invoices for
that client last July". This turns that into a FILTER over real rows.

The rule that cannot bend: it finds and filters, and never interprets,
summarises, or stands between the reader and the record. These tests
exist because that rule is the product — the moment the thing says
"here's what happened, trust me", the ledger stops being a proof.
"""
from __future__ import annotations

import sys
import pathlib
from datetime import datetime, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import ledger_navigator as ln  # noqa: E402


# ─── It resolves language into a filter ──────────────────────────────

def test_dates_resolve_without_a_model():
    """"Last 7 days" has one meaning and it is not worth a token or a
    hallucination."""
    f = ln.resolve("what failed in the last 7 days", use_model=False)["filter"]
    assert f["failed_only"] is True
    assert f["since"].endswith("Z")
    d = datetime.strptime(f["since"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert 6 <= (datetime.now(timezone.utc) - d).days <= 8


def test_yesterday_is_a_closed_range():
    f = ln.resolve("what happened yesterday", use_model=False)["filter"]
    assert f["since"] < f["until"]


def test_failure_words_all_land():
    for q in ("what failed", "show me errors", "what didn't work",
              "what broke last week"):
        assert ln.resolve(q, use_model=False)["filter"].get("failed_only") is True


def test_edit_words_reach_the_provable_tier():
    """"Who edited this" must reach the db-trigger rows — that tier is
    the one that proves a direct record change happened."""
    for q in ("who edited records", "was anything deleted", "what changed"):
        assert ln.resolve(q, use_model=False)["filter"].get("include_db") is True


# ─── It never narrates ───────────────────────────────────────────────

def test_the_only_sentence_is_about_the_filter():
    """It may state WHAT FILTER it applied. It may not state what the
    records mean."""
    for q in ("what failed last 7 days", "yesterday", "anything at all",
              "who edited records this month"):
        line = ln.resolve(q, use_model=False)["description"].lower()
        assert line.startswith("showing")
        for banned in ("nothing unusual", "looks fine", "appears", "seems",
                       "probably", "no issues", "everything is", "suggests",
                       "indicates", "concerning", "suspicious"):
            assert banned not in line, f"{banned!r} is interpretation, not a filter"


def test_empty_question_shows_everything_rather_than_guessing():
    """An absent filter shows more records, which is safe. A guessed
    filter HIDES records, which is not."""
    out = ln.resolve("", use_model=False)
    assert out["filter"] == {}
    assert "everything recorded" in out["description"]


def test_the_model_never_receives_row_contents():
    """The structural guarantee: it cannot summarise data it was never
    given. Stronger than asking it not to."""
    src = pathlib.Path(_here.parent / "ledger_navigator.py").read_text(encoding="utf-8")
    body = src.split("def resolve(")[1]
    call = body.split("llm_call.post(")[1].split("}, task=")[0]
    for leak in ("entries", "rows", "audit_log", "payload", "summary("):
        assert leak not in call, f"the navigator must not send {leak} to the model"
    assert "Vocabulary" in call
    assert "question" in call, "the model gets the question and the vocabulary only"


# ─── It refuses to trust the model ───────────────────────────────────

def test_unknown_keys_are_dropped():
    """An unknown key is a hallucinated filter."""
    out = ln._sanitize({"since": "2026-07-01T00:00:00Z", "sql": "DROP TABLE",
                        "business_id": "other-tenant", "nonsense": 1})
    assert set(out) == {"since"}


def test_invented_verbs_are_dropped():
    """A guessed verb hides every row that doesn't match it."""
    assert ln._sanitize({"verb": "definitely_not_a_verb"}) == {}
    assert ln._sanitize({"verb": "create_invoice"})["verb"] == "create_invoice"
    # Namespaced ledger verbs are legitimate.
    assert ln._sanitize({"verb": "db:invoices_update"})["verb"] == "db:invoices_update"


def test_subject_id_is_stripped_of_injection():
    out = ln._sanitize({"subject_id": "abc-123'; DROP TABLE audit_log;--"})
    # Underscores go too — ledger subject ids are uuids (hex + hyphens),
    # so the narrow allowlist costs nothing and leaves no escape hatch.
    assert out["subject_id"] == "abc-123DROPTABLEauditlog--"
    assert "'" not in out["subject_id"] and " " not in out["subject_id"]


def test_limit_is_bounded():
    assert ln._sanitize({"limit": 99999})["limit"] == 500
    assert ln._sanitize({"limit": -5})["limit"] == 1
    assert ln._sanitize({"limit": "junk"}) == {}


def test_actor_must_be_a_known_actor():
    assert ln._sanitize({"actor": "chief"})["actor"] == "chief"
    assert ln._sanitize({"actor": "root"}) == {}


def test_deterministic_dates_win_over_the_model(monkeypatch):
    """A resolved date range is not a matter of opinion, so the model
    cannot overwrite one."""
    class _R:
        status_code = 200
        def json(self):
            return {"content": [{"type": "text",
                                 "text": '{"since":"1999-01-01T00:00:00Z"}'}]}
    import llm_call
    monkeypatch.setattr(llm_call, "post", lambda *a, **k: _R())
    monkeypatch.setattr(llm_call, "text_of",
                        lambda d: d["content"][0]["text"])
    f = ln.resolve("what happened yesterday", use_model=True)["filter"]
    assert not f["since"].startswith("1999")


def test_model_failure_degrades_to_the_literal_filter(monkeypatch):
    import llm_call

    def _boom(*a, **k):
        raise RuntimeError("anthropic down")
    monkeypatch.setattr(llm_call, "post", _boom)
    out = ln.resolve("what failed yesterday", use_model=True)
    assert out["model_used"] is False
    assert out["filter"]["failed_only"] is True   # the literal layer still works


# ─── The search itself is recorded ───────────────────────────────────

def test_searching_the_ledger_is_written_to_the_ledger():
    """Who went looking for what belongs in the record — especially
    when the reader is an auditor."""
    src = pathlib.Path(_here.parent / "audit_log.py").read_text(encoding="utf-8")
    body = src.split("def navigate(")[1].split("@router.get(\"/export\")")[0]
    assert 'verb="ledger:searched"' in body
    assert "_require_ledger_read(" in body
    # And it returns rows, not prose.
    assert '"entries": entries' in body
