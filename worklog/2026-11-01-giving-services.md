---
title: Giving recorded by service (giving by service, step 2 server)
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "if tithes and offering coming in sunday and it''s time to record that the system ask or allow selection for sunday or where ever type of service it is and they can record the giving for that sunday and put in mutliple people that sunday or service... the system should be able to recognize Sunday and already prepare for that service for giving. and when someone gives online the system see that and automatic connect the only giving to that service as a prefill... the treasurer should be able to set dates for possible services that are not reacurring... allow for them to set a reacurring service and time" then "build everything"'
status: in review
prs: ["kmj-intake-server (this PR)", "solutionist-studio #1432 (the screens)"]
migrations: [supabase/APPLY-2026-11-01-giving-services.sql (applied 2026-11-01)]
left_undone:
  - "Switched with GIVING_SERVICES (owner until a Thursday flip)"
  - "Step 3: closing a count (counted cash and checks, counters, the lock), reopening with a reason, the correction lock, and Chief recording gifts to a service"
  - "Step 4: the printable count sheet and reading a photo of it"
decisions:
  - "A service is every week on a day at a time, or once on a date, on the church's clock (church_checkin.church_zone_name); collects_online says the week's online gifts count toward it"
  - "A count is made when its day comes (Sunday's is ready Sunday morning), never for days before the service was added (a one-time service may be in the past, to record a night already held); one per service per day by a unique constraint"
  - "Online gifts (card through the give page, Subsplash payouts) go into the open count of a collecting service: from the previous collecting service plus 3 hours to this one plus 3 hours, so a gift during the service counts toward it. A gift in a closed count's window stays out and is listed as Not in a service"
  - "Gifts recorded into a count take the service's date; each row has its own request_id (GIVE-manual-<id>), so a repeat never records twice; each row answers for itself"
  - "A gift moves only between open counts, never to none (an online one would be placed again by its window); moving never changes its date or amount"
  - "giving_router.record_manual_gift is the one way a gift is recorded by hand (the form and a count)"
  - "Account lifecycle: the tables are deleted with the business and exported; a restored church sets its services again, and its gifts come back in no count"
related: [2026-11-01-giving-ways.md]
---
`giving_services.py` (new), `giving_router.record_manual_gift`, `kmj_intake_automation`
(router), `account_lifecycle`, `docs/MIGRATIONS.md`. Tests: `__tests__/test_giving_services.py` (14).
