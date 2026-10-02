"""Changing one clause of a template you own.

business_doc_templates was insert / select / delete — no update path at
any layer. So "add an IP clause to our design agreement" had exactly one
honest answer: recompose the whole thing, which INSERTS a second
near-identical row that then competes with the first in the picker and
in resolve_template.

Sections are already an addressable list of {heading, text}, so add and
remove are list surgery on JSON. NO MODEL CALL, and none is wanted — a
deterministic edit to paper the practitioner owns should not cost a
credit or acquire a failure mode.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import pytest
from fastapi import HTTPException

import action_registry as ar
import chief_contract_actions as cca
import chief_of_staff as cos
import doc_templates as dt
import doc_templates_router as dtr

BIZ = "biz-1"
ROW = "row-9"


class _User:
    id = "owner-1"


def _template():
    return {
        "title": "Design Agreement",
        "subtitle": "Scope & Delivery",
        "description": "A project agreement.",
        "category": "custom",
        "suggested_for": [],
        "numbered": True,
        "fields": [{"key": "scope", "label": "Scope", "type": "textarea",
                    "required": True, "placeholder": "", "default": "",
                    "sticky": False}],
        "sections": [
            {"kind": "fixed", "heading": "THE PROJECT", "text": "{scope}"},
            {"kind": "fixed", "heading": "PAYMENT", "text": "Half up front."},
            {"kind": "fixed", "heading": None,
             "text": "ACCEPTED AND AGREED\n\nBy: ______"},
        ],
    }


@pytest.fixture
def store(monkeypatch):
    state = {"template": _template(), "patched": []}

    monkeypatch.setattr(dtr, "_owner", lambda biz, user: {"id": biz, "type": "creative"})
    monkeypatch.setattr(
        dtr.sb_clients, "sb_get_as_service",
        lambda path: [{"id": ROW, "template": state["template"]}])

    def _patch(path, body):
        state["patched"].append((path, body))
        state["template"] = body["template"]
        return [{"id": ROW}]

    monkeypatch.setattr(dtr.sb_clients, "sb_patch_as_service", _patch)
    return state


async def _adjust(**kw):
    body = dtr.AdjustBody(business_id=BIZ, **kw)
    return await dtr.doctemplates_adjust_custom(ROW, body, _User())


def _headings(state):
    return [s.get("heading") for s in state["template"]["sections"]]


# ── The three operations ─────────────────────────────────────────────

def test_add_puts_the_clause_before_the_signature_block(store):
    import asyncio
    asyncio.run(_adjust(operation="add", heading="OWNERSHIP",
                        text="Rights transfer on payment in full."))
    heads = _headings(store)
    assert "OWNERSHIP" in heads
    # ...and NOT after the signatures, which would put terms below the
    # place the parties signed.
    assert heads.index("OWNERSHIP") < len(heads) - 1


def test_add_after_a_named_clause(store):
    import asyncio
    asyncio.run(_adjust(operation="add", heading="OWNERSHIP",
                        text="Rights transfer on payment.", after="THE PROJECT"))
    heads = _headings(store)
    assert heads.index("OWNERSHIP") == heads.index("THE PROJECT") + 1


def test_remove_takes_the_clause_out(store):
    import asyncio
    asyncio.run(_adjust(operation="remove", heading="PAYMENT"))
    assert "PAYMENT" not in _headings(store)


def test_replace_changes_the_words_not_the_position(store):
    import asyncio
    before = _headings(store)
    asyncio.run(_adjust(operation="replace", heading="PAYMENT",
                        text="Paid in three milestones."))
    assert _headings(store) == before
    txt = [s["text"] for s in store["template"]["sections"]
           if s.get("heading") == "PAYMENT"][0]
    assert "three milestones" in txt


def test_matching_is_case_insensitive(store):
    import asyncio
    asyncio.run(_adjust(operation="remove", heading="payment"))
    assert "PAYMENT" not in _headings(store)


# ── The refusals ─────────────────────────────────────────────────────

def test_the_signature_block_cannot_be_removed(store):
    """Removing it turns an agreement into a memo, silently."""
    import asyncio
    with pytest.raises(HTTPException) as e:
        asyncio.run(_adjust(operation="remove", heading=None or ""))
    assert e.value.status_code == 400  # no heading given

    # and by its real (absent) heading, via the text check
    store["template"]["sections"][2]["heading"] = "SIGNATURES"
    with pytest.raises(HTTPException) as e2:
        asyncio.run(_adjust(operation="remove", heading="SIGNATURES"))
    assert e2.value.status_code == 409
    assert "sign" in str(e2.value.detail).lower()


def test_adding_a_duplicate_heading_is_refused(store):
    """Two clauses with the same heading is how a contract ends up saying
    two different things about one term."""
    import asyncio
    with pytest.raises(HTTPException) as e:
        asyncio.run(_adjust(operation="add", heading="PAYMENT", text="Anything."))
    assert e.value.status_code == 409
    assert "already" in str(e.value.detail)


def test_removing_something_that_is_not_there(store):
    import asyncio
    with pytest.raises(HTTPException) as e:
        asyncio.run(_adjust(operation="remove", heading="NOPE"))
    assert e.value.status_code == 404


def test_add_and_replace_need_the_text(store):
    import asyncio
    for op in ("add", "replace"):
        with pytest.raises(HTTPException) as e:
            asyncio.run(_adjust(operation=op, heading="X"))
        assert e.value.status_code == 400


def test_an_unknown_operation_is_refused(store):
    import asyncio
    with pytest.raises(HTTPException) as e:
        asyncio.run(_adjust(operation="delete_everything", heading="PAYMENT"))
    assert e.value.status_code == 400


# ── The library is not editable in place ─────────────────────────────

def test_chief_refuses_to_edit_a_built_in_and_offers_the_fork(store):
    """TEMPLATE_INDEX is a module-level dict shared by every business, so
    editing one in place would change one practitioner's paper for all
    of them."""
    import asyncio
    out = asyncio.run(cca.handle_adjust_template(
        None, {"id": BIZ, "owner_id": "owner-1"},
        {"template": "engagement_letter", "operation": "add",
         "heading": "X", "text": "y"}))
    assert out["type"] == "adjust_template"
    assert "fork" in str(out).lower() or "own copy" in str(out).lower()


def test_the_fork_flattens_drafted_sections():
    """A business's own template is deterministic paper, matching what
    learn and compose already produce — not a model call waiting."""
    src = dt.TEMPLATE_INDEX["engagement_letter"]
    assert any(s["kind"] == "drafted" for s in src["sections"])
    fn = inspect.getsource(dtr.doctemplates_fork_library)
    assert '"kind": "fixed"' in fn
    assert 'fallback' in fn


# ── Registered in all three places ───────────────────────────────────

def test_the_verb_is_registered_everywhere():
    """Handler, registry AND prompt. A verb missing the third ships
    nothing — the lesson giving_statement taught this codebase."""
    assert "adjust_template" in cos.ACTION_HANDLERS
    assert "adjust_template" in ar.REGISTRY
    src = chief_source()
    assert '"type":"adjust_template"' in src


def test_it_is_class_a_and_says_nothing_client_facing_changes():
    entry = ar.REGISTRY["adjust_template"]
    assert entry["reversibility"] == "A"
    why = entry["why"].lower()
    assert "no document is created" in why
    assert "client-facing" in why


def test_it_makes_no_model_call():
    """Add and remove are list surgery; a reword uses the practitioner's
    own words. Charging a credit for a deterministic edit to their own
    paper would be indefensible."""
    src = inspect.getsource(cca.handle_adjust_template)
    for spend in ("_draft_short", "llm_call", "anthropic", "require_units"):
        assert spend not in src, spend
