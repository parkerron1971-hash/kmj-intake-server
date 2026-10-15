import hashlib
import json
from pathlib import Path
import pytest
import dev_redact
import dev_kai
import dev_bridge
from __tests__.dev_relay_fake import relay, run

# Source: claude-bench test/fixtures/redaction-vectors.json, commit 288904f.
# Only four inputs encode fake token prefixes for GitHub push protection:
# Stripe live and restricted test keys (restricted key only), GitLab token,
# SendGrid key, and Twilio API key sid. Decode before exact shared comparisons.
FIXTURE = (Path(__file__).parent/'fixtures/redaction_vectors.json').read_text(encoding='utf-8')
for placeholder, prefix in {
    '<<stripe-restricted-test>>': 'rk_test_',
    '<<gitlab>>': 'glpat-',
    '<<sendgrid>>': 'SG.',
    '<<twilio>>': 'SK',
}.items():
    FIXTURE = FIXTURE.replace(placeholder, prefix)
VECTORS = json.loads(FIXTURE)['vectors']


def test_decoded_fixture_is_identical_to_desktop_source():
    assert hashlib.sha256(FIXTURE.encode('utf-8')).hexdigest() == (
        '84319f086b38193dbf19127380b0d3824a314b0a00f42c304933f6b38f3f399e')


@pytest.mark.parametrize('vector', VECTORS, ids=lambda v:v['name'])
def test_shared_vectors(vector):
    if vector.get('desktop_only'):
        pytest.skip('Known values stay on the desktop')
    assert dev_redact.text(vector['input']) == vector['expect']
    assert dev_redact.text(vector['expect']) == vector['expect']


def test_recursive_sensitive_keys_and_structural_ids():
    assert dev_redact.deep({'id':'ghp_abc', 'api_key':'not-shaped', 'items':[{'text':'Bearer abcd1234efgh'}]}) == {
        'id':'ghp_abc', 'api_key':'[redacted:secret]', 'items':[{'text':'Bearer [redacted:token]'}]}


def test_kai_and_legacy_screens_redact_before_truncation(relay, monkeypatch):
    row = dev_kai._entry_row(dev_kai.KaiEntry(id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',kind='kai',
        text='sk-ant-'+'x'*4000), 'd')
    assert row['text'] == '[redacted:token]'
    task = {'id':'t', 'notes':[]}
    relay.tables['dev_tasks'].append(task)
    run(dev_bridge._put_screen(None,task,'API_KEY=secret',None))
    assert relay.tables['dev_tasks'][0]['notes'][0]['text'] == 'API_KEY=[redacted:secret]'
    assert dev_kai._clean_state({'approvals':[{'id':1,'what':'--password hello'}]})['approvals'][0]['what'] == '--password [redacted:secret]'


def test_failure_never_returns_raw_text(monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError('rule failed')
    monkeypatch.setattr(dev_redact, 'text', broken)
    with pytest.raises(RuntimeError):
        dev_kai._entry_row(dev_kai.KaiEntry(id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',kind='kai',text='secret'), 'd')


def test_repeated_sensitive_name_is_linear_and_redacts_when_assigned():
    # This used to take over one second at 16 KB and grows quadratically.
    # A large delimiter-free name and an assignment exercise both paths.
    value='token'*40000
    assert dev_redact.text(value)==value
    assert dev_redact.text(value+'=hidden')==value+'=[redacted:secret]'


def test_uuid_survives_kai_metadata_and_insert_layer():
    value='12345678-90ab-4cde-8f12-34567890abcd'
    row=dev_kai._entry_row(dev_kai.KaiEntry(id=value,kind='tool',meta={'card':value}),value)
    assert dev_redact.deep(row)['device_id']==value
    assert dev_redact.deep(row)['meta']['card']==value


@pytest.mark.parametrize('value', [
    'Basic configuration; the bearer of news',
    'bearer abcd1234efgh basic abcd1234efgh',
    'Author: Kevin McClain preauth=hello authz=world',
    'token=true secret=false password=null TOKEN=$GITHUB_TOKEN',
])
def test_instruction_like_prose_and_safe_values(value):
    assert dev_redact.text(value) == value


def test_auth_is_a_whole_component_and_quotes_end_bare_values():
    assert dev_redact.text('auth=hidden auth_token=hidden') == 'auth=[redacted:secret] auth_token=[redacted:secret]'
    assert dev_redact.text('token=hidden" followed by prose') == 'token=[redacted:secret]" followed by prose'
    assert dev_redact.text('--token hidden" followed by prose') == '--token [redacted:secret]" followed by prose'
    assert dev_redact.deep({'author': 'Kevin', 'auth': '$VAR', 'token': 'false'}) == {
        'author': 'Kevin', 'auth': '$VAR', 'token': 'false'}


def test_flag_boundary_and_dash_line_are_linear():
    from time import perf_counter
    value = '-' * 16000
    started = perf_counter()
    assert dev_redact.text(value) == value
    assert dev_redact.text('--with-token --token abcd1234efgh') == '--with-token --token [redacted:secret]'
    assert dev_redact.text('prefix--token plain') == 'prefix--token plain'
    assert perf_counter() - started < 3  # Regression previously took 14 seconds.


@pytest.mark.parametrize('sender', ['kevin', 'session', 'device', 'dev'])
@pytest.mark.parametrize('work', [False, True])
def test_only_kevin_notes_bypass_redaction(relay, monkeypatch, sender, work):
    import chief_local_work
    task = {'id': 't', 'notes': []}
    relay.tables['dev_tasks'].append(task)
    stored = []
    monkeypatch.setattr(dev_bridge, '_is_work', lambda _: work)

    async def db(method, path, body):
        stored.append(body['note'])
    monkeypatch.setattr(chief_local_work, 'db', db)
    raw = 'Use --token abcd1234efgh'
    run(dev_bridge._append_note(None, task, sender, raw))
    note = stored[0] if work else relay.tables['dev_tasks'][0]['notes'][0]
    assert note['text'] == (raw if sender == 'kevin' else 'Use --token [redacted:secret]')


def test_large_text_runs_off_loop_and_propagates_failure(monkeypatch):
    import threading
    main_thread = threading.get_ident()
    seen = []
    original = dev_redact.text

    def checked(value):
        seen.append(threading.get_ident())
        return original(value)
    monkeypatch.setattr(dev_redact, 'text', checked)
    value = ' ' * dev_redact.THREAD_THRESHOLD + 'token=hidden'
    assert run(dev_redact.text_async(value)).endswith('token=[redacted:secret]')
    assert seen and all(t != main_thread for t in seen)

    def broken(value):
        raise RuntimeError('redaction failed')
    monkeypatch.setattr(dev_redact, 'text', broken)
    with pytest.raises(RuntimeError, match='redaction failed'):
        run(dev_redact.text_async(value))


def test_nonsensitive_label_does_not_swallow_secret_assignment():
    assert dev_redact.text("note: token=hidden") == "note: token=[redacted:secret]"
