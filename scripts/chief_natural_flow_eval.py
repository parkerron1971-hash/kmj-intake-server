"""Opt-in business-age/vision evaluation using fictional records, no account reads.

Uses the configured opener and voice models with normal metering. Inspect the
printed replies for warmth, clarity, and fidelity as well as the basic checks.
Run with --live in an environment supplying provider credentials.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chief_fast_track as fast
import chief_models
import chief_of_staff as chief
import route_ledger
from chief_conversation import conversation_style

MESSAGE = 'How long has my business been in operation, and what is the vision of my business?'
CASES = {
    'missing_start_and_inferred_vision': (
        'The app account was created on July 1, 2026. No operating start date or approved '
        'vision statement is available. Owner notes: help first-time founders reach their '
        'first paying customer through coaching; software supports that practice.'
    ),
    'known_start_and_approved_vision': (
        'The owner confirmed the business began operating on September 30, 2022. '
        'The app account was created on July 1, 2026. Approved vision statement: '
        'Help first-time founders turn a useful idea into their first paying customer.'
    ),
}


async def main():
    pieces, out = [], {}
    async for piece in fast.stream_text(
        conversation_style({}) + '\n' + fast._VOICE_OPENER_SYSTEM,
        [{'role': 'user', 'content': fast.opener_request(MESSAGE, voice=True)}],
        model=chief_models.model_for('opener'), max_tokens=fast.VOICE_OPENER_MAX_TOKENS,
        rec=route_ledger.RouteRecord(arrived=time.perf_counter()),
        endpoint='/chief/natural-flow-eval', units=0, business_id=None, out=out,
    ):
        pieces.append(piece)
    if out.get('error') or not pieces:
        raise RuntimeError('Opener evaluation failed')
    gate = fast.mr.OpenerGate(MESSAGE, max_words=fast.VOICE_OPENER_MAX_WORDS, max_sentences=2)
    opening = gate.feed(''.join(pieces)) + gate.finish()
    print(json.dumps({'opening': opening}, indent=2), flush=True)
    assert opening.strip(), 'The opener gate rejected the opening'

    holder = fast.OpenerHolder()
    holder.parallel_voice = True
    token = fast.OPENER.set(holder)
    try:
        # The main model can start before any opener text is available.
        handoff = fast.continuation_block('')
    finally:
        fast.OPENER.reset(token)
    ctx = {key: [] for key in ('queue', 'events', 'sessions', 'insights', 'modules', 'at_risk', 'contacts_lookup')}
    ctx.update(business={'name': 'Example Studio'}, module_counts={},
               contacts_total=0, contacts_by_status={}, avg_health=None)
    base = chief._build_system_prompt(ctx, False) + chief_models.VOICE_DELIVERY_BLOCK + handoff
    async with httpx.AsyncClient(timeout=60) as client:
        for name, records in CASES.items():
            system = base + '\nEvaluation date: September 30, 2026. Synthetic records: ' + records
            answer = await chief._call_claude(
                client, system, [{'role': 'user', 'content': MESSAGE}],
                model=chief_models.model_for('voice'), max_tokens=chief_models.max_tokens_for('voice'),
                effort=chief_models.effort_for('voice'), enable_web_search=False,
                read_tools=None, stable_tools=False,
            )
            print(json.dumps({'case': name, 'answer': answer}, indent=2), flush=True)
            lowered = answer.lower()
            assert 'founder' in lowered and 'customer' in lowered, 'Vision omitted'
            assert not re.search(r'want me to\?\s*$', lowered), 'Unclear trailing offer'
            assert answer.count('?') <= 1, 'Unnecessary interview'
            if name.startswith('missing'):
                assert not re.search(r'(?:three|3) months', lowered), 'Account age used as business age'
                before_vision = lowered[:lowered.index('founder')]
                assert not re.search(r'\b(?:tell me|if you (?:tell|give))\b', before_vision), \
                    'Missing-date request interrupted the answer'
                assert not re.search(r"\b(?:save|sharpen|rewrite)\b", lowered), 'Unrequested editing offer'
                if '?' in answer:
                    assert lowered.index('customer') < lowered.index('?'), 'Question interrupted the answer'
            else:
                assert re.search(r'(?:four|4) years', lowered), 'Known operating age not answered'
                assert '?' not in answer, 'Known answer replaced by a follow-up'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Run the small synthetic provider evaluation')
    if not parser.parse_args().live:
        parser.error('--live is required; this calls the configured providers')
    asyncio.run(main())
