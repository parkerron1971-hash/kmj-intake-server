# THE MARKETING ARC — one engine, every channel

**Opened:** 2026-08-31 · **Repo:** `kmj-intake-server` (trunk `main`)
**Status:** plan, not code. Nothing here has shipped.

---

## 1. The finding

The system is not missing "marketing." It has a lot of marketing, and
all of it points at people the platform **already knows**. Every paid
channel — the part that reaches strangers — is a stub or absent.

### What exists today

| layer | what it does | where |
|---|---|---|
| Marketing **law** | 10 fixed growth laws, injected only on marketing-shaped turns | `growth_doctrine.py` |
| Owned-media **campaigns** | goal + audience slice + email/SMS touch sequence, drafted in the practitioner's voice, executed by a 1-minute sweep | `campaigns_router.py` (712 lines) |
| Chief **verbs** for those | `plan_campaign` (A), `launch_campaign` (C), `pause_campaign` (C), `campaign_status` (read) | `chief_campaign_actions.py` |
| Weekly **briefing / insights** | AI reads 7d/30d of activity → briefing + 3-5 insights + drafted follow-ups | `growth_engine.py` (1285 lines) |
| **Attribution capture** | `utm_*`, `gclid`, `fbclid`, `ref` off the Referer + a session stash; referrer reduced to host; everything else dropped unread | `lead_attribution.py`, `marketing_pages.py:749` |
| **Conversion return path** | server-side Lead / CompleteRegistration / Subscribe, SHA-256 email only | `meta_capi.py` — **Meta only** |
| **Ad spend read** | campaign-level spend/impressions/clicks, 10-min cache, fail-soft | `meta_ads.py` — **Meta only, read-only, platform's own account** |
| **The scoreboard** | sessions → leads → waitlist → signups → active subs → MRR, bucketed by channel | `platform_console.py:/platform/growth` |
| The **agent pattern** | deterministic tick → `platform_agent_runs` (every run) → `platform_changelog` (findings only) → Chief narrates | `hermes_agent.py` |
| **Spend ceiling** | daily $ circuit breaker, per-tenant + platform, **fails OPEN** | `spend_guard.py` — **AI tokens only** |

### What is actually missing

1. **No channel abstraction.** `meta_ads.py` is 136 good lines that
   know one vendor. Google, Reddit and X on that pattern is four
   near-identical files, four cache dicts, four error shapes, and four
   places to forget a fix.
2. **No campaign object that spans paid and owned.** A `campaigns` row
   today *is* an email/SMS sequence. There is nowhere to say "this
   Reddit ad set and this nurture sequence are the same push."
3. **No money object.** `spend_guard` caps AI tokens and fails **open**
   by doctrine — correct for tokens. There is nothing at all for ad
   dollars. An agent holding a write-scoped Google Ads token with no
   budget object is the single largest risk in this whole idea, and it
   is not hypothetical: budget writes are the first thing anyone
   automates.
4. **Conversions flow back to one channel.** Meta gets server-side
   signal; anything else would optimise blind against browser pixels.
   This is the difference between a channel that gets cheaper over
   time and one that does not.
5. **Click ids we do not capture and can never backfill.**
   `CAMPAIGN_KEYS` is `utm_* + gclid + fbclid + ref`. Missing:
   `rdt_cid` (Reddit), `twclid` (X), `msclkid` (Microsoft),
   `ttclid` (TikTok), `li_fat_id` (LinkedIn). No click id → no
   server-side conversion match on that channel, ever, for those
   clicks. `_channel_of()` likewise maps only `gclid`/`fbclid`, so
   Reddit and X spend would land in the scoreboard as a referrer host
   or as "untracked".
6. **No creative pipeline.** Chief writes email and SMS copy well. It
   has never written an ad, there is no approved-creative library, and
   `growth_doctrine` (which is exactly the right rubric for ad copy)
   is not wired to anything that produces one.
