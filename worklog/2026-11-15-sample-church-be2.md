---
title: The sample church gets its records (sample church, BE-2, the seed)
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14, approved the sample church signup: "top tier, no cut corners". BE-2 is the seed: Grace Street Fellowship''s people, Sundays, giving, groups, calendar, sermons, member app, care, office and website, so every church room has something in it.'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "BE-3 (#1855) merged while this was in review and guards every send, spend and sweep. The seed is quiet on its own too (every send switch off, every sweep's stamp set, the shepherding sweep's Monday notes marked sent, follow-ups past the late ladder), so the two layers overlap on purpose. The seeded rows the sweeps would otherwise reach: church_shepherd_signals, church_follow_up, church_first_visit, group_email / group_post_later / group_study, news_alerts / news_reach, sunday_serving_alerts, the task sweeps, lead_response / notification_engine, church_checkin's hourly occasion."
  - "Photos: twelve Unsplash picks are wired (sample_church/site_config.json) but no file is in the repo. The parent session gets Kevin's OK, adds static/sample_church/<name>.jpg for each, and a credits entry. The site already credits whatever is on disk in its footer and leaves out any photo that isn't."
  - "Not proved on the real database: no production writes were allowed. The schema snapshot test checks every seeded column and required value against production's PostgREST description (read-only), and the CHECK constraints were read from the migrations; the first run on a tester's sample is the proof. Print lines: [sample] seeding / seeded / failed."
  - "Giving is not pinned to the mock's $18,420: each gift depends only on its own date (so a refresh never rewrites gifts, see decisions). It averages about $21,000 a month by the four funds in the mock's proportions; on 11-14 this month reads about $13,200 and last month about $21,000. The digest gives Chief the true numbers."
  - "The mock's 238 on the roll in 52 families is bigger than the approved plan's ~120 people in ~40 families; the seed follows the plan (125 people, 43 families)."
  - "The Home greeting: BE-1 copies the home's practitioner_name into the sample (so it greets the visitor); the mock says Pastor Daniels. Left as BE-1 set it; the sample's pastor is Pastor Jordan Daniels everywhere else."
  - "Rooms that reads still hide from a non-owner whatever is seeded: the new church Home is owner-only (FE churchHomeRollout); /reports/funds, /givers and /giver-history 402 on the sample (billing_limits vertical_reports, no plan); FUNDS and CHURCH_MAP are unset (owner) in production."
  - "Report history before the sample's created_at shows a dash (church_reports._members_on reads businesses.created_at). Not backdated here: BE-3's 60-day idle cleanup may read created_at."
  - "Found, not changed: church_monthly_report.py:505 selects and orders by group_members.id, a column that table doesn't have, so a church with Sunday teams gets that report block as unread."
