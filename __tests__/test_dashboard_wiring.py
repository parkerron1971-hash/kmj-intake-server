import asyncio
import copy
import json
from unittest.mock import AsyncMock
import pytest
import chief_of_staff as chief
import chief_dashboard_actions as dashboard
import sb_clients
from system_destinations import destination, module_destination

U='11111111-1111-4111-8111-111111111111'
B='22222222-2222-4222-8222-222222222222'
M='33333333-3333-4333-8333-333333333333'

@pytest.fixture
def env(monkeypatch):
    state={'prefs':{'sidebarPinned':['contacts'], 'shellMode':'chat'},'writes':[], 'drop_write':False}
    async def sb(client, method, path, body=None):
        if path.startswith('/custom_modules'):
            assert f'business_id=eq.{B}' in path
            return [{'id':M,'name':'Sales tracker','slug':'sales-tracker','archetype':'composed_dashboard'}]
        assert path.startswith('/user_ui_prefs')
        if method=='GET':
            assert f'user_id=eq.{U}' in path and f'business_id=eq.{B}' in path
            return [{'prefs':copy.deepcopy(state['prefs'])}]
        state['writes'].append((path,body))
        if not state['drop_write']: state['prefs']=copy.deepcopy(body['prefs'])
        return [{'prefs':copy.deepcopy(state['prefs'])}]
    monkeypatch.setattr(dashboard, '_sb', sb)
    token=chief._TURN_USER_ID.set(U)
    jwt=sb_clients.set_user_jwt('test-verified-request-context')
    yield state
    chief._TURN_USER_ID.reset(token)
    sb_clients.reset_user_jwt(jwt)

def run(handler, action):
    return asyncio.run(handler(None,{'id':B}, action))

def test_module_is_featured_in_the_requested_dashboard_and_saved(env):
    out=run(dashboard.handle_set_dashboard_focus,{'dashboard':'grow','module_id':M})
    assert out['result']=='saved'
    assert out['nav']=={'tab':'grow','sub':'dashboard'}
    assert env['prefs']['dashboardFocus']['grow']['sub']==f'module:{M}'
    assert env['prefs']['dashboardFocus']['grow']['tab']=='operate'
    assert env['prefs']['sidebarPinned']==['contacts']
    assert out['frontend_event']['detail']['user_id']==U

def test_spoken_exact_module_name_resolves_in_this_business(env):
    out=run(dashboard.handle_set_dashboard_focus,{'module':'Sales tracker'})
    assert out['result']=='saved'
    assert 'home' in env['prefs']['dashboardFocus']

def test_unknown_or_foreign_module_is_not_saved(env):
    out=run(dashboard.handle_set_dashboard_focus,{'module_id':'another-business-module'})
    assert out['failed'] and not env['writes']

@pytest.mark.parametrize('tab,sub',[('home',None),('grow','dashboard'),('operate','missing'),('build','my-site'),('studio',None)])
def test_recursive_unknown_or_immersive_dashboard_targets_are_refused(env,tab,sub):
    assert run(dashboard.handle_set_dashboard_focus,{'tab':tab,'sub':sub})['failed']
    assert not env['writes']

def test_clear_preserves_other_dashboards_and_data(env):
    run(dashboard.handle_set_dashboard_focus,{'dashboard':'grow','tab':'grow','sub':'goals'})
    run(dashboard.handle_set_dashboard_focus,{'dashboard':'home','tab':'operate','sub':'calendar'})
    run(dashboard.handle_set_dashboard_focus,{'dashboard':'home','clear':True})
    assert list(env['prefs']['dashboardFocus'])==['grow']
    assert env['prefs']['shellMode']=='chat'

def test_start_page_persists_and_clears(env):
    assert run(dashboard.handle_set_start_page,{'module_id':M})['result']=='saved'
    assert env['prefs']['startPage']['sub']==f'module:{M}'
    run(dashboard.handle_set_start_page,{'clear':True})
    assert env['prefs']['startPage'] is None

def test_silent_database_failure_is_never_claimed_as_saved(env):
    env['drop_write']=True
    out=run(dashboard.handle_set_dashboard_focus,{'module_id':M})
    assert out['failed'] and 'frontend_event' not in out

def test_unattended_or_spoofed_user_id_cannot_change_personal_layout(env):
    token=chief._TURN_USER_ID.set('')
    try:
        out=run(dashboard.handle_set_start_page,{'tab':'home','user_id':U})
        assert out['failed'] and not env['writes']
    finally: chief._TURN_USER_ID.reset(token)

def test_read_layout_is_personal_and_does_not_write(env):
    out=run(dashboard.handle_get_dashboard_layout,{})
    assert json.loads(out['result'])=={'dashboardFocus':None,'startPage':None}
    assert not env['writes']

def test_navigation_aliases_resolve_and_unknown_leaves_fail():
    assert destination('grow','insights')=={'tab':'grow','sub':'retention'}
    with pytest.raises(ValueError): destination('operate','not-a-page')

def test_module_placement_uses_archetype_daily_home():
    assert module_destination({'id':M,'archetype':'booking_calendar'})=={'tab':'operate','sub':f'module:{M}'}
    assert module_destination({'id':M,'archetype':'fallback_generic'})['tab']=='build'

def test_accept_cannot_materialize_a_proposal_outside_this_business(monkeypatch):
    import module_spec_generator as generator
    import chief_module_actions as modules
    calls=[]
    monkeypatch.setattr(sb_clients,'sb_get_as_service',lambda path: [])
    monkeypatch.setattr(generator,'materialize_spec',lambda *a: calls.append(a))
    result=run(modules.handle_accept_module_spec,{'spec_id':'foreign-proposal'})
    assert result['failed'] and not calls

def test_reject_cannot_change_a_proposal_outside_this_business(monkeypatch):
    import module_spec_generator as generator
    import chief_module_actions as modules
    calls=[]
    monkeypatch.setattr(modules,'_sb',AsyncMock(return_value=[]))
    monkeypatch.setattr(generator,'reject_spec',lambda *a: calls.append(a))
    result=run(modules.handle_reject_module_spec,{'spec_id':'foreign-proposal'})
    assert result['failed'] and not calls

def test_executor_marks_successful_mutations_for_both_chat_and_voice(monkeypatch):
    monkeypatch.setattr(chief,'_gate_class_c',AsyncMock(return_value=('pass',None)))
    monkeypatch.setattr(chief,'_record_undoable',AsyncMock())
    import policy_engine
    monkeypatch.setattr(policy_engine,'evaluate',lambda *a,**k: type('V',(),{'allowed':True,'rule':'test'})())
    monkeypatch.setitem(chief.ACTION_HANDLERS,'create_contact',AsyncMock(return_value={'type':'create_contact','result':'created','label':'Created'}))
    out=asyncio.run(chief._execute_actions(None,{'id':B},[{'type':'create_contact'}],user_id=U))
    assert out[0]['data_changed']=={'business_id':B}
    monkeypatch.setitem(chief.ACTION_HANDLERS,'create_contact',AsyncMock(return_value={'type':'create_contact','result':'Failed: refused','label':'Held','failed':True}))
    out=asyncio.run(chief._execute_actions(None,{'id':B},[{'type':'create_contact'}],user_id=U))
    assert 'data_changed' not in out[0]
