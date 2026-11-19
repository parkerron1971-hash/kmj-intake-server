---
title: The Embrace the Shift tables were open to the public anon key and to every login. The migration that closes them, the site build that goes first, and the app's realtime sign-in
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: "Close a live data exposure on the Embrace the Shift tables without breaking the public site. Build only: commit locally, do NOT push, do NOT deploy anything."
status: waiting on Kevin
prs: []
migrations: ["supabase/APPLY-2026-11-19-close-ets-policies.sql (NOT APPLIED; deploy the site's new build first, then run it)"]
left_undone:
  - "NOT APPLIED. The hole is open on production until supabase/APPLY-2026-11-19-close-ets-policies.sql is run, AFTER the site's new build (ets-web, branch close-public-reads) is deployed with the Vercel CLI. Applied before that build, the live site's events list and event pages fail (they ask for '*', and anon may no longer read virtual_link), its inquiry form and registration fail, and its confirmation page says Registration Not Found."
  - "Not pushed, not deployed: local commits on close-ets-policies (this repo), close-public-reads (ets-web, a local repo with no remote) and ets-realtime-signed-in (solutionist-studio)."
  - "Nothing confirms a paid registration (an existing gap, not built here): there is no Stripe webhook for these tables, and stripe_proxy makes the payment links with no return address (no after_completion). So a paid registration stays pending; a registrant who does come back with ?session_id= finds nothing, because nothing writes stripe_session_id, and sees Registration Not Found. The confirmation page's payment poll used to run for as long as the page was open; it now stops after 5 minutes and says plainly that the payment is not confirmed yet (ets-web close-public-reads)."
  - "No capacity or tier-quantity check on a public registration, on purpose (an existing gap): a WITH CHECK on capacity does not stop anyone filling an event with pending registrations (they count as soon as they are added), and once abandoned pending registrations pile up it would refuse real people. The site checks capacity on the page, as before."
  - "Who writes ets_agent_log and ets_emails (8 and 4 rows) was not found in either repo. If it is something outside them using the anon key, it stops working when the file is applied; with the service role it is unaffected."
  - "Production's ets_events DDL was not in any repo. The site's new build asks only for columns the app saves on every event (EventCreate's payload: venue_address, not address; no timezone or require_phone). If production has address, timezone or require_phone columns with values typed in by hand, the event pages no longer show them (the confirmation function still answers address and timezone when the columns exist). Check 2 before lists the 55 columns the site and the policies need."
  - "The fixture's four event tables follow the app's columns, the tier flags production showed and the count triggers' production shape; ets_event_summary's text was not read (a stand-in). The registration status labels beyond pending and confirmed are a guess."
  - "The rollback keeps ets_registration_confirmation (the new site build reads it). Its last line, commented, drops it once the old build is back. It resets security_invoker only on production's two views, by name: if APPLY-2026-09-01-rls-advisor-errors.sql (pending, sets the same two) has been applied since, leave its section 4 out."
  - "The bucket client-images has the same 'any signed-in login' write policies (2026-08-09); not touched here."
