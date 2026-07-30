# __tests__/test_custom_domain_www.py
"""www custom-hostname coverage (the www.kmjcreate.com outage, 2026-07-29).

Cloudflare-for-SaaS certs are issued PER HOSTNAME. The connect flow used to
register only the apex — while its own DNS instructions told the practitioner
to point www at the edge, so every correctly-configured www served no cert
(HANDSHAKE_FAILURE_ON_CLIENT_HELLO). The serving side was www-blind too:
custom_domain lookups matched the raw Host against the stored apex, so www
would 404 even with a cert.

Covers: both registrations on connect, www DNS record naming relative to the
apex, verify's non-blocking www report + self-heal backfill, disconnect
deleting both, and the www strip in the public-site lookup.
"""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest import mock

CF_ENV = {"CF_API_TOKEN": "tok", "CF_ZONE_ID": "zone",
          "CF_SAAS_CNAME_TARGET": "saas-origin.mysolutionist.app"}


def _ch(hostname, active=True, txt_name=None):
    """A Cloudflare custom-hostname API object, shaped."""
    return {
        "id": f"id-{hostname}",
        "hostname": hostname,
        "status": "active" if active else "pending",
        "ssl": {
            "status": "active" if active else "pending_validation",
            "validation_records": [
                {"txt_name": txt_name or f"_acme-challenge.{hostname}",
                 "txt_value": f"val-{hostname}"}],
        },
    }


class TestShapeWwwRecords(unittest.TestCase):
    """DNS instructions must name records the way providers expect —
    relative to the REGISTERED domain, not the full www hostname."""

    def test_apex_shape_unchanged(self):
        import cloudflare_saas as cf
        with mock.patch.dict(os.environ, CF_ENV):
            shaped = cf._shape(_ch("kmjcreate.com"))
        cname = [d for d in shaped["dns"] if d["type"] == "CNAME"][0]
        self.assertEqual(cname["host"], "@")
        txt = [d for d in shaped["dns"] if d["type"] == "TXT"][0]
        self.assertEqual(txt["host"], "_acme-challenge")

    def test_www_records_named_relative_to_apex(self):
        import cloudflare_saas as cf
        with mock.patch.dict(os.environ, CF_ENV):
            shaped = cf._shape(_ch("www.kmjcreate.com"), apex="kmjcreate.com")
        cname = [d for d in shaped["dns"] if d["type"] == "CNAME"][0]
        self.assertEqual(cname["host"], "www")
        txt = [d for d in shaped["dns"] if d["type"] == "TXT"][0]
        # '_acme-challenge' alone would validate the APEX cert, never www.
        self.assertEqual(txt["host"], "_acme-challenge.www")

    def test_www_without_apex_would_misname(self):
        """The bug the apex param exists to prevent: shaped against the full
        www hostname, the TXT shortens to '_acme-challenge' — wrong record."""
        import cloudflare_saas as cf
        with mock.patch.dict(os.environ, CF_ENV):
            shaped = cf._shape(_ch("www.kmjcreate.com"))
        txt = [d for d in shaped["dns"] if d["type"] == "TXT"][0]
        self.assertEqual(txt["host"], "_acme-challenge")  # documents the trap


def _session():
    return SimpleNamespace(user=SimpleNamespace(id="user-1"))


class _ConnectHarness:
    """connect_domain with everything but the CF calls stubbed out."""

    def __enter__(self):
        import site_composer as sc
        self.sc = sc
        self.patched = [
            mock.patch.object(sc, "_require_owner", lambda b, u: None),
            mock.patch.object(sc, "_load_site_cfg",
                              lambda b: ("my-slug", {}, {"slug": "my-slug"})),
            mock.patch.object(sc.sb_clients, "sb_get_as_service",
                              lambda q: []),  # uniqueness check: unclaimed
            mock.patch.object(sc.sb_clients, "sb_patch_as_service",
                              mock.MagicMock()),
        ]
        for p in self.patched:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patched:
            p.stop()


