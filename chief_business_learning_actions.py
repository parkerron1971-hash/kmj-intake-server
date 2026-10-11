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


def _norm_words(text):
    return ' '.join(str(text or '').lower().replace('’', "'").split()).strip(' .!')


def _owner_said(statement, owner_text):
    """The rule is the owner's own words: present in their current message,
    ignoring case, spacing and trailing punctuation."""
    s, t = _norm_words(statement), _norm_words(owner_text)
    return bool(s) and s in t


async def handle_adopt_business_rule(client, biz, action):
    """A standing do/don't for how Chief works for this business. Only the
    owner's own words this turn, or the owner's tap on a proposal, make one."""
    kind = 'adopt_business_rule'
    statement = ' '.join(str(action.get('statement') or '').split())
    approved = bool(action.get('_owner_approved'))
    if not statement:
        return _result(kind, 'A rule needs the words to follow.', failed=True)
    if not approved and not _owner_said(statement, action.get('_owner_text')):
        return _result(kind, 'A rule has to be in your own words. Tell me the rule and I will '
                       'save it, or approve one I proposed.', failed=True)
    polarity = str(action.get('polarity') or '').strip().lower().replace("'", '')
    polarity = {'don’t': 'dont', 'do_not': 'dont', 'never': 'dont', 'always': 'do'}.get(polarity, polarity)
    try:
        row, fact = await asyncio.to_thread(
            learning.adopt_rule, biz, statement=statement, polarity=polarity,
            kind=str(action.get('kind') or 'preference'), scope=str(action.get('scope') or ''),
            key=action.get('key') or None, origin='proposal' if approved else 'chat')
        import business_brain
        await asyncio.to_thread(business_brain.stamp, biz, reason=f'rule adopted: {fact.key}')
        lead = 'From now on I will' if fact.polarity == 'do' else 'From now on I will not'
        return _result(kind, f'Rule saved. {lead} follow this: “{fact.content}”',
                       rule_key=fact.key, revision=(row or {}).get('revision'))
    except Exception as e:
        return _result(kind, str(e), failed=True)


def _distinctive(text):
    import re
    words = re.findall(r"[a-z0-9]+", str(text or '').lower())
    return {w for w in words if len(w) >= 4 or any(c.isdigit() for c in w)}


def owner_points_at(rule_content, key, owner_text):
    """Does the owner's message name THIS rule? Its key, or enough of its
    own distinctive words. Any owner turn is not enough: text the owner
    pasted could steer the model at a rule they never mentioned."""
    text = _norm_words(owner_text)
    if not text:
        return False
    if key and key.lower() in text:
        return True
    words = _distinctive(rule_content)
    hits = sum(1 for w in words if w in text)
    return hits >= (1 if len(words) <= 2 else 2)


async def handle_remove_business_rule(client, biz, action):
    kind = 'remove_business_rule'
    key = str(action.get('key') or '').strip()
    if not key:
        return _result(kind, 'Name the rule to remove (its key from OWNER RULES).', failed=True)
    if not action.get('_owner_approved'):
        owner_text = str(action.get('_owner_text') or '')
        if not owner_text.strip():
            return _result(kind, 'Only the owner can remove a rule.', failed=True)
        try:
            row = await asyncio.to_thread(learning.load, biz['id'])
        except Exception as e:
            return _result(kind, str(e), failed=True)
        target = next((f for f in ((row or {}).get('profile') or {}).get('facts') or []
                       if f.get('key') == key and f.get('polarity')), None)
        if not target:
            return _result(kind, f'No rule named {key}.', failed=True)
        if not owner_points_at(target.get('content'), key, owner_text):
            return _result(kind, 'Which rule should I remove? Say it in your own words '
                           f'(for example "remove the rule about {target.get("content", "")[:40]}"), '
                           'or remove it on your What Chief knows page.', failed=True)
    try:
        row, fact = await asyncio.to_thread(learning.remove_rule, biz['id'], key)
        import business_brain
        await asyncio.to_thread(business_brain.stamp, biz, reason=f'rule removed: {key}')
        return _result(kind, f'Rule removed: “{fact.content}”', rule_key=key,
                       revision=(row or {}).get('revision'))
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
