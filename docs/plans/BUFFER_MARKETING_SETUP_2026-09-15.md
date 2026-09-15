# Solutionist Buffer marketing setup

## Implemented in this build

Mission Control → Growth now has an owner-only publishing workspace:

- Verify the server's Buffer connection and explicitly select Solutionist's organization and social accounts.
- Upload immutable, shared PNG/JPEG/MP4 marketing exports, or attach a newly exported flyer through the existing flyer event.
- Save/edit campaign posts, landing pages and dates. Every link receives source, organic medium, campaign and creative tags.
- Ask Chief to draft seven varied daily captions from the owner's supplied facts, audience and offer. These remain drafts until reviewed.
- Review exact captions, media, channels, times and expiry together; approve a batch atomically. Edits invalidate approval.
- Publish approved posts from the existing leader scheduler. No n8n/Make service is required.
- Track provider receipts, sent versus submitted, failures and uncertain outcomes. No blind retries after a timeout or lost receipt.
- Pause future dispatches. Dates remain local until due; already in-flight delivery may finish. Existing direct Meta publishing is separate and receives no automatic copy of these jobs.
- Explore Post for Me, Upload-Post, bundle.social and Ayrshare from the customer options section.
- Separate explicitly tagged paid and organic traffic in Growth; cost per paid Meta signup excludes organic signups. This is not paying-customer CAC.

Initial publishing support: Facebook, Instagram, X and LinkedIn. One image or video per post; Facebook and Instagram videos use Reel metadata. Instagram requires media. Buffer remains responsible for final network/format validation; test the actual connected accounts before scaling. Video rendering and flyer creation remain in the existing creative tools; the new library stores their exports, not editable project files.

## Activation checklist

1. Deploy the backend and frontend changes together. The backend defaults to publishing **off**.
2. Apply `supabase/APPLY-2026-09-15-platform-marketing.sql` using the Supabase SQL editor. Repository convention is manual migration application. It adds four service-only tables, atomic approval/claim functions, audit triggers and the public `platform-marketing` export bucket. It does not modify tenant social connections.
3. Sign into or create the owner's Buffer account. Connect only the channels belonging to The Solutionist System. Start with the desired plan; no subscription was purchased by this build.
4. In Buffer → Settings → API, create a personal API key. Save it as **BUFFER_API_KEY** in backend Railway variables. Do not place it in frontend environment variables, source control or chat. The app never returns the key.
5. Open Mission Control → Growth → Buffer connection and setup. Click **Check Buffer connection**, select the correct organization/accounts, then **Save channels**. This leaves publishing paused.
6. Save one reviewed post with a real export and tracked landing page. Inspect the media preview and exact destination. Test the signup journey's tags separately.
7. Set **BUFFER_PUBLISHING=on** in Railway. Approve the test post and click **Resume approved posts**. This is the point at which reviewed content may publish publicly at its due time.
8. Verify the Buffer receipt becomes **published**, and check the live post, media and tracked link. Check an actual short video independently. Only then approve the rest of the week.

Production setup on 2026-09-15: migration applied after a successful rollback rehearsal; four RLS-protected tables, the export bucket, atomic approval/claim and audit verified. The owner added BUFFER_API_KEY to Railway and a read-only Buffer account/channel check succeeded. BUFFER_PUBLISHING is set to on; the database calendar remains paused and empty. Buffer currently reports no connected social accounts. Connect the intended Solutionist social accounts in Buffer, then check and save those channels in Mission Control. No live post or paid campaign has been created. Deployment verification is recorded in the release PRs.

## Daily operation

Prepare one campaign and seven distinct messages. Use the week generator for one starting channel, then edit individual drafts to vary creative, dates and destinations. Upload exported demo clips and flyers and select them from the shared library. Review the entire batch. Keep enough approved inventory for seven days; refresh the delivery panel daily and handle exceptions. The generator is owner-triggered and metered through the existing model seam; it does not generate or approve new campaigns unattended.

The scheduler claims up to five due items each minute and checks pending Buffer statuses every ten minutes. Unapproved content never dispatches. A six-hour delivery window is the default; enter an explicit offer expiry for time-sensitive posts. A worker interrupted during an external request becomes **uncertain** after five minutes. Inspect Buffer and use **Match a Buffer post** with its ID; the backend checks the exact destination and caption. Do not make a replacement until the uncertain attempt is resolved. Provider failures with a receipt should be handled in Buffer; the app will not create a second copy.

Changing connected channels pauses the calendar. Approved posts remain bound to the original organization/account; they cannot silently move to another business. The owner's key is never used for customer businesses.

## Paid advertising and customer providers

Google Ads and Meta Ads Manager links are included. This release does not create ads, change budgets or spend money. Keep paid campaigns native until signup/activation/subscription tracking and the missing Meta spend configuration are verified. Platform post metrics are not yet imported; use Buffer's reports plus Solutionist's tagged acquisition scoreboard.

Provider review links:

- [Post for Me developer/white-label options](https://www.postforme.dev/developers): the documented own-credential option is the strongest match to Solutionist-only permission screens, with platform approval work required.
- [Upload-Post white-label integration](https://www.upload-post.com/whitelabel/): evaluate the whole connection flow and X link quotas before selecting it.
- [bundle.social](https://bundle.social/): compare its account and publishing-volume pricing, including X usage.
- [Ayrshare pricing](https://www.ayrshare.com/pricing/): compare multi-customer plans and onboarding.

These are evaluation links. No alternative provider was installed, purchased or connected.

## Verification

Backend unit/API checks use mocked providers and test HTTP requests; they do not publish:

```powershell
python -m pytest __tests__/test_platform_marketing.py __tests__/test_growth_intelligence.py __tests__/test_marketing_news.py -q -p no:cacheprovider
```

Additional database and browser harnesses use isolated test dependencies (not production dependencies):

```powershell
npm install --prefix output/marketing-qa --no-save @electric-sql/pglite @playwright/test
node __tests__/platform_marketing_db.mjs
# Start the frontend Vite server on port 5293, then:
node __tests__/platform_marketing_ui.mjs
```

The database harness runs real PostgreSQL-compatible PGlite locally, replays the migration twice, and verifies batch rollback, stale review, unique claims, pause, expiry, audit and denied tenant access. It is not a live Supabase/network-concurrency test. Browser checks use the mocked `tests/platform-marketing-preview.html` fixture at desktop and 390px widths. Real account connection and social delivery remain activation checks.

Frontend validation: Vite production build passed; app typecheck retains the same 14 pre-existing errors and adds none.
