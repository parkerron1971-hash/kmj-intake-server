# Desk: church-office

## 1. What it owns

The church staff's side of the app: what a pastor and the office logins see
when they sign in. Church Home (the briefing, the week, My week, Move-in until
the church is moved in), the members roll and families, People & care
(Prayer & care, shepherding, follow-ups, guests and the visitor path, "I'm new
here" cards), Serve and volunteers (who serves when, Sunday planning, event
volunteers, sign-up links), the leaders map, roles, duties, job descriptions,
assignments and handovers, the leaders' dates and meetings, office logins
(invites, the church-branded office door, who sees what), classes and
discipleship (Course Studio, live class nights, homework), kids check-in and
the check-in station, spaces, the covenant gate, and the sample church a new
church explores before it signs up.

## 2. Where the code is

Backend (`kmj-intake-server`), most routers under `/church`:
- Logins and access: `business_users_router.py` (`/team`: invite, accept,
  `accept-mine`, `my-role`; `role_of` / `require_role`, ranks viewer < member <
  manager < admin < owner), `business_access.py` (`business_access(min_role)`
  dependency), `office_door.py`, `church_areas.py` (who sees what),
  `church_keys.py`, `church_duties.py`, `church_roles.py`, `church_job_defs.py`,
  `church_job_descriptions.py`, `church_sheet.py`, `church_structure.py`,
  `church_over.py` (who is over whom), `church_assignments.py`,
  `church_handovers.py`, `church_office_tasks.py`, `church_covenant.py`.
- The leaders map: `church_map.py`, `church_map_router.py` (`/church/map`),
  `church_map_asks.py`, `church_map_batch.py`, `church_leader_tasks.py`,
  `church_leaders_note.py`.
- Home and the week: `church_router.py`, `church_morning.py`,
  `church_weekly_briefing.py`, `church_week.py`, `church_my_week.py`,
  `church_team_week.py`, `church_monthly_report.py`, `church_tells*.py`,
  `church_startup.py`, `church_move_in.py` (+ `/platform/move-in`),
  `church_move_setup.py`, `church_move_ready.py`.
- People: `church_roll.py`, `church_roll_edit.py` (`/church/roll`),
  `church_families.py`, `church_register.py`, `church_shepherding.py`,
  `church_shepherd_signals.py`, `church_follow_up.py`, `church_guests.py`,
  `church_first_visit.py`, `guest_path.py`, `guest_path_weeks.py`,
  `guest_card.py`, `guest_brief.py`, `guest_calls.py`, `new_here.py`,
  `private_care.py`, `care_handoff.py`, `church_help.py`, `church_news.py`,
  `news_approvers.py`.
- Serve: `sunday_planning.py`, `sunday_order.py` (`/planning`),
  `sunday_serving.py`, `sunday_serving_alerts.py`, `sunday_leading.py`,
  `serve_dates.py`, `serve_links.py` (`/serve-link`), `church_serving.py`,
  `event_volunteers.py` (`/church/event-volunteers`), `event_signup_links.py`,
  `church_event_signups.py`, `church_schedule*.py`, `church_board.py`
  (meetings and minutes), `church_spaces.py`.
- Classes: `academy_*.py` (join, calendar, work, live router, slides,
  reminders, recordings, site, class nights), `church_plan_course.py`. Course
  Studio writes `academy_*` tables from the browser under RLS.
- Kids: `kids_router.py`, `kids_checkin.py`, `kids_station.py` (`/kids`).
- Sample church: `sample_church.py`, `sample_church_data.py`,
  `sample_church_seed.py`, `sample_church_guard.py` (middleware, 409 on writes),
  `sample_chief.py`, `sample_church/`.
- Specs (read before building): `docs/CHURCH_*.md`, `docs/EVENT_VOLUNTEERS.md`,
  `EVENT_SIGNUP_LINKS.md`, `ACADEMY_LIVE.md`, `MINISTRY_READINESS.md`.
- Main tables: `business_users`, `church_role_defs`, `church_leader_roles`,
  `church_departments`, `church_area_keys`, `church_duty_holders`, `tasks`,
  `church_follow_ups`, `ministry_care_requests`, `serve_*`, `worship_services`,
  `church_away_asks`, `church_board_*`, `groups`, `group_members`,
  `households`, `children`, `child_checkins`, `academy_*`.

Frontend (`solutionist-studio`):
- `src/core/components/church/`: `home/`, `briefing/`, `myweek/`, `movein/`,
  `roll/`, `team/`, `areas/`, `leaders/`, `assign/`, `schedule/`, `serving/`,
  `events/`, `guests/`, `followup/`, `shepherding/`, `register/`, `board/`,
  `spaces/`, `steps/`, `findway/`, `KidsCheckinPanel.tsx`, `StationApp.tsx`,
  `GroupsOffice.tsx`, `ChurchRoomOverview.tsx`; rollout flags in
  `*Rollout.ts` beside them.
- `src/core/components/care/`, `PrivateCarePanel.tsx`, `TeamPanel.tsx`,
  `CourseStudio.tsx`, `course/`, `sample/`.
- API helpers: `src/core/lib/church*.ts`, `officeDoor.ts`, `teamLogins.ts`,
  `sampleChurch.ts`.

## 3. Rules that must not break

