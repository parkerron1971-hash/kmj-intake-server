---
title: A church that signs up looks around a sample church instead of a trial (sample church, BE-1, the foundation)
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14, approved the sample church signup and gave BE-1 a Build slot: "top tier, no cut corners"'
status: in review
prs: ["kmj-intake-server (this PR, sample-church-be1)"]
migrations: [supabase/APPLY-2026-11-15-sample-church.sql (NOT APPLIED; the parent session applies it)]
left_undone:
  - "BE-2, the seed: a generator and seeder for Grace Street Fellowship's records, and a site fixture with licensed stock photos (Kevin picked stock photos). It fills sample_church.seed_hook, which must be idempotent and refuse quickly while a seed is running (ensure() calls it on every /billing/access load of a pending sample), and sets settings.sample_church.status to ready."
  - "BE-3, send and spend guards on every path that can send or spend for a sample, sample_church.skip() in the sweeps that do not filter is_active (church_billing._founding_taken, church_founding counts, anything that reads businesses without is_active=eq.true), a test that nothing is ever sent from a sample, READ_POSTS filled, and the daily cleanup: delete samples whose home pays or is gone (is_sample and sample_of null), samples marked ending that a deploy cut short, and samples idle 60 days (Kevin picked 60)."
  - "BE-3 or FE: a visitor really owns the sample, so RLS lets their own login write its child tables (contacts, events and so on) straight through PostgREST. The new trigger guards only the businesses row. Either the app never writes there for a sample, or a restrictive policy through a SECURITY DEFINER is_sample_business(b) helper refuses it (docs/RLS_MODEL.md rule 2)."
  - "BE-4, the sample's Chief: ten questions per person in its own lane, written to sample_church_questions (n 1..10, unique per person), metered through api_usage_logger, behind the spend guard."
  - "FE-1..4, the app: open the sample when /billing/access says state sample, word the 409 sample_church, the signup screen (/access/open church_sample), the welcome email's church-sample words (TODO in launch_access.create_business), and never write the sample's businesses row (the trigger refuses it with 42501)."
  - "One follow-up email on day 3 to a church that looked around and didn't start (Kevin picked this)."
  - "A run-through on a made-up church, then CHURCH_SAMPLE=on, on a Thursday. No live test payment: Kevin, the first real church tests checkout."
  - "Found, not changed: feature_gates._access_state honours a comp_tier only from PLANS (starter, professional, practice), so a business comped on a church plan reads locked / no_subscription there while plan_of() gives it the plan. Worth a look on its own."
decisions:
  - "One sample per church: a second businesses row, owned by the same person, is_active false, is_sample true, sample_of the home. Every owner check and RLS policy works unchanged; nobody can see anyone else's. Deleting it is account_lifecycle._delete_business."
  - "Who gets one is derived from the home row (applies), never a settings marker: a church, not a sample, no comp, no subscription, never a trial, no status, owner not grandfathered, billing enforced, the columns there, the switch allowing it."
  - "CHURCH_SAMPLE ships at test with CHURCH_SAMPLE_TESTERS empty: nobody gets a sample and applies() answers before any read, so real users see no change. Anything but off/test/on reads as off."
  - "The trigger tests current_user (anon or authenticated are refused), the same test as the repo's other client guards, not request.jwt.claims, which a SECURITY DEFINER function can set. SECURITY INVOKER, reads no table, no policy: nothing can recurse. A foreign-key action runs as the table owner, so deleting a home still nulls its sample's sample_of."
  - "access_state stays pure: a sample row is known from its own column; a home's 'sample' comes from the caller's applies() (church_sample=), and only from the locked / no_subscription state with none of a live church's columns set, so a careless True can never lift a paying church into it. Every gate treats sample as locked (feature_gates.LOCKED_STATES)."
  - "A sample gets 409 sample_church (never 402, which opens the app's Open Billing toast) from require_live_access, require_units and require_card, whatever enforcement says; a home in a sample gets the usual 402 with reason church_sample and words that say to start the church."
  - "The webhook ends the sample on active or trialing on any plan: either way the home has a subscription and applies() can never hold again. The first-run arc opens on active only for a home whose sample just ended, so every other active subscription still opens nothing."
  - "Refused for a sample: subscription checkout, credit packs, Stripe Connect (start, create-account, account-session), texting numbers (through require_card), texting registration send, and custom domains (site and email). There is no domain purchase anywhere in the code; connecting a domain is refused instead because a domain is held by one site."
  - "The export leaves sample businesses out; sample_church_questions is in EXPORT_EXCLUDED and USER_CHILD_TABLES (deleted with the person)."
related: [2026-11-13-church-plans-no-free-week.md, 2026-10-03-no-card-trial.md]
---
BE-1 lays the floor for the sample church and changes nothing while the switch
sits at its default. `sample_church.py` holds the switch, `applies()`, the
sample lookups (`is_sample`, `sample_for`, `home_of`, `skip`), `ensure()` (the
row only, race-safe on the unique index), `end()` (mark "ending", then
`account_lifecycle._delete_business`, never the home), the 409 refusals and the
`/billing/access` sample block (`business_id`, `home_business_id`, `ready`,
`questions_left`, `questions_of`, `read_posts`, `promise`, `free_moves_left`).
`no_card_trial.eligible()` says `sample` / `church_sample` first, signup answers
`sample: {pending: true}` and skips the trial and the first-run arc,
`/access/open` carries `church_sample`.

The 11-13 log (`2026-11-13-church-plans-no-free-week.md`) called taking the
church look-around away "a separate decision"; Kevin made it on 11-14. Before
switching it on for anyone, apply the migration, then set CHURCH_SAMPLE_TESTERS.
