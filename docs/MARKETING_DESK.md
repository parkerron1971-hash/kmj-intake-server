# The Marketing desk: one week, one place, Chief in front

Mission Control → Growth → Marketing. This is Solutionist's own marketing,
and the setup that will later ship to businesses. It was streamlined on
2026-10-02 from the design canvas
https://claude.ai/artifact/R4YcBsj9xwtAgyDFsj19pW, which Kevin approved.

## The weekly loop

1. **Thursday 7:00 AM ET: plan next week** (`marketing_engine`). The engine
   reads the numbers and names one problem with the number that proves it. It
   picks plays from a fixed library and saves five posts as drafts, each with
   a flyer. Monday to Wednesday it plans the rest of the current week only if
   that week was never planned. It never plans overnight.
   - Before this release, `week_window` rolled to next week only once fewer
     than two posting times were left. That made every plan land on Thursday
     at 10:00 by accident, while the desk said "Monday 7:00".
2. **Chief tells the owner** (`marketing_desk`):
   - a push (`tell_owner_about_plan`), sent for scheduled plans only, and only
     once for a week that fails;
   - a Today item ("Chief drafted next week. Five posts wait for your OK");
   - Chief's read on the desk, which the drawer also opens with.
   All of it is computed from rows. No model call is made.
3. **The owner decides on the desk.** They can approve the week or one idea,
   ask Chief to change a post, or skip it. Approval stays the owner's alone:
   Chief has no approve action, and `/approve` still binds exact content hashes.
4. **Posts go out at 11:00 AM**, or the desk speaks up. A failed post, an
   unconfirmed delivery, or publishing that is paused while posts are approved
   reaches Today the same hour. `due_tick` pushes once per tick through
   `tell_owner_about_delivery`.
5. **Results.** Every post has its own `/go/` link, and the next plan leans on
   the plays that did well.

## What changed in the backend

- `marketing_desk.py` (new) handles the desk's read, masthead, "Needs a look",
  the Today items, the Chief digest and the pushes.
  - A **post** here means one idea: the same caption on every channel.
  - **Missed** drafts (time passed, never approved) are never counted as
    waiting; they become a "Reschedule or let go" item.
- `GET /platform/marketing/engine` adds `note`, `masthead`, `attention`,
  `deadline` and `relation`. `planning` is now read from the run row, so every
  replica agrees; before, it was a per-process set.
- New endpoints:
  - `POST /platform/marketing/slot/edit` changes one idea's caption and/or
    time on every channel. All posts are checked before any is saved, and
    each goes back to draft.
  - `POST /platform/marketing/slot/cancel` skips an idea or lets missed
    drafts go.
  - `POST /platform/marketing/posts/{id}/not-sent` is the way out for an
    unconfirmed delivery once the owner has checked Buffer.
- `dispatch`: an error before Buffer is reached (a storage blip, a channel
  lookup) puts the post back to `approved`, and the next tick tries again
  until its window closes. A preflight refusal fails it. Only an error once the
  create is under way is `uncertain`. Before, it escaped, and the row went
  `dispatching` → `uncertain` with no exit. A result that cannot be recorded
  is logged and left for the recovery sweep, never re-sent.
- `/slot/edit` and `/slot/cancel` check every channel's revision and state
  before writing anything. A change in the instant between check and write is
  reported channel by channel.
- New posts go everywhere by default (2026-10-02, after a hand-written post
  went to Instagram alone). `POST /platform/marketing/ideas` saves one caption
  for every connected channel in one insert unless `channel_ids` is given,
  leaves Instagram out (and says so) without a picture, and takes the next open
  slot (`GET /ideas/next-slot`: a weekday at 11:00 AM or 3:00 PM Eastern with no
  post at that time) unless `run_at` is given. Chief's `marketing_new_post`
  calls the same function, so Chief makes a post and says where and when,
  instead of asking first.
