"""
test_public_site_url.py — print the address the owner actually uses.

KEVIN, 2026-08-10: "it has the email signature with the default website
not the domain site that i have."

kmjcreate.com had been verified for weeks. Both _compose_footer and
_compose_signature built the url from the site SLUG and never looked at
the custom domain, so every signature, footer and copyright line the
platform published named an address the owner had already replaced.

The rule with teeth is the status check: a PENDING domain has no DNS
behind it, and a dead address in an email signature is worse than a
working default.
"""
import brand_engine


def _site(domain=None, status=None, slug="kmj-creative-solutions"):
    return {"slug": slug, "site_config": {
        "custom_domain": domain, "custom_domain_status": status}}


def test_a_verified_domain_wins():
    assert brand_engine.public_site_url(
        _site("kmjcreate.com", "verified")) == "https://kmjcreate.com"


def test_a_pending_domain_does_not():
    """THE RULE WITH TEETH. Pending means DNS is not there yet — printing
    it puts a dead link in every email the practitioner sends."""
    assert brand_engine.public_site_url(_site("kmjcreate.com", "pending")) \
        == "https://kmj-creative-solutions.mysolutionist.app"


def test_no_domain_falls_back_to_the_platform_subdomain():
    assert brand_engine.public_site_url(_site()) \
        == "https://kmj-creative-solutions.mysolutionist.app"


def test_owners_type_their_domain_in_every_shape():
    """It is a text field. People paste a full url and hold shift."""
    for typed in ("https://kmjcreate.com", "http://kmjcreate.com",
                  "  KMJCreate.COM  ", "kmjcreate.com"):
        assert brand_engine.public_site_url(_site(typed, "verified")) \
            == "https://kmjcreate.com", typed


def test_never_emits_a_double_scheme():
    url = brand_engine.public_site_url(_site("https://kmjcreate.com", "verified"))
    assert url.count("https://") == 1


def test_no_site_and_no_slug_give_nothing_rather_than_a_broken_url():
    assert brand_engine.public_site_url(None) is None
    assert brand_engine.public_site_url({"slug": None, "site_config": {}}) is None


def test_the_signature_and_the_footer_agree(monkeypatch):
    """Both are printed as the practitioner, so they must never disagree
    about where the practitioner lives."""
    def fake_one(table, col, val):
        if table == "businesses":
            return {"id": "biz-1", "name": "KMJ", "owner_id": "o1", "settings": {}}
        if table == "business_sites":
            return _site("kmjcreate.com", "verified")
        return {}
    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    b = brand_engine.get_bundle("biz-1", use_cache=False)
    assert b["signature_block"]["site_url"] == "https://kmjcreate.com"
    assert b["footer"]["site_url"] == "https://kmjcreate.com"