class TestConnectRegistersBoth(unittest.TestCase):

    def test_connect_registers_apex_and_www(self):
        import cloudflare_saas as cf
        import site_composer as sc
        calls = []

        def fake_create(hostname, apex=None):
            calls.append((hostname, apex))
            return cf._shape(_ch(hostname, active=False), apex)

        with _ConnectHarness(), \
                mock.patch.dict(os.environ, CF_ENV), \
                mock.patch.object(cf, "create_custom_hostname", fake_create):
            body = sc.DomainConnectBody(business_id="b1", domain="KMJcreate.com")
            out = sc.connect_domain(body, session=_session())

        self.assertEqual(calls, [("kmjcreate.com", None),
                                 ("www.kmjcreate.com", "kmjcreate.com")])
        self.assertEqual(out["cert"], "cloudflare")
        hosts = [d["host"] for d in out["dns"]]
        # One combined instruction list: apex CNAME + apex DCV + www CNAME + www DCV.
        self.assertIn("@", hosts)
        self.assertIn("www", hosts)
        self.assertIn("_acme-challenge", hosts)
        self.assertIn("_acme-challenge.www", hosts)

    def test_www_skipped_when_apex_registration_fails(self):
        """Fail-open stays coherent: no apex hostname → no www orphan."""
        import cloudflare_saas as cf
        import site_composer as sc
        calls = []

        def fake_create(hostname, apex=None):
            calls.append(hostname)
            return None

        with _ConnectHarness(), \
                mock.patch.dict(os.environ, CF_ENV), \
                mock.patch.object(cf, "create_custom_hostname", fake_create):
            body = sc.DomainConnectBody(business_id="b1", domain="kmjcreate.com")
            out = sc.connect_domain(body, session=_session())

        self.assertEqual(calls, ["kmjcreate.com"])
        self.assertEqual(out["cert"], "manual")

    def test_stored_config_carries_both_ids(self):
        import cloudflare_saas as cf
        import site_composer as sc

        def fake_create(hostname, apex=None):
            return cf._shape(_ch(hostname, active=False), apex)

        with _ConnectHarness() as h, \
                mock.patch.dict(os.environ, CF_ENV), \
                mock.patch.object(cf, "create_custom_hostname", fake_create):
            body = sc.DomainConnectBody(business_id="b1", domain="kmjcreate.com")
            sc.connect_domain(body, session=_session())
            patch_mock = h.sc.sb_clients.sb_patch_as_service
            cfg = patch_mock.call_args[0][1]["site_config"]

        self.assertEqual(cfg["custom_domain_cf_id"], "id-kmjcreate.com")
        self.assertEqual(cfg["custom_domain_cf_www_id"], "id-www.kmjcreate.com")


class _VerifyHarness:
    def __init__(self, cfg):
        self.cfg = cfg

    def __enter__(self):
        import site_composer as sc
        self.sc = sc
        self.patch_mock = mock.MagicMock()
        self.patched = [
            mock.patch.object(sc, "_require_owner", lambda b, u: None),
            mock.patch.object(sc, "_load_site_cfg",
                              lambda b: ("my-slug", self.cfg, {})),
            mock.patch.object(sc.sb_clients, "sb_patch_as_service", self.patch_mock),
        ]
        for p in self.patched:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patched:
            p.stop()


