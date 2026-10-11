"""Document checks: outgoing files hashed into the ledger; a public check by hash.

Database, DocuSeal and email doubles only; no production reads or writes.
"""
import asyncio
import base64
import hashlib
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import document_ledger as dl

BIZ = '11111111-1111-4111-8111-111111111111'
PDF = b'%PDF-1.7 the executed agreement'
SHA = hashlib.sha256(PDF).hexdigest()


@pytest.fixture
def ledger(monkeypatch):
    rows = []
    import audit_log

    def record(business_id, **k):
        rows.append({'business_id': business_id, **k})
        return True
    monkeypatch.setattr(audit_log, 'record', record)
    return rows


# ── recording ───────────────────────────────────────────────────────────

def test_doc_fields_hash_the_exact_bytes_or_say_they_were_not():
    f = dl.doc_fields(PDF, kind='signed_agreement', label='  Coaching  agreement ')
    assert f == {'doc_kind': 'signed_agreement', 'doc_label': 'Coaching agreement',
                 'doc_sha256': SHA, 'doc_bytes': len(PDF)}
    missing = dl.doc_fields(None, kind='signed_agreement', label='x')
    assert missing['doc_hashed'] is False and 'doc_sha256' not in missing


def test_record_document_writes_one_ledger_row(ledger):
    assert dl.record_document(BIZ, PDF, kind='contract_pdf', label='Proposal',
                              actor_type='chief') == SHA
    row = ledger[0]
    assert row['verb'] == 'document_recorded' and row['actor_type'] == 'chief'
    assert row['payload']['doc_sha256'] == SHA and row['payload']['doc_kind'] == 'contract_pdf'


def test_record_document_never_breaks_the_flow(monkeypatch):
    import audit_log
    monkeypatch.setattr(audit_log, 'record', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('db down')))
    assert dl.record_document(BIZ, PDF, kind='contract_pdf') is None
    assert dl.record_document(BIZ, b'', kind='contract_pdf') is None
    assert dl.record_document(None, PDF, kind='contract_pdf') is None


# ── DocuSeal completion ─────────────────────────────────────────────────

def _esign_env(monkeypatch, ledger, pdf_b64):
    import docuseal_router as dr
    import event_spine
    sent, fetches = [], []
    monkeypatch.setattr(dr.sb_clients, 'sb_patch_as_service', lambda path, body: None)
    monkeypatch.setattr(event_spine, 'emit', lambda *a, **k: None)

    async def fetch(document_id):
        fetches.append(document_id)
        if isinstance(pdf_b64, Exception):
            raise pdf_b64
        return pdf_b64
    monkeypatch.setattr(dr, '_signed_pdf_b64', fetch)

    async def owner_email(owner_id):
        return 'owner@example.com'
    monkeypatch.setattr(dr, '_owner_email', owner_email)
    import email_sender

    async def send(**kw):
        sent.append(kw)
        return {'id': 'x'}
    monkeypatch.setattr(email_sender, 'send_via_resend', send)
    doc = {'id': 'row1', 'document_id': 'sub-9', 'status': 'sent', 'title': 'Coaching agreement',
           'signer_email': 'client@example.com', 'signer_name': 'Ana'}
    biz = {'id': BIZ, 'owner_id': 'o1', 'name': 'Fade Room'}
    return dr, doc, biz, sent, fetches


def test_signed_agreement_hash_lands_in_the_completion_row(monkeypatch, ledger):
    dr, doc, biz, sent, fetches = _esign_env(monkeypatch, ledger, base64.b64encode(PDF).decode())
    asyncio.run(dr._apply_status(doc, biz, 'completed'))
    row = next(r for r in ledger if r['verb'] == 'esign_completed')
    assert row['payload']['doc_sha256'] == SHA and row['payload']['doc_kind'] == 'signed_agreement'
    assert fetches == ['sub-9'], 'the executed copy is fetched once'
    assert sent and all(base64.b64decode(s['attachments'][0]['content']) == PDF for s in sent), \
        'the hashed bytes are the bytes both parties receive'