decisions:
  - "sample_church_data.build(today, tz, business_id, slug) is pure and deterministic (random.Random seeded with SEED and strings, ids uuid5 of the sample and what). Every date is computed from today on the church's clock; last Sunday is last Sunday."
  - "The story is computed the way the app computes it and pinned for six different todays: last Sunday 186 (152 in the room, 34 online, 12 more than the week before), the mock's eight Sundays, 2 first-time, 8 first visits then 4 came back then 2 joined, exactly Denise Carter, Luis Moreno, Angela Brooks and Samuel Okafor missing the last three Sundays (no group drift adds anyone), next Sunday 15 of 18 places (two kids rooms, slides), Priya Shah and Kofi Mensah not reached, 3 new prayer requests (oldest 2 days), 5 unread messages, no task due all week, last Sunday's offering recorded: 4 things need you."
  - "One Sunday Worship occasion per Sunday (11:00, 'Sanctuary and online') with headcount areas '9:00 service', '11:00 service', 'Online': the app counts per occasion, so two occasions would have halved last Sunday."
  - "Re-seed in place when the version changes (sample_church.SEED_VERSION, now 1), the seed is over 6 days old, or the church's week or month turned (its 'last Sunday' or 'this month' would read empty). ensure() asks sample_church.seed_due first, which reads nothing."
  - "The claim is a conditional PATCH on settings->sample_church->>status (and ->>run); Postgres re-checks the WHERE under a racing UPDATE, so two loads on any replicas seed once. A claim older than 10 minutes is taken over; a failure retries after 2 minutes, doubling to 30. The seeder checks its claim before each table. SAMPLE_CHURCH_SEED: on (background thread, the default), sync, off (the tests' default in conftest)."
  - "Gifts are never rewritten. Deleting an invoice writes the tamper-evident audit_log (and the GL queue); a weekly wipe would write about 2,000 audit rows per sample per week. Contacts, giving services, giving counts and gifts are kept and diffed by id (gifts before counts before people, every delete still scoped by business_id=<sample>); everything else is rewritten. A gift's id is its own content and it depends only on its date."
  - "The GL drain marks a sample's queue rows done without posting (gl_engine.process_queue): a made-up church keeps no books, so no chart of accounts or journal entries for it. growth_events stays empty (contacts' last_interaction is null). Every trigger the seed touches writes only rows keyed by the sample's business_id (attendance, kids, groups and serve guards only reject bad rows; gift and contact triggers as above)."
  - "Move-in: church_move_in.switched_on answers False for a sample, so its Home shows an established church, not 'Your move starts here', and no fake Stripe account id is ever needed. settings.checklist_dismissed is true."
  - "Seeded to stop a GET from writing: church_role_settings.seeded_at (the leaders library), a business_sites row (the member portal), Sunday occasions four weeks ahead (check-in), giving counts for every Sunday in the year with no online collection (the counts screen)."
  - "Fake contact data only: emails @example.org, phones +1<area>555-01NN over eight area codes, made-up streets in Riverton 00000. Names from many backgrounds, handed to roles at random."
  - "The website is the site kit's bulletin layout from sample_church/site_config.json, slug sample-<10 hex> kept across re-seeds, noindex,nofollow, a 'made-up sample church' note on top. Photos load from /assets/sample-church/<name>.jpg (a new pattern-checked route in public_site) only when the file is on disk."
  - "settings.sample_church carries the digest (about 2,700 characters) for the sample's Chief (BE-4). Every marker the seed writes keeps the keys it doesn't own (BE-3's last_seen_at, which the 60-day cleanup measures idle from), and BE-3's last-visit stamp (sample_church.touch) now writes only while the marker still reads ready, so it can never undo a re-seed's claim."
related: [2026-11-15-sample-church-be1.md, 2026-11-14-sample-church-plumbing.md]
---
BE-2 fills the sample church. `sample_church_data.py` says what Grace Street
Fellowship holds; `sample_church_seed.py` writes it (`provision` is
`sample_church.seed_hook`, `due` is the new `sample_church.seed_due`). About
4,900 rows: 125 people in 43 families with 45 children and pickups, 16 Sundays
of attendance and 8 of kids check-ins, a year of gifts (about 2,000 from 55
givers) with Sunday counts, a building campaign with 18 pledges, 9 groups and 4
serving teams with a roster, the calendar, 16 sermons in 3 series, posts and a
devotional, 8 follow-ups, care and benevolence, shepherding, a deacons board,
the office's tasks and Chief's notes, and the website.

Overlaps: read both repos' `worklog/` first. BE-3 (`2026-11-15-sample-church-be3.md`, #1855) merged mid-review; rebased onto it. BE-1 (`2026-11-15-sample-church-be1.md`)
named this PR's job; FE-1 (`2026-11-14-sample-church-plumbing.md`) reads the
sample row and refuses every write from the app. In `sample_church.py`
this PR wires the seed (SEED_VERSION, `seed_due`, `_seed`'s gate, the hook at
the foot) and makes BE-3's `touch()` conditional on a ready marker; two BE-1
test lines change with the re-seed rule.

