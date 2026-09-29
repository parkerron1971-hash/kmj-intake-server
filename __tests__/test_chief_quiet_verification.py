import asyncio
import json
from unittest.mock import AsyncMock
import chief_truth as truth


def test_cold_leads_warning_removes_claim_not_just_the_warning():
    draft = 'There are 725 contacts. Four leads have gone cold for sixty-plus days with no outreach.'
    raw = json.dumps({'verdict':'unsupported','claims':[
        {'text':'There are 725 contacts.','kind':'fact','source_id':'context:contacts_total','quote':'725'},
        {'text':'Four leads have gone cold for sixty-plus days with no outreach.','kind':'fact',
         'source_id':'','quote':'','gap':'No outreach history supports this claim'}]})
    reviewer=AsyncMock(return_value=raw)
    answer,meta=asyncio.run(truth.finalize_reply(None,draft,ctx={'contacts_total':725},
        view_detail={},taken=[],message='Give me an update',business_id='biz',reviewer=reviewer))
    assert answer == 'There are 725 contacts.'
    assert meta['gaps'] and meta['status']=='trimmed'
    reviewer.assert_awaited_once()  # cleanup adds no model latency


def test_real_uncertainty_is_not_hidden_when_nothing_can_be_verified():
    draft='Four leads have gone cold for sixty-plus days with no outreach.'
    raw=json.dumps({'verdict':'unsupported','claims':[
        {'text':draft,'kind':'fact','source_id':'','quote':'','gap':'No activity history'}]})
    answer,meta=asyncio.run(truth.finalize_reply(None,draft,ctx={},view_detail={},taken=[],
        message='Which leads need attention?',business_id='biz',reviewer=AsyncMock(return_value=raw)))
    assert 'Four leads' not in answer and 'still unverified' not in answer
    assert meta['status']=='withheld' and "couldn't verify" in answer