7. **No agent.** Nothing runs a marketing beat. `/platform/growth` is
   a page somebody has to remember to open.

---

## 2. The shape

Five layers. The load-bearing decision is the first one.

### 2.0 Tenancy: one engine, platform as tenant zero

Every table below carries `business_id uuid NULL`.
**NULL = the platform itself.** This is not a new idea in this repo —
`/platform/growth` already reads `site_events` with
`business_id=is.null` to mean "the marketing site, not a practitioner's
site." The marketing engine adopts the same rule.

Why this and not two systems: the practitioner-facing version and
Kevin's own acquisition need the *same* adapter, the *same* budget
guard, the *same* conversion fan-out and the *same* creative rubric.
Building the platform one first and the practitioner one later means
building it twice. Building one engine and running the platform on it
means **every practitioner-facing bug gets found by Kevin first**,
against his own money, before a paying practitioner ever sees it.

RLS: practitioner rows owner-scoped exactly like `contacts`
(see `docs/RLS_MODEL.md`); `business_id IS NULL` rows readable only
through `require_owner` (`PLATFORM_OWNER_EMAIL`) — never through the
per-business policy, or one naive `OR` hands every practitioner the
platform's ad spend.

### 2.1 Channel adapters — `marketing_channels/`

One interface, N implementations, each declaring what it can do.

```python
class ChannelAdapter(Protocol):
    id: str                    # "meta" | "google_ads" | "reddit" | "x"
    name: str
    capabilities: set[str]     # {"read_spend","push_conversions",
                               #  "read_entities","set_budget",
                               #  "set_status","create_campaign"}

    def configured(self, account: AdAccount) -> bool: ...
    async def read_spend(self, account, since, until) -> SpendReport: ...
    async def read_entities(self, account) -> list[AdEntity]: ...
    async def push_conversion(self, account, event: ConversionEvent) -> bool: ...
    async def set_budget(self, account, entity_id, daily_cents) -> Result: ...
    async def set_status(self, account, entity_id, status) -> Result: ...
```

Rules, taken straight from `meta_ads.py`'s existing doctrine:

- **Unconfigured is a field, never an exception.** `{"configured": False}`
  and the panel does not render the card.
- **An upstream error is a field, never a 500.** The funnel must not
  die because a vendor rate-limited a spend read.
- **A missing capability greys the control out.** X may never grant
  write access; the UI must be honest about that rather than fail on
  click.
- Reads cached per (account, window); a failed read is **not** cached.

`meta_ads.py` and `meta_capi.py` become the first adapter — a port,
not a rewrite, and the port is what proves the interface is real.

### 2.2 The ledger — one migration

`supabase/APPLY-2026-XX-XX-marketing-engine.sql`, idempotent, plus a
row in `docs/MIGRATIONS.md`.

| table | holds | notes |
|---|---|---|
| `ad_accounts` | one row per (tenant, channel, external account id) | credential **reference** only — tokens stay in env / the existing OAuth token store, never in a readable column |
| `ad_campaigns` | mirror of the vendor's campaign/ad-set tree | `external_id`, `channel`, `status`, `daily_budget_cents`, `objective`, `last_synced_at` |
| `ad_metrics_daily` | `(account, entity, day)` → spend, impressions, clicks, conversions | UNIQUE on that triple = the sync can crash mid-run and re-run without double-counting (same discipline as `campaign_sends`) |
| `ad_creatives` | headline / body / image ref / channel / status | `status`: `draft` → `approved` → `live` → `retired`. Nothing ships without an explicit approval row. |
| `marketing_budgets` | `(tenant, channel or null)` → daily + monthly ceiling cents | the object §2.3 enforces |
| `marketing_agent_runs` | every tick, findings or not | sibling of `platform_agent_runs` |

`campaigns.paid_link_id` (nullable FK to `ad_campaigns`) is the one
column that joins owned media to paid — so "the spring push" can be a
Reddit ad set *and* a nurture sequence and report as one thing.

### 2.3 `ad_spend_guard.py` — the sibling that fails CLOSED

