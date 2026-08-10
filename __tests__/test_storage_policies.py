"""Storage writes require an identity, and an owner.

Measured against production before the lockdown, querying
storage.objects as role `anon`:

    business-assets      17 objects listable anonymously
    site_images          13
    proposals             5
    ets-event-files       4
    client-images         3
    business-documents    1

    has_table_privilege('anon','storage.objects', SELECT/INSERT/UPDATE/DELETE)
      -> true, true, true, true

Every policy read `TO public USING (bucket_id = '…')` and nothing else.
`public` includes anon, and the anon key ships in the browser bundle, so
anyone could upload into, overwrite, or DELETE a practitioner's client
documents.

The policies are SQL and live in Supabase, not in this repo, so what
these tests can hold down is the migration that produced them: it stays
in the tree, it keeps saying what it did, and nobody quietly re-adds a
`to public` write. The behaviour itself was verified against production
at apply time, by probe:

    anon insert into business-documents                -> 42501 REFUSED
    authenticated non-owner into someone else's path   -> 42501 REFUSED
    the real owner, all four bucket/path shapes        -> ALLOWED

with the object count 43 before and 43 after, and zero probe rows left
behind (the rollbacks held; an earlier reading that said otherwise was a
LIKE pattern of mine treating `_` as the wildcard it is).
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL = ROOT / "supabase" / "APPLY-2026-08-09-storage-write-lockdown.sql"
READ_SQL = ROOT / "supabase" / "APPLY-2026-08-10-close-the-document-vault.sql"

WRITE_BUCKETS = ("business-assets", "site_images", "business-documents",
                 "proposals", "client-images", "ets-event-files")


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _code() -> str:
    """The SQL with `--` comments stripped.

    Anything asserting on the ORDER of clauses has to read code, not
    prose. The first version of the owner-gap test below searched the
    raw file and found "business_users" inside a comment explaining the
    owner gap — so it failed against a migration that was correct. A
    test that can be fooled by a comment is measuring the wrong file.
    """
    return "\n".join(
        line.split("--", 1)[0] for line in _sql().splitlines())


class TestTheMigrationIsStillHere:
    def test_it_exists(self):
        assert SQL.exists(), (
            "the storage lockdown migration is the only record of why the "
            "policies look the way they do")

    def test_every_write_policy_it_creates_targets_authenticated(self):
        """`to public` is what the hole was made of."""
        s = _code()
        for m in re.finditer(r"create policy[^;]+?;", s, re.S | re.I):
            block = m.group(0)
            if re.search(r"for\s+(insert|update|delete)", block, re.I):
                assert re.search(r"to\s+authenticated", block, re.I), (
                    f"a write policy does not target authenticated:\n{block[:200]}")
                assert not re.search(r"to\s+public", block, re.I), (
                    f"a write policy still targets public:\n{block[:200]}")

    def test_it_drops_the_old_permissive_policies(self):
        """Creating tighter policies beside the old ones would change
        nothing: RLS is permissive-OR, so one surviving `to public`
        INSERT re-opens the bucket."""
        s = _code()
        for name in ("Allow uploads", "Allow deletes",
                     "Allow public upload business-documents",
                     "Allow public delete business-documents",
                     "Allow public upload proposals",
                     "Allow uploads to site_images",
                     "Allow deletes from site_images"):
            assert f'drop policy if exists "{name}"' in s, (
                f"the old permissive policy {name!r} is never dropped")

    def test_the_business_scoped_buckets_check_ownership(self):
        s = _code()
        for bucket in ("business-assets", "site_images",
                       "business-documents", "proposals"):
            for m in re.finditer(r"create policy[^;]+?;", s, re.S | re.I):
                block = m.group(0)
                if f"'{bucket}'" in block and re.search(
                        r"for\s+(insert|update|delete)", block, re.I):
                    assert "user_can_access_business" in block, (
                        f"{bucket} write policy has no ownership check")


class TestTheOwnerGap:
    """business_users has ZERO rows in production: every business today
    is reached through businesses.owner_id. A seat-only check would lock
    out 100% of users — the failure that hit backend #464."""

    def test_owner_id_is_checked_independently_of_seats(self):
        s = _code()
        fn = s[s.index("function public.user_can_access_business"):]
        fn = fn[:fn.index("$$;") + 3]
        assert "owner_id = auth.uid()" in fn
        owner_at = fn.index("owner_id = auth.uid()")
        seats_at = fn.index("business_users")
        assert owner_at < seats_at, (
            "owner must be resolved before seats, or a brand-new business "
            "with no seat row locks its own owner out")
        # OR, not AND — an owner with no seat must still pass.
        between = fn[owner_at:seats_at]
        assert re.search(r"\bor\b", between, re.I), (
            "owner and seat checks must be OR'd, not AND'd")

    def test_revoked_seats_do_not_count(self):
        assert "revoked_at is null" in _code()


