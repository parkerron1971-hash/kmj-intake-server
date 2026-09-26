"""Typed work orders and deterministic, checkpointed build execution.
No model calls, credentials, or database dependencies in the state machine.
"""
from __future__ import annotations
import asyncio
import contextvars
import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from uuid import UUID, uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

worker_scope = contextvars.ContextVar('chief_build_scope', default=None)
turn_scope = contextvars.ContextVar('chief_build_turn', default=None)
entity_id = contextvars.ContextVar('chief_build_entity', default=None)
KINDS = {'event_setup', 'form_and_link', 'flyer', 'site_door'}
MAX_STEPS = 8


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def stable_id(business, turn, slot='build'):
    return str(uuid5(NAMESPACE_URL, f'{business}:{turn}:{slot}'))


@dataclass
class WorkOrder:
    order_id: str
    kind: str
    brief: str
    facts: dict
    asked_by: str
    surface: str = 'desktop'
    practitioner_words: str = ''
    approvals: dict = field(default_factory=dict)
    untrusted_taint: bool = False
    version: int = 1
    submission_fingerprint: str = ""
    # The chat that asked for it, so the practitioner's recent chats can
    # show where the work stands and the done message lands in the right
    # place (2026-09-24). An id from the app; never trusted for authority.
    conversation_id: str = ""

    @classmethod
    def create(cls, payload, *, business_id, user_id, turn_id, surface, words, tainted=False,
               conversation_id=''):
        kind = payload.get('kind')
        if kind not in KINDS:
            raise ValueError('Choose an event, a form, a flyer, or an events page for this build.')
        facts = payload.get('facts') or {}
        if not isinstance(facts, dict) or len(json.dumps(facts)) > 16000:
            raise ValueError('The build details are too large or invalid.')
        string_fields = ('title','starts_at','timezone','location','name','description','prompt','website_url','send_to','channel','capability','form_type','link_module','confirmation_message','admission','flyer_url')
        for key in string_fields:
            if key in facts and facts[key] is not None and (not isinstance(facts[key],str) or len(facts[key])>4000):
                raise ValueError('Build text fields must contain plain text.')
        for key in ('wants_registration_form','wants_flyer'):
            if key in facts and type(facts[key]) is not bool:
                raise ValueError('Build options must be true or false.')
        if 'reference_ids' in facts:
            refs=facts['reference_ids']
            if not isinstance(refs,list) or len(refs)>4:
                raise ValueError('Choose up to four reference images.')
            facts={**facts,'reference_ids':[str(UUID(str(ref))) for ref in refs]}
        # Authority and identity are supplied only by the server, never the model.
        conversation_id = conversation_id if isinstance(conversation_id, str) else ''
        return cls(stable_id(business_id, turn_id), kind, str(payload.get('brief') or '')[:4000],
                   dict(facts), str(UUID(str(user_id))), surface, words[:600], untrusted_taint=bool(tainted),
                   conversation_id=conversation_id if _CONVERSATION_ID.fullmatch(conversation_id) else '')

    def payload(self):
        return asdict(self)


class BuildQuestion(Exception):
    def __init__(self, field, text):
        self.field, self.text = field, text
        super().__init__(text)


@dataclass
class Step:
    name: str
    verb: str
    label: str
    params: dict = field(default_factory=dict)
    requires: tuple = ()
    sensitive: bool = False


def question(order):
    f = order.facts
    needed = {'event_setup': [('title', 'What is the workshop called?'),
        ('starts_at', 'What date and time does it start?'), ('timezone', 'Which time zone is the workshop in?'),
        ('location', 'Where will the workshop take place?')],
        'form_and_link': [('name', 'What should the form be called?')],
        'flyer': [('prompt', 'What should the flyer show?')], 'site_door': []}[order.kind]
    for key, text in needed:
        if not f.get(key):
            return {'field': key, 'text': text}
    if order.kind == 'form_and_link' and str(f.get('form_type') or '').strip().lower() == 'event':
        from event_form_details import event_values, details_question
        details = event_values(f)
        need = details_question(details)
        if need: return need
        f['event_details'] = details
    if order.kind == 'event_setup':
        try:
            tz = ZoneInfo(str(f['timezone']))
        except Exception:
            return {'field':'timezone','text':'Which time zone should I use? For example, America/Detroit.'}
        try:
            dt = datetime.fromisoformat(str(f['starts_at']))
            if dt.tzinfo is None:
                # Refuse DST ambiguity instead of guessing which clock hour.
                a, b = dt.replace(tzinfo=tz, fold=0), dt.replace(tzinfo=tz, fold=1)
                if a.utcoffset() != b.utcoffset():
                    raise ValueError('ambiguous local time')
                dt = a
            f['starts_at'] = dt.isoformat()
        except Exception:
            return {'field': 'starts_at', 'text': 'Please give the start time with its UTC offset, and a valid time zone.'}
        if f.get('capacity') is not None and (type(f['capacity']) is not int or f['capacity'] < 1):
            return {'field': 'capacity', 'text': 'How many people can attend? Please give a whole number above zero.'}
        if f.get('price', 0) != 0:
            return {'field': 'price', 'text': 'This registration is free. Set the price to zero to continue, or cancel and set up paid booking.'}
    if order.kind == 'site_door' and f.get('capability', 'events') != 'events':
        return {'field': 'capability', 'text': 'This build supports an events page. Use events to continue.'}
    return None