Deliberately the mirror image of `spend_guard.py`, and the docstring
should say so in as many words.

`spend_guard` fails **open** because a bookkeeping hiccup must never
brick Chief, and the downside of one extra AI call is cents.
`ad_spend_guard` fails **closed** because the downside of one extra
budget write is *whatever the vendor will spend before somebody
notices*. If we cannot prove we are under the ceiling, we do not raise
spend.

- Ceilings: daily + monthly, per tenant, and per channel within a
  tenant. Platform ceilings come from env
  (`AD_DAILY_CAP_USD`, `AD_MONTHLY_CAP_USD`); practitioner ceilings
  from `marketing_budgets`.
- **Every adapter call that can increase spend** — `set_budget` up,
  `set_status` → active, `create_campaign` — passes the guard first.
  Calls that *decrease* spend (pause, budget down) always run, even
  when the guard is broken. Safety has a direction.
- Crossing 80% pushes to the owner via the existing
  `push_notifications` rail, exactly as `spend_guard._push_owner` does.
- Kill switch `AD_WRITES=off` disables every write capability
  platform-wide without a deploy.

### 2.4 The conversion return path — `conversions.py`

The piece that actually lowers cost per acquisition, and the cheapest
piece to build.

One internal event (`Lead`, `Signup`, `Subscribe`, plus a value in
cents) fans out to every configured channel's server-side API, each
matched by the click id captured at the door:

| channel | endpoint | matched by |
|---|---|---|
| Meta | Conversions API — **already built** | `fbclid` / `_fbp` / `_fbc` + hashed email |
| Google Ads | Enhanced Conversions for Leads | `gclid` + hashed email |
| Reddit | Conversions API | `rdt_cid` + hashed email |
| X | Conversion API | `twclid` + hashed email |

Privacy rules are inherited verbatim from `meta_capi.py`, which already
got them right: the raw email never leaves the process (SHA-256 after
trim + lowercase), an event with no matchable identifier is **dropped
rather than sent as noise**, and every send fires after the response so
a marketing beacon can never slow a signup down.

This layer depends on **PR 1** and only PR 1. It is worth building even
if the rest of this document is rejected.

### 2.5 The agent — `marketing_agent.py`

Named **Argos** (the hundred-eyed watcher — free; `hermes` is taken).
Rename at will.

Built on the Hermes pattern exactly, because Kevin already ruled on it:
*one brain, many senses.* Argos is a **sense**. It is deterministic, it
spends no LLM tokens, it never converses. It looks, and it writes what
it saw. The Chief reads those findings in its snapshot and does the
talking.

**The beat** (daily, leader-gated like every other job in
`kmj_intake_automation.py:1057+`):

1. Pull yesterday's spend + metrics per channel/campaign into
   `ad_metrics_daily` (idempotent upsert).
2. Join spend against `/platform/growth`'s existing funnel to compute,
   per channel: **CAC**, cost per lead, lead→signup rate, signup→paid
   rate, and payback against `TIER_PRICE_CENTS`.
3. Fire the named conditions — deterministic, no model judgment:
   - a channel's CAC crossed N× LTV
   - spend up >X% week-over-week with conversions flat
   - a campaign spending with **zero** conversions for N days
   - budget pacing: on track to blow the monthly ceiling before day 30
   - a creative whose CTR fell below its own 14-day baseline
   - an ad account that went unreadable (token expired — the failure
     mode that is currently silent, and is already listed on
     `platform_console.BLIND_SPOTS`)
4. Write every run to `marketing_agent_runs`; write **only findings**
   to `platform_changelog`. No noise, same as Hermes.
5. Register in the Mission Control agents panel
   (`platform_console.py:1160+`) as `{"id": "argos", "kind": "watcher"}`.

