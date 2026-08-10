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
