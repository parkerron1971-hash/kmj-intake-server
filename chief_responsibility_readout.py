"""Read the work-report shortcut directly from owner-scoped records.

This renders typed statuses and counts, never blesses model-written prose.
General questions and mixed action requests keep the normal Chief pipeline.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from fastapi import HTTPException

SHORTCUT = ('Check all your responsibilities. What are you handling, what needs me, '
            'and when will you check again? Include any work you could not verify.')
SOURCE_NAMES = {'assignments': 'Ongoing responsibilities', 'missions': 'Plans',
                'jobs': 'Background work', 'errands': 'Errands',
                'approvals': 'Approvals', 'events': 'Interrupted follow-ups'}
STATUS_NAMES = {'awaiting_approval': 'awaiting your approval; not sent',
                'failed': 'failed; needs review', 'held': 'on hold',
                'needs_answer': 'waiting for an answer', 'needs_hand': 'needs your help',
                'done_with_gaps': 'finished with gaps', 'needs_review': 'needs review',
                'planned': 'planned', 'paused': 'paused', 'interrupted': 'interrupted',
                'draft': 'draft', 'active': 'active', 'queued': 'queued', 'running': 'running',
                'done': 'marked done', 'completed': 'marked complete',
                'measurement_unavailable': 'progress could not be checked',
                'needs_you': 'needs your attention', 'approved': 'approved'}
DISPLAY_LIMIT = 60


def request_shape(req):
    if getattr(req, 'image_ids', None) or getattr(req, 'mode', None) not in (None, '', 'chief'):
        return False
    text = ' '.join((getattr(req, 'message', '') or '').split()).casefold().rstrip('.?!')
    return text in (SHORTCUT.casefold().rstrip('.?!'), 'what chief is handling')


def _title(value):
    import untrusted_text
    import chief_speech_boundary
    text = ' '.join(str(value or 'Work item').split())[:160]
    if (untrusted_text.detect_injection(text) or untrusted_text.ACTION_TAGLIKE_RE.search(text)
            or chief_speech_boundary.internal_scaffolding(text)):
        return 'Work item (title omitted)'
    # Business titles are literal data, not Markdown links, HTML or directives.
    return re.sub(r'([\\`*_{}\[\]()<>#!|])', r'\\\1', text)


def render(report):
    items = report['items']
    sources = report['sources']
    missing = [SOURCE_NAMES.get(k, 'Work source') for k, v in sources.items() if not v['available']]
    limited = [SOURCE_NAMES.get(k, 'Work source') for k, v in sources.items() if v['limited']]
    if sources and len(missing) == len(sources):
        return "I couldn't read the work report. Unavailable: " + ', '.join(missing) + '. No work was changed.'
    attention = sum(bool(i['needs_you']) for i in items)
    lines = [f'I found {len(items)} work items; {attention} need your attention.']
    if missing:
        lines.append('Could not verify: ' + ', '.join(missing) + '.')
    if limited:
        lines.append('These sources reached their reading limit: ' + ', '.join(limited) + '. Their counts may be incomplete.')
    if report.get('partial'):
        lines.append('This is a partial report; unread work is unknown, not an empty queue.')
    shown = 0
    for needs_you, heading in ((True, 'Needs you'), (False, 'Other recorded work')):
        rows = [i for i in items if bool(i['needs_you']) == needs_you]
        if not rows:
            continue
        lines.append('\n**' + heading + '**')
        for source, name in SOURCE_NAMES.items():
            group = [i for i in rows if i['source'] == source]
            if not group:
                continue
            lines.append(f'\n{name}: {len(group)}')
            for item in group:
                if shown >= DISPLAY_LIMIT:
                    continue
                status = STATUS_NAMES.get(item['status'], 'status needs review')
                lines.append(f"- {_title(item['title'])} — {status}.")
                shown += 1
    if shown < len(items):
        lines.append(f'\n{len(items) - shown} additional read items are not listed here. Ask about a work category for its details.')
    lines.append('\n**Next checks**')
    scheduled = [i for i in items if i.get('next_check_at')]
    if not scheduled:
        lines.append('No next check is recorded for these items. I cannot promise a check time.')
    for item in scheduled[:8]:
        try:
            stamp = datetime.fromisoformat(str(item['next_check_at']).replace('Z', '+00:00'))
            when = (stamp.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                    if stamp.tzinfo else stamp.strftime('%Y-%m-%d %H:%M (time zone not recorded)'))
        except (TypeError, ValueError):
            when = 'recorded time could not be read'
        lines.append(f"- {_title(item['title'])}: {when}.")
    if len(scheduled) > 8:
        lines.append(f'{len(scheduled) - 8} additional recorded check times are not listed here.')
    lines.append('\nThese are recorded statuses, not a fresh verification of completed work. This report did not approve, send, retry or change any work.')
    return '\n'.join(lines)


async def serve_request(client, req, session, biz):
    if not request_shape(req):
        return None
    owner_id = str(getattr(getattr(session, 'user', None), 'id', '') or '')
    if (not isinstance(biz, dict) or not owner_id
            or str(biz.get('id') or '') != str(req.business_id)
            or str(biz.get('owner_id') or '') != owner_id):
        raise HTTPException(403, 'Not authorized for this business.')
    import chief_of_staff as chief
    import chief_stream_replay as replay
    import chief_responsibilities
    recovered = replay.recover(req, owner_id)
    if recovered is None and chief._STREAM_SINK.get() is None:
        recovered = await replay.recover_async(req, owner_id)
    if recovered is not None:
        return recovered
    report = await chief_responsibilities.snapshot(biz['id'])
    answer = render(report)
    result = {'response': answer, 'actions_taken': [],
              'grounding': {'status': 'records', 'sources': ['responsibilities'],
                            'partial': bool(report.get('partial'))}}
    sink = chief._STREAM_SINK.get()
    if sink is not None:
        sink(chief.PROSE_PREFIX + answer)
    await chief._archive_turn(client, biz, req.message, answer, [])
    if sink is not None:
        replay.remember(req, owner_id, result)
    return result
