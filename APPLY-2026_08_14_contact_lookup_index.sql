-- APPLY-2026_08_14_contact_lookup_index.sql
--
-- THE LEAD ARC PR 7 — supporting the one dedupe rule.
--
-- ═══════════════════════════════════════════════════════════════════
-- WHY THERE IS NO UNIQUE INDEX HERE
-- ═══════════════════════════════════════════════════════════════════
--
-- The spec for this arc said "one dedupe rule + the missing unique
-- index on (business_id, lower(email))". Production says the second
-- half is wrong, and not merely because duplicates exist today.
--
-- Two of the duplicate rows are:
--
--     Rev. Marcus Williams   creativecryptobag@gmail.com   active
--     Sister Williams        creativecryptobag@gmail.com   lead
--
-- Two DIFFERENT people at one household address, in one church's
-- contact list. A shared email is a legitimate state for a church, a
-- family business, a couple. A unique constraint would make the second
-- person unable to exist, and would surface as a 500 on a public form
-- submission with nothing to explain it — a lost lead caused by the
-- thing meant to keep the data tidy.
--
-- Application-level resolution can weigh a name against the match.
-- A unique index cannot weigh anything. lead_identity.same_person()
-- is the guard, and it deliberately errs toward SPLITTING, because a
-- false merge interleaves two people's history across seventeen
-- foreign keys and a false split is a visible duplicate somebody can
-- fix.
--
-- ═══════════════════════════════════════════════════════════════════
-- WHY THERE IS NO lower(email) INDEX EITHER
-- ═══════════════════════════════════════════════════════════════════
--
-- The resolver matches email with PostgREST's `ilike` and no wildcards
-- — case-insensitive exact match, which also works on the mixed-case
-- rows already in the table. That compiles to `email ~~* '…'`, and the
-- planner will NOT use a btree on lower(email) for it.
--
-- An index the query cannot use is worse than no index: it implies a
-- coverage that does not exist, and the next person to look at a slow
-- lookup sees an index there and goes hunting elsewhere. When the
-- stored data is uniformly lowercased and the resolver can switch to
-- plain equality, the index and the query change together.
--
-- The phone lookup IS a plain equality on a normalized E.164 string,
-- so that one is real and it is below.

CREATE INDEX IF NOT EXISTS contacts_business_phone_idx
  ON public.contacts (business_id, phone)
  WHERE phone IS NOT NULL;

COMMENT ON INDEX public.contacts_business_phone_idx IS
  'lead_identity.find() second pass: match a returning enquirer by '
  'normalized phone when they left no email. Partial — a contact with '
  'no phone is never looked up this way.';
