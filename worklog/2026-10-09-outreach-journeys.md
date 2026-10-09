---
title: Outreach that runs by itself (review ask, win-back, rebook, birthday)
date: 2026-10-09
agent: Claude Code (Claude Opus 5.5)
asked: "work on this in order (Kevin, 2026-10-09; step 2 of the approved plan: Outreach texts that run by themselves); on the 10DLC question Kevin picked Build now, texts after"
status: waiting on kevin
prs: [kmj-intake-server#1365, solutionist-studio#1191]
migrations: [supabase/APPLY-2026-10-09-journeys.sql]
left_undone: ["JOURNEY_TEXTS stays off until Kevin adds a marketing use case to the shared number's 10DLC registration (his step in Twilio); then set JOURNEY_TEXTS=on on Railway web and worker", "the Run nurture every day switch in Business Settings still does nothing (run_nurture_for_all is never scheduled); not touched here", "quiet hours for the 24h reminders are still America/New_York for everyone; journeys use the business's own clock", "contacts.metadata.birthday from imports is not read; only contacts.birthdate", "no per-service rebook interval: rebook uses one number of days per business"]
decisions: ["journeys are computed from sessions (online bookings mirror there) and contacts every 30 minutes; the owner switches each on beside its exact words (settings.journeys), the standing approval", "review ask every plan with the owner's review link (settings.get_found.review_url), at most once per person in 120 days; win-back 60 days (14-day window), rebook 35 days (7-day window), birthday on the business's clock, from the Week level up", "email now; text only when JOURNEY_TEXTS=on AND sms_consents source booking_marketing AND no STOP; booking_marketing is not reminder consent", "9 AM-8 PM business time, 40 notes per business per day, automations_paused respected, journey_sends claimed before each note"]
related: [2026-10-09-outreach-links.md, 2026-10-09-month-calendar.md]
---
The Reach plan's step 2. Before: the only automatic client text was the
24-hour reminder; review asks, win-back and rebook were manual or Chief
email drafts, and nothing sent birthday notes. Now four journeys run by
themselves once the owner switches them on in Grow → Outreach → Automatic
(solutionist-studio#1191), by email; texts wait for the registration.
