"""Opt-in live evaluation of a conversational pivot, with synthetic records only.

Uses configured models and normal metering. No business reads or action tools.
Run with --live in an environment that already supplies provider credentials.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chief_fast_track as fast
import chief_models
import chief_of_staff as chief
import route_ledger
from chief_conversation import conversation_style
from chief_turn_direction import direction_for

MESSAGE = ("I need to know exactly what is the plan. Well, actually, let's go back to "
           "that vision we were talking about earlier and making the vision and getting "
           "things done with that. Let's try to figure that out.")
HISTORY = [
    {"role": "user", "content": "My vision is to help first-time founders turn one useful idea "
     "into their first paying customer. Coaching is the service; the software supports it. "
     "I want to prove that with a small pilot before expanding."},
    {"role": "assistant", "content": "We settled on one business: coaching helps first-time "
     "founders reach their first paying customer, with software supporting the process. "
     "The next decision is which outcome the small pilot should demonstrate."},
]


async def generate(system, messages, lane):
    out, pieces = {}, []
    rec = route_ledger.RouteRecord(arrived=time.perf_counter())
    async for piece in fast.stream_text(
            system, messages, model=chief_models.model_for(lane), max_tokens=400,
            rec=rec, endpoint='/chief/direction-eval', units=0, business_id=None, out=out):
        pieces.append(piece)
    if out.get('error') or not pieces:
        raise RuntimeError('Synthetic model evaluation failed; no provider response logged')
    return ''.join(pieces).strip()


async def main():
    direction = direction_for(MESSAGE).prompt()
    opening = await generate(conversation_style({}) + '\n' + fast._OPENER_SYSTEM + direction,
                             HISTORY + [{'role': 'user', 'content': fast.opener_request(MESSAGE)}], 'fast')
    holder = fast.OpenerHolder()
    holder.parallel_voice = True
    token = fast.OPENER.set(holder)
    try:
        # Empty snapshot reproduces the parallel race: the main model may
        # begin before Haiku has produced any opening words.
        handoff = fast.continuation_block('')
    finally:
        fast.OPENER.reset(token)
    ctx = {key: [] for key in ('queue', 'events', 'sessions', 'insights', 'modules', 'at_risk', 'contacts_lookup')}
    ctx.update(business={'name': 'Example Studio'}, module_counts={},
               contacts_total=0, contacts_by_status={}, avg_health=None)
    system = chief._build_system_prompt(ctx, False)
    system += ('\nSynthetic records: eight open tasks: invoice follow-up, lead follow-up, '
               'event listing, testimonials, beta review, pricing, weekly review, pilot invitation. '
               'The first four tasks are overdue. Seven old goals need a status update.')
    system += chief_models.VOICE_DELIVERY_BLOCK + direction + handoff
    async with httpx.AsyncClient(timeout=60) as client:
        answer = await chief._call_claude(
            client, system, HISTORY + [{'role': 'user', 'content': MESSAGE}],
            model=chief_models.model_for('voice'), max_tokens=chief_models.max_tokens_for('voice'),
            effort=chief_models.effort_for('voice'), enable_web_search=False,
            read_tools=None, stable_tools=False)
    print(json.dumps({'opening': opening, 'answer': answer, 'answer_words': len(answer.split()),
                      'questions': answer.count('?'), 'parallel_empty_snapshot': True}, indent=2))
    assert answer.count('?') <= 1, 'Discussion restarted with a questionnaire'
    assert not any(word in answer.lower() for word in ('overdue', 'seven old goals', 'eight open tasks')), \
        'Abandoned task audit displaced the vision discussion'
    assert 'founder' in answer.lower() and ('paying' in answer.lower() or 'customer' in answer.lower()), \
        'The answer did not resume the supplied vision'
    assert "here's the plan" not in answer.lower(), 'Main answer restarted the introduction'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Authorize the small synthetic model calls')
    if not parser.parse_args().live:
        parser.error('--live is required; this evaluation calls the configured providers')
    asyncio.run(main())
