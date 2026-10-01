"""Opt-in actual-prompt speech timing with fictional records and no action tools.

Compare with --baseline-ref cef010d: only streaming/check/meter functions are
loaded from that revision, while prompts, fixture records and models stay fixed.
Timings begin with context already loaded; this is not production end-to-end SLO.
"""
import argparse
import ast
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chief_fast_track as fast
import chief_models
import chief_of_staff as chief
import chief_truth as truth
from chief_voice_bridge import VoiceBridge
import model_router as mr
import route_ledger


def baseline(ref):
    for module, names in [(chief, ['_SentenceStreamer']),
                          (truth, ['review_stream_prefix']),
                          (__import__('llm_call'), ['apost', '_meter'])]:
        name = Path(module.__file__).name
        code = subprocess.check_output(['git', 'show', f'{ref}:{name}'], text=True, encoding='utf-8')
        tree = ast.parse(code)
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
                exec(compile(ast.Module(body=[node], type_ignores=[]), f'{ref}:{name}', 'exec'), module.__dict__)


def fixture():
    ctx = {key: [] for key in ('queue', 'events', 'sessions', 'insights', 'modules', 'at_risk', 'contacts_lookup')}
    ctx.update(business={'name': 'Example Studio', 'type': 'business coaching'}, module_counts={},
               contacts_total=0, contacts_by_status={}, avg_health=None,
               offerings=[{'name': 'Launch Lab', 'price': 40, 'description': 'Introductory workshop for first-time founders.'}],
               # Representative irrelevant material lets the early reviewer exercise
               # its bounds while the author/final reviewer keep the complete context.
               brand_block='Color palette: navy and cream. Typography: clear headings. ' * 200,
               voice_block='Writing voice favors concise sentences and active verbs. ' * 200,
               blueprint_block='Visual layout uses balanced spacing and generous margins. ' * 200,
               playbook_block='Page composition groups navigation and footer links. ' * 200)
    return ctx


async def run_case(name, message):
    ctx = fixture()
    sources = truth.evidence_for_review(ctx, '', [])
    system = chief._build_system_prompt(ctx, False) + chief_models.VOICE_DELIVERY_BLOCK + truth.AUTHOR_RULES
    # Operational offering rows normally enter the dynamic context tail.
    system += '\nSUPPLIED FICTIONAL RECORDS:\n' + json.dumps(sources, ensure_ascii=False)
    req = SimpleNamespace(message=message, business_id='', conversation_id='synthetic-'+name,
                          client_surface='voice', conversation_history=[], spoken_opener=None)
    rec = route_ledger.RouteRecord(arrived=time.perf_counter(), surface='voice')
    track = fast.TwoTrack(req, 'synthetic-owner', rec, mr.score(message), mr.Route('full', 'synthetic'))
    track.turn_started = True
    started = time.perf_counter()
    checked, checks, leads = [], [], []
    first_draft = None
    def sink(piece):
        if piece.startswith(chief.PROSE_PREFIX):
            checked.append((time.perf_counter()-started, piece[len(chief.PROSE_PREFIX):]))
            track.holder.answer_ready.set()
    async def opener():
        async for event in track.lead(lambda: None):
            leads.append((time.perf_counter()-started, event['text']))
    async with httpx.AsyncClient(timeout=60) as client:
        async def review(prefix):
            begin = time.perf_counter()
            result = await truth.review_stream_prefix(client, prefix, sources=sources,
                message=message, business_id=None)
            checks.append({'ms': round((time.perf_counter()-begin)*1000), 'accepted': result})
            return result
        prover = truth.stream_prover(sources)
        streamer = chief._SentenceStreamer(sink, prover, review=review)
        bridge = None
        import chief_headline
        if chief_headline.eligible(message, lane='voice', is_greeting=False, is_coach_mode=False):
            bridge = VoiceBridge(sink, prover, chief._SentenceStreamer, prefix=chief.PROSE_PREFIX)
            streamer._sink = bridge.main
            bridge.start(message, sources, business_id=None)
        def generated(piece):
            nonlocal first_draft
            if first_draft is None:
                first_draft = time.perf_counter()-started
            streamer(piece)
        token = fast.OPENER.set(track.holder)
        opening_task = asyncio.create_task(opener())
        try:
            system += fast.continuation_block('')
            raw = await chief._call_claude(client, system, [{'role':'user', 'content':message}],
                model=chief_models.model_for('voice'), max_tokens=350,
                effort=chief_models.effort_for('voice'), enable_web_search=False,
                read_tools=None, stable_tools=False, stream_sink=generated)
            streamer.finish_input()
            if bridge:
                await bridge.close()
            actions, clean = chief._extract_actions_and_clean(raw)
            if actions:
                raise RuntimeError('Fixture generated an action tag; no action was executed')
            final, grounding = await truth.finalize_reply(client, clean, ctx=ctx, view_detail='', taken=[],
                message=message, business_id=None, reviewer=truth.review_reply,
                repairer=truth.repair_reply, budget_s=20.0)
            streamer.close()
            await streamer.wait_closed()
            final = chief._stitch_after_stream(streamer.text, final)
            if bridge:
                final = bridge.stitch(final)
            await opening_task
            already = ''.join(text for _, text in checked)
            if final.startswith(already):
                remainder = final[len(already):]
            elif final.strip() == already.strip():
                remainder = ''
            else:
                raise AssertionError('Checked wire prefix diverges from the final answer')
            if remainder:
                checked.append((time.perf_counter()-started, remainder))
            stamps = [at for at, text in checked if text.strip()]
            gaps = [b-a for a,b in zip(stamps, stamps[1:])]
            report = {'case': name, 'first_draft_ms': round(first_draft*1000) if first_draft is not None else None,
                'first_checked_ms': round(stamps[0]*1000) if stamps else None,
                'max_continuation_gap_ms': round(max(gaps, default=0)*1000),
                'total_ms': round((time.perf_counter()-started)*1000),
                'checked_chunks': [{'ms': round(at*1000), 'text': text} for at,text in checked],
                'opening': ''.join(text for _,text in leads), 'opener_cut': rec.opener_cut,
                'checks': checks, 'grounding': grounding.get('status'), 'answer': final,
                'answer_words': len(final.split()), 'context_loaded_before_clock': True}
            print(json.dumps(report, ensure_ascii=True), flush=True)
        finally:
            streamer.close()
            await streamer.wait_closed()
            if bridge:
                await bridge.close()
            if not opening_task.done():
                opening_task.cancel()
            await asyncio.gather(opening_task, return_exceptions=True)
            fast.OPENER.reset(token)


async def main():
    # Warm purely local imports before the timing clock, as in a running server.
    import model_ladder
    import spend_guard
    await asyncio.to_thread(spend_guard.over_budget, None)
    for name, message in [
        ('business_record', 'What is the name and price of my introductory workshop?'),
        ('marketing_discussion', 'For marketing the workshop, would you start with a few personal invitations or daily social posts? Give me your view briefly; do not create or send anything.'),
    ]:
        await run_case(name, message)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--baseline-ref')
    args=parser.parse_args()
    if not args.live:
        parser.error('--live is required for the bounded fictional model calls')
    if args.baseline_ref:
        baseline(args.baseline_ref)
    asyncio.run(main())
