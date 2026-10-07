---
title: Each business's marketing numbers, facts and profile, read-only (marketing suite B7)
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#TBD]
migrations: []
left_undone: ["The preview endpoint (GET /marketing/{business_id}/preview) moves to B8, to keep this PR off the routers two other PRs are changing", "Nothing calls marketing_signals, marketing_profile or business_marketing_engine yet: the caption writer, the weekly run and the fan-out are B8/B9", "Play scores are always {} until tracked links and results land (B6)", "Open chairs use the shortest bookable offering; D5's most-booked offering waits for B11, which verifies module_entries' offering fields", "Not verified against production: past bookings keep status active (only active and cancelled are seen in code), compute_slots' concurrent_capacity, and whether every published site carries the visit counter (a site that never counted is not called barely seen)"]
decisions: ["A read that fails or reaches its row limit is None and named in signals.unread, never 0; every diagnosis rule skips a None signal", "Rule order: bookings_down, empty_week, something_new, visits_without_leads, traffic_down, gone_quiet, barely_seen, steady; the calendar comes first because an empty chair this week cannot be sold later", "Reads are bounded: site_events 5,000 rows over 35 days (not the 50,000-row report), contacts 500, bookings 1,000, posts 200, runs 12", "marketing_engine gains default-preserving parameters (check_caption/check_flyer own_hosts, _day tz) and fill_slots factored out of pick_plays; the platform's tests pass unchanged", "site_analytics.business_rows is business_traffic's read without the access check; contacts that cannot be read are None there, and the public report still shows them as 0 leads as before", "A business caption may name its own host and no other address; a dollar amount must be a stated price, and in a post about one offering, that offering's", "Verified facts leave out hidden prices, inactive or archived offerings, brand colours and web addresses (their digits would pass the number rule)", "The profile's clock and shape reuse business_marketing.business_tz and has_chair_calendar (imported, not edited); an unreadable one raises ProfileUnavailable rather than guessing UTC or week", "Audience: the desk's, then voice_profile.audience, then a default per vertical; the flyer footer is the business's name and host"]
related: [2026-10-07-marketing-desk-api.md, 2026-10-07-marketing-suite-storage.md, 2026-10-07-marketing-plan-gates.md, 2026-10-02-marketing-desk.md]
---
B7 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md, without its endpoint.
marketing_signals.py reads one business's numbers (visits, new contacts,
bookings ahead against the 4-week average, open chairs for a chair business
with a live calendar, new offerings, site news, the last post, what past
plans were about), bounded and None-not-0. marketing_profile.py says who the
marketing speaks for and to (audience, voice, clock, host, landing page,
shape, the caption writer's instructions where "we" is the business, the
flyer footer). business_marketing_engine.py is the pure half: diagnose, six
plays that never name a person, pick_plays on the platform's own ranking and
slot filler, verified_facts and the caption and flyer checks. No endpoint,
job, Chief action, model call or migration. Tests:
__tests__/test_business_marketing_signals.py (no live calls). The read is
described in docs/MARKETING_DESK.md, "How Chief reads a business".
