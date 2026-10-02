# Solutionist marketing automation recommendation

Prepared September 15, 2026. Scope: promoting The Solutionist System from Mission Control. This is an audit and proposed build, not a launched campaign. No advertising spend, public posts, account connections, or production changes were made.

## Recommendation

Extend Mission Control → Growth into a marketing workspace. Chief prepares campaign briefs and reusable creative packages; the owner reviews a weekly batch; approved posts publish daily; attribution and conversion results return to Growth. Use the existing FastAPI/Supabase/scheduler infrastructure and connect Buffer for organic distribution. Initially operate paid campaigns in Meta Ads Manager and Google Ads, then add limited API controls once measurement is trustworthy.

This minimizes new software and connector maintenance while keeping creative decisions, approval history, and business results inside Solutionist. A new n8n or Make installation is optional, not required for the first build.

## What I verified

### Live application

Mission Control loaded in the existing Chrome session. The newer Edge session sent its Mission Control button to the Build overview; this navigation difference needs investigation before adding the new workspace.

Growth currently includes:

- A channel funnel and tagged-link builder.
- Publishing to the Solutionist news site.
- “Post as Solutionist,” with The Solutionist System and Kevin McCloud Jr available as Facebook Page choices. Their presence does not prove tokens can successfully publish today.
- Image Studio and a flyer layout/print workflow. Flyer drafts explicitly say they save on this device; the inspected browser showed zero saved flyer versions.
- Approval settings: social posts require review; publishing to the owned site has a separate autonomy setting.

The selected 30-day window showed 406 marketing-site sessions, 6 signups, zero applications, zero waitlist joins, and $0 all-time attributed MRR. Of the sessions, 338 were untracked (about 83%), 66 were labeled google-ads with zero attributed signups, and one was labeled facebook. Test records were visible. These counts are an instrumentation snapshot, not verified unique prospects or a clean acquisition cohort. No ad-account spending or conversion diagnostics were inspected.

System Health reports the Meta FB/IG application and Meta Pixel/CAPI as configured. It reports the read-only Meta spend integration missing `META_ADS_ACCESS_TOKEN` and `META_AD_ACCOUNT_ID`. Configuration presence alone is not a successful delivery test. The health log also shows repeated missing-schema errors for `chief_suggestions` and `businesses.logo_url`; investigate their effect on proactive planning and brand context before relying on unattended creative generation.

The public site advertises a seven-day trial. Opening /start in the signed-in session redirected to the app, so a new visitor's signup and activation journey remains untested. Do not treat this as a successful end-to-end conversion test.

### Backend evidence

| Existing component | What it provides | Implication |
| --- | --- | --- |
| `brand_engine_router.py`, `media_library.py` | Brand and media foundations | Reuse for the Solutionist marketing library. |
| `video_studio.py`, `video_worker/README.md` | HyperFrames video planning/rendering, narration, captions, several aspect ratios | Rendering availability depends on deployment flags/worker configuration. The documented scope excludes social publishing. |
| `meta_oauth.py` | Facebook text/photo and Instagram image publishing | Video/Reels publishing needs another delivery path. |
| `content_approval.py`, `post_approval.py`, `chief_scheduler.py` | Approve specific content and schedule unattended publication | Weekly batch approval can preserve the existing content-specific checks. |
| `chief_grow_actions.py` | Content planning and Meta publishing | A planned platform label is not proof of an implemented X or LinkedIn publisher. |
| `campaigns_router.py` | Scheduled email/SMS sequences | These are contact-nurture campaigns, not paid-ad campaigns. |
| `meta_ads.py` | Read-only Meta campaign spend | It does not create ads, set budgets, or launch campaigns. |
| `meta_capi.py`, `marketing_pages.py` | Meta conversion-event and browser-pixel plumbing | Configuration and event delivery must still be checked in Events Manager. |
| `platform_console.py`, `lead_attribution.py` | Source/click-ID capture and channel reporting | Expand to campaign, creative, paid/organic, activation, and paying-customer reporting. |

Two reporting corrections are especially important. `_channel_of` groups by source without splitting paid from organic. Its Meta “CAC” divides spend by channel signups, not new paying customers, and can include organic Facebook/Instagram signups. Rename that measure where appropriate and calculate paid customer-acquisition cost separately. Windowed activity also must not be divided into all-time revenue as if it were a matching cohort.

## First audience and message

Starting hypothesis, pending the owner's audience preference: solo service-business owners, particularly coaches and consultants. This fits the founder's existing practice and allows concrete demonstrations of contacts, bookings, invoices, and Chief. It is a strategic hypothesis, not a conclusion established by the current analytics.

Lead with one useful outcome per campaign. Example: “Run your clients, bookings, and invoices from one workspace—with Chief helping you follow through.” Show an actual workflow using demo data. Use the site's verified trial offer as the call to action, with a focused landing page for that audience.

