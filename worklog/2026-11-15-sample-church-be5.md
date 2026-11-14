---
title: "The sample church's polish before the run-through (sample church, BE-5): its rooms open, the welcome and the day-3 note, comps on any plan, the church pages' line"
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14, approved the sample church signup: "top tier, no cut corners". BE-5 is the polish before the run-through: the rooms and reports open, the welcome email, one note on day 3 ("one note on day 3"), the comp bug BE-1 found, and the church pages'' trial line.'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Not proved on the real database or a real inbox: no production reads or writes, no email sent. The first tester's signup is the proof: the welcome's subject starts 'Welcome. Look around a sample church', and three days later (if they haven't started) 'Ready to start <church>?'. Logs: [lifecycle] welcome sent biz=<id> (sample church), [lifecycle] sample follow-up scanned/sent."
  - "Read, not changed: the ordinary welcome still says 'Your first 7 days on any plan are free.' to a church that signs up with the switch off (a no-card trial is what it gets then, so it is true today; it stops being true for churches once CHURCH_SAMPLE=on, and then they get the sample's welcome instead)."
  - "The founding line is Kevin's wording verbatim ('... for as long as they stay, until January 31.'). It could be read as the price lasting until January 31; 'The offer ends January 31.' would be unambiguous if he wants it."
  - "The comp fix changes access for any business comped on a church, barber or ChurchSavvy plan with no live subscription: locked (or grace) before, full now, which is what a comp has always meant (plan_of already gave them the plan). Not checked against production (no reads were allowed): a comped, non-grandfathered business that has been seeing the paywall will now open."
  - "A What's New entry, and the switch to CHURCH_SAMPLE=on, after the run-through (Thursday)."
decisions:
  - "Item 1's seam is a new feature_gates.opens_feature(row, feature), asked by billing_limits.require_feature (the 402 on a room or report) and entitlements()' `allowed` (the app's FeatureGate) and nothing else: has_feature(), or a sample row looking at a feature of SAMPLE_TOUR_PLAN = church_growing. A test pins that only those two ask it."
  - "Not plan_of(): it feeds the allowance (usage_metering's allotment, limit_for, monthly_credits), seats, texts (church_texts), clip hours, Chief's model lanes by plan, MRR, the Money room's income, the business cap and the billing rehearsal. A sample's plan_of stays None, so all of those stay what they were (allotment 0, can_interact False)."
  - "Not has_feature(): its direct callers are AI or outside-agent surfaces (site_concierge.is_enabled, mcp_oauth's two tier checks, mcp_server's tool and connector gates, connected_ai.enabled); they keep saying no for a sample, a second wall behind BE-3's. Not plan_features(): it is a pure function of a plan key and can't see the row. Not plan_includes(): it guards money spent unasked (the marketing suite's drafts and flyers, standing permissions) and stays at nothing."
  - "Growing because the start sheet (FE-2) picks it first and it carries every church feature but the audit trail, the outside accountant and marketing autopilot, which stay shut in the tour too. entitlements() keeps plan null and included_in_plan false for a sample (UpgradeCard, ProfileCard and service_profile read those), and adds sample_features_of: church_growing."
  - "require_feature callers on write or spend paths (clip runs, the sourcing search and RFQ send, chief bookkeeping's analyses, contractor pay, period close, a texting number) now pass the plan gate for a sample, and are stopped where they were already: the write guard's 409 on every POST that names a sample, require_card's 409 (numbers), llm_call's refusal, the send seams. The GET-only callers (the reports, the GL, the close screen, clip and number status) open."
  - "The welcome: send_welcome(..., church_sample=) picks sample_welcome_body; create_business passes its applies() answer; the retry (church_sample None) asks sample_church.applies(row, the owner's email) itself, which reads nothing while the switch lets nobody in. Same delivery key business/<id>/welcome, same stamp, same first-business rule: one welcome either way."
  - "The day-3 note: lifecycle_emails.sample_follow_up_tick, hourly at :50 (job sample_follow_up, beside week_beats; classified in the BE-3 pin test as reading homes only). Candidates are active, is_sample=is.false homes with no status, subscription or trial, signed up 3 to 6 days ago; each is read again just before the send and must still pass sample_church.applies(row, owner's email) (a church, not started, no comp, not grandfathered, enforcement on, the switch, testers in test mode), have a sample that was seeded (seeded_at) and isn't ending, and carry no settings.lifecycle_emails.sample_follow_up_at. Delivery key business/<home>/sample_follow_up, then the stamp on the HOME: a lost stamp still can't send twice. Nothing reads or writes the sample row except sample_for()."
  - "Opt-outs are the lifecycle ones: LIFECYCLE_EMAILS=off, and send_via_resend's suppression list and List-Unsubscribe header (every lifecycle send goes through it). No business_id is passed, so it is the platform's mail to the owner, and BE-3's reserved-domain guard still applies to the address. sample_church.anyone() (no read) stops the tick before it reads anything while CHURCH_SAMPLE lets nobody in."
  - "Both emails greet as Chief does ('Pastor Sam Lee' -> 'Hi Pastor Sam,'); the titles are copied from chief_prompt (which can't be imported before chief_of_staff) and a test holds the two together. No 'business', 'client', 'trial' or free days; brand_voice.offenses is empty for both."
  - "The founding line only while church_founding.public_state() has a place left, its number and end day from the offer ('The first ten churches keep the founding price for as long as they stay, until January 31.'; one place: 'The first church keeps ... as long as it stays'; no end date: ends at 'stay.')."
  - "The comp fix: feature_gates._access_state honours comp_tier in ALL_PLANS (what plan_of() and POST /access/business/{id}/tier accept), not PLANS. Every ALL_PLANS key is pinned full; a comp that names no plan is still no comp; a comped church still can't be pulled into a sample."
  - "The church pages: with CHURCH_SAMPLE=on (sample_church.open_to_all: on, enforced, columns there), _trial_tokens(church=True) says CTA 'Start free, no card', TRIAL_LINE 'Look around a sample church first, no card needed. No contract. Leave any time, and your records go with you.', TRIAL_FINE 'Look around a sample church first, no card needed · your first month starts the day you choose your plan'. With the free week back: '... no card needed. 7 days free once you choose your plan.' Off and test: unchanged (pinned equal). The coach pages never change."
