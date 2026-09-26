# Mission Control campaign operations

This release adds the first operational campaign loop to the existing Publishing
Desk: persist a brief, prepare a strategy and production package, hand draft copy
to the existing reviewed-post workflow, then inspect linked posts and Buffer
performance. It does not launch ads, verify external research, or join paying
customer conversions yet. The interface labels those boundaries explicitly.

## Release order

1. Merge the backend PR. Apply this migration after merge:
   `supabase/APPLY-2026-09-26-marketing-campaigns.sql`.
   It requires the already-applied September 15 platform-marketing migration.
2. Verify all five new tables have RLS enabled and no anon/authenticated grants
   or policies. Verify the three callable RPCs are service-role only.
3. Deploy the frontend PR. Existing post publishing works without the new
   migration; the Campaigns view returns a visible setup error until it is ready.
4. Save a test brief through the owner API, edit it, attempt a stale revision,
   and verify the immutable `mc-<uuid>` campaign tracking key stays unchanged.
5. Explicitly request one plan and inspect its quality. This uses the existing
   deep model lane and metering seam. Plan requests are owner-triggered only.
6. Prepare a post from a social production item. Check destination, caption,
   media and schedule. Saving a campaign or plan does not approve that post.
   Image/video publication tests require a reviewed real post and are separate
   from this release's isolated automated tests.
7. With an existing published post, use Refresh social results. Verify the
   provider/channel identity, metric units, source timestamp and live receipt.
8. Optionally set `MARKETING_METRICS_ENABLED=on` on the scheduler worker. The
   hourly job claims up to 25 published posts from the last 90 days, selecting
   those never checked or checked more than 24 hours ago. Manual and worker
   refreshes share a database-backed 15-minute cooldown. Buffer metrics may
   lag the social network by about one day.

## Contracts

- Campaigns are platform-owner records, separate from tenant nurture campaigns.
  Campaign stage is a planning label, not a publishing switch; archiving blocks
  new linked drafts but does not stop already approved posts. Use the existing
  publishing pause/cancel controls to stop delivery.
- The production budget is a planning assumption, not a spend authorization,
  hard provider limit or accounting report. Generation is bounded at six plan
  attempts per hour across replicas. Existing AI metering/spend checks still
  apply, but their fail-open behavior is not a financial guarantee.
- Each write uses compare-and-swap revisions and records an audit snapshot.
  Editing brief facts changes its hash and marks a generated plan stale. Prior
  plan snapshots remain in the audit history. Reviewed posts keep their own
  immutable content and approval; changes to offers require reviewing posts.
- The request UUID reserves a planning attempt before any model call. Duplicate
  or interrupted attempts never automatically incur another call. A fresh,
  explicit request is required after failure/interruption. Concurrent brief
  edits prevent the stale model response from overwriting newer work.
- Source links are owner-supplied references, not fetched pages. No external
  claim is presented as independently verified. Model output is validated to
  a bounded schema; all public output remains subject to post review.
- `campaign_id` is nullable for old posts. The existing campaign text becomes
  the permanent tracking key on linked posts; display-name changes do not
  change attribution. Existing post approval hashes remain valid on migration.
- Social totals are lifetime per-post snapshots for the displayed linked posts,
  not unique audience, period conversions, revenue or ROI. Coverage is reported
  per metric. Unavailable data is null; a reported zero remains zero. Buffer
  itself may default unreported metrics to zero, so provider counts are not
  independent proof of no activity. Provider failures retain previous values
  and mark affected rows unavailable rather than silently showing stale success.

## Local verification

```powershell
python -m pytest __tests__/test_marketing_campaigns.py __tests__/test_platform_marketing.py __tests__/test_platform_chief_marketing.py -q -p no:cacheprovider
npm install --prefix output/marketing-qa --no-save @electric-sql/pglite
node __tests__/marketing_campaigns_db.mjs
```

The SQL harness is an isolated PostgreSQL-compatible database, not a production
network/concurrency test. It checks migration replay, RLS/grants, request reuse,
cross-replica claim semantics, stale revisions, audit, provider identity,
cooldown and preserving values on failures. Provider tests use fakes and do not
publish or spend money. Frontend validation and responsive fixtures live in the
paired frontend PR.

## Rollback

Disable `MARKETING_METRICS_ENABLED` on the worker and revert the frontend/backend
code if necessary. Retain the additive tables and nullable relationship column
so saved briefs, audits and metrics remain recoverable. No destructive rollback
or loss of existing Buffer posts is required.

## Next increments

Validated conversion events with test-traffic exclusion and campaign joins;
source-backed live research; durable asynchronous production jobs; editable
creative masters; direct plan-to-image/video production; cohort revenue and
cost reporting; then scoped paid-campaign controls. Do not describe this first
release as a fully autonomous marketing department.

Provider references checked September 26, 2026:
- https://developers.buffer.com/examples/get-post-metrics.html
- https://developers.buffer.com/types/PostMetric.html
- https://developers.buffer.com/types/PostMetricType.html
- https://developers.buffer.com/types/PostMetricUnit.html