decisions:
  - "The confirmation function answers the registrant's email, because the page shows it back twice ('A confirmation has been sent to ...'). It never answers the phone, organization, notes, check-in or Stripe fields. Anyone holding the link (a random id, or a Stripe session id) sees the name and email on it."
  - "The event's virtual link is the public's nowhere: anon may read every ets_events column but virtual_link (a column grant, the list read from the catalog as the file runs, so a later column is not silently missed), and the confirmation function answers it only once the registration is confirmed. Otherwise anyone could read it from the table, or add a pending registration for a paid virtual event and read it without paying. No production event has one today (0 of 3)."
  - "The public reads (events, tiers, files) are TO anon only: the site never signs in, and a signed-in login that is not the owner now reads no row of the ten. The two public inserts stay TO anon and authenticated; a non-owner login's registration is refused anyway, because it sees no event."
  - "The confirmation function reads the event's fields through to_jsonb, so a column the page asks for that the table lacks (address, timezone) answers null instead of failing, and the address falls back to venue_address, the column the app saves."
  - "A Stripe session id that two registrations share finds neither (the old page's .single() also failed on two). A reference must be a uuid's exact text or a session id: no pattern, at most 200 characters."
  - "Production's views ets_event_summary and ets_pending_agent_actions read past every policy as their owner, and anon could read them. Each view that reads the ten is set to run as the caller (security_invoker) and loses anon. No code reads them; none is dropped."
  - "anon's grants: REVOKE ALL then GRANT exactly what the site needs (end state), rather than only revoking UPDATE, DELETE and TRUNCATE. authenticated keeps SELECT, INSERT, UPDATE, DELETE (the policies decide) and loses TRUNCATE, TRIGGER and REFERENCES, which no browser call needs (TRUNCATE skips every policy)."
  - "The ets-event-files bucket: upload and delete only when is_platform_owner(), keeping the two policies' names; 'Allow public read' stays (the site shows the covers and files)."
  - "The file refuses to run, changing nothing, when a default of an internal inquiry or registration column is not the one it was written for, or a trigger it does not know sits on ets_inquiries or ets_registrations: either would make every public insert fail. It does not guess around them."
  - "The site's confirmation page falls back to its old read only when PostgREST says the function does not exist (PGRST202), so the new build works in the gap between its deploy and this file; that read never asks for the virtual link."
  - "The app's EventRegistrations page opens its own anon realtime socket for new registrations, beside useETSRealtime; both now join with the owner's sign-in (one helper)."
related: [2026-11-18-close-allow-all-policies.md]
---
Production's catalog, read 2026-11-19: the ten `ets_*` tables of the Embrace
the Shift business have RLS on, but four carry "Allow all for anon" (every
command, USING true, TO public), the other six a SELECT USING (true), and all
ten an ALL policy USING (auth.uid() IS NOT NULL). `anon` holds select, insert,
update and delete on all ten. The public site embracetheshift.live ships the
anon key, so anyone could read every inquiry (contact names, emails, phone
numbers), registration, engagement (prices, contract data), email, agent note,
signature and session row, and every event's virtual link, change them, and
delete them; any signed-in Solutionist login could too, and could upload to
and delete from the public ets-event-files bucket.

## What changes

`supabase/APPLY-2026-11-19-close-ets-policies.sql`, one transaction:

| who | before | after |
|---|---|---|
| anon (the site) | everything on all ten | published / sold-out events (every column but `virtual_link`), their visible tiers and their files; may add an inquiry (internal fields left alone) and a registration (published event, visible tier of it, pending or free-and-confirmed, the right amount, nothing staff-only); reads a registration only through `ets_registration_confirmation` |
| a login that is not the owner | everything on all ten, writes to the bucket | no row of the ten; no truncate; no write to the bucket |
| the platform owner (the app) | everything | everything (`ets_owner_all`, `is_platform_owner()`), and the bucket |
| the server | bypasses RLS | the same |

The two count triggers become SECURITY DEFINER with `search_path = public`
(bodies untouched): as the caller, with the new grants, they fail every
registration the site sends. The views that read the ten get
`security_invoker`.

## The order

1. The site: `ets-web` branch `close-public-reads`, deployed with the Vercel
   CLI. It names the event columns it shows (never `virtual_link`), inserts
   with an id it made and does not read the row back; the confirmation page
   reads through the function, and the old way while the function is
   missing. Works before and after the file.
2. The app's realtime hooks: solutionist-studio `ets-realtime-signed-in`
   (any time; works before and after).
3. The file. Then its "Check after" block.

## Tests

- `__tests__/ets_close_policies_db.mjs` (PGlite, as the superuser and as a
  table owner without BYPASSRLS, plus a database with address and timezone
  columns): 774 checks. The hole before; the file's Check blocks as written;
  the file twice; every public path the new site uses, with its exact
  column lists, and every refusal (the virtual link by name, by `*`, by the
  whole row); the function's answers; a non-owner login; the owner; the
  bucket; the count triggers (and the same insert failing with them as the
  caller); the rollback restoring the catalog exactly (storage's policies
  and authenticated's grants too) while a view that already ran as the
  caller stays so, then the file again. 21 deliberate breaks of the file and
  the rollback each fail it.
- `__tests__/test_close_ets_policies.py`: the files as text (13 tests).