class TestItFailsClosed:
    def test_an_unrecognised_path_yields_no_business(self):
        """storage_business_id returns NULL for a path shape it does not
        know, and every policy ANDs on it — so a new path layout is
        refused rather than silently unguarded."""
        s = _code()
        fn = s[s.index("function public.storage_business_id"):]
        fn = fn[:fn.index("$$;") + 3]
        assert "else null" in fn.lower()

    def test_the_access_helper_is_security_definer(self):
        """businesses and business_users both carry RLS. Evaluating them
        as the caller from inside a storage policy is how the 42P17
        policy-cycle outage happened before."""
        s = _code()
        fn = s[s.index("function public.user_can_access_business"):]
        fn = fn[:fn.index("$$;") + 3]
        assert "security definer" in fn.lower()
        assert "set search_path" in fn.lower(), (
            "a SECURITY DEFINER function without a pinned search_path is a "
            "privilege-escalation shape")

    def test_the_helper_is_not_executable_by_anon(self):
        s = _code()
        assert "revoke all on function public.user_can_access_business(uuid) from public" in s
        assert "grant execute on function public.user_can_access_business(uuid) to authenticated" in s


class TestScopeIsStated:
    def test_it_says_reads_are_still_open(self):
        """SELECT is deliberately untouched — published customer sites
        load these images anonymously. A migration that quietly left the
        read side open without saying so would read as a finished job."""
        s = _sql().lower()
        assert "select is deliberately left alone" in s

    def test_it_says_why_the_ets_buckets_are_not_business_scoped(self):
        s = _sql().lower()
        assert "project" in s and "event" in s, (
            "the ETS buckets are keyed on project/event ids, not business "
            "ids; that has to be written down or it reads as an oversight")


class TestTheReadSideIsClosed:
    """Step 3: business-documents and proposals stop being public.

    Verified against production at apply time:

        bucket flags      business-documents / proposals -> private
        as anon           neither bucket appears at all
        as the OWNER      1 document + 5 proposals still readable

    That last line is the one that matters as much as the first two. A
    read lockdown that also locked out the owner would have passed every
    "anon cannot see it" assertion while making the Documents panel look
    like the files had been deleted.
    """

    def _code(self):
        return "\n".join(
            line.split("--", 1)[0]
            for line in READ_SQL.read_text(encoding="utf-8").splitlines())

    def test_the_migration_exists(self):
        assert READ_SQL.exists()

    def test_public_read_is_dropped_for_both(self):
        s = self._code()
        assert 'drop policy if exists "Allow public read business-documents"' in s
        assert 'drop policy if exists "Allow public read proposals"' in s

    def test_owner_scoped_read_REPLACES_it_rather_than_just_removing_it(self):
        """createSignedUrl asks Postgres for SELECT before it will sign.
        A bucket with no select policy cannot be read even by its owner —
        the panel goes blank and it looks like the files are gone."""
        s = self._code()
        for bucket in ("business-documents", "proposals"):
            assert f"create policy \"biz read: {bucket}\"" in s, (
                f"{bucket} lost its public read without gaining a scoped one")
        assert s.count("user_can_access_business") >= 5

    def test_both_buckets_are_marked_private(self):
        s = self._code()
        assert "set public = false" in s
        assert "business-documents" in s and "proposals" in s

    def test_product_files_is_fetchable_but_not_listable(self):
        """The deliberate opposite: a buyer clicks that link from an
        email months later with nobody signed in, so the bucket is
        public to FETCH. It gets no select policy, so it cannot be
        enumerated — knowing one path reveals no others."""
        s = self._code()
        assert "'product-files'" in s
        assert "'product-files', true" in s, "the bucket must be public to fetch"
        for verb in ("insert", "update", "delete"):
            assert f'create policy "product-files {verb}"' in s
        assert 'create policy "product-files select"' not in s, (
            "a select policy on product-files would make it listable")
