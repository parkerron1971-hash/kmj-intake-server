"""Three measurable business responsibilities, using the existing assignment engine.

Starting one records a goal; it grants no new permission to send, book or charge.
"""
from __future__ import annotations
import asyncio
from uuid import UUID

import chief_assignments as assignments
import sb_clients

PLAYBOOKS = {
    'fill_appointments': {
        'kind': 'sessions_scheduled', 'title': 'Fill appointments',
        'guidance': 'Check actual capacity and current bookings first. Identify suitable existing contacts '
                    'using their recorded contact preferences. Prepare specific outreach for owner review. '
                    'Never reserve a slot or send outreach without the existing required permission. '
                    'Recheck bookings before each move and stop when the target is met.'},
    'collect_invoice': {
        'kind': 'invoice_paid', 'title': 'Collect invoice',
        'guidance': 'Read the selected invoice and customer history. Confirm it remains unpaid before '
                    'preparing a reminder. Keep reminders in the approval queue. Do not send, charge, '
                    'or mark an invoice paid without the existing required permission. Stop when the '
                    'invoice records payment; a sent reminder is not a collected payment.'},
    'grow_contacts': {
        'kind': 'new_contacts', 'title': 'Grow new contacts',
        'guidance': 'Check new enquiries and existing drafts before preparing follow-up. Respect recorded '
                    'contact preferences and do not duplicate customer records to meet the goal. '
                    'Propose outreach for owner review. Count actual new contacts, never drafted messages. '
                    'Report observed growth without claiming all of it was caused by Chief.'},
}


async def handle_start_business_responsibility(client, biz, action):
    verb = 'start_business_responsibility'
    def fail(message):
        return {'type': verb, 'label': message, 'result': message, 'failed': True, 'nav': None}
    workflow = action.get('workflow')
    recipe = PLAYBOOKS.get(workflow)
    if not recipe:
        return fail('Choose appointment filling, invoice collection, or new-contact growth.')
    try:
        bid = str(UUID(str(biz['id'])))
        target = {'kind': recipe['kind']}
        if workflow == 'collect_invoice':
            iid = str(UUID(str(action.get('invoice_id'))))
            rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
                f'/invoices?business_id=eq.{bid}&id=eq.{iid}&select=id,status,paid_at&limit=1')
            if rows is None:
                return fail('I could not check the invoice. No responsibility was started.')
            if not rows:
                return fail('That invoice is not available in this business.')
            if rows[0].get('status') == 'paid' or rows[0].get('paid_at'):
                return fail('That invoice is already paid; no collection work was started.')
            target['invoice_id'] = iid
        else:
            count = action.get('count')
            if type(count) is not int or count < 1 or count > 999:
                return fail('Give me a whole-number target from 1 to 999.')
            if not assignments._parse_date(action.get('from')) or not assignments._parse_date(action.get('to')):
                return fail('Give me the start and end dates for this responsibility.')
            target.update({'from': action.get('from'), 'to': action.get('to'), 'count': count})
        error, target = assignments.normalize_target(target)
        if error:
            return fail(error)
        baseline = await asyncio.to_thread(assignments.measure, bid, target)
        if baseline.get('met'):
            return fail('The records already meet that target. No extra work was started.')
        title = str(action.get('title') or recipe['title'])[:160]
        result = await assignments.handle_create_assignment(client, biz, {
            'title': title, 'target': target, 'deadline': action.get('deadline'),
            'ask': recipe['guidance']})
        result = {**result, 'type': verb}
        if result.get('failed') or str(result.get('result', '')).lower().startswith('failed'):
            return result
        result['baseline'] = baseline
        result['workflow'] = workflow
        result['for_chief'] = ('The target is the total for the specified dates, not an additional count. '
            'State the baseline and deadline. This records a responsibility, not a completed outcome. '
            'The existing autonomy switch and approval rules apply. ' + recipe['guidance'])
        return result
    except (ValueError, TypeError):
        return fail('Check the invoice identifier, target dates, and deadline before starting this responsibility.')
    except Exception:
        return fail('I could not verify the records needed to start this responsibility. Nothing more was attempted.')
