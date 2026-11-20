# The leaders schedule: who is away, who says yes, and how many at once

Kevin, 2026-11-18. The ask, in his words:

- "I want to be able to build Leaders schedule. this is for when leaders are planning time off
  and have certain obiligations so that we as a church can plan around meeting ... making sure
  that everyone is not gone at the same time on our services. allowing only so many people off at
  the same time. ... there should volunteers one and one for leadership ... divided amongs the
  department to manage there department as well. so since [name] is over that she should be able
  to see the full list of people on for the week so she can manage volunteer hours".
- Shown the five calls the plan rests on (section 7): "Yes build to all five".

**What it is.** A leader asks to be away: planned time off, another commitment, or "I can't make
it". The ask goes to the person over them on the church's own leaders map, who says yes or not
this one. A yes becomes an away date in `serve_away`, the one table Who serves when already
reads, so the scheduler stops asking that person without learning anything new. The reason they
gave stays private. Step 2 adds the limit: only so many of a group, or of a department, away on
one service date; days nobody takes off; two people who can't be away together; and the same
path for volunteers when their date is full or they already said yes to serve it.

**Where it stands (2026-11-20).** Eleven PRs. Step 1's tables and step 2's are both in
production. The limit on how many can be away at once is built for leaders and the office (S2-2
and S2-3, below), and so are people who can't be away together (S2-4), the volunteers' rules
(S2-5) and things that repeat (S1-7). Only the optional S1-8 (the office front page's count) is
not built.

**Step 1's migration is applied.** `supabase/APPLY-2026-11-19-church-schedule.sql` was run by the
owner on 2026-11-18 and checked by the lead session with the file's own Check block: the four
tables have RLS on, no policies and no browser or anon read; `serve_away_ask_id_fkey` and
`serve_away_kind` are there and not validated; `church_away_settle` runs for `service_role`
only; no asks, and no `serve_away` row with an `ask_id` or a `kind`. `CHURCH_SCHEDULE` is unset,
which means `owner`: **the schedule is open at the platform owner's own church**, and to his
own login, and closed everywhere else. So what each PR below adds is live there as soon as it
deploys. Wherever this doc says "before the migration" or "until its tables are there", it
describes what the code does on a database without them (a new environment, a test); in
production that time has passed.

- **S1-1 (#1929, merged)** holds step 1's tables:
  `supabase/APPLY-2026-11-19-church-schedule.sql` (**applied 2026-11-18**), its real-Postgres
  check (`__tests__/church_schedule_db.mjs`), the export decision for the four new tables, and
  this doc.
- **S1-2 and S1-3 (#1930, one PR)** hold `church_schedule.py`: the switch, who is on the schedule,
  asking, answering, withdrawing, the calendar and the notice days, behind the office routes of
  section 4.1 (all but the commitments routes). Owner-only by default. Every route answered
  404 until the migration was applied; now they answer at the platform owner's church.
- **S1-4** holds `church_schedule_tell.py`: who is told of an ask, an answer and a take-back,
  and the hourly sweep on the worker (what a write couldn't tell, the one nudge, an ask sent on
  when who is over someone changes, a private reason and an answer's note cleared 90 days after
  the last day). Owner-only by default. It was silent until the migration was applied (the
  sweep read nothing before it); now it tells, and sweeps, at the platform owner's church. No
  migration of its own.
- **S1-5 (#1936)** holds `member_portal_dates.py`: Dates on the member app's Lead tab, where one of the
  church's people asks for time off, says "I can't make it", takes one back, says yes or not
  this one to what went to them, and sees who else is away. `church_schedule.section` gives the
  Lead tab its Dates entry, and `member_portal._leads` gives the tab to someone on the schedule
  who leads nothing else. A person's notice now opens this page. Owner-only by default. It
  wasn't there at all until the migration was applied; now it is there for the people on the
  schedule at the platform owner's church. No migration of its own.
- **S1-6 (#1938)** ties it to Who serves when, the volunteer schedule. `church_schedule.holds` is the
  scheduler's hook: someone whose ask still waits reads as away for those days on
  `sunday_planning._Board`, in the board's own words and nothing more. The Away form on the
  Serve page asks instead of saving for someone on the leaders schedule (`takes`), and says so
  with a way to their Dates page; a volunteer's Away is byte for byte what it was. Taking off
  an away date that came from an ask takes the ask back (`withdraw_fact`). A yes opens the
  places that person had already agreed to serve inside those days
  (`sunday_serving.open_places`). Owner-only by default, and the migration was already
  applied when it merged, so all of it is live at the platform owner's church from its first
  deploy: there the board makes one more read, and someone on the leaders schedule who presses
  Save under Away is asked for. With the switch closed for a church (every other church), the
  scheduler and the Serve page make no read they didn't make before. No migration of its own.
- **S2-1 (#1941)** holds step 2's tables and nothing else:
  `supabase/APPLY-2026-11-20-church-schedule-limits.sql` (**applied 2026-11-18**, run by the
  owner and checked by the lead session with the file's own Check block), its real-Postgres
  check (`__tests__/church_schedule_limits_db.mjs`) and the export decision for the three new
  tables. It does not touch `church_away_settle` or `serve_away`, so running it changed nothing
  the code above does (section 2.2 says what was checked).
- **S2-2 and S2-3 (#1943, one PR)** hold `church_schedule_limits.py` and the step 2 parts of
  `church_schedule.py`, `church_schedule_tell.py` and `member_portal_dates.py`: how many of the
  leaders, of the office and of a department may be away on one service day; which days count;
  the protected days; and what happens to an ask that runs into either. Such an ask is **never
  refused**: it is flagged and goes up to whoever oversees the office (from a shepherd or a
  senior, to the owner alone), and a yes to it is saved as an exception. A yes looks at the days
  again first. On Dates a leader sees, before anything is sent, that a day is full or protected,
  the nearest open service days, and who can make an exception. Owner-only by default, and both
  migrations were applied when it merged, so it is live at the platform owner's church from its
  first deploy. Step 2 has its own check for its tables (`church_schedule_limits.ready()`): on a
  database with step 1's file alone, all of this is off and nothing of step 2 is read. No
  migration of its own.
- **S2-4 (#1948)** holds pairs: two people who can't be away together, set and read by the
  owner and whoever oversees the office alone (`GET` / `POST` / `DELETE
  /church/schedule/pairs`), and the `pair` flag. An ask whose days overlap, on any day, an away
  date of the other of a pair, or an ask of theirs still waiting that was made first, is never
  refused: it is flagged `pair` and goes up as an ask past the number does, the yes looks again,
  and the exception is saved with `pair` in it. The one asking reads "This overlaps with someone
  you can't be away with at the same time" and never who or which days; the flag is on the
  calendar only for those who read the reason; whoever it went up to reads who it overlaps
  with only when they may give the exception. A pair with someone since taken off the schedule
  is kept and does nothing. Owner-only by default; both migrations were applied before it
  merged, so it is live at the platform owner's church from its first deploy. No migration of
  its own; on a database with step 1's file alone nothing of it is read.
- **S2-5 (#1951)** holds the volunteers' rules (`church_schedule_volunteers.py`; the owner's call 3:
  "Volunteers need no yes to be away, unless the date is full or they already agreed to serve
  it; then it goes to their team leader"). A volunteer's Away on the Serve page on a free date is
  saved at once, byte for byte as before. On a day full for one of their departments (counting
  only away dates that were agreed, as S2-3 counts), or a day they said yes to serve, it is an
  ask (`grp = volunteers`, `team_group_id`) to the leader of the Sunday team concerned, and the
  page says so by name and why. That leader answers on Dates (the entry is theirs while it waits,
  on the leaders schedule or not) with a plain yes, over the department's number too; the yes
  writes the away date and opens the places they had agreed to. A volunteer's Away never fails
  because of this: anything that goes wrong saves it at once. Owner-only by default; both
  migrations were applied before it merged, so it is live at the platform owner's church from its
  first deploy, and **real volunteers there meet it on deploy**. No migration of its own; on a
  database with step 1's file alone a volunteer's Away is exactly what it was.
- **S1-7 (#1990)** holds things that repeat (`church_schedule_repeats.py`): a leader says once
  "I work every other Saturday" (every week, every other week counted from its first day, or the
  first to fourth or the last such day of each month; from when, and until when if it ends), ten
  in force a person. No yes, never blocked, never counted toward a limit or a pair. It is on the
  leaders calendar (`standing`: each day, the name, and what it is only for those who read an
  ask's reason), and `church_schedule.holds` holds the person from the scheduler on those days
  only. The one an ask of theirs would go to is told once, never what it is. Office routes `GET` /
  `POST` / `DELETE /church/schedule/commitments`; on Dates a "Things that repeat" part after My
  dates. The table was in step 1's file (applied 2026-11-18), so it is live at the platform
  owner's church on deploy. No migration of its own.
- **Step 4, The week (#1979)** holds `church_week.py`: the office's read-only page of every
  department's volunteers for one week, with hours (Volunteers → The week; the pastor approved the
  mock on 2026-11-19, "go"). `GET /church/week` and `GET /church/week/status`, for the owner, an
  Admin and a Manager who keeps either door of Who serves when; hours and "Can't serve with kids
  yet" by church_serving's own rule. Nothing on it writes. `CHURCH_WEEK`, owner when unset, so it
  is live at the platform owner's church on deploy; the office page itself is the frontend's next
  PR. No migration. Section 8 is its contract.

The office app has no screen yet: a login's notice still points at the office app, where the
ask isn't shown. A login whose person is on the schedule answers in the member app, as that
person.

In sections 3 to 6, what is marked **built** describes code that exists; only the optional S1-8
is still a plan. Section 7 is what was decided; 7.4 is
what the build of S1-2 and S1-3 decided, 7.5 what the build of S1-4 decided, 7.6 what the build
of S1-5 decided, 7.7 what the build of S1-6 decided, 7.8 what the writing of S2-1 decided,
7.9 what the build of S2-2 and S2-3 decided, 7.10 what the build of S2-4 decided, 7.11 what
the build of S2-5 decided, and 7.12 what the build of S1-7 decided, each with where it differs
from the plan above it.

**Three tables share a word and nothing else.** `church_away_asks` (here: a leader asks to be
away) is unrelated to `church_map_asks` (an office login's "Is this right?" about the work
Chief has them doing, `docs/CHURCH_LEADERS_STEP2.md`) and to `member_asks` (`member_asks.py`:
a member asks the church for a room, help, a visit). None reads or writes another.

**Rule code reads the church's data, never a title.** Who is over whom comes from
`church_over.above`; who is on the schedule from the roles, groups, departments and seats the
church set up, plus its own add and remove list. No title word or role key decides anything
(`test_church_no_title_words.py`'s rule). Tests use the four fixture churches in
`__tests__/church_three.py`.

**Line references.** Every `path:line` below was read at `a73eb5c6` (2026-11-18), and each
names its function, which is the durable part. Main has moved twice since (#1926, #1927). The
references marked `f859d05a` were corrected in S1-1; for the rest, these are the shifts from
`a73eb5c6` to `f859d05a`:

| File | Shift |
|---|---|
| `kmj_intake_automation.py` | +5 after line 462, +9 after 996, +22 after 1888 |
| `church_over.py` | +1 after line 272 |
| `church_duties.py` | +13 after line 463, +14 after 845, +15 after 984 |
| `account_lifecycle.py` | +4 after line 310, +5 after 744, +10 after 947 |
| `chief_of_staff.py` | +1 after line 263, +2 after 423, +6 after 6704, +7 after 12446, +16 after 15907 |
| `action_registry.py` | +11 after line 602 |
| `chief_areas.py` | +4 after line 110 |
| `.env.example` | +9 after line 44 |

`__tests__/test_sample_church_no_sends.py` gained 3 lines after line 165, below the `TICKS`
neighbours cited. No other file cited here changed between the two.

---

## 1. Findings that shape the design

### 1.1 `serve_away` today

- **Shape** (`supabase/APPLY-2026-10-23-sunday-planning.sql:86-96`): `id, business_id, contact_id, starts_on, ends_on, note text default '' (<=100), created_at`; check `ends_on >= starts_on and ends_on - starts_on <= 366`; index `serve_away_by_person (business_id, contact_id, ends_on)`.
- **Trigger** `serve_same_business` (rewritten in `APPLY-2026-10-23-serving-member.sql:33-70`) only checks the contact is the church's. It fires before every insert and every update of a row (no column list), so any later update of a `serve_away` row looks its person up again. RLS on, no policies.
- **Writers** (only two):
  - `sunday_serving.add_away(biz, cid, start, end, note="")` `:467-484`. No past dates, 366 days at most, `MAX_AWAY = 20` open rows a person.
  - `sunday_serving.drop_away` `:487-490` deletes by `id + business_id + contact_id`.
  - Both are called only from `member_portal_serving.py:895-904`.
- **The note is never written.** The route passes only `"start", "end"` (`:897`), so `serve_away.note` is `''` everywhere. "Never copy the reason into note" costs nothing.
- **`add_away` never touches `serve_assignments`.** Someone who said yes and then adds away dates keeps their place.
- **Readers** (none selects `kind` or `ask_id`, so two new nullable columns break nothing):

| Reader | Where | What it does |
|---|---|---|
| `sunday_planning._Board.__init__` | `:932-933` | one read per board, `select=contact_id,starts_on,ends_on,note` |
| `_Board.is_away` | `:946-948` | feeds `candidates` `:974-979`, `do_ask` `:1309` (409 "is away that Sunday") and `do_fill` `:1428` |
| `GET /planning/schedule` | `:1018-1026` | returns `away: [{contact_id, name, starts_on, ends_on}]` to every Planning reader |
| `sunday_serving.mine` | `:101-102` | their own chips |
| `sunday_serving.free_sundays` | `:305` | "I can do another Sunday" |
| `church_serving._sunday_spans` | `:456-474` | a yes on an away day earns no hours |

- **Privacy consequence:** an approved leader's away fact already shows by name and dates on `/planning/schedule`. That is allowed. A pending ask must not be merged into `board.away`.
- **Lifecycle:** `serve_away` is in `account_lifecycle.BUSINESS_CHILD_TABLES` `:256` and `_IMPORT_SKIP` (the block at `:851`, f859d05a). The export carries its two new columns; it is not re-imported.

### 1.2 `church_over`: who is over a contact

- `me` / `who` is `{kind: 'login'|'person', id}` (`church_over.py:84-88`, `who()` `:200`, `parse_for` `:208`).
- **`above(ch, who)` `:911-919` / `_above` `:930-975` is the right function for "who says yes".** It returns nearest first; `[]` only at the top.

**(a) A ministry leader (person)** `:949-975`
- `church_leader_tasks.overseer` (`:789-814`) gives the first step of `church_map.chain_for` (`church_map.py:445-524`) where the map is open: the department's overseer, then the item's department leader then overseer, then `answers_to_contact_id`, then `church_roles.chain_above`.
- With the map closed it is `chain_above` alone.
- A group leader with no role uses `clt.group_department` `:817-836`.
- A step can hold **several** people (`:964-974`).
- A step whose person has an office login becomes that login; one who is the owner's identity becomes the owner's login.
- Nobody found: `_top`, the owner's login (`:922-927`).

**(b) An office login** `:931-941`
- A Manager not over the lanes: `church_duties.manager_holders(b, "oversee_lanes")` (`church_duties.py:749`), else the owner.
- An Admin, or the login over the lanes: the owner.
- **A person who has an office login is routed as that login** (`:947-948`), even if they also lead a department.

**(c) Directly under the owner**
- Seniors (`Church.seniors` `:452-465`) go to the owner (`:945-946`).
- The owner's own identity (`Church.top` `:438-450`) gets `[]`.

Other facts:
- `is_over` (`:806-813`) and `under` (`:794-803`) walk down. They are heavier and answer "anyone over them", which is wider than the privacy rule allows. Do not use them to decide who may answer an ask.
- **Guarded people** (`Church.guarded` `:523-527`, `is_guarded` `:816-829`): no office standing is over a shepherd or a senior. This matters for step 2's "goes up to the office overseer".
- **Office overseer:** role keys from `church_duties.overseer_keys` `:477-491` (the map's `office_overseer_roles`, else the Executive Pastor key); the logins are `Church.exec_users` `:280-292`. `Church.over_lanes(uid)` `:275-278` is true for the owner and Admins too, so use `manager_holders(b, OVERSEE)` for "the office overseer" alone.

### 1.3 Seat to contact

- `Church.login_person` `:388-414`: user id to contact id for the owner and **every** active seat.
  - `business_users.contact_id` first, else the one contact the seat's `invited_email` names (several: the one whose first name the seat gave). One batched read (`_by_email` `:340-354`).
  - The owner: `settings.church_owner_contact_id` (`owner_pick` `:370-386`), else the sign-in email.
- `Church.person_login` `:416-419`: contact to office login (Admin and Manager only).
- `Church.owner_person` `:421-427`, `owner_how` `:429-436`.
- `business_users_router.seat_person` `:191-198` does the same match for one seat and **writes** the tie (`_keep_contact` `:177-188`); `chief_areas.who_for` `:564-584` calls it. `docs/CHURCH_ASSIGNMENTS.md:149-153` says not to use it in rule code. Use `Church.login_person`.
- **A seat that matches no contact has no person.** `serve_away.contact_id` is NOT NULL, so that login cannot hold an away fact.

### 1.4 The switch pattern

- `church_over.mode / open_to / church_open / office_open` `:134-166`; the same shape is in `church_map.py:79-111`, `church_leader_tasks.py:105-131` and `serve_dates.py:57-81`.
- `owner` means `member_asks.platform_church(biz)` (`member_asks.py:193-213`): one businesses read plus the owner's email, kept ten minutes per replica.
- Sweeps read the switch on the worker; `.env.example:718-729` (f859d05a) says "set it on BOTH services".
- Owner-mode sweeps scope with `church_assignments._open_churches` `:1271-1287`, which also drops sample churches.
- **"Is the migration there" probe:** `serve_dates.ready()` `:85-110` (cached 600 s yes, 60 s no, `_FORCE` for tests). `conftest.py:169-178` pins `_FORCE = False` so every other suite reads as before the migration. Our scheduler hook needs the same pin, or the default `owner` mode adds `platform_church` reads to every Planning test.

### 1.5 `leaders_room_people` and its cost

- `member_portal_messaging.leaders_room_people` `:177-217`:
  - leaders of active groups;
  - holders of an active role that leads (`can_lead` where the map is open, else `LEADER_JOBS` `:174`, or a role another role reports to);
  - on an open map, each active department's leader and overseer who hold a role;
  - **already the office**: `office_contacts` `:220-244` (Admin and Manager seats as their contact).
- It returns a flat list with no group label. `church_leader_tasks.leaders` `:333-361` subtracts `office_contacts` to get "leaders who aren't office". The owner is in the list only if he holds a leading role.
- **Cost, uncached:** `group_members` (limit 5000), `groups`, `church_leader_roles`, `cr.defs`, `church_map.opened` (5 reads unless inside `church_map.once()` `:277-291`), `business_users`, plus one `contacts` read per untied seat. About 11 calls plus one per untied seat.
- Too heavy to run on every Lead-tab page view. Keep the roster 60 s per replica, as `church_duties.CACHE_SECONDS = 60` (`:538`) does.

### 1.6 Notify patterns

**To a contact**
- `member_push.send(business, kind, title=, body=, url='/my…', contact_ids=[…], ref_id=, tag=)` `:277-293`.
  - Never raises; returns phones reached.
  - 0 when the church hasn't switched that kind on (`church_kinds` `:112`), or `ref_id` was already claimed (`member_push_sends`).
- **Callers never call `church_threads.record` themselves.** `_send` does it (`:325-331`) for `THREAD_KINDS` (`church_threads.py:92-93`, which includes `serving`), with one row per contact and identical keys (`:256-291`).
- Email fallback: `church_leader_tasks.deliver` `:551` with `render_email` `:540`, reply-to `_office_email` `:525`.
- "Email when the phone wasn't reached" is `sunday_serving_alerts.tell` `:196-214` (`if email_ok or not rang`).
- `serving` is not in `QUIET_KINDS` (`member_push.py:103`), so the caller must check `member_push.quiet_hour(biz)` `:156` itself.

**To a seat**
- `push_notifications.send_to_user(uid, title=, body=, nav=, tag=, business_id=)` `:178`.
- Email to `church_assignments._login_email(ch, uid)` `:1169-1180` (`None` means unread: don't claim), rendered with `church_office_tasks.render` `:178`, link `cot._link` `:138`. Worked example: `tell_raised` `:1183-1257`.
- Claim before send, release on failure: `church_handovers._claim/_release` `:546-559`.

**Sweeps**
- Registered at `kmj_intake_automation.py:2039-2053` (f859d05a).
- **Every `add_job` must be listed in `__tests__/test_sample_church_no_sends.py` `TICKS` (`:97-98` are the neighbours).**

### 1.7 The Lead tab

- `member_portal_lead.serve` `:660-731` dispatches on `selected` (tasks, sundays, families, groups, safety, prayer, a follow-up id).
- `_context` `:639-657` sets per-request ContextVars (`SUNDAYS`, `PARTS`, `PAID_BACK`, `TASKS`, `ASSIGN` `:59-76`).
- `_seg` `:826-853` builds the switcher from them.
- The best template is `member_portal_assign.py`:
  - `view` `:144`, `section` `:375-397` (the switcher count; `None` while closed), `serve` `:400-423`;
  - `_act` `:455-479`: `_signed_in`, preview never writes, `cfu.is_church`, switch or 404, `rate_limit.allow_strict("member_action", …)`, the form, the function in a thread, a 303 back with a short code;
  - `_code` `:434-452`: refusals become codes, never words in the URL.
- `_signed_in` is `member_portal_church.py:1135-1151`; the Origin / Sec-Fetch-Site refusal lives under it (`member_portal_assign.py:33-36`).
- Routers are included at `kmj_intake_automation.py:607-610` (f859d05a).
- **Who gets the tab:** `member_portal._leads` `:1197-1219` (a role, a led group, a tasks section, or serve-mode parts). An office login's person with no role or group gets no Lead tab today.

### 1.8 Tests and lints a new church module must pass

- **Fixtures:** `__tests__/church_three.py` `build(monkeypatch, map_on=…, filled=…)`: four churches in one fake PostgREST (`ThreeDB` `:104`, `MAX_ROWS = 1000`), with `db.who[church][handle]` and `db.label`. New tables are added as `d.t["…"] = []` (`test_church_handovers.py:54-57`).
- **Office app fixture:** `test_church_handovers.py:84-107` (`dependency_overrides[sb_clients.authed_request]`, `as_(app, biz, handle)`).
- **Member app fixture:** `test_member_portal_assign.py:67-104` (fake `_shell`, patched `mpc._signed_in`, `page()`, `text()`).
  - It asserts no ids and no office words on screen: `UUID` and `OFFICE_WORDS` regexes `:47-48`.
  - It asserts cross-site POST is refused, `Origin: null` is allowed, and the preview never writes.
- **RPC fake precedent:** `test_church_duties.py:77` (`/rpc/church_duty_set`).
- **Real-Postgres check:** `__tests__/church_assignments_db.mjs` is the shape; every `*_db.mjs` runs in the `test-db` job of `.github/workflows/ci.yml` (PGlite 0.5.8). This feature's is `__tests__/church_schedule_db.mjs` (S1-1).
- **Lints:**
  - `test_church_no_title_words.py` is a pinned list of named readers, not a general scan. The rule still binds: decide from data, never from a title word or role key.
  - `test_business_access_ratchet.py` (`ownership_sweep.py`): an office handler taking a business id must reach a gate that raises. `church_assignments._church_from_body` `:299-307` (`business_access.assert_access`) qualifies.
  - `test_export_import.py:205` (`test_every_business_scoped_table_is_a_decision`) scans `create table … business_id` in the migrations. Every new table must be in `BUSINESS_CHILD_TABLES` or `EXPORT_EXCLUDED` (`account_lifecycle.py:100`, `:196`). Step 1's four are in `EXPORT_EXCLUDED` (S1-1).
  - `test_sample_church_no_sends.py` `TICKS`.
  - `test_brand_voice.py` covers the public site only.

### 1.9 Service days

- No per-church service weekday exists. The weekly service is assumed to be Sunday:
  - `sunday_planning._sunday_on_or_after` `:847`;
  - `POST /planning/sundays` `:1033-1060` (adds `worship_services` rows on Sundays at a typed time, default 10:30);
  - `church_work_checks.py:213, :307` ("last Sunday");
  - `serve_dates.is_sunday` `:135`.
- A dated occasion that isn't Sunday is a `worship_services` row with `kind='event'` (`serve_dates.py:1-33`); only the Volunteers' teams serve it (`sunday_planning.serves` `:902-905`).
- **Two clock helpers:** `sunday_planning._zone` (`:360`) and `church_work_checks.church_zone` (`:71-81`, also `Church.tz` at `church_over.py:305-312`). Both end at `business_marketing.business_tz` (`:232`).

### 1.10 Departments and Sunday teams

- A Sunday team is a `groups` row of `kind='team'` plus a `serve_teams` row; its leaders are `group_members.role='leader'` (`sunday_leading.led_teams` `:26-39`).
- It hangs from a department as a `group` unit (`church_department_units.group_id`, "any kind, serve teams and ministries too", `APPLY-2026-11-04-church-map.sql:~283`), or by name as a `serve_option` label unit.
- Lookup: `Map.department_of(kind, ref)` (`church_map.py:165-173`).
- #1719's fallback for a team with no leader is `church_map.team_head(m, defs, holders, team)` `:426-441`: the department's leader while they hold a role that leads, else its overseer while they hold one that oversees.

---

## 2. Data model

### 2.1 Step 1: `supabase/APPLY-2026-11-19-church-schedule.sql` (S1-1; applied 2026-11-18)

The file is the source; this is the map of it. `serve_away` stays the one table of facts
("this person is away these dates") and everything that reads it today reads it as before.

| Object | What it holds |
|---|---|
| `church_away_asks` | One row an ask: the person, the dates (366 days at most), the `kind` (`time_off`, `commitment`, `cant`), a private `reason` (500 at most), who covers (`cover_contact_id` or a typed `cover_name`, never the asker), the group they were on when they asked (`grp`), the department, who it went to (`to_user_id` or `to_contact_id`, never both), the `state` (`asked`, `yes`, `no`, `withdrawn`), who decided (`decided_by_user_id` or `decided_by_contact_id`, never both), `decided_at`, `decided_note` (300 at most), `withdrawn_at`, the `flags`, and three marks for the notices (`told_at`, `answer_told_at`, `nudged_at`) |
| `church_away_settle(p_business_id, p_ask_id, p_state, p_by_user, p_by_contact, p_note)` | One decision in one transaction (the precedent is `church_duty_set`, `APPLY-2026-11-01-church-duties.sql:51-89`). Answers `{"changed": bool, "ask": row}`, or null when that church has no such ask |
| `serve_away.ask_id`, `serve_away.kind` | The ask a fact came from and that ask's kind. Both null on every row that exists and on every away date added the way it always was |
| `church_away_commitments` | Something that repeats: a label, a weekday (1 Monday to 7 Sunday), `weekly`, `every_other` (counted from `starts_on`, which must fall on that weekday) or `month_nth` (`nth` 1 to 5, 5 meaning the last), from when, until when |
| `church_schedule_people` | The church's own add list (with the group, `leaders` or `office`) and remove list; one row a person |
| `church_schedule_settings` | One row a church: `notice_days` (14 by default, 0 to 90) |

**What `church_away_settle` does**

| Asked for | The ask is | Written | Answers |
|---|---|---|---|
| `yes` | `asked` | state `yes`, `decided_at`, who decided, the note, `answer_told_at` cleared; **one** `serve_away` row: the ask's church, person, dates and kind, `note` `''`, `ask_id` | `changed: true` |
| `no` | `asked` | state `no`, `decided_at`, who decided, the note; no fact | `changed: true` |
| `yes` or `no` | anything else | nothing | `changed: false`, the ask as it stands |
| `withdrawn` | `asked` or `yes` | state `withdrawn`, `withdrawn_at`; its fact, if any, deleted | `changed: true` |
| `withdrawn` | `no` or `withdrawn` | nothing | `changed: false` |
| anything | not this church's, or not there | nothing | null |
| a state that isn't one of the three, or null | | nothing | raises |

The row is locked (`for update`) before it is read, so two answers at once land one after the
other and the second gets `changed: false`. The reason is never copied: the fact's `note` is
always `''`.

**What a state holds** (`church_away_asks_decided`): `asked` has no `decided_at` and no
`withdrawn_at`; `yes` and `no` have a `decided_at` and no `withdrawn_at`; `withdrawn` has a
`withdrawn_at`, and keeps its `decided_at` when it had been a yes.

**Guards**

- `church_away_asks_same_business` (before insert, and before an update that names one of
  `business_id, contact_id, cover_contact_id, to_contact_id, decided_by_contact_id,
  department_id`): the asker, who covers, who it goes to, who answered and the department are
  the ask's own church's; an ask never changes its church or its person. Each is checked only
  when a write names them, so a foreign key setting one of them null checks nothing.
- `serve_away_ask_guard` (before insert, and before an update of `ask_id`, `business_id` or
  `contact_id`): the ask a fact names is the same church's and the same person's.
- `serve_away_one_per_ask` (unique, where `ask_id is not null`): one fact an ask.
- `church_away_asks_one_open` (unique on church, person, start, end, where `state = 'asked'`):
  a double press never makes two asks for the same days. Once answered, the days can be asked
  again.
- `church_schedule_person_same_business`: the person on the list, and the person a commitment
  is, are the church's own, and the row stays with its church.

**Server-only.** All four tables: RLS on, no policies, `anon` and `authenticated` revoked,
`service_role` granted. All four functions: execute revoked from `public`, `anon` and
`authenticated`; `church_away_settle` granted to `service_role`. It is not `security definer`:
it runs as the server's role, which already has every table it touches.

**What goes with what.** A church deleted takes everything. A person deleted takes their asks,
their facts, their commitments and their place on the lists. A login deleted leaves the ask
with nulls in its place (`made_by`, `to_user_id`, `decided_by_user_id`); so does a person who
covered, answered or was asked, and a department. An ask deleted by hand leaves its fact as a
plain away date (`on delete set null`).

**How it goes in.** One transaction, `lock_timeout` 5s, safe to run twice, ends with
`NOTIFY pgrst`. `serve_away`'s foreign key and check go in `NOT VALID`: its two new columns are
null on every existing row, so nothing old is scanned under the lock and every row written
from then on is checked. The file's own Check and Rollback blocks are at its end.

**Changed from the draft in the build spec, and why** (the check rehearses red without each of
the first four):

1. **A null state is refused by name.** The draft tested `p_state not in (…)`, which is null for
   a null state, so the function fell through to an update that set `state` to null and failed
   on the column's NOT NULL with a message nobody would read as "bad state". Now
   `p_state is null or p_state not in (…)`.
2. **`church_away_asks_decided` pins `withdrawn_at` too.** The draft's third arm was
   `or state = 'withdrawn'`, which let a withdrawn row have no `withdrawn_at`, and let an asked
   or answered row carry one. It now says what `church_away_settle` writes for each state.
3. **An ask stays with its person.** The draft re-checked a changed `contact_id` against the
   church; the trigger now refuses the change. Nothing moves an ask to another person, and
   allowing it would let a fact name an ask that is no longer its own person's.
4. **`serve_away_ask_guard` also fires when a fact's `business_id` or `contact_id` is
   updated.** The draft fired on `ask_id` only, so a fact with an ask could be moved to another
   person without the guard looking.
5. **`NOTIFY pgrst, 'reload schema'` after the commit**, as the files since 2026-11-17 do: the
   API has to see a new function before `/rpc/church_away_settle` answers.
6. **The header no longer says "nothing dropped".** The file drops and re-makes its own
   triggers, as every file here does. It now says no table, column or row is dropped.
7. **The Check block also asks about `anon`, `service_role` and the old rows**, and the table
   comment says the table is unrelated to `church_map_asks` and `member_asks`. The Check and
   Rollback blocks were run as written: the rollback leaves `serve_away` and the catalog as they
   were before the file, keeps every away row, and the file applies again after it.

**Checked and kept as drafted** (run on PGlite 0.5.8, which carries PostgreSQL 18.3; production
may be an older Postgres, and none of this is new behaviour)

- `on conflict (ask_id) where ask_id is not null do nothing` does infer the partial unique index
  `serve_away_one_per_ask` (run for real: a yes on an ask that already has a fact lands and
  leaves one fact).
- `old.…` read inside an insert trigger's `tg_op = 'INSERT' or …` test is null, not an error.
- **`on delete set null` on `serve_away.ask_id` is safe with `serve_same_business`.** That
  trigger looks the person up on every update, and a set-null is an update, so the worry was a
  person's delete being refused when their ask happened to go before their fact. It isn't:
  Postgres runs the foreign keys' own deletes first and the set-nulls they queue afterwards, by
  which time the fact is gone by `serve_away`'s own keys. The check deletes a person and a
  church with an approved ask in both orders the foreign keys can fire.
- The trigger column lists: each foreign key that sets a column null updates only that column;
  for `cover_contact_id`, `to_contact_id`, `decided_by_contact_id` and `department_id` the
  trigger fires and finds nothing to check, and for the three login columns it doesn't fire.

**Not solved by the tables** (for the PRs that write the code)

- **A take-back has no column to claim its notice**: `told_at` is "whoever it went to was told
  of the ask" and `answer_told_at` "the asker was told the answer". S1-4 sends it straight after
  the write and never tries again; no mark was added (section 7.5, which also says who is told).
- **A fact taken off the old way leaves its ask at `yes`.** Since S1-6
  `sunday_serving.drop_away` takes the ask back instead (`church_schedule.withdraw_fact`, which
  goes through `church_away_settle`). Whenever the switch is closed for the church it still
  deletes the `serve_away` row as it always did, and the ask stays a yes with no fact.
  `church_away_settle` will not make the fact again, on purpose. Anything that shows "away"
  must read the fact, not the ask's state.
- `church_away_asks_untold` (`where told_at is null`) keeps every ask that was answered or
  withdrawn before it was told. The sweep's reads each name their own state (built, S1-4).

### 2.2 Step 2: `supabase/APPLY-2026-11-20-church-schedule-limits.sql` (S2-1; applied 2026-11-18)

The file is the source; this is the map of it. It went in after step 1's file, adds to step 1's
tables and calls step 1's function. **Applied 2026-11-18** (run by the owner; checked by the
lead session with the file's own Check block: three tables with RLS on, no policies and no
browser or anon read; the five new columns; the four constraints validated; `church_away_settle`
with six arguments and `church_away_settle_excepted` with seven, each running for `service_role`
only; no asks). Since S2-2 and S2-3 it is read by `church_schedule_limits.py` and
`church_schedule.py` (section 3.3), and since S2-4 `church_away_pairs` too; `team_group_id`
waits for S2-5. Where it differs from the draft this section used to hold is listed, with why, in 7.8.

| Object | What it holds |
|---|---|
| `church_schedule_settings.leaders_limit`, `office_limit` | How many of each group may be away on one service date: 1 to 99, null = worked out (`max(1, people // 4)`) |
| `church_schedule_settings.service_weekdays` | The church's usual service days, 1 Monday to 7 Sunday: a plain list of 1 to 7 of them, null = worked out from its own plans, else Sunday (section 5) |
| `church_schedule_department_limits` | One number a department (`at_most`, 1 to 99), keyed by the department. No row = no limit (decision 9). Who set it: a login or a person, never both |
| `church_protected_days` | A day nobody takes off: one row a date a church, with a `name` of 80 at most |
| `church_away_pairs` | Two people who can't be away together, with a private `note` of 140 at most. `a_contact_id < b_contact_id`, so a pair is saved once and nobody is paired with themself. Private: only the owner and whoever oversees the office read them |
| `church_away_asks.excepted` | The flags a yes was given over (`over_limit`, `protected_day`, `pair`): the exception. `'{}'` on every ask until one is given; `decided_by` says who gave it |
| `church_away_asks.team_group_id` | A volunteer's ask: the team whose leader it went to |
| `church_away_settle_excepted(p_business_id, p_ask_id, p_state, p_by_user, p_by_contact, p_note, p_excepted)` | `church_away_settle`'s decision, then the exception saved on a yes it just made, in one transaction |

There is no table for which dates count: that is worked out in Python (section 5).

**The decision function: two names, on purpose.** Step 1's `church_away_settle` (six arguments)
is live and called by deployed code, and this file does not touch it: not its body, its
arguments or its grants (the check compares the function's id, body and grants before and
after). The exception gets a function of its own name, `church_away_settle_excepted`, which
calls `church_away_settle` for the decision and then saves the exception. So there is still one
place the decision is made, and the two can't drift apart. After the file there are exactly two
functions, one a name, neither overloaded, so neither a six-name nor a seven-name call has
anything to choose between. The two other ways were run on a real Postgres and turned down (the
check keeps both runs):

1. **Two functions of one name, the new one with a defaulted seventh argument.** Postgres itself
   refuses every call that leaves the seventh out (`function church_away_settle(p_business_id =>
   uuid, …) is not unique`), and PostgREST refuses it first (PGRST203: it picks by argument
   names, and both match). Every answer at the live church would fail.
2. **Drop the six-argument function and make a seven-argument one of the same name** (the
   draft, and decision 19). It works on the day: a six-name call lands on the new function
   through the default. But it takes a live function away to do it, and it leaves a trap. Step
   1's file is safe to run twice and makes the six-argument function again, so running it once
   more after step 2 would bring back case 1 and break every answer until someone noticed. With
   two names, no order of running the two files, however many times, leaves two functions for
   one name.

**What `church_away_settle_excepted` does**

| Asked for | The ask is | Written | Answers |
|---|---|---|---|
| `yes`, with an exception | `asked` | everything `church_away_settle` writes for a yes (2.1), then `excepted`: each flag once, in order | `changed: true`, the ask with its `excepted` |
| `yes`, with an exception that isn't one of the ask's flags, or is `short_notice`, `serving`, null or anything else | `asked` | nothing: it raises "An exception is for a flag the ask has…", and the yes and its fact are undone with it | raises |
| `yes`, no exception (left out, `'{}'` or null) | `asked` | what `church_away_settle` writes | what `church_away_settle` answers |
| `yes` | anything else | nothing; an exception passed now does not replace the one on the ask | `changed: false` |
| `no`, `withdrawn` | any | what `church_away_settle` writes; an exception passed is ignored. A yes taken back keeps the exception it was given | what `church_away_settle` answers |
| anything | not this church's, or not there | nothing | null |
| a state that isn't one of the three, or null | | nothing | raises, in `church_away_settle`'s own words |

It does not ask who is answering: a "can't make it" (a yes nobody gave) goes through it like any
other, so nothing here can block one. Whether an exception is ever passed with nobody deciding
is S2-3's call (7.8).

**What an exception may hold** (`church_away_asks_excepted`, whoever writes the row): only
`over_limit`, `protected_day` and `pair`; only flags the ask has (so a flag can't be taken off
an ask while an exception rests on it); and only on a `yes` or a `withdrawn` ask.

**Guards**

- `church_schedule_limits_same_business`, one function on three tables. On
  `church_schedule_department_limits` (before insert, and before an update that names
  `department_id`, `business_id` or `set_by_contact_id`): the department is the row's own
  church's, and so is the person who set the number. On `church_away_pairs` (before insert, and
  before an update that names either person or `business_id`): both people are that church's.
  On `church_away_asks` (trigger `church_away_asks_team_same_business`, before insert and
  before an update of `team_group_id`): the team is the ask's own church's. Each is checked
  only when a write names it, so a foreign key setting one of them null checks nothing.
- `church_away_pairs_ordered` (`a_contact_id < b_contact_id`) and `church_away_pairs_one`
  (unique on church and both people): one row a pair. `church_away_pairs_b` (church, second
  person) finds a pair from either side.
- `church_protected_days_one` (unique on church and day): one row a date a church.
- `church_schedule_settings_limits`, `church_schedule_settings_weekdays`,
  `church_schedule_department_limits_by_one` and the column checks on `at_most`, a day's
  `name` and a pair's `note`.

**Server-only.** All three tables: RLS on, no policies, `anon` and `authenticated` revoked,
`service_role` granted. Both functions: execute revoked from `public`, `anon` and
`authenticated`; `church_away_settle_excepted` granted to `service_role`. Neither is `security
definer`.

**What goes with what.** A church deleted takes everything. A department deleted takes its
number. A person deleted takes the pairs they are in; a number they set stays, with nobody in
their place. A login deleted leaves the number, the day and the pair, and the exception on an
ask stays when whoever gave it is gone. A team deleted leaves the ask with no team. The check
deletes a church both ways round (its people before its departments, and after).

**How it goes in.** One transaction, `lock_timeout` 5s, safe to run twice and in any order with
step 1's file, ends with `NOTIFY pgrst`. Additive: no table, column, function or row is dropped
or rewritten (the file's own triggers are dropped and made again, as every file here does), and
`serve_away` is not touched. The new columns are null, or `'{}'` by a constant default, on every
row that exists. The three checks and the one foreign key added to `church_away_asks` and
`church_schedule_settings` are validated as they go in, not `NOT VALID`: both tables are days
old and open at one church, and every row passes; the foreign key takes a short lock on
`groups` and reads none of it. The file's own Check and Rollback blocks are at its end, and the
check runs both as written: the rollback leaves the catalog exactly as step 1 left it, keeps
every ask and away date, and the file applies again after it.

**What the deployed code sees the moment it runs** (read in `church_schedule.py`,
`church_schedule_tell.py`, `member_portal_dates.py`, `sunday_serving.py` and
`sunday_planning.py` at `9871429b`, and run for real in the check):

- Every read of `church_away_asks`, `church_schedule_settings`, `church_schedule_people` and
  `serve_away` names its columns (`FIELDS`, `FACT_FIELDS`, `notice_days`, `id`); none is
  `select=*`. So no read returns anything new.
- `/rpc/church_away_settle` is called with six names and answers as before, from the same
  function. The row it answers with (`to_jsonb` of the ask) gains two keys, `excepted` (`[]`)
  and `team_group_id` (null), and so does the row a new ask's insert returns. Both go only
  through `shape()` and `church_schedule_tell._bare()`, which pick their keys by name.
- The check calls the function once before the file and again after it in the same session, so
  a connection that had already used it keeps working when the table gains its columns.
- No write sends the new columns: an ask's insert, the notice marks, an ask sent on, the
  reason cleared and an ask taken back all pass the new check and the new trigger untouched
  (`excepted` is `'{}'`, `team_group_id` null). Nothing deployed updates `flags`.
- Saving the notice days (an upsert that names `notice_days`, `updated_by`, `updated_at`)
  leaves the three new settings columns as they were.
- Step 1's own check, `__tests__/church_schedule_db.mjs`, passes with not a line changed when
  this file is applied straight after every run of step 1's file (152 of 152).

**For the PRs that write the code**

- **Step 2 has its own "is it there yet"** (built, S2-2): `church_schedule_limits.ready()`, a
  read of `church_protected_days`, kept as `ready()` is, with a `_FORCE` pin that `conftest`
  sets to False for every suite. `church_schedule.ready()` is true as soon as step 1's tables
  answer, with or without this file. Whatever reads a step 2 table or column, or passes
  `p_excepted`, first asks `church_schedule.step2()`, and until it says yes everything behaves
  as step 1.
- An answer that carries an exception calls `/rpc/church_away_settle_excepted` with seven names
  (built, S2-3). `church_away_settle` stays for every call that has none, a yes with nothing to
  except included, and both give the same answer for the same decision (the check runs every
  state against every decision through both). `__tests__/church_schedule_fake.py` models the
  new one, and with `limits=False` (its default) refuses everything this file adds, as a
  database without it does.
- A pair is written with the smaller id first. Postgres orders two uuids as their lower-case
  text orders (checked), so the server sorts the two ids as lower-case text before it writes;
  the wrong way round is refused, never saved twice. (Built, S2-4: `add_pair` sorts the two
  ids `_uuid` gives, which are lower-case.)
- The upsert keys: `department_id` for a department's number, `business_id,day` for a
  protected day (naming a day again changes its name, still one row).
- A flag can't be taken off an ask while an exception rests on it, so anything that recomputes
  an answered ask's flags leaves them alone.

**Checked** on PGlite 0.5.8 (PostgreSQL 18.3; production may be an older Postgres, and none of
this is new behaviour): `__tests__/church_schedule_limits_db.mjs`, 289 checks, in CI's database
job. Each rule of the file was broken once in a scratch copy to see the check go red (52 rules:
every constraint, every trigger check and its column list, each line of the new function, the
revokes, RLS, the Check and Rollback blocks, and "the old function is not touched").

### 2.3 Lifecycle registration

All in `account_lifecycle.EXPORT_EXCLUDED` (`:100`), each with a reason sentence. Step 1's four
went in with S1-1; step 2's three went in with S2-1 (built), which also made the settings
sentence true of its new columns.

| Table | Reason, in short |
|---|---|
| `church_away_asks` | who it went to and who answered are sign-in user ids; a private reason and told marks a restore must not carry; cascade on business and person |
| `church_away_commitments`, `church_schedule_people` | cite people by an id an import mints anew; the church sets them again |
| `church_schedule_settings` | a few numbers (the notice days and, from step 2, the two limits and the usual service days); set again |
| `church_schedule_department_limits` | keyed by a department id an import mints anew, set by a login or a person; each department sets its number again, and until then has no limit |
| `church_protected_days` | a date, a name and the login that added it; the church names its days again |
| `church_away_pairs` | both people are ids an import mints anew, and a pair is private; the church pairs them again |

`serve_away` stays where it is (`BUSINESS_CHILD_TABLES`, exported, not re-imported). Its export
now carries `ask_id` and `kind`: an id of an ask the export leaves out, and that ask's kind.
Neither is the reason.

---

## 3. Module layout

### 3.1 New files, step 1

**`church_schedule.py`** (the engine and the office router, `APIRouter(prefix="/church", tags=["church"])`)

**Built** (S1-2 and S1-3):

```
SWITCH = "CHURCH_SCHEDULE"; KINDS = ("time_off","commitment","cant"); GROUPS = ("leaders","office","volunteers")
NOTICE_DAYS = 14; MAX_OPEN = 20; ROSTER_SECONDS = 60; _FORCE: Optional[bool] = None

mode() -> str                          # off | owner | on; owner when unset; a typo is off
open_to(user) -> bool                  # as church_over.open_to
church_open(biz) -> bool               # member_asks.platform_church with `owner`
office_open(user, biz) -> bool
ready() -> bool                        # church_away_asks answers; serve_dates.ready's cache and _FORCE. Only "no such
                                       # table" (42P01, or PostgREST's PGRST205) says no; a blip keeps the last answer
on(biz) -> bool                        # church_open(biz) and ready(); what every reader outside the routes asks

settings(ch) -> {"notice_days": int}   # no row = 14; a failed read is a 503
save_settings(ch, me, body) -> dict    # the owner, or whoever oversees the office
is_short(ch, starts_on, today, notice_days=None) -> bool   # starts_on < today + notice_days

class Roster: leaders: Set[str]; office: Set[str]; added: Dict[str,str]; removed: Set[str]
    group_of(cid) -> Optional[str]; people() -> Set[str]
                                       # leaders / office are the groups as they stand (adds in, removes out)
roster(ch) -> Roster                   # inside church_map.once():
                                       #   leads  = member_portal_messaging.leading_people(ch.b)   (None = 503)
                                       #   office = set(ch.person_login)
                                       #   leaders = leads; office group = office - leads
                                       #   then adds (their grp, whatever the data says) and removes
roster_kept(biz) -> Optional[Roster]   # 60 s a replica; None on a failed read, never kept; for the member side
forget(biz)                            # a change is read again at once on this replica
waiting_kept(biz) -> Optional[Dict[str,int]]   # S1-5. {person: asks waiting for their yes}, by waiting()'s rule for a
                                       # person; 60 s a replica beside the roster; reads who and how many, never a
                                       # reason or a note; None on a failed read, never kept
forget_waiting(biz)                    # S1-5. _after calls it: a write on this replica is counted at once
section(biz, cid) -> Optional[{"waiting": int}]   # S1-5. the Lead tab's Dates entry for a person. None = no entry:
                                       # the tables aren't there (asked first, so nothing else is read before the
                                       # migration), the switch is closed, or they are not on the kept roster and
                                       # nothing waits on them. A count that couldn't be read is 0. Never raises:
                                       # anything that goes wrong is one logged line and no entry
set_listed(ch, me, contact_id, listed, grp=None) -> dict   # upsert or delete in church_schedule_people; the answer
                                       # (the schedule after) is worked out before the write; forgets the kept roster
people(ch, me) -> dict                 # GET people
department_of(ch, cid) -> Optional[dict]   # the active department they lead, else oversee, else are in

office_overseers(ch) -> List[str]      # the Manager logins that do oversee_lanes, from the Church's own rows
person_of(ch, me) -> Optional[str]     # a person is themself; a login, ch.login_person
over_all(ch, me) -> bool               # an office login that is the owner or an office overseer. Never a person
nearest(ch, asker_cid) -> List[Dict]   # S1-4. everyone at the nearest step over them: co.above(ch, who(PERSON, cid));
                                       # [] only for ch.owner_person. Anyone else church_over puts at the top (shares
                                       # the owner's email): the owner's login
goes_to(ch, asker_cid) -> Optional[Dict]   # nearest(...)[0]; None only for ch.owner_person
may_decide(ch, me, ask) -> bool        # it went to them, or over_all. Never your own ask, nor (the owner aside) one
                                       # you entered
needs_no_yes(ch, ask) -> bool          # kind 'cant', or the owner's own person's: never answered by anyone
sees_reason(ch, me, ask) -> bool       # the asker, whoever it went to, or over_all
may_withdraw(ch, me, ask) -> bool      # the asker, or over_all. Having entered it is not enough

ask(ch, me, body, *, now=None) -> dict       # the one write of an ask (section 5); reads everything before it writes
answer(ch, me, ask_id, yes, note=None) -> dict   # may_decide or 403; /rpc/church_away_settle; changed False = 409
withdraw(ch, me, ask_id) -> dict             # may_withdraw or 403; settle 'withdrawn'; changed False = 409
_after(what, ch, row, **kw) -> None          # S1-4. hands the row to church_schedule_tell once the write is back
                                             # (member_push._later: a thread of its own, a Church of its own); never
                                             # raises. ask -> tell_new, answer -> tell_answer, withdraw -> tell_withdrawn.
                                             # Since S1-5 it also forgets the kept counts (forget_waiting)
shape(ch, me, row, names) -> dict            # the one place a reason can leave: None unless sees_reason
mine(ch, me, now) -> List[dict]              # my asks, waiting first, 90 days back
waiting(ch, me) -> List[dict]                # asks that went to me and still wait
everything(ch, me, now) -> List[dict]        # every ask: over_all or 403
calendar(ch, me, lo, hi) -> dict             # by group: away (from the facts), waiting (only what `me` may read),
                                             # standing (S1-7: each day a thing that repeats falls on; the label
                                             # only for those who read a reason)
status(ch, me) -> dict                       # GET status
```

**Built** (S1-6: where it meets Who serves when):

```
HOLD_PAGE = 1000; HOLD_PAGES = 5
_here(biz) -> bool                           # the cheap check all four below start with: the switch (no read), the
                                             # tables (kept), the church. Under `owner` the church's answer is kept a
                                             # minute a replica whatever it was, a lookup that failed included (_OPEN):
                                             # member_asks.platform_church keeps only what it could read, and asks the
                                             # sign-in service again each time it couldn't
holds(biz_id, lo, hi) -> List[dict]          # the scheduler's hook: [{contact_id, starts_on, ends_on}] for every ask still
                                             # `asked` that touches lo..hi, then (built, S1-7) one row a day for each day
                                             # a thing that repeats falls on (church_schedule_repeats.held_days, its
                                             # own read: when it fails the asks are still held). Selects
                                             # who and which days only. NEVER RAISES and FAILS OPEN: [] when the switch
                                             # is off, the tables aren't there, the church is closed, or the read failed.
                                             # Asked in that order (switch, tables kept, church kept), so no read is
                                             # made there. Open: one read, HOLD_PAGE rows a page, HOLD_PAGES pages at most
on_schedule(biz, cid) -> Optional[bool]      # on the kept roster? False: off, closed, before the tables (no read), or
                                             # not on it. When the minute is up and it can't be read again, the last one
                                             # this replica read answers (_LAST). None: open, and this replica has never
                                             # read this church's roster and can't now. Never raises. What a page asks
takes(biz, cid) -> bool                      # on_schedule, for a write: the Serving Away form asks instead of saving.
                                             # None there reads as "not on it" (a volunteer comes first): the Away is
                                             # saved at once, as it always was, and one line is logged (the church,
                                             # never a name). Never raises
withdraw_fact(biz, cid, away_id) -> bool     # sunday_serving.drop_away: the date names an ask, so the ask is taken back
                                             # through withdraw() as that person (church_away_settle removes the date).
                                             # False: not ours (closed, a plain date, no such date, its ask gone or
                                             # already settled) and the caller deletes as it always did. A failed read
                                             # or write is a 503 with nothing removed
_serving(ch, cid, a, b, now) -> bool         # the `serving` flag when asked: they already said yes to serve inside the
                                             # days (sunday_serving.yes_places). A failed read says no and is logged
_open_places(ch, row, now=None) -> int       # after a yes: sunday_serving.open_places for the ask's days. After the
                                             # write, never inside it; anything that goes wrong is one logged line
```

`ask` sets `serving` beside `short_notice`. `answer` (a yes) and `ask` (one that settles at once,
and one found already settled) call `_open_places` once the settle is back, before the notice
is handed on.

**Built** (S1-7: things that repeat), in a module of its own, **`church_schedule_repeats.py`**
(`APIRouter(prefix="/church")`, the same gate as the other schedule routes), so the engine,
already near two thousand lines, gains only the two hooks below:

```
PATTERNS = ("weekly","every_other","month_nth"); WEEKDAYS (1 Monday … 7 Sunday); NTH (5 = "last")
MAX_EACH = 10; LABEL_MAX = 80; SPAN_DAYS = 366; START_BACK = 366; TELL_DAYS = 7
FIELDS (with the label, for those who shape it); DAYS_FIELDS (never the label: the scheduler's read)

days_of(row, lo, hi) -> List[date]           # pure: the days one commitment falls on inside lo..hi; a row that
                                             # can't be read falls on none, never an error
commitment_days(rows, lo, hi) -> Dict[str, List[date]]   # pure: {commitment id: days}; SPAN_DAYS (366) days at most,
                                             # counted from lo; days that aren't days fall on nothing
first_day(weekday, pattern, nth, start) -> date   # the first day it falls on, on or after start: what is saved
                                             # as starts_on (every other week's anchor is always one of its days)
how(row) -> str; said(row, today, long=False) -> str   # "Every other Saturday, from Dec 5", "The last Sunday of
                                             # each month", "Every Wednesday until Mar 31". Never the label
sees_label(ch, me, cid) -> bool              # church_schedule.sees_reason on the row an ask of theirs would be
                                             # (goes_to worked out now): the person, the one it would go to, and
                                             # (a login) the owner and whoever oversees the office
shape(ch, me, row, names, today) -> dict     # THE ONE PLACE A LABEL LEAVES ON A LIST: {id, contact_id, name,
                                             # weekday, pattern, nth, starts_on, until_on, said, mine, can_remove,
                                             # created_at} and `label` only when sees_label (absent otherwise)
standing(ch, me, rows, names, lo, hi) -> List[dict]   # the calendar's: {contact_id, name, day} a day, `label` the same way
of_people(ch, people, lo, hi) -> List[row]   # the calendar's read: a hundred people a read, each paged; 503 on failure
held_days(biz_id, lo, hi) -> List[dict]      # the scheduler's: [{contact_id, starts_on, ends_on}] one a day; one read,
                                             # HOLD_PAGE a page, HOLD_PAGES pages; NEVER THE LABEL; a page that fails
                                             # is [] and a logged line; NEVER RAISES
commitments(ch, me, box="mine") -> List[dict]    # mine: my own in force; all: every one in force (over_all, else 403)
add_commitment(ch, me, body) -> dict         # reads everything first; `for` as an ask's; ten in force; the same one
                                             # again is the one there; told_at set at once when there is nobody to tell
drop_commitment(ch, me, id) -> dict          # their own, or over_all; read first (404 for another church's); the
                                             # shape of what was taken off. Nobody is told
_after(ch, row)                              # member_push._later -> church_schedule_tell.tell_repeat
```

Where it is wired (built, S1-7): `church_schedule.holds` adds `held_days` after the asks, in a
try of its own; `church_schedule.calendar` reads `of_people` for the people on the schedule and
fills each group's `standing`; `church_schedule_tell` has `repeat_words`, `tell_repeat`,
`_bare_repeat` / `REPEAT_FIELDS` and the sweep's fifth read (`_claim`, `_release` and
`_claimed_send` take the table); `member_portal_dates` has the part of the page and its two
routes; `kmj_intake_automation` includes the router beside the limits'; `church_schedule_fake`
runs the table's checks and trigger on an insert.

- **The gate** copies `church_assignments._church` / `_church_from_body`: a church (404), `office_open` (404), `ready()` (404), then `co.Church(biz)`.
- **Who changes the structure** (section 7, item 7): `save_settings` and `set_listed` are for the owner and whoever oversees the office only. An Admin does not change the roster, the notice days or (step 2) the leaders and office numbers.
- **`may_decide`** differs by door, and is never true for your own ask:
  - a login (office app): it went to them (`to_user_id` while that login is still on an office seat, or `to_contact_id in ch.persons_of(me)`), or they are the owner, or one of `office_overseers(ch)`. The owner also holds an ask nobody else can answer (both `to` columns empty, or a login that has left the office: no longer an Admin or Manager seat, whatever seat it has now). Never one they entered, unless they are the owner;
  - a person (member app): `to_contact_id == me`, or `to_user_id` is still an office login and `ch.login_person.get(to_user_id) == me`. Never the owner's or overseer's across-the-board power (section 7, item 6).
- **Every write reads first.** `ask`, `answer`, `withdraw` and `set_listed` read everything their answer says (who `me` is, who oversees the office, every name) before the write, so a failed read is a 503 with nothing saved and nothing after a write can fail on a read.
- **An ask that needs no yes is two writes** (the insert, then `church_away_settle`): the tables have no one-transaction path for "make it and settle it". If the second fails the ask is deleted and the answer is a 503. Asking again finishes whatever was left (an ask still `asked` for the same days and kind is settled, not copied) and answers with one that did settle when only its answer was lost (the same days and kind, a yes nobody decided, its fact still there). Two presses at once end as one: the table keeps one waiting ask for the same days, so the second insert goes in once the first has settled; the second looks again before it settles, deletes its own row and answers with the first. A settle that finds the ask moved (`changed: false`) is a 409, never `saved`. The insert and every settle are sent with `redact=True`, so a refusal's body (which can echo the row) never reaches the log.

**`church_schedule_tell.py`** (**built**, S1-4)

```
KIND = "serving"; NUDGE_DAYS = 3; REASON_DAYS = 90; SETTLE_SECONDS = 120; ANSWER_DAYS = 7
MEMBER_PAGE = "/my/lead/dates"  # where a person's notice points: Dates on the Lead tab (S1-5; it was /my/lead)
MEMBER_LINK = "Open your dates" # the email's button (S1-5; it was "Open your Lead tab")
PRIVATE = "or=(reason.not.is.null,decided_note.not.is.null)"   # an ask that still holds either private text
FIELDS = "id,business_id,contact_id,kind,starts_on,ends_on,state,flags,to_user_id,to_contact_id,decided_by_*,
          decided_at,told_at,answer_told_at,nudged_at,created_at"     # all a notice may know: never reason, never decided_note
_bare(ask) -> dict              # the ask with FIELDS only: every function below starts with it

Each tell answers with what happened: told | held (quiet hours) | taken (someone else told it) | unsent (nothing could
be sent: the claim is let go) | unread (a name or an address couldn't be read: nothing claimed) | none | closed.

tell_new(ch, ask, *, now=None) -> str        # claim told_at, tell whoever it went to. `cant` (once it is a yes) goes at
                                             # once; any other kind waits out member_push.quiet_hour(biz) for the sweep
tell_answer(ch, ask, *, now=None) -> str     # claim answer_told_at, tell the asker, outside quiet hours. Nobody when
                                             # nobody decided (decided_by empty) or it needs_no_yes
tell_withdrawn(ch, ask, *, by) -> str        # no claim: sent once, straight after the write. `by` the asker: whoever it
                                             # went to, when told_at is set. `by` anyone else: the asker
tell_nudge(ch, ask, *, now=None) -> str      # claim nudged_at: told_at is NUDGE_DAYS old and it still waits
to_person(biz, cid, *, title, body, ref, subject, text, url=MEMBER_PAGE, link_label="", email=None, name="")
                                -> {"rang", "mailed"}
                                # member_push.send(biz, KIND, …, contact_ids=[cid], ref_id=ref): the push and the line in
                                # the church's conversation, once a ref; when rang == 0 and they have an email:
                                # clt.deliver(clt.render_email(…)), the link {site origin}/my/lead/dates
to_login(ch, uid, *, title, body, ref, subject, text, email=None, name="") -> {"rang", "mailed"}
                                # push_notifications.send_to_user(nav=cas.NAV) and an email (cot.render, cot._link).
                                # cas._login_email None: nothing is sent, so nothing is claimed
sweep_tick(now=None) -> Dict[str,int]   # hourly on the worker: {churches, moved, told, answers, nudged, cleared, held,
                                        # unsent, unread}
```

- **The reason and the note are in no notice and no log line.** `_bare` drops them from every row handed in; the
  sweep's reads never select them; every write to `church_away_asks` is sent `redact=True` (new on
  `sb_clients.sb_patch_as_service`), so a refusal's body, which can quote the whole row, is never logged. A lock
  screen says "Marcus asked for Dec 20 to 27".
- **Who is reached how.** `to_contact_id`: a person. `to_user_id`: a login. The asker: the owner's login for
  `Church.owner_person`, their office login for an Admin's or Manager's person (`Church.person_login`), else a person.
- **A claim** is one update that lands only while the mark is empty, the ask is in the state it was read in, and
  (for `told_at` and `nudged_at`) it still names the same `to`. It is taken before the send and let go when nothing
  was sent.
- `ask`, `answer` and `withdraw` hand the row on through `church_schedule._after` (`member_push._later`) once the
  write is back. The thread makes its own `Church`.
- The sweep reads nothing while `mode()` is off or `ready()` is false. It works the churches
  `cas._open_churches()` gives that `church_open` also says yes to (so it follows `CHURCH_ASSIGNMENTS` too), and
  never a sample church. Four reads, each paged by id and each naming its state:
  - `state=eq.asked`: sent on where stale (below), told when untold and older than `SETTLE_SECONDS`, nudged;
  - `state=eq.yes&kind=eq.cant&told_at=is.null`: an untold "can't make it", until its last day has passed;
  - `state=in.(yes,no)&answer_told_at=is.null`, decided by someone in the last `ANSWER_DAYS`: untold answers;
  - `or=(reason.not.is.null,decided_note.not.is.null)&ends_on=lt.…`: ids only, then `reason` and `decided_note`
    set null by id, the write naming the same rule again (section 7, item 14). A row with a note and no reason is
    found too. The note went with the reason in S1-5 (7.6); S1-4 cleared the reason alone.
- **Sent on** (section 7, item 15, as built in 7.5): a waiting ask whose `to` is empty, a login that has left the
  office, or no longer anyone `nearest()` gives goes to `goes_to()`'s answer, with `told_at` cleared. Never one that
  `needs_no_yes`. An ask whose last day has passed is neither sent on, told nor nudged.
- **Not in the sweep** (corrected in S1-1): the spec had "a yes with no `serve_away` row is settled again". `church_away_settle` writes the yes and its fact in one transaction, so a yes without a fact can only be a fact deleted afterwards, and a second yes answers `changed: false` and writes nothing. That is on purpose: the function must not bring back an away date its person took off.

**`member_portal_dates.py`** (**built**, S1-5; `APIRouter()`; a copy of `member_portal_assign.py`'s shape)

```
HERE = "/my/lead/dates"; WINDOW_DAYS = 62; PICK_MAX = 200; DONE, DONE_ALONE, ERRORS, DATES_CSS
_ch_me(biz, me) -> (Church, who)                # THE ONE PLACE that says who `me` is: always co.who(PERSON, …)
view(biz, contact_id, now=None) -> dict         # {mine (each with on_calendar), waiting, away, people (to pick who
                                                # covers), on_it, top, to, notice_days, near, today, tz, repeats}.
                                                # Every ask through shape() as that person. `away` is name, days, who
                                                # covers and "waiting for your yes" and nothing else (and, S1-7,
                                                # someone's thing that repeats as name and `days`). `repeats`: their
                                                # own, through church_schedule_repeats.shape() as that person
chief_line(v) -> str; body(v) -> str
render(biz, site, request, me, v, seg, *, err="") -> str; render_not_here(biz, site, me) -> str
async serve(request, biz, site, me, *, err="")  # GET /my/lead/dates: (html, status), or None when it is not a page
                                                # at all (closed, or before the tables). The page reads fresh; someone
                                                # with nothing of theirs there gets render_not_here and a 404
_go(**q); _code(e) -> str; async _act(request, fn, ok)   # as member_portal_assign, the switch being church_schedule.on;
                                                # fn may answer with its own done code
_cover(ch, me, form) -> Optional[str]           # who covers, from the list: on the schedule here, never the asker
```

Page order: Waiting for your yes (if any); Ask for time off (first day, last day, kind, private reason, who covers); I can't make it; My dates with their state and Take it back; Things that repeat (S1-7, built: their own in plain words with what they typed and Remove, then the form: what it is, which day, how often, starting, until if it ends; the form only for someone on the schedule, and none past ten); Who else is away (name, days, who covers; never a reason, a note or the kind; someone's thing that repeats as their name and its days, never what it is). No ids on the page; ids ride in form addresses and option values.

- **A member-app session is a person, never a login** (section 7, item 6). Every call into the engine is made as `co.who(PERSON, …)` through `_ch_me`, whoever is signed in: the owner's own person and the person of whoever oversees the office read a reason and answer only what went to them (or to the office login tied to exactly them), and their own.
- **A refusal comes back as plain words.** `_code` turns the engine's 400, 403, 404, 409 and 503 into a short code; the page's own `ERRORS` says it. Nothing but the code rides in the address: the name ("waiting for …'s yes") and the number of days are filled in on the page.
- **My dates reads the fact.** A yes is "on the calendar" only while its `serve_away` row is there (`_on_calendar`); one taken off since is shown as "Off the calendar" (section 2.1, "Not solved by the tables"). Since S1-6 that is left only by a date taken off while the switch was closed: with it open, taking the date off takes the ask back, and My dates says "Taken back".
- **A place that will open is said before the yes** (S1-6, `_serving_line`): while an ask that carries `serving` waits, the one it went to reads "{first name} said yes to serve on one of these days. With your yes, that place opens again for their team.", and the one who asked reads the same about their own. Never on "can't make it", and never once it is answered.

### 3.2 Existing files changed, step 1

The first six rows are S1-6, **built**; where the build differs from the plan the row says what was built.

| File | Function | Change |
|---|---|---|
| `sunday_serving.py` | `add_away` | first lines: `if church_schedule.takes(biz, cid)`, then `_ask_away`: `church_schedule.ask` as that person (`member_portal_dates._ch_me`) with `kind: time_off` and no reason, answering `{"asked": True, "state", "to": name, "short"}`. Everyone else falls through to the code as it was, untouched. If the engine says they aren't on the schedule after all (taken off within the minute the roster is kept), it is saved as anyone's |
| `sunday_serving.py` | `drop_away` | first lines: `if church_schedule.withdraw_fact(biz, cid, away_id): return`; else the delete as today. While the switch is closed the delete goes as today and leaves that ask at `yes` with no fact; the calendar reads facts from `serve_away`, so nothing shows as away that isn't |
| `sunday_serving.py` | `_opened`, `yes_places`, `open_places` (new) | `_opened(why)` is what a place that opens is saved as, now shared with `cant_make_it` (which writes what it always wrote). `yes_places(biz_id, cid, starts_on, ends_on, now)`: their `yes` places on services still to come whose day, on the scheduler's clock, is inside the days; the services are read a page at a time and the places a hundred services at a time. `open_places(...)`: one update for those places, guarded by `contact_id` and `status=eq.yes`, with the note "Can't make it · Away" |
| `sunday_planning.py` | `_Board.__init__` | after the `serve_away` read: `self.held = church_schedule.holds(biz, self.lo_day, last)` |
| `sunday_planning.py` | `_Board.is_away` | also true for a row in `self.held`. `board.away` and `GET /planning/schedule` stay untouched, so a waiting ask is never listed. Everything that asks the board gets the hold with no change of its own: `candidates`, `do_ask`, `do_fill`, `sunday_leading` (a team's own leader), `sunday_serving` (taking an offered place, covering for someone, finding a sub), an event date (`serve_dates` adds rows to the same board) and the worker's "No answer yet" note (`sunday_serving_alerts._office_note`, which names who could take the place) |
| `member_portal_serving.py` | `away` route, `ASKED`, `_asked_flash`, `_dates_line`, `_dates`, `serve`, `render_page` | the route keeps `add_away`'s answer in a closure and goes back with `done=asked` or `done=asked_short` (only the code rides in the address; one that needed no yes goes back with `done=away`, as anyone's does). `serve` sets `m["dates"]` from `church_schedule.on_schedule` (what is kept; no read where closed): `None` for everyone not on the leaders schedule, and then the page is byte for byte what it was. For someone on it: the flash "Asked. {name} will say yes or not this one, and with a yes these days go on your away days." with a link to `/my/lead/dates` (the name is read on that one page view only), and one line under Away with the same link |
| `member_portal_dates.py` | `_serving_line`, `_wait_card`, `_mine_card` | one line while an ask that carries `serving` waits: a yes opens the place they had agreed to serve. Done in S1-6 |
| `member_portal_lead.py` | ContextVars `:59-76`, `_context` `:639`, `_seg` `:826`, `serve` `:660` | new `DATES` ContextVar set from `church_schedule.section`; a `("dates", "/my/lead/dates", "Dates · n")` entry after Tasks (the switcher takes the class `fit` only when Dates is in it: each entry keeps its words on one line and the row scrolls inside itself on a phone); `selected == "dates"` goes to `member_portal_dates.serve`; with nothing else to lead, `/my/lead` opens on Dates. Done in S1-5 |
| `member_portal.py` | `_leads` `:1197` | after the tasks check: `church_schedule.section(biz, me_id) is not None` gives the tab, so an office login's person with no role still reaches Dates. It answers from what is kept a minute: no read on a page view. Done in S1-5 |
| `kmj_intake_automation.py` | routers `:453-456`, `:607-610`; jobs `:2039-2053` (f859d05a) | include `church_schedule.router` (done in S1-2) and `member_portal_dates.router` (done in S1-5, beside the other Lead tab routers); `add_job(g("church_schedule_sweep", _cst.sweep_tick), "interval", hours=1, id="church_schedule_sweep")`, after the hand-overs sweep. Done in S1-4 |
| `sb_clients.py` | `sb_patch_as_service` | takes `redact=` as the GET and the POST do, so a refused update of an ask never logs the row. Done in S1-4 |
| `account_lifecycle.py` | `EXPORT_EXCLUDED` `:100` | the four tables (2.3). Done in S1-1 |
| `__tests__/conftest.py` | near `:169-178` | autouse: `church_schedule._FORCE = False`, so no other suite gains a read; the schedule suites set it True. Since S1-5 it also empties the kept counts (`_WAITING`), as it does the kept roster |
| `__tests__/test_sample_church_no_sends.py` | `TICKS` `:97` | `"church_schedule_sweep": "church_schedule_tell:sweep_tick"`. Done in S1-4 |
| `__tests__/church_schedule_fake.py` | `build`, `later` | what a write hands on to be told is kept in `db.later` and not run, so every schedule suite sees that nothing is told inside a write; `later(db)` runs it. Done in S1-4 |
| `.env.example` | near `:718-729` (f859d05a) | the `CHURCH_SCHEDULE` block: off / owner / on, owner by default, read on both services (unset means owner on both), needs the migration. Done in S1-4 |
| `docs/MIGRATIONS.md` | ledger | one row a file. Step 1's is in S1-1 |
| `.github/workflows/ci.yml` | the `test-db` job's list | `node __tests__/church_schedule_db.mjs`. Done in S1-1 |
| `church_my_week.py` (optional, S1-8) | where `from_office` is built `:332-395` | `dates: {waiting: n}` for a login: the office front page's count |

### 3.3 Step 2

**`church_schedule_limits.py`** (**built**, S2-2 and S2-3; the numbers, the days, the protected
days, and its own router on the same `/church` prefix)

```
FLAGS = ("over_limit", "protected_day", "pair"); NEAR_DAYS = 56; PICTURE_DAYS = 366 + 2 * 56 + 2; _FORCE
ready() -> bool                                # step 2's own "are its tables there": church_protected_days answers.
                                               # church_schedule.ready's rule and cache; conftest pins it False
default_limit(people) -> int                   # max(1, people // 4)
usual_weekdays(ch, now=None) -> List[int]      # settings.service_weekdays, else worked out, else [7]
department_people(ch, department_id) -> Set[str]   # everyone on its Sunday teams (leaders too), each once. A team is
                                               # an active group with a serve_teams row that hangs from the department
                                               # as a group unit, or by name as a Serve option
class Picture: lo, hi, today, roster, people, limits, weekdays, worked_out, days, departments, away, pairs, held
    away_on(day, people, but="") -> Set[str]   # who of `people` has an away date that day; never `but` (the asker)
    counted(lo=None, hi=None) -> List[day]     # the days that count, soonest first
    pair_hits(cid, first, last, before=None) -> Set[str]   # S2-4: the other of each of their pairs in force whose away
                                               # date, or waiting ask made before `before`, overlaps on any day. PRIVATE
picture(ch, lo, hi, *, now=None, who=None) -> Picture    # ONE WINDOW, READ ONCE (PICTURE_DAYS at most, a 400 past it):
                                               # the roster, the church's numbers, its plans (a page at a time), the
                                               # protected days, each numbered department's people, and THE FACTS
                                               # (serve_away, a hundred people a read, each read paged). Never an ask.
                                               # `who` (S2-4): also those people's pairs in force (one read), and, only
                                               # when there is one, the other's waiting asks (who, days, created_at)
service_days(ch, lo, hi) -> List[{"day": date, "kind": "service"|"event"|"protected", "name": str}]
limit_for(ch, grp, department_id=None) -> Optional[int]   # a department: its row's number, None = no limit
away_on(ch, day, grp, department_id=None) -> Set[str]
flags_of(picture, cid, first, last, department_id=None, *, before=None, pairs=True) -> {"flags": [...], "why": [...]}
                                               # pure; S2-4 adds at most one {"flag": "pair"}, no day, no name
flags_for(ch, asker_cid, starts_on, ends_on, *, department_id=None, now=None, before=None) -> the same, read fresh
                                               # for those days, with the asker's pairs (`before`: the recheck's
                                               # created_at, so a later waiting ask of the other never counts)
nearest_open(picture, cid, first, last, department_id=None) -> {"before": day|None, "after": day|None}   # never pairs
look(ch, cid, first, last, *, department_id=None, now=None) -> {"flags", "why", "open", "up"}   # the Dates page,
                                               # before sending. Reads; never writes. A pair alone offers no open days
may_set_limit(ch, me, department_id=None) -> bool
limits(ch, me) -> dict; set_limit(ch, me, body) -> dict      # GET / PUT limits
days(ch, me, lo, hi) -> dict                                 # GET days
protected_days(ch, me, lo, hi); add_protected(ch, me, body); drop_protected(ch, me, id)
volunteers(ch, me, lo, hi) -> dict                           # GET volunteers (read only)
pairs(ch) -> List[row]                                       # S2-4: every pair, paged. PRIVATE (internal)
view_pairs(ch, me); add_pair(ch, me, a, b, note); drop_pair(ch, me, id)   # GET / POST / DELETE pairs: the owner and
                                                             # whoever oversees the office only
_partners(ch, who, on); _waiting(ch, people, lo, hi); _made_before(at, before)
```

`why` has one entry a day and cause, soonest first: `{"flag": "protected_day", "day", "name"}`,
and `{"flag": "over_limit", "day", "of": "leaders"|"office"|"department", "name", "away",
"at_most"}`. Counts only. Then, last and at most once, `{"flag": "pair"}` (S2-4), with no day
and no name.

**`church_schedule.py`**, step 2 (**built**, S2-3)

```
UP_FLAGS = ("over_limit", "protected_day", "pair")
step2() -> bool                                # church_schedule_limits.ready(); never raises. Asked before anything
                                               # of step 2 is read or looked at
_fields() -> str                               # FIELDS, and `excepted` once step 2 is there
flagged(ask) -> bool                           # the row carries a flag that sent it up
gives_exception(ch, uid, asker_cid) -> bool    # the owner always; whoever oversees the office unless the asker is
                                               # guarded (co.is_guarded). Nobody else, an Admin included
goes_up(ch, asker_cid, *, entered=None) -> Dict    # whoever oversees the office; the owner when nobody does, when the
                                               # asker is guarded or is one of them, or when the only one is `entered`
                                               # (the login that entered the ask, who can't answer it)
held_right(ch, ask) -> bool                    # a flagged ask sits with a login that may give its exception
_may_except(ch, me, ask) -> bool               # a login: gives_exception. A person: only an ask whose `to` login is
                                               # tied to exactly them and gives the exception
_recheck(ch, me, row) -> (excepted, moved)     # before a yes. READS ONLY
_send_up(ch, row, moved)                       # a yes that didn't land: one update (flags, to, told_at), tell_new for
                                               # the new person, then a 409. Always raises
```

- `ask`: for an ask that needs a yes, and only once `step2()` says yes, `flags_for`; any flag
  is added and `to` becomes `goes_up`. An ask that needs no yes ("can't make it", the owner's
  own) is never looked at and reads nothing of step 2.
- `may_decide`: a flagged ask is answered only through `_may_except`. The one it first went to
  no longer answers it.
- `answer`: a yes calls `_recheck`. Nothing new: the yes goes through
  `/rpc/church_away_settle_excepted` with the ask's own flags that are still true, or through
  `/rpc/church_away_settle` when none is. Something new: `_send_up`, and the yes does not land.
- `shape`: carries `excepted` only when the row does, so on a database with step 1 alone the
  shape is step 1's, key for key.
- `calendar` is unchanged: the counts a service day are `GET /church/schedule/days`.

Since S2-4 (**built**): `DAY_FLAGS`; `NEEDS_NOW`, `WENT_UP_NEEDS`, `YOURS_NEEDS` and
`_now_words(flags)`, the words of a yes that didn't land when what is new (or unshown) is a pair
alone; `_recheck` passes the ask's `created_at` as `before` and returns `new`; `shape` drops
`pair` from `flags` and `excepted` for anyone who doesn't read the reason.

**`church_schedule_tell.py`**, step 2 (**built**, S2-3): `up_words(ask)` is the one sentence a
flagged ask's notice adds ("It's past the number who can be away at once", "It's on a protected
day", and since S2-4 "It overlaps with someone they can't be away with", or two or three of
them in one sentence); the sweep leaves a flagged ask where it is while `held_right`, sends it
to `goes_up` when it isn't, and never sends one back down to the nearest step.

**`member_portal_dates.py`**, step 2 (**built**, S2-3): `_look`, `_Look`, `_show`, `_ask_again`,
`_look_block`, `_up_line`, `_why_said`, `_limits` (section 4.2 and 7.9). Since S2-4: `PAIR_YOU`,
`PAIR_THEY`, `NOT_SENT_PAIR`, the codes `dt_up_now` and `dt_yours_now`; `_limits` reads the
pairs of whoever asked what waits for the reader's yes and names the other only on a card the
reader may answer; `_why_lines` says a pair once, after the days (7.10).

**`church_schedule_volunteers.py`** (**built**, S2-5; the volunteers' rules. No router: the
member app's Serve page and Dates, and the hourly sweep, call it)

```
GRP = "volunteers"; MINE_MAX = 50
here(biz) -> bool                              # church_schedule._here (switch, tables, church: kept) and step2() (kept).
                                               # NEVER RAISES. False: nothing here reads
teams_of(ch, cid) -> List[gid]                 # the Sunday teams they are on (serve_teams, active), by name; paged
departments_of(ch, cid) -> List[{id, name, teams}]   # the active departments those teams hang from (as one of its
                                               # groups, or by name as one of its Serve options), the church's order
team_step(ch, gid, department_id=None, *, but) -> List[{kind, id, name}]   # everyone at the first step that has
                                               # anyone: the team's own leaders (group_members role leader, by name);
                                               # the department it hangs from, its leader while they hold a role that
                                               # leads, else its overseer while they hold one that oversees
                                               # (church_map.team_head's rule, #1719); its leader, else its overseer,
                                               # whatever they hold; whoever keeps Who serves when (the Manager logins
                                               # holding serve_schedule; never an Admin); the owner. Never `but`
leader_of(ch, gid, department_id=None, *, but) -> Optional[{kind, id, name}]   # team_step's first: the doc's
                                               # `team_leader` (that word is a role key, kept out of rule code)
volunteer_plan(ch, cid, starts_on, ends_on, *, now) -> {"instant", "flags", "to", "team_group_id", "department_id",
                                               "full": [{department, why}], "places": [...]}   # READS ONLY
ask(ch, cid, starts_on, ends_on, plan) -> row  # the one write: time off, no reason, grp volunteers, team_group_id,
                                               # department_id, to the plan's `to`; the same days again answer with
                                               # the one waiting; 20 waiting a 400 (TOO_MANY)
away(biz, cid, start, end) -> Optional[dict]   # the Serve page's branch (sunday_serving.add_away). None: SAVED AT
                                               # ONCE, AS ALWAYS (free, closed, on the leaders schedule or can't tell,
                                               # or ANYTHING going wrong: one line logged). Else {"asked": True,
                                               # "volunteer": True, "state", "to", "short": False}
mine(biz, cid, now=None) -> Optional[List[shaped]]   # My serving: their own still waiting, and a "not this one"
                                               # still to come, through shape() as that person. One bounded read;
                                               # None closed (no read) or unreadable. NEVER RAISES
take_back(biz, cid, ask_id) -> bool            # the x on a waiting one (church_schedule.withdraw_fact asks it when no
                                               # away date has that id, and only with step 2 there)
stale(ch, ask) -> Optional[{kind, id, name}]   # the sweep: who it should sit with now, or None to leave it
```

Where it is wired (**built**, S2-5):

- `church_schedule.volunteer(ask)`: `grp` (or shape()'s `group`) is `volunteers`. `flagged()`
  is false for such an ask, so it never goes up and whoever it went to answers it;
  `answer()` never rechecks one and never gives it an exception; `withdraw_fact` hands an
  id that names no away date to `take_back`.
- `sunday_serving.add_away`: after `takes()` says no, `church_schedule_volunteers.away`; None
  goes on to the code as it always was.
- `member_portal_serving`: `_vol` (`m["vol"]`), `_vol_flash` (`done=vol_asked`: "Sent to {to},
  because {why}. …", with "Find someone to cover {day}" for each Sunday they were on for),
  `_vol_chips` ("Dec 18 – 25 · waiting for {name}", with the same x), `_vol_lines` (a "not this
  one" still to come, and its note). With `m["vol"]` None all three are empty.
- `member_portal_dates`: `_limits` works out `why` for a volunteer's ask on a full day (their
  department's number alone); `_vol_line` is its card's "Why it came to you" (and, on their own
  card, "Why it went to {name}"); a volunteer who opens Dates by a link reads that theirs are on
  My serving too.
- `church_schedule_tell`: `FIELDS` gains `grp` and `department_id`; `volunteer_why`, the words
  of a volunteer's ask and its answer; `SERVING_PAGE` (`/my/serving`, "Open My serving") for
  the volunteer's own notices; the sweep reads `team_group_id` where step 2 is there and sends a
  volunteer's waiting ask on only along its team's chain (`stale`).

### 3.4 Where step 5 (Chief verbs) hooks in

- A new `chief_church_schedule.py` in the shape of `chief_church_assignments.py`.
- `HANDLERS` and `PROGRESS` merged at `chief_of_staff.py:12446` and `:423`.
- A `turn_line` beside `:15897-15900`.
- Registry rows beside `action_registry.py:548-573`.
- Each verb calls `church_schedule.ask / answer / withdraw / calendar` with `me = co.who(LOGIN, turn user)`. Every read goes through `shape()`, so Chief never says a reason to a login that can't read it.

---

## 4. Routes

### 4.1 Office (`/church/schedule/…`)

- Session and gate as `church_handovers.py:447-482`: `Depends(sb_clients.authed_request)`; reads use `Depends(business_access.business_access("member"))`; writes use `_church_from_body` (`assert_access(..., "member")`).
- Closed, not a church, or before the migration: 404. A failed read or write: 503.

**The ask shape**

```
{id, contact_id, name, group, department: {id,name}|null, kind, starts_on, ends_on,
 state, flags: [..], to: {kind,id,name}|null, cover: {contact_id|null, name}|null,
 decided: {by, at, note}|null, reason: str|null, reason_hidden: bool,
 mine: bool, can_answer: bool, can_withdraw: bool, created_at}
```

- `decided.note` is kept to the same people as `reason` (it can say why). `decided.by` is null on a yes that needed nobody's.
- With step 2's tables there the shape also has `excepted: [..]`, the flags a yes was given over (empty until one is). On a database with step 1 alone the key is absent.
- A plain away date (a `serve_away` row with no ask) is shown on the calendar with the same keys: `id` and `kind` null, `state` `yes`, never a reason, `can_withdraw` false.

**Step 1** (built, every row; the commitments row in S1-7)

| Route | Body / query | Answers | Who |
|---|---|---|---|
| `GET /church/schedule/status?business_id=` | | `{open, me: {person: contact_id\|null, group: 'leaders'\|'office'\|null, goes_to: {kind,id,name}\|null, sees_all: bool, can_set: bool}, owner_how, notice_days}` | any seat |
| `GET /church/schedule/people?business_id=` | | `{leaders: [{contact_id,name,what,department}], office: [...], added: [...], removed: [...], can_change}` | a seat whose person is on the schedule; the owner, an Admin, the office overseer. `can_change` is true for the owner and the office overseer only |
| `PUT /church/schedule/people` | `{business_id, contact_id, listed: 'add'\|'remove'\|null, group?}` (`group` is `leaders` unless it says `office`; null puts them back to what the church's data says) | the same shape, as it stands after | the owner, the office overseer (not an Admin: section 7, item 7) |
| `GET /church/schedule/leaders?business_id=&from=&to=` (93 days at most; from today for 62 days when unnamed; days that can't be a window, the very end of the calendar included, are a 400) | | `{from, to, groups: [{key, name, people, away: [ask or plain fact], waiting: [ask], standing: [{contact_id,name,day,label}]}]}`. `people` is how many are in the group. `away` is read from `serve_away`; everyone on the schedule gets name, dates and who covers, and a reason only as `shape()` allows. `waiting` holds only the asks the reader may read (their own, the ones that went to them, and for the owner and the office overseer every one). `standing` (built, S1-7): one entry for each day in the window a thing that repeats of someone in the group falls on, `{contact_id, name, day}`, and `label` only for those who read an ask's reason (the person, whoever an ask of theirs would go to, the owner, the office overseer); for anyone else the key is absent | on the schedule, or the owner / office overseer. **The `serve_schedule` holder gets a 403 here unless they are on the schedule themselves** |
| `GET /church/schedule/asks?business_id=&box=mine\|to_me\|all` | | `{asks: [ask]}`. `mine`: waiting first, then the last 90 days. `to_me`: the waiting ones that went to me (for the owner, also one nobody else can answer). `all`: every waiting ask and the last 90 days; the owner and the office overseer only (403) | as the box says |
| `POST /church/schedule/asks` | `{business_id, starts_on, ends_on, kind, reason?, cover_contact_id?, cover_name?, for?: "person:<id>"}` | `{saved: ask}` | a seat for its own person (409 "This login isn't matched to a person here yet" when it has none; 403 when that person isn't on the schedule); `for` only by the owner / office overseer (403), and only for someone on the schedule (400). `kind: cant` only when the first day is inside the church's notice days, two days at least (400 otherwise, pointing to time off) |
| `POST /church/schedule/asks/{id}/answer` | `{business_id, yes: bool, note?}` | `{saved: ask}`; 409 when it had already moved | `may_decide`: 403 for your own ask and (the owner aside) for one you entered; 409 for one that needs no yes |
| `POST /church/schedule/asks/{id}/withdraw` | `{business_id}` | `{saved: ask}` | the asker's login; the owner and the office overseer (403 for anyone else, the login that entered it too) |
| `GET /church/schedule/settings?business_id=` / `PUT` | `{business_id, notice_days}` (0 to 90) | `{notice_days}` | read: on the schedule, the owner, the office overseer; write: the owner, the office overseer |
| `GET /church/schedule/commitments?business_id=&box=mine\|all` / `POST` / `DELETE …/{id}?business_id=` (**built**, S1-7) | `POST {business_id, label (80 at most), weekday (1 Monday to 7 Sunday), pattern: weekly\|every_other\|month_nth, nth? (1 to 5, 5 the last; month_nth only), starts_on? (today when unnamed; within a year either side), until_on? (today or later), for?: "person:<id>"}`. starts_on is saved as the first day it falls on, on or after the day named | `{commitments: [c]}` / `{saved: c}` / `{removed: c}`, each `c` `{id, contact_id, name, label?, weekday, pattern, nth, starts_on, until_on, said, mine, can_remove, created_at}` (`said`: "Every other Saturday, from Dec 5") | `GET mine` and `POST`: a seat for its own person (409 when it has none; `POST` 403 when that person isn't on the schedule, 400 past ten in force); `for` only by the owner / office overseer (403), and only for someone on the schedule (400), as an ask's. `GET all`: the owner and the office overseer (403). `DELETE`: their own, or the owner / office overseer (403); 404 for another church's |

**Step 2** (every row is **built**: S2-2 and S2-3, and the pairs rows S2-4; every one answers 404 until step 2's own tables are there)

| Route | Body / answers | Who |
|---|---|---|
| `GET /church/schedule/limits?business_id=` | `{leaders: {at_most, set, people}, office: {…}, departments: [{id, name, at_most\|null, people, can_set}], service_weekdays, worked_out: bool, can_set: bool}`. `set` is the church's own number (null: `at_most` is worked out) | on the schedule, the owner, the office overseer. The `serve_schedule` holder who is not on the schedule gets `departments` only (`leaders` and `office` null). Anyone else: 403 |
| `PUT /church/schedule/limits` | exactly one of `{business_id, group: 'leaders'\|'office', at_most\|null}`, `{business_id, department_id, at_most\|null}`, `{business_id, service_weekdays\|null}`. `at_most` is 1 to 99 and must be named: an explicit null puts a group back to worked out and a department back to no limit. Answers with the limits as they stand after | groups and weekdays: the owner, the office overseer (not an Admin: section 7, item 7). A department: an office login whose person is its leader or its overseer, the owner, the office overseer, or the `serve_schedule` holder (an Admin holds every duty, so an Admin too) |
| `GET /church/schedule/days?business_id=&from=&to=` (93 days at most; from today for 62 when unnamed) | `{from, to, days: [{day, kind: 'service'\|'event'\|'protected', name, leaders: {away, at_most, full, who: [{contact_id, name}]}, office: {…}, departments: [{id, name, away, at_most, full}]}]}`. From the facts only: a waiting ask is not counted and not named. Only departments with a number are listed. On an `event` day `leaders` and `office` are null | as `limits` |
| `GET /church/schedule/protected-days?business_id=&from=&to=` (from today for a year when unnamed) | `{days: [{id, day, name}], can_change}` | as `limits` |
| `POST /church/schedule/protected-days` | `{business_id, day, name}` (today or later; a name of 80 at most). One row a date: naming a day again renames it. `{saved: {id, day, name}}` | the owner, the office overseer |
| `DELETE /church/schedule/protected-days/{id}?business_id=` | `{removed: {id, day, name}}`; 404 for one that isn't this church's | the owner, the office overseer |
| `GET /church/schedule/volunteers?business_id=&from=&to=` (**built**, read only; 93 days at most) | `{from, to, departments: [{id, name, at_most\|null, people, away: [{contact_id, name, starts_on, ends_on}], waiting: [{contact_id, name, starts_on, ends_on, flags}]}]}`. `away` is the department's own people's away dates (the facts). `waiting` holds only a volunteer's ask (`grp = volunteers`), never a leader's, and the read does not select a reason. Since S2-5 such asks exist: each is listed under the department it was filed under (the full one, else the serving team's own), and under none when that team hangs from no department | `serve_schedule` holders (so an Admin), the owner, the office overseer: every department. An office login whose person leads a department or is over it: that one. Anyone else: 403 |
| `GET /church/schedule/pairs?business_id=` (**built**, S2-4) | `{pairs: [{id, a: {contact_id, name, on_schedule}, b: {…}, note, in_force, created_at}], can_change}`, `a` the smaller id. `in_force` is false while either is off the leaders schedule (kept, and it does nothing) | the owner and the office overseer only (403 for anyone else: an Admin, a Manager who doesn't oversee the office, a department's leader, one of the pair) |
| `POST /church/schedule/pairs` (**built**, S2-4) | `{business_id, a_contact_id, b_contact_id, note?}`, either order. Two different people (400), both this church's own (400), both on the leaders schedule (400), a note of 140 at most (400); the same two again, either order, 409. `{saved: pair}` | as `GET` |
| `DELETE /church/schedule/pairs/{id}?business_id=` (**built**, S2-4) | `{removed: pair}`; 404 for one that isn't this church's | as `GET` |

What changes on step 1's routes once step 2 is there (**built**, S2-3):

- `POST /church/schedule/asks`: a planned ask past the number, or on a protected day, is saved as any other with `over_limit` and/or `protected_day` in `flags` and `to` the login `goes_up` gives. Never a refusal. Since S2-4 the same with `pair`, when the other of a pair in force has an away date, or an ask still waiting, on any of the same days.
- Every route that returns an ask (S2-4): `pair` is in `flags` and `excepted` only for those who read the reason (the asker, whoever it went to, the owner, the office overseer); the calendar's other readers get the ask without it.
- `POST /church/schedule/asks/{id}/answer`: 403 on a flagged ask for anyone who may not give its exception (the one it first went to, an Admin, and for a guarded asker the office overseer). A yes that runs into something new answers **409** with one of `church_schedule.WENT_UP` ("… It has gone to {name}, who can make an exception.") or `YOURS_NOW` ("… It's marked now. Say yes again to make an exception."), both starting with `FULL_NOW`; nothing is decided and the ask now carries the new flags. When what is new is a pair alone (S2-4), the same two endings start with `NEEDS_NOW` instead (`WENT_UP_NEEDS`, `YOURS_NEEDS`: "Those days have changed since this was asked, and they need an exception now…"), which never says there is a pair. A yes over a flag answers with `excepted` filled. The body takes `shown: [flag]`, the flags the screen showed as being in the way; a yes lands as an exception only when every flag it would be given over is in `shown` (absent = none shown), else the same 409 with nothing written. A yes to a flagged ask while the server can't tell whether step 2's tables are there is a **503**, nothing saved.

### 4.2 Member app

All `include_in_schema=False`, `_signed_in`, never the preview, `rate_limit.allow_strict("member_action", …)`, a 303 back to `/my/lead/dates?done=…|err=…`.

Every row is **built**: the first five in S1-5, the two commitments rows in S1-7.

| Route | Form | Who |
|---|---|---|
| `GET /my/lead/dates` (served by `member_portal_lead.serve`, never in the owner's preview) | `?done=` or `?err=`, a short code | on the leaders schedule, or with an ask waiting for their yes, or with asks of their own. Anyone else: a few plain words and a 404. Closed, or before the tables: the Lead tab's own 404 |
| `POST /my/lead/dates/ask` | `start, end, kind (time_off\|commitment), reason, cover (the id of someone on the schedule, or ''), cover_name`, and (step 2) `sure=yes` | on the leaders schedule. With step 2 there and no `sure`: when the days are full or protected **nothing is sent**, and the answer is the Dates page itself (200, never kept by a browser) with what they typed still in the form, what is in the way, the nearest open service days and who can make an exception. "Ask anyway" posts the same form with `sure=yes`; the other button posts it without, so changed days are looked at again. Goes back with `done=dt_asked_up` when it went up |
| `POST /my/lead/dates/cant` | `start (today on the church's clock by default), end, reason` | on the leaders schedule |
| `POST /my/lead/dates/{id}/withdraw` | | the asker |
| `POST /my/lead/dates/{id}/answer` | `ans (yes\|no), note` (the note is kept with a no only), `shown` (with a Yes: the flags its card showed, comma-separated) | it went to this person (or to the login this person is). A flagged ask: only the very person it went up to. Goes back with `done=dt_yes_x` for a yes over a flag, `err=dt_up` or `err=dt_yours` for a yes that didn't land (`err=dt_up_now` or `err=dt_yours_now` when what was new is a pair alone, S2-4) |
| `POST /my/lead/dates/commitments` (**built**, S1-7) | `label, weekday (1 to 7), often (weekly\|every_other\|month_1 … month_4\|month_last: the one list "How often" stands for the engine's pattern and nth), start (today when empty), until` | on the leaders schedule. Goes back with `done=dt_repeat`; a refusal is `err=dt_repeat_label`, `dt_repeat_days`, `dt_repeat_none`, `dt_repeat_many`, `dt_said` or `dt_not_on` |
| `POST /my/lead/dates/commitments/{id}/remove` (**built**, S1-7) | | theirs, as that person (the owner's own person and the office overseer's take off only their own here). `done=dt_repeat_off`, else `err=dt_gone` |

Every POST answers 404 while the switch is closed for the church or its tables aren't there (`church_schedule.on`), refuses another site's POST (and lets `Origin: null` from this address through, by `Sec-Fetch-Site`), and never writes in the owner's preview.

- Unchanged addresses with new behaviour (**built**, S1-6): `POST /my/serving/away` and `/my/serving/away/remove` (3.2). For someone on the leaders schedule the first asks instead of saving and goes back with `done=asked` or `done=asked_short`; the second takes the ask back when the date came from one. For everyone else both do what they always did. `POST /my/serving/cant` ("Can't make it" on a place they agreed to) is unchanged for everyone.
- Step 2 adds nothing new for volunteers: the same two routes; the team leader answers on `/my/lead/dates`. **Built** (S2-5): `POST /my/serving/away` for a volunteer whose day is full or who is on for it goes back with `done=vol_asked` (only the code rides in the address); `POST /my/serving/away/remove` with the id of their waiting ask takes it back (the chip's x). For every other Away both are what they always were.

---

## 5. The rules, as a decision table

**Definitions**
- `to` = `co.above(ch, person)[0]`, else the owner's login.
- "Told" = `church_schedule_tell` (built, S1-4; person: push and the church thread, email if no phone was reached; login: staff push and email). Once each, never with the reason or the note. A planned ask, an answer and the nudge wait out the church's quiet hours; "can't make it" and a take-back don't.
- "Hold" = `church_schedule.holds` (built, S1-6), so the scheduler won't ask them: on the board they read as away for those days, in the board's own words, and are never in its list of who is away. It fails open: a hold that couldn't be read holds nobody.
- "Opens their places" = `sunday_serving.open_places` (built, S1-6): each place they had already said yes to on a day inside the ask, still to come, is saved the way "Can't make it" saves one, with the note "Can't make it · Away". After the yes is written, never inside it.

### Step 1

| Who asks | When / kind | Goes to | Flags | Written | Told |
|---|---|---|---|---|---|
| Core leader (leaders group) | planned (start is at least `notice_days` out), time off or another commitment | `to` | none | ask `asked`; hold | `to`, outside quiet hours |
| same | short notice (inside the window) | `to` (the same person; not blocked) | `short_notice` | ask `asked`; hold | `to`; the words say "short notice" |
| same | can't make it, first day inside the church's notice days (two days at least, so today and tomorrow always work) | nobody decides | `short_notice` if so | ask, then settled yes with nobody in `decided_by`; `serve_away(ask_id, kind='cant')` | `to`, at once, quiet hours or not |
| same | can't make it, first day farther out than that | refused (400): it is planned, so it is asked for as time off | | nothing | |
| Office login's person (office group) | all three | as above; `to` comes from the office rule (a Manager: the office overseer, else the owner; an Admin or the office overseer: the owner) | as above | as above | as above |
| A leader who is also an office login | all three | routed as the login (`church_over.py:947`); counted in `leaders` | | | |
| On the add list | all three | `to`, as anyone's | | `grp` as listed | |
| The owner's own person (`Church.owner_person`, the one person the owner is) | any (a "can't make it" inside the same window as anyone's) | nobody is over them | none | ask settled yes at once; fact | nobody (7.5; the plan had the office overseer told for their information). It is on the calendar for everyone on the schedule |
| Someone else who carries the owner's sign-in email (a husband or wife on a family address; `church_over` puts them at the top too) | all three | the owner's login, as any ask with nobody else over it | as planned / short | as anyone's | the owner |
| On the remove list, or a volunteer | Serving, Away | none | none | plain `serve_away` row, exactly as today (no ask, `ask_id` null) | nobody |
| Core leader using Serving, Away (built, S1-6) | any day, even tomorrow: that form never makes a "can't make it" | `to` | as planned / short, and `serving` if so | an ask (`time_off`, no reason), not a row; hold | `to`; the page says "Asked", by name, with a way to Dates |
| The owner's own person using Serving, Away | | nobody is over them | `serving` if so | ask settled yes at once; fact (it names its ask) | nobody; the page says "Saved", as for anyone |
| Anyone whose ask says they already agreed to serve one of the days (built, S1-6) | any kind | as it would anyway | `+serving` | as it would anyway | as it would anyway; Dates says, while it waits, that a yes opens that place |

**Answers and withdrawals**

| Event | Written | Told |
|---|---|---|
| Yes (by `to`; in the office app also the owner or the office overseer) | settle yes: the fact is written, the hold becomes a fact; then, after the write, their places open (S1-6) | the asker. The team sees the place open on its board, as for any "Can't make it"; nobody is sent anything about it |
| A "can't make it", or the owner's own, settling at once | the same: fact, then their places open | as the table above |
| Not this one (optional note) | settle no: no fact, the hold ends | the asker |
| Withdraw by the asker (`asked` or `yes`) | settle withdrawn: the fact is deleted. A place that opened stays open | `to`, when they had been told of it (`told_at`); nobody otherwise. Sent once, never tried again (7.5) |
| The asker takes the away date off under Serving, Away (S1-6) | the same withdraw, through `withdraw_fact` | the same |
| Withdraw by the owner or the office overseer, in the office app | the same | the asker. Sent once, never tried again (7.5) |
| Still waiting three days after `to` was told | `nudged_at` | `to`, once; never a second, whoever it is sent on to |
| Two answers at once, or an answer after a withdraw | the RPC answers `changed: false`; the route returns 409 "That one was already answered" | |

**Refusals**
- A last day in the past, an end before the start, or more than 366 days: 400. (A first day already past is allowed while the last day isn't: they are away now.)
- The same dates already waiting: 409, from the read before the write and, for two presses at once, from `church_away_asks_one_open` (PostgREST's 23505).
- `MAX_OPEN` (20) already waiting: 400. Never for an ask that needs no yes: "can't make it" doesn't wait, so it is never one too many.
- Who covers is the asker, or isn't one of the church's people: 400. A typed name over 80 letters: 400.
- A reason over 500 characters: 400. A note with an answer over 300: 400.
- Someone who isn't on the schedule: 403 for themself, 400 when named with `for`.
- An answer from anyone it didn't go to (the owner and the office overseer aside), to your own ask, or (the owner aside) to one you entered: 403. An answer to one that needs no yes (a "can't make it", or the owner's own, left waiting by a failed settle): 409. A withdraw by anyone but the asker, the owner or the office overseer: 403.
- "Can't make it" whose first day is on or after today plus the church's notice days (two at least): 400, in words that point to asking for time off.
- A login that has left the office (its seat is no longer Admin or Manager) answering what went to that login: 403; it is the owner's.

**Standing commitments** (built, S1-7; 7.12)
- No yes is needed, and nothing blocks one: never a full day, never a pair, never counted toward a limit. Ten in force a person.
- `to` (whoever an ask of theirs would go to, worked out when the notice goes: the table keeps no `to`) is told once when one is added (`told_at`, claimed before the send and let go when nothing went), outside quiet hours, in who and which days and never what it is. Nobody for the owner's own person, nor when it would go to the very login that added it (saved as told). Taking one off tells nobody.
- They show on the calendar (`standing`, what it is only for those who read a reason) and hold the person from the scheduler on those days only (`holds`), in the board's words for an away date.

### Step 2

Computed in `flags_for` when asked, and again at yes. The leader and office rows, the protected
day row, the yes rows and the "can't make it" row are **built** (S2-2 and S2-3), the pair row
too (S2-4), and the volunteer rows (S2-5, `church_schedule_volunteers`; where they differ from
the rows as planned, 7.11 says).

| Case | Goes to | Flags | Written | Told |
|---|---|---|---|---|
| Core leader / office, every counted date under the group's limit, no protected day | as step 1 | as step 1 | as step 1 | as step 1 |
| A counted date already at the limit (facts for that group on that date, the asker's own aside, >= limit), or the same for their department when they are one of the people it counts | `goes_up`: the office overseer, else the owner. For a shepherd or a senior (`co.is_guarded`), or the office overseer themself: the owner. Never refused | `+over_limit` | ask `asked`; hold | `goes_up`, and nobody else (7.9: the plan also told step 1's `to` for their information) |
| A protected day in the range | `goes_up` | `+protected_day` | same | same. The Dates page names the day; the notice doesn't |
| The other of a pair (in force: both on the leaders schedule) has a fact or a waiting ask on any of the same days (**built**, S2-4). At the yes, only their waiting asks made before this one count (7.10) | `goes_up` | `+pair` | same | same; the notice adds "It overlaps with someone they can't be away with", no name. The asker sees "This overlaps with someone you can't be away with at the same time", never who or which days |
| A yes on a flagged ask | only someone who may give the exception: the owner, or the office overseer unless the asker is guarded (403 for anyone else). In the member app, only the very person it went up to | | settle yes through `church_away_settle_excepted`, with `p_excepted` = the ask's flags still true. None still true: a plain yes through `church_away_settle` | the asker |
| A yes on an ask that has run into something new since it was asked (a day filled, or was made a protected day) | the decider gets 409 in plain words; the ask takes the new flags and is re-addressed to `goes_up` (`to_*` changed, `told_at` cleared) unless it already sits with someone who may give the exception | the new flags added | still `asked`; nothing decided, no exception | `goes_up`, when it moved |
| Not this one on a flagged ask | as any ask that went to them | | settle no; no exception | the asker |
| Can't make it, or the owner's own time away, on any of the above | nobody decides; never blocked; **never looked at** | none of step 2's (7.9: the plan recorded them) | fact at once. It counts for the next person who asks | step 1's `to`, at once (the owner's own: nobody) |
| The dates hold no service date and no protected day (a Monday to Thursday trip) | as step 1 | never `over_limit` | | |
| Volunteer: none of their departments' dates full, and no yes to serve in the range (**built**) | none | none | plain `serve_away` row, instant, as today, byte for byte | nobody |
| Volunteer: a department's date is full (**built**) | the team's leader (`leader_of`: the team's own leaders, else the department's by `church_map.team_head`'s rule, else its leader or overseer, else whoever keeps Who serves when, else the owner) | `over_limit` | ask `grp='volunteers'`, `team_group_id`, `department_id`; hold | the leader ("That day is already full, so it came to you"); the page says who, and "that day is full for {department}" |
| Volunteer: already said yes to serve one of the days (**built**) | the leader of that place's team | `serving` (and `over_limit` if so) | same | same; the page links each such Sunday to `/my/serving?sub=<assignment>` ("Find someone to cover") |
| The team leader says yes (**built**) | | | a plain yes (no recheck, no exception, over the number too): fact; each of their yes places in the range still to come opened as `sunday_serving.cant_make_it` does (`open_places`, S1-6) | the volunteer, on My serving; Planning's own alerts tell the office |
| The team leader says not this one (**built**) | | | settle no, with the note | the volunteer; My serving says who said it, and the note, while the days are still to come |
| Volunteer, sick today | none | | they use Can't make it on the place itself (`ss.cant_make_it`, today's path); an away row for today stays instant | as today |
| Anything going wrong while a volunteer's Away is looked at (**built**) | none | none | plain `serve_away` row, instant, as always; one line logged (the church's id cut short) | nobody |

The sweep (S1-4) and a flagged ask (**built**, S2-3): it stays with whoever may give its
exception and is never sent back down to the nearest step. It is sent on, to `goes_up`, only
when the login it names has left the office, no longer gives the exception for that asker, or
is the asker's own.

### Which dates count ("service date")

**Built** (S2-2, `church_schedule_limits.picture`). For a range, in the church's own clock (`ch.tz`):
1. Every day with a live `worship_services` row of `kind='service'` (not a template, not archived). Before the event-date columns are there (`serve_dates.ready()`), every live row is a service.
2. For days with no such row: the church's usual service weekdays.
   - `settings.service_weekdays`; else
   - any weekday that holds its `kind='service'` rows on two days or more from 8 weeks back to 8 weeks ahead; else
   - Sunday (the platform's rule today, `sunday_planning.py:847`).
3. Every protected day.
4. A `kind='event'` date counts toward **department** limits only (only the Volunteers' teams serve it, `sunday_planning.py:902`).

Counting:
- The leaders and office limits count distinct people of that group, as the roster stands today, with a fact on the date.
- A department's limit counts distinct members of its Sunday teams (their leaders too).
- The asker's own away dates never count against them.
- "Full" is at the number: as many already away as may be.
- Waiting asks are neither counted nor shown (7.9: the plan showed "2 away, 1 waiting"); the recount at yes covers the gap.

---

## 6. PR split

Each was safe alone: `CHURCH_SCHEDULE` defaults to `owner`, `ready()` was False until the file was applied (2026-11-18, before S1-6 merged; since then it is True in production and each step is live at the platform owner's church), and `conftest` pins it off for every other suite.

### Step 1

| PR | Contains | Tests | Migration first? |
|---|---|---|---|
| **S1-1 Migration** (this doc's PR) | `APPLY-2026-11-19-church-schedule.sql`; `docs/MIGRATIONS.md` row; `EXPORT_EXCLUDED`; `__tests__/church_schedule_db.mjs` and the `ci.yml` line; `docs/CHURCH_SCHEDULE.md`; the worklog entry | PGlite, 152 checks: twice changes nothing, with rows there; the RPC (yes writes one fact, a second yes none, withdrawn deletes it, no leaves none, another church gets null, a bad or null state raises); `serve_away_ask_guard`; `church_away_asks_one_open`; the same-business triggers; a person or church deleted takes its rows, in either order the foreign keys fire; a login deleted leaves the ask; server-only under Supabase's default grants. `test_export_import` green | this is it. **Applied 2026-11-18** (run by the owner; checked with the file's Check block) |
| **S1-2 Switch and roster** (built, in one PR with S1-3) | `church_schedule.py`: switch, `ready`, the gate, `roster`, `roster_kept`, `set_listed`, `office_overseers`, `goes_to`; `GET status`, `GET/PUT people`; the `conftest` pin; `.env.example` | `test_church_schedule_roster.py` at the four churches: roster equals `leaders_room_people` split by `Church.person_login`, and `set(ch.person_login)` equals `mpm.office_contacts` (pinned as `Church.held` is to `standing`); someone in both counts in leaders; add / remove; Riverside is empty; `goes_to` for a department leader, a group leader with no role, a Manager, an Admin, a senior and the owner; `off` and other churches under `owner` get 404; before the migration 404; a failed read 503; `test_business_access_ratchet` green | no (404 until it was applied, 2026-11-18) |
| **S1-3 Asks** (built, in one PR with S1-2) | `ask`, `answer`, `withdraw`, `shape`, `mine`, `waiting`, `calendar`, settings; the `asks`, `leaders` and `settings` routes; no notices yet | `test_church_schedule.py`: every step-1 row of section 5 through the real routes; the RPC faked on `ThreeDB` (as `test_church_duties.py:77`); **privacy**: the reason is absent for another leader, for an Admin and for the `serve_schedule` holder, present for the asker, `to`, the owner and the office overseer; `serve_away.note` stays `''`; a failed write is a 503 with nothing saved; races give 409 | yes |
| **S1-4 Notices** (built) | `church_schedule_tell.py`; the hooks in `church_schedule.ask / answer / withdraw` (`_after`); the sweep job (with the one nudge after 3 days, the re-address and the 90-day clearing of reasons: section 7, items 1, 14, 15); `TICKS`; `.env.example` "both services"; `sb_patch_as_service(redact=)` | `test_church_schedule_tell.py`, at New Hope through the real routes and senders: no reason and no note in any push, email, conversation line or log line, and the words the same with or without them; nothing told inside a write, and a failed notice never fails it; person vs login channels; email only when no phone rang; `cant` ignores quiet hours, a planned ask and an answer wait; claim before send, let go when nothing went; told once (two sweeps at once, the write's notice and the sweep); a yes nobody gave tells nobody; `_login_email` None is not claimed; one nudge, never a second; a waiting ask is sent on when who is over them changes, their login leaves the office or it names nobody, never one that needs no yes, and never round the same step; the reason (and, since S1-5, the note that came with the answer), and only those, are gone 90 days after the last day; every read names its state and is paged (1,003 rows); take-backs; where a notice points; a sample church is told nothing; before the migration and with the switch off the sweep reads nothing; on `owner` one church is swept. Each rule was broken once to see its test go red (the PR lists them) | no (silent until it was applied, 2026-11-18) |
| **S1-5 Dates on the Lead tab** (built) | `member_portal_dates.py`; `church_schedule.section`, `waiting_kept`, `forget_waiting`; `member_portal_lead` (`DATES`, `_context`, `_seg`, `serve`); `member_portal._leads`; router include; `church_schedule_tell.MEMBER_PAGE` and the button's words; the sweep clears the answer's note with the reason | `test_member_portal_dates.py` (the `test_member_portal_assign` harness, at New Hope): the page and its order for a leader, for someone over people, for an office person with no role, for the owner's person, for someone taken off the schedule who is still over someone; no ids, no office words, no title words and no keys on screen; a reason and a note only where `shape()` allows, and never under Who else is away; every POST; preview never writes; cross-site refused, `Origin: null` allowed; closed or before the tables means no Dates entry and 404 writes; a member-app session never gets the owner's or the office overseer's across-the-board view, and every call into the engine is made as a person; every refusal comes back as plain words; who covers is the people on the schedule here, never the asker, 200 at most; days in the church's own clock; short notice said before and after and never blocked; real labels on every field; the switcher's count from what is kept a minute, with no read on a page view. `test_church_schedule_tell.py`: where a person's notice points, and the note cleared with the reason. Each rule was broken once to see its test go red (the PR lists them) | no (not there until it was applied, 2026-11-18) |
| **S1-6 Serving Away form and the scheduler hold** (built) | `church_schedule.holds`, `on_schedule`, `takes`, `withdraw_fact`, `_serving`, `_open_places`; `sunday_planning._Board` `held`; `sunday_serving.add_away / drop_away`, `yes_places`, `open_places`; `member_portal_serving` flash and line; `member_portal_dates._serving_line` | `test_sunday_planning_holds.py`, at New Hope through the real scheduler, engine and member routes: off, before the migration or closed the board makes exactly today's reads (the church looked up once, then kept); open it makes one more, selecting who and which days only; a read that fails, or anything else going wrong, holds nobody and is never a 503; 1,003 waiting asks are read in two pages and the read is bounded; a waiting ask makes `candidates` say away, an ask a 409 and a fill skip, for the office, a team's own leader, a teammate finding a sub and an event date; the board's words are the same for a waiting ask as for an away date, and nothing of the ask is in anything the scheduler answers; it is absent from `/planning/schedule`'s `away`; a volunteer's Away makes the same calls and the same page, byte for byte, open or closed, and against the commit this was cut from (that one is skipped where the commit isn't in the clone, as in CI); a leader's Away is asked for through the engine with its rules and never saved at once; under `owner`, whose church it is is asked once a minute even when it can't be read; when the roster can't be read again the last one read answers, and on a replica that never read one an Away is saved at once, as it always was, with one line logged that names nobody; "Can't make it" on a place is unchanged; taking off a date that came from an ask takes the ask back in one transaction, and a failure leaves both as they were; a plain date comes off as it always did; a yes opens their places exactly as `cant_make_it` does, after the write, and a failure there never fails the yes; a year of services is read a page at a time; no title word or role key in the rule code. `test_sunday_serving.py` passes untouched. Each rule was broken once to see its test go red (the PR lists them) | no. The schedule's own was applied before this merged, so it is live at the platform owner's church from its first deploy |
| **S1-7 Things that repeat** (built, #1990) | `church_schedule_repeats.py` (the commitments routes, `commitment_days`, `add_commitment`, `drop_commitment`, `commitments`, `sees_label`, `held_days`); `calendar` `standing`; `holds` adds the days; `church_schedule_tell.tell_repeat` and the sweep's read; the Dates part and its two routes; `church_schedule_fake` taught the table | `test_church_schedule_repeats.py`, at New Hope through the real routes: every week, every other week from its first day (a window opening on the off week, a start long ago), the first to the fourth and the last (in months with four and with five of that weekday), from and until, 366 days at most and the very end of the calendar, a row that can't be read; no yes, never an ask or an away date; ten in force, an ended one not counted; the same one twice is one; every refusal in plain words with nothing written; who adds (`for` as an ask's), reads the list and takes one off; the label read exactly where an ask's reason is, absent for everyone else, following whoever an ask would go to now; someone off the schedule is off the calendar; never counted toward a limit or a pair with step 2's file; closed, off or before the tables a 404 with nothing read; another church's never read or held; 1,003 read whole; no title word or role key. `test_sunday_planning_holds.py`: held on those days only, in the board's words for an away date and with nothing of what it is; byte for byte what it was with nothing of this church's in the window; a failed read still holds the asks, and a failed asks read reads nothing more; paged and bounded. `test_church_schedule_tell.py`: told once, never what it is, the same words whatever it is, as a login for an office person, quiet hours, a claim let go and tried for a week, nobody to tell, taking one off tells nobody. `test_member_portal_dates.py`: the part after My dates in plain words, Who else is away by name and days only, remove their own only (a member-app session is a person), refusals as the page's words, ten and the form gone, someone off the schedule keeps theirs, the owner's own; the preview, cross-site and closed sweeps now cover the two routes. Each rule was broken once to see its test go red (the PR lists them) | no. The table is in step 1's file, applied 2026-11-18 |
| S1-8 (optional) My week count | `church_my_week` `dates` | a login sees how many wait for their yes | yes |

**Turning on:** the migration is applied (2026-11-18), so the switch alone decides. `CHURCH_SCHEDULE` is read on **both** `kmj-intake-server` (the routes, and the notice that follows each write) and `kmj-intake-worker` (the hourly sweep). Unset means `owner` on both, so nothing needs setting for the platform owner's own church; to open it wider, or to close it, set the same value on both. The sweep also works only the churches `CHURCH_ASSIGNMENTS` is open for (7.5). The scheduler hold (S1-6) is read wherever a board is built: on the web service for every Planning and My serving page, and on the worker for the "No answer yet" note, which names who could take a place. So it too follows the value set on both.

### Step 2

| PR | Contains | Tests | Migration |
|---|---|---|---|
| **S2-1 Migration** (built, #1941) | `APPLY-2026-11-20-church-schedule-limits.sql`; `docs/MIGRATIONS.md` row; `EXPORT_EXCLUDED`; `__tests__/church_schedule_limits_db.mjs` and the `ci.yml` line; section 2.2 and 7.8 of this doc; the worklog entry. No Python | PGlite, 289 checks, over step 1's file with step 1 already in use: `church_away_settle` is the same function before and after (id, body, grants), and a session that had used it keeps working; every ask, away date and setting reads as it did, and `serve_away` is not touched; the writes the deployed code makes still pass; twice is a no-op, in any order with step 1's file, and leaves one function a name; the six-name call and the seven-name call (`church_away_settle_excepted`) both work; the new function gives the old one's answer for every state and every decision, saves an exception only on a yes it just made (each flag once, in order), and refuses a bad one by name with the yes undone; every constraint and trigger refused by a bad row and accepted by a good one (a pair is ordered and unique and never one person; one protected day a date; limits 1 to 99; weekdays a plain list of 1 to 7; another church's department, person or team refused); server-only under Supabase's default grants; a login, person, department, team or church deleted takes what it should, with a church's foreign keys firing both ways round; the file's Check block answers as it says and its Rollback block puts the catalog back as step 1 left it; the two ways not taken fail as the header says; step 1's own check passes unchanged with this file applied after it. Each rule was broken once to see the check go red (52). `test_export_import` green | this is it. **Applied 2026-11-18** (run by the owner; checked with the file's Check block) |
| **S2-2 Service days and limits** (built, #1943, in one PR with S2-3) | `church_schedule_limits.py`: `ready`, `picture`, `service_days`, `usual_weekdays`, `limit_for`, `away_on`, `department_people`, `may_set_limit`, `limits`, `set_limit`, `days`, `volunteers`; `GET/PUT limits`, `GET days`, `GET volunteers` (read only); the `conftest` pin; `church_schedule_fake` taught step 2's file | `test_church_schedule_limits.py`, at New Hope: the default is `max(1, n // 4)`; the church's own number replaces it and null puts it back; a number is 1 to 99; who may set each number (an Admin sets no church-wide number and no usual days; a department's by those who run it and whoever keeps Who serves when; from the member app, as a person, deferred); a Saturday church's weekdays worked out from its plans, once is not usual, the church's own replace them; a late-evening service is counted on the church's own day; a protected day counts and says its name; event dates count for departments only; who is away is counted from the facts, each person once; a waiting ask is never counted and never shown; 1,003 away dates, 1,003 plans and a team of 1,003 are read whole; a window too wide is refused before anything is read; every value in an address is quoted; a failed read is a 503; with step 1's file alone every route is a 404, the engine is step 1 key for key and nothing of step 2 is read. Each rule was broken once to see its test go red (the PR lists them) | no. Both were applied before this merged |
| **S2-3 Limit and protected days for leaders** (built, #1943, in one PR with S2-2) | `flags_of`, `flags_for`, `nearest_open`, `look`; `church_schedule.step2`, `flagged`, `gives_exception`, `goes_up`, `held_right`, `_recheck`, `_send_up`; `ask` / `answer` / `may_decide` / `shape` wired; the protected-days routes; `church_schedule_tell.up_words` and the sweep; the Dates page: the look before sending, the cards | `test_church_schedule_limits.py`: each step-2 leader row; never refused; at the number is full; a guarded person's flagged ask goes to the owner alone, and the office overseer's own; a department past its number; only someone who may give the exception says yes; `excepted` recorded in one transaction, kept by a yes taken back; the flags still true; the recheck at yes (past the number, a protected day, by someone who may give it, a second new flag), and "not this one" never rechecked; an ask entered for someone never goes up to whoever entered it; `cant` and the owner's own never flagged, never blocked, and still counted; a member-app session gives an exception only on an ask that went up to that very person; an Admin never gives one; a failed read is a 503 with nothing saved; a yes whose exception fails leaves nothing half made; two answers at once; no title word or role key. `test_church_schedule_tell.py`: a flagged ask's notice goes to whoever it went up to and adds only that it is past the number or on a protected day; the sweep never sends one back down, and sends it on only when it no longer sits with someone who may give the exception. `test_member_portal_dates.py`: before sending nothing is sent and the page says what is in the way, the nearest open days and who can make an exception, with what they typed still in the form; ask anyway; the card after; why it came, as a count and never a name; a protected day named; a yes that no longer lands in plain words; nobody gets an across-the-board view; with step 1 alone the page never looks. Each rule was broken once to see its test go red (the PR lists them) | no |
| **S2-4 Pairs** (built, #1948) | `church_schedule_limits`: `pairs`, `view_pairs`, `add_pair`, `drop_pair`, the pairs routes, `picture(who=)`, `Picture.pair_hits`, `flags_of`/`flags_for` (`+pair`, `before`), `nearest_open` without pairs; `church_schedule`: `shape` hides `pair`, `_recheck` with `before`, `NEEDS_NOW` and `_now_words`; `church_schedule_tell.up_words`; the Dates page's words and `_limits`; `church_schedule_fake` taught the table's update | `test_church_schedule_pairs.py`, at New Hope: only the owner and the office overseer read or change pairs (an Admin, a Manager who doesn't oversee the office, a department's leader, one of the pair and every member-app session refused); two different people of this church on the schedule, saved once, the smaller first, the same two a 409 (two at once too); another church's id refused and its pair not found; the second ask goes up and the first does not, on any day, from a guarded asker to the owner alone; a pair and a full day are one ask with both flags; the recheck catches a pair that arose after the ask (a new pair, the other's "can't make it"); a later waiting ask of the other never sends the first up; an exception over `pair` only when shown; a pair dropped before the yes is a plain yes; "can't make it" and the owner's own read no pair and count for the other; never named to the asker, never on the calendar for anyone who doesn't read the reason; the other's waiting ask never shown to anyone who may not read it; the nearest open days never give the other's days away; a pair with someone off the schedule does nothing and says so to the owner; with no pairs an ask and its yes each make one read more and nothing else changes, and nothing else reads one; a failed read is a 503; every value quoted; 1,003 pairs listed whole; the fake refuses as the SQL does; no title word or role key. `test_church_schedule_tell.py`: the notice says it overlaps with someone, never who or which days. `test_member_portal_dates.py`: before sending and on the asker's card, unnamed, never the other's days, said from the flag; whoever may give the exception reads who, and their Yes carries `pair`; anyone else with the card reads no name; a yes that no longer lands for a pair alone never says pair. Each rule was broken once to see its test go red (the PR lists them) | no. Both were applied before this merged |
| **S2-5 Volunteers** (built, #1951) | `church_schedule_volunteers.py` (`volunteer_plan`, `leader_of` / `team_step` for the plan's `team_leader`, `departments_of`, `ask`, `away`, `mine`, `take_back`, `stale`); `church_schedule.volunteer`, `flagged`, `answer`, `withdraw_fact`; the `add_away` branch; My serving's flash, chips and lines; Dates' card; the notices' words and where they open; the sweep | `test_church_schedule_volunteers.py`, at New Hope through the real engine, scheduler and member routes: a free date saved at once with the same write and the same page, byte for byte, at a church with departments and numbers set; a waiting ask never makes a day full; closed or before step 2 nothing reads; every read that fails, and anything at all going wrong, saves it at once with one line logged; serving and full each an ask to the team's leader, never the map's step over them, never instant, a second press the same ask; the chain for a team with no leader (`church_map.team_head`'s answer, then the department's leader, whoever keeps Who serves when, the owner), never themself; someone on the leaders schedule is never a volunteer here; the team leader's yes on Dates is a plain yes that writes the date and opens their places, over the number too; not this one with a note, and the reason and the note by `shape()`'s rule; the Dates entry for a team leader off the schedule; a member-app session is a person; "can't make it" unchanged; taking one back from My serving; the notice words, the claim, quiet hours, My serving as where the volunteer's notice opens; the sweep keeps it with the team and moves it with the team's leader; the hold and the board's words; GET volunteers; 1,003 groups; quoting; no title word; plain words. `test_sunday_planning_holds.py` (the byte-for-byte pin at an open church with numbers set), `test_member_portal_dates.py` (the card), `test_sunday_serving.py`. Each rule was broken once to see its test go red (the PR lists them) | no. Both were applied before this merged |

---

## 7. Decisions

Settled 2026-11-18. Two kinds, and the difference matters when one is questioned later:
**Kevin's** are his words, or a call he was shown and said yes to. **Decided in the build**
are calls the build made on the questions the spec left open; Kevin has not ruled on those,
and any of them can be reopened with him.

### 7.1 Kevin's

His words are at the top of this doc. On the five calls the plan rests on he said: **"Yes build
to all five"**. The five, as they were put to him:

1. **Who the core leaders are.** Pastors, elders, ministers, department leaders and overseers,
   plus the office admins as their own group. Any name can be added or removed.
2. **The number.** The leaders' number starts at about one in four away on any Sunday. Each
   department leader sets their own number with the volunteer coordinator.
3. **Volunteers.** They need no yes to be away, unless the date is full or they already agreed
   to serve it; then it goes to their team leader.
4. **Who says yes.** The person over a leader on the leaders map. Past the limit, or on a
   protected Sunday, only the owner or whoever oversees the office.
5. **Notice.** Two weeks' notice for planned time off. Sickness and emergencies are never
   blocked.

The code reads none of those titles: "pastors, elders, ministers" is who the church's own roles,
groups, departments and seats put on the schedule (section 3.1, `roster`).

### 7.2 Decided in the build

The numbers are the build spec's open questions, kept so the PRs ahead can cite them.

| # | Question | Decision |
|---|---|---|
| 0 | One Postgres function for the yes? | Yes: `church_away_settle` sets the ask and writes the fact in one transaction (section 2.1). |
| 1 | Several people at the nearest step above (`co.above` can return more than one) | The ask goes to the first, in the library's order. The owner and the office overseer can always answer in the office app. One nudge goes after 3 days. Naming all of them would widen who reads the reason. |
| 2 | A leader who also has an office login | Routed by the office rule (`church_over.py:947-948`); they still count in the `leaders` group. |
| 3 | A login matched to no person | A 409 in plain words, and `status.me.person` is null so the screen asks them to pick their record. Rule code never calls `seat_person`. |
| 4 | The owner's person may be unknown (`owner_how == 'none'`) | Before S1-5 is switched on for a church, the owner's person must be found (their sign-in email on their record, or `PUT /church/owner-person`). The lead session checks the first church's before S1-5 opens there. |
| 5 | The push kind | Reuse `serving` (it lands in the church conversation). Email whenever no phone was reached. A church with Serving alerts off gets email only. |
| 6 | The member app and a login's across-the-board power | A member-app session never carries the owner's or the office overseer's power. There, a person reads reasons and answers only asks that went to them, or to the login tied to exactly them. "Every ask and every reason" is the office routes only. |
| 7 | Admins | **Changed from the spec's recommendation.** Admins do **not** change the roster, the notice days, or the leaders and office numbers: those are the owner and whoever oversees the office only (what Kevin was shown said "set by you"). Admins still do not read reasons or answer asks unless one went to them. A department's number: its leader, its overseer, the owner, the office overseer, or the holder of the `serve_schedule` duty. |
| 8 | The office overseer and guarded people (step 2) | A flagged ask from a guarded person (a shepherd or a senior, `co.is_guarded`) goes to the owner only. |
| 9 | A department with no number set | No limit, so volunteers stay instant as today. The one-in-four default (`max(1, people // 4)`) applies to the leaders and office groups only. |
| 10 | A yes to a volunteer who already said yes to serve | It opens those places, as `sunday_serving.cant_make_it` does. It runs after the RPC, not in its transaction; failures are logged, and Planning's own "still no answer" alerts catch the rest. Built in S1-6 for every yes, not only a volunteer's (7.7), and nothing tries a failed one again: the alerts named here are about an ask nobody answered, not a yes from someone who is away. |
| 11 | Standing commitments and the limit | Shown, and they hold the person from the scheduler. Not counted toward a limit, never blocked. |
| 12 | `holds()` on a failed read | Fails open (returns `[]`), on purpose, and its docstring says why: the other choice is Who serves when failing whenever this table blips. The worst case is asking someone whose ask is still waiting. Built in S1-6. |
| 13 | Other readers of `serve_away` (`sunday_serving.mine`, `free_sundays`) | Left as they are: they don't see waiting asks, so a leader with a pending ask can still be shown an open place on their own page. (Pressing "I'll take it" there asks the board, which says they are away: 7.7.) `church_serving._sunday_spans` is left too: hours follow what was agreed, and a waiting ask isn't that. |
| 14 | Private reasons kept for good | The sweep clears `reason` 90 days after `ends_on` (built, S1-4). Reasons can be medical. Since S1-5 it clears `decided_note` with it: the note that came with an answer can say why, so it is as private (7.6). The ask and its answer stay. |
| 15 | Asks made before a role change | The sweep re-addresses a waiting ask whose `to` is no longer who `goes_to` gives, and clears `told_at` (built, S1-4). As built, "no longer" means no longer anyone at the nearest step over the asker (7.5). |
| 16 | Away dates written before the switch opened | A core leader's old instant `serve_away` rows have no ask. The calendar shows them as plain "away" with no kind, and `drop_away` deletes them as today. |
| 17 | Roster cost | Kept 60 seconds a replica for the member side; an add or remove on one replica can show up to a minute late on another. The office routes always read fresh. |
| 18 | Two clocks | `ch.tz` for "today" and notice; the scheduler keeps its own zone for the service day. |
| 19 | Step 2 drops and re-makes `church_away_settle` | **Reversed in S2-1 (7.8, section 2.2).** `church_away_settle` is not touched; the exception has a function of its own name, `church_away_settle_excepted`, which calls it. As first decided: kept, to avoid two functions for PostgREST to choose between, a six-argument call resolving through the new argument's default. That holds on the day, and stops holding the first time step 1's file is run again. |
| 20 | The name `church_away_asks` | Kept. This doc's header and the table's own comment say it is unrelated to `church_map_asks` and `member_asks`. |
| 21 | The office frontend | Comes after the backend. The route shapes in section 4 are its contract. Until it exists, a login's yes is reachable only through the member app as their own person, and the roster, settings and limits writes are API-only. |
| | Short notice | Flagged, never blocked, and it goes to the same person. |
| | "Can't make it" | Instant: nobody decides, and the person over them is told at once. For the days just ahead only (7.4). |

### 7.3 Decided while writing S1-1

Small, and all decided in the build:

- The seven changes to the draft SQL (section 2.1).
- The service weekdays (step 2) are set by the same people as the leaders and office numbers:
  the owner and the office overseer. Decision 7 names the numbers; the weekdays were grouped
  with them in the route table and are kept there. Confirm in S2-2.
- The office overseer is named among those who read `GET /church/schedule/volunteers`. The
  spec's row listed the owner and an Admin and left the overseer out; decision 6 gives the
  overseer every ask in the office routes.
- The sweep does not "settle again" a yes with no fact (section 3.1).

### 7.4 Decided while building S1-2 and S1-3

All decided in the build; none is Kevin's call, and any can be reopened with him.

- **One PR for S1-2 and S1-3.** The roster has no reader without asks, and the privacy rule is
  easier to check with both in view.
- **`member_portal_messaging.leading_people`** is new: the leaders room without the office,
  taken out of `leaders_room_people` (which is unchanged in what it reads and answers). The
  roster needs "leads something" on its own to tell a leader who also has an office login
  (counted in `leaders`, decision 2) from an office login who leads nothing.
- **`office_overseers` reads the Church's own rows** (`Church.over_lanes` for each Manager
  seat), not `church_duties.manager_holders`, whose answers are kept a minute a replica: who
  reads a private reason should not lag a duty that just moved. A test pins the two to the
  same answer at the four fixture churches. (`church_over.above` still asks
  `manager_holders` for where a Manager's ask goes; S1-4's re-address covers a stale one.)
- **Nobody answers their own ask**, whatever their standing: an office overseer's own ask
  goes to the owner, and only the owner (or a second overseer) says yes.
- **Nobody answers an ask they entered, the owner aside** (review of #1930). A login matched
  to no person could otherwise add its own record, ask for it with `for`, and say yes to it.
  An office overseer who enters an ask for someone leaves the yes to the person it went to,
  or the owner (or a second overseer).
- **Who takes one back** (decided by the lead session in the review of #1930): the asker, and
  in the office app the owner or whoever oversees the office. Having entered it (`made_by`)
  is not enough: a login that entered one and has since lost that standing can't withdraw it.
- **"The owner's own person" is one person**: `Church.owner_person`. `church_over` puts every
  contact carrying the owner's sign-in email at the top (`Church.top`), which is right for
  "never under anyone" and too wide for "needs no yes": a husband or wife on a family address
  asks as anyone does and it goes to the owner's login. Where the owner's person can't be
  told (two records on that email and none picked), nobody is instant until the church picks
  (decision 4).
- **A login has left the office when its seat is no longer an Admin or Manager seat**, not
  only when it has no seat. What went to that login is then the owner's: the login no longer
  finds it in `to_me`, reads its reason or answers it, in the office app or (as the person it
  is) in the member app.
- **An ask that needs no yes is never answered.** A "can't make it" (or the owner's own) can
  be left waiting only by a failed settle that also couldn't be deleted. It is in nobody's
  `to_me`, `can_answer` is false and `answer` is a 409; it settles when they ask for those
  days again, or they take it back.
- **The note that comes with an answer is as private as the reason.** It can say why, so
  `shape()` gives it only to those who read the reason.
- **Someone not on the schedule can't ask here.** A login whose person is off it gets a 403
  in plain words; the owner naming them with `for` gets a 400 ("add them first"). That
  includes the owner's own person at a church with nothing set up (Riverside in the tests):
  the owner adds their own name, as they add anyone's.
- **The owner's own ask carries no `short_notice` flag.** Nobody is over them to flag it for.
- **"Can't make it" still records who is over them** in `to_*`: nobody decides, and S1-4 tells
  that person at once. They read its reason, as "whoever it went to".
- **`MAX_OPEN` never blocks an ask that needs no yes** (sickness is never blocked), and it
  counts each person's own waiting asks.
- **A waiting ask is on nobody's calendar but those who may read it.** Everyone on the
  schedule sees approved away dates (name, days, who covers); a waiting ask shows only to the
  asker, whoever it went to, the owner and the office overseer. Planning already works that
  way (section 1.1).
- **The calendar lists the people on the schedule today.** An away date of someone since
  taken off it isn't shown, and each one is under the person's group as it is now, not the
  `grp` kept on the ask.
- **An ask whose `to` login has left the office is the owner's** to answer (and shows in the
  owner's `to_me`), until S1-4's sweep re-addresses it (decision 15).
- **Once an ask is a no or taken back, the one it went to has no list that shows it.** It
  stays on the asker's own list, and in `all` for the two who see every ask; the calendar
  never shows it. The review of #1930 read this as the more private choice, and it stays.
  Say so if a "what I answered" list is ever wanted.
- **Withdrawing has no date limit.** Taking back a yes whose days have passed deletes that
  away date, as `sunday_serving.drop_away` already can.
- **`for` takes `person:<id>` only**, never `login:<id>`.
- **`ready()` reads "no such table"** as Postgres's `42P01` or PostgREST's `PGRST205` (a 404).
  Neither was seen against production; the check is `church_away_asks?select=id&limit=1`.
- **"Can't make it" is for the days just ahead** (decided by the lead session in the review
  of #1930, from Kevin's fifth call: "two weeks' notice for planned time off; sickness and
  emergencies are never blocked"). Anything farther out than the church's notice days is
  planned, so it is asked for: a `cant` whose first day is on or after today plus the notice
  days is a 400 that points to asking for time off. Inside the window it is instant as
  before, never counted and never blocked. With the notice days set to 0 it still works for
  today and tomorrow (a floor of two days). The owner's own is held to the same window (their
  time off is instant anyway).
- **Two presses of "can't make it" at once end as one ask and one away date** (review of
  #1930): see section 3.1.
- **Days at the very end of the calendar** are a 400 on the calendar route, never a 500. An
  ask for such days is taken like any other (nothing in `ask` adds to a day the caller gave).

### 7.5 Decided while building S1-4

All decided in the build unless it says the lead session; none is Kevin's call, and any can be
reopened with him.

- **Taking back** (decided by the lead session, in the brief for S1-4; not the pastor's call).
  When the asker takes back an ask that whoever it went to had already been told of, that
  person is told. When the owner or whoever oversees the office takes back someone's ask, the
  asker is told. Both are sent straight after the write and never tried again: there is no
  column to claim them and no migration was added. The plan's "`to`, only if it had been a
  yes" is replaced by this.
- **When the owner or the office overseer takes one back, whoever it went to is not told.**
  The lead session's rule names the asker only. It leaves that person's list quietly. Say so
  if they should hear too.
- **The owner's own time away tells nobody.** The plan's table had the office overseer told
  "for their information"; the brief for S1-4 said a yes that needed nobody tells nobody, and
  that is the quieter of the two. It is on the calendar for everyone on the schedule, and in
  `all` for the office overseer.
- **"Can't make it" tells the person over them and nobody else.** The one who pressed it gets
  no answer notice, nor does someone the office entered one for.
- **What a notice says.** A new ask: "Marcus asked for Dec 20 to 27", with "Short notice."
  when it is. "Can't make it": "Marcus can't make it Dec 20". Time off and another commitment
  read the same: the kind can hint at the reason. An answer says who answered and whether it
  was a yes or "not this one"; never that a note came with it. The words are the same whether
  or not a reason or a note was given (a test holds them equal).
- **First names on a lock screen, the whole name in the email.** The owner is called by the
  church's own name for them (`practitioner_name`). A login with no name to say is "The church
  office", never a stand-in and never part of an email address.
- **An answer and the nudge wait out quiet hours too**, as a planned ask does; the sweep sends
  them. Only "can't make it" (at once: section 5's table) and a take-back (no column, so no
  later try) go whatever the hour.
- **Who is reached as a login.** `to_user_id` always. The asker: the owner's login when they
  are the one person the owner is, their office login when their person has one (an Admin or
  Manager seat), else as one of the church's people. A leader on a Member seat is told in the
  member app, as a person.
- **A person with a phone is told in the church's conversation and by push; the email goes
  only when no phone was reached** (a church with Serving alerts off, or the person turned
  them off, gets the email). The line in the conversation is written once however many tries
  it takes (`member_push`'s own once-a-`ref` log).
- **Nothing could be sent** means no phone was reached and no email went (none on file, or it
  failed). The claim is let go and the sweep tries each hour while the ask still waits and its
  last day hasn't passed. Someone with no phone and no address is tried each hour until then;
  the ask is still on the owner's and the office overseer's list.
- **A login with no address on file is told by push alone**, and that counts as told. A login
  whose address couldn't be read is not told this time and nothing is claimed.
- **Sent on only when it has left the nearest step.** Decision 15 said "no longer who
  `goes_to` gives". `goes_to` is the first of those at the nearest step, in an order two reads
  can disagree on (holders invited at the same moment, the order of seats). As built, an ask
  stays where it is while its `to` is still one of them (`church_schedule.nearest`), and is
  sent on (to `goes_to`'s answer) only when it is none of them, a login that has left the
  office, or empty. Sending it round the step would tell two people in turn and widen who
  reads the reason (decision 1).
- **One nudge an ask, for good.** Counted from when whoever it went to was told (`told_at`),
  not from when it was asked: an ask sent on to someone new isn't nudged the same hour. Once
  an ask has been nudged it is never nudged again, whoever it is sent on to.
- **An ask whose last day has passed is left alone**: not sent on, not told, not nudged. It
  still waits for whoever opens it. An untold "can't make it" is told by the sweep until its
  last day has passed.
- **An untold answer is tried for a week** (`ANSWER_DAYS`), then left. An answer whose decider
  can no longer be named (both `decided_by` columns empty) is never told: that is also what a
  yes nobody gave looks like.
- **The sweep leaves an ask under two minutes old** to the notice its own write handed on.
  Either way one of them wins the claim.
- **The sweep follows `CHURCH_ASSIGNMENTS` as well as `CHURCH_SCHEDULE`.** It works the
  churches `church_assignments._open_churches()` gives (the brief's rule) that
  `church_schedule.church_open` also says yes to. With `CHURCH_ASSIGNMENTS=off` nothing is
  swept; the notice that follows a write still goes. `.env.example` says so.
- **A notice goes only where the church's own switch is open** (`church_schedule.on`), not
  where only the platform owner's login is (`open_to`): a write he makes at someone else's
  church tells nobody there.
- **Only `reason` is cleared at 90 days.** `decided_note` is as private as the reason and
  stays: the brief said only the reason. Say so if the note should go with it. **Changed in
  S1-5** (the lead session, in the review of #1934): the note goes with the reason (7.6).
- **Where a notice points.** A person: `{the church's site}/my/lead` in the email and
  `/my/lead` in the conversation (the Lead tab's front page, the nearest page leaders have
  today). A login: the office app (`church_office_tasks._link`), and the push opens My week
  (`church_assignments.NAV`). Neither place shows the ask yet. **S1-5 moved the person's link
  to the Dates page** (`MEMBER_PAGE`, one constant: now `/my/lead/dates`, where the ask is on
  the screen); the login's moves when the office screen exists.
- **`sb_clients.sb_patch_as_service` takes `redact=`**, as the GET and the POST already did.
  Every update this module makes to `church_away_asks` uses it, and asks back for `id` only.
- **`church_schedule.nearest`** is new and `goes_to` is its first row: what `goes_to` answers
  is unchanged.
- **The tells answer with a word** (`told`, `held`, `taken`, `unsent`, `unread`, `none`,
  `closed`) where the plan had `None`, for the sweep's counts and the tests.

### 7.6 Decided while building S1-5

All decided in the build unless it says the lead session; none is Kevin's call, and any can be
reopened with him.

- **The answer's note is cleared with the reason, 90 days after the last day** (decided by the
  lead session, in the review of #1934; it replaces 7.5's "only the reason"). The sweep's read
  finds an ask that still holds either (`church_schedule_tell.PRIVATE`), so a note with no
  reason is found, and the write clears both, naming the same rule again. `cleared` counts
  asks, not texts.
- **The switcher's count is kept a minute too.** The brief asked for the kept roster and no
  fresh read on a Lead-tab view; `member_portal._leads` asks on every page of the app, for
  every member. So how many asks wait for each person is kept beside the roster
  (`waiting_kept`: one paged read a church a minute a replica, of who and how many, never a
  reason or a note), and `section` answers from the two with no read of its own. A write on a
  replica forgets its count at once (`_after`); on another replica "Dates · 1" can lag a
  minute. The Dates page itself always shows what it just read.
- **The count is `waiting()`'s rule for a person**: the ask names them, or the office login
  tied to exactly them; never their own, never one that needs no yes. A test holds the two
  equal for everyone on the schedule.
- **`section` asks about the tables first** (`ready()`, kept), then the switch: before the
  migration nothing else is read, and no other test suite gains a read.
- **`section` never raises.** Every page of the member app waits on it (through `_leads`), so
  whatever goes wrong there is one logged line and no Dates entry, never a broken page. The
  two kept maps are walked as copies: page views ask from many threads at once.
- **What is kept decides the switcher and the tab, never the page.** `/my/lead/dates` reads
  fresh. Someone with nothing of theirs there (not on the schedule, nothing waiting for their
  yes, no asks of their own) who follows a link gets a few plain words and a 404. While the
  switch is closed for the church, or before its tables, it is not a page at all: the Lead tab
  answers as it does for any address it doesn't know.
- **Someone taken off the schedule who is still over someone** keeps a Dates entry while an ask
  waits for their yes, and sees only that (and any asks of their own): no forms, no "Who else
  is away".
- **Who covers is picked from the people on the leaders schedule**, not from the whole church:
  by name, never the asker, 200 at most (`PICK_MAX`), their names read a hundred at a time.
  Anyone else (a volunteer, say) is typed as a name. The member route refuses a picked id that
  isn't on the schedule; the engine and the office route still take any of the church's
  people. A church's whole list is never sent to a leader's phone.
- **"Who else is away" says a name, the days and who covers.** Never the kind: time off,
  another commitment and "can't make it" read the same there, as they do on a lock screen
  (7.5), because the kind can hint at the reason. Two months ahead, one list, not by group.
  An ask waiting for the reader's own yes is in it, marked so; nobody else's waiting ask is.
- **Once an ask is answered, the one who answered no longer has its reason on this page.**
  `shape()` would still give it to them; the page has no place that shows it (they read it
  while it waited). The asker keeps their own reason, and the note that came with the answer,
  under My dates.
- **My dates reads the fact.** A yes whose away date was taken off since (Serving, Away, until
  S1-6) is shown as "Off the calendar" with no button to take it back, never as away.
- **A note goes with "not this one" only.** The form offers it there, and the member route
  drops a note sent with a yes.
- **"Can't make it" with no day named is today**, on the church's own clock. `/ask` takes time
  off or another commitment; "can't make it" has its own route.
- **Short notice is said on a planned ask only**, before it is sent (one line under the form,
  with the church's own number of days) and right after (the words that follow the press, and
  a mark on the ask). A "can't make it" is never marked short: it always is.
- **The page's own words for a refusal**, by a short code (`_code`, `ERRORS`): the engine's
  sentences name "the owner, or whoever oversees the office", which the member app doesn't
  say. Someone not on the schedule reads "The church office can add you."
- **Nothing on the page says the reason is cleared after 90 days, and it doesn't say an answer
  "will be told".** Both depend on the sweep and on someone having a phone or an address. The
  one such line is on "I can't make it": "{name} is let know."
- **Who reads a reason, as the page says it**: "{who it goes to} can read this, and so can
  those who look after the whole church. Nobody else who sees your dates can." Those are the
  owner and whoever oversees the office, in the office app, without a title.
- **No role names in the page's header.** The other Lead pages show the person's roles as
  chips; this one says nothing by title. The one title that can appear is inside the church's
  own name for its owner (`practitioner_name`), where an ask goes to them, as on the
  Assignments page.
- **The switcher scrolls inside itself only when Dates is in it** (`ld-seg fit`). Six entries
  don't fit a phone; the class is added only for someone with a Dates entry, so nobody else's
  Lead tab changes by a pixel.
- **With nothing else to lead, `/my/lead` opens on Dates**, as it opens on tasks for someone
  with only tasks.
- **A notice's words are unchanged.** Only where a person's notice opens (`MEMBER_PAGE`) and
  the email's button ("Open your dates") moved: every sentence already described what the page
  now does. A login's notice still opens the office app, which has no screen for it yet.
- **Tests run at New Hope**, the made-up church of 500: Love City's fixture carries real
  names, and this page's tests and pictures use none.

### 7.7 Decided while building S1-6

All decided in the build unless it says the lead session; none is Kevin's call, and any can be
reopened with him. Where a choice had to be made that the plan and the brief didn't settle, the
one that changes the least for volunteers was taken.

**The scheduler's hold**

- **Who is held**: everyone with an ask still `asked` at the church that touches the board's
  days, whoever they are. Someone since taken off the schedule, and a "can't make it" left
  waiting by a failed settle, are held too: they asked for the days.
- **The order it asks in** is the switch (no read), then the tables (kept ten minutes), then
  the church: off, or before the migration, not even the church is looked up (`_here`). Under
  `owner`, a church that isn't the platform owner's costs one lookup, then nothing. Open, it is
  one read a board.
- **Whose church it is, is kept a minute even when it couldn't be read.** Under `owner` that
  answer comes from the sign-in service (`member_asks.platform_church`), which keeps only an
  answer it could read; when it can't, it asks again every time, and each try can take ten
  seconds. The scheduler, the Serve page and the Away form ask through `_here`, which keeps
  the answer a minute a replica whatever it was. A lookup that failed reads as closed, as it
  always has: for that minute, at the platform owner's church, nobody is held and a leader's
  Away is saved at once, which is what happened before this PR.
- **The hold's read waits as long as any of the board's reads can** (the client's own
  timeout). Nothing shorter was added for it.
- **Bounded**: a page of 1,000, five pages at most. A church with more than 5,000 asks waiting
  in one window holds the first 5,000 it read. A page that fails holds nobody (decision 12).
- **Everything that asks the board gets the hold**, with no change of its own: the office's
  routes, a team's own leader (`sunday_leading`), the member's side (taking an offered place,
  saying yes to cover for someone, the list of who could be a sub), an event date
  (`serve_dates`), and the worker's "No answer yet" note, which names who could take the
  place. So the switch is read on the worker for this too.
- **Not held, on purpose**: `sunday_serving.mine`'s open spots and `free_sundays` (decision
  13: they read their own away dates; pressing "I'll take it" then asks the board and is
  refused in the board's words), and `church_serving._sunday_spans` (hours follow what was
  agreed; a waiting ask isn't that).
- **"Away" in `candidates`, absent from the schedule's `away` list** (the lead session, in the
  brief for S1-6). The two can differ for the same person on the same day. Someone who
  compares them could guess that something is waiting; the list stays what was agreed.
- **A teammate reads it too.** The brief names a team's leader and whoever plans; someone
  looking for a sub on My serving reads the same "Away that day" for a held person. It is the
  board's word, and it says no more to them than to a leader.
- **What `_Board.away` selects is unchanged** (an unpaged read of the window's away dates, as
  before this PR). It isn't made worse here and isn't fixed here.

**The Serving Away form**

- **Who "on the leaders schedule" is, at a church where it is open**: the roster as S1-2
  built it. Everyone who leads a group is on it, a Sunday team's own leader included, with
  the holders of a role that leads, each department's leader and overseer, and the office
  logins' people. So a team's leader who also serves is asked for under Away, not saved at
  once. That follows from the roster, not from anything decided here; it is said here because
  it is the first place a team's leader will meet it. **It stands as built** (the lead
  session, in the review of #1938): a read-only count at the platform owner's church on
  2026-11-18 found nobody there who leads only a small group, so the list there is the people
  with a role on the leaders map, the department leaders and overseers, and the office
  logins.
- **A blip never stands between a volunteer and their Away.** The roster is kept a minute;
  when the minute is up and it can't be read again, the last one this replica read answers
  (`_LAST`), however old. Someone added to the schedule since then is still saved at once
  until it can be read; someone on it is still asked for (and the engine, which reads fresh,
  answers "try again").
- **A volunteer's Away never fails because of this** (decided by the lead session, in the
  review of #1938; it replaces what the build first did, a 503 and "try again"). On a replica
  that has never read the church's roster and can't read it now, it can't be told who is
  asking, and `takes` answers "not on the leaders schedule": the Away is saved at once,
  exactly as it always was. The cost is that in that one corner a leader's Away from the
  Serve page is saved at once too, which is what happened before the leaders schedule and
  harms nothing. One line is logged each time (the church, never a name). The page's
  leaders line isn't shown there either: it is shown only on a yes.
- **Taking an away date off reads the row first** at a church where it is open: one read
  more than before for a volunteer, then the same delete. If that read fails they read "try
  again" and nothing is removed.
- **The roster is the one kept a minute** (the lead session, in the brief). On another
  replica, someone added to the schedule in the last minute can still get an away date at
  once; someone taken off it is found out by the engine (which reads fresh) and their Away is
  saved as anyone's is.
- **That form always asks for time off**, whatever the day, tomorrow included: short notice
  is flagged and it goes to the same person. It never makes a "can't make it" (which needs no
  yes): that is its own button, under Dates, and the line under Away says so. No reason is
  asked for there, and none is saved.
- **The one person the church's owner is** is set at once, by the engine's own rule, and reads
  "Saved. Nobody asks you on those days." as anyone does. The date names its ask.
- **What they read after pressing Save**: "Asked. {name} will say yes or not this one, and
  with a yes these days go on your away days." (or, short notice: "Asked. It's short notice,
  so {name} may need a little time with it. With a yes these days go on your away days."),
  with "See it under Dates". Only a short code rides in the address; the name is read on that
  one page view, from their newest waiting ask, and the words stand without it when it can't
  be read.
- **One line under Away** for someone on the leaders schedule: "You're on the leaders
  schedule, so away days you add here go through your Dates page. That's where you see the
  answer, take one back, or say you can't make it." It is true for the owner's own person
  too, so nothing is read to tell them apart.
- **A waiting ask is not shown under Away** on My serving: that list stays the away dates.
  The flash and the line send them to Dates, where it is. (Step 2 puts a volunteer's waiting
  ask beside the away dates.)
- **`on_schedule`** is new: the kept roster as three answers (yes, no, couldn't tell), never
  raising. A page asks it and shows the leaders' part only on yes; a write asks `takes`.

**Taking an away date off**

- **It goes through `withdraw()` as the person**, so its rules hold and whoever it went to is
  told as for any take-back (7.5). A "can't make it" date taken off is taken back the same
  way.
- **A date whose ask is gone or already settled is a plain date**: it comes off as any does,
  and nothing is settled twice. (The tables don't make such a row; one left by hand would
  otherwise never come off.)
- **A failure removes nothing**: a 503, the date and its ask as they were.
- **Closed for the church, it is still the plain delete** (section 2.1): no read is made to
  find out whether the date had an ask. Unchanged from the plan.

**A yes opens the places they had agreed to serve**

- **For every yes, not only a volunteer's.** Decision 10 was written for step 2's volunteers;
  the brief asked for it now. A leader or someone in the office who also serves on a team is
  the case in step 1.
- **In the request, straight after the write**, not on a thread of its own: by the time the
  one who said yes reads "You said yes", the team's board already shows the gap. It is
  wrapped so that nothing in it can fail the yes; a failure is one logged line (no name, no
  reason) and **is not tried again by anything**. Say so if the hourly sweep should.
- **Only a place that is a yes**, on a service still to come, whose day (on the scheduler's
  own clock, decision 18) is inside the ask. A place they were asked for and never answered
  is left for them to answer, as it is today when a volunteer adds away dates.
- **Saved exactly as "Can't make it" saves one** (`sunday_serving._opened`, now shared), with
  "Away" for why: status no, the note "Can't make it · Away", and a cover request they had
  sent is dropped, as that button drops it. The team reads the board's own words and never
  that it was asked for, what kind, or why.
- **Nobody is sent anything when a place opens.** "Can't make it" sends nothing either; the
  team's leader and the office see it on the board.
- **Taking the yes back doesn't put them back** on a place that opened. Whoever schedules
  asks them again.
- **The `serving` flag** is set when asked, for anyone with a yes place inside the days, and
  not worked out again at the yes (the opening reads for itself). A read that fails while
  asking leaves the flag off and never costs anyone their ask.
- **Dates says it before the yes.** While an ask that carries `serving` waits, the one it
  went to reads "{first name} said yes to serve on one of these days. With your yes, that
  place opens again for their team.", and the one who asked reads the same of their own.
  New words on a page that was built in S1-5.

**Tests**

- **"Byte for byte what it is on origin/main"** is pinned twice. The lasting test renders a
  volunteer's My serving with the schedule open, off, and before its tables, and holds the
  three equal (and a leader's equal to it but for the one line). The other reads
  `member_portal_serving.py` and `sunday_serving.py` out of git at the commit S1-6 was cut
  from (`4ee7e90a`), renders main's page and this one, and holds them equal. CI checks out a
  single commit, so that one is **skipped in CI** and runs on a full clone. It should be
  deleted the first time My serving is changed on purpose for everyone.
- **Tests run at New Hope**, as S1-5's do.

### 7.8 Decided while writing S2-1 (#1941)

All decided in the build; none is the owner's call, and any can be reopened. The file is
`supabase/APPLY-2026-11-20-church-schedule-limits.sql`; section 2.2 is the map of it. Every
difference from the draft that section 2.2 used to hold:

**The decision function**

1. **`church_away_settle` is not dropped and re-made; the exception has a function of its own
   name.** This reverses decision 19. The draft dropped the six-argument function and made a
   seven-argument one of the same name. That works on the day and leaves a trap: step 1's file
   is safe to run twice and makes the six-argument function again, and two functions of one
   name where one only adds a defaulted argument make Postgres refuse every six-argument call
   ("is not unique"; PGRST203 from PostgREST). The check runs both. With two names, no order
   of running the two files leaves two functions for one name, and the function the live code
   calls is the same function before and after (same id, body and grants).
2. **`church_away_settle_excepted` calls `church_away_settle`** instead of repeating its body
   with one more column. One place makes the decision, so the two can't drift apart. The
   exception is saved after the yes, in the same statement, so a refusal undoes the yes.
3. **A bad exception is refused by name.** In the draft the only refusal was the table's check
   constraint, with a message nobody would read as "that isn't one of this ask's flags" (the
   same reasoning as S1-1's null state). The constraint still stands behind it for any other
   writer.
4. **The exception is saved each flag once, in order**, whatever was passed (a flag twice, a
   list of lists).
5. **A no leaves `excepted` alone** rather than writing `'{}'` over it. It is `'{}'` on every
   waiting ask already, and the constraint below keeps it so.

**The tables**

6. **`church_away_asks_excepted` also says where an exception may sit**: only on a `yes`, or
   on a `withdrawn` ask (a yes taken back keeps it). The draft allowed one on a waiting ask or
   a no, where it means nothing and would be counted by anything that lists exceptions.
7. **`service_weekdays` is a plain list**: `array_ndims = 1` beside the draft's two tests. A
   list of lists passed both of those.
8. **The person who set a department's number is the church's own.** The draft checked the
   department and not `set_by_contact_id`; the trigger now checks both and also fires when
   that column is updated.
9. **Each trigger check runs only when a write names what it checks**, as step 1's do. The
   draft looked the department and the pair up again on every fire. With `set_by_contact_id`
   in the trigger's columns, a person's delete sets it null, which is an update: checked this
   way it can never refuse a delete, whichever way round a church's foreign keys fire (the
   check deletes a church both ways).
10. **The pair's refusal reads "A pair is two people in this church"** (the draft: "Both
    people are this church's own"), since it is also what someone paired with themself gets,
    before `church_away_pairs_ordered` is reached.
11. **A comment on the pair's note** (private, like the pair) **and on the new function.**

**The file**

12. **Its date is 2026-11-20**, and its header says to run it after step 1's file.
13. **The header names nobody**: the owner's words are given as the platform owner's.
14. **The header no longer says the function is "dropped and made again"**; it says what was
    chosen, the two ways turned down, and that nothing is dropped.
15. **Full Check and Rollback blocks**, where the draft had one line. The Check block's
    answers are stated (three tables, five columns, four validated constraints, two functions
    with one a name, no exception yet); the check runs both blocks as written.

**Kept as drafted, on purpose**

- **The three checks and the foreign key are validated as they go in**, not `NOT VALID` as
  step 1's two on `serve_away` were. `church_away_asks` and `church_schedule_settings` are
  days old and open at one church; every row passes (the new columns are `'{}'` or null); and a
  validated constraint is one nobody has to come back for.
- **A limit is 1 to 99.** Nothing here can say "nobody may be away" with a 0; a protected day
  is how a church says that.
- **`team_group_id` is not tied to `grp = 'volunteers'`** and the team's kind is not checked:
  S2-5 writes it, and nothing here should refuse what it turns out to need.
- **No table for which dates count.** Worked out in Python (section 5).
- **All three new tables are left out of the export** (section 2.3).

**Left open for the PRs ahead**

- **A "can't make it" with flags.** `church_away_settle_excepted` does not ask who is
  answering, so it never refuses a yes nobody gave, with or without an exception: nothing in
  the database can block a "can't make it". Whether S2-3 records an exception on one (nobody
  gave it) or leaves `excepted` empty and lets the flags speak is S2-3's call; the column's
  comment says `decided_by` says who gave it, which argues for leaving it empty. **Settled in
  S2-3 (7.9):** a "can't make it" is never looked at, so it carries no step 2 flag and no
  exception, and settles through `church_away_settle` as it always did.
- **Step 2's own "is it there yet"** (section 2.2): `ready()` can't tell whether this file has
  been applied. **Built in S2-2:** `church_schedule_limits.ready()`.
- **A real PostgREST was not run.** The check calls both functions by argument names on a
  real Postgres, which is the call PostgREST makes, and there is one function a name, so
  PostgREST has nothing to choose between. What PostgREST does with two of one name
  (PGRST203) is from its documentation, not from a run here; the "is not unique" refusal from
  Postgres itself is from a run.

### 7.9 Decided while building S2-2 and S2-3 (#1943)

All decided in the build unless it says the lead session; none is the owner's call, and any can
be reopened with him. Where the plan and the brief didn't settle something, the more private
choice was taken, and the one that blocks nobody.

**One PR, and where things live**

- **S2-2 and S2-3 are one PR** (the lead session, in the brief). The numbers have no reader
  without the rule that uses them.
- **Who may give an exception lives in `church_schedule.py`**, not in the limits module where
  the plan had `goes_up`: `may_decide`, the sweep and the notices all ask it from the row alone,
  with nothing of step 2 read. `church_schedule_limits.py` holds the numbers, the days and
  `flags_for`.
- **`flags_for` takes no group.** The plan's signature had one; the group is the asker's on the
  roster as it stands, at the ask and again at the yes.
- **`church_schedule.calendar` is unchanged.** The plan had it carry counts a service date;
  those are `GET /church/schedule/days`, so step 1's route answers exactly what it did.
- **Step 2's check is `church_protected_days`** (the file is one transaction, so one table says
  all of it), asked only where the switch is open and step 1 is there. On a replica's first
  minute after a read that couldn't tell, an ask is made as in step 1: one on a full day goes to
  the one over the asker unflagged, and the recheck catches it at a yes made on a replica that
  can tell. A yes to an ask that is already flagged, on a replica that can't tell, is a 503 with
  nothing saved (from the review of #1943): it would otherwise land as a plain yes over a full
  day with no exception on record. Flagged asks exist only where step 2 is applied, so a
  database with step 1's file alone never meets it.

**Which days count, and who is counted**

- **"Two or more" is two days or more.** Two services on one Saturday (a conference) don't make
  Saturday a usual day; a service on two Saturdays does.
- **A department's number counts the members of its Sunday teams** (the plan's words), and a
  team is found two ways: as one of the department's groups, or by name as one of its Serve
  options. A team's own leaders are members. **A leader is held to a department's number only
  when they are one of the people it counts.** The department's leader or overseer who is on
  none of its teams is not counted by its number and not flagged by it; the leaders number is
  what holds them. Say so if a department's own leader should count toward its number.
- **The asker's own away dates never count against them**: someone already away that Sunday
  doesn't make it fuller by asking again.
- **Full is at the number**: with two allowed and two away, the third ask is flagged.
- **The group counted is the roster as it stands**, not the group kept on old asks: someone
  since taken off the schedule is no longer counted.
- **A waiting ask is neither counted nor shown** (the lead session, in the brief; it replaces
  the plan's "2 away, 1 waiting"). A count that included one would tell everyone on the
  schedule that someone has asked. So three people can be waiting on a Sunday that takes two:
  the first yeses land, and the next yes is caught by the recheck.
- **`GET days` names who is away** for the leaders and the office (`who`), to the people who
  already see them on the calendar, and gives a department's count without names.
- **A window is bounded**: three months on `days` and `volunteers`; a year and eight weeks
  either side (`PICTURE_DAYS`) for anything an ask reads. One row a day at most for protected
  days; the plans, the away dates and a team's people are read a page at a time.

**Who sets what**

- **The usual service days are the owner's and the office overseer's**, with the two numbers
  (7.3 said to confirm it here).
- **An Admin can set a department's number**, because an Admin holds every duty and the rule
  says the `serve_schedule` holder may (decision 7). An Admin still sets no church-wide number,
  no usual days and no protected day.
- **A department's leader or overseer sets its number as an office login whose person they
  are** (a leader on a Member seat too). From the member app, as a person, is deferred, as the
  plan said.
- **`at_most` must be named.** `{group: "leaders"}` alone is a 400; only an explicit null puts
  a number back. A missing key should never clear a church's number.
- **A protected day is today or later**, named again it is renamed (one row a date), and
  anyone who reads the numbers reads the days.

**An ask that runs into the limit**

- **"Can't make it" and the owner's own time away are never looked at**, so they carry no
  `over_limit` or `protected_day` flag and no exception (the lead session, in the brief; the
  plan recorded the flags). They read nothing of step 2. Their away dates count for the next
  person who asks.
- **Only whoever it went up to is told.** The plan also told the one over the asker "for their
  information". There is no column to claim that notice, they can no longer answer it or read
  its reason, and the brief names only whoever it went up to; they see the days on the calendar
  once it is a yes. Say so if they should hear.
- **The one it first went to no longer answers a flagged ask, or reads its reason.** `to`
  moves, and `sees_reason` follows `to` as it always has.
- **An ask entered for someone never goes up to whoever entered it** (they can't answer it,
  7.4). With one office overseer who entered it, it goes to the owner.
- **A second office overseer may give the exception** on the first one's own flagged ask, as
  in step 1; it is addressed to the owner.
- **The exception is the ask's flags that are still true at the yes.** A flagged ask whose
  days have cleared is a plain yes through `church_away_settle`, by the same person: the flag
  stays on the ask as what was true when it was asked, and it is not sent back down.
- **A yes on an ask that has run into something new never lands the first time, whoever
  presses it**, the owner included: the ask is marked, and their second yes is the exception.
  Nobody gives an exception without having been shown that it is one. The same when an ask
  that was already flagged meets a second flag.
- **The recheck is not a lock.** Two yeses in the same moment for two different people can
  both land and put a Sunday one over. The database decides one ask at a time; nothing counts
  across asks inside a transaction. Accepted for now by the lead session (one church; `GET
  days` shows the day over its number when it happens). The later fix is a recount under an
  advisory lock (per church and day) inside `church_away_settle_excepted` and `church_away_settle`.

**From the review of #1943** (the lead session; each pinned by a test that went red with the
fix taken out)

- **An ask that already sits with someone who may give the exception stays with them,
  flagged before or not.** The recheck used to keep only an already-flagged ask in place, so
  an Admin's ask sitting with the owner was sent to the office overseer the moment its day
  filled, and the owner's next yes was a 403: he was locked out of an exception that was his.
  Now `held_right` alone decides: it is marked where it is, nobody is told, and the holder's
  next yes is the exception. (A second line, "the login `goes_up` gives is the one it already
  names: nothing moves, nobody is told again", is kept as a guard; with `held_right` before it
  no case reaches it today, so no test can make it matter.)
- **The hourly sweep knows who entered an ask.** `made_by` is in `church_schedule_tell.FIELDS`
  for the sweep's own use (it is in no notice's words) and is passed to `goes_up`, so a flagged
  ask is never sent on to the login that entered it.
- **Nobody gives an exception they were not shown.** A yes carries the flags the screen showed
  as being in the way (the Dates page posts them with its Yes as `shown`; the office route takes
  `shown` in its body; nothing said is none shown). A yes lands as an exception only when every
  flag it would be given over is among them; otherwise it is the same 409 with nothing written.
  So a double tap of Yes, whose second press was on its way when the first marked the ask, does
  not land an exception nobody saw. A yes with nothing to except, "not this one" and a take-back
  never ask what was shown. The office frontend must post `shown` with every Yes it draws.
- **`away_on(..., department_id)` reads that department's own people**, number or not. It used
  to read from a picture that holds a department's away dates only when it has a number, and so
  answered "nobody" for one without.
- **"Not this one" is never rechecked**, and a yes taken back keeps the exception it was given
  (the table's own rule).
- **The Serving Away form** (S1-6) asks through the same engine, so a leader's Away there on a
  full day is flagged and goes up with no look first. That page is unchanged; its line already
  sends them to Dates, where the card says why.

**The Dates page**

- **"Before sending" is a second press, not a script.** The page has no script. "Ask for these
  days" on days that are full or protected sends nothing: the page comes back, as the answer to
  that press, with what they typed still in the form, and says "Not sent yet" at its top (the
  form can be below what waits for their yes). What they typed never rides in an address
  (a reason is private), which is why it is not a redirect; the answer carries the member
  app's own no-store headers. A refresh asks the browser to send the form again, and looks
  again.
- **Two buttons then**: "Ask anyway" (sends it, `sure=yes`), and "I changed the days. Ask for
  those" (the same form without it, so new days are looked at again).
- **What it says**: each full or protected day, the first three and then how many more; "Sun,
  Dec 20 is full: two of the leaders are already away, and that's as many as can be away at
  once."; "Thu, Dec 24 is a protected day (Christmas Eve)."; the nearest open service days
  either side, when there are any within eight weeks; and "It goes to {name}, who can make an
  exception.", by the church's own name for them.
- **A count, never a name**, on the look and on both cards. Who is away is under Who else is
  away for those who may see it.
- **The cards are worked out when the page is read**, from the facts as they stand, not kept
  on the ask: one whose days have cleared says there is room now, and that a yes is a plain
  yes.
- **"A protected day"** is what the page and the notice call it, as the owner was shown it.
- **A yes that didn't land** comes back as the page's own words by a short code (`dt_up`,
  `dt_yours`); the engine's sentence names who it went to, and the page's doesn't need to.
- **On a database with step 1 alone the page never looks** and is byte for byte step 1's.

**The notices**

- **A flagged ask's notice adds one clause**: "It's past the number who can be away at once",
  "It's on a protected day", or both, "so it came to you". Never how many, never who, never
  which day, and the protected day's name is left to the page.
- **The sweep on a database with step 1 alone** asks nothing of step 2: whether an ask went up
  is read from its own flags.

**Tests**

- **`church_schedule_fake.build(limits=False)` is the default**, a database with step 1's file
  alone that refuses everything step 2 adds. Every step 1 suite runs on it with not a line
  changed but the two fixtures that now take `limits`.
- **The fake's `patch` now runs the ask's checks** (flags, one `to`, `church_away_asks_excepted`)
  on the row as it would stand after.
- **Tests run at New Hope**, as S1-5's and S1-6's do.

**Open for the lead session or the owner**

- Whether the one over the asker should hear that their ask went up (above).
- Whether a department's own leader counts toward its number (above).
- The office app has no screen for the numbers, the days or the protected days: they are set
  through the API until the office frontend exists (decision 21).
- Nothing tells a leader whose waiting ask sits on a day that has since been made protected,
  until someone says yes to it.

### 7.10 Decided while building S2-4 (#1948)

All decided in the build unless it says the lead session; none is the owner's call, and any can
be reopened with him. Where the plan and the brief didn't settle something, the more private
choice was taken, and the one that blocks nobody.

**Where things live, and who**

- **Pairs live in `church_schedule_limits.py`**, with step 2's other reads and routes, behind
  step 2's own check: on a database with step 1's file alone the routes are a 404 and nothing of
  a pair is read. `pairs(ch)` is the internal reader (every pair, a page at a time);
  `view_pairs(ch, me)` is the `GET`; `add_pair`, `drop_pair`.
- **`DELETE` takes the pair's id in the address** (`DELETE /church/schedule/pairs/{id}?business_id=`),
  as protected days do. The plan's row gave only a body.
- **Reading is the owner's and the office overseer's alone** (`over_all`), as the brief said: an
  Admin, a Manager who doesn't oversee the office, a department's leader on any seat, one of the
  pair, and every member-app session (a person, whoever it is) get a 403, for reading, adding and
  removing alike. The answer carries `can_change: true` (whoever reads may change), kept for the
  shape of the other routes.

**What a pair is**

- **Two different people (400), both this church's own (400, by the same read and the same words
  as who covers), both on the leaders schedule when it is made (400), and a note of 140 letters at
  most** (spaces folded to one line). The smaller id first, as lower-case text. The same two again,
  either way round, are a 409 "Those two are already a pair.": a read before the write, and the
  table's own uniqueness (23505) for two presses at once. The note is sent redacted, and no card,
  notice or log line has it.
- **Someone later taken off the schedule (the brief's question): the pair is kept, and does
  nothing.** A pair is in force only while both people are on the leaders schedule as it stands
  today. While either is off it, no ask of the other is flagged by it, and the owner's list shows
  it with `in_force: false` and which of them is off. Put back, it is in force again. Nothing is
  deleted on its own and nobody is told. Someone leaves the schedule in many ways that never pass
  through this module (a group they led closes, a role ends, the owner takes them off), so "kept
  and quiet" is the one rule that holds for all of them, and it says nothing to anyone. The owner
  or the overseer takes it off when they want it gone.

**What counts**

- **Any of the same days**, not only the days that count for the limit: section 5's row said "any
  of the same days", and a pair is about two people, not a Sunday's numbers. A Tuesday counts.
- **The other's away dates are the facts in `serve_away`, whatever made them**: a yes, a "can't
  make it", the owner's own, a plain away date from the Serve page. They are already in the
  picture (the other is on the schedule), so a pair adds no read of the facts.
- **First asked, first answered.** At the ask (and the look before sending) every waiting ask of
  the other counts. At the yes (the recheck), only their waiting asks made before this one count,
  by `created_at` (the same moment counts, and a moment that can't be read counts). Without this,
  the second asker's waiting ask would send the first asker's ask up too at its yes: both would
  sit with the office overseer, and the first asker would be held up by something they couldn't
  see, and then told on their card that someone had asked since. With it, exactly the second ask
  goes up, as the plan's test row says. An away date counts whenever it was made: once the first
  is a yes, the second's yes needs the exception.
- **A pair taken off before the yes** is not found by the recheck, and the yes is a plain one (the
  flag stays on the ask as what was true when it was asked), as for a day that cleared.
- **One read of pairs an ask**: the asker's, both columns at once, a page at a time, at the ask, at
  the look before sending and at the yes. The other's waiting asks are read only when there is a
  pair in force. No pair is read for "can't make it", the owner's own, "not this one", `GET days`,
  `GET limits`, the calendar, or a Dates page with nothing flagged. "No read at all where the
  church has no pairs" would need a kept "this church has pairs" answer, a minute stale on the
  other replicas, so an ask in that minute would miss a pair just made; one bounded read was
  chosen over that. Pinned: with no pairs, an ask and its yes each read exactly what S2-3 read,
  and the one pairs read.

**Private**

- **The `pair` flag is shown only to those who read the reason** (`shape`: the asker, whoever it
  went to, the owner and the office overseer). Everyone else who sees the ask on the calendar sees
  it without `pair`, in `flags` and in `excepted`: "this person is in a pair" is the pair, and the
  plan didn't say. The other of the pair is one of those who don't see it.
- **The one asking is told it in these words alone**: "This overlaps with someone you can't be
  away with at the same time." Never who, never which days are the other's, never what kind.
  Before sending, `why` holds `{"flag": "pair"}` and nothing else, and no nearest open days are
  offered for a pair alone (they would be guesses about the other's time away). Where a day is
  also full or protected, the nearest open days are worked out without pairs: skipping the days
  the other is away would say which days those are.
- **The asker's card says it from the ask's own flag and never works it out again**: whatever
  happens to the other's time away afterwards (taken back, answered) never reaches them. The full
  and protected parts of the card still follow the facts, as in S2-3.
- **"Why it came to you" names the other only on a card the reader may answer** (`can_answer`). In
  the member app that is the owner's person, or the person of whoever oversees the office, on an
  ask that went up to them; both may read every ask and every pair in the office app. "It overlaps
  with time away for Esther Moss, someone they can't be away with at the same time." It never says
  which days are the other's, or whether theirs is a yes or still waiting. Anyone else who has the
  card (one that sits with someone who can't give its exception, until the sweep sends it on)
  reads "It overlaps with someone they can't be away with at the same time." The pair's note is on
  no card.
- **The notice**: "It overlaps with someone they can't be away with, so it came to you." With the
  other flags, one sentence: "It's past the number who can be away at once, and overlaps with…",
  "It's on a protected day, and overlaps with…", or all three. No name, no days.
- **A yes that no longer lands because of a pair alone never says "pair"**: whoever pressed it may
  be the one over the asker, who doesn't read pairs. It reads `NEEDS_NOW` ("Those days have
  changed since this was asked, and they need an exception now. Your yes didn't go through.")
  with the usual two endings (`WENT_UP_NEEDS`, `YOURS_NEEDS`), and on Dates the codes
  `dt_up_now` and `dt_yours_now`. Where a full or protected day is new too, S2-3's words stand,
  unchanged. The same for a yes refused because `pair` wasn't shown.
- **The privacy edge (the lead session, in the brief): telling the asker "this overlaps" when the
  other has only a waiting ask says that someone they can't be away with has something waiting on
  those days.** Accepted, in the unnamed form only, as the brief allowed: it is the least the
  asker must be told for the flag to make sense, and nothing else of the other's waiting ask (who,
  which days, what kind, its reason, where it stands) reaches anyone who may not already read it.
  Accepted with it, and written down: someone who presses "Ask for these days" over and over on
  different days (each look sends nothing) could narrow down which days the other is away or
  waiting, and match the approved ones against the calendar. Nothing here stops that; it would
  take a limit on looks, a later call.

**Left as it is**

- **An overlap with the office overseer's own time away goes up to the overseer**, as any flagged
  ask does (`goes_up` is unchanged): they decide on an overlap with their own absence, as they
  already do for a day that is full partly because they are away.
- **The office app has no screen for pairs**; they are set through the API until the office
  frontend exists (decision 21).
- **The fake** (`church_schedule_fake`) now runs the table's before trigger, its ordering check,
  the note's length and its uniqueness, in Postgres's order, on an update as well as an insert.

**Open for the lead session or the owner**

- Whether an ask that overlaps the office overseer's own time away should go to the owner.
- Whether looks before sending should be limited (the probing above).

### 7.11 Decided while building S2-5 (#1951)

All decided in the build unless it says the lead session; none is the owner's call, and any can
be reopened with him. His call 3 is the rule: "Volunteers need no yes to be away, unless the date
is full or they already agreed to serve it; then it goes to their team leader." Where the plan
and the brief didn't settle something, the choice that changes the least for volunteers was
taken, and the one that blocks nobody.

**Where things live, and who is a volunteer**

- **The rules are a module of their own**, `church_schedule_volunteers.py`, beside the engine and
  the limit, with no route of its own: the Serve page, Dates and the sweep call it. The plan's
  `team_leader` is built as `leader_of` (and `team_step`, everyone at its first step): that word
  is a role key, and the title-words rule keeps role keys out of rule code.
- **A volunteer is anyone the kept roster says is not on the leaders schedule**
  (`church_schedule.on_schedule` is False). A replica that can't tell saves the Away at once, as
  S1-6 decided; someone taken off the schedule inside the minute the roster is kept is saved at
  once too (S1-6's corner), and is a volunteer from the next minute.
- **Only where step 2's tables are there.** `team_group_id` is step 2's column, so the rules ask
  `step2()` first (after the switch, the tables and the church, each kept): with step 1's file
  alone, or the switch closed, a volunteer's Away is exactly what it was and nothing is read.

**Full, and already serving**

- **Their departments** are the active departments their Sunday teams hang from, found the two
  ways S2-2 counts a department's people (as one of its groups, or by name as one of its Serve
  options). A department with no number never makes a day full (decision 9).
- **Full is S2-3's count, for their departments alone**: away dates that were agreed, each person
  once, their own never against them, at the number, on the days that count for a department
  (the services, the usual weekdays, the event dates). **A protected day and a pair are the
  leaders' rules and are not looked at for a volunteer** (call 3 names a full date and agreeing to
  serve, nothing else). Say so if a protected day should send a volunteer's Away to their team's
  leader too.
- **Already serving** is a place they said yes to on a day inside the days, still to come
  (`sunday_serving.yes_places`, the very places a yes opens). A place they were asked for and
  never answered doesn't count, as it doesn't for a leader (7.7).
- **The team concerned** is the team of the soonest place they said yes to; with none, their first
  team (by name) in the first full department (the church's order). The ask is filed under the
  full department where there is one (the serving team's own when that one is full), else under
  the serving team's own department, and under none when that team hangs from none. `GET
  /church/schedule/volunteers` lists an ask under the department it was filed under, so one filed
  under none is in no department's list there (it still waits on the team leader's Dates, and on
  the owner's list).

**Who it goes to**

- **The chain**, nearest first, everyone at the first step that has anyone (the brief asked for it
  written down): (1) the team's own leaders, by name; (2) the department it hangs from: its
  leader while they hold a role that leads, else its overseer while they hold one that oversees
  (`church_map.team_head`'s rule from #1719, applied however the team hangs from it); (3) that
  department's leader, else its overseer, whatever they hold; (4) whoever keeps Who serves when:
  the Manager logins holding the `serve_schedule` duty (an Admin holds every duty by its seat and
  is not picked for it); (5) the owner. Never the volunteer themself at any step, and never the
  leaders map's step over the volunteer (`church_over.above`), which knows nothing of their team.
- **The first of the step** gets it, as decision 1 does for a leader's ask; the owner and the office
  overseer can always answer in the office app.
- **A person is asked as a person** (`to_contact_id`), even one with an office login, so they
  answer on Dates in the member app and their notice opens Dates. Steps 4 and 5 are logins.

**The ask**

- **It is never "flagged"** (`church_schedule.volunteer`; `flagged()` is false for it), so it never
  goes up: the brief's "goes up like a leader's only if the doc says so", and section 5's rows send
  it to the team's leader. **The team's leader says a plain yes over the department's number for
  their own team** (the simpler, less blocking option the brief named): no recheck at the yes, no
  exception recorded (`excepted` stays empty), no `shown` on its Yes. `over_limit` on the ask
  says the day was full when they asked; `GET days` shows the department over its number from the
  facts once it is a yes. Say so if a volunteer's yes over the number should be saved as an
  exception, or go up to the owner or the office overseer.
- **No short notice for a volunteer.** The notice days are the leaders' (call 5); the Serve page
  never asked a volunteer for notice, and the flag would read as a complaint on the leader's card.
- **What is written**: time off (the Serve page's Away has no kind), no reason (it asks for none),
  `made_by` empty, `grp` volunteers, `team_group_id`, `department_id`, `to`, the flags, in one
  insert sent redacted.
- **A second press of the same days answers with the ask already waiting**, never a second (two
  presses at once end as one, by the table's own uniqueness). Twenty waiting is a 400 in the
  engine's own words, as twenty away dates is today: the one refusal kept.
- **A volunteer's Away never fails because of this** (the lead session's standing rule from S1-6):
  every read the rules make (the teams, the numbers, the away dates they count, the places, the
  map, the asks, who is on the schedule) that fails, the ask's own write failing, or anything else
  at all, saves it at once, as always, with one line logged that carries the church's id cut short
  and nothing else. Only the Away's own reads and write, as they always were, can still fail it.

**What the volunteer reads**

- **After Save**: "Sent to {name}, because you're on the schedule that day. With a yes these days go
  on your away days." ("that day is full for Kids", "you're on the schedule on one of those days,
  and one of them is full for Kids"), with "Find someone to cover Dec 20" for each Sunday inside
  the days they were on for (three at most, none that already has a cover asked). Only the short
  code (`done=vol_asked`) rides in the address; the name, the department and the days are read on
  that page view from their newest waiting ask. Their own reasons only, never anyone else's.
- **Under Away**, beside their away dates: each ask still waiting as "Dec 18 – 25 · waiting for
  {name}", with the same x to take it back (it posts the ask's id to the same route; an id that
  names no away date of theirs is looked up as their waiting ask, only where step 2 is there).
  A "not this one" whose days are still to come says who said it, and their note (the asker reads
  it, by `shape()`'s rule). A yes is an away date like any other there, and taking it off takes
  the ask back (S1-6).
- **One bounded read more on My serving** where the rules reach (their own asks, 50 at most,
  through `shape()` as that person), and the church's whole row when there is one to show (the
  member app's church row, from `member_portal`'s site row, carries no owner, so an ask that went
  to the owner would otherwise read as "waiting for a yes"); none where they don't. With no such
  ask the page is what it
  always was, byte for byte (pinned open against closed at a church with numbers set, and against
  main's own page where that commit is in the clone).
- **The Lead tab's own serve-only page** (`/my/lead` for someone whose only part is serving) shows
  neither the chips nor the flash, as it never showed the leaders' part either; its Away goes
  back to My serving, which does.
- **A volunteer who opens Dates by a link** sees their own asks under My dates, with why it went to
  whoever it went to, and "They're on My serving too." in place of the line for someone over
  people.

**What the team's leader reads**

- **On Dates**, under Waiting for your yes (the entry is theirs while it waits, on the leaders
  schedule or not, from the kept count): "Why it came to you": "{first name} is on the schedule to
  serve on one of these days." and/or the full day by the day and the department's name ("Sun,
  Dec 20 is full for Kids."), worked out when the page is read, never a count and never who is
  away (changed in review: a department's numbers are read only by office logins, and with a
  number of one a count says who); then "Your yes is all it needs." S1-6's line about the place
  that opens stands beside it. The volunteer's own card on Dates says it the same way.

**Who is told**

- **The team's leader**: "{first name} asked for Dec 20", then "They're on the schedule to serve
  that day, so it came to you." or "That day is already full, so it came to you." Never which
  department, how many, who else, a reason or a note. A planned ask's quiet hours, its claim
  (`told_at`) and its one nudge, as for a leader's ask.
- **The volunteer**: the answer in their page's words ("It's on your away days now.", "Open My
  serving to see it."), and their notice opens My serving (`SERVING_PAGE`; the email's button
  says "Open My serving"). A take-back by the owner or the office overseer opens it too.
- `church_schedule_tell.FIELDS` gains `grp` and `department_id` (step 1's columns, in no notice's
  words), so a row handed to a notice says whether it is a volunteer's.

**The sweep and the hold**

- **A volunteer's waiting ask is its team's**: the sweep leaves it while its `to` is still one of
  those at the first step of its team's chain, and sends it on only along that chain (when `to`
  is empty, a login that has left the office, or no longer one of them); never to the leaders
  map's step over the volunteer, never round the same step. The sweep's read of waiting asks names
  `team_group_id` only where step 2 is there, and a volunteer's ask read without that column is
  left where it is (added in review: a replica whose first look at step 2 blips would otherwise
  skip the team's own leaders, move the ask to the department's head, and move it back the next
  hour, telling each).
- **The hold is unchanged**: it already holds everyone with an ask still waiting, so a volunteer
  is not asked to serve those days, the board says "away" in its own words, and they are never in
  `/planning/schedule`'s list of who is away.

**Tests**

- **`test_church_schedule_volunteers.py`** at New Hope, with three made-up Sunday teams (Kids
  Check-in hung from Kids by name, with a leader of its own; the Worship Team with none; the
  Parking Team with no department); Kids may have one away at once. Its member-app pages and
  routes are handed the church row as the member app has it (no owner on it). The byte-for-byte
  pin at an open church with numbers set is in `test_sunday_planning_holds.py`, beside S1-6's.

**Open for the lead session or the owner**

- Whether a volunteer's yes over the number should be saved as an exception, or go up.
- Whether a protected day, or the notice days, should apply to a volunteer's Away.
- A volunteer's ask filed under no department is in no department's `GET volunteers` list.
- A "not this one" leaves them on the place they had said yes to; nothing more tells their team's
  leader to find a sub (the leader can, from the team's Sundays).
- The office app's Leaders' dates screen (FE #1639) lists the leaders' asks: an ask that went to
  whoever keeps Who serves when, or to the owner, is answered in the member app by that login's
  own person (on Dates), or through the office routes.
- **Found while building, FIXED in this PR from review (S1-5 and S1-6's code):** the member app
  hands the engine the church row from `member_portal._site_row`, which embeds the business
  without `owner_id`, and `member_portal_dates._ch_me` built `church_over.Church` from it, so
  `ch.owner` was empty on every Dates page and write, and in the Serve page's ask for a leader
  (`sunday_serving._ask_away`): an ask whose `to` is the owner's login was not "theirs" to the
  owner's own person on Dates, `nearest` and `goes_up` couldn't fall back to the owner, and the
  owner's own time away from the member app was not instant. Every earlier test built the church
  from the whole row, so none saw it. `_ch_me` now takes the whole row
  (`church_schedule._own_row`, one read when the row handed in has no owner; a read that fails
  keeps the row as handed in). The session is still a person: it reads and answers only what
  went to it (the person-session tests now run on the member app's row and still hold).

**From the review of #1951**

An independent review found no leak and no way for a volunteer's Away to fail. Fixed, each with a
test that goes red when the fix is taken out:

1. The sweep leaves a volunteer's ask read without `team_group_id` where it is (above).
2. Dates takes the church's whole row, so an ask at the chain's last step (the owner) can be
   answered: before, nobody could answer it in any screen, and it held the volunteer until its
   days passed (above).
3. A volunteer's card on Dates, theirs and their team leader's, names the full day and the
   department, never a count (above).
4. An Away for days ending today stays instant, whatever they said yes to later today: the code
   now matches the decision table's "Volunteer, sick today". Before, a place at 7 PM made a
   morning's sick day an ask, and at night its notice waited out quiet hours.
5. My serving never shows a volunteer a stand-in for a name ("The owner", "An office login"); it
   says "your team's leader" instead (`member_portal_serving._vol_named`, the same stand-ins
   `church_schedule_tell._NO_NAME` keeps out of notices).

Seen and left as they are:

- A login with no person and no seat name is still named by its email's part before the @
  (`Church.login_name`), on My serving as everywhere: seats are made with names, so this needs a
  seat with none.
- The double-press check matches the person's waiting ask in any group. The unique index
  (`church_away_asks_one_open`) ignores the group too, so matching only volunteers' asks would
  only turn the same case into a refused write and an instant save. Someone moved off the
  leaders schedule while their leaders' ask for the same days waits gets "sent" with that ask.
- If the ask's write lands but its answer is lost, `away()` falls back and saves at once too; a
  later yes adds a second away row for the same days. That comes with the never-fail rule.
- A leader's yes opens the volunteer's places (S1-6's `open_places`), which clears a cover
  request still waiting for an answer; a cover already accepted is safe (the place has moved).

### 7.12 Decided while building S1-7 (#1990)

All decided in the build; none is the owner's call, and any can be reopened with him. His calls
that bind it are 7.1's item 11 as the plan wrote it (shown, they hold the person from the
scheduler, never counted toward a limit, never blocked). Where the plan and the brief didn't
settle something, the more private choice was taken, and the one that blocks nobody. No
migration: `church_away_commitments` was in step 1's file, and no column was missing.

**Where things live**

- **A module of its own, `church_schedule_repeats.py`**, with its own router on `/church`
  behind the engine's own gate (`church_schedule._church` / `_church_from_body`: not a church,
  closed, or before the tables, a 404). The engine gains two hooks only: `holds` and `calendar`.
- **`GET` takes `box=mine|all`**, as the asks' boxes do (no `to_me`: nothing waits on anyone).
  **`DELETE` takes the id in the address** (`…/commitments/{id}?business_id=`), as protected days
  and pairs do, and answers `{removed: c}`; `drop_commitment` returns that shape where the plan
  had `None`.

**What one is**

- **Its start is saved as the first day it falls on**, on or after the day named, for every
  pattern. So every other week always counts from one of its own days (the table's anchor check is
  met, never tripped), and the "from" a page shows is a day it happens. A start that isn't that
  weekday is moved forward, not refused.
- **A start may be up to a year back or a year ahead** (a past Saturday sets which alternate
  weekends are theirs); none named is today. **An end is today or later**, after the start, and a
  start and end with none of those days between them are a 400 ("It doesn't fall on that day
  between the start and the end you picked.").
- **The fifth is the last**: nth 5 is the last such weekday of the month, the fourth in a month
  that has four, as the table's comment says.
- **Ten in force a person.** One whose end has passed is not counted, not listed and not read
  again; it stays in the table (nothing cleans it up).
- **The same one again is the one there**: what it is (spaces and capitals aside), the day, how
  often, from and until. Two presses in the very same instant can still make two (the table has
  no unique index, and none was added).
- **366 days at most**: `commitment_days` counts from the window's first day for 366 days and no
  further. Every window that asks is shorter (the calendar 93 days, Dates 62, a board 8 weeks).

**Who**

- **Adding**: someone on the leaders schedule, for their own person; `for` exactly as an ask's
  (the owner and whoever oversees the office, for someone on the schedule; an Admin can't).
- **The list**: their own; every one only for the owner and whoever oversees the office.
- **Taking one off**: their own person's, and the owner's and the office overseer's anyone's.
  The one over them can't (it isn't theirs), and in the member app nobody but the person.
- **Someone taken off the schedule keeps theirs.** They still hold them from the scheduler, as an
  ask of someone since taken off still does (7.7); they are off the calendar, which lists the
  people on the schedule today; they can't add one; they see theirs on Dates, with Remove, if they
  open it (the Lead tab gives them no Dates entry for that alone: `section` answers from what is
  kept and reads nothing new); the office sees theirs in `all` and can take them off.

**The label is the person's, the owner's and the office overseer's**

- **Read by the person, and (an office login) the owner and whoever oversees the office**, and by
  nobody else (`sees_label`). Changed in the review of #1990: as first built it was read like an
  ask's reason, by whoever an ask of theirs would go to, worked out on every read. That cost about
  four reads a person with one on every calendar and every leader's Dates page (20 people: 22 reads
  became 99), each a new way for the page to fail, and it let who reads it move when the order at
  the nearest step changed (a co-leader added who sorts first), which an ask's reason never does
  (decision 1). A reason is read by whoever answers the ask; a thing that repeats needs no yes, so
  nobody over them has a decision to make with what it is. Whoever it would go to is still told
  that it's there, and on which days, never what it is.
- **For anyone else the key is absent**, on the calendar and on a list; never an empty string.
- **The day and the pattern are not private**: everyone on the schedule reads the name and the
  days on the calendar, as they read an approved away date's.
- **On Dates, Who else is away gives a name and the days only**: one row a person (their days
  together), the first three and how many more. Never what it is, even for the one it would go to
  (they read it in the office app).
- **Nothing the scheduler or a notice reads selects it** (`held_days`, the sweep), and every
  insert is sent redacted.

**The scheduler**

- **Everyone with one in the window is held**, on the schedule today or not, as for asks.
- **Its own read, after the asks, in a try of its own**: when it fails the asks are still held;
  when the asks' read fails nobody is held and nothing more is read, as before. One read more where
  the schedule is open, a page at a time (the asks' `HOLD_PAGE`, `HOLD_PAGES`). With nothing of this
  church's in the window the answer is byte for byte what it was.
- **Never counted toward a limit or a pair**: those read the facts in `serve_away`, which a thing
  that repeats never writes; `GET days` doesn't count it.

**The notice**

- **To whoever an ask of theirs would go to**, worked out when it goes (the table keeps no `to`):
  "Elena has something that repeats", "Every other Saturday, from Dec 5. It's on the calendar.
  Nothing for you to answer." The email says nobody asks them to serve on those days. Never what it
  is: the words are the same whatever was typed (pinned).
- **As a planned ask's**: outside quiet hours, `told_at` claimed before the send and let go when
  nothing went; the sweep's fifth read finds those untold and added in the last week
  (`TELL_DAYS`), never the label, and leaves them after that. One whose end has passed tells nobody.
  The sweep counts them as `repeats`.
- **Nobody to tell**: the one person the owner is, or one the office adds where it would go to the
  very login that added it. It is saved as told and nothing is handed on.
- **One the office adds for someone tells whoever it would go to, not the person**, as an ask
  entered for someone tells nobody else. **Taking one off tells nobody.**

**The Dates page**

- **"How often" is one list** (`often`: every week, every other week, once a month the 1st to the
  4th or the last) where the plan's form had `pattern` and `nth`: a page with no script can't show
  the second list only for "once a month".
- **"Starting" is today unless changed; "Until, if it ends" is empty; the day is picked from a
  list** that starts at "Pick a day". The form is only for someone on the schedule, and past ten it
  is one line instead ("That's ten, as many as you can have. Take one off to add another.").
- **In plain words**: "from" only while it hasn't started, "until" only when it ends, the year only
  when it isn't this one. The privacy line under "What it is" reads "between you and those who look
  after the whole church" for everyone, and "We'll let Amara know." follows for whoever has someone
  over them (and, from the same review, "I can't make it" says "We'll let Amara know." too, where it
  said "Amara is let know.").

**Open for the lead session or the owner**

- Whether the person should hear when the office adds one for them.
- Whether whoever it would go to should hear when one is taken off.
- Whether someone taken off the schedule should keep a Dates entry for theirs, or theirs should
  stop holding them from the scheduler. For now they hold them (it's still true that they work that
  Saturday), and the office's Leaders' dates screen will list everyone's, theirs too, with Take it
  off for the owner and the office overseer (the frontend follow-up), so none is out of sight.
- From the review of #1990, also: `weekday` and `nth` are read as ASCII digits only, four at most
  ("²" or a 5,000-digit string was a 500, now the plain refusal).
- Two presses in the same instant can make two copies (no unique index).
- The office app has no screen for them: the API only, until the office frontend exists
  (decision 21).

---

## 8. Step 4: The week (#1979)

The pastor approved the mock on 2026-11-19 ("go"). The office's menu: Volunteers → **The week**,
first in that group. One week, Sunday to Saturday (Nov 22 to 28), with a way to the week before
and the week after. In order: four counts, "Look at first", then one card per department. **Read
only**: nothing on the page writes; changes stay where they are today, door by door, in Who serves
when. **Built**: `church_week.py` (the module and both routes), `church_serving.minutes_of` and
`checks_of` (its own rules, read for one week's people), and `__tests__/test_church_week.py`.
No migration, no new table, no env var set anywhere: `CHURCH_WEEK` is unset, which means
`owner`, so the routes are live at the platform owner's own church (and to the platform owner's
own login) as soon as this deploys, and closed everywhere else. The office page is the
frontend's next PR, built from this section. A department leader's own view in the member app
comes later.

### 8.1 Routes

| Route | Answers |
|---|---|
| `GET /church/week/status?business_id=` | `{"enabled": bool, "hours": bool, "checks": bool}`: whether this login's menu shows The week, and what it will show. All three false (200) for a closed switch, a business that isn't a church (or a church on ChurchSavvy alone), a login that keeps neither door of Who serves when, or a read that failed. 404 for a login with no seat at that business; 400 for an id that isn't one. |
| `GET /church/week?business_id=&start=YYYY-MM-DD` | The week `start` falls in (any day of it: Wednesday Nov 25 is the week of Sunday Nov 22). No `start`, or one that isn't a real date, is this week on the church's clock. A week more than 52 weeks back or 26 weeks ahead of this one is a 400 ("Pick a week from a year back to six months ahead."). 403 for a seat here that keeps neither door; 404 for no seat here, the switch closed for this church, Who serves when (`SUNDAY_PLANNING`) closed to them, or not a church; 503 when a read fails (never an empty or shorter week). |

Both take the auth header like every office route (`require_user`). The frontend reads `status`
once to decide whether Volunteers shows "The week", then `GET /church/week` with `start` set to
`week.prev` or `week.next` for the arrows.

### 8.2 Who reads it

- **The owner, every Admin, and a Manager that keeps either door of Who serves when.** A Manager
  keeps a door when it changes some team there (`sunday_planning._owners_for`: `serve_schedule`
  for the Volunteers' door; `production_schedule`, `churchsavvy_team` or a ChurchSavvy part that
  schedules for ChurchSavvy's), or holds a duty the office menu opens that door's Who serves when
  for (`church_week.READS`: `serve_teams`, `new_volunteers`, `background_checks`,
  `serving_thanks` for the Volunteers' door, the office menu's own rule from the frontend's
  2026-11-02 Volunteers door; `production_schedule`, `churchsavvy_team` for ChurchSavvy's). Duties
  are `church_duties.standing`'s (a lane's starting duties, a move, or a Manager's areas when it has
  no lane).
- **They read every department, both doors**, ChurchSavvy's worship and production teams too.
  `can.change` says which doors' teams this login changes in Who serves when; the page itself
  changes nothing.
- **Anyone else with a seat is a 403** ("The week is for whoever keeps the volunteer teams or Who
  serves when."): a Member or Viewer seat, and a Manager that keeps neither door (at the fixture
  church, Office & Leadership and People & Care). A stranger, another church's owner included, is a
  404 (`business_access.assert_access`). A ChurchSavvy team member without an office seat is not an
  office login and reads nothing here.
- **The church's own gate**: a church (`church_follow_up.is_church`), and not one on ChurchSavvy
  alone (no office, no doors): otherwise 404.

**At the platform owner's church, does the volunteers keeper see "Can't serve with kids yet"?**
What decides it is `church_serving._access`'s `checks`. The owner and every Admin always have it.
A Manager the page admits has it when **any one** of these holds:

1. **Who sees what is not on** (`CHURCH_AREAS` anything but `on`): `_access` reads no areas then,
   so every admitted Manager reads who's cleared.
2. **Its areas are the whole church**: `church_areas.my_areas` gives none (no pick and nothing to
   guess from), which `_access` reads as everything.
3. **Its areas include Kids & youth or People & care** (the church's pick on the login, else
   Chief's guess), whatever duties it holds.
4. **It holds the `background_checks` duty** (`church_duties.holds`, `record`). The Sunday &
   Serving lane starts with it (`church_duties.STARTER`; the owner's 2026-11-02 call made checks
   Sunday & Serving's). A login on one of the church's own jobs holds it only when it is on that
   login's sheet; a Manager with no lane, when its areas include Kids & youth. Once the duty is
   moved to someone else, only the logins it moved to hold it.

A Manager on the Sunday & Serving lane is written with the areas Worship & media alone, so with
Who sees what on and the duty where the lane starts it, it **does** see it, by 4. If the duty was
moved away it doesn't, unless 1 to 3 says otherwise (pinned:
`test_the_volunteers_keeper_reads_checks_by_the_background_checks_duty`, and by areas without the
duty, `test_a_reader_cleared_by_their_areas_sees_it_without_the_checks_duty`). Whether the duty
sits with the volunteers keeper at the owner's church, and what that login's areas are, was not
checked against production in this PR.

### 8.3 The shape, field by field

An example, trimmed (the fixture church's week of Nov 22, read by its volunteers keeper on Wednesday
Nov 18):

```json
{
  "week": {"from": "2026-11-22", "to": "2026-11-28", "words": "Nov 22 to 28", "this_week": false,
           "prev": "2026-11-15", "next": "2026-11-29"},
  "counts": {"on": 6, "open": 7, "away": 2, "hours": 9.5},
  "look": [
    {"kind": "short", "title": "Kids is short one on Sunday: Nursery.",
     "details": ["Dara Quinn is away. Two people on the Kids Check-in team are free that morning."],
     "service_id": "…", "day": "2026-11-22",
     "find": {"group_id": "…", "service_id": "…", "day": "2026-11-22"}},
    {"kind": "short", "title": "Worship is short one on Sunday: Vocals.",
     "details": ["The worship team fills this in ChurchSavvy."], "service_id": "…", "day": "2026-11-22",
     "find": null},
    {"kind": "no_answer", "title": "Kids: Toby Wells hasn't answered for Sunday.",
     "details": ["Toby was asked on Monday."], "service_id": "…", "day": "2026-11-22", "find": null},
    {"kind": "cant_serve_kids", "title": "Kids: Lila Penn can't serve with kids yet.",
     "details": ["Lila's background check isn't on record. Lila is on for Sunday."],
     "service_id": "…", "day": "2026-11-22", "find": null}
  ],
  "departments": [
    {"department_id": "…", "group_id": null, "name": "Kids", "led_by": "Kara Bell", "churchsavvy": false,
     "open": 4, "label": "4 open",
     "teams": [{"group_id": "…", "name": "Kids Check-in", "door": "volunteers", "churchsavvy": false}],
     "services": [
       {"service_id": "…", "day": "2026-11-22", "weekday": "Sunday", "time": "10:30",
        "words": "Sunday 10:30 AM", "kind": "service", "title": "Sunday service", "past": false,
        "rows": [
          {"group_id": "…", "team": "Kids Check-in", "door": "volunteers", "place_id": "…",
           "place": "Nursery", "slot": 2, "person": {"contact_id": "…", "name": "Dara Quinn"},
           "who": "Dara Quinn", "state": "away", "state_words": "Away", "minutes": 90,
           "hours_words": "1.5 hours", "find": {"group_id": "…", "service_id": "…", "day": "2026-11-22"},
           "note": null}]},
       {"service_id": "…", "day": "2026-11-26", "weekday": "Thursday", "time": "19:00",
        "words": "Thursday 7 PM · Outreach night", "kind": "event", "title": "Outreach night",
        "past": false, "rows": ["…"]}]}
  ],
  "can": {"hours": true, "checks": true, "change": ["volunteers"]}
}
```

**`week`**

| Field | What it is |
|---|---|
| `from`, `to` | The Sunday and the Saturday shown (`YYYY-MM-DD`, the church's clock). |
| `words` | The heading: "Nov 22 to 28", or "Nov 29 to Dec 5" across a month. |
| `this_week` | The week we're in, on the church's clock. |
| `prev`, `next` | The Sundays of the weeks either side, to pass back as `start`; `null` past the bounds (52 weeks back, 26 ahead), so the arrow hides. |

**`counts`** (the four at the top; the whole week, every service in it, past or to come)

| Field | What it is | The mock's label |
|---|---|---|
| `on` | Places with someone on them who said yes or hasn't answered yet (and isn't away that day). Someone who can't serve with kids yet still counts here, for every reader, so the count never gives it away. | On the schedule |
| `open` | Places nobody is on: never asked, a no, offered to the team and not taken, **or** someone on it who is away that day. | Open places |
| `away` | People on the Sunday teams (every team shown) with an away date (`serve_away`, the facts) touching this week, each once. A waiting ask is never counted. | Away |
| `hours` | Hours this calendar year (to today) of this week's people (everyone the rows name), one decimal. `null` when this login doesn't read hours: show nothing, not 0. | Hours this year |

**`look`** ("Look at first"), most urgent first: by service time, then short, no answer, can't
serve with kids yet; within those, the Volunteers' door before ChurchSavvy's, then the cards'
order. Only services still to come make a line.

| Field | What it is |
|---|---|
| `kind` | `short`, `no_answer`, `cant_serve_kids`, or `clear` (the one line when nothing needs a look). For the frontend's icon or colour only; never show it. |
| `title` | The line, in full. `short`: "{department} is short {one, two…} on {day}: {places}." (a place needing two reads "Nursery (2)"). `no_answer`: "{department}: {name} hasn't answered for {day}." `cant_serve_kids`: "{department}: {name} can't serve with kids yet." `clear`: "Everything is filled for Sunday." (every day still to come at which some team has a place: "for Sunday and Thursday"; a service no team has a place at, such as an event date with only ChurchSavvy's teams, is never named), "This week's services have passed." (every service with places has started), "Nothing is on the schedule this week." (no service this week at which a team has a place) or "No teams are on Who serves when yet." `{day}` is the weekday, with the time when the week has two services that weekday ("Sunday at 9 AM"). A team on no department's card says its own name where a department's would be ("Parking Team: …"). |
| `details` | The smaller lines under it, in full, each its own line (may be empty). `short`: one per person on a place who is away ("{name} is away. Two people on the {team} team are free that morning.", "One person…", "Nobody else…"; morning, afternoon or evening by the service's time), and "The worship team fills this in ChurchSavvy." for ChurchSavvy's door. `no_answer`: "{first name} was asked on Monday." (today, yesterday, a weekday within the week, else "on Nov 9"; no line when the ask has no time). `cant_serve_kids`: "{first name}'s background check isn't on record. {first name} is on for Sunday." (or "was asked for Sunday"). |
| `service_id`, `day` | The service the line is about (`null` on `clear`). |
| `find` | For a `short` line on the Volunteers' door: `{group_id, service_id, day}` of the first short team, for a "Find someone" button to Who serves when (see rows). `null` otherwise. |

**`departments`**: the cards, in the church's own order (the leaders map's active departments, by
their order), then one card for each Sunday team that hangs from no department (in Who serves
when's team order). A department with no Sunday team has no card.

| Field | What it is |
|---|---|
| `department_id` | The department's id; `null` on a team's own card. |
| `group_id` | On a team's own card, the team's id; `null` on a department's. |
| `name` | The department's name, or the team's on its own card. |
| `led_by` | The department's leader's name; on a team's own card, the team's own leader (the first by name); `null` when there is none (show nothing). "led by {led_by}". |
| `churchsavvy` | Every team on the card is ChurchSavvy's: show the "Scheduled in ChurchSavvy" chip on the card. (`teams[].churchsavvy` says it per team, for a card with both.) |
| `open` | Open places on the card this week (as `counts.open`). |
| `label` | "{n} open", "Filled", or "Nothing this week" (no places this week at all), in full. |
| `teams` | `[{group_id, name, door, churchsavvy}]`: its Sunday teams. `door` is `volunteers` or `churchsavvy` (never shown). |
| `services` | When it serves this week: the services and event dates at which any of its teams serve (ChurchSavvy's teams never serve an event date), soonest first. |

**`departments[].services[]`**

| Field | What it is |
|---|---|
| `service_id`, `day`, `weekday`, `time` | The service; `time` is 24-hour `HH:MM` on the church's clock. |
| `words` | "Sunday 10:30 AM", or for an event date "Thursday 7 PM · Outreach night": the line to show. |
| `kind`, `title` | `service` or `event`, and its own title. |
| `past` | It has started. A past service keeps its rows, makes no "Look at first" line and offers no "Find someone". |
| `rows` | One per place and spot (a place that needs two people has two rows, `slot` 1 and 2), team by team in Who serves when's order, each team's places in its order. |

**`departments[].services[].rows[]`**

| Field | What it is |
|---|---|
| `group_id`, `team`, `door` | The team the place is on (its name is shown when a card has more than one team). |
| `place_id`, `place`, `slot` | The place and which of its spots. |
| `person` | `{contact_id, name}` of whoever is on it, or `null` for an open place. |
| `who` | The name to show, or "Open place". |
| `state` | `on`, `no_answer`, `open`, `away`, `cant_serve_kids`; never shown. |
| `state_words` | "On", "No answer yet", "Open", "Away", "Can't serve with kids yet": show this. |
| `minutes`, `hours_words` | That person's serving this year (`0`, "No hours yet"; "45 minutes"; "1 hour"; "3 hours"; "1.5 hours"). Both `null` on an open place, and on every row for a login that doesn't read hours. |
| `find` | `{group_id, service_id, day}` on an open or away place of a Volunteers' team at a service still to come: "Find someone", opening Who serves when's Volunteers door on that team and day. `null` otherwise. |
| `note` | On an open or away place of a ChurchSavvy team: "The worship team fills this in ChurchSavvy." (show it where "Find someone" would be); `null` otherwise. |

**`can`**: `hours` and `checks`, whether this login reads hours and who's cleared (as `status`
says); `change`, the doors (`volunteers`, `churchsavvy`) whose teams it changes in Who serves when.
The page needs none of them to draw itself; they say why a field is `null`.

### 8.4 Hours and "Can't serve with kids yet"

- **Who sees them is church_serving's rule, asked of `church_serving._access` itself.** A login it
  turns away (its areas leave Serving out and it doesn't do the background checks, or
  `CHURCH_SERVING` closed to it) gets no hours: every `minutes`, `hours_words` and `counts.hours`
  is `null`. A login it lets in but doesn't let read who's cleared (`checks` false) never sees
  "Can't serve with kids yet": that person is `on` (or `no_answer`), no line says it, and the page
  is byte for byte the page it would be if their check were on record (pinned).
- **The hours are church_serving's own arithmetic** (`minutes_of`): each yes this year by the team's
  length or the plan's span, two places one day counted once, a sub's yes theirs, a group gathering
  they led and were marked at, hours the office added; away days never. Read for the week's people
  alone and bounded to the year: the year's services' ids first, then these people's yeses at those
  services (both lists chunked, sixty ids each), then those services' plans, their away dates, their
  leads and their records, chunked and paged. So they equal what the Serving page gives the same
  people (pinned against `overview`, with a gathering, an away day, two places one Sunday and the
  office's hours), and a long history costs nothing more. The Serving page's own reads (the whole
  church, and one member's My serving) are unchanged.
- **"Can't serve with kids yet" is church_serving's `blocked`** (`checks_of`, `check_state`): no
  check on record (the latest of the leader approval's and one recorded on Serving) and on the
  schedule with Kids & youth (a Sunday team `church_serving._kids_teams` places there), at a service
  of this week still to come. Under 18 is never blocked. A check that ran out, or runs out within
  the month, is not this state, and neither is any check on record (Serving's page shows those).
  Only worked out for a login that may read it: anyone else's request makes no check read at all
  (no leaders' dates, no Kids & youth teams; pinned on the reads).

### 8.5 Decided in the build (beyond the brief; none is the pastor's call)

1. **Who reads it**: the owner, an Admin, and a Manager that keeps either door, where keeping is
   changing its teams (`_owners_for`) **or** holding a duty the office opens that door's Who serves
   when for (`READS`). The second half is the frontend's own menu rule for the Volunteers' pages;
   without it the background-checks holder (who sees the Volunteers group) would be refused.
2. **Counts cover the whole week**, past days included, as Who serves when shows a week. An away
   person's place is open; a "can't serve with kids yet" person's place is on the schedule, for
   every reader.
3. **Away is the facts only.** Someone who asked to be away and still waits is not away here, not
   counted, and counts as free ("Two people… are free"); Who serves when, where they are picked,
   already skips them. Nothing here reads `church_away_asks`.
4. **"Free"** is the team's people who aren't away that day by the facts and aren't on another
   place at that service. It ignores checks and how many Sundays a month they serve; Who serves
   when's own list ranks them when someone is picked.
5. **Short lines are one per department, service and door**, listing the places, not one per
   place, so a new church with thirty open places reads a few lines. ChurchSavvy's teams get their
   short lines too, under the Volunteers' door's, with the ChurchSavvy line and no "Find someone".
6. **A department with no Sunday team has no card**; a team two departments name is on the first
   department's card only (nothing counted twice); with the leaders map closed for a church every
   team is its own card. A team's own card is led by its own leader.
7. **Hours are this calendar year to today**, whatever week is shown, and are those of the people
   the week's rows name (someone away included). A "no" never shows who said it.
8. **Bounds**: 52 weeks back, 26 ahead (event dates are added up to 180 days out). A start that
   isn't a date is this week, never a 400.
9. **Only a service still to come** makes a "Look at first" line, offers "Find someone" or can show
   "Can't serve with kids yet"; a past service is what happened.
10. **A ChurchSavvy-alone church has no week** (404), as it has no office or doors. Who serves when
    closed (`SUNDAY_PLANNING`) closes it too.
11. **Status** is quiet (all false, 200) for everything but a login with no seat, as Serving's is.
12. **"Filled" is said only of days a team has places** that week: with no places at all, or with
    an event date only ChurchSavvy's teams have places around, the line is "Nothing is on the
    schedule this week." or names the days that do have places (changed in review).

Seen in review and left as they are:

- **Further out than Serving looks.** The week marks "Can't serve with kids yet" at any service
  still to come in the week shown, up to 26 weeks out, while Serving's checks call someone
  `blocked` only when they are on with kids within `SOON_DAYS` (28) and `none` farther out. Both
  pages are read by the same people (church_serving's rule), so this tells no one anything new; it
  only means a week two months out can say it while Serving's list says "none on record".
- **A Manager who loses its duties can still read for up to a minute on a replica.**
  `church_duties.standing` is kept 60 seconds a replica, as it is for `sunday_planning._owners_for`
  and every duty check. The same for a login's areas.
- **The People & Care lane is refused while a no-lane Manager with like areas is let in.** The lane
  starts with People & Care's duties, none of which opens Who serves when; a Manager with no lane
  holds every duty in its areas, so one whose areas include Kids & youth holds `background_checks`
  and keeps the Volunteers' door. That is how duties work today (`church_duties._area_duties`);
  moving `background_checks` (or `serve_teams`) to a People & Care login lets it in.

### 8.6 Left out

- The department leader's own view in the member app (later, as the brief says).
- A check that ran out, or runs out soon, is not a line here (Serving's page has it).
- Who asked someone to cover their place (`swap_to`) is not shown; they read as On until the cover
  says yes, as Who serves when has it.
- The ask's state on the person's side (sent or still waiting for the sweep) is not shown; "was
  asked on Monday" is when it was made.
- A place's spots past its number (a place cut from three to two) and a retired place are not
  rows, as Who serves when shows them.
- No caching: each read is fresh (about fifty reads a week for the fixture church, most of them the
  gate's duty, area and map reads).

### 8.7 Tests

`__tests__/test_church_week.py` at New Hope (church_three; every name made up), on
church_schedule_fake's tables with the real gate, duties, areas, leaders map and church_serving:
the page as the volunteers keeper reads it, word for word; who reads it (owner, Admin, the two
doors' keepers, the Kids & youth Manager) and who is refused (403 for two office Managers, a Member
and a Viewer; 404 for another church's owner and a stranger; 404 for a business that isn't a church
and a ChurchSavvy-alone church); every read this church's and quoted, another church's rows that
name its places changing nothing, and a typed start never reaching an address; a team of 1,150
read whole; "Can't serve with kids yet" byte-for-byte hidden, a full Sunday reading full to whoever
can't see checks, the background checks duty granting it and moving it away taking it; hours by
church_serving's rule; `minutes_of` and `checks_of` equal to the Serving page's; no note, ask,
reason, phone, email or stranger's name; plain words; the switch; the bounds; a failed read a 503.
Each rule was broken once on purpose and its test went red, then green again (the PR lists them).
From the review: for whoever may see checks, only none on record reads "Can't serve with kids yet"
(a check that ran out, runs out soon, is recorded on Serving or on the Kids leaders page, and
someone under 18 read On), the latest check date counts, a past service never says it, a login
cleared by its areas without the checks duty sees it, and nobody else's request reads a check;
the hours equal the Serving page's with a gathering, an away day, two places one Sunday and the
office's hours, and read only this year's yeses; "Everything is filled" is said only of days with
places.

---

## 10. Step 3: Meetings and one calendar (S3-1)

The pastor approved the mock and its five calls on 2026-11-20, each as recommended. Four screens:
the office's church calendar gains two kinds, **Meeting** and **Away** (who is away, by name and
dates, never why); **Set a meeting** (a name; who comes: every leader on the leaders list, the
office, or a board; when, how long, where; how often; and a date check across a few candidate
days showing who can't come and whether the room is free); **the meeting page** (who said "I'll
be there", who said "I can't", who hasn't answered, and "Remind the ones who haven't answered";
attendance, agenda, minutes and decisions as Board & minutes has them today); and **a leader's
phone** ("Coming up" at the top of Dates, with I'll be there / I can't on each meeting they are
in, and one private link that puts it all on their phone's calendar).

**Where it stands.** S3-1 holds the tables and nothing else:
`supabase/APPLY-2026-11-21-church-meetings.sql` (**not applied**), its real-Postgres check
(`__tests__/church_meetings_db.mjs`), the export decision for the four new tables, and this
section. No Python reads or writes any of it yet. 10.9 is the PR split for the rest.

### 10.1 The five calls (the pastor's)

As they were put to him, and his answer to each was yes, as recommended:

1. **One home for every meeting.** Board & minutes is renamed **Meetings & minutes**. The
   huddle, the leaders meeting, check-ins and each board sit side by side, each with agenda,
   attendance and minutes as boards have now.
2. **"Every leader" keeps itself up to date.** A meeting for every leader follows the leaders
   list (`church_schedule.roster`): add an elder to the list and they are invited to the next
   meeting, with nobody touching the meeting. The same for the office.
3. **"I can't" needs no yes.** It is an answer to one meeting, not time off. A short optional
   note, read only by whoever set the meeting (the meetings' keepers), the owner and whoever
   oversees the office.
4. **A reminder the day before, in the app.** Everyone who hasn't said "I can't" gets an app
   notice the day before, never in quiet hours; email only when there is no app on their phone;
   no texts.
5. **A private link for their phone's calendar** (an ICS feed). It stays up to date. Anyone
   with the link can see those dates, so the person can make a new one at any time and the old
   one stops working.

Also in the build, from the mock: setting a meeting books the room in Rooms & spaces
(`church_spaces.py`) when it is free.

### 10.2 The data model: `supabase/APPLY-2026-11-21-church-meetings.sql` (S3-1; not applied)

The file is the source; this is the map of it. **Board & minutes' six tables stay the one home of
every meeting** (call 1): a group that meets is a `church_boards` row, a meeting is a
`church_board_meetings` row, and its agenda, attendance, decisions and minutes are the rows they
are today. Nothing about a board changes.

| Object | What it holds |
|---|---|
| `church_boards.kind` | `board` (it governs: its people give the board's yes on money, and it is a board on the leaders map) or `meeting` (it only meets: the huddle, the leaders meeting, check-ins). Every group there is today is a `board` |
| `church_boards.audience` | Who comes. `members`: the group's own people, as every board has them. `leaders`: everyone on the leaders list. `office`: the office on it. A group for the list is always a `meeting` (`church_boards_list_is_meeting`), keeps its audience for good (trigger `church_boards_audience_kept`), and is the one open group of its name and audience, whatever its case (`church_boards_one_list_name`) |
| `church_board_members.from_list` | A row the server keeps in step with the leaders list. On a group for the list every row is one; on any other group none is (trigger `church_board_members_follow_list`). One a person a group (`church_board_members_one_from_list`) |
| `church_meeting_series` | A meeting that repeats: its group, a `weekday` (1 Monday to 7 Sunday), `pattern` (`weekly`, `every_other` counted from `starts_on`, or `month_nth` with `nth` 1 to 5, 5 the last), `starts_on`, `until_on`, `at_time` on the church's clock, `length_minutes` (5 to 720, 60 by default), `title`, `place`, `video_url`, the room (`space_id`), `made_through` (meetings exist up to this day) and who set it |
| `church_board_meetings.series_id`, `series_day` | The series a meeting was made from and the day of it that it stands for (one meeting a day of a series: `church_board_meetings_one_a_day`). A series deleted leaves its meetings, keeping their day |
| `church_board_meetings.length_minutes` | How long (5 to 720). Null on every meeting set before step 3: an hour wherever a length is needed |
| `church_board_meetings.space_id`, `booking_id` | The room, and the booking made for it in `church_space_bookings` (of that room; one meeting a booking) |
| `church_board_meetings.cancelled_at`, `cancelled_by` | Called off (a one-off) or skipped (one of a series). Only a meeting still `planned`. The row stays, so a series never makes that day again and a phone's calendar drops it |
| `church_board_meetings.changed_alone_at` | Changed by itself; changing the series from a day on leaves it alone. Only a meeting of a series |
| `church_meeting_answers` | "I'll be there" (`yes`) or "I can't" (`cant`): one a person a meeting (`primary key (meeting_id, member_id)`), keyed by their member row as `church_board_attendance` is; `for_starts_at` (the start the answer was given for); a private `note` of 200 at most, with `cant` only; who gave it (`by_user_id` or `by_contact_id`, never both) |
| `church_meeting_notices` | The reminders' ledger: `day_before` or `nudge`, a person, a meeting, `for_day`; `claimed_at`, `sent_at`, `how` (`app`, `email` or `nobody`: never a text), `tries`, and `made_by` (a nudge only). One a person a meeting a kind a day (`church_meeting_notices_once`) |
| `church_calendar_links` | A person's private link for their phone's calendar: `token_hash` (the sha256 of its key, 64 lower-case hex; the key itself is never kept), `made_by`, `revoked_at`, `last_read_at`. A key is one link's anywhere (`church_calendar_links_token`); one working link a person (`church_calendar_links_one_live`) |

**Who comes: one member row a person, kept in step by the server.** A board's people are its
member rows today, and everything else keys a person by that row: attendance
(`church_board_attendance.member_id`), the quorum (`church_board.roster`), who moved and
seconded a motion (foreign keys to the member row), a follow-up's person
(`church_board_items.follow_up_member`), whom "Send minutes for approval" emails, and the member
app's Board tab (`member_portal_board.boards_of`, by `contact_id`). So a meeting for every leader,
or for the office, has member rows too: the server keeps them in step with the leaders list, and
every one of those pieces works for the huddle as it does for the deacons, unchanged. Answers
and reminders key a person the same way.

The other way, a meeting's audience with answers and attendance keyed by `contact_id` and no
member rows for the list, was turned down: it would need a second shape of attendance, of
decisions (whose movers are member rows), of follow-ups, of the minutes email and of the meeting
page, side by side with the first, for ever.

**Keeping the list's rows in step** (S3-2, `church_meetings.keep_in_step`):

- `leaders` is everyone on the leaders list: `church_schedule.roster(ch).people()`, its leaders
  group and its office group both (an all-leaders meeting has the office staff in it). `office`
  is the list's office group plus everyone counted among its leaders who has an office login
  (decision 2 counts a leader with a login under leaders, and the Executive Pastor still comes to
  the huddle): `roster.office | (roster.leaders & set(ch.person_login))`. The list's own add and
  remove lists decide for both.
- The rule, for one group: a person on the list with no row gets one (`from_list`, their
  `contact_id`, `user_id` the login they are by `Church.person_login`, so an office person also
  reads the group in the office app); a row whose person is back on the list is `active` again;
  an active row whose person is off the list is `active = false`, as leaving a board is, so old
  minutes keep the name. Nobody adds a person to a group for the list by hand
  (`church_board_members_follow_list` refuses it), and the list never adds one to a board.
- When: before anything reads who a group for the list is for (the meeting page, Set a meeting,
  the date check, Coming up, the reminders), with the roster kept a minute a replica on the
  member side (`roster_kept`, decision 17); and the hourly sweep keeps every group for the list
  at an open church in step, so the calendar feed (which has no session to read the list with)
  is at most an hour behind. Two replicas at once add a person once
  (`church_board_members_one_from_list`; `on conflict (board_id, contact_id) where from_list do
  nothing`). That is call 2: nobody touches the meeting.

**`kind`: a meeting is never a board, and S3-2 must say so everywhere a board is meant.** Today
every `church_boards` row is a board, and four readers treat every row as one. A huddle or a
check-in read as a board would hand its people **the board's yes on money**. So, in the same
pull request that first writes a `kind = 'meeting'` row (S3-2), each of these reads
`kind=eq.board`:

| Reader (at `c62547f7`) | What reading a meeting as a board would do |
|---|---|
| `church_money_levels._open_boards` (`:253-258`), feeding `board` and `board_people` | every leader (the leaders meeting) or every office login (the huddle) could give the **board's yes on a check request**, in the office app and in the member app (`/my/board/approvals`) |
| `church_map._THINGS["board"]` (`:555`, read at `:653` and `:1009`) | the leaders map offers the huddle as a board a department can hang from |
| `member_portal_board.boards_of` (`:335-349`) | every leader gets the member app's Board tab, showing the leaders meeting as their board (step 3 puts meetings under Coming up on Dates instead; S3-5 may show them on the Board tab too, by choice and by `kind`) |
| `housing_allowance._check_links` (`:549-553`) | a decision recorded in the huddle could be picked as the board's vote on a minister's housing allowance |

A lint test in S3-2 (`test_board_readers_name_kind`) scans every `church_boards` and
`church_board_members` read outside `church_board.py` and `church_meetings*.py` and fails unless
it names `kind` or is on a short pinned list with a reason, so a reader added later can't forget.
The database backs one half of it: a group for the list can never be a board
(`church_boards_list_is_meeting`). A check-in (a meeting of its own people) is held to `meeting`
by the server alone; making one a board is the keepers' choice, on purpose.

**A meeting that repeats.** The rule is `church_away_commitments`' own, column for column, so
`church_schedule_repeats.days_of` works out a series' days as it does a commitment's: every
Tuesday (the huddle), every other week from its first day, or the first to fourth or the last
such day of the month (the leaders meeting on the third Saturday). In S3-3:

- **How far ahead.** Every meeting of a series through 91 days ahead (13 weeks, the calendar's
  window) exists as a row, so answers, the room and the phone's calendar all have something to
  hold; the next is made as the window moves (the hourly sweep, which writes `made_through`).
  Each is made with `on conflict (series_id, series_day) do nothing`, so two replicas make one.
  `starts_at` is the day at `at_time` on the church's clock (`ch.tz`), worked out for each day,
  so a meeting stays at 7 PM across the clock change.
- **Editing one.** That meeting changes (its time, length, place, room) and is marked
  `changed_alone_at`; it keeps its `series_day`, so the series never makes that day again.
- **Editing all, from a day on.** The same rule (a new time, length, place or room): the series
  row changes, and so does each of its meetings from that day on that is still `planned`, not
  called off and not changed by itself. A new rule (another weekday, how often): the old series
  ends the day before (`until_on`) and a new one starts that day, so nothing already made has to
  become a different day; the old series' meetings after its end are taken out when nothing is
  recorded on them (no agenda item, attendance mark or decision) and called off otherwise.
- **Skipping one.** `cancelled_at`, and its booking is cancelled. Back on: `cancelled_at`
  cleared, and the room booked again when it is still free.
- **Ending a series.** `until_on`; its meetings after that day go as for a new rule.
- **Deleting a series.** Its meetings stay, as one-off meetings with their day.

**Answers** (call 3; S3-2):

- `yes` or `cant`, and nothing else: no "maybe". "I can't" needs no yes and asks nobody.
- `for_starts_at` is the meeting's start when the answer was given. Once the meeting moves, an
  answer for the old time no longer counts as an answer: the person is listed with those who
  haven't answered (with "said … for the old time" to whoever may read it) and is reminded as
  they are. Nothing is deleted.
- **The note**, 200 characters at most and with `cant` only (`church_meeting_answers_note`), is
  read by the person who wrote it, the meetings' keepers (church_board's: the owner, an Admin,
  the Manager holding the `meetings` duty), the login that set that meeting (`created_by`) and
  whoever oversees the office (`church_schedule.office_overseers`), wherever they can open the
  meeting. Never by anyone else on the meeting, never in a notice, a calendar feed, a log line or
  the meeting's minutes. The sweep clears it 90 days after the meeting, as the schedule clears a
  reason (decision 14): it can say why, and why can be medical.
- A `cant` given before the meeting is ended reads as `excused` when "End the meeting" marks
  everyone not yet marked (`church_board._mark_rest_absent` marks the rest absent today).
- Answering is for a meeting still `planned`, not called off and not started; a seat that has
  left (`active = false`) doesn't answer.

**Reminders** (call 4; S3-6). The ledger is claim-before-send, as every notice here is:

- `day_before`: on the hourly sweep, for each meeting whose day on the church's clock is
  tomorrow, `planned` and not called off, each active seat that hasn't said `cant` **for the
  current time** gets one: claimed by `insert … on conflict (meeting_id, member_id, kind, for_day)
  do nothing returning id` with `claimed_at` set, sent, then `sent_at` and `how` written; let go
  (the row deleted, or `claimed_at` cleared and `tries` counted) when nothing went, so the next
  sweep tries. `for_day` is the meeting's own day, so a meeting moved to another day gets a fresh
  one. Never in quiet hours (`member_push.quiet_hour`): the sweep waits; one that can't go on the
  day before, outside quiet hours, isn't sent.
- `nudge` ("Remind the ones who haven't answered", on the meeting page): each active seat with no
  answer for the current time; once a day a person (`for_day` is the church's day it was
  pressed); `made_by` is who pressed it. Outside quiet hours it is claimed and sent at once,
  after the write; inside them it is saved unclaimed and the sweep sends it when they end.
- How: a person, by `church_schedule_tell.to_person` (a push to their phone and a line in their
  conversation with the church, and an email only when no phone was reached: "email only when
  there is no app on their phone"); a seat with a login and no person, by
  `church_schedule_tell.to_login`. `how` is `app`, `email` or `nobody`; there is no value for a
  text, so nothing can record one. What it says: the meeting's name, the day and time, the place.
  Never a note, never who else can't come.

**The private link for a phone's calendar** (call 5; S3-6):

- The key is `secrets.token_urlsafe(32)`; only its sha256 is kept (`token_hash`). The person is
  shown the link once, when it is made; afterwards the page says when it was made and offers
  "Make a new link" and "Stop this link".
- One working link a person (`church_calendar_links_one_live`). A new link stops the old one
  first (`revoked_at`), then goes in; two presses at once leave one working link, and the second
  is told to try again. A stopped link stays stopped (the trigger refuses clearing or moving
  `revoked_at`), and a link never changes church, person or key: a new one is a new row.
- The feed, `GET /cal/{key}.ics`, needs no sign-in: it finds the link by `token_hash` with
  `revoked_at` null (a stopped or unknown key is a 404, the same for both), then the meetings of
  every group the person has an active seat on, from 30 days back to 180 ahead. Each event: the
  meeting's name, its start and end (an hour when it has no length), the room or the place, and a
  link to Coming up. A meeting called off is sent as cancelled for 30 days, so phones drop it.
  Never an agenda, a note, an answer or who else is coming. That is what "anyone with the link
  can see those dates" means, and the page says so beside the link.
- `last_read_at` is written at most once an hour a link, so a phone's polling costs no writes.
  The feed is rate-limited by the key's hash, never by the key.

**The room.** Setting a meeting with a room checks it with `church_spaces.clashes` for the
meeting's time. Free: a booking is made (its title the meeting's name, `booked_by` the login that
set the meeting), `booked` when that login books straight away under Rooms & spaces' own rules
(the owner, an Admin, the Manager who does the rooms) and `requested` otherwise, waiting for
whoever does the rooms, as any room request does; `booking_id` names it. Taken: the meeting is
saved without a booking and the page says the room is taken that day (by what, as Rooms &
spaces would show this login). Two presses at once: the booking table's own exclusion
constraint refuses the second booked one (23P01), read as taken. A meeting moved, by itself or
with its series, moves its booking (re-checked; taken at the new time, the booking is cancelled
and the page says so). Called off, skipped or deleted: its booking is cancelled. A booking
cancelled from Rooms & spaces leaves the meeting naming the room with a cancelled booking, and
the page says it isn't booked. A series' meetings each book their own room as they are made.

**Guards**

- `church_boards_kind`, `church_boards_audience`, `church_boards_list_is_meeting`, and
  `church_boards_audience_kept` (before an update of `audience`: a group keeps who it is for; a
  change of audience would leave a group for the list holding hand-added rows, or a board holding
  the list's).
- `church_boards_one_list_name` (unique on church, audience and `lower(name)`, where the audience
  isn't `members` and the group isn't archived): Set a meeting pressed twice for "Leaders meeting"
  finds or makes one. A closed group frees its name; boards may share a name, as they always could.
- `church_board_members_follow_list` (before insert, and before an update of `from_list`,
  `board_id` or `business_id`): a row is the list's exactly when its group follows the list, and
  a row the list adds names one of the church's people. A person deleted (their `contact_id` set
  null by the board's own key) checks nothing, and their row stays, for old minutes.
- `church_meetings_same_business`, one function on five tables, each check made only when a
  write names what it checks, so a foreign key setting something null (a room, a booking, a
  series, a person or a login deleted) checks nothing: a series' room is its church's; a
  meeting's series is the same church's and the same group's, its room its church's, and its
  booking its church's and of its room (checked when the booking is written, so whoever moves a
  meeting to another room writes its booking in the same update); an answer's and a reminder's
  seat is on the meeting's group; the person who answered is the church's; a calendar link's
  person is the church's, and the link keeps its church, person and key and, once stopped, stays
  stopped. A series' group is its church's by its foreign key, which carries the church.
- The constraints: a series' `nth` with `month_nth` only, its end after its start, every other
  week starting on its weekday, its length; a meeting of a series names its day, its length,
  only a `planned` meeting called off and who called it off only with when, "changed by itself"
  only in a series; an answer's note with `cant` only and 1 to 200 characters after trimming, by
  a login or a person never both; a reminder sent only once claimed and always with how, made
  by someone only as a nudge; a link's hash 64 lower-case hex characters.

**Server-only.** All four new tables: RLS on, no policies, `anon` and `authenticated` revoked,
`service_role` granted. All three functions: execute revoked from `public`, `anon` and
`authenticated`; none is `security definer`. The board's and the rooms' tables keep exactly the
grants they had.

**What goes with what.** A church deleted takes everything of its own. A group deleted takes its
series, meetings, seats, answers and reminders. A meeting deleted takes its answers and
reminders (its booking is Rooms & spaces' own; S3-2 cancels it first). A seat deleted takes its
answers and reminders. A series deleted leaves its meetings as one-offs that keep their day. A
room deleted leaves its meetings and series with no room, and its bookings go with it (leaving
the meetings with no booking); a booking deleted leaves its meeting. A person deleted takes their
calendar link; their seats stay with no person, as a board's always have, and so do answers given
from them, with nobody named. A login deleted leaves everything it named, with nobody in its
place. The check deletes a church both ways round (its groups before its rooms, and its rooms
first, which sets its meetings' room and booking to nothing before the meetings go).

**How it goes in.** One transaction, `lock_timeout` 5s, safe to run twice, ends with `NOTIFY
pgrst`. Additive: no table, column, row or existing constraint is dropped or rewritten (the
file's own triggers are dropped and made again, as every file here does). The new columns are
null, `false`, `'board'` or `'members'` by a constant default on every existing row, so no row is
rewritten. The three checks on `church_boards`, the four on `church_board_meetings` and its four
foreign keys are validated as they go in, not `NOT VALID`: the tables are small (a church has a
few boards and some dozens of meetings) and every row passes. The foreign keys take a short lock
on `church_meeting_series`, `church_spaces`, `church_space_bookings` and `auth.users` and read
none of them. The Check and Rollback blocks are at the end of the file.

**The Rollback block** loses every series, answer, reminder and link, and keeps every board,
member, meeting, item, attendance mark, decision, room and booking (meetings made from a series
stay as one-offs). Run it only with the code that reads these columns rolled back first. Its
first line closes (archives) every `kind = 'meeting'` group: once `kind` is gone a huddle would
read as a board, and the board's money yes reads open boards only. Its second takes out a
meeting called off with nothing recorded on it, which would otherwise read as planned again; one
with an agenda, attendance or a decision stays.

**What the deployed code sees the moment it runs** (read in `church_board.py`,
`member_portal_board.py`, `church_money_levels.py`, `church_map.py`, `sample_church_data.py` and
`account_lifecycle.py` at `c62547f7`, and run for real in the check):

- Every read of the board tables names its columns (`MEMBER_FIELDS`, `MEETING_FIELDS`,
  `ITEM_FIELDS`, `DECISION_FIELDS`, the boards' own list); none is `select=*` except the export.
  So no read returns anything new, and nothing reads `kind` or `audience` before S3-2.
- No write sends a new column. A new board is a `board` for its own `members`; a new seat is not
  the list's; a new meeting has no series, length, room or booking and is not called off. Every
  write church_board.py makes (a board and its edit, a seat, its title, leaving and coming back,
  a meeting through planned, in progress, minutes drafted and back, attendance by upsert, the
  agenda carried forward by `on conflict (carried_from)`, a decision, a meeting deleted with its
  agenda) passes every new constraint and trigger untouched (the check makes each of them).
- Nothing writes a `kind = 'meeting'` row, so the four readers above still see only boards.
- The export (`select=*`) carries the new columns of the three board tables: `kind`,
  `audience`, `from_list`, and on a meeting a series id, a room id and a booking id the export
  leaves out or doesn't re-import. None is private. A restored group for the list has its seats
  made again by the next keeping in step (its seats aren't re-imported, as no board's are).

**Checked** on PGlite 0.5.8 (PostgreSQL 18.3; production may be an older Postgres, and nothing
here is new behaviour): `__tests__/church_meetings_db.mjs`, 332 checks, in CI's database
job. Each rule of the file was broken once in a scratch copy to see the check go red
(75 rules; the PR lists them).

### 10.3 Who can't come: the date check's inputs (S3-3)

`POST /church/meetings/check` and Set a meeting's own look before it saves. Its inputs: who comes
(a board's or a meeting's own seats, or the leaders list's people for `leaders` or `office`, as
keeping in step would seat them), one to eight candidate days (none in the past, three months at
most), the time and length, and the room if one is named. For each day:

| Can't come because | Read from | Shown |
|---|---|---|
| away that day | `serve_away` (the facts) | the name, "away" |
| an ask to be away still waiting | `church_away_asks` (`state = 'asked'`), only those the reader may read (`church_schedule.calendar`'s `waiting` rule) | the name, "asked to be away" |
| something that repeats falls on it | `church_away_commitments` (`church_schedule_repeats.days_of`) | the name, "something that repeats": what it is only where `sees_label` says |
| another meeting they're in overlaps the time | `church_board_meetings` of their other groups, `planned` and not called off | the name, "in another meeting": which one only if the reader may open it |

and the room: `free`, `taken` (a booked booking overlaps), or `asked for` (only a request
overlaps; it isn't a block) for that time. Then the day with the fewest who can't come. Never a
reason, a note or what a thing that repeats is. Chief's `check_dates` (#1995, step 5) reads the
first three the same way; S3-3 makes one function both call.

### 10.4 The rename

Board & minutes becomes **Meetings & minutes** wherever `CHURCH_MEETINGS` is open for the
church; with it closed, every word stays as it is today. What changes (S3-2 and the office PR):

| Where | Today | With step 3 open |
|---|---|---|
| The office menu (the frontend; item id `board`) | Board & minutes | Meetings & minutes. `GET /church/board/status` gains `name` and `meetings: bool`, and the menu shows the name it is given |
| The office page's title and empty state | Board & minutes, "Boards" | Meetings & minutes: the meetings and the boards side by side |
| `church_my_week.py:84` (the `meetings` duty's link) | "Open Board & minutes" | "Open Meetings & minutes" |
| `church_money_levels.py:398`, `housing_allowance.py:362` (advice that names the page) | "… in Board & minutes" | "… in Meetings & minutes" |
| `church_board.NOT_CHURCH` | "Board & minutes are for churches" | "Meetings & minutes are for churches" |
| `church_board.py`'s and `member_portal_board.py`'s docstrings, this doc, `docs/MIGRATIONS.md` | Board & minutes | Meetings & minutes (formerly Board & minutes), as each is next touched |

What stays: every route (`/church/board/…`, `/my/board`), the menu item's id, the tables' names,
the `meetings` duty (its label already reads "Meetings and minutes", `church_duties.py:129`), the
office lane's words (`church_areas.py:385`), and the member app's **Board** tab, which is a
board's. Chief's map (`chief_map.py`'s `board` units, the leaders map's) means boards and reads
`kind=eq.board`; nothing of Chief's is renamed. Tests that assert the old words
(`test_housing_allowance.py:300`) change with S3-2.

### 10.5 Who may do what

From church_board's rules (`_access`, `may_write`) and the schedule's (`office_overseers`):

| What | Who |
|---|---|
| Open Meetings & minutes | as Board & minutes today: the meetings' keepers (the owner, an Admin, the Manager holding `meetings`) every group; anyone else the groups they have a seat on (a seat with their login, the list's included) |
| Make a group for every leader or the office | the keepers |
| Make a board, or a meeting of its own people (a check-in) | the keepers, as setting up a board is today |
| Set, edit, skip or call off a meeting; set, edit or end a series | a board or a meeting of its own people: the keepers and its own writer seats (`may_write`, as today); a group for the list: **the keepers only** |
| Agenda, attendance, minutes, decisions | as today on a board; on a group for the list, the keepers only: a seat the list gave reads and answers, and never writes (nobody granted it) |
| Answer for yourself | the person, in the member app (their seat by `contact_id`); a login, in the office app (a seat with that login, or with the login's person) |
| Mark someone's answer for them ("she called to say she can't") | whoever may write the meeting; `by_user_id` says who |
| Read who said what (names) | whoever may open the meeting page. In the member app, a person reads their own answer and how many said they'll be there, never who can't |
| Read an "I can't" note | the person, the keepers, the login that set the meeting, whoever oversees the office |
| Remind the ones who haven't answered | whoever may write the meeting |
| The date check | whoever may set a meeting for that audience; waiting asks only as `church_schedule.calendar` lets them |
| Make or stop a calendar link | the person, in the member app; an office login for its own person, in the office app |
| The church calendar's Meeting and Away | every office login that reads the church calendar: a meeting's name, time and room (as its room booking already shows there); Away, the names and dates of the people on the leaders list, from the facts only, never a kind, a reason or a waiting ask |

### 10.6 Switches

`CHURCH_MEETINGS`: `off` | `owner` | `on`, **unset means `owner`** (the platform owner's own
church, and his own login), as `CHURCH_SCHEDULE` and `CHURCH_WEEK` do. It opens only where
`CHURCH_BOARD` is open too. A group for the list, the date check's leaders and Coming up also
need the leaders schedule (`church_schedule.on`); where it is closed, Set a meeting offers
boards only. `church_meetings.ready()` asks `church_meeting_answers` (one transaction makes all
four tables) by `church_schedule.ready`'s rule, with a `_FORCE` pin that `conftest` sets to False
for every other suite. Until it says yes, Meetings & minutes is Board & minutes exactly: its
name, its reads (no new column named), its writes. Read on **both** services: the routes on
`kmj-intake-server`, the sweep (making meetings ahead, keeping the list in step, reminders,
clearing notes) on `kmj-intake-worker`, as `.env.example` says for the schedule.

### 10.7 The routes the next PRs add

Office (`/church/meetings/…`, beside the board's unchanged `/church/board/…`; session and gate as
`church_board`'s: `require_user`, `business_access.assert_access`, then the keepers' rules):

| Route | Body / answers | PR |
|---|---|---|
| `GET /church/board/status` | gains `name` ("Meetings & minutes" or "Board & minutes") and `meetings: bool` | S3-2 |
| `POST /church/meetings` | `{business_id, name, who: 'leaders'\|'office'\|'group:<id>', starts_at, length_minutes?, place?, video_url?, space_id?, repeat?: {pattern, weekday, nth?, until_on?}}`. For `leaders` or `office` the open group of that name and audience is found, or made (`church_boards_one_list_name`: two presses make one). `{meeting, series?, room: 'booked'\|'requested'\|'taken'\|null}` | S3-2 (one-off), S3-3 (`repeat`, the room) |
| `POST /church/meetings/check` | the date check (10.3): `{business_id, who, days: [..], time, length_minutes, space_id?}` → `{days: [{day, cant: [{contact_id, name, why}], room}], best}` | S3-3 |
| `GET /church/meetings/{id}/answers?business_id=` | `{coming: [seat], cant: [seat + note?], waiting: [seat], moved: bool}`; `note` only for its readers | S3-2 |
| `PUT /church/meetings/{id}/answers` | `{business_id, member_id?, answer: 'yes'\|'cant'\|null, note?}`; no `member_id` is the login's own seat | S3-2 |
| `POST /church/meetings/{id}/remind` | `{business_id}` → how many it went to now, and how many wait out quiet hours | S3-6 |
| `PATCH /church/meetings/{id}` | `{business_id, starts_at?, length_minutes?, place?, space_id?}`: this one (`changed_alone_at` in a series) | S3-3 |
| `POST /church/meetings/{id}/call-off`, `/back-on` | skip one or call off a one-off; and back | S3-3 |
| `PATCH /church/meetings/series/{id}` | `{business_id, from, at_time?, length_minutes?, place?, space_id?, weekday?, pattern?, nth?, until_on?}`: all, from a day on | S3-3 |
| `GET /church/meetings/calendar?business_id=&from=&to=` | the church calendar's two kinds: `{meetings: [{id, name, starts_at, ends_at, room, called_off}], away: [{contact_id, name, starts_on, ends_on}]}` (93 days at most) | S3-3 |

Member app (`include_in_schema=False`, `_signed_in`, never the preview, `rate_limit.allow_strict(
"member_action", …)`, a 303 back with a short code, as Dates' routes are):

| Route | Form | PR |
|---|---|---|
| `GET /my/lead/dates` | "Coming up" at the top: the next 30 days of meetings of every group they have a seat on, soonest first, with their answer and how many are coming | S3-5 |
| `POST /my/lead/dates/meetings/{id}/answer` | `ans (yes\|cant), note` | S3-5 |
| `POST /my/lead/dates/calendar-link`, `/calendar-link/stop` | make a new link (shown once), or stop it | S3-6 |
| `GET /cal/{key}.ics` | public, no session: the feed (10.2) | S3-6 |

### 10.8 Lifecycle registration

All four new tables are in `account_lifecycle.EXPORT_EXCLUDED`, each with its reason, as step 1's
and step 2's are (built, S3-1):

| Table | Reason, in short |
|---|---|
| `church_meeting_series` | cites its group, its room and the login that set it by ids an import mints anew; the meetings it made are exported with the board's tables; a restored church sets its repeating meetings again |
| `church_meeting_answers` | keyed by seats and meetings that aren't re-imported, a private note, and who answered as a sign-in user id |
| `church_meeting_notices` | the reminders' sent-once ledger: the server's own, nothing a church keeps |
| `church_calendar_links` | a hash of a private key that must never come back to life in a restore; the person makes a new link |

The three board tables stay where they are (`BUSINESS_CHILD_TABLES`; the meetings, seats,
agenda, attendance and decisions not re-imported); their export now carries the new columns
(10.2).

### 10.9 PR split

Each is safe alone: `CHURCH_MEETINGS` defaults to `owner`, `ready()` is false until the file is
applied, and `conftest` pins it off for every other suite. The plan first split the rest in four
(server, office, phone, reminders and the link); the server half is split in two here, because
its first part changes who counts as a board and should be reviewed alone.

| PR | Contains | Migration first? |
|---|---|---|
| **S3-1 Migration** (this) | `APPLY-2026-11-21-church-meetings.sql`; its `docs/MIGRATIONS.md` row; `EXPORT_EXCLUDED`; `__tests__/church_meetings_db.mjs` and its `ci.yml` line; this section; the work log. No Python | this is it |
| **S3-2 Groups and answers** (server) | `church_meetings.py`: the switch, `ready`, keeping the list in step, `kind=eq.board` in the four readers of 10.2 **and the lint that pins them**, Set a meeting for a one-off (a group for the list found or made), the answers and the note's readers, the meeting page's who comes and answers, `cant` read as excused at the end, the rename's words; `church_schedule_fake` taught the tables | yes |
| **S3-3 Series, rooms and the date check** (server) | series made ahead, edit one, edit all from a day, skip, end; the room booked, moved and let go; the date check (shared with Chief's `check_dates`); the church calendar's route; the sweep's making ahead and keeping in step; `TICKS` | yes |
| **S3-4 The office** (frontend) | Meetings & minutes: the groups side by side, Set a meeting with the date check, the meeting page's answers and Remind, Meeting and Away on the church calendar | after S3-2 and S3-3 |
| **S3-5 The phone** (member app, this repo) | Coming up on Dates, I'll be there / I can't with the note; whether the Board tab shows meetings | after S3-2 |
| **S3-6 Reminders and the link** (server and member app) | the day-before sweep, Remind's sending, quiet hours, email only without the app, notes cleared at 90 days; the calendar link (make, stop, show once) and the feed | after S3-2 and S3-3 |
| S3-7 (optional) Chief | "Set the leaders meeting for the third Saturday", "who's coming Tuesday?": verbs over S3-2 and S3-3 in the shape of #1995, no rule of their own | after S3-3 |

### 10.10 Decided while writing S3-1

All decided in the build; none is the pastor's call, and any can be reopened with him.

1. **A group that meets is a `church_boards` row**, and step 3 adds no table for groups. Call 1
   is one home, and Board & minutes already is the home of agenda, attendance and minutes.
2. **`kind` (board or meeting) beside `audience`.** Audience alone can't tell a board from a
   check-in of two hand-picked people, and only a board may give the board's yes on money. Every
   existing row is a board.
3. **Seats for the list are member rows kept in step by the server** (`from_list`), not answers
   and attendance keyed by `contact_id`: everything that keys a person on a board keeps working,
   at the price of the four readers of 10.2 and a sync. The reason is in 10.2.
4. **A group for the list is always a meeting and keeps its audience**, enforced in the
   database, so no order of edits can leave a board holding the list's seats or a group for the
   list holding hand-added ones.
5. **`leaders` is both of the list's groups; `office` is its office group plus its leaders who
   have an office login.** (Open question 1.)
6. **A series is its own table**, not columns on the group: a board meets monthly and also holds
   a called meeting, and editing one or all, skipping and ending need their own row. Its rule is
   the commitments' rule, column for column, so the code that works out its days already exists.
7. **One meeting a day of a series** (unique), and **a skipped meeting stays as a row**
   (`cancelled_at`) rather than being deleted, so the series never makes it again, its answers
   stay, and a phone's calendar is told it is off. `made_through` keeps a meeting deleted by hand
   from being made again.
8. **A new rule splits the series** (the old ends, a new starts) instead of moving meetings
   already made to other days.
9. **An answer records the start it was given for** (`for_starts_at`), so a meeting moved needs
   no answers deleted and nobody's "I can't" is silently carried to a new time.
10. **No "maybe".** The calls name two answers.
11. **The note is 200 characters, with `cant` only, and cleared at 90 days**, as a schedule
    reason is.
12. **Reminders are one ledger with two kinds** (`day_before`, `nudge`), claimed by insert, one a
    person a meeting a kind a day; `how` has no value for a text.
13. **One working calendar link a person**, a stopped link stays stopped, only a hash is kept,
    and a link never changes its key: making a new one is the only way to change it.
14. **The room's booking follows Rooms & spaces' own rules** (booked straight away by those who
    may, a request otherwise), and a taken room never blocks the meeting.
15. **Same-church checks are triggers, checked only when a write names what they check**, as
    step 1's and step 2's are, so a foreign key setting something null can never refuse a
    delete. Composite foreign keys carry the church where a row cascades with its parent (an
    answer, a reminder, a series).
16. **The constraints and foreign keys on the board tables are validated as they go in**, not
    `NOT VALID`: small tables, every row passes, and nothing to come back for.
17. **The Rollback closes meeting groups and takes out empty called-off meetings** before it
    drops `kind` and `cancelled_at`, so rolling back can't turn a huddle into a board or bring a
    called-off meeting back onto someone's calendar.
18. **One open group for the list a name** (unique, whatever its case), so two presses of Set a
    meeting never make two leaders meetings, each inviting every leader. Boards keep sharing a
    name if they do.
19. **Its date is 2026-11-21**, and it needs no other step's file but Board & minutes' and Rooms &
    spaces' (both applied in October).

### 10.11 Open questions for the pastor

1. **Does "every leader" include the office staff who lead nothing?** Built as yes: the leaders
   list's two groups both come to a meeting for every leader. If not, `leaders` becomes the
   list's leaders group alone.
2. **Should an Admin read an "I can't" note?** Admins are keepers of the meetings in Board &
   minutes today, and call 3 gives the note to the keepers, so built as yes. (The schedule keeps
   a leader's reason from Admins, decision 7.)
3. **Should the people at a meeting see who else can't come**, by name, in the member app? Built
   as no: they see their own answer and how many are coming; the meeting page in the office
   shows names to whoever may open it.
4. **The calendar link: only meetings, or their own away dates and Sundays they serve too?**
   Built as meetings only for now; the same link can carry more later without a new one.
