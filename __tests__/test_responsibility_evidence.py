"""Paged work reports must give the reviewer every page the author read."""
import asyncio
import copy
import json

import chief_of_staff as chief
import chief_responsibilities as reports
import chief_tool_loop as loop
import chief_truth as truth
import pytest


BIZ = {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'owner_id': 'owner'}


@pytest.fixture
def report(monkeypatch):
    items = [reports.normalize('approvals', {
        'id': f'draft-{n}', 'subject': f'Client follow-up {n}',
        'status': 'draft', 'created_at': '2026-10-03T12:00:00Z'}) for n in range(11)]
    items.append(reports.normalize('jobs', {
        'id': 'site', 'kind': 'rebuild_site', 'status': 'failed',
        'result': {'summary_label': 'Drafting bespoke sections (3 of 3).'}}))
    data = {'items': items, 'needs_you': 12, 'partial': False,
            'sources': {s: {'available': True, 'limited': False}
                        for s in ('approvals', 'jobs', 'missions')}, 'errors': []}

    async def snapshot(_):
        return copy.deepcopy(data)

    monkeypatch.setattr(reports, 'snapshot', snapshot)
    monkeypatch.setitem(chief.ACTION_HANDLERS, 'responsibility_status', reports.handle_responsibility_status)
    return data


def review(reply, sid, quote, sources):
    return truth.assess_review(json.dumps({'verdict': 'supported', 'claims': [
        {'text': reply, 'kind': 'fact', 'source_id': sid, 'quote': quote}]}), reply, sources)[0]


def test_six_report_reads_preserve_earlier_evidence_and_exact_counts(report):
    async def scenario():
        token = truth.begin('owner', 'What are you handling?')
        loop.reset_turn()
        try:
            pages = []
            for args in ({}, {'offset': 6}, {'source': 'jobs'},
                         {'source': 'approvals'}, {'source': 'approvals', 'offset': 6},
                         {'source': 'missions'}):
                failed, text = await loop.execute_tool_use(None, BIZ, 'responsibility_status', args)
                assert not failed
                assert len(text) <= loop.MAX_RESULT_CHARS
                pages.append(json.loads(text)['responsibilities'])
            # Force the real production evidence budget to compete with large
            # unrelated business context, as it did for the KMJ report.
            sources = truth.evidence_for_review({k: 'x' * 10000 for k in
                ('blueprint_block', 'brand_block', 'playbook_block', 'voice_block', 'foundation_block')}, {}, [])
            assert pages[0]['page_count'] == 6
            assert pages[0]['total_found'] == 12
            assert pages[0]['source_counts']['approvals']['found'] == 11
            sid = 'tool:responsibility_status:all:0'
            assert review('There are 11 approval drafts.', sid, '"approvals": {"found": 11', sources) == 'supported'
            assert review('Client follow-up 0 is waiting for your decision.', sid,
                          'Client follow-up 0', sources) == 'supported'
            assert review('Site rebuild last reported Drafting bespoke sections (3 of 3).',
                          'tool:responsibility_status:jobs:0',
                          'Drafting bespoke sections (3 of 3).', sources) == 'supported'
            assert review('There are 99 approval drafts.', sid,
                          '"approvals": {"found": 11', sources) == 'unsupported'
            assert not truth.wrote_anything(sources)
            assert sum(len(s['text']) for s in sources.values()) <= truth.MAX_EVIDENCE_CHARS
        finally:
            truth.end(token)
            loop.reset_turn()
        token = truth.begin('owner', 'A new turn')
        try:
            assert not truth.evidence_for_review({}, {}, [])
        finally:
            truth.end(token)
    asyncio.run(scenario())


def test_failed_later_page_does_not_erase_a_successful_page(report, monkeypatch):
    original = reports.handle_responsibility_status

    async def handler(client, biz, action):
        if action.get('offset') == 6:
            raise RuntimeError('page unavailable')
        return await original(client, biz, action)

    monkeypatch.setitem(chief.ACTION_HANDLERS, 'responsibility_status', handler)

    async def scenario():
        token = truth.begin('owner', 'What are you handling?')
        loop.reset_turn()
        try:
            assert not (await loop.execute_tool_use(None, BIZ, 'responsibility_status', {}))[0]
            assert (await loop.execute_tool_use(None, BIZ, 'responsibility_status', {'offset': 6}))[0]
            sources = truth.evidence_for_review({}, {}, [])
            assert 'Client follow-up 0' in sources['tool:responsibility_status:all:0']['text']
            assert 'tool:responsibility_status:all:6' not in sources
            assert 'tool:responsibility_status:all:6' in truth.unavailable_sources()
        finally:
            truth.end(token)
            loop.reset_turn()
    asyncio.run(scenario())