class TestVerifyWww(unittest.TestCase):

    def test_apex_active_www_pending_still_verifies(self):
        """www must never hold verification hostage — the apex governs."""
        import cloudflare_saas as cf
        import site_composer as sc

        def fake_status(hostname, apex=None):
            if hostname.startswith("www."):
                return {"found": True, **cf._shape(_ch(hostname, active=False), apex)}
            return {"found": True, **cf._shape(_ch(hostname, active=True))}

        with _VerifyHarness({"custom_domain": "kmjcreate.com"}), \
                mock.patch.dict(os.environ, CF_ENV), \
                mock.patch.object(cf, "hostname_status", fake_status):
            out = sc.verify_domain(sc.DomainVerifyBody(business_id="b1"),
                                   session=_session())

        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "verified")
        self.assertFalse(out["www_ok"])
        # The practitioner still sees what www needs.
        self.assertIn("_acme-challenge.www", [d["host"] for d in out["dns"]])

    def test_both_active_reports_www_ok(self):
        import cloudflare_saas as cf
        import site_composer as sc

        def fake_status(hostname, apex=None):
            return {"found": True, **cf._shape(_ch(hostname, active=True), apex)}

        with _VerifyHarness({"custom_domain": "kmjcreate.com"}), \
                mock.patch.dict(os.environ, CF_ENV), \
                mock.patch.object(cf, "hostname_status", fake_status):
            out = sc.verify_domain(sc.DomainVerifyBody(business_id="b1"),
                                   session=_session())

        self.assertTrue(out["ok"])
        self.assertTrue(out["www_ok"])
        self.assertEqual(out["dns"], [])

    def test_missing_www_is_backfilled(self):
        """Domains connected before the www fix (kmjcreate itself): verify
        registers www on the spot and persists the new hostname id."""
        import cloudflare_saas as cf
        import site_composer as sc
        created = []

        def fake_status(hostname, apex=None):
            if hostname.startswith("www."):
                return {"found": False}
            return {"found": True, **cf._shape(_ch(hostname, active=True))}

        def fake_create(hostname, apex=None):
            created.append((hostname, apex))
            return cf._shape(_ch(hostname, active=False), apex)

        with _VerifyHarness({"custom_domain": "kmjcreate.com"}) as h, \
                mock.patch.dict(os.environ, CF_ENV), \
                mock.patch.object(cf, "hostname_status", fake_status), \
                mock.patch.object(cf, "create_custom_hostname", fake_create):
            out = sc.verify_domain(sc.DomainVerifyBody(business_id="b1"),
                                   session=_session())

        self.assertEqual(created, [("www.kmjcreate.com", "kmjcreate.com")])
        self.assertTrue(out["ok"])          # apex active → verified regardless
        self.assertFalse(out["www_ok"])
        # The new www id must be PERSISTED, not just mutated in memory.
        stored = [c.args[1]["site_config"] for c in
                  h.patch_mock.call_args_list]
        self.assertTrue(any(c.get("custom_domain_cf_www_id") ==
                            "id-www.kmjcreate.com" for c in stored))


class TestDisconnectDeletesBoth(unittest.TestCase):

    def test_disconnect_removes_both_hostnames_and_ids(self):
        import cloudflare_saas as cf
        import site_composer as sc
        deleted = []
        cfg = {"custom_domain": "kmjcreate.com",
               "custom_domain_cf_id": "a", "custom_domain_cf_www_id": "w",
               "custom_domain_status": "verified", "custom_domain_token": "t"}
        patch_mock = mock.MagicMock()
        with mock.patch.object(sc, "_require_owner", lambda b, u: None), \
                mock.patch.object(sc, "_load_site_cfg", lambda b: ("s", cfg, {})), \
                mock.patch.object(sc.sb_clients, "sb_patch_as_service", patch_mock), \
                mock.patch.object(cf, "delete_custom_hostname",
                                  lambda h: deleted.append(h)):
            sc.disconnect_domain(sc.DomainVerifyBody(business_id="b1"),
                                 session=_session())
        self.assertEqual(deleted, ["kmjcreate.com", "www.kmjcreate.com"])
        stored = patch_mock.call_args[0][1]["site_config"]
        for k in ("custom_domain", "custom_domain_cf_id",
                  "custom_domain_cf_www_id", "custom_domain_status",
                  "custom_domain_token"):
            self.assertNotIn(k, stored)


class TestServeStripsWww(unittest.TestCase):
    """A www visitor must reach the site stored under the apex — the DB only
    ever stores the apex (connect's normalizer strips www)."""

    def _lookup_domains(self, host):
        import public_site as ps
        queried = []

        async def fake_sb(client, query):
            queried.append(query)
            return []  # not found → function returns None, that's fine

        with mock.patch.object(ps, "_sb", fake_sb):
            asyncio.run(ps._serve_site_by_custom_domain(host))
        return queried

    def test_www_host_queries_apex(self):
        queries = self._lookup_domains("www.kmjcreate.com")
        self.assertTrue(queries)
        for q in queries:
            self.assertIn("eq.kmjcreate.com", q)
            self.assertNotIn("www.", q)

    def test_apex_host_unchanged(self):
        queries = self._lookup_domains("kmjcreate.com")
        self.assertTrue(queries)
        self.assertIn("eq.kmjcreate.com", queries[0])


if __name__ == "__main__":
    unittest.main()
