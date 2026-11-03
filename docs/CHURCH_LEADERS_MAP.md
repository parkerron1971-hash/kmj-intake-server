# Church leaders, step 1: the map

Kevin, 2026-11-03: take the leaders flow further. Show how elders, pastors and ministry leaders connect, with their roles and responsibilities, to the admins, the lead pastor and the people. It has to work for every church that subscribes, and Chief must be able to adjust it later: "what i don't want is what i build works for love city but is broken and messed up for other churches."

He approved the design (artifact https://claude.ai/artifact/4V41zJz1kEJGdeo4J9D2Ym), with four yeses:
- one engine;
- each church's structure is data;
- new churches start from drafts;
- the session drafts Love City's sheet, and steps 1 and 2 come before 3.

Every church runs on one engine, and each church's structure is data. Step 1 adds that data and makes the engine read it in this order: the map first, then today's rule. A church's routing changes only where its map says something, and only where `CHURCH_MAP` is open. Love City opens first.

Line numbers are trunk: `origin/main` for the backend, `origin/module-system` for the frontend, as of 2026-11-03. Re-check them before you edit.

The three lines (from the approved 10-27 plan):
- **Shepherding:** shepherds care for families.
- **Oversight:** overseers → department leaders → team and group leaders → volunteers.
- **Support:** office logins holding duties help departments and never direct them.

One rule: every department has one leader, one overseer and one office helper (a duty).

## Decisions taken (2026-11-03)

1. **A team or group leader's late items go first to their department's leader, then to its overseer.** This mirrors today's first step to the ministry role (church_roles.py:669-673). A department leader's own late items go to the department's overseer.
2. **Defaults for new custom roles:** pastoral roles shepherd by default; other jobs don't. The church-wide Ministers switch stays for the roles that follow it (`can_shepherd` null).
3. **Money levels:** only the owner may change a church's levels, and every change is logged (`map_by`/`map_at`, plus a log line).
4. **Love City's real department sheet** is step 4. The session drafts it from the system and from the 10-27 plan's twelve departments, and Kevin corrects it once. The fixture's people are made up.

## 0. Rules every PR keeps

**(a) Words suggest, data decides.** A title or a key may *suggest* a value once, when the thing first appears. The suggestion is stored as data the church can change. No code reads a title word or a role key at read time to decide behavior. Today's readers, and what replaces each:

| Today | Replaced by | PR |
|---|---|---|
| `SHEPHERD_TITLE`/`MINISTER_TITLE` on titles, church_shepherding.py:61-62, :163-178 | `can_shepherd` | 4 |
| The stream's word in key+title as a tie-break, church_follow_up.py:386-388 | `made_for` | 4 |
| The `executive_pastor` key/catalog_key query, church_duties.py:437-438 (`_exec_users`); church_office_tasks.py:45, :83-85. (church_duties.py:81 is the same string used as the pseudo-lane key for the lanes and starter sets; it is not a role read, and PR 9 decides whether to rename it.) | the `office_overseer_roles` setting | 7 |
| `_AREA_WORDS` on titles and team names at read time, church_areas.py:140-202. It sets a login's default areas through `_guesses` :295-330, so it is behavior | the department's area, then a stored guess | 8 |
| `job_for_title` falling back to "care", church_roles.py:1093 | §4 | 8 |

These stay, because they are structure and not words:
- `job`: which streams a role may take (church_roles.py:505-511), the senior role at the top of every chain (:693-699), and the office/kids refusals (church_follow_up.py:839-842).
- `covers`.
- LEGACY definitions, looked up by stored keys (church_follow_up.py:278-291).

Reads that only change wording are display, and they move in step 2: `role_name` (church_follow_up.py:887) and LeadersRoles.tsx:119 (`key === 'team_leader'`).

**(b) The three test churches.** Every leaders PR runs `__tests__/church_three.py`, which builds Love City, Grace Baptist and New Hope, along with the scenario test (§6).

**(c) Love City is preserved.** Existing roles, holders, shepherds, follow-ups and behavior must come out exactly as today, and the preservation tests prove it.

**(d) The switch.** `CHURCH_MAP = off | owner | on`, default `owner`. It follows the church_leader_tasks.py:94-119 pattern:
- `open_to(user)` opens the office routes to the platform owner's login.
- `church_open(biz)` opens the engine (sweeps and the member side) to the platform owner's church (`member_asks.platform_church`, :193-213).
- When closed, today's code runs unchanged.
- It must be set on both Railway services.

## 1. Data model

New file `supabase/APPLY-2026-11-04-church-map.sql`. It is idempotent, additive and server-only.

```sql
begin;
-- Roles: the switches. "Takes prayer requests" / "takes care needs" stay in handles.
do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema='public'
                   and table_name='church_role_defs' and column_name='can_lead') then
    alter table public.church_role_defs
      add column can_shepherd  boolean,                       -- null = follows church_shepherd_settings.ministers
      add column can_oversee   boolean not null default false,
      add column can_lead      boolean not null default false,
      add column can_board_yes boolean not null default false,
      add column can_see_all   boolean not null default false,
      add column made_for      text[]  not null default '{}';  -- streams it is "the role made for"
    alter table public.church_role_defs disable trigger church_role_defs_guard;
    update public.church_role_defs d set                      -- §2, once
      can_shepherd = case when d.job='senior' then true
                          when d.job='pastoral' and d.title ~* 'pastor|elder|bishop|overseer|shepherd' then true
                          when d.job='pastoral' and d.title ~* 'minister' then null else false end,
      can_oversee = d.job in ('senior','pastoral'),
      can_lead    = d.job in ('senior','pastoral','ministry','team','welcome','teach'),
      can_see_all = d.job = 'senior',
      made_for    = array(select s from unnest(d.handles) s
                          where strpos(d.key||' '||lower(d.title), left(split_part(s,'_',1),6)) > 0);
    alter table public.church_role_defs enable trigger church_role_defs_guard;
    alter table public.church_role_defs add constraint church_role_defs_made_for check (made_for <@ handles);
  end if;
end $$;

-- People: a holder answers to a person
alter table public.church_leader_roles
  add column if not exists answers_to_contact_id uuid references public.contacts(id) on delete set null;

-- Church settings (null = today's platform rule)
alter table public.church_role_settings
  add column if not exists pastor_from_cents integer check (pastor_from_cents between 0 and 10000000),
  add column if not exists board_over_cents  integer check (board_over_cents between 0 and 10000000),
  add column if not exists pastor_yes_roles      uuid[] check (cardinality(pastor_yes_roles) <= 20),
  add column if not exists office_overseer_roles uuid[] check (cardinality(office_overseer_roles) <= 20),
  add column if not exists map_by uuid, add column if not exists map_at timestamptz;
-- + church_role_settings_levels: board_over_cents >= pastor_from_cents when both set (added if missing)

create table if not exists public.church_departments(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  leader_contact_id   uuid references public.contacts(id) on delete set null,
  overseer_contact_id uuid references public.contacts(id) on delete set null,
  support_duty text check (support_duty ~ '^[a-z][a-z0-9_]{1,39}$'),        -- a church_duties.CATALOG key
  area text check (area in ('worship_media','people_care','giving_money','kids_youth',
                            'groups_classes','messages_safety','website_outreach','office')),
  status text not null default 'active' check (status in ('draft','active','archived')),
  source text not null default 'office' check (source in ('office','chief','template')),
  sort smallint not null default 0 check (sort between 0 and 999),
  updated_by uuid, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  constraint church_departments_two check (leader_contact_id <> overseer_contact_id));
create unique index if not exists church_departments_name
  on public.church_departments(business_id, lower(btrim(name))) where status <> 'archived';
create index if not exists church_departments_leader   on public.church_departments(leader_contact_id)   where status='active';
create index if not exists church_departments_overseer on public.church_departments(overseer_contact_id) where status='active';

-- What hangs from a department: the five leader sources, plus the loose ones
create table if not exists public.church_department_units(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  department_id uuid not null references public.church_departments(id) on delete cascade,
  kind text not null check (kind in ('group','role','board','worship_ministry','serve_option','space','check_line')),
  group_id uuid references public.groups(id) on delete cascade,              -- any kind, incl. serve_teams / 'ministry'
  role_id uuid references public.church_role_defs(id) on delete cascade,
  board_id uuid references public.church_boards(id) on delete cascade,
  worship_ministry_id uuid references public.worship_ministries(id) on delete cascade,
  label text not null default '' check (char_length(label) <= 120),          -- serve option / 'youth'|'kids' / check line
  created_at timestamptz not null default now(),
  constraint church_department_units_shape check (
    num_nonnulls(group_id, role_id, board_id, worship_ministry_id)
      = case when kind in ('serve_option','space','check_line') then 0 else 1 end
    and (kind <> 'group' or group_id is not null) and (kind <> 'role' or role_id is not null)
    and (kind <> 'board' or board_id is not null) and (kind <> 'worship_ministry' or worship_ministry_id is not null)
    and (kind not in ('serve_option','check_line') or label <> '') and (kind <> 'space' or label in ('youth','kids'))));
-- one department per thing: unique (business_id, group_id) where group_id is not null; same for role_id,
-- board_id, worship_ministry_id; unique (business_id, kind, lower(label)) where label <> ''; index (department_id)

-- Areas: picks vs Chief's stored guesses
alter table public.church_area_places
  add column if not exists by text not null default 'church' check (by in ('church','guess')),
  add column if not exists word text not null default '' check (char_length(word) <= 40);
```

Guards and permissions:
- Each guard uses nested IFs (the rule in APPLY-2026-10-17-church-leaders-trigger-fix.sql).
- `church_map_same_business()`: departments (leader and overseer contacts) and units (department, group, role, board, worship ministry) must all be in the same business.
- `church_answers_to_guard()`: the answers-to person is not the holder, and is in the same business.
- `church_role_settings_guard()`: every role id in either array is this business's. It is created after the backfill.
- Guard functions are revoked from public, anon and authenticated.
- Both new tables get RLS on, anon/authenticated revoked and service_role granted, using the loop at APPLY-2026-10-17-church-role-library.sql:72-78. No policies.
- Rollback: drop the two tables and the new columns.

**"One leader, one overseer" is two explicit columns.** A column holds one person, so the rule is a fact of the schema rather than a pick among a role's holders at read time. The chain needs a person, and a role-derived answer can only give one by emailing every holder (church_roles.py:677-700), which is what we are fixing. Team and group leaders stay derived from their own sources; a department only links to them.

## 2. Backfill: today's rules, frozen once, so day one changes nothing

| Column | Value | Today's source |
|---|---|---|
| `can_shepherd` (every row, any status) | senior → true; pastoral with a shepherd-word title → true; pastoral with "minister" → **null** (follows the Ministers setting, so ShepherdingPage.tsx:409 `switch==='ministers'` keeps working); otherwise false | church_shepherding.py:163-178 |
| `can_lead` | the job is in `LEADER_JOBS` | member_portal_messaging.py:159 |
| `can_oversee` | senior or pastoral | no reader today, because there are no departments |
| `can_board_yes` | false | the board's yes comes only from church_board_members (church_money_levels.py:194-235) |
| `can_see_all` | senior | JOBS senior "sees" (church_roles.py:77); no reader in step 1 |
| `made_for` | the streams whose word is in key+title | church_follow_up.py:386-388; identical by construction |
| `answers_to_contact_id` | null | the map doesn't know, so today's chain applies |
| `office_overseer_roles` | the active roles with key or catalog_key `executive_pastor`, per church: `insert … on conflict do update … where office_overseer_roles is null` | church_duties.py:437-438, church_office_tasks.py:83-85; the last key read |
| `pastor_from/board_over_cents`, `pastor_yes_roles` | null, meaning $500 / $2,500 and every active senior role | church_money_levels.py:70-71, :167 |
| `church_area_places.by/word` | 'church', '' | existing rows are the church's own picks |

Two notes on the backfill:
- Code never writes null to the two settings arrays. It writes `'{}'`, meaning "none named", which falls back to the owner, so a re-run fills only rows that were never set.
- The guard trigger is disabled during the update because `needs_class` has no foreign key (church_role_library.sql:93-98). A deleted course would otherwise abort the migration (inferred).

**Not auto-created, for any church including Love City:**
- departments and units;
- holder links (answers-to);
- money limits and pastor's-yes picks;
- any switch flip beyond today's rule.

Every department names an overseer, and an overseer changes who hears about a late item. Creating departments from groups of kind 'ministry' or from `oversees_teams` would change routing on day one, and would mean guessing people from names. Instead, `church_map.propose(biz)` returns a read-only draft from those sources; it is the hook for step 2. Love City's map is entered after PR 5, on Kevin's word, from the department sheet (step 4), following docs/CHURCH_DUTIES.md:28-31 rule 3.

## 3. Code changes

**Fallback order, for every reader:**
1. `CHURCH_MAP` is closed, or `church_map.ready()` is false (the migration isn't applied): today's code runs.
2. Open and ready: the map decides wherever it knows (a person, a department, a setting), then the role's switches, then today's rule.
3. Open and ready but `load()` failed: the caller does what it does today on a failed read. The sweep skips that church (church_follow_up.py:1234-1235) and routes return 503. It never drops silently back to the old people.

**New `church_map.py`:**
- `mode/open_to/church_open`.
- `ready()`: one probe of the new columns, remembered per process once true.
- `load(biz) → Map | None`: five reads of its own. `church_roles.defs`'s select (:522-523) is not touched, so it can never fail before the migration.
- `can(m, d)`: the seven switches. Prayer is `prayer_shared` in handles and care is `care_need` in handles. Handles stay bounded by the job (:505-511).
- `chain_for(m, defs, holders, person, role, *, team='', group_id=None, skip=())`: the same shape as `chain_above`, a list of (label, [people]), nearest first. Each step up from person P:
  1. P leads an active department → that department's overseer. If P leads several, use the one whose units hold the item's team, group or role; otherwise every overseer of P's departments, deduplicated.
  2. The item's team, group or role is in a department P doesn't lead → that department's leader. The next step is its overseer (decision 1).
  3. P's holder row names an `answers_to_contact_id` → that person.
  4. Otherwise → `cr.chain_above` from P's role, skipping anyone already named. This is today's chain, including the senior fallback.
- People count only while they hold an active role with the right switch: an overseer needs `can_oversee`, a leader `can_lead`, an answers-to person any active role. Otherwise they are passed over, like an empty role. The `support_duty` is never a step in the chain: support helps and never directs.
- Writes: `save_department`, `archive_department`, `set_answers_to`, `save_settings`. Validation:
  - switches as above;
  - the duty must be in `church_duties.CATALOG`;
  - serve options must come from `cfu.teams` (church_follow_up.py:443-460);
  - check lines must come from the church_checks settings (:364-371);
  - a thing can hang from only one department.
- Routes under `/church/map` (404 unless `open_to`):
  - GET (manager seat and up) with `gaps`: missing leader, overseer or duty; a leader who no longer qualifies; a serve option no longer on the card.
  - PUT departments, PUT answers-to: owner or admin.
  - PUT settings: owner or admin for the role picks; owner only for money levels (decision 3).

**Changes by module:**

| Module | What changes (map first) | PR |
|---|---|---|
| church_roles.py | Jobs get default switches. Every TYPES row carries explicit switch values, pinned equal to the backfill oracle; the nondenom Executive Pastor row gets `office=True`. `ensure_library`/`set_type`/`create_role` write the switches, and an `office` row adds itself to `office_overseer_roles`. `_FIELDS` (church_roles.py:722-723) and `_RoleDef` (church_router.py:128-140) accept `can_*` and `made_for` (trimmed when handles change). `library`/`chief_lines` show them. New columns are left out of writes until `ready()`. A new custom pastoral role shepherds by default (decision 2). See "As built in PR 3" below. | 3 |
| church_shepherding.py | `role_rows` covers any role with `can_shepherd` true, or null with Ministers on; `lead` stays the senior job. `_chain` (:922-933) uses `chain_for`. | 4, 6 |
| church_follow_up.py | The `choose` tie-break becomes "stream in `made_for`". A Serve sign-up with no team leader (:358-377) goes to the team's department leader, then its overseer, before `oversees_teams`. `_sweep_church` (:1333-1340) uses `chain_for`. `_effective_defs` gives legacy roles their job's switches. | 4, 6 |
| member_portal_messaging.py | The leaders room (:182-188) uses `can_lead` instead of the job list, and keeps today's structural rule that also seats a role another role answers to (:180-184; Love City's Intercessor leader, New Hope's Deacons in the fixture). It adds the leaders and overseers of active departments. | 4 |
| church_prayer.py | The late ladder (:430-448) uses `chain_for`. `pass_targets` (:279-292) also offers holders who answer to this leader as a person. | 6 |
| church_shepherd_signals.py | `_chain` (:255-260) drives `told_name` and the climb (:495-507). | 6 |
| church_leader_tasks.py | `overseer` (:565-584) takes the first step of `chain_for`. A group leader with no role goes to their group's department (leader, then overseer) before `handed_by` (:641-654). | 6 |
| church_money_levels.py | `required` (:132-139) and `page_view` (:303-329) use the church's levels. `pastors` (:160-183) reads `pastor_yes_roles` when set. `board`/`board_people` add holders of `can_board_yes` roles. church_checks `LEVELS_ON` (:117-118) is formatted from the church's levels. **Check first:** `/my/board/approvals` may open only to church_board_members (`boards_of`, member_portal_board.py:334). If so, open it to board-yes role holders too. | 7 |
| church_duties.py `_exec_users`, church_office_tasks.py `overseers` | Read `office_overseer_roles`. | 7 |
| member_asks.py | A room ask's phone alerts (:558-563) go to `church_duties.holders_of(biz,"rooms")` (:658-675) instead of `recipients(…,"office")` (:377-407). The bell is unchanged. | 7 |
| church_areas.py | `place_role`/`place_team` order: the church's pick → the department's area → a stored guess (`by='guess'`) → the job (:152-155). Guesses are written once: lazily on first open (an insert that never overwrites a pick) and when a role or serve option is new. | 8 |

**As built in PR 3** (decisions the table above left open):
- **A job change** starts the five `can_*` switches again from the new job's defaults, unless the same request sets them; `made_for` is trimmed to the new handles. A role's job, like what it covers, changes only while no one holds it (status not declined). The page already said so; the server now refuses it too.
- **A new custom role's `made_for`** is suggested once from its key and title (today's tie-break, as the migration's insert trigger would), then stored. `can_shepherd` follows decision 2, not the title.
- **`can_shepherd` null** (follows Ministers) is kept only on a pastoral role; on any other job it is saved as false.
- **Every role insert names all six switch columns** once `ready()`: `ensure_library`, `set_type`, `create_role` and Chief's draft. The live insert trigger (`church_role_defs_switches`) reads a row with all six at their column defaults as "none said" and fills today's rule. So a pastoral role saved null with every other switch off and no `made_for` is saved as false, and a role saved all off stays off. The fake runs that trigger. **PR 9 drops the insert fill** (and `church_role_switches_today`) once every write names the switches; the `made_for` trim stays.
- **`office_overseer_roles`:** an `office` row names itself only while the church's list is null (never set), as the backfill did. A list the church set, `'{}'` included, is left alone. `create_role` makes no catalog row, so it never adds one; a custom pick such as New Hope's Director of Operations is PR 5's settings write.
- **Readers:** `library` carries each role's switches whenever `ready()`. `chief_lines` says them only where `church_open(biz)` and `ready()`, so a closed church's Chief reads exactly today's lines. A failed switch read returns None (503), as the page's other reads do.
- **`ready()`** probes `church_role_defs`'s new columns. The file is one transaction, so that answers for all of it. False is not remembered.
- **`propose(biz)`** is a stub that returns `{}`. Step 2 drafts from ministry groups and `oversees_teams`, naming a leader only where one person holds the source and never an overseer.
- **The fixture:** Love City's Prophets is made with `can_shepherd: false`, since it predates the map and the backfill gave it today's rule. `build(..., migrated=False)` is the database before the file, and every baseline runs that way too.

Unchanged; these become the map's sources: group leaders (group_lead.py:36-39), serve teams (sunday_leading.py:25-38), church_board_members, space_leaders and worship_ministries. `member_portal._leads` (:1172-1194) needs no change either: department people must hold an active role, which already opens the Lead tab.

Frontend: nothing is required in step 1. `AREA_OF` (churchStructure.tsx:330-380) maps pages to areas and reads no role title or job. Step 2 covers the department sheet, switch toggles in RoleDetail.tsx, a per-role shepherd switch, and LeadersRoles.tsx:119.

## 4. `job_for_title`

- New `guess_job(title) → (job | None, why)`:
  - Exact catalog titles first (:1078-1081), then the word list (:1082-1091).
  - Add `prophet|apostle|overseer` → pastoral.
  - Nothing matches → None. "Board member" and "First Lady" return None: a board seat lives in Board & minutes or `can_board_yes`, not in a job.
- `job_for_title` keeps its `str` signature and returns `guess_job(t)[0] or ""` instead of "care". Known titles are unchanged, and test_church_roles.py:297-302 still passes.
- `chief_draft` (:1059-1071), given no job and no guess, raises 400: "Chief can't tell what job a {title} does here. Pick one: …". chief_church_actions.py:260-264 already turns that into `_fail`, so Chief asks the owner and retries with a job.

## 5. The PRs, in order

Each PR is independently mergeable and about 700 lines or fewer.

1. **Fixture, baseline and this doc** (tests only, about 650 lines).
   - `docs/CHURCH_LEADERS_MAP.md` and `__tests__/church_three.py`.
   - `test_church_three_today.py` pins today's outputs for all three churches.
   - `test_church_leaders_scenario.py`, with each need marked `xfail(strict=True)` and the PR that fixes it.
   - A lint test for rule (a), xfail until PR 9.
2. **Migration** (about 500 lines).
   - The SQL file, and `__tests__/church_map_db.mjs` (PGlite): shape, guards, RLS and revokes, a second run changes nothing, and md5s of `church_leader_roles`, `church_shepherds`, `church_follow_ups` and `church_shepherd_settings` are unchanged.
   - `__tests__/fixtures/church_map_backfill_vectors.json`: the Python oracle's values for every TYPES row and the fixture's titles. SQL and Python must both match it.
   - A docs/MIGRATIONS.md row with verify SQL (Love City's `can_shepherd` equals today's Shepherding page), and a ci.yml line.
   - **Applied by hand after review, before PR 3 merges.**
3. **`church_map` read core, and switches as role data** (about 650 lines; built at about 920: about 490 of code, 380 of tests, 50 of docs). Tests: `ready()` false means writes leave the columns out and every reader runs today's path; the catalog equals the vectors.
4. **Switches replace words** (about 350 lines): shepherding, `made_for`, the leaders room. Tests: with the map open but empty, all three churches equal the baseline; Grace's deacons, once flipped, shepherd; null roles follow the Ministers toggle.
5. **Map writes and routes** (about 650 lines). Tests: validation, the gaps list, `propose` writes nothing, 404 when closed, 503 before the migration. Love City's map is entered after this merges.
6. **The person chain** (about 650 lines). Scenario needs 2 and 4 pass. Tests: New Hope's two other associate pastors are never emailed; where the map doesn't know, output equals the baseline; a loop guard; a vacant overseer is passed over.
7. **Settings take effect; room asks go to the rooms duty** (about 500 lines). Scenario needs 1 and 3 pass. Love City's money and office-overseer outputs equal the baseline.
8. **Areas and job guesses stop deciding** (about 500 lines). Tests: places with the map open equal the baseline; a renamed role keeps its area; the department's area wins; the five titles in §4.
9. **Close-out, after `CHURCH_MAP=on` everywhere** (about 150 lines): delete the regexes, `OVERSEER_KEYS`, the key query, the word tie-break and read-time `_AREA_WORDS`. The lint test passes.

## 6. The three-church fixture

**How it's built.** `__tests__/church_three.py` provides `build(monkeypatch, *, map_on=True, filled=True) → db`. It uses test_church_duties' `DutyDB` (the FakeDB in test_church_roles.py with `church_duty_set`), with all three churches in one fake, which checks cross-church scoping for free.
- Ids are deterministic, one prefix per church; Love City uses `BIZ` from test_church_follow_up.py:28.
- Each library is filled by the real `ensure_library`, then custom roles, holders, households, Sunday attendance, office logins, duty moves and (when `filled=True`) the map.
- `filled=False` is the "map empty" mode that every preservation test uses.

**Love City** (nondenom; the owner is the platform owner):
- Holders: Kevin (Lead Pastor), Jessica (Executive Pastor), Andre (Associate Pastor), two Elders (Marcus answers to Jessica), Ministers (setting off), the Intercessor leader and Intercessors, Prophets (custom, pastoral; "can oversee" comes from the backfill for every pastoral role, not a flip), Evangelists (welcome, overseeing flipped on), Youth Pastor Y, the Children's Director, and team leaders for "Hospitality Team" and "Youth Ministry (YWD)".
- Office: the five lane logins from docs/CHURCH_DUTIES.md:321-336, plus the treasurer's Admin login (reuse the constants in test_church_duties.py).
- Departments: Prayer (overseer a Prophet), Outreach & Welcome (overseer an Evangelist), and Youth (leader Y, overseer Andre, duty `youth`; units: the YWD serve option, the Youth group, space 'youth').
- An elder board in church_boards.

**Grace Baptist** (baptist):
- 90 contacts, 30 households.
- One Pastor (the owner).
- A Deacon Board role with four holders, shepherding and overseeing flipped on.
- Youth Minister Y.
- Office: the treasurer is an Admin login; a part-time secretary is a Manager login with every non-money duty moved to her.
- Money levels $200 / $1,000. No board.
- Youth's overseer is deacon D1; deacon D2 shepherds the drifting family.

**New Hope** (nondenom, retitled):
- 500 contacts.
- A Senior Pastor; Associate Pastors A1, A2 and A3; Youth Director Y.
- Five Elders with board yes on, each answering to one associate pastor.
- "Director of Operations" is set as `office_overseer_roles`.
- 7 office logins. Money levels $1,000 / $5,000.
- Departments: Worship (A1), Youth (A2), Kids (A2), Care (A3).

**The scenario test** (parametrized over the three churches, for Y):

1. **A room request.** Its phone alerts go to the holders of the rooms duty (`church_duties.holders_of(biz, "rooms")`): the owner and admins, plus the Manager holders, who are Naiya and Jessica, the secretary, and New Hope's office-lane login and its office overseer (the Director of Operations holds Rooms by default). The People & Care login is not among them.
2. **A drifting youth family.** `monday_plan` over three Mondays goes to the shepherd, then the shepherd's overseer, then the senior pastor:
   - Love City: Marcus → Jessica → Kevin.
   - Grace: D2 → Pastor, and it stops there.
   - New Hope: elder → A2 → Senior Pastor.
3. **A $180 pay-back.** The treasurer alone, everywhere. At $250, Grace also needs the pastor; the other two churches don't. The secretary's steps never include the treasurer's.
4. **A late task and a late follow-up.** `tell_late`, and the follow-up's one-day-late step, both email exactly Youth's overseer: Andre, D1 or A2. The three-day step goes one person further up.

## Hooks left for steps 2 and 3

- On departments: `status='draft'` and `source='chief'|'template'`.
- `propose()`.
- `map_by`/`map_at`. A change log with undo comes in step 2, with the Chief verbs.
- `can_see_all`, and the holders of a `support_duty` (for "who helps you").
- `chain_for`, which step 3 reuses for "your overseer" and "Under you".
