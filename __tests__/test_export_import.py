"""The export is all of it, and something can read it back.

TWO FAULTS.

_fetch_table asked PostgREST for limit=10000 and returned whatever came
back. Nothing paginated and nothing checked, so a business with more
than 10,000 rows in any table exported the first 10,000 and reported
success — while deletion, which has no such cap, removed all of them.
"What we delete is what we export" is this module's stated contract, and
that made it false in the one direction that cannot be undone.

No table is over the cap in production today (largest business-scoped
table is ~3k rows), so it was a loaded gun rather than active loss. It
fires the first time a busy practitioner's events table grows up.

And there was no import. An export nobody can read back is a file, not
portability.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import account_lifecycle as al

FETCH = inspect.getsource(al._fetch_table)
EXPORT = inspect.getsource(al.export_account)
IMPORT = inspect.getsource(al.import_account)


class TestTheExportStoppedTruncating:
    def test_it_pages_rather_than_capping(self):
        assert "offset" in FETCH
        assert "_EXPORT_PAGE" in FETCH
        assert '"limit": "10000"' not in FETCH

    @pytest.mark.parametrize("total,expect_calls", [(0, 1), (5, 1), (1000, 2), (2500, 3)])
    def test_it_keeps_asking_until_a_short_page(self, total, expect_calls):
        """Behavioural, not introspective. The first version of this test
        inspected the return ANNOTATION and carried an `or True`, so it
        asserted nothing at all — it would have passed against the
        truncating implementation it exists to catch."""
        import asyncio

        calls = []

        class _Resp:
            def __init__(self, rows):
                self.status_code = 200
                self._rows = rows

            def json(self):
                return self._rows

        class _Client:
            async def get(self, url, headers=None, params=None):
                off = int(params["offset"])
                calls.append(off)
                page = [{"i": i} for i in range(off, min(off + al._EXPORT_PAGE, total))]
                return _Resp(page)

        rows, complete = asyncio.run(al._fetch_table(_Client(), "events", "b1"))
        assert len(rows) == total, "paging dropped rows"
        assert complete is True
        assert len(calls) == expect_calls

    def test_it_would_have_truncated_before(self, ):
        """Guards the guard: 2,500 rows is more than one page, so a
        single-request implementation could not return them all."""
        assert al._EXPORT_PAGE < 2500

    def test_a_missing_table_is_complete_not_a_failure(self):
        """404 on the FIRST page means the table is absent or unscoped.
        Nothing to export is not the same as failing to export, and
        conflating them would mark every export incomplete."""
        assert "if offset == 0:" in FETCH
        assert "return [], True" in FETCH

    def test_a_LATER_page_failing_marks_it_incomplete(self):
        """This is the dangerous one: a mid-export failure that returns
        the rows so far looks exactly like reaching the end of the data."""
        i = FETCH.index("if offset == 0:")
        after = FETCH[i:i + 500]
        assert "return rows, False" in after

    def test_the_ceiling_is_declared_not_silent(self):
        assert "_EXPORT_MAX_ROWS" in FETCH
        assert "return rows, False" in FETCH

    def test_the_bundle_carries_counts_and_a_completeness_flag(self):
        for token in ('"row_counts"', '"complete"', '"incomplete_tables"'):
            assert token in EXPORT

    def test_the_version_was_bumped(self):
        """An importer must be able to tell a v1 bundle — which may be
        silently short — from a v2 one, which says so."""
        assert '"export_version": 2' in EXPORT


class TestTheImportRefusesTheDangerousThings:
    def test_it_never_writes_into_an_existing_business(self):
        """Merging an export into live data means deciding what wins on
        every conflicting row, and getting that wrong destroys the thing
        they were protecting."""
        assert "/rest/v1/businesses" in IMPORT
        assert '"owner_id": str(user.id)' in IMPORT

    def test_it_strips_ids_rather_than_reusing_them(self):
        """A bundle can be imported twice, or back into the account it
        came from. Reusing ids would collide or silently overwrite."""
        assert "_IMPORT_STRIP" in IMPORT
        assert "id" in al._IMPORT_STRIP
        assert "business_id" in al._IMPORT_STRIP

    def test_it_refuses_to_import_the_ledger(self):
        """audit_log is append-only, per-tenant sequenced and hash
        chained. Imported rows would take new sequences and break the
        chain they exist to prove."""
        assert "audit_log" in al._IMPORT_SKIP

    def test_it_refuses_to_import_live_credentials(self):
        """Re-importing tokens would resurrect access somebody revoked."""
        assert "mcp_tokens" in al._IMPORT_SKIP

    def test_it_restores_parents_before_children(self):
        """The delete list is ordered children-first for FK safety, so
        restoration walks it backwards. Inserting a child before its
        parent fails on the foreign key."""
        assert "reversed(BUSINESS_CHILD_TABLES)" in IMPORT

    def test_one_business_at_a_time(self):
        """A failure halfway through three businesses leaves a mess
        nobody can reason about."""
        assert "len(businesses) != 1" in IMPORT

    def test_an_unknown_version_is_refused(self):
        assert "unsupported export_version" in IMPORT


class TestTheImportTellsTheTruth:
    def test_a_failed_table_is_reported_not_swallowed(self):
        """A partial import that claims success is how somebody finds
        out three months later that their invoices never came back."""
        assert "skipped[table]" in IMPORT
        assert '"skipped": skipped' in IMPORT

    def test_one_bad_table_does_not_abort_the_rest(self):
        """A dropped column should cost that table, not the other
        ninety."""
        assert "break" in IMPORT
        assert "raise" not in IMPORT.split("for table in reversed")[1]

    def test_a_v1_bundle_is_imported_WITH_a_warning(self):
        """Refusing somebody their own data would be worse than importing
        it — but a partial restore must not look complete."""
        assert "version == 1" in IMPORT
        assert "truncated" in IMPORT

    def test_a_self_declared_incomplete_export_warns_too(self):
        assert 'src.get("complete") is False' in IMPORT

    def test_it_records_the_import_in_the_ledger(self):
        assert "import_business" in IMPORT


class TestTheContractBetweenThem:
    def test_export_and_import_agree_on_what_is_portable(self):
        """Everything the import skips must be something the export
        still INCLUDES — the export is the archive, the import is the
        restore, and they answer different questions. If a table stopped
        being exported, skipping it on import would hide the loss."""
        for table in al._IMPORT_SKIP:
            assert table in al.BUSINESS_CHILD_TABLES, (
                f"{table} is skipped on import but no longer exported at all")


# ─── The list cannot rot (2026-09-04) ───────────────────────────────────

import glob
import os
import re


def _tables_with_business_id():
    """Every table a migration creates with a business_id column."""
    root = pathlib.Path(al.__file__).resolve().parent
    found = {}
    for f in glob.glob(str(root / "supabase" / "*.sql")) + glob.glob(str(root / "__migrations__" / "*.sql")):
        src = open(f, encoding="utf-8", errors="ignore").read()
        for m in re.finditer(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)\s*\((.*?)\);",
                             src, re.I | re.S):
            if re.search(r"\bbusiness_id\b", m.group(2), re.I):
                found.setdefault(m.group(1), os.path.basename(f))
    return found


class TestTheListCannotRot:
    def test_every_business_scoped_table_is_a_decision(self):
        """A table with a business_id column is either exported (and
        deleted) with the business, or excluded here WITH A REASON. A
        third state — nobody thought about it — is what the 2026-07-31
        reconciliation found forty tables in, and what this scan found
        nine practitioner tables in on 2026-09-04."""
        found = _tables_with_business_id()
        assert len(found) > 50, "the migration scan stopped seeing tables"
        listed = set(al.BUSINESS_CHILD_TABLES)
        excluded = set(al.EXPORT_EXCLUDED)
        undecided = sorted(t for t in found if t not in listed and t not in excluded)
        assert not undecided, (
            "business-scoped tables that are neither exported nor excluded with a reason: "
            + ", ".join(f"{t} ({found[t]})" for t in undecided))

    def test_nothing_is_both_exported_and_excluded(self):
        both = set(al.BUSINESS_CHILD_TABLES) & set(al.EXPORT_EXCLUDED)
        assert not both, both

    def test_every_exclusion_says_why(self):
        for table, why in al.EXPORT_EXCLUDED.items():
            assert isinstance(why, str) and len(why) > 15, table

    def test_the_september_tables_are_carried(self):
        for t in ("sms_numbers", "concierge_conversations", "consent_records",
                  "support_ticket_messages", "business_doc_templates",
                  "auditor_links", "push_subscriptions", "stripe_disputes_cache"):
            assert t in al.BUSINESS_CHILD_TABLES, t

    def test_children_precede_their_parents(self):
        order = {t: i for i, t in enumerate(al.BUSINESS_CHILD_TABLES)}
        assert order["support_ticket_messages"] < order["support_tickets"]
        assert order["concierge_conversations"] < order["contacts"]
        assert order["consent_records"] < order["contacts"]

    def test_what_cannot_be_restored_is_still_exported(self):
        """Skipped on import is not the same as dropped from export."""
        for t in ("sms_numbers", "auditor_links", "push_subscriptions", "stripe_disputes_cache"):
            assert t in al._IMPORT_SKIP and t in al.BUSINESS_CHILD_TABLES, t


class TestDeletingABusinessHandsBackItsNumber:
    def test_the_line_is_released_at_the_provider_before_the_rows_go(self, monkeypatch):
        import asyncio
        import twilio_sms
        calls = []
        monkeypatch.setattr(twilio_sms, "detach_from_service", lambda sid: calls.append(("detach", sid)))
        monkeypatch.setattr(twilio_sms, "release_number", lambda sid: calls.append(("release", sid)))

        class _Resp:
            status_code = 200
            def json(self):
                return [{"id": "n1", "phone_number": "+12165550100", "provider_sid": "PN123"},
                        {"id": "n2", "phone_number": "+12165550101", "provider_sid": None}]

        class _Client:
            async def get(self, url, headers=None, params=None):
                assert url.endswith("/rest/v1/sms_numbers")
                assert params["status"] == "in.(active,suspended,releasing)"
                return _Resp()

        n = asyncio.run(al._release_sms_lines(_Client(), "biz-1"))
        assert n == 2
        assert calls == [("detach", "PN123"), ("release", "PN123")], "detach, then release; the sid-less row is just counted"

    def test_a_provider_error_is_logged_and_deletion_continues(self, monkeypatch):
        import asyncio
        import twilio_sms
        monkeypatch.setattr(twilio_sms, "detach_from_service", lambda sid: (_ for _ in ()).throw(RuntimeError("twilio down")))
        monkeypatch.setattr(twilio_sms, "release_number", lambda sid: None)

        class _Resp:
            status_code = 200
            def json(self):
                return [{"id": "n1", "phone_number": "+1", "provider_sid": "PN1"}]

        class _Client:
            async def get(self, url, headers=None, params=None):
                return _Resp()

        assert asyncio.run(al._release_sms_lines(_Client(), "biz-1")) == 0

    def test_delete_business_releases_before_it_deletes(self):
        src = inspect.getsource(al._delete_business)
        assert src.index("_release_sms_lines") < src.index("for table in BUSINESS_CHILD_TABLES")
