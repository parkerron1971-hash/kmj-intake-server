"""Opt-in live, tool-free smoke test. Uses synthetic records, never business actions.
Run with existing provider environment; prints only timing and fixture outcomes.
"""
import asyncio
import json
import pathlib
import sys
import time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import httpx
import chief_fast_track as fast
import chief_models
import chief_truth as truth
import model_router as mr
import route_ledger


async def main():
    rec = route_ledger.RouteRecord(arrived=time.perf_counter())
    gate = mr.OpenerGate('Which invoices should I chase first?')
    out, chunks, first = {}, [], None
    async for piece in fast.stream_text(
        fast.style_for('fixture', 'fixture') + '\n\n' + fast._OPENER_SYSTEM,
        [{'role': 'user', 'content': 'Which invoices should I chase first?'}],
        model=chief_models.model_for('fast'), max_tokens=fast.OPENER_MAX_TOKENS,
        rec=rec, endpoint='/chief/stream-smoke', units=0, business_id=None, out=out):
        safe = gate.feed(piece)
        if safe:
            if first is None:
                first = round((time.perf_counter() - rec.arrived) * 1000)
            chunks.append(safe)
    chunks.append(gate.finish())
    print(json.dumps({'opener': ''.join(chunks), 'first_model_words_ms': first, 'cut': gate.cut_reason}))
    if not ''.join(chunks).strip():
        raise RuntimeError('No useful opening from the provider')
    sources = {'context:daily_bookings': {'kind': 'record', 'complete': True,
        'text': 'Booked appointments by day for the full current week: Monday 2, Tuesday 8, Wednesday 3, Thursday 4, Friday 1, Saturday 0, Sunday 0.'}}
    # Production has already loaded the main model and checked its budget.
    # Warm those same imports/guard outside the incremental-check clock.
    import model_ladder
    import spend_guard
    await asyncio.to_thread(spend_guard.over_budget, None)
    client = fast.client()
    if client is not None:
        for prefix, expected in [('Your busiest day is Tuesday.', True), ('Your busiest day is Friday.', False)]:
            t0 = time.perf_counter()
            try:
                accepted = await asyncio.wait_for(truth.review_stream_prefix(client, prefix,
                    sources=sources, message='Which day is busiest?', business_id=None), 4.0)
                result = {'accepted': accepted, 'expected': expected, 'ms': round((time.perf_counter()-t0)*1000)}
            except asyncio.TimeoutError:
                result = {'timeout': True, 'expected': expected, 'ms': round((time.perf_counter()-t0)*1000)}
            print(json.dumps(result))
            if result.get('accepted') is not expected:
                raise RuntimeError('Prefix check did not meet the timing/correctness contract')


if __name__ == '__main__':
    asyncio.run(main())