related: [2026-11-15-sample-church-be1.md, 2026-11-15-sample-church-be2.md, 2026-11-15-sample-church-be3.md, 2026-11-15-sample-church-be4.md]
---
BE-5 polishes the sample church before the run-through. Everything here is
inert for real users until CHURCH_SAMPLE=on (a sample row exists only for a
tester; the emails and the page line ask the switch), except the comp fix.

Overlaps: read both repos' `worklog/` first. BE-1..4 (#1851, #1854, #1855,
#1856) and the photos (#1858) are the backend half; FE-1, FE-2 and FE-4
(solutionist-studio #1561, #1563, #1564) the app's. FE-4's log left "the
welcome email's sample words" and "the church pages don't say look around
first" to the backend: both are here. A frontend session is building the
church Home opening and FE-3 in parallel; nothing here touches the app.
In BE-1..4's files this PR adds `sample_church.anyone()` (applies() asks it
too) and one line in the BE-3 job pin test.

## The emails

Welcome, subject "Welcome. Look around a sample church before <church> starts":

    Hi Pastor Sam,

    Your account is ready. Before First Church starts, you can look around
    Grace Street Fellowship, a sample church that is already set up: its people
    and families, its Sundays, giving, groups, sermons and website. It's made
    up, so nothing you do there is saved or sent.

    Chief answers 10 questions about it. Ask who has missed the last few
    Sundays, how giving is doing this month, or for a note to a family that
    visited, and see what Chief would do in a real week.

    When you're ready, press "Start your church" at the top of the screen and
    choose your plan. First Church starts that day, ready for your own people
    and records.
       <app>/

    The first ten churches keep the founding price for as long as they stay,
    until January 31.            (only while a founding place is open)

    No contract. Leave any time, and your records go with you.

    Reply to this email if anything is unclear. A person reads it.

    The Solutionist System
    <support address>

Day 3, subject "Ready to start <church>?":

    Hi Pastor Sam,

    Grace Street Fellowship, the sample church, is still there for you to look
    around: last Sunday's attendance, the families who visited and came back,
    giving by fund, and the follow-ups that keep a church's week moving.
    Nothing there is saved or sent.

    Chief has 8 of your 10 questions left to answer about it.
        (or: "Chief still has all 10 of your questions to answer about it." /
         "You've asked Chief all 10 of your questions. In your own church,
          Chief keeps going." / unreadable: "Chief answers 10 questions about it.")

    When you're ready, press "Start your church" ... (as above), the founding
    line while open, the promise.

    If something is holding you back, reply and tell us. A person reads it.

`__tests__/test_sample_church_be5.py` pins all five items.