Room → tables (sample_church_data.ROOM_TABLES; the empty-room test fails on any
room left empty): Home (module_entries, attendance, attendance_headcounts,
invoices, ministry_care_requests, chief_notifications, worship_services,
church_shepherds, contacts); People (contacts, households, household_adults,
children, church_leader_roles, church_register_entries, group_members); Families
(+ household_pickups, child_care_notes); Kids check-in (church_checkin_settings,
checkin_stations, child_checkins); Giving (invoices, giving_services,
giving_counts, church_campaigns, church_pledges); Reports; Groups (groups,
group_members, group_meetings, group_meeting_attendance); Services & Events
(custom_modules, module_entries); Sunday planning (worship_services,
worship_songs, serve_teams, serve_positions, serve_assignments, serve_trained);
Sermons (sermon_series, sermons); Member app (church_posts, devotionals);
Follow-ups (church_follow_ups, church_follow_up_notes, events); Care
(ministry_care_requests, ministry_care_notes, church_help_*); Shepherding
(church_shepherds, church_shepherd_settings, _touches, _signals, church_role_defs,
church_leader_roles); Office (tasks, chief_notifications, church_board*); Website
(business_sites). Empty by design: member chat, church email, texting, recurring
gifts (Stripe), funds and the bank (Plaid), office logins, Live.

Photos (Unsplash License, free; credit given in the site's footer). File name,
slot, photographer, Unsplash id, page:
- hero.jpg: worship gathering. Stephanie Hernandez (@whitecanvascreative), h8hAGzjyFlc, https://unsplash.com/photos/h8hAGzjyFlc (2022; one or two masks at the back). Second choice H-Z3IcVNf9w.
- welcome.jpg: greeters at the door. Kristina Paparo (@krispaparo), IIY5YxY8WKY, https://unsplash.com/photos/IIY5YxY8WKY (only "MAIN ENTRANCE" on the glass; the caption names a real church, the picture doesn't). Second choice b_zi7R-qIdQ (Erika Giraud).
- kids.jpg: kids at a craft table. Rewired Digital (@rewired41), kPkRpy6pIIg, https://unsplash.com/photos/kPkRpy6pIIg. Second choice r-_71cqvTUo (AMONWAT DUMKRUT).
- small-group.jpg: small group at a patio table. Small Group Network (@smallgroupnetwork), hRScHZGXkTA, https://unsplash.com/photos/hRScHZGXkTA.
- prayer.jpg: women praying together. Rosie Sun (@rosiesun; the photo page says Rosie Fraser), rTwhmFSoXC8, https://unsplash.com/photos/rTwhmFSoXC8.
- pantry.jpg: food pantry volunteers. Joel Muniz (@jmuniz), 3k3l2brxmwQ, https://unsplash.com/photos/3k3l2brxmwQ.
- youth.jpg: young people laughing outdoors. Crosby Hinze (@crosbyhinze), EU-Oc9VQHRg, https://unsplash.com/photos/EU-Oc9VQHRg (they read as young adults; the teen alternative hOF1bWoet_Q by Tim Mossholder is a mostly white group).
- worship-team.jpg: a small band. AMONWAT DUMKRUT (@amonwatdumkrut), F1Pm7V8WyZA, https://unsplash.com/photos/F1Pm7V8WyZA.
- fellowship.jpg: coffee after church. Vitaly Gariev (@silverkblack), abO-HcdXyiA, https://unsplash.com/photos/abO-HcdXyiA.
- family.jpg: four generations on a porch. Rajiv Perera (@rajivperera), NjtUbWjri_Y, https://unsplash.com/photos/NjtUbWjri_Y.
- seniors.jpg: two older women arm in arm. Leiada Krözjhen (@leiadakrozjhen), LTgaxUAGNUk, https://unsplash.com/photos/LTgaxUAGNUk.
- outreach.jpg: a park clean-up. Vitaly Gariev (@silverkblack), U20gjfPjtuI, https://unsplash.com/photos/U20gjfPjtuI.