def plan(order):
    f = order.facts
    if order.kind == 'event_setup':
        steps = [Step('events_module', 'ensure_module', 'Events is ready in Build.',
            {'module_name': 'Events', 'archetype': 'event_roster'}),
            Step('occasion', 'create_module_entry', 'Your workshop is saved.', requires=('events_module',)),
            Step('events_page', 'set_site_capability', 'Your events page is available.',
                 {'capability': 'events', 'on': True}, ('occasion',))]
        if f.get('wants_registration_form', True):
            steps.append(Step('registration', 'verify_registration', 'Registration is connected to your workshop.', requires=('events_page',)))
        steps.append(Step('site_link', 'connect_events', 'Your website links to Events.', requires=('events_page',)))
        if f.get('wants_flyer'):
            steps.append(Step('flyer', 'generate_image', 'Your flyer is ready in Media Library.', sensitive=True))
        return steps
    if order.kind == 'form_and_link':
        steps = [Step('form', 'create_client_form', 'Your form is ready.',
                      {k: f[k] for k in ('name','fields','form_type','description','link_module','confirmation_message','event_details','starts_at','timezone','location','admission','include_flyer','flyer_url') if k in f})]
        if f.get('send_to'):
            steps.append(Step('send', 'send_form_link', 'Your form link was sent.', requires=('form',), sensitive=True))
        return steps
    if order.kind == 'flyer':
        return [Step('flyer', 'generate_image', 'Your flyer is ready in Media Library.', sensitive=True)]
    return [Step('events_module', 'ensure_module', 'Events is ready in Build.', {'module_name':'Events','archetype':'event_roster'}),
            Step('events_page', 'set_site_capability', 'Your events page is available.', {'capability':'events','on':True}, ('events_module',)),
            Step('site_link', 'connect_events', 'Your website links to Events.', requires=('events_page',))]


_CONVERSATION_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')


def _lower_first(text):
    return text[:1].lower() + text[1:] if text[:1].isupper() and not text[1:2].isupper() else text


def progress_note(steps, i, state, stage):
    """What Chief says about the build while step i runs (Kevin, 2026-09-24:
    "just finished with ... now going on to ...", "I am almost done").
    Built from the plan and the receipts only, never a model: "finished"
    names only a step whose result was read back and verified."""
    n = len(steps)
    now = _lower_first(stage)
    if n == 1:
        return f'On it. {stage}.'
    if i == 0:
        return f'On it. {stage} (1 of {n}).'
    finished = None
    for s in steps[:i]:
        r = state.get('steps', {}).get(s.name) or {}
        if r.get('verified', {}).get('ok'):
            finished = r.get('label')
    lead = f'{finished.rstrip()} ' if finished else ''
    if i == n - 1:
        return f'{lead}Almost done: {now} ({n} of {n}).'
    return f'{lead}Now {now} ({i + 1} of {n}).' if finished else f'{stage} ({i + 1} of {n}).'


def ordered_receipts(state):
    """The receipts in the order the plan runs them. The checkpoint is saved
    as jsonb, which keeps object keys in its own order (shortest first), so
    after any save and resume the steps came back shuffled and the summary
    read "Your workshop is saved" before "Events is ready" (first live
    build, 2026-09-26). The plan's own order is saved beside them."""
    receipts = list(state.get('steps', {}).values())
    order = state.get('order') or []
    rank = {name: i for i, name in enumerate(order)}
    return sorted(receipts, key=lambda r: rank.get(r.get('step'), len(order)))


def closing_note(state, total):
    receipts = ordered_receipts(state)
    waiting = [r for r in receipts if r.get('outcome') == 'queued']
    if waiting:
        return f'Almost done. Still waiting on this: {waiting[0].get("label", "").rstrip()}'
    checked = sum(1 for r in receipts if r.get('verified', {}).get('ok'))
    if checked == total:
        return 'All done. Every step is checked.'
    return f'Finished what I could: {checked} of {total} steps checked.'


def receipt(step, outcome, label=None, *, ids=None, verified=None, detail=''):
    return {'step': step.name, 'type': step.verb, 'outcome': outcome, 'label': label or step.label,
            'ids': ids or {}, 'verified': verified or {'ok': False, 'how': 'not performed'}, 'detail': detail}


