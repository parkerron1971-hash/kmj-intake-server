"""Real invoice handler results survive narration rejection without invented writes."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import chief_of_staff as chief
import chief_truth as truth
from chief_invoice_readout import invoice_view_answer, owner_invoice_scope

BIZ = {'id': 'invoice-test', 'owner_id': 'owner', 'settings': {}}
ROWS = [
    {'id': 'i1', 'invoice_number': 'TEST-1', 'total': 40, 'status': 'sent', 'due_date': '2020-01-01'},
    {'id': 'i2', 'invoice_number': 'TEST-2', 'total': 60, 'status': 'paid', 'due_date': '2020-01-01'},
    {'id': 'i3', 'invoice_number': 'TEST-3', 'total': 25, 'status': 'draft', 'due_date': '2020-01-01'},
]


def view(monkeypatch, rows=None, **action):
    db = AsyncMock(return_value=deepcopy(ROWS if rows is None else rows))
    monkeypatch.setattr(chief, '_sb', db)
    result = asyncio.run(chief.handle_show_view(None, BIZ,
        {'type': 'show_view', 'view': 'invoices', 'filter': 'all', 'form': 'chart', **action}))
    return result, db


def finalize(receipt, draft, raw):
    reviewer = AsyncMock(return_value=raw)
    result = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail='', taken=[receipt],
        message='Pull up all my invoices as a visual so I can see where things stand.',
        business_id=BIZ['id'], reviewer=reviewer))
    return result, reviewer


def test_rejected_invoice_narration_recovers_real_status_totals(monkeypatch):
    receipt, db = view(monkeypatch)
    result, reviewer = finalize(receipt, 'The invoices total $999.',
        json.dumps({'verdict': 'unsupported', 'claims': []}))
    answer, meta = result
    assert '$125.00' in answer and '$999' not in answer
    assert '1 sent: $40.00' in answer and '1 paid: $60.00' in answer and '1 draft: $25.00' in answer
    assert 'invoices shown' in answer and 'could not verify' not in answer
    assert meta == {'status': 'records', 'sources': ['result:0']}
    assert db.await_count == 1 and reviewer.await_count == 1
    assert receipt['form'] == 'chart' and len(receipt['series']) == 3


def test_visual_completion_claim_is_supported_without_write_authority(monkeypatch):
    receipt, _ = view(monkeypatch)
    sources = truth.evidence_for_review({}, '', [receipt])
    assert sources['result:0']['kind'] == 'receipt'
    assert sources['result:0']['effect'] == 'read'
    assert not truth.wrote_anything(sources)
    draft = 'The view is on your screen now.'
    raw = json.dumps({'verdict': 'supported', 'claims': [
        {'text': draft, 'kind': 'action', 'source_id': 'result:0', 'quote': 'showing 3 invoices'}]})
    assert truth.assess_review(raw, draft, sources)[0] == 'supported'
    (answer, meta), _ = finalize(receipt, draft, raw)
    assert answer == draft and meta['status'] == 'supported'


@pytest.mark.parametrize('claim', ["I sent the invoices.", "I paid your invoices.",
    "I opened the view and sent the invoices.", "I opened a bank account.",
    "The view is on your screen now and payments were processed."])
def test_display_receipt_cannot_clear_write_claim(monkeypatch, claim):
    receipt, _ = view(monkeypatch)
    raw = json.dumps({'verdict': 'supported', 'claims': [
        {'text': claim, 'kind': 'action', 'source_id': 'result:0', 'quote': 'showing 3 invoices'}]})
    assert truth.assess_review(raw, claim, truth.evidence_for_review({}, '', [receipt]))[0] == 'unsupported'


def test_paid_and_draft_past_due_dates_are_not_narrated_overdue(monkeypatch):
    receipt, _ = view(monkeypatch)
    parts = receipt['speak'].split('; ')
    assert 'overdue' in parts[0]
    assert 'overdue' not in parts[1] and 'overdue' not in parts[2]


def test_capped_view_never_claims_whole_business_balance(monkeypatch):
    receipt, _ = view(monkeypatch, rows=[ROWS[0]] * 25)
    answer = invoice_view_answer([receipt])
    assert receipt['limit_reached'] is True
    assert 'capped at 25 rows' in receipt['result']
    assert not truth.evidence_for_review({}, '', [receipt])['result:0']['complete']
    assert 'capped at 25' in answer and 'only the invoices shown' in answer
    assert 'all your invoices' not in answer


def test_empty_view_is_empty_but_refused_read_is_not(monkeypatch):
    empty, _ = view(monkeypatch, rows=[])
    assert invoice_view_answer([empty]) == 'No invoices match this view.'
    monkeypatch.setattr(chief, '_sb', AsyncMock(return_value=None))
    failed = asyncio.run(chief.handle_show_view(None, BIZ, {'view': 'invoices'}))
    assert failed['failed'] and invoice_view_answer([failed]) is None


@pytest.mark.parametrize('change', [{'rows': None}, {'rows': [{'amount': 'NaN', 'status': 'paid'}]},
    {'rows': [{'amount': 4, 'status': 'unknown'}]}, {'failed': True}, {'needs_confirmation': True}])
def test_invalid_or_held_payload_has_no_invoice_recovery(monkeypatch, change):
    receipt, _ = view(monkeypatch)
    assert invoice_view_answer([{**receipt, **change}]) is None


def test_model_label_and_summary_cannot_invent_recovered_figures(monkeypatch):
    receipt, _ = view(monkeypatch)
    receipt.update(label='All invoices paid: $9,999', summary={'total': 9999}, result='Everything paid')
    answer = invoice_view_answer([receipt])
    assert '$125.00' in answer and '9,999' not in answer and '1 sent' in answer
    assert invoice_view_answer([receipt, {'type': 'send_invoice'}]) is None


@pytest.mark.parametrize('text', ['Show all invoices', 'Pull up all the invoices that I have, as a visual.',
    'Show every invoice', 'List all of my invoices', 'Open all invoices', 'Open all my invoices as a chart'])
def test_explicit_all_scope_corrects_model_open_default(text):
    action = {'type': 'show_view', 'view': 'invoices', 'filter': 'open'}
    assert owner_invoice_scope(action, text)['filter'] == 'all'
    assert action['filter'] == 'open'


@pytest.mark.parametrize('text', ['Show all open invoices', 'Show all invoices that are overdue',
    "Do not show all invoices", 'Show all invoices except paid', 'Show all invoices, only drafts'])
def test_qualified_or_negated_scope_is_not_broadened(text):
    action = {'type': 'show_view', 'view': 'invoices', 'filter': 'open'}
    assert owner_invoice_scope(action, text) == action


def test_owner_all_scope_reaches_real_handler_through_action_door(monkeypatch):
    import policy_engine
    monkeypatch.setattr(policy_engine, 'evaluate', lambda *a, **kw: SimpleNamespace(allowed=True, rule='owner'))
    monkeypatch.setattr(chief, '_record_undoable', AsyncMock())
    db = AsyncMock(return_value=deepcopy(ROWS))
    monkeypatch.setattr(chief, '_sb', db)
    receipts = asyncio.run(chief._execute_actions(None, BIZ,
        [{'type': 'show_view', 'view': 'invoices', 'filter': 'open', 'form': 'chart'}],
        user_id='owner', owner_text='Pull up all invoices as a visual.'))
    assert receipts[0]['filter'] == 'all'
    query = db.await_args.args[2]
    assert 'business_id=eq.invoice-test' in query and 'status=neq.void' in query
    assert 'status=in.(sent,viewed,overdue)' not in query


def test_generic_read_fallback_does_not_claim_nothing_ran_or_results_are_visible(monkeypatch):
    monkeypatch.setenv('CHIEF_REVIEW_FAST_LANE', 'off')
    receipt = {'type': 'search_ledger', 'result': 'No matching ledger entries', 'label': 'Search'}
    import action_registry
    assert action_registry.effect('search_ledger') == action_registry.READ
    (answer, meta), _ = finalize(receipt, 'I found the ledger entry.',
        json.dumps({'verdict': 'unsupported', 'claims': []}))
    assert 'lookup ran' in answer and 'No action ran' not in answer and 'results shown' not in answer
    assert meta['status'] == 'withheld'


@pytest.mark.parametrize("qualifier", ["that are sent", "with an outstanding balance", "from last month", "for Jordan", "that are viewed"])
def test_qualified_all_request_preserves_selected_scope(qualifier):
    action = {"type": "show_view", "view": "invoices", "filter": "open"}
    assert owner_invoice_scope(action, "Show all invoices " + qualifier) == action

def test_conversational_all_visual_request():
    action = {"type": "show_view", "view": "invoices", "filter": "open"}
    text = "Can you do me a favor? I want you to pull up all the invoices to show me a visual of the invoices, so that way I can get an idea exactly where things are standing."
    assert owner_invoice_scope(action, text)["filter"] == "all"


@pytest.mark.parametrize("prefix", ["For Jordan, ", "For last month, ", "For sent status, ", "Without the settled ones, "])
def test_qualified_prefix_preserves_invoice_scope(prefix):
    action = {"type": "show_view", "view": "invoices", "filter": "open"}
    assert owner_invoice_scope(action, prefix + "show all invoices.") == action
