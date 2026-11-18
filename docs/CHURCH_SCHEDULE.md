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

**Where it stands (2026-11-18).** Three PRs.

- **S1-1 (#1929, merged)** holds step 1's tables:
  `supabase/APPLY-2026-11-19-church-schedule.sql` (**not applied yet**), its real-Postgres
  check (`__tests__/church_schedule_db.mjs`), the export decision for the four new tables, and
  this doc.
- **S1-2 and S1-3 (#1930, one PR)** hold `church_schedule.py`: the switch, who is on the schedule,
  asking, answering, withdrawing, the calendar and the notice days, behind the office routes of
  section 4.1 (all but the commitments routes). Owner-only by default, and every route answers
  404 until the migration is applied.
- **S1-4** holds `church_schedule_tell.py`: who is told of an ask, an answer and a take-back,
  and the hourly sweep on the worker (what a write couldn't tell, the one nudge, an ask sent on
  when who is over someone changes, a private reason cleared 90 days after the last day).
  Owner-only by default, and silent until the migration is applied: the sweep reads nothing
  before it. No migration of its own.

The member app has no page yet (S1-5), and the Serving Away form and the scheduler are
untouched (S1-6): until those land, an ask exists only for someone who calls the office routes,
and a notice points at the Lead tab or the office app, where the ask isn't on a screen yet.

In sections 3 to 6, what is marked **built** describes code that exists; the rest is still the
plan for the PRs ahead (S1-5 to S1-7, then step 2). Section 7 is what was decided; 7.4 is what
the build of S1-2 and S1-3 decided, and 7.5 what the build of S1-4 decided, each with where it
differs from the plan above it.

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

### 2.1 Step 1: `supabase/APPLY-2026-11-19-church-schedule.sql` (S1-1; not applied yet)

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
- **A fact taken off the old way leaves its ask at `yes`.** `sunday_serving.drop_away` deletes
  the `serve_away` row; until S1-6 teaches it to withdraw the ask instead, and whenever the
  switch is closed, the ask stays a yes with no fact. `church_away_settle` will not make the
  fact again, on purpose. Anything that shows "away" must read the fact, not the ask's state.
- `church_away_asks_untold` (`where told_at is null`) keeps every ask that was answered or
  withdrawn before it was told. The sweep's reads each name their own state (built, S1-4).

### 2.2 Step 2: `supabase/APPLY-2026-11-XX-church-schedule-limits.sql` (the plan for S2-1; not a file yet)

This is a draft, kept here until S2-1 ships it as its own file with its own PGlite check. It carries the two changes S1-1 made to `church_away_settle` (a null state is refused by name; it never makes a fact again for an ask that is already a yes). It was rehearsed once on PGlite over the step 1 file on 2026-11-18 (see the note under it); S2-1 still reads every statement again.

```sql
-- APPLY-2026-11-XX-church-schedule-limits.sql
--
-- The leaders schedule, step 2: the limit (church_schedule_limits.py;
-- docs/CHURCH_SCHEDULE.md). Kevin, 2026-11-18: "making sure that everyone is
-- not gone at the same time on our services. allowing only so many people off
-- at the same time."
--
--   church_schedule_settings.leaders_limit / office_limit
--                           how many of each group may be away on one service
--                           date (null = max(1, people / 4), worked out)
--   church_schedule_settings.service_weekdays
--                           the church's usual service days, 1 Monday … 7
--                           Sunday (null = worked out from its own plans,
--                           else Sunday)
--   church_schedule_department_limits   one number a department
--   church_protected_days   a day nobody takes off (a date and its name)
--   church_away_pairs       two people who can't be away together
--   church_away_asks.excepted       the flags a yes was given over: the
--                           exception, by the owner or whoever oversees the
--                           office (decided_by says who)
--   church_away_asks.team_group_id  a volunteer's ask: the Sunday team whose
--                           leader it went to
--   church_away_settle()    takes the exception with the yes (one more
--                           argument, '{}' by default)
--
-- Server-only, one transaction, lock_timeout 5s, safe to run twice. The one
-- thing replaced is church_away_settle (dropped and made again here, in this
-- transaction, so there is never two of it for PostgREST to choose between);
-- step 1's six-argument calls keep working.
begin;

set local lock_timeout = '5s';

alter table public.church_schedule_settings
  add column if not exists leaders_limit smallint,
  add column if not exists office_limit smallint,
  add column if not exists service_weekdays smallint[];

alter table public.church_away_asks
  add column if not exists excepted text[] not null default '{}',
  add column if not exists team_group_id uuid;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_schedule_settings_limits'
                   and conrelid = 'public.church_schedule_settings'::regclass) then
    alter table public.church_schedule_settings add constraint church_schedule_settings_limits
      check ((leaders_limit is null or leaders_limit between 1 and 99)
             and (office_limit is null or office_limit between 1 and 99));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_schedule_settings_weekdays'
                   and conrelid = 'public.church_schedule_settings'::regclass) then
    alter table public.church_schedule_settings add constraint church_schedule_settings_weekdays
      check (service_weekdays is null
             or (cardinality(service_weekdays) between 1 and 7
                 and service_weekdays <@ array[1, 2, 3, 4, 5, 6, 7]::smallint[]));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_away_asks_excepted'
                   and conrelid = 'public.church_away_asks'::regclass) then
    alter table public.church_away_asks add constraint church_away_asks_excepted
      check (excepted <@ array['over_limit', 'protected_day', 'pair']::text[] and excepted <@ flags);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_away_asks_team_group_id_fkey'
                   and conrelid = 'public.church_away_asks'::regclass) then
    alter table public.church_away_asks add constraint church_away_asks_team_group_id_fkey
      foreign key (team_group_id) references public.groups(id) on delete set null;
  end if;
end $$;

create table if not exists public.church_schedule_department_limits(
  department_id uuid primary key references public.church_departments(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  at_most smallint not null check (at_most between 1 and 99),
  set_by_user_id uuid references auth.users(id) on delete set null,
  set_by_contact_id uuid references public.contacts(id) on delete set null,
  updated_at timestamptz not null default now(),
  constraint church_schedule_department_limits_by_one
    check (set_by_user_id is null or set_by_contact_id is null)
);
create index if not exists church_schedule_department_limits_by_church
  on public.church_schedule_department_limits (business_id);

create table if not exists public.church_protected_days(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  day date not null,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create unique index if not exists church_protected_days_one
  on public.church_protected_days (business_id, day);

create table if not exists public.church_away_pairs(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  a_contact_id uuid not null references public.contacts(id) on delete cascade,
  b_contact_id uuid not null references public.contacts(id) on delete cascade,
  note text check (note is null or char_length(note) <= 140),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  constraint church_away_pairs_ordered check (a_contact_id < b_contact_id)     -- one row a pair
);
create unique index if not exists church_away_pairs_one
  on public.church_away_pairs (business_id, a_contact_id, b_contact_id);
create index if not exists church_away_pairs_b on public.church_away_pairs (business_id, b_contact_id);

-- A department's limit names this church's department; a pair, two of this
-- church's people; a volunteer's ask, one of this church's groups. Each check
-- sits under its own table test (PL/pgSQL doesn't short-circuit `and`).
create or replace function public.church_schedule_limits_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'church_schedule_department_limits' then
    if not exists (select 1 from public.church_departments d
                   where d.id = new.department_id and d.business_id = new.business_id) then
      raise exception 'That department is not in this church';
    end if;
  end if;
  if tg_table_name = 'church_away_pairs' then
    if (select count(*) from public.contacts c
         where c.id in (new.a_contact_id, new.b_contact_id) and c.business_id = new.business_id) <> 2 then
      raise exception 'Both people are this church''s own';
    end if;
  end if;
  if tg_table_name = 'church_away_asks' then
    if new.team_group_id is not null
       and (tg_op = 'INSERT' or new.team_group_id is distinct from old.team_group_id) then
      if not exists (select 1 from public.groups g
                     where g.id = new.team_group_id and g.business_id = new.business_id) then
        raise exception 'That team is not in this church';
      end if;
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_schedule_limits_same_business() from public, anon, authenticated;

drop trigger if exists church_schedule_limits_same_business on public.church_schedule_department_limits;
create trigger church_schedule_limits_same_business
  before insert or update of department_id, business_id on public.church_schedule_department_limits
  for each row execute function public.church_schedule_limits_same_business();
drop trigger if exists church_schedule_limits_same_business on public.church_away_pairs;
create trigger church_schedule_limits_same_business
  before insert or update of a_contact_id, b_contact_id, business_id on public.church_away_pairs
  for each row execute function public.church_schedule_limits_same_business();
drop trigger if exists church_away_asks_team_same_business on public.church_away_asks;
create trigger church_away_asks_team_same_business
  before insert or update of team_group_id on public.church_away_asks
  for each row execute function public.church_schedule_limits_same_business();

-- The decision, now carrying the exception a yes was given over. As in step
-- 1, it never makes a fact again for an ask that is already a yes.
drop function if exists public.church_away_settle(uuid, uuid, text, uuid, uuid, text);
create or replace function public.church_away_settle(
  p_business_id uuid, p_ask_id uuid, p_state text,
  p_by_user uuid default null, p_by_contact uuid default null, p_note text default null,
  p_excepted text[] default '{}')
returns jsonb
language plpgsql set search_path = public as $$
declare
  v public.church_away_asks;
begin
  if p_state is null or p_state not in ('yes', 'no', 'withdrawn') then
    raise exception 'An ask is answered yes or no, or withdrawn';
  end if;
  select * into v from public.church_away_asks a
   where a.id = p_ask_id and a.business_id = p_business_id for update;
  if not found then
    return null;
  end if;
  if (p_state in ('yes', 'no') and v.state <> 'asked')
     or (p_state = 'withdrawn' and v.state not in ('asked', 'yes')) then
    return jsonb_build_object('changed', false, 'ask', to_jsonb(v));
  end if;
  if p_state = 'withdrawn' then
    update public.church_away_asks a
       set state = 'withdrawn', withdrawn_at = clock_timestamp(), updated_at = clock_timestamp()
     where a.id = v.id returning * into v;
    delete from public.serve_away s where s.ask_id = v.id and s.business_id = v.business_id;
  else
    update public.church_away_asks a
       set state = p_state, decided_at = clock_timestamp(), decided_by_user_id = p_by_user,
           decided_by_contact_id = p_by_contact, decided_note = nullif(btrim(left(coalesce(p_note, ''), 300)), ''),
           excepted = case when p_state = 'yes' then coalesce(p_excepted, '{}') else '{}' end,
           answer_told_at = null, updated_at = clock_timestamp()
     where a.id = v.id returning * into v;
    if p_state = 'yes' then
      insert into public.serve_away(business_id, contact_id, starts_on, ends_on, note, ask_id, kind)
      values (v.business_id, v.contact_id, v.starts_on, v.ends_on, '', v.id, v.kind)
      on conflict (ask_id) where ask_id is not null do nothing;
    end if;
  end if;
  return jsonb_build_object('changed', true, 'ask', to_jsonb(v));
end $$;
revoke all on function public.church_away_settle(uuid, uuid, text, uuid, uuid, text, text[]) from public, anon, authenticated;
grant execute on function public.church_away_settle(uuid, uuid, text, uuid, uuid, text, text[]) to service_role;

do $$ declare t text; begin
  foreach t in array array['church_schedule_department_limits', 'church_protected_days', 'church_away_pairs'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

comment on column public.church_schedule_settings.leaders_limit is
  'How many of the leaders group may be away on one service date. Null = max(1, people / 4).';
comment on column public.church_schedule_settings.office_limit is
  'How many of the office group may be away on one service date. Null = max(1, people / 4).';
comment on column public.church_schedule_settings.service_weekdays is
  'The church''s usual service days (1 Monday … 7 Sunday), for dates with no service planned yet. Null = worked out from its own plans, else Sunday.';
comment on table public.church_schedule_department_limits is
  'How many of a department''s people may be away on one service date. No row = no limit. Server-only.';
comment on table public.church_protected_days is
  'A day nobody takes off. Only the owner or whoever oversees the office says yes to an ask on one. Server-only.';
comment on table public.church_away_pairs is
  'Two people who can''t be away together (a_contact_id < b_contact_id, one row a pair). Server-only.';
comment on column public.church_away_asks.excepted is
  'The flags (over_limit, protected_day, pair) a yes was given over: the exception. decided_by says who gave it.';
comment on column public.church_away_asks.team_group_id is
  'A volunteer''s ask: the Sunday team whose leader it went to.';

commit;

notify pgrst, 'reload schema';

-- Check / Rollback: same shape as step 1 (three tables true/0/false; one church_away_settle, seven arguments).
```

**Rehearsed 2026-11-18** (a one-off run on PGlite 0.5.8, over the step 1 file; not a kept
check): the draft applies twice; one `church_away_settle` is left, with seven arguments; a
six-argument call still answers; a yes records `excepted` and a no clears it; an exception that
isn't one of the ask's flags, or is `serving`, is refused; a null state is refused by name; a
team, a pair or a department of another church is refused; a pair is ordered and unique; one
protected day a date; weekdays outside 1 to 7, an empty list and a limit of 0 are refused; the
three tables and both functions are server-only; a person in a pair and the church delete
cleanly. S2-1 turns that into `__tests__/church_schedule_limits_db.mjs`.

### 2.3 Lifecycle registration

All in `account_lifecycle.EXPORT_EXCLUDED` (`:100`), each with a reason sentence. Step 1's four
went in with S1-1; step 2's three go in with S2-1.

| Table | Reason, in short |
|---|---|
| `church_away_asks` | who it went to and who answered are sign-in user ids; a private reason and told marks a restore must not carry; cascade on business and person |
| `church_away_commitments`, `church_schedule_people` | cite people by an id an import mints anew; the church sets them again |
| `church_schedule_settings` | one number; set again |
| step 2: `church_schedule_department_limits`, `church_protected_days`, `church_away_pairs` | same reasons |

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
                                             # raises. ask -> tell_new, answer -> tell_answer, withdraw -> tell_withdrawn
shape(ch, me, row, names) -> dict            # the one place a reason can leave: None unless sees_reason
mine(ch, me, now) -> List[dict]              # my asks, waiting first, 90 days back
waiting(ch, me) -> List[dict]                # asks that went to me and still wait
everything(ch, me, now) -> List[dict]        # every ask: over_all or 403
calendar(ch, me, lo, hi) -> dict             # by group: away (from the facts), waiting (only what `me` may read)
status(ch, me) -> dict                       # GET status
```

**Still ahead** (their own PRs):

```
withdraw_fact(biz, cid, away_id) -> bool     # S1-6. sunday_serving.drop_away: the row names an ask, so withdraw the ask
holds(biz_id, lo, hi) -> List[dict]          # S1-6. the scheduler's hook: [{contact_id, starts_on, ends_on}] for waiting
                                             # asks (and, from S1-7, commitment days). Never raises; [] when off, not
                                             # ready, or the read failed
takes(biz, cid) -> bool                      # S1-6. on(biz) and cid on the kept roster: the Serving Away form asks instead
section(biz, cid) -> Optional[{"waiting": int}]   # S1-5. the Lead tab's switcher; None = no Dates entry
add_commitment(ch, me, body) -> dict; drop_commitment(ch, me, id) -> None    # S1-7
commitment_days(rows, lo, hi) -> Dict[str, List[date]]   # S1-7. pure; 366 days at most
```

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
MEMBER_PAGE = "/my/lead"        # where a person's notice points today; S1-5 moves it to /my/lead/dates
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
                                # clt.deliver(clt.render_email(…)), the link {site origin}/my/lead
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
  - `reason=not.is.null&ends_on=lt.…`: ids only, then `reason` set null by id (section 7, item 14).
- **Sent on** (section 7, item 15, as built in 7.5): a waiting ask whose `to` is empty, a login that has left the
  office, or no longer anyone `nearest()` gives goes to `goes_to()`'s answer, with `told_at` cleared. Never one that
  `needs_no_yes`. An ask whose last day has passed is neither sent on, told nor nudged.
- **Not in the sweep** (corrected in S1-1): the spec had "a yes with no `serve_away` row is settled again". `church_away_settle` writes the yes and its fact in one transaction, so a yes without a fact can only be a fact deleted afterwards, and a second yes answers `changed: false` and writes nothing. That is on purpose: the function must not bring back an away date its person took off.

**`member_portal_dates.py`** (`APIRouter()`; a copy of `member_portal_assign.py`'s shape)

```
HERE = "/my/lead/dates"; DONE, ERRORS, DATES_CSS
view(biz, contact_id, now=None) -> dict         # {mine, waiting, away, commitments, notice_days, people (to pick who covers)}
body(v) -> str; render(biz, site, request, me, active, v, seg, *, err="") -> str
async serve(request, biz, site, me, *, err="")  # GET /my/lead/dates
_go(**q); _code(e) -> str; async _act(request, fn, ok)   # as member_portal_assign :428-479, the switch being church_schedule.on
```

Page order: Waiting for your yes (if any); Ask for time off (dates, kind, private reason, who covers); I can't make it; My dates with their state and Withdraw; Who else is away (name, dates, who covers, never a reason); Things that repeat (S1-7). No ids on the page; ids ride in form addresses.

### 3.2 Existing files changed, step 1

| File | Function | Change |
|---|---|---|
| `sunday_serving.py` | `add_away` `:467` | first line: `if church_schedule.takes(biz, cid): return church_schedule.ask(Church(biz), who(PERSON, cid), {"starts_on": a, "ends_on": b, "kind": "time_off"})`, returning `{"asked": True, "to": name}`; everyone else unchanged |
| `sunday_serving.py` | `drop_away` `:487` | when `church_schedule.on(biz)`: read the row's `ask_id`; if set, `church_schedule.withdraw_fact` (the RPC removes the fact); else the delete as today. While the switch is closed the delete goes as today and leaves that ask at `yes` with no fact; the calendar reads facts from `serve_away`, so nothing shows as away that isn't |
| `sunday_planning.py` | `_Board.__init__` `:932` | after the `serve_away` read: `self.held = church_schedule.holds(biz, self.lo_day, last)` |
| `sunday_planning.py` | `_Board.is_away` `:946-948` | also true for a row in `self.held`. `board.away` and `GET /planning/schedule` (`:1018-1026`) stay untouched, so a pending ask is never listed |
| `member_portal_serving.py` | `away` route `:895-898`, `DONE` `:209` | capture `add_away`'s result in a closure and flash "Asked. {name} will say yes or not this one." (`done=asked`) |
| `member_portal_serving.py` | `render_page` `:466-492` | for someone on the leaders schedule, one line under Away linking to `/my/lead/dates` |
| `member_portal_lead.py` | ContextVars `:59-76`, `_context` `:639`, `_seg` `:826`, `serve` `:660` | new `DATES` ContextVar set from `church_schedule.section`; a `("dates", "/my/lead/dates", "Dates · n")` entry; `if selected == "dates": return await member_portal_dates.serve(...)` |
| `member_portal.py` | `_leads` `:1197` | after the tasks check: `church_schedule.section(biz, me_id) is not None` gives the tab, so an office login's person with no role still reaches Dates |
| `kmj_intake_automation.py` | routers `:453-456`, `:607-610`; jobs `:2039-2053` (f859d05a) | include `church_schedule.router` (done in S1-2) and `member_portal_dates.router` (S1-5); `add_job(g("church_schedule_sweep", _cst.sweep_tick), "interval", hours=1, id="church_schedule_sweep")`, after the hand-overs sweep. Done in S1-4 |
| `sb_clients.py` | `sb_patch_as_service` | takes `redact=` as the GET and the POST do, so a refused update of an ask never logs the row. Done in S1-4 |
| `account_lifecycle.py` | `EXPORT_EXCLUDED` `:100` | the four tables (2.3). Done in S1-1 |
| `__tests__/conftest.py` | near `:169-178` | autouse: `church_schedule._FORCE = False`, so no other suite gains a read; the schedule suites set it True |
| `__tests__/test_sample_church_no_sends.py` | `TICKS` `:97` | `"church_schedule_sweep": "church_schedule_tell:sweep_tick"`. Done in S1-4 |
| `__tests__/church_schedule_fake.py` | `build`, `later` | what a write hands on to be told is kept in `db.later` and not run, so every schedule suite sees that nothing is told inside a write; `later(db)` runs it. Done in S1-4 |
| `.env.example` | near `:718-729` (f859d05a) | the `CHURCH_SCHEDULE` block: off / owner / on, owner by default, read on both services (unset means owner on both), needs the migration. Done in S1-4 |
| `docs/MIGRATIONS.md` | ledger | one row a file. Step 1's is in S1-1 |
| `.github/workflows/ci.yml` | the `test-db` job's list | `node __tests__/church_schedule_db.mjs`. Done in S1-1 |
| `church_my_week.py` (optional, S1-8) | where `from_office` is built `:332-395` | `dates: {waiting: n}` for a login: the office front page's count |

### 3.3 Step 2

**`church_schedule_limits.py`**

```
service_days(ch, lo, hi) -> List[{"day": date, "kind": "service"|"event"|"protected", "name": str}]
usual_weekdays(ch) -> List[int]                 # settings.service_weekdays, else worked out, else [7]
limit_for(ch, grp, department_id=None) -> Optional[int]
away_on(ch, day, grp, department_id=None) -> Set[str]    # facts only (serve_away), chunked in.() reads of 100 ids
department_people(ch, department_id) -> Set[str]         # members of its Sunday teams
departments_of(ch, cid) -> List[dict]
flags_for(ch, asker_cid, grp, starts_on, ends_on, *, department_id=None) -> {"flags": [...], "why": [...]}
goes_up(ch, asker_cid) -> Dict                  # the office overseer, unless the asker is guarded or is them: then the owner
volunteer_plan(ch, cid, starts_on, ends_on) -> {"instant": bool, "flags", "to", "team_group_id", "assignments"}
team_leader(ch, group_id) -> Optional[Dict]     # the team's leaders (group_members.role = leader, by name), else
                                                # church_map.team_head, else the owner
set_limit(ch, me, grp, at_most, department_id=None); may_set_limit(ch, me, department_id) -> bool
protected_days(ch, lo, hi); add_protected(ch, me, body); drop_protected(ch, me, id)
pairs(ch); add_pair(ch, me, a, b, note); drop_pair(ch, me, id)
```

Changes to existing code:
- `church_schedule.ask`: `flags_for`, then `goes_up` when a flag says so.
- `church_schedule.answer`: recompute the flags; pass `p_excepted`.
- `church_schedule.calendar`: counts per service date.
- `sunday_serving.add_away`: the volunteer branch (`volunteer_plan`).
- `sunday_serving.mine` `:101`: a volunteer's waiting asks beside the away chips.
- `member_portal_serving.render_page` `:466-492`: the "waiting for {leader}" chip and the find-a-sub link to `/my/serving?sub=<id>` (`ss.subs` `:422`, `ask_sub` `:434`).

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
- A plain away date (a `serve_away` row with no ask) is shown on the calendar with the same keys: `id` and `kind` null, `state` `yes`, never a reason, `can_withdraw` false.

**Step 1** (built, all but the commitments row)

| Route | Body / query | Answers | Who |
|---|---|---|---|
| `GET /church/schedule/status?business_id=` | | `{open, me: {person: contact_id\|null, group: 'leaders'\|'office'\|null, goes_to: {kind,id,name}\|null, sees_all: bool, can_set: bool}, owner_how, notice_days}` | any seat |
| `GET /church/schedule/people?business_id=` | | `{leaders: [{contact_id,name,what,department}], office: [...], added: [...], removed: [...], can_change}` | a seat whose person is on the schedule; the owner, an Admin, the office overseer. `can_change` is true for the owner and the office overseer only |
| `PUT /church/schedule/people` | `{business_id, contact_id, listed: 'add'\|'remove'\|null, group?}` (`group` is `leaders` unless it says `office`; null puts them back to what the church's data says) | the same shape, as it stands after | the owner, the office overseer (not an Admin: section 7, item 7) |
| `GET /church/schedule/leaders?business_id=&from=&to=` (93 days at most; from today for 62 days when unnamed; days that can't be a window, the very end of the calendar included, are a 400) | | `{from, to, groups: [{key, name, people, away: [ask or plain fact], waiting: [ask], standing: [{contact_id,name,day,label}]}]}`. `people` is how many are in the group. `away` is read from `serve_away`; everyone on the schedule gets name, dates and who covers, and a reason only as `shape()` allows. `waiting` holds only the asks the reader may read (their own, the ones that went to them, and for the owner and the office overseer every one). `standing` is empty until S1-7 | on the schedule, or the owner / office overseer. **The `serve_schedule` holder gets a 403 here unless they are on the schedule themselves** |
| `GET /church/schedule/asks?business_id=&box=mine\|to_me\|all` | | `{asks: [ask]}`. `mine`: waiting first, then the last 90 days. `to_me`: the waiting ones that went to me (for the owner, also one nobody else can answer). `all`: every waiting ask and the last 90 days; the owner and the office overseer only (403) | as the box says |
| `POST /church/schedule/asks` | `{business_id, starts_on, ends_on, kind, reason?, cover_contact_id?, cover_name?, for?: "person:<id>"}` | `{saved: ask}` | a seat for its own person (409 "This login isn't matched to a person here yet" when it has none; 403 when that person isn't on the schedule); `for` only by the owner / office overseer (403), and only for someone on the schedule (400). `kind: cant` only when the first day is inside the church's notice days, two days at least (400 otherwise, pointing to time off) |
| `POST /church/schedule/asks/{id}/answer` | `{business_id, yes: bool, note?}` | `{saved: ask}`; 409 when it had already moved | `may_decide`: 403 for your own ask and (the owner aside) for one you entered; 409 for one that needs no yes |
| `POST /church/schedule/asks/{id}/withdraw` | `{business_id}` | `{saved: ask}` | the asker's login; the owner and the office overseer (403 for anyone else, the login that entered it too) |
| `GET /church/schedule/settings?business_id=` / `PUT` | `{business_id, notice_days}` (0 to 90) | `{notice_days}` | read: on the schedule, the owner, the office overseer; write: the owner, the office overseer |
| `GET /church/schedule/commitments?business_id=` / `POST` / `DELETE …/{id}` (**S1-7, not built**) | `{business_id, label, weekday, pattern, nth?, starts_on, until_on?}` | `{commitments: [...]}` / `{saved}` | a seat for its own person |

**Step 2**

| Route | Body | Who |
|---|---|---|
| `GET /church/schedule/limits?business_id=` | `{leaders: {at_most, set, people}, office: {…}, departments: [{id, name, at_most\|null, people, can_set}], service_weekdays, worked_out: bool}` | on the schedule; the `serve_schedule` holder sees `departments` only |
| `PUT /church/schedule/limits` | `{business_id, group: 'leaders'\|'office', at_most\|null}` or `{business_id, department_id, at_most\|null}` or `{business_id, service_weekdays\|null}` | groups and weekdays: the owner, the office overseer (not an Admin: section 7, item 7). A department: its leader, its overseer, the owner, the office overseer, or `church_duties.holds(biz, user, "serve_schedule")` |
| `GET /church/schedule/days?business_id=&from=&to=` | `{days: [{day, kind, name, leaders: {away, at_most}, office: {…}, departments: [{id, away, at_most}]}]}`: counts and names only | as `limits` |
| `GET` / `POST` / `DELETE /church/schedule/protected-days` | `{business_id, day, name}` | read: on the schedule; write: the owner, the office overseer |
| `GET` / `POST` / `DELETE /church/schedule/pairs` | `{business_id, a_contact_id, b_contact_id, note?}` | the owner and the office overseer only, reads too |
| `GET /church/schedule/volunteers?business_id=&from=&to=` | by department: volunteers' facts and waiting asks, never a leader's ask or anyone's reason | `serve_schedule` holders, the owner, the office overseer, an Admin, each department's leader and overseer for their own |

### 4.2 Member app

All `include_in_schema=False`, `_signed_in`, never the preview, `rate_limit.allow_strict("member_action", …)`, a 303 back to `/my/lead/dates?done=…|err=…`.

| Route | Form | Who |
|---|---|---|
| `GET /my/lead/dates` | | `church_schedule.section` is not None |
| `POST /my/lead/dates/ask` | `start, end, kind (time_off\|commitment), reason, cover (contact id or ''), cover_name` | on the leaders schedule |
| `POST /my/lead/dates/cant` | `start (today by default), end, reason` | on the leaders schedule |
| `POST /my/lead/dates/{id}/withdraw` | | the asker |
| `POST /my/lead/dates/{id}/answer` | `ans (yes\|no), note` | it went to this person (or to the login this person is) |
| `POST /my/lead/dates/commitments` | `label, weekday, pattern, nth, start, until` | on the leaders schedule (S1-7) |
| `POST /my/lead/dates/commitments/{id}/remove` | | theirs |

- Unchanged addresses with new behaviour: `POST /my/serving/away` and `/my/serving/away/remove` (3.2).
- Step 2 adds nothing new for volunteers: the same two routes; the team leader answers on `/my/lead/dates`.

---

## 5. The rules, as a decision table

**Definitions**
- `to` = `co.above(ch, person)[0]`, else the owner's login.
- "Told" = `church_schedule_tell` (built, S1-4; person: push and the church thread, email if no phone was reached; login: staff push and email). Once each, never with the reason or the note. A planned ask, an answer and the nudge wait out the church's quiet hours; "can't make it" and a take-back don't.
- "Hold" = `church_schedule.holds`, so the scheduler won't ask them.

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
| Core leader using Serving, Away | | `to` | as planned / short | an ask (`time_off`, no reason), not a row | `to`; the page says "Asked" |

**Answers and withdrawals**

| Event | Written | Told |
|---|---|---|
| Yes (by `to`; in the office app also the owner or the office overseer) | settle yes: the fact is written, the hold becomes a fact | the asker |
| Not this one (optional note) | settle no: no fact, the hold ends | the asker |
| Withdraw by the asker (`asked` or `yes`) | settle withdrawn: the fact is deleted | `to`, when they had been told of it (`told_at`); nobody otherwise. Sent once, never tried again (7.5) |
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

**Standing commitments**
- No yes is needed. `to` is told once when one is added (`told_at`; S1-7 builds this, S1-4 tells nobody of a commitment).
- They show on the calendar; from S1-7 they hold the person from the scheduler.

### Step 2

Computed in `flags_for` when asked, and again at yes.

| Case | Goes to | Flags | Written | Told |
|---|---|---|---|---|
| Core leader / office, every counted date under the group's limit, no protected day, no pair | as step 1 | as step 1 | as step 1 | as step 1 |
| A counted date already at the limit (facts for that group on that date >= limit) | `goes_up`: the office overseer, else the owner. For a pastor or elder (`co.is_guarded`), or the office overseer themself: the owner | `+over_limit` | ask `asked`; hold | `goes_up`; step 1's `to` for their information |
| A protected day in the range | `goes_up` | `+protected_day` | same | same; the page names the day |
| The other of a pair has a fact or a waiting ask on any of the same days | `goes_up` | `+pair` | same | same; the asker sees "This overlaps with someone you can't be away with" and no name |
| A yes on a flagged ask | only the owner or the office overseer (403 for anyone else) | | settle yes with `p_excepted` = the flags still true | the asker |
| A yes on an unflagged ask that became over / protected / paired since it was asked | the decider gets 409; the ask is re-addressed to `goes_up` (`to_*` changed, `told_at` cleared, flags added) | the new flags | still `asked` | `goes_up` |
| Can't make it, any of the above | nobody decides; never blocked | the flags are recorded | fact at once | `to`, at once; `goes_up` too when flagged |
| The dates hold no service date and no protected day (a Monday to Thursday trip) | as step 1 | never `over_limit` | | |
| Volunteer: none of their departments' dates full, and no yes to serve in the range | none | none | plain `serve_away` row, instant, as today | nobody |
| Volunteer: a department's date is full | the team's leader (`team_leader`: the team's leaders, else `church_map.team_head`, else the owner) | `over_limit` | ask `grp='volunteers'`, `team_group_id`, `department_id`; hold | the leader; the page offers Find a sub |
| Volunteer: already said yes to serve one of the days | the leader of that place's team | `serving` (and `over_limit` if so) | same | same; each such Sunday links to `/my/serving?sub=<assignment>` |
| The team leader says yes | | | fact; each of their yes places in the range with no sub agreed is opened as `sunday_serving.cant_make_it` does (`:451-463`) | the volunteer; Planning's own alerts tell the office |
| Volunteer, sick today | none | | they use Can't make it on the place itself (`ss.cant_make_it`, today's path); an away row for today stays instant | as today |

### Which dates count ("service date")

For a range, in the church's own clock (`ch.tz`):
1. Every day with a live `worship_services` row of `kind='service'` (not a template, not archived).
2. For days with no such row: the church's usual service weekdays.
   - `settings.service_weekdays`; else
   - any weekday that holds two or more of its `kind='service'` rows from 8 weeks back to 8 weeks ahead; else
   - Sunday (the platform's rule today, `sunday_planning.py:847`).
3. Every protected day.
4. A `kind='event'` date counts toward **department** limits only (only the Volunteers' teams serve it, `sunday_planning.py:902`).

Counting:
- The leaders and office limits count distinct people of that group with a fact on the date.
- A department's limit counts distinct members of its Sunday teams.
- Waiting asks are shown ("2 away, 1 waiting") and not counted; the recount at yes covers the gap.

---

## 6. PR split

Each is safe alone: `CHURCH_SCHEDULE` defaults to `owner`, `ready()` is False until the file is applied, and `conftest` pins it off for every other suite.

### Step 1

| PR | Contains | Tests | Migration first? |
|---|---|---|---|
| **S1-1 Migration** (this doc's PR) | `APPLY-2026-11-19-church-schedule.sql`; `docs/MIGRATIONS.md` row; `EXPORT_EXCLUDED`; `__tests__/church_schedule_db.mjs` and the `ci.yml` line; `docs/CHURCH_SCHEDULE.md`; the worklog entry | PGlite, 152 checks: twice changes nothing, with rows there; the RPC (yes writes one fact, a second yes none, withdrawn deletes it, no leaves none, another church gets null, a bad or null state raises); `serve_away_ask_guard`; `church_away_asks_one_open`; the same-business triggers; a person or church deleted takes its rows, in either order the foreign keys fire; a login deleted leaves the ask; server-only under Supabase's default grants. `test_export_import` green | this is it; apply after review. Nothing reads it yet |
| **S1-2 Switch and roster** (built, in one PR with S1-3) | `church_schedule.py`: switch, `ready`, the gate, `roster`, `roster_kept`, `set_listed`, `office_overseers`, `goes_to`; `GET status`, `GET/PUT people`; the `conftest` pin; `.env.example` | `test_church_schedule_roster.py` at the four churches: roster equals `leaders_room_people` split by `Church.person_login`, and `set(ch.person_login)` equals `mpm.office_contacts` (pinned as `Church.held` is to `standing`); someone in both counts in leaders; add / remove; Riverside is empty; `goes_to` for a department leader, a group leader with no role, a Manager, an Admin, a senior and the owner; `off` and other churches under `owner` get 404; before the migration 404; a failed read 503; `test_business_access_ratchet` green | no (404 until applied) |
| **S1-3 Asks** (built, in one PR with S1-2) | `ask`, `answer`, `withdraw`, `shape`, `mine`, `waiting`, `calendar`, settings; the `asks`, `leaders` and `settings` routes; no notices yet | `test_church_schedule.py`: every step-1 row of section 5 through the real routes; the RPC faked on `ThreeDB` (as `test_church_duties.py:77`); **privacy**: the reason is absent for another leader, for an Admin and for the `serve_schedule` holder, present for the asker, `to`, the owner and the office overseer; `serve_away.note` stays `''`; a failed write is a 503 with nothing saved; races give 409 | yes |
| **S1-4 Notices** (built) | `church_schedule_tell.py`; the hooks in `church_schedule.ask / answer / withdraw` (`_after`); the sweep job (with the one nudge after 3 days, the re-address and the 90-day clearing of reasons: section 7, items 1, 14, 15); `TICKS`; `.env.example` "both services"; `sb_patch_as_service(redact=)` | `test_church_schedule_tell.py`, at New Hope through the real routes and senders: no reason and no note in any push, email, conversation line or log line, and the words the same with or without them; nothing told inside a write, and a failed notice never fails it; person vs login channels; email only when no phone rang; `cant` ignores quiet hours, a planned ask and an answer wait; claim before send, let go when nothing went; told once (two sweeps at once, the write's notice and the sweep); a yes nobody gave tells nobody; `_login_email` None is not claimed; one nudge, never a second; a waiting ask is sent on when who is over them changes, their login leaves the office or it names nobody, never one that needs no yes, and never round the same step; the reason, and only the reason, is gone 90 days after the last day; every read names its state and is paged (1,003 rows); take-backs; where a notice points; a sample church is told nothing; before the migration and with the switch off the sweep reads nothing; on `owner` one church is swept. Each rule was broken once to see its test go red (the PR lists them) | no (silent until it is applied) |
| **S1-5 Dates on the Lead tab** | `member_portal_dates.py`; `member_portal_lead` (`DATES`, `_context`, `_seg`, `serve`); `member_portal._leads`; router include | `test_member_portal_dates.py` (the `test_member_portal_assign` harness): the page for a leader, for someone over people, for an office person with no role, for the owner's person; no ids and no office words on screen; a reason only where allowed; every POST; preview never writes; cross-site refused, `Origin: null` allowed; closed means no Dates entry and 404 writes; a member-app session never gets the owner's across-the-board view | yes |
| **S1-6 Serving Away form and the scheduler hold** | `sunday_serving.add_away / drop_away`; `member_portal_serving` flash and line; `sunday_planning._Board` `held` | `test_sunday_planning_holds.py`: a waiting ask makes `candidates` say away, `do_ask` 409 and `do_fill` skip; it is absent from `/planning/schedule`'s `away`; closed or a failed read gives no extra read and no 503; a volunteer's Away is byte-for-byte as before (`test_sunday_serving` untouched); a core leader's Away makes an ask; removing an approved date withdraws the ask | yes |
| **S1-7 Things that repeat** | commitments routes, the Dates section, `calendar` `standing`, `holds` adds `commitment_days` | weekly / every other / nth and "last"; `until`; the scheduler holds them on those days only; 10 a person | yes |
| S1-8 (optional) My week count | `church_my_week` `dates` | a login sees how many wait for their yes | yes |

**Turning on:** `CHURCH_SCHEDULE` is read on **both** `kmj-intake-server` (the routes, and the notice that follows each write) and `kmj-intake-worker` (the hourly sweep). Unset means `owner` on both, so nothing needs setting for the platform owner's own church; to open it wider, or to close it, set the same value on both. The sweep also works only the churches `CHURCH_ASSIGNMENTS` is open for (7.5). The scheduler hold (S1-6) is read on the web service.

### Step 2

| PR | Contains | Tests | Migration |
|---|---|---|---|
| **S2-1 Migration** | the limits file; ledger; `EXPORT_EXCLUDED`; `church_schedule_limits_db.mjs` | twice is a no-op; a pair is ordered and unique; one protected day a date; the seven-argument settle with `excepted`, and the six-argument call still works; server-only | this is it |
| **S2-2 Service days and limits (read and set, nothing enforced)** | `service_days`, `usual_weekdays`, `limit_for`, `away_on`, `department_people`; `GET/PUT limits`, `GET days`, `GET volunteers` | the default is `max(1, n // 4)`; who may set each number (the department's leader and overseer as persons from the member app are deferred; a login whose person leads it may); a Saturday church's weekdays worked out from its plans; event dates count for departments only; a read over 1,000 rows is paged or chunked | yes |
| **S2-3 Limit and protected days for leaders** | `flags_for`, `goes_up`; `ask` / `answer` wired; the protected-days routes; the Dates page words | each step-2 leader row; the recheck at yes; a pastor's or elder's flagged ask goes to the owner, never the office overseer; `excepted` recorded; `cant` never blocked | yes |
| **S2-4 Pairs** | the pairs routes; `+pair` | the second ask goes up; the asker never sees the other's name; only the owner and the office overseer read pairs | yes |
| **S2-5 Volunteers** | `volunteer_plan`, `team_leader`; `add_away` branch; My serving chips and the sub offer; yes opens their places | instant when free; an ask when full or already serving; no-leader team goes to the department leader, then the overseer, then the owner (the #1719 cases, `test_church_map_serve.py`); the coordinator never sees a leader's ask | yes |

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
| 10 | A yes to a volunteer who already said yes to serve | It opens those places, as `sunday_serving.cant_make_it` does. It runs after the RPC, not in its transaction; failures are logged, and Planning's own "still no answer" alerts catch the rest. |
| 11 | Standing commitments and the limit | Shown, and they hold the person from the scheduler. Not counted toward a limit, never blocked. |
| 12 | `holds()` on a failed read | Fails open (returns `[]`), on purpose, and its docstring says why: the other choice is Who serves when failing whenever this table blips. The worst case is asking someone whose ask is still waiting. |
| 13 | Other readers of `serve_away` (`sunday_serving.mine`, `free_sundays`) | Left as they are: they don't see waiting asks, so a leader with a pending ask can still be shown an open place on their own page. |
| 14 | Private reasons kept for good | The sweep clears `reason` 90 days after `ends_on` (built, S1-4). Reasons can be medical. Only `reason`: the ask, and the note that came with its answer, stay (7.5). |
| 15 | Asks made before a role change | The sweep re-addresses a waiting ask whose `to` is no longer who `goes_to` gives, and clears `told_at` (built, S1-4). As built, "no longer" means no longer anyone at the nearest step over the asker (7.5). |
| 16 | Away dates written before the switch opened | A core leader's old instant `serve_away` rows have no ask. The calendar shows them as plain "away" with no kind, and `drop_away` deletes them as today. |
| 17 | Roster cost | Kept 60 seconds a replica for the member side; an add or remove on one replica can show up to a minute late on another. The office routes always read fresh. |
| 18 | Two clocks | `ch.tz` for "today" and notice; the scheduler keeps its own zone for the service day. |
| 19 | Step 2 drops and re-makes `church_away_settle` | Kept, and its file's header says so. It avoids two functions for PostgREST to choose between; a six-argument call from an old replica still resolves through the new argument's default. |
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
  stays: the brief said only the reason. Say so if the note should go with it.
- **Where a notice points.** A person: `{the church's site}/my/lead` in the email and
  `/my/lead` in the conversation (the Lead tab's front page, the nearest page leaders have
  today). A login: the office app (`church_office_tasks._link`), and the push opens My week
  (`church_assignments.NAV`). Neither place shows the ask yet. **S1-5 moves the person's link
  to the Dates page** (`MEMBER_PAGE`, one constant); the login's moves when the office screen
  exists.
- **`sb_clients.sb_patch_as_service` takes `redact=`**, as the GET and the POST already did.
  Every update this module makes to `church_away_asks` uses it, and asks back for `id` only.
- **`church_schedule.nearest`** is new and `goes_to` is its first row: what `goes_to` answers
  is unchanged.
- **The tells answer with a word** (`told`, `held`, `taken`, `unsent`, `unread`, `none`,
  `closed`) where the plan had `None`, for the sweep's counts and the tests.
