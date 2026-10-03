"""Release a scoped scheduling calculation without a prose repair loop."""
from __future__ import annotations


async def serve_request(client, req, session, biz):
    import chief_availability
    if not chief_availability.request_shape(req):
        return None
    owner_id = str(getattr(getattr(session, 'user', None), 'id', '') or '')
    if (not isinstance(biz, dict) or not owner_id
            or str(biz.get('id') or '') != str(req.business_id)
            or str(biz.get('owner_id') or '') != owner_id):
        return None

    import chief_of_staff as chief
    import chief_stream_replay as replay
    import chief_speech_boundary as speech
    recovered = replay.recover(req, owner_id)
    if recovered is not None:
        return recovered
    if chief._STREAM_SINK.get() is None:
        recovered = await replay.recover_async(req, owner_id)
        if recovered is not None:
            return recovered

    import chief_listening
    prepared = chief_listening.consume(owner_id, req.business_id,
        getattr(req, 'listening_turn_id', None), getattr(req, 'listening_revision', None), req.message)
    result = await chief_availability.check_request(client, req, biz, prepared=prepared)
    if result is None:
        return None
    # This route cannot carry actions, including from a malformed result.
    if result.get('actions_taken') != [] or not isinstance(result.get('response'), str):
        raise ValueError('Invalid read-only availability result')
    answer = speech.final_reply(result['response'], req.message, request_id=req.request_id)
    result = {**result, 'response': answer}
    sink = chief._STREAM_SINK.get()
    if sink is not None:
        sink(chief.PROSE_PREFIX + answer)
    await chief._archive_turn(client, biz, req.message, answer, [])
    if sink is not None:
        replay.remember(req, owner_id, result)
    return result