- Every write route: auth plus a role check (`business_access(...)` or
  `require_role`), server writes with the service role. The menu filter
  (`CHURCH_AREAS`) only HIDES; each router must enforce its own wall.
- Admins and managers never hand work to a pastor or elder (`church_over`):
  seniors are under the owner only. Handovers are the allowed path.
- Roles come from the church's own data and switches, never from title words
  (`test_church_no_title_words.py`).
- Check-ins and kids' messages never go to children
  (`test_church_no_check_ins_to_children.py`); kids medical notes are a
  guarded tick.
- Prayer & care is private (lock: `CHURCH_CARE_LOCK`; heads-up and due time:
  `CARE_HEADS_UP`). Help requests: the pastor decides, the treasurer pays.
- Office job presets show only at churches that use them
  (`church_job_defs.uses_presets`).
- "Member" is never set automatically on the roll; nameless numbers stay in
  their own list until they have a profile.
- The sample church refuses writes (409 `sample_church`) and never sends;
  `MADE_UP_RECIPIENT_GUARD` blocks texts and mail to made-up addresses for
  every business.
- Rollout switches (`CHURCH_ROLL`, `CHURCH_AREAS`, `CHURCH_DUTIES`,
  `CHURCH_KEYS`, `SUNDAY_PLANNING`, `CHURCH_SCHEDULE`, `CHURCH_TEAM_ROLLUP`,
  `CHURCH_MONTHLY_REPORT`, `CHURCH_REGISTER`, `CHURCH_EVENT_VOLUNTEERS`,
  `EVENT_SIGNUP_LINKS`, `GUEST_PATH`, `CHURCH_SAMPLE`) are set on BOTH Railway
  services (`kmj-intake-server` and `kmj-intake-worker`), and switch on on a
  Thursday unless the owner says otherwise.
- Design changes: mock first and the owner's go-ahead. Mobile in the same
  pass, `useTerm` for nouns, design tokens, and a `whatsNew.ts` entry for
  anything a pastor can see.
- Never commit real figures or real people's details from the owner's church.

## 4. Traps already hit

- An invite token lived only in the browser that opened it; invited logins
  landed in new-church setup. Fixed by `POST /team/accept-mine`.
- `academy_courses.self_join=false` only closed the form; the class stayed
  public. `academy_courses.private` exists for that.
- Batched reads hit PostgREST's 1000-row cap silently; page any read that can
  grow, and order it.
- A bulk insert with mixed keys loses the whole chunk (PGRST102); FakeSB hid it.
- A user-JWT write to a server-owned table returns None, not an error; write
  with the service role.
- `"Put it on Sunday's screen"` 403'd for office logins (plan-part check); look
  for owner-only gates in older routers when a login reports "not allowed".
- The church-overviews harness caches My week's yes for the page's life: test
  "switch off" with a fresh business id.
- Something must call `useBusinessRole` for the role-based view to be right.
- Worklog front matter is YAML: `asked:` must be one quoted string.
- `test_sunday_planning_holds`' byte check is skipped in CI; run it locally.
- iPad to Brother label printing for kids check-in is untested on hardware.

## 5. How to check work

- Backend: `pytest -q __tests__/test_church_*.py __tests__/test_sunday_*.py
  __tests__/test_serve_links.py __tests__/test_event_volunteers*.py
  __tests__/test_academy_*.py __tests__/test_kids_*.py
  __tests__/test_care_*.py __tests__/test_guest_*.py
  __tests__/test_sample_church*.py __tests__/test_office_door.py`.
- Migration checks on PGlite: `PGLITE_MODULE=... node
  __tests__/church_schedule_db.mjs` (and the other `__tests__/church_*_db.mjs`,
  `serve_*_db.mjs`, `academy_private_db.mjs`).
- Frontend: `npx tsc -p tsconfig.app.json --noEmit` (no new errors),
  `npx vite build`, the matching `node scripts/check-church-*.mjs`
  (roll, logins, serving, leaders-dates, home, team…), `check-event-volunteers.mjs`,
  `check-sample-church.mjs`, `check-first-run.mjs`.
- Preview: `npx vite --config tests/church-overviews.vite.config.ts --port 5191`,
  then `/tests/church-overviews-preview.html?room=operate&frame=desk|phone
  &theme=sanctuary_dark&role=member`; per-room harnesses in `tests/*-preview.html`.
- A write path is proven against the real database, not only the fakes.

## 6. Edges

- chief: `chief_church_*.py` and `chief_office.py` are Chief's action modules;
  the chief desk owns the action plumbing, this desk owns the domain modules
  they call. Change both sides together and tell the other worker.
- member-app: the `/my` pages for Serve, classes, kids, leading and dates read
  this desk's data (`member_portal_serving.py`, `member_portal_classes.py`,
  `member_portal_dates.py`, `member_portal_lead.py`).
- money: `church_money_gate.py` (the money wall), giving, `church_checks.py`,
  `church_pledges.py`, `church_reports.py`, payroll. Office logins reaching
  money go through that gate.
- messaging: texts and mail the office sends (leaders note texts, threads,
  church mail, push). This desk decides who; messaging delivers.
- live-media: live class nights' video and recordings, ChurchSavvy screens;
  `academy_live_router.py` is shared.
- system: migrations, RLS on new tables, `account_lifecycle` coverage.