@pytest.mark.parametrize('failure', [None, RuntimeError('docuseal down')])
def test_a_failed_fetch_is_recorded_as_unhashed_and_the_flow_goes_on(monkeypatch, ledger, failure):
    dr, doc, biz, sent, _ = _esign_env(monkeypatch, ledger, failure)
    out = asyncio.run(dr._apply_status(doc, biz, 'completed'))
    assert out['changed'] is True
    row = next(r for r in ledger if r['verb'] == 'esign_completed')
    assert row['payload']['doc_hashed'] is False and 'doc_sha256' not in row['payload']
    assert sent and sent[0].get('attachments') is None, 'the email still goes, without the file'


def test_a_slow_fetch_is_bounded(monkeypatch, ledger):
    dr, doc, biz, sent, _ = _esign_env(monkeypatch, ledger, None)
    monkeypatch.setattr(dr, 'SIGNED_COPY_TIMEOUT_S', 0.05)

    async def slow(document_id):
        await asyncio.sleep(5)
        return base64.b64encode(PDF).decode()
    monkeypatch.setattr(dr, '_signed_pdf_b64', slow)
    asyncio.run(dr._apply_status(doc, biz, 'completed'))
    row = next(r for r in ledger if r['verb'] == 'esign_completed')
    assert row['payload']['doc_hashed'] is False


# ── Chief's contract PDF ────────────────────────────────────────────────

def test_contract_pdf_is_recorded(monkeypatch, ledger):
    import chief_contract_actions as cca
    import contract_agent as ca
    contact = {'id': 'c1', 'name': 'Marcus', 'metadata': {}, 'role': ''}
    row = {'id': 'q9', 'subject': 'Engagement Letter', 'body': 'Terms...', 'contact_id': 'c1'}
    monkeypatch.setattr(cca.sb_clients, 'sb_get_as_service',
                        lambda q: [contact] if '/contacts?' in q else ([row] if '/agent_queue?' in q else []))
    monkeypatch.setattr(ca, '_build_pdf', lambda **kw: PDF)

    async def upload(client, data, biz_id, contact_id):
        return 'https://sb.example.com/x.pdf'
    monkeypatch.setattr(ca, '_upload_pdf_to_supabase', upload)
    out = asyncio.run(cca.handle_contract_pdf(None, {'id': BIZ, 'name': 'Webb', 'settings': {}},
                                              {'contact_name': 'Marcus'}))
    assert out['doc_sha256'] == SHA and out['result'] and out['label']
    assert ledger[-1]['payload']['doc_kind'] == 'contract_pdf'


# ── the public check ────────────────────────────────────────────────────