def finish(state):
    receipts = ordered_receipts(state)
    state['receipts'] = receipts
    bad = [r for r in receipts if r['outcome'] in ('failed','needs_hand','uncertain','blocked')]
    if state.get('question'):
        status = 'needs_answer'
    elif any(r['outcome'] == 'held' for r in receipts):
        status = 'held'
    elif any(r['outcome'] == 'queued' for r in receipts):
        status = 'waiting'
    elif bad or any(not r['verified']['ok'] for r in receipts):
        status = 'done_with_gaps' if any(r['verified']['ok'] for r in receipts) else 'failed'
    else:
        status = 'done' if receipts else 'failed'
    state['status'] = status
    state['summary_label'] = ' '.join(r['label'] for r in receipts)
    if state.get('question'):
        state['summary_label'] = state['question']['text']
    if not state['summary_label']:
        state['summary_label'] = 'The build did not complete.'
    return state


async def run(order, adapter, previous=None):
    state = dict(previous or {})
    state.setdefault('steps', {})
    state.setdefault('attempted', {})
    state['held'] = None
    state['question'] = question(order)
    if state['question']:
        return finish(state)
    steps = plan(order)
    if not steps or len(steps) > MAX_STEPS:
        raise ValueError('Invalid build plan')
    state['order'] = [s.name for s in steps]
    sensitive_count = int(state.get('sensitive_count', 0))
    for i, step in enumerate(steps):
        try:
            await adapter.assert_authority(step)
        except Exception:
            state['steps'][step.name] = receipt(step, 'failed', 'This step could not pass its permission check.')
            break
        old = state['steps'].get(step.name)
        if old and old['outcome'] in ('created', 'existed') and old['verified']['ok']:
            # Completed checkpoints replay. Existing resources on a NEW order
            # still go through verify below.
            continue
        if any(not state['steps'].get(dep, {}).get('verified', {}).get('ok') for dep in step.requires):
            state['steps'][step.name] = receipt(step, 'blocked', 'This part is waiting for an earlier step to be fixed.')
            continue
        try:
            params = await adapter.parameters(step, state)
            existing = await adapter.find(step, params, state)
        except BuildQuestion as need:
            state['question'] = {'field':need.field,'text':need.text}
            break
        fingerprint = digest({'step': step.name, 'params': params})
        if existing is not None:
            checked = await adapter.verify(step, params, existing, state)
            if checked.get('verified', {}).get('ok'):
                checked['outcome'] = 'existed'
            state['steps'][step.name] = checked
            await adapter.save(finish(state))
            continue
        if step.sensitive and (order.untrusted_taint or
                (order.surface == 'voice' and order.approvals.get(step.name) != fingerprint)):
            label = await adapter.confirmation(step, params)
            state['held'] = {'step': step.name, 'fingerprint': fingerprint, 'say': 'go ahead', 'label': label}
            state['steps'][step.name] = receipt(step, 'held', label)
            # Independent steps may continue; dependent ones are blocked above.
            continue
        if step.sensitive and sensitive_count >= 3:
            state['steps'][step.name] = receipt(step, 'held', 'The sensitive-action limit was reached. Review the remaining work.')
            continue
        if state['attempted'].get(step.name) and not adapter.retry_safe(step):
            state['steps'][step.name] = receipt(step, 'uncertain', 'This action may already have happened. Check its history before trying again.')
            continue
        state['attempted'][step.name] = fingerprint
        stage = adapter.stage(step)
        state['progress'] = {'pct': int(100*i/len(steps)), 'stage': stage, 'step': i + 1,
                             'steps': len(steps), 'say': progress_note(steps, i, state, stage)}
        if step.sensitive:
            sensitive_count += 1
            state['sensitive_count'] = sensitive_count
        # Durable intent BEFORE effects. A failed checkpoint prevents dispatch.
        await adapter.save(finish(state))
        result = None
        error = ''
        try:
            result = await asyncio.wait_for(adapter.execute(step, params, state), timeout=120)
        except Exception as exc:
            error = type(exc).__name__
        # Even a handler exception can occur AFTER its insert. Reconcile first.
        checked = await adapter.verify(step, params, result, state)
        if error:
            checked['detail'] = error
        state['steps'][step.name] = checked
        await adapter.save(finish(state))
    count = sum(1 for r in state['steps'].values() if r.get('verified',{}).get('ok'))
    state['progress'] = {'pct': int(100*count/len(steps)), 'stage': 'Checked' if count==len(steps) else 'Waiting for remaining work',
                         'step': count, 'steps': len(steps), 'say': closing_note(state, len(steps))}
    return finish(state)