- Posting right away, with the owner's yes (2026-10-02). Kevin: "allow for
  permission to be given if they are looking to post right away."
  - On the desk, "Post now" in the new-post editor asks first
    (`POST /ideas` with `post_now`), and "Approve and post now" sends one
    reviewed post (`POST /post-now`, bound to its content hashes). The time
    moves to two minutes out and the owner's approval follows in the same
    step. Before anything is saved or moved, both check that publishing is
    on, that it is not paused, and that Buffer says each channel is live.
  - Chief's `marketing_post_now` is in the `review` group, so it never
    runs on its own. Its card freezes the exact caption and channels (or
    the desk post's words and revisions) when it is proposed. The handler
    runs only from a human-approved card and re-checks the frozen words.
- The seven-caption generator (`POST /platform/marketing/week`) is retired.
  The weekly plan is the one way a week is drafted.
- Today (`platform_today._marketing`) reads the weekly plan's posts. It used
  to count the platform business's content calendar, a different pipeline, so
  the engine's drafts never reached Today.
- Chief:
  - The Mission Control snapshot carries `marketing` (the digest), and
    `DIGEST_PROMPT` tells Chief to include it in "what needs me?".
  - The marketing drawer adds `marketing_edit_slot` (drafts gate),
    `marketing_skip_slot` and `marketing_replan_week` (marketing_stop gate,
    so the owner approves each on a review card).
  - A rewrite may not add a link, a hashtag or a number the post did not
    already carry.

No migration is needed.

## Before this ships to businesses

What is still platform-only:

- **Storage:** `platform_marketing_config` is a single row (`id = true`). The
  `platform_marketing_*` tables have no `business_id`, and the run id is
  keyed by week alone.
- **Credentials:** there is one `BUFFER_API_KEY` from the environment.
- **Brand and domain are hard-coded:**
  - `mysolutionist.app` in `tracked_link`, `short_link`, `follow`, `LANDING`
    and the news URLs;
  - the flyer footer;
  - `AUDIENCE`, `SYSTEM` and `TZ` in the engine.
- **Signals** come from platform-wide sources: `growth_summary`,
  `founder_offer`, `public_claims`, and `site_events` where
  `business_id is null`.
- **Owner gates:** every route uses `require_owner`; pushes go to
  `PLATFORM_OWNER_EMAIL`.

Tenant social publishing today is separate: Meta only, through
`content_calendar` and `post_approval`.

## The desk for every business — API

B4 of `docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md` (2026-10-07). The same
desk, for one business, on the `marketing_*` tables through
`business_marketing_store`. `business_marketing.py` is mounted at
`/marketing/{business_id}`, after `clip_posting` and before the public-site
catch-all. **Nothing here sends.** B5's sender claims approved posts
(`marketing_claim_due`) and re-checks everything at send time.

| Route | Who | What |
| --- | --- | --- |
| `GET /engine` | owner + members | settings, this and next week's posts, Chief's read, attention, `level`, `upgrade`, accounts |
| `GET /ideas/next-slot` | owner | the next open time |
| `POST /ideas` | owner | a new post as a draft (`post_now`: saved and approved, out in two minutes) |
| `POST /approve` | owner | `[{id, revision, content_hash}]`, all or nothing (`marketing_approve`) |
| `POST /slot/edit` | owner | words, time, accounts, picture or link; back to draft |
| `POST /slot/cancel` | owner | skip a post or let missed drafts go |
| `POST /post-now` | owner | a reviewed post goes out in two minutes |
| `POST /posts/{id}/not-sent` | owner | an unconfirmed delivery becomes a failure |
| `PUT /settings` | owner | paused, plan_enabled, accounts, hour (6-21), audience, link; makes the desk row |

- **Who.** Reads use `business_access('viewer')`. Writes use `require_user`
  plus an owner check: a service-role read of `businesses.owner_id`. A member
  never approves, edits or posts.
- **One row per post.** Its accounts are in `targets`. The post id is a uuid5
  of the business and the caller's idea id, so a retried save is the same
  post.
- **Defaults for a new post.** It goes to the desk's accounts that are still
  connected, or to every connected Post for Me account when the desk names
  none. Instagram is left out without a picture, and TikTok and YouTube
  without a video; `dropped` and `note` say so. Its time is the next weekday
  at the desk's hour or 3:00 PM on the business's own clock, at least an hour
  away and not already taken. The clock is `availability.timezone`, then the
  owner's `practitioner_profiles.timezone`, then `PLATFORM_DEFAULT_TZ`, then
  UTC. A post may still go out up to six hours after its time.
- **The approval.** `content_hash` is `business_marketing_store.digest`. Any
  change bumps `revision`, recomputes the hash and drops the approval.
- **Post now** refuses, before anything is written, unless all of these hold:
  `MARKETING_DESK_PUBLISHING=on` (B5's switch, off by default), the posting
  pilot is on for the business, the desk is not paused, every account is
  still connected, Instagram has a picture, and the caption fits each network.
- **This business's rows only.** Every post, picture, clip and account is
  read with the business id in the filter, so another business's id answers
  exactly like a missing one.
- **Links.** `landing_url` must be https on the business's own host: its
  `mysolutionist.app` subdomain, or its custom domain once verified.
  `publish_text` is the caption until B6 adds the tracked short link.
- **Fail closed.** A failed read is a 503 in plain words, never an empty desk.
- **`level`** comes from the real plan (`feature_gates.plan_includes`, which
  ignores `BILLING_ENFORCE`). `upgrade` is the next level's feature and
  `upgrade_plan_for`'s plan.

| Plan | `level` | `upgrade` |
| --- | --- | --- |
| Starter, no plan | suggest | marketing_week → Professional |
| Solo, Booked | suggest | marketing_week → Boss |
| Professional, Boss | week | marketing_autopilot → Solutionist |
| Professional, Boss: a personal_services business with a live booking calendar | openings | marketing_autopilot → Solutionist |
| Solutionist (practice) | autopilot | none |

`business_marketing_desk.py` computes the business desk's words from rows,
with no model call: Chief's read, the masthead, "Needs a look", Today items
and a Chief digest. They are on the business's clock: `marketing_desk`'s
wording helpers now take `tz`, and the platform desk's default is unchanged.
It promises no weekly plan until a planner exists (B8/B9). Nothing calls
`today_items` or `chief_digest` yet.

### How Chief reads a business

B7 (2026-10-07): the business's own numbers, facts and profile, read-only.
Nothing calls these yet; B8 adds the preview endpoint and the weekly
suggestion.

- **Signals** (`marketing_signals.read_signals`): service-role reads of one
  business, each bounded by a date window and a row limit, so a Thursday
  fan-out stays cheap.
  - Site visits: distinct sessions in the last 7 days, against the weekly
    average of the 28 days before (`site_analytics.business_rows`, at most
    5,000 rows, not the 50,000-row traffic report).
  - New contacts in the same windows.
  - Bookings (`module_entries`, `appointment_at`, status active): the next 7
    days against the trailing 4-week weekly average.
  - Open chairs, for a personal_services business with a live calendar and
    weekly hours set: open times in the next 7 days for its shortest bookable
    offering (`agent_site.slots_for`). No count of them goes in a caption.
  - Offerings and site news posts from the last 21 days, and whether a plan
    has been about them yet (`marketing_runs.slots[].subject_key`).
  - The last post, from `marketing_posts` and `social_publications` (a desk
    post sent through Post for Me is counted once).
- **None, never 0.** A read that fails, or reaches its row limit, is None and
  is named in `unread`. Zero means it was counted. A rule whose signal is
  None is skipped, so a failed bookings read never says "fill the calendar".
- **The diagnosis** (`business_marketing_engine.diagnose`): first match wins,
  and each names the number that proves it.

  | # | Rule | Problem | When |
  | --- | --- | --- | --- |
  | 1 | bookings_down | fill_the_calendar | next 7 days under 70% of the weekly average (at least 3 a week) |
  | 2 | empty_week | fill_the_calendar | nothing booked in the next 7 days, open times on 2 or more of them |
  | 3 | something_new | tell_about_new | an offering or news post from the last 21 days no plan has been about |
  | 4 | visits_without_leads | turn_visits_into_leads | 20 or more visits in 7 days, no new contact |
  | 5 | traffic_down | get_found | visits under 70% of the weekly average before (at least 10 a week) |
  | 6 | gone_quiet | stay_visible | nothing posted from Solutionist in 14 days, nothing approved ahead |
  | 7 | barely_seen | get_found | under 10 visits in 7 days, on a site whose counter has counted |
  | 8 | steady | stay_visible | nothing is off |

  The calendar comes first because an empty chair this week cannot be sold
  next week. The rest follow the platform's order.
- **Plays:** `offer_spotlight`, `book_a_time`, `whats_new`, `useful_tip`,
  `meet_us` and `come_back`. None names a person. `pick_plays` uses the
  platform's own `_rank` and `fill_slots`, and every slot links to the
  business's own site (the desk's link, its booking page or its home page).
- **Facts:** `creative_director.business_facts` through `verified_facts`. A
  hidden price stays out, and so do inactive or archived offerings, brand
  colours and web addresses. Every number in a caption must be in the facts.
  A dollar amount must be a stated price, and in a post about one offering it
  must be that offering's price. The only address a caption may name is the
  business's own host (`marketing_engine.check_caption(..., own_hosts=...)`).
  The platform's default is unchanged.
- **The profile** (`marketing_profile.read_profile`) holds:
  - the audience: the desk's, then the owner's `voice_profile.audience`, then
    a default for the business type;
  - the voice and the desk's clock;
  - the host and the landing page;
  - the shape: `openings` for a chair business with a live calendar, else
    `week`;
  - the caption writer's instructions, where "we" is the business;
  - the flyer footer: the business's name and host, never Solutionist's.
