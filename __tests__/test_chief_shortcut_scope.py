from types import SimpleNamespace

import pytest

import chief_invoice_readout as invoices
import chief_quick_plan as plans


def request(text, history=(), **kw):
    return SimpleNamespace(message=text,
        conversation_history=[SimpleNamespace(role='user', content=m) for m in history], **kw)


@pytest.mark.parametrize('history', [
    ['For this plan focus only on my website, no invoice reminders'],
    ['My budget is $200 for this plan'],
    ['I only have one hour tomorrow'],
    ['Show my invoices', 'Only Ada Sample'],
    ['The next two days should be dedicated to the website.'],
    ['Keep the plan centered on marketing.'],
    ['Take a screenshot; keep my work focused only on marketing'],
])
def test_prior_plan_constraints_stay_in_the_full_reasoning_path(history):
    assert not plans.eligible(request('Show me a short plan for the next two days', history))


@pytest.mark.parametrize('history', [
    ['Only show unpaid invoices for Ada Sample'],
    ['Show my invoices', 'Only Ada Sample'],
    ['Exclude invoices that are paid'],
    ['The invoices we are talking about are for Acme.'],
    ['I mean the ones for Acme.'],
    ['Show invoices', 'For Acme'],
    ['Show invoices', 'Okay', 'For Acme'],
    ['Show paid invoices'],
])
def test_invoice_filter_constraints_are_not_dropped(history):
    assert invoices.request_action(request('Show invoices', history)) is None


@pytest.mark.parametrize('changes', [
    {'intent': 'build'},
    {'current_context': SimpleNamespace(viewing_contact_id='contact')},
    {'current_context': SimpleNamespace(viewing_module_id='module')},
    {'current_context': SimpleNamespace(viewing_session_id='session')},
])
def test_invoice_shortcut_keeps_scoped_views_on_full_path(changes):
    assert invoices.request_action(request('Show invoices', **changes)) is None


def test_readonly_plan_safety_instruction_does_not_disable_following_generic_plan():
    history = ['Show me a short suggested plan for the next two days. '
               'Only show the plan; do not create tasks, send messages, or change records.']
    assert plans.eligible(request('Show me a short plan for the next two days', history))


def test_plain_previous_invoice_display_is_not_a_plan_constraint():
    assert plans.eligible(request('Show me a short plan for the next two days', ['Show invoices']))


def test_unrelated_site_read_is_not_a_persistent_plan_constraint():
    req = request('Show me a short plan for the next two days',
                  ['Can you pull up a screenshot of my website from the public internet?'])
    # A semantic scope check can clear this independent older operation.
    assert plans.request_shape(req) and not plans.eligible(req)
