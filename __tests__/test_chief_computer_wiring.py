import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
import chief_errands as ce
import chief_hand_actions as actions
import chief_of_staff as cos
import action_inverse
import policy_engine
import errand_completion

BID='00000000-0000-4000-8000-000000000001'
UID='00000000-0000-4000-8000-000000000002'
EID='00000000-0000-4000-8000-000000000003'

@pytest.mark.parametrize('text,expected',[
    ('approve this errand',True),('Please approve the order and run it.',True),
    ('Should I approve this errand?',False),('I approved it yesterday',False),
    ('yes',False),('Do not approve this errand',False),('"approve this errand"',False)])
def test_current_turn_confirmation_is_narrow(text,expected):
    assert cos._is_errand_confirmation(text)==expected


def test_approval_handler_cannot_use_model_supplied_confirmation(monkeypatch):
    row={'id':EID,'business_id':BID,'status':'planned','title':'Fixture','plan':{}}
    monkeypatch.setattr(actions,'_errand_user',lambda:SimpleNamespace(id=UID))
    monkeypatch.setattr(ce,'business',lambda *a:{'id':BID})
    monkeypatch.setattr(ce,'authorized',lambda *a:copy.deepcopy(row))
    approve=AsyncMock(return_value={**row,'status':'approved'})
    monkeypatch.setattr(ce,'approve',approve)
    token=cos._TURN_ERRAND_CONFIRMED.set(False)
    try:
        action={'type':'approve_errand','errand_id':EID,'confirmed':True}
        result=asyncio.run(actions.handle_approve_errand(None,{'id':BID},action))
        assert result['failed']
        approve.assert_not_called()
        cos._TURN_ERRAND_CONFIRMED.set(True)
        assert asyncio.run(actions.handle_approve_errand(None,{'id':BID},action))['type']=='errand_status'
        approve.assert_awaited_once()
    finally: cos._TURN_ERRAND_CONFIRMED.reset(token)


def test_same_turn_plan_cannot_be_approved_even_on_an_approval_turn(monkeypatch):
    row={'id':EID,'business_id':BID,'status':'planned','title':'Fixture','plan':{}}
    monkeypatch.setattr(actions,'_errand_user',lambda:SimpleNamespace(id=UID))
    monkeypatch.setattr(ce,'business',lambda *a:{'id':BID})
    monkeypatch.setattr(ce,'authorized',lambda *a:row)
    approve=AsyncMock()
    monkeypatch.setattr(ce,'approve',approve)
    yes=cos._TURN_ERRAND_CONFIRMED.set(True)
    planned=cos._TURN_ERRAND_PLANS.set((EID,))
    try:
        result=asyncio.run(actions.handle_approve_errand(None,{'id':BID},{'type':'approve_errand','errand_id':EID}))
        assert result['failed']
        approve.assert_not_called()
    finally:
        cos._TURN_ERRAND_CONFIRMED.reset(yes)
        cos._TURN_ERRAND_PLANS.reset(planned)


def test_sentry_transport_never_receives_secure_entry_event():
    import sentry_sdk
    from sentry_sdk.transport import Transport
    from access_log_redaction import scrub_sentry_event
    envelopes=[]
    class MemoryTransport(Transport):
        def capture_envelope(self,envelope): envelopes.append(envelope)
    client=sentry_sdk.Client(dsn='https://fixture@example.invalid/1',transport=MemoryTransport,
        default_integrations=False,before_send=scrub_sentry_event,
        before_send_transaction=scrub_sentry_event)
    try:
        client.capture_event({'message':'PRIVATE FIXTURE PASSWORD','request':{
            'url':f'https://api.test/agents/chief/errands/{EID}/secret',
            'data':{'password':'PRIVATE FIXTURE PASSWORD'}}})
        assert not envelopes
        client.capture_event({'message':'control'})
        assert len(envelopes)==1
        assert 'PRIVATE FIXTURE' not in str(envelopes)
    finally: client.close()


@pytest.mark.parametrize('surface',['scheduler','workflow','agent','autopilot'])
@pytest.mark.parametrize('prompted',[False,True])
def test_unattended_paths_cannot_approve_even_if_mislabeled_prompted(surface,prompted):
    result=policy_engine.evaluate(BID,verb='approve_errand',surface=surface,prompted=prompted)
    assert not result.allowed
    assert result.rule=='errand:explicit-approval-required'


def test_undo_builds_only_a_new_plan():
    assert action_inverse.build_inverse('approve_errand',{}, {'errand_id':EID,'status':'done'})=={
        'type':'plan_errand','kind':'cancel_order','original_errand_id':EID}
    assert action_inverse.build_inverse('approve_errand',{}, {'errand_id':EID,'status':'approved'}) is None


def test_unknown_cancel_window_returns_unsent_request_without_browser(monkeypatch):
    monkeypatch.setattr(ce,'get_row',lambda eid:{'id':EID,'business_id':BID,'kind':'reorder','status':'done',
        'receipt':{'order_number':'TEST-1'}})
    rpc=Mock()
    monkeypatch.setattr(ce,'rpc',rpc)
    result=asyncio.run(ce.plan_cancellation({'id':BID},UID,{'original_errand_id':EID}))
    assert result['errand'] is None and result['door']=='email'
    assert 'Nothing was sent' in result['action']['result']
    rpc.assert_not_called()


def test_ledger_receives_last_four_and_no_page_or_fields(monkeypatch):
    import audit_log
    record=Mock(return_value=True)
    monkeypatch.setattr(audit_log,'record',record)
    errand_completion.lifecycle({'id':EID,'business_id':BID,'status':'done','approved_by':UID,
        'approval_scope':'button','plan':{'__confirmation_text':'PRIVATE PAGE'},
        'receipt':{'paid_with':'card 1234','charged_cents':349,'confirmation_host':'supplier.test',
                   'fields':{'number':'PRIVATE PAN'}}},'done')
    payload=record.call_args.kwargs
    assert payload['payload']['last4']=='1234'
    assert payload['verb']=='order_placed' and payload['authorized_by']=='errand:button'
    assert 'PRIVATE' not in str(payload)


def test_replay_is_injected_even_when_model_emits_no_action(monkeypatch):
    report={'type':'errand_status','errand_id':EID,'replay':True}
    monkeypatch.setattr(errand_completion,'reports',lambda bid:[report])
    rpc=Mock(return_value=True)
    monkeypatch.setattr(ce,'rpc',rpc)
    assert asyncio.run(cos._inject_errand_report([],BID))==[report]
    assert rpc.call_args.args==('chief_errand_shown',)


def test_prompt_advertises_real_computer_and_secure_entry_contract():
    source=Path('chief_prompt.py').read_text(encoding='utf8')
    for verb in ('plan_errand','approve_errand','stop_errand','errand_status'):
        assert '"type":"'+verb+'"' in source
        assert verb in cos.ACTION_HANDLERS
    for promise in ('CURRENT turn','Secure Entry','Chief cannot do step-up','Unattended approvals are forbidden'):
        assert promise in source
