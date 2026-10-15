import json
from pathlib import Path
import pytest
import dev_redact
import dev_kai
import dev_bridge
from __tests__.dev_relay_fake import relay, run

VECTORS = json.loads((Path(__file__).parent/'fixtures/redaction_vectors.json').read_text())['vectors']

@pytest.mark.parametrize('vector', VECTORS, ids=lambda v:v['name'])
def test_shared_vectors(vector):
    assert dev_redact.text(vector['input']) == vector['expected']
    assert dev_redact.text(vector['expected']) == vector['expected']


def test_recursive_sensitive_keys_and_structural_ids():
    assert dev_redact.deep({'id':'ghp_abc', 'api_key':'not-shaped', 'items':[{'text':'Bearer secret'}]}) == {
        'id':'ghp_abc', 'api_key':'[redacted:assignment]', 'items':[{'text':'Bearer [redacted:token]'}]}


def test_kai_and_legacy_screens_redact_before_truncation(relay, monkeypatch):
    row = dev_kai._entry_row(dev_kai.KaiEntry(id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',kind='kai',
        text='sk-ant-'+'x'*4000), 'd')
    assert row['text'] == '[redacted:token]'
    task = {'id':'t', 'notes':[]}
    relay.tables['dev_tasks'].append(task)
    run(dev_bridge._put_screen(None,task,'API_KEY=secret',None))
    assert relay.tables['dev_tasks'][0]['notes'][0]['text'] == 'API_KEY=[redacted:assignment]'
    assert dev_kai._clean_state({'approvals':[{'id':1,'what':'--password hello'}]})['approvals'][0]['what'] == '--password [redacted:assignment]'


def test_failure_never_returns_raw_text(monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError('rule failed')
    monkeypatch.setattr(dev_redact, 'text', broken)
    with pytest.raises(RuntimeError):
        dev_kai._entry_row(dev_kai.KaiEntry(id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',kind='kai',text='secret'), 'd')


def test_repeated_sensitive_name_is_linear_and_redacts_when_assigned():
    # This used to take over one second at 16 KB and grows quadratically.
    # A large delimiter-free name and an assignment exercise both paths.
    value='auth'*40000
    assert dev_redact.text(value)==value
    assert dev_redact.text(value+'=hidden')==value+'=[redacted:assignment]'


def test_uuid_survives_kai_metadata_and_insert_layer():
    value='12345678-90ab-4cde-8f12-34567890abcd'
    row=dev_kai._entry_row(dev_kai.KaiEntry(id=value,kind='tool',meta={'card':value}),value)
    assert dev_redact.deep(row)['device_id']==value
    assert dev_redact.deep(row)['meta']['card']==value
