"""Apple Pay / Google Pay inside the give page: the domains registered
on the church's own Stripe account, and the file Apple checks."""
import inspect

import httpx
import pytest

import payment_domains as pd


def test_give_domains_cover_subdomain_custom_domain_and_www():
    assert pd.give_domains("love-city", "lovecityc.com") == [
        "love-city.mysolutionist.app", "lovecityc.com", "www.lovecityc.com"]
    # Stored with www by hand: still apex + www, once each.
    assert pd.give_domains("love-city", "WWW.LoveCityC.com/") == [
        "love-city.mysolutionist.app", "lovecityc.com", "www.lovecityc.com"]
    assert pd.give_domains("love-city", None) == ["love-city.mysolutionist.app"]
    assert pd.give_domains(None, "") == []
    # Junk never reaches Stripe.
    assert pd.give_domains("bad slug!", "not a domain") == []


def test_register_for_business_merges_sites_without_duplicates(monkeypatch):
    got = {}
    monkeypatch.setattr(pd, "register_give_domains",
                        lambda acct, domains: got.update(acct=acct, domains=domains) or {})
    pd.register_for_business({"stripe_account_id": "acct_9"}, [
        {"slug": "love-city", "custom_domain": "lovecityc.com"},
        {"slug": "love-city", "custom_domain": None}])
    assert got == {"acct": "acct_9", "domains": [
        "love-city.mysolutionist.app", "lovecityc.com", "www.lovecityc.com"]}
    got.clear()
    assert pd.register_for_business({"stripe_account_id": "acct_9"}, []) == {} and not got


class _FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, auth=None, headers=None, data=None):
        self.calls.append((url, headers, data))
        r = self.replies[data["domain_name"]]
        if isinstance(r, Exception):
            raise r
        return r


def _resp(code, message=None):
    body = {"error": {"message": message}} if message else {"id": "pmd_1"}
    return httpx.Response(code, json=body)


def test_register_reports_each_domain_and_treats_existing_as_done(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    fake = _FakeClient({
        "a.mysolutionist.app": _resp(200),
        "lovecityc.com": _resp(400, "Domain already registered on this account."),
        "www.lovecityc.com": _resp(500, "boom"),
        "x.example.org": httpx.ConnectError("down"),
    })
    monkeypatch.setattr(pd.httpx, "Client", lambda timeout=None: fake)
    out = pd.register_give_domains(
        "acct_123", ["a.mysolutionist.app", "lovecityc.com", "www.lovecityc.com", "x.example.org"])
    assert out == {"a.mysolutionist.app": "registered", "lovecityc.com": "already",
                   "www.lovecityc.com": "failed", "x.example.org": "failed"}
    url, headers, data = fake.calls[0]
    assert url.endswith("/v1/payment_method_domains")
    # Direct charges: the domain belongs on the church's account, not ours.
    assert headers == {"Stripe-Account": "acct_123"}
    assert data == {"domain_name": "a.mysolutionist.app"}


@pytest.mark.parametrize("key,acct", [("", "acct_1"), ("sk_test_x", ""), ("sk_test_x", "acct 1")])
def test_register_never_calls_stripe_without_a_key_or_real_account(monkeypatch, key, acct):
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    monkeypatch.setattr(pd.httpx, "Client", lambda timeout=None: pytest.fail("called Stripe"))
    assert pd.register_give_domains(acct, ["a.mysolutionist.app"]) == {"a.mysolutionist.app": "failed"}


def test_vendored_apple_file_is_stripes_hex_blob():
    text = pd.apple_association()
    assert text and len(text) > 1000
    assert all(c in "0123456789abcdefABCDEF" for c in text)
    # Hex of '{"pspId":' — the file is Stripe's, not a placeholder.
    assert text.startswith("7B227073704964223A")


def test_every_served_site_answers_the_apple_file():
    import public_site as ps
    assert ps._APPLE_ASSOCIATION_PATH == pd.APPLE_ASSOCIATION_PATH
    for fn in (ps._serve_site_by_slug, ps._serve_site_by_custom_domain):
        src = inspect.getsource(fn)
        assert "_APPLE_ASSOCIATION_PATH" in src and "_apple_association_response()" in src, fn.__name__
    resp = ps._apple_association_response()
    assert resp.body.decode() == pd.apple_association()