**Then the Chief proposes.** The narration and the recommendation are
Chief's job, using `growth_doctrine` — which is already gated to
marketing-shaped turns and already says the right things (G3 diagnosis
before prescription; G4 name the ONE move). The doctrine needs one new
law for paid, roughly: *rented traffic is a tap, not a strategy — every
paid dollar ends in something owned.* That is G5 applied to money.

**Autonomy** (`action_registry.py`, A/B/C):

| verb | effect | class | why |
|---|---|---|---|
| `marketing_status`, `channel_performance`, `creative_performance` | read | — | exposable to an agent surface |
| `draft_ad_creative` | write | **A** | a reviewable artifact, an edit away from right — same as `draft_email` |
| `pause_ad_campaign`, `lower_ad_budget` | write | **A** | reversible *and* protective; spend only goes down |
| `raise_ad_budget`, `launch_ad_campaign`, `create_ad_campaign` | write | **C** | money leaves, irreversibly. **Proposal-only, forever.** Not a tuning knob. |

Per the registry's own doctrine, class C does **not** mean Chief cannot
do it — a practitioner (or Kevin) who says "raise the Reddit budget to
$40" has supplied the approval. It means Chief never does it
*unprompted*. Combined with §2.3, that is two independent controls on
the same failure, which is what money deserves.

---

## 3. The channel reality — verified 2026-08-31

This is the part that decides sequencing, and it is not a matter of
engineering effort. Re-verify at build time; these gates move.

| channel | read spend | conversions back | write (budgets/campaigns) | the gate |
|---|---|---|---|---|
| **Meta** | already built | already built | needs `ads_management` | System User token, already held. Easiest by far. |
| **Google Ads** | yes | Enhanced Conversions | yes | Developer token + OAuth2. Tiers: Test → **Explorer** → Basic → Standard. Explorer (new, Feb 2026) auto-upgrades some tokens to hit production without waiting on a human, capped ~2,880 ops/day. Basic review can land in hours once brand verification is done on the linked Cloud project. **Applying is the long pole; start it before writing code.** |
| **Reddit** | allow-listed | **easy** | allow-listed | Two different doors. The **Ads API** is allow-listed by Reddit sales/partnerships (spend or partner status). The **Conversions API** is granted to most advertisers with no spend bar — a non-expiring conversion access token from the ad account. So: **conversions yes, management probably not, for a while.** Note their 2026-07-13 change requiring `conversion_pixel_id` on ad groups / CBO campaigns. |
| **X** | approval | approval | approval | Ads API is a separate approval-gated partner program from the general X API, manual review, OAuth 1.0a for writes, and the advertiser must grant the app's @username access at business.x.com. Not subject to the general API's pay-per-use pricing. **Hardest gate; treat as speculative.** |

The honest read: **Meta is done, Google is an application away, Reddit
is half-open (measure yes, manage no), X may never open.** An
architecture that assumes all four behave alike will be wrong within a
month. That is precisely why §2.1 makes capabilities per-adapter data
rather than an assumption.

---

## 4. The arc

Ten PRs. Each independently shippable and independently useful — the
same discipline as `LEAD_CAPTURE_ARC_SPEC.md`. One PR per change; never
stacked.

### PR 1 — Capture the click ids we can never backfill

**No dependency on any decision below. Smallest, most urgent.**
Add `rdt_cid`, `twclid`, `msclkid`, `ttclid`, `li_fat_id` to
`lead_attribution.CAMPAIGN_KEYS`; the same keys to the two hardcoded JS
lists in `marketing_pages.py` (~:749 and ~:790); map them in
`platform_console._channel_of()` (`rdt_cid`→`reddit-ads`,
`twclid`→`x-ads`, `msclkid`→`bing-ads`, `ttclid`→`tiktok-ads`).
Tests extend `__tests__/test_lead_attribution.py`.
Everything downstream (`site_analytics`, `public_site`) reads
`CAMPAIGN_KEYS` and inherits it for free.

**Why first:** the day a Reddit ad runs without this, those clicks are
unattributable and unmatchable *forever*. Nothing else here has a
deadline; this one does.

