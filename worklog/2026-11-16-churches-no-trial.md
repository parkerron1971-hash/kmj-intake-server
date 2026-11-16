---
title: No church gets the no-card trial; a church's first week starts when it pays; a true church welcome; the tier mirror holds church plans
date: 2026-11-16
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-16, after the first real pastor signed up with Google and was handed the business trial: "make sure trial is only for business side not church side", "top tier, no cut corners"'
status: in review
prs: [kmj-intake-server#1875]
migrations: [supabase/APPLY-2026-11-16-tier-all-plans.sql (NOT APPLIED; the parent session applies it)]
left_undone:
  - "Apply supabase/APPLY-2026-11-16-tier-all-plans.sql (SQL editor). Step 2 re-mirrors tier for founding churches still on their founding price (1 row expected: the first church, professional -> church_growing). Any other stale mirror is fixed by its next Stripe event."
  - "Frontend, BusinessSettings.tsx: the Settings chip and the 'Billing and plan' row print businesses.tier raw ('Professional plan' for the first church today; 'Church_growing plan' once the mirror is right). It should use planLabel(entitlements.plan), as the sidebar chip and WorkspaceShell already do."
  - "Frontend, AccessGate: a church that never subscribed reads 'A subscription is needed to continue' and 'contacts, invoices, books, your Chief'. With no trial this is a new church's first screen; it wants church words (choose your church's plan, the founding deal is already on the cards)."
  - "Frontend, ChurchBriefingHost: Chief's welcome for a new church opens on first sign-in without asking /billing/access. With no trial, a new church's first sign-in is the plan screen (AccessGate, z-index 5000), so the welcome may open beneath it. It should wait until access is not locked."
  - "Kevin's call, not changed: the church pages say 'Start free' (about 20 static buttons in church_site/*.html) and, with CHURCH_SAMPLE off, 'Start free, no card' / 'No card to sign up · your first month starts the day you choose your plan' (church_site._trial_tokens). That was decided 2026-11-13 as true of signing up (the overview reads 'Start free, pick your plan, then ask for the move'), and it stays literally true without the trial, but a pastor may read 'Start free' as free days. One line in _trial_tokens(church=True) plus the static buttons if he wants 'Get started'."
  - "setup_brief.launch_day counts a business as launching while young or trialing. A church that pays more than SETUP_BRIEF_WINDOW_DAYS after signing up is active, not trialing, so its morning setup step does not run even though its arc moved to the day it paid. Rare; not changed."
  - "Not proved on the real database or a real inbox: no production reads or writes, no email sent. After deploy, the next church signup prints '[no-card] no trial for <id8>: church' in Railway, and its welcome's subject is 'Welcome. <church> starts the day you choose its plan'."
decisions:
  - "no_card_trial.eligible() says 'church' for any business whose kind resolves to ministry (church_billing.is_church), after 'sample' / 'church_sample' and before every trial switch, so the answer is the same in every CHURCH_SAMPLE mode and whatever PRICE_NO_CARD_TRIAL, BILLING_ENFORCE or BILLING_TRIAL_DAYS say. Both doors (launch_access.create_business, stripe_billing.billing_access) go through start() -> eligible(). The row's own type answers (both doors' rows carry it); a row without one costs one select=type read, and an unreadable one says 'type_unreadable' (fail closed, like owner_history_unreadable)."
  - "Churches already on a trial keep it: eligible() only gates starting one, and neither door asks it for a row with a status. access_state, describe() and the reverse trial's free workspace are unchanged for those rows. A new church has no marker, so _free_workspace can never give it the free workspace: it reads locked / no_subscription, the app's plan screen."
  - "The first-run arc: create_business still opens it from the signup door for a church (a comped or grandfathered church never reaches Stripe). stripe_billing._church_first_start, read before the webhook's patch, answers True only for a church with no Stripe subscription yet, or this same subscription still at incomplete; then begin(source='subscription') runs, which opens the arc if missing or re-stamps a signup arc's day one to today once (its existing latch), before Chief's introduction, which a locked church cannot have had (require_units refuses it). A renewal, plan change, recovered past_due, a second subscription after a cancel, or a church's free week ending never asks, so a church that has been running can never be handed a first week. Combined with the sample-ended branch into one begin() call."
  - "The welcome: send_welcome picks the sample welcome (unchanged), else a church welcome for any church, else the business welcome (unchanged). The church welcome: subject 'Welcome. <church> starts the day you choose its plan'; the plans go by Sunday size and are on the first screen; 'Your first month starts the day you choose your plan.' (or the free days while PLAN_CHURCH_FREE_WEEK is back); then Chief's welcome and the Move-in list; founding_line() only while a place is open; church_site.PROMISE. A church that already has its way in (comp, grandfathered owner, or a plan or trial by the time the retry sends) gets 'Welcome. <church> is ready' without the plans. No 'business', 'client', 'trial', 'free' or days free; no exclamation points; brand_voice.offenses empty. Same delivery key and stamp: one welcome."
  - "The tier mirror: businesses_tier_check last widened 2026-10-24 (ChurchSavvy) and never learned the four church plans, so the webhook's patch with tier=church_growing was refused, retried without tier, and the first church kept the trial's 'professional'. businesses_comp_tier_check had the same gap, and POST /access/business/{id}/tier answered ok while the database refused a church comp. The migration widens both to feature_gates.ALL_PLANS (plus the retired tier words). The writers already set tier = the resolved plan key; the fallback stays and now prints when it fires. The comp endpoint now answers 502 when the write is refused and 404 when no row matched."
  - "Who reads businesses.tier: the app's Settings chip and 'Billing and plan' row (BusinessSettings.tsx), the church extras' fallback for church-ness and the logins plan key (ChurchPlanExtras.tsx, after entitlements' plan), and the AI support-reply drafter's 'plan' fact (support_drafts.py, comp_tier or tier). Mission Control's roster, the sidebar chip, WorkspaceShell and every gate read plan_of() / entitlements, which were right all along."
  - "A test pins that the newest migration defining each CHECK lists every ALL_PLANS key, so the next new plan fails CI until its migration is written instead of losing its mirror silently."
related: [2026-11-15-sample-church-be1.md, 2026-11-15-sample-church-be5.md, 2026-11-13-church-plans-no-free-week.md, 2026-10-03-no-card-trial.md]
---
The first paying church signed up today with Google and was given the
business no-card trial (7 days on Professional, 500 credits), then paid for
Growing at the founding price. From this PR no church starts that trial:
it meets its plans on the first screen, and its first week (the first-run
arc) starts the day it pays. Its welcome email says so, with no free days
in it. The tier mirror's CHECK learns the church plans, and the migration
puts the first church's mirror right.

Overlaps: read both repos' `worklog/` first. BE-1 and BE-5 of the sample
church (#1851, BE-5) built `eligible()`'s sample reasons, the sample
welcome and the sample-ended arc branch; this PR keeps all three and adds
beside them. A frontend agent is fixing the Google sign-up church signal in
parallel; nothing here touches the app. The three frontend follow-ups above
came out of reading the app for this change.
