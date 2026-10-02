"""Vault confidentiality, context binding, and failure behavior; no real secrets."""
import json
import pathlib
import sys

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import secret_vault as vault

BINDING = {'business_id': '10000000-0000-4000-8000-000000000001',
           'secret_id': '20000000-0000-4000-8000-000000000002', 'host': 'supplier.example'}
FIELDS = {'username': 'fixture-user', 'password': '  fixture-only-pässword 🔒  '}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    generated = Fernet.generate_key()
    monkeypatch.setenv('VAULT_ENCRYPTION_KEY', generated.decode())
    return generated


def test_roundtrip_keeps_whitespace_unicode_and_hides_plaintext(caplog):
    token = vault.encrypt(FIELDS, **BINDING)
    assert all(v not in token for v in FIELDS.values())
    assert vault.decrypt(token, **BINDING) == FIELDS
    assert vault.encrypt(FIELDS, **BINDING) != token  # randomized authenticated encryption
    assert not caplog.records


@pytest.mark.parametrize('configured', [None, '', ' ', 'invalid-key', '🔒'])
def test_missing_or_invalid_key_fails_closed_without_tin_fallback(monkeypatch, configured):
    monkeypatch.setenv('TIN_ENCRYPTION_KEY', Fernet.generate_key().decode())
    if configured is None:
        monkeypatch.delenv('VAULT_ENCRYPTION_KEY')
    else:
        monkeypatch.setenv('VAULT_ENCRYPTION_KEY', configured)
    for operation in (lambda: vault.encrypt(FIELDS, **BINDING),
                      lambda: vault.decrypt('not-a-secret', **BINDING)):
        with pytest.raises(HTTPException) as exc:
            operation()
        assert exc.value.status_code == 500
        assert FIELDS['password'] not in str(exc.value)


@pytest.mark.parametrize('field,value', [
    ('business_id', '30000000-0000-4000-8000-000000000003'),
    ('secret_id', '40000000-0000-4000-8000-000000000004'),
    ('host', 'other.supplier.example'),
])
def test_ciphertext_cannot_be_reassigned_to_another_tenant_row_or_host(field, value):
    token = vault.encrypt(FIELDS, **BINDING)
    with pytest.raises(HTTPException) as exc:
        vault.decrypt(token, **{**BINDING, field: value})
    assert exc.value.status_code == 500
    assert token not in str(exc.value)


def test_key_replacement_and_ciphertext_tampering_are_generic_failures(monkeypatch, caplog):
    token = vault.encrypt(FIELDS, **BINDING)
    with pytest.raises(HTTPException, match='Stored secret cannot be decrypted'):
        vault.decrypt(token[:60] + ('A' if token[60] != 'A' else 'B') + token[61:], **BINDING)
    monkeypatch.setenv('VAULT_ENCRYPTION_KEY', Fernet.generate_key().decode())
    with pytest.raises(HTTPException, match='Stored secret cannot be decrypted'):
        vault.decrypt(token, **BINDING)
    assert not caplog.records


@pytest.mark.parametrize('payload', [[], {}, {'version': 2},
    {'version': 1, **BINDING, 'kind': 'login', 'fields': {**FIELDS, 'cvc': '123'}},
    {'version': 1, **BINDING, 'kind': 'login', 'fields': FIELDS, 'unexpected': 'value'}])
def test_authenticated_but_malformed_envelopes_are_not_returned(key, payload):
    token = Fernet(key).encrypt(json.dumps(payload).encode()).decode()
    with pytest.raises(HTTPException) as exc:
        vault.decrypt(token, **BINDING)
    assert exc.value.status_code == 500


@pytest.mark.parametrize('fields', [None, {}, {'username': 'u'},
    {**FIELDS, 'cvc': '123'}, {**FIELDS, 'code': '123456'},
    {'username': 'u', 'password': {'otp': '123456'}},
    {'username': 'u', 'password': ''}, {'username': 'u', 'password': 'a' * 4097}])
def test_only_bounded_login_fields_may_be_persisted(fields):
    with pytest.raises(HTTPException) as exc:
        vault.encrypt(fields, **BINDING)
    assert exc.value.status_code == 422


@pytest.mark.parametrize('kind', ['card', 'otp', 'session', 'custom'])
def test_unreviewed_secret_kinds_cannot_be_saved(kind):
    with pytest.raises(HTTPException) as exc:
        vault.encrypt(FIELDS, kind=kind, **BINDING)
    assert exc.value.status_code == 422


def test_large_unicode_cannot_produce_ciphertext_that_cannot_be_read():
    with pytest.raises(HTTPException) as exc:
        vault.encrypt({'username': '🔒' * 4096, 'password': '🔒' * 4096}, **BINDING)
    assert exc.value.status_code == 422


@pytest.mark.parametrize('host', ['https://supplier.example', 'supplier.example:443',
    '*.supplier.example', 'user@supplier.example', 'supplier.example/path',
    'supplier.example?secret=x', 'supplier.example..', '127.0.0.1', '[::1]',
    'localhost', 'x.local', 'x.internal', ' supplier.example', 'supplier.example\n'])
def test_hosts_cannot_include_urls_or_credentials(host):
    with pytest.raises(HTTPException) as exc:
        vault.encrypt(FIELDS, **{**BINDING, 'host': host})
    assert exc.value.status_code == 422


def test_canonical_exact_host_binding():
    token = vault.encrypt(FIELDS, **{**BINDING, 'host': 'Supplier.Example.'})
    assert vault.decrypt(token, **BINDING) == FIELDS


def test_metadata_uses_an_allowlist_and_never_copies_nested_credential_data():
    row = {'id': BINDING['secret_id'], 'business_id': BINDING['business_id'],
           'host': BINDING['host'], 'kind': 'login', 'label': 'Supplier login',
           'fields_ciphertext': 'ciphertext-fixture', 'password': FIELDS['password'],
           'display': {'password': FIELDS['password'], 'username_hint': FIELDS['username']}}
    public = vault.secret_metadata(row)
    assert set(public) == {'id', 'kind', 'host', 'label', 'display', 'created_at', 'last_used_at', 'use_count'}
    assert 'ciphertext-fixture' not in json.dumps(public)
    assert all(v not in json.dumps(public, ensure_ascii=False) for v in FIELDS.values())
    assert 'fields_ciphertext' not in vault.METADATA_COLUMNS.split(',')
    assert '*' not in vault.METADATA_COLUMNS and '*' not in vault.FILL_COLUMNS


def test_vault_is_excluded_from_exports_and_errands_cannot_be_imported():
    import account_lifecycle as lifecycle
    assert 'business_secrets' in lifecycle.EXPORT_EXCLUDED
    assert 'business_secrets' not in lifecycle.BUSINESS_CHILD_TABLES
    for table in ('chief_errands', 'chief_errand_events'):
        assert table in lifecycle.BUSINESS_CHILD_TABLES
        assert table in lifecycle._IMPORT_SKIP