### PR 2 — The ledger + the tenancy rule

The migration in §2.2, RLS per §2.0, `docs/MIGRATIONS.md` row, no
behaviour change. Ships dark.

### PR 3 — The adapter interface + Meta ported onto it

`marketing_channels/base.py` + `marketing_channels/meta.py` wrapping
today's `meta_ads` / `meta_capi`. `/platform/growth` reads through the
adapter. **Proof the interface is real: the panel renders identically.**

### PR 4 — `ad_spend_guard.py`

The fail-closed ceiling, before a single write capability exists
anywhere. Ships with tests that assert the *closed* direction, and that
decrease-spend calls survive a broken guard.

### PR 5 — Conversion fan-out

`conversions.py` + Google Enhanced Conversions + Reddit CAPI on top of
PR 1. Meta keeps working unchanged. Cheapest real ROI in the arc.

### PR 6 — Google Ads adapter (read)

Spend, campaigns, keywords. Read-only. Gated behind the developer-token
application, which should be filed the same week PR 1 merges.

### PR 7 — Argos, the watcher

The daily beat of §2.5, read-only findings, Mission Control
registration. This is the first PR where the system *tells Kevin
something he did not go looking for.*

### PR 8 — The creative pipeline

`ad_creatives` + a Chief verb that drafts against `growth_doctrine`
(class A) + the approval flow. Nothing goes live without an approval row.

### PR 9 — Write capabilities behind proposals

`set_budget` / `set_status` on Meta and Google, each behind
`ad_spend_guard` *and* the class-C proposal gate. Reddit/X write only if
their gates ever open.

### PR 10 — The practitioner unlock

The same engine, `business_id` non-null: per-business ad accounts,
per-business budgets from `marketing_budgets`, feature-gated by plan
tier, `paid_link_id` joining paid to the existing nurture campaigns.
Priced as a real feature — the platform has been running on it for
months by this point.

---

## 5. What this needs from Kevin

**Decisions**

1. **Scope.** Platform-only, practitioner feature, or one engine with
   the platform as tenant zero? This spec assumes the third; PRs 1-9
   are identical under any of the three, so the answer is only urgent
   by PR 10.
2. **Ceilings.** Starting `AD_DAILY_CAP_USD` / `AD_MONTHLY_CAP_USD`.
   Pick numbers you would be annoyed but not hurt by.
3. **Autonomy floor.** The table in §2.5 keeps every spend *increase*
   proposal-only forever. Confirm that is the intent — it is the one
   line in here I would not move without you saying so out loud.
4. **The name.** Argos, or something else.

**Access to start (all human-wait, none blocking code)**

- Google Ads: developer token application + brand verification on the
  linked Cloud project. **File this first; it is the long pole.**
- Reddit: a conversion access token from the ad account (easy), and a
  separate ask to Reddit sales for Ads API allow-listing (slow).
- X: developer app + Ads API access request. Assume no.
- Meta: nothing — `ads_management` scope on the existing System User
  when PR 9 lands.

**Costs**

Argos spends no model tokens by design (it is a sense, not a brain).
The only new AI spend is PR 8's creative drafting, which is a Chief call
already metered by `api_usage_logger` and capped by `spend_guard`. The
real new spend is ad spend, and §2.3 is the thing that bounds it.

---

## 6. What I would not build

- **A bid manager.** Google and Meta optimise bids better than anything
  worth writing here, and the reasoning already written into
  `meta_ads.py` ("campaigns are created and managed in Ads Manager,
  which is better at that job") applies with more force to bidding. The
  edge is not in the auction; it is in feeding better conversion signal
  into it (§2.4) and in joining spend to *revenue*, which the vendors
  structurally cannot see and `/platform/growth` already can.
- **A tactic library.** `growth_doctrine.py` already argues this out:
  laws are rubrics, tactic libraries are one industry's moves dressed as
  universal. Ad copy gets the doctrine, not a swipe file.
- **Four vendor files.** See §2.1.
