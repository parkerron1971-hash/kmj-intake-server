"""Chief's existing action door owns authorization; all ids come from that business."""
import asyncio

import business_learning as learning


def _result(action, text, **extra):
    return {'type': action, 'result': text, 'label': text, 'nav': None, **extra}


async def handle_recall_business_knowledge(client, biz, action):
    kind = 'recall_business_knowledge'
    try:
        row = await asyncio.to_thread(learning.load, biz['id'])
        return _result(kind, 'Here is the operating knowledge on file.' if row else
                       'No operating profile yet. Tell me how your business works.', profile=row)
    except Exception as e:
        return _result(kind, str(e), failed=True)


async def handle_learn_business(client, biz, action):
    import chief_jobs
    kind = 'learn_business'
    description = str(action.get('_owner_text') or '').strip()
    question = str(action.get('research_question') or '').strip()
    if not description:
        return _result(kind, 'Business discovery needs an owner message.', failed=True)
    if not biz.get('owner_id'):
        return _result(kind, 'The business owner could not be identified.', failed=True)
    try:
        # Migration/read failures are explicit and happen before a paid job starts.
        await asyncio.to_thread(learning.load, biz['id'])
        job = await chief_jobs.enqueue(client, user_id=str(biz['owner_id']), business_id=biz['id'],
            kind='learn_business', params={'description': description[:12000],
                                          'research_question': question[:1000]}, source='chief')
        if not job:
            raise RuntimeError('The learning job could not be started.')
        return _result(kind, 'Business discovery is already running.' if job.get('deduped') else
                       'I am developing your business profile and keeping track of what needs checking.',
                       job_id=job['id'])
    except Exception as e:
        return _result(kind, str(e), failed=True)


async def handle_correct_business_knowledge(client, biz, action):
    kind = 'correct_business_knowledge'
    statement = str(action.get('statement') or '').strip()
    owner_text = str(action.get('_owner_text') or '')
    if not statement or statement not in owner_text:
        return _result(kind, 'The correction must quote what you just told me.', failed=True)
    try:
        revision = action.get('expected_revision')
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise ValueError('Recall the current knowledge revision before correcting it.')
        row = await asyncio.to_thread(learning.correct, biz['id'], key=action.get('key'),
            kind=action.get('kind'), statement=statement, expected_revision=revision,
            resolves_gap=action.get('resolves_gap'))
        return _result(kind, 'I saved your correction for future conversations and build proposals. '
                       'Existing workspace settings have not been changed.', revision=row['revision'])
    except Exception as e:
        return _result(kind, str(e), failed=True)


async def handle_capture_business_knowledge(client, biz, action):
    kind = 'capture_business_knowledge'
    owner_text = str(action.get('_owner_text') or '')
    if not owner_text:
        return _result(kind, 'Capturing business knowledge requires an actual owner message.', failed=True)
    try:
        row = await asyncio.to_thread(learning.capture, biz,
            {'facts': action.get('facts'), 'expected_revision': action.get('expected_revision')}, owner_text)
        return _result(kind, 'Your answers are saved in your private business knowledge.',
                       revision=row['revision'], status=row['status'])
    except Exception as e:
        return _result(kind, str(e), failed=True)


async def seed_custom_business(biz):
    try:
        return await _seed_custom_business(biz)
    except Exception:
        # Other signup background work (welcome, trial and attribution) must
        # still run if discovery storage or the queue is unavailable.
        learning.log.exception('Custom business discovery could not be queued')
        return {'status': 'failed'}


async def _seed_custom_business(biz):
    """Runs on FastAPI's event loop after signup, using the durable job runner.

    A synchronous asyncio.run here would cancel the runner on return. Keep this
    function async and register it directly as a background task.
    """
    import httpx
    import chief_jobs
    import vertical_registry
    if vertical_registry.resolve(biz.get('type')) != 'custom':
        return None
    existing = await asyncio.to_thread(learning.load, biz['id'])
    if existing:
        return {'status': existing['status']}
    description = str((biz.get('settings') or {}).get('custom_type') or '').strip()
    if not description:
        return {'status': 'needs_input'}
    async with httpx.AsyncClient() as client:
        job = await chief_jobs.enqueue(client, user_id=str(biz['owner_id']), business_id=biz['id'],
            kind='learn_business', params={'description': description, 'build_workspace': True}, source='signup')
    if not job:
        raise RuntimeError('Custom business discovery could not be queued.')
    return {'status': 'queued', 'job_id': job['id']}
