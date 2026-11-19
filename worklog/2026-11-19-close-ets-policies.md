---
title: The Embrace the Shift tables were open to the public anon key and to every login. The migration that closes them, the site build that goes first, and the app's realtime sign-in
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: "Close a live data exposure on the Embrace the Shift tables without breaking the public site. Build only: commit locally, do NOT push, do NOT deploy anything."
status: waiting on Kevin
prs: []
migrations: ["supabase/APPLY-2026-11-19-close-ets-policies.sql (NOT APPLIED; deploy the site's new build first, then run it)"]
left_undone:
  - "NOT APPLIED. The hole is open on production until supabase/APPLY-2026-11-19-close-ets-policies.sql is run, AFTER the site's new build (ets-web, branch close-public-reads) is deployed with the Vercel CLI. Applied before that build, the live site's inquiry form and registration fail and its confirmation page says Registration Not Found."
  - "Not pushed, not deployed: local commits on close-ets-policies (this repo), close-public-reads (ets-web, a local repo with no remote) and ets-realtime-signed-in (solutionist-studio)."
  - "Nothing confirms a paid registration: there is no Stripe webhook for these tables, and stripe_proxy makes the payment links with no return address (no after_completion), so a paid registration stays pending and its confirmation page (if reached) keeps polling. An existing gap, not built here."
  - "Who writes ets_agent_log and ets_emails (8 and 4 rows) was not found in either repo. If it is something outside them using the anon key, it stops working when the file is applied; with the service role it is unaffected."
  - "The fixture's four event tables are built from the columns the site and the app use, and the registration status labels beyond pending and confirmed are a guess; production's DDL for them was not in any repo. The file checks the columns and defaults it relies on before it changes anything."
  - "The rollback keeps ets_registration_confirmation (the new site build reads it). Its last line, commented, drops it once the old build is back."
decisions:
  - "The confirmation function answers the registrant's email, because the page shows it back twice ('A confirmation has been sent to ...'). It never answers the phone, organization, notes, check-in or Stripe fields. Anyone holding the link (a random id, or a Stripe session id) sees the name and email on it."
  - "The event's virtual link is answered only once the registration is confirmed, as the page shows it. Otherwise anyone could add a pending registration for a paid virtual event and read the link without paying."
  - "A Stripe session id that two registrations share finds neither (the old page's .single() also failed on two). A reference must be a uuid's exact text or a session id: no pattern, at most 200 characters."
  - "The views ets_pipeline_summary, ets_revenue_summary and ets_pending_agent_actions read past every policy as their owner, and anon could read them; they were not in the brief. Each view that reads the ten is set to run as the caller (security_invoker) and loses anon. No code reads them; none is dropped."
  - "anon's grants: REVOKE ALL then GRANT exactly SELECT on events, tiers and files and INSERT on inquiries and registrations, read as the end state the brief describes, rather than only revoking UPDATE, DELETE and TRUNCATE (which would leave INSERT on events and SELECT on inquiries and registrations to the policies alone)."
  - "The file refuses to run, changing nothing, when a default of an internal inquiry or registration column is not the one it was written for, or a trigger it does not know sits on ets_inquiries or ets_registrations: either would make every public insert fail. It does not guess around them."
  - "A signed-in login that is not the platform owner reaches exactly what the public does: the published events, and the two forms. The brief's 'gets nothing anywhere' is read as 'nothing past the public'."
  - "The site's confirmation page falls back to its old read only when PostgREST says the function does not exist (PGRST202), so the new build works in the gap between its deploy and this file."
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
signature and session row, change them, and delete them; any signed-in
Solutionist login could too.

## What changes

`supabase/APPLY-2026-11-19-close-ets-policies.sql`, one transaction:

| who | before | after |
|---|---|---|
| anon (the site) | everything on all ten | published / sold-out events, their visible tiers and their files; may add an inquiry (internal fields left alone) and a registration (published event, visible tier of it, pending or free-and-confirmed, the right amount, nothing staff-only); reads a registration only through `ets_registration_confirmation` |
| a login that is not the owner | everything on all ten | the same as anon |
| the platform owner (the app) | everything | everything (`ets_owner_all`, `is_platform_owner()`) |
| the server | bypasses RLS | the same |

The two count triggers become SECURITY DEFINER with `search_path = public`
(bodies untouched): as the caller, with the new grants, they fail every
registration the site sends. The views that read the ten get
`security_invoker`.

## The order

1. The site: `ets-web` branch `close-public-reads`, deployed with the Vercel
   CLI. It inserts with an id it made and does not read the row back; the
   confirmation page reads through the function, and the old way while the
   function is missing. Works before and after the file.
2. The app's realtime hooks: solutionist-studio `ets-realtime-signed-in`
   (any time; works before and after).
3. The file. Then its "Check after" block.

## Tests

- `__tests__/ets_close_policies_db.mjs` (PGlite, both as the superuser and as
  a table owner without BYPASSRLS): 636 checks. The hole before; the file's
  Check blocks as written; the file twice; every public path the site uses
  and every refusal; the function's answers; a non-owner login; the owner;
  the count triggers (and the same insert failing with them as the caller);
  the rollback restoring the catalog exactly, then the file again. Ten
  mutations of the file (no definer on the triggers, hidden tiers shown, a
  paid registration self-confirmed, lead_score unchecked, the link always
  answered, the phone answered, the views untouched, the staff grants kept,
  a shared session id answered, draft files public) each fail it.
- `__tests__/test_close_ets_policies.py`: the file as text.