Keep church/nonprofit messaging in a separate campaign with its own use cases and landing page. Later audience expansion should follow activation and retention evidence. Avoid generating dozens of niche campaigns before one works.

## How the weekly and daily workflow would work

1. **Weekly brief:** Choose one audience, one problem, one offer, and one landing page. Chief uses approved product facts, current pricing, and verified feature availability.
2. **Creative package:** Produce one short demo recording, two or three edited clips, two graphics, one printable flyer with a tracked QR destination, a useful tip/carousel, and channel-specific captions. Reuse source material across formats.
3. **Review once:** Show previews, exact captions, destination accounts, links, and dates together. Batch approval records approval separately for each immutable content version and channel.
4. **Publish daily:** Send the approved calendar to the selected publishing provider. Vary the content and purpose across the week; do not repeatedly publish the same flyer.
5. **Verify delivery:** Record the provider's publication ID/status/link. A queued post is not a published post. Failed or uncertain deliveries appear in an exception queue.
6. **Daily summary:** Show what published, failures, remaining approved inventory, traffic, activated trials, paying customers, and paid spend.
7. **Weekly improvement:** Review results with an adequate observation window. Create new variants of promising messages; avoid declaring winners from a handful of clicks or constantly resetting paid campaigns.

Suggested initial calendar, subject to audience response:

| Day | Core item |
| --- | --- |
| Monday | Short demo of one painful task made easier |
| Tuesday | Practical business tip with a relevant screenshot |
| Wednesday | Founder explanation or story |
| Thursday | Feature walkthrough or common question |
| Friday | Focused trial invitation and graphic |
| Saturday | Second clip adapted from the week's demo |
| Sunday | FAQ, recap, or use-case example |

Aim for a daily presence across the chosen channels, not seven forced posts per week on every network. Allow roughly 45–60 minutes for weekly creative review and 10–15 minutes daily for real questions and comments as an initial operating estimate.

## Distribution choices

### Organic social: Buffer

Use a server-side Buffer integration for Solutionist's own X, Facebook Page, Instagram, and optionally LinkedIn/YouTube channels. Its current API documents scheduling, channel-specific configuration, and sent/error status retrieval. Validate each media format against the actual account type before enabling it. [Buffer publishing API](https://developers.buffer.com/guides/posts-and-scheduling.html).

Keep exactly one delivery provider responsible for each post/channel. Existing direct Meta publishing can remain available, but the same item must not be queued through both paths. Buffer's Google Business Profile support is a separate surface from paid Google Ads.

Buffer currently offers three free channels with ten scheduled posts per channel. Essentials costs $6/channel/month for the first ten channels; four channels would therefore be $24/month before tax on monthly billing. Team costs $12/channel/month at that size and is useful if approvals must also live in Buffer. Mission Control approvals may make Essentials sufficient for the owner's workflow. [Buffer pricing](https://support.buffer.com/en-us/articles/buffer-pricing-and-features-6pJrOPuzIt), [free-plan details](https://buffer.com/pricing).

For promotion of Solutionist itself, a server-held personal API key fits Buffer's documented personal automation model. Reassess OAuth, account permissions, and metric-access restrictions before turning this into a customer-facing integration for every tenant. Do not reuse the platform owner's key across customers.

X automation should publish original, useful posts. Exclude automated unsolicited replies/DMs and repetitive duplicate posts. X's rules specifically restrict duplicative or substantially similar posts. [X automation rules](https://help.x.com/en/rules-and-policies/x-automation).

### Paid Meta campaigns

Create the initial campaign in Ads Manager using approved video/image variants, one audience hypothesis, a matching landing page, a conversion objective, and a finite budget. Reuse `meta_ads.py` for reporting after confirming its connection. Connect verified trial/registration/subscription events through the existing measurement foundation.