@pytest.fixture
def public(monkeypatch):
    st = SimpleNamespace(rows=[], verify={'intact': True}, anchors=[], reads=[])

    def get(path):
        st.reads.append(path)
        if path.startswith('/audit_log?'):
            return [r for r in st.rows if f"eq.{r['payload'].get('doc_sha256')}" in path]
        if path.startswith('/businesses?'):
            return [{'name': 'Fade Room'}]
        if path.startswith('/ledger_anchors?'):
            return st.anchors
        if path.startswith('/ledger_anchor_upgrades?'):
            return []
        return []

    def post(path, body, *a, **k):
        if path == '/rpc/ledger_verify':
            if isinstance(st.verify, Exception):
                raise st.verify
            return [st.verify]
        return None
    monkeypatch.setattr(dl.sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(dl.sb_clients, 'sb_post_as_service', post)
    import ledger_anchor
    monkeypatch.setattr(ledger_anchor.sb_clients, 'sb_get_as_service', get, raising=False)
    import rate_limit
    monkeypatch.setattr(rate_limit, 'allow_strict', lambda *a, **k: True)
    app = FastAPI()
    app.include_router(dl.router)
    st.client = TestClient(app)
    return st


def _row(seq=41, kind='signed_agreement'):
    return {'business_id': BIZ, 'sequence': seq, 'created_at': '2026-10-12T15:04:22.000Z',
            'row_hash': 'a' * 64,
            'payload': {'doc_sha256': SHA, 'doc_kind': kind, 'doc_label': 'Agreement with Ana Ruiz'}}


def test_a_match_returns_facts_and_nothing_else(public):
    public.rows.append(_row())
    r = public.client.post('/public/verify/document', json={'sha256': SHA.upper()})
    assert r.status_code == 200
    body = r.json()
    assert body['match'] is True
    rec = body['records'][0]
    assert set(rec) == {'business', 'document', 'recorded_at', 'ledger_record',
                        'chain_verifies_here', 'public_anchors', 'statement'}
    assert rec['statement'] == 'This file matches the signed agreement Fade Room recorded on 2026-10-12.'
    assert rec['chain_verifies_here'] is True and rec['ledger_record'] == 41
    assert 'Ana' not in r.text and 'doc_label' not in r.text and BIZ not in r.text


def test_no_match_says_so_plainly(public):
    r = public.client.post('/public/verify/document', json={'sha256': 'b' * 64})
    assert r.json() == {'match': False, 'message': dl.NO_MATCH}


def test_input_is_validated_and_rate_limited(public, monkeypatch):
    for bad in ('', 'xyz', 'g' * 64, 'a' * 63, SHA + "' or 1=1"):
        assert public.client.post('/public/verify/document', json={'sha256': bad}).status_code == 422
    import rate_limit
    monkeypatch.setattr(rate_limit, 'allow_strict', lambda *a, **k: False)
    assert public.client.post('/public/verify/document', json={'sha256': SHA}).status_code == 429


def test_chain_state_is_reported_never_rounded(public):
    public.rows.append(_row(seq=41))
    public.verify = {'intact': False, 'broken_at': 90}
    assert dl.lookup(SHA)['records'][0]['chain_verifies_here'] is True, 'broken after this row'
    public.verify = {'intact': False, 'broken_at': 12}
    assert dl.lookup(SHA)['records'][0]['chain_verifies_here'] is False
    public.verify = RuntimeError('rpc down')
    assert dl.lookup(SHA)['records'][0]['chain_verifies_here'] is None


def test_only_public_anchors_count(public, monkeypatch):
    import ledger_anchor
    public.rows.append(_row(seq=41))
    public.anchors = [{'id': 'a1', 'provider': 'local', 'provider_ref': None, 'anchored_at': 't'},
                      {'id': 'a2', 'provider': 'opentimestamps', 'provider_ref': 'x', 'anchored_at': 't2'}]
    monkeypatch.setattr(ledger_anchor, 'is_independent', lambda p: p == 'opentimestamps')
    monkeypatch.setattr(ledger_anchor, 'proof_status',
                        lambda ref, provider=None: {'confirmed': True, 'bitcoin_block': 961016})
    anchors = dl.lookup(SHA)['records'][0]['public_anchors']
    assert anchors == [{'network': 'Bitcoin', 'anchored_at': 't2', 'status': 'confirmed',
                        'bitcoin_block': 961016, 'verify_url': None}]


def test_the_page_sends_only_the_hash():
    page = dl.PAGE
    assert page.count('fetch(') == 1
    assert "body:JSON.stringify({sha256:hex})" in page
    assert 'FormData' not in page and 'readAsDataURL' not in page and 'body:file' not in page
    assert "crypto.subtle.digest('SHA-256'" in page


def test_the_page_serves_with_no_store(public):
    r = public.client.get('/public/verify')
    assert r.status_code == 200 and 'Check a document' in r.text
    assert 'no-store' in r.headers.get('cache-control', '')


def test_wording_states_facts_and_never_vouches():
    words = dl.PAGE + dl.NO_MATCH + ' '.join(dl.KIND_LABELS.values()) + \
        'This file matches the signed agreement Fade Room recorded on 2026-10-12.'
    for banned in ('trusted', 'trustworthy', 'legitimate', 'safe', 'authentic', 'guarantee'):
        assert not re.search(rf'\b{banned}\b', words, re.I), banned
