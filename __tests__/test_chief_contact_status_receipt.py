import asyncio
from unittest.mock import AsyncMock
import pytest
import chief_of_staff as chief


@pytest.mark.parametrize('saved', [None, [], {}, [{'id':'contact','status':'lead'}], [{'id':'other','status':'inactive'}]])
def test_unconfirmed_contact_write_cannot_claim_success_or_emit_event(monkeypatch, saved):
    monkeypatch.setattr(chief, '_validate_contact', AsyncMock(return_value={'id':'contact','name':'Example','status':'lead'}))
    sb=AsyncMock(return_value=saved)
    monkeypatch.setattr(chief, '_sb', sb)
    result=asyncio.run(chief.handle_update_contact_status(None, {'id':'business'}, {'contact_id':'contact','new_status':'inactive'}))
    assert result['failed'] is True
    assert 'could not be confirmed' in result['result']
    assert sb.await_count == 1
    assert 'business_id=eq.business' in sb.await_args.args[2]


def test_confirmed_contact_change_records_event_and_receipt(monkeypatch):
    monkeypatch.setattr(chief, '_validate_contact', AsyncMock(return_value={'id':'contact','name':'Example','status':'lead'}))
    sb=AsyncMock(side_effect=[[{'id':'contact','status':'inactive'}], [{'id':'event'}]])
    monkeypatch.setattr(chief, '_sb', sb)
    result=asyncio.run(chief.handle_update_contact_status(None, {'id':'business'}, {'contact_id':'contact','new_status':'inactive'}))
    assert result['result'] == 'lead → inactive'
    assert sb.await_count == 2
    assert sb.await_args.args[3]['data'] == {'from':'lead','to':'inactive'}


def test_already_correct_status_needs_no_write(monkeypatch):
    monkeypatch.setattr(chief, '_validate_contact', AsyncMock(return_value={'id':'contact','name':'Example','status':'inactive'}))
    sb=AsyncMock(); monkeypatch.setattr(chief, '_sb', sb)
    result=asyncio.run(chief.handle_update_contact_status(None, {'id':'business'}, {'contact_id':'contact','new_status':'inactive'}))
    assert result['result'] == 'already inactive'
    sb.assert_not_awaited()
