# Private business learning

Chief can retain how an unfamiliar business operates, identify missing information,
research an important gap, and use the saved knowledge when preparing module and
offering proposals. An owner correction replaces the named fact in the next
revision and governs subsequent conversations and build proposals.

## Product behavior

- Strategy Coach, Business Coach and operational Chief read the same private
  profile. Strategy questions can use its open gaps and already-known answers.
  `capture_business_knowledge` saves useful owner answers immediately during a
  session, before a phase or the plan is completed. It can initialize a profile
  and batch up to eight exact quotations into one atomic revision, with no extra
  model call. A running research job cannot overwrite a newer captured answer.
- Captures distinguish reported operations, explicit decisions and tentative
  plans. Tentative plans remain assumptions and cannot replace a settled owner
  rule or resolve an owner-question gap. Strategy deliverables and forecasts
  continue in their existing store; model-generated content is not automatically
  treated as owner evidence. Existing launch confirmation is preserved.
- A custom signup with a trade description queues `learn_business` after creation.
  A profile ready for a starting workspace proceeds through the existing
  `business_blueprint` builder. Its cards use the existing review/accept flow.
  Missing descriptions or blocking questions remain discovery work, never an
  empty workspace reported as successfully provisioned.
- In Chief, describe the operation or ask it to learn the business. The action
  uses the actual current owner message, not a model-supplied claim of provenance.
- Ask Chief what it knows: `recall_business_knowledge` returns the complete
  profile, revision, source evidence and open questions through its native read
  toolbox. This also works for a connected agent scoped to the same business.
- Correct a fact or report an outcome: Chief saves an exact quotation using
  `correct_business_knowledge`. The profile is the owner's account of the
  operation; an anecdotal outcome is not labeled proven effectiveness.
- Research uses the existing provider web-search tool, at most three searches
  per research pass. A job may automatically research one blocking gap. Further
  gaps remain visible. Only provider-returned citations can support research
  facts. No citation means the research gap remains unresolved.
- Sources retain URLs, excerpts and retrieval/review dates. After 30 days,
  contextual retrieval marks a source stale and tells Chief to verify it.
  There is no unattended periodic research or unbounded research loop.
- Profiles never write to `vertical_knowledge` or alter `businesses.type`.
  Cross-business clustering and shared vertical promotion are outside this first
  implementation. Public templates will need a separately reviewed write path.

## What knowledge changes

`vertical_context` appends private operating knowledge to existing shared trade
defaults. Chief's regular prompt and Business Coach include the learning actions.
The whole-business mapper and individual module generator read the same profile.
Owner corrections are prioritized when the bounded context cannot fit all facts.
Full details remain available through recall.

New generated modules and offerings carry the profile revision they used.
Acceptance refuses a versioned proposal if the profile changed while the card
was waiting; regenerate it using the correction. Legacy cards without revision
metadata continue to work.

Saving a fact does **not** silently alter an installed booking schedule, send a
message, reprice an offering, or rewrite an existing module. Chief must use the
existing corresponding action when the owner asks for that operational change.
This distinction is explicit in the prompt and correction result.

## Storage and isolation

`business_operating_profiles` has one validated JSON profile per business.
`business_operating_profile_history` retains each revision. The service-only
`save_business_operating_profile` RPC locks the parent business and compares the
expected revision, updating the current profile and history atomically. A
concurrent stale writer fails instead of overwriting an owner correction.

Both tables have RLS enabled with no client grants. HTTP reads, history,
discovery and corrections require a verified owner; Chief uses its existing
authorized business/action door. UUID validation precedes PostgREST filters.
Both tables participate in account export, import and deletion and cascade when
the business is deleted. No source or profile is sent to another tenant.

Routes:

- `GET /business-learning/{business_id}`
- `GET /business-learning/{business_id}/history` (latest 50 revisions)
- `POST /business-learning/{business_id}/discover` with `description` and optional
  `research_question`; returns the existing Chief job shape.
- `POST /business-learning/{business_id}/correct` with `key`, `kind`, `statement`,
  `expected_revision`, optional `resolves_gap`; stale revisions return 409.

Discovery calls pass through `llm_call` metering and the existing daily tenant
spend guard. `RL_BUSINESS_LEARNING_PER_HOUR` defaults to 24 model calls per
business, using the existing limiter. No new provider or API key is required.

## Release and verification

This implementation is not deployed by creating the files. Apply
`supabase/APPLY-2026-09-07-business-learning.sql` before deploying the backend.
Then deploy the small frontend terminology/What's New change.

Run these checks in the target database:

```sql
SELECT to_regclass('public.business_operating_profiles'),
       to_regclass('public.business_operating_profile_history');
SELECT relname, relrowsecurity FROM pg_class
WHERE relname IN ('business_operating_profiles','business_operating_profile_history');
SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants
WHERE table_name IN ('business_operating_profiles','business_operating_profile_history')
  AND grantee IN ('anon','authenticated'); -- expect zero rows
SELECT has_function_privilege('authenticated',
  'public.save_business_operating_profile(uuid,integer,jsonb,text,text)', 'EXECUTE'); -- false
```

Live smoke test with a test-owned mobile pet-grooming business:

1. Describe its customers, offerings, workflow and payment process. Finish any
   blocking owner questions. Confirm the private profile survives a new session.
2. Ask Chief to research one actual trade question. Confirm returned source
   excerpts support the saved facts; verify research stays within its budget.
3. Correct `travel_buffer` with an exact owner statement and current revision.
   Confirm recall in a new session uses the correction. Submit a stale revision;
   it must return 409 and preserve the latest correction.
4. Ask for an appointment module. Review that its proposed shape reflects the
   correction. Correct the profile again before accepting the draft; the old
   draft must be refused and offer regeneration.
5. Sign in as a different owner and try all private-profile routes for this
   business. They must refuse access. Check no `vertical_knowledge` row was added.

Automated tests use fake model/provider responses and a tenant-scoped database
double. They do not certify production migration application, provider citation
quality, live PostgreSQL locking, or the quality of real generated modules.
