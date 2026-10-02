"""Opt-in real-model weather routing/proof check; fictional business, no write tools.

Provider calls retain normal metering. Only public NWS weather is retrieved.
Run with configured provider credentials: python scripts/chief_weather_eval.py --live
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chief_models
import chief_of_staff as chief
import chief_tool_loop as loop
import chief_truth as truth
import chief_weather as weather


async def main():
    ctx = {key: [] for key in ('queue', 'events', 'sessions', 'insights', 'modules', 'at_risk', 'contacts_lookup')}
    ctx.update(business={'name': 'Example Studio'}, module_counts={}, contacts_total=0, contacts_by_status={}, avg_health=None)
    system = chief._build_system_prompt(ctx, False) + chief_models.VOICE_DELIVERY_BLOCK + truth.AUTHOR_RULES
    cases = [
        ('direct', [{'role': 'user', 'content': 'Can you check the weather in Muskegon, Michigan?'}]),
        ('retry', [{'role': 'user', 'content': 'Can you check the weather in Muskegon, Michigan?'},
                   {'role': 'assistant', 'content': 'That search result was from yesterday. Would you like me to try again?'},
                   {'role': 'user', 'content': 'yes'}]),
    ]
    async with httpx.AsyncClient(timeout=90) as client:
        for name, messages in cases:
            token = truth.begin('fictional-owner', messages[-1]['content'])
            loop.reset_turn()
            started = time.perf_counter()
            try:
                draft = await chief._call_claude(client, system, messages,
                    model=chief_models.model_for('voice'), effort=chief_models.effort_for('voice'),
                    max_tokens=chief_models.max_tokens_for('voice'), enable_web_search=True,
                    read_tools=[weather.TOOL], tool_biz={})
                actions, answer = chief._extract_actions_and_clean(draft)
                assert not actions, 'Weather must not propose business writes'
                sources = truth.evidence_for_review(ctx, '', [])
                assert 'tool:get_weather' in sources, 'Model failed to use direct weather read'
                assert not any(s.startswith('web:') for s in sources), 'Model used generic web search'
                print(json.dumps({'case': name, 'draft': answer}), flush=True)
                async def inspect_review(*args, **kwargs):
                    raw = await truth.review_reply(*args, **kwargs)
                    print(json.dumps({'case': name, 'review': raw}), flush=True)
                    return raw
                answer, meta = await truth.finalize_reply(client, answer, ctx=ctx, view_detail='', taken=[],
                    message=messages[-1]['content'], business_id=None, reviewer=inspect_review)
                print(json.dumps({'case': name, 'elapsed_ms': round((time.perf_counter()-started)*1000),
                    'answer': answer, 'grounding': meta, 'weather': json.loads(sources['tool:get_weather']['text'])}), flush=True)
                assert meta['status'] in ('supported', 'trimmed'), 'Weather answer was withheld'
                current = json.loads(sources['tool:get_weather']['text']).get('current')
                if current:
                    local_clock = current['observed_local'].split()[0].lstrip('0')
                    assert local_clock in answer, 'Verified observation/time disappeared from final answer'
                assert 'try again' not in answer.lower() and 'no action ran' not in answer.lower()
            finally:
                truth.end(token)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    if not parser.parse_args().live:
        parser.error('--live required: real provider calls are metered')
    asyncio.run(main())