Later, add API actions for draft campaign creation, approved creative upload, status reads, and pause/resume under explicit campaign limits. Marketing API write access differs from the existing `ads_read` integration; own-account and customer-account access requirements must be evaluated separately. [Meta's maintained SDK and access overview](https://github.com/facebook/facebook-python-business-sdk).

### Google Ads

Start by auditing the traffic already labeled google-ads: actual search terms, destination page, spend, and conversion diagnostics. Prefer a focused Search test for demonstrated customer intent once tracking works. An image flyer is an input for certain visual placements; Search campaigns need keyword/ad-text/landing-page work of their own.

Use a clearly defined valuable conversion for bidding and distinguish primary from secondary actions. Do not optimize the campaign for simple page views while judging it on paid customers. [Google conversion goals](https://support.google.com/google-ads/answer/11461796?hl=en).

For a later native connector, follow current Google Cloud/OAuth onboarding. Google's current migration guide says developer tokens were sunset September 9, 2026, with API access now tied to Google Cloud projects. Older token-based setup tutorials are stale; account access and production API approval still need verification. [Google's migration guidance](https://developers.google.com/google-ads/api/docs/api-policy/developer-token).

Keep platform-native budget controls as the spending boundary. Google average daily budgets are not strict daily caps; most campaigns can spend up to twice that amount in a day, subject to their monthly limits. Do not promise a precise spending ceiling from a periodic Mission Control polling job. [Google budget rules](https://support.google.com/google-ads/answer/6385083).

## Build scope

### Mission Control sections

- **Plan:** audience, offer, objective, channel choices, and content calendar.
- **Create:** existing Image Studio/flyers plus Video Studio entry, brand facts, reusable templates, and format variants.
- **Review:** weekly batch previews and per-version approval.
- **Publish:** queued, published, failed, and uncertain items; live links and account health.
- **Ads:** spend/results first, approved campaign controls later.
- **Results:** visits → trial → first useful action → subscription → retention, split by campaign and creative.

### Server foundations

Use platform-scoped marketing campaign, asset-version, publication-job, publication-attempt, and daily-metric tables. Avoid overloading the tenant email/SMS `campaigns` concept. Scope the workflow to The Solutionist System brand/business; do not accidentally use KMJ's separate consulting brand or its contacts.

Store flyer projects and immutable exports in the shared library, not browser-only storage. Preserve source rights and approved facts. Render text, prices, logos, and QR codes from structured templates so they remain accurate and readable; use generated imagery where it adds value. Store reusable portrait, square, landscape, and print variants. Provider-specific validation still controls what can ship.

Use durable job claims, unique publication keys, retry backoff, and a manual exception queue. Reconcile provider status after an ambiguous timeout before retrying; a local unique constraint alone cannot prevent an external double post. Prevent overlapping calendars and expire time-sensitive offers. Refresh account tokens securely and show disconnected status visibly.

Ensure provider media URLs remain fetchable through ingestion and processing, while exposing only approved marketing exports. Include an asset content hash in approval, not just a mutable image URL. Editing creative or destination invalidates approval. A pause-all action must stop local jobs and cancel any already delegated provider queue; changing a local flag alone is insufficient.

### Measurement first

Automatically tag every link and QR destination with source, medium, campaign, and creative ID. Preserve tags through the public site, signup, and billing journey; distinguish initial source from subsequent touches. Support applicable Google click identifiers in addition to the existing gclid capture. Exclude internal/test records and clearly label unattributed traffic rather than inventing attribution.

Track activation as a real useful action, such as completing setup plus making a booking page or first invoice, with a definition appropriate to the chosen audience. Track paid customers and collected revenue separately from trial starts and MRR. Reconcile platform-reported conversions against first-party records; different attribution windows will not always agree. Respect consent choices and avoid sending private customer content in marketing events.

## Rollout and budget

**Phase 1 — foundations:** Resolve Mission Control navigation differences; investigate the observed schema errors; verify the brand/account scope; configure the missing Meta spend connection; audit signup/conversion tracking; clean test traffic; prepare one focused landing page and reusable templates.

**Phase 2 — daily organic:** Add the server-backed campaign calendar, shared flyer/video exports, batch review, Buffer delivery, and visible failure recovery. Prepare one week of content and operate it for two weeks before expanding.

**Phase 3 — measured paid test:** Run one paid acquisition channel at a time with a finite approved test budget. Since Google-labeled traffic already exists, audit that account before choosing Google or Meta for the first test. A $300–$750 total monthly test is a planning option, not a recommendation to spend without examining traffic cost and available funds. Keep X organic initially unless conversion evidence supports an ad test there.

**Phase 4 — more autonomy:** Add campaign draft APIs and narrowly bounded management actions after reporting and account connections are reliable. Generate new content automatically, but keep new claims/offers and spend expansion reviewable. Routine delivery of approved batches can be unattended immediately.

Incremental costs are the chosen Buffer plan, existing AI/image usage, video rendering/hosting/storage, and any paid media. Price these separately; there is no basis yet for a reliable all-in monthly figure. A lean version is plausibly a 2–4 week engineering project, as a rough estimate rather than a commitment; platform access, frontend integration, and tracking defects can extend it.

## Acceptance checks before unattended delivery

- A tagged test journey reaches the correct signup and activation records; test data stays out of production marketing metrics.
- A rendered graphic/video has the correct brand, readable text, working link/QR, and correct destination account.
- Approved scheduled content publishes once and records a provider ID/status. A disconnect and an ambiguous timeout both recover without duplicate posts.
- Edited content returns to review. Expired offers do not publish.
- The owner can pause all pending distribution, including provider-held queues.
- Paid/organic attribution and cost-per-trial versus cost-per-paying-customer are distinct; missing telemetry is visible.
- The weekly review can be completed in one place and seven days of approved content remain available.

Success means a repeatable flow of qualified, activated users and eventually retained paying customers. Daily output is the operating rhythm, not the success metric.
