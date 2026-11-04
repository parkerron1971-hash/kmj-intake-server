# Church leaders, step 2: any church sets up and changes its map

Kevin approved the design on 2026-11-03 (artifact https://claude.ai/artifact/4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas").

Step 1 (docs/CHURCH_LEADERS_MAP.md) made each church's leaders structure data, its map, and taught the engine to read it. Step 2 makes that map easy for any church to set up and change, with no Love City shape in code. It has five parts:
- church setup sessions with Chief, built on the business Academy;
- a searchable ready-made directory;
- Chief verbs with undo;
- the department sheet;
- drafts for new churches.

Line numbers are from backend `origin/main` 97043adc and frontend `origin/module-system` 8a27a353. Re-check them before you edit. "(inferred)" marks a claim the code doesn't show directly.

## Decisions taken (2026-11-03)

1. **Chief's changes.** When the owner or an admin asks Chief in plain words, the change happens at once with Undo, as duties do. A change that is Chief's own idea waits as pending on the sheet. This follows Kevin's standing rule: Chief does what Kevin can on request and leaves a reviewable, undoable record.
2. **Launching with leaders who haven't said yes.** The department goes live. `chain_for` passes over anyone who doesn't hold an active role until they say yes.
3. **Permissions.** Changing a role's switches (`can_*`, `made_for`) needs an Admin seat. Today any Manager seat can PATCH them. `can_board_yes`, a yes on money, needs the owner. This matches step 1's decision 3: money levels are the owner's.
4. **Open for Kevin: coach model and cost (§3.5).** It is needed only by B9. Until he answers, B9 uses the plan's deep lane, as the business coaches do.

## 0. Rules

1. **Step 1's §0 still holds.** Words suggest once and data decides. The three churches, Love City preserved, and the switches all still apply. Every PR runs `__tests__/church_three.py`.

   B1 adds a fourth church, **Riverside**:
   - AME, 60 contacts;
   - no settings row, no roles, no holders;
   - an owner who is not the platform owner;
   - never seeded.
2. **Drafts already route nothing.** The engine reads active departments only (`Map.active`, church_map.py:141) and active roles only (`church_roles.defs`, church_roles.py:606-622). `add_role` refuses a draft role (church_follow_up.py:859-860). Step 2 adds no reader of drafts outside the sheet, the coach and launch.
3. **Switches.**
   - `CHURCH_MAP` (from step 1) gates the sheet, the directory, the change log and Chief's map verbs.
   - New `CHURCH_SETUP = off | owner | on` (default `owner`) gates the coach, the setup routes and draft seeding.
   - `owner` means the platform owner's login, as `church_map.open_to` decides it (church_map.py:83-91). For seeding it means a church that login owns, so Kevin can try a fresh church. Love City is already seeded and can't be reseeded.
   - Set both switches on both Railway services. Turn `CHURCH_SETUP` on only after `CHURCH_MAP` is on.
4. **Plain words.** Screens and Chief say draft, ready-made, change, Undo and Launch. They never say batch, op, template, switch, unit, status or phase.

## 1. Data model

### 1.1 Templates live in code, not a table

The catalog is a Python module, `church_templates.py`, for these reasons:
- **The PR is the review.** It is platform-curated only, so there's no admin screen and no RLS surface.
- **The directory can't disagree with the seed.** Role templates are built at import from `church_roles.TYPES` (church_roles.py:264-432), the same rows `ensure_library` seeds, so their switch values stay pinned by `__tests__/fixtures/church_map_backfill_vectors.json`.
- **Content changes need no migration or backfill**, because copies are forks.
- **Community sharing can come later** as a submissions table behind review. Approved entries join this catalog, and existing copies never change.

Versioning:
- Every template carries a `version`.
- `VERSIONS = {key: (version, sha256 of its content)}` is pinned, and a test fails when content changes without a version bump.
- A copy stores `template_key` and `template_version`. The platform never writes to a copy again.
- The sheet may say "a newer version of this ready-made exists" and show both side by side. It never updates the copy.

### 1.2 The migration (PR B2, the only one)

`supabase/APPLY-2026-11-xx-church-map-step2.sql`: additive, idempotent and server-only. It is applied by hand after review, before B3a merges.

```sql
begin;
-- Where a copy came from. The platform never writes these rows again.
alter table public.church_departments
  add column if not exists template_key text check (template_key ~ '^[a-z0-9_.]{2,60}$'),
  add column if not exists template_version smallint check (template_version between 1 and 999),
  add column if not exists unfinished_at timestamptz;          -- set only by a save that failed half-way
alter table public.church_role_defs
  add column if not exists template_key text check (template_key ~ '^[a-z0-9_.]{2,60}$'),
  add column if not exists template_version smallint check (template_version between 1 and 999);
alter table public.church_role_defs drop constraint if exists church_role_defs_source_check;
alter table public.church_role_defs add constraint church_role_defs_source_check
  check (source in ('catalog','custom','legacy','chief','template'));
alter table public.church_role_settings
  add column if not exists seeded_as text not null default 'active' check (seeded_as in ('active','draft')),
  add column if not exists confirmed_at timestamptz,
  add column if not exists shape_key text check (shape_key ~ '^[a-z0-9_]{2,40}$'),
  add column if not exists shape_version smallint check (shape_version between 1 and 999);

-- Every change to a map: one row per change, each part with its before and after.
create table if not exists public.church_map_changes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  status text not null check (status in ('pending','applied','undone','discarded','failed')),
  origin text not null check (origin in ('office','chief','session','template','launch')),
  phase text check (phase in ('church','ministries','leaders','shepherding','office_help','rhythm_launch')),
  said text not null default '' check (char_length(said) <= 400),
  parts jsonb not null check (jsonb_typeof(parts) = 'array' and jsonb_array_length(parts) between 1 and 80),
  money boolean not null default false,
  made_by uuid references auth.users(id) on delete set null,
  made_at timestamptz not null default now(),
  applied_by uuid references auth.users(id) on delete set null, applied_at timestamptz,
  undoes uuid references public.church_map_changes(id) on delete set null, undone_at timestamptz,
  error text not null default '' check (char_length(error) <= 400),
  constraint church_map_changes_applied check (status not in ('applied','undone') or applied_at is not null));
create index if not exists church_map_changes_recent  on public.church_map_changes(business_id, made_at desc);
create index if not exists church_map_changes_pending on public.church_map_changes(business_id) where status = 'pending';

-- A church's setup sessions, one row per church.
create table if not exists public.church_setup_tracks(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  status text not null default 'in_progress' check (status in ('in_progress','launched')),
  started_from text not null default 'blank' check (started_from ~ '^(blank|live|shape:[a-z0-9_]{2,40})$'),
  current_phase text not null default 'church'
    check (current_phase in ('church','ministries','leaders','shepherding','office_help','rhythm_launch')),
  phases jsonb not null default '{}' check (jsonb_typeof(phases) = 'object'),     -- {phase:{state,at,note}}
  asks jsonb not null default '[]' check (jsonb_typeof(asks) = 'array' and jsonb_array_length(asks) <= 200),
  rhythm jsonb not null default '{}' check (jsonb_typeof(rhythm) = 'object'),
  session_log jsonb not null default '[]' check (jsonb_typeof(session_log) = 'array'),
  turns smallint not null default 0 check (turns between 0 and 999),
  launched_at timestamptz, launched_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now());

-- Server-only: RLS on, browser roles revoked, service role granted, no policies.
do $$ declare t text; begin
  foreach t in array array['church_map_changes','church_setup_tracks'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop; end $$;

-- An office draft with nothing hung from it can only be a half-made save.
update public.church_departments d set unfinished_at = d.updated_at
 where d.status = 'draft' and d.source = 'office' and d.unfinished_at is null
   and not exists (select 1 from public.church_department_units u where u.department_id = d.id);
commit;
```

Builders must check this DDL against the real schema, as PR 2 of step 1 did. Verify:
- trigger and constraint names, in particular whether `church_role_defs_source_check` is the real name of the source check;
- the existing guard triggers;
- idempotence;
- each column add as a DO block where an inline `if not exists` could duplicate a constraint.

### 1.3 Compatibility and backfill

- **Existing rows.**
  - Every existing row reads as before, and `template_key` is null.
  - `seeded_as` defaults to `'active'`, so every church already seeded is confirmed.
  - A library is unconfirmed exactly when `seeded_as='draft' and confirmed_at is null`.
- **`unfinished_at` replaces `_left_behind`'s guess** (church_map.py:650-668; the #1719 review note).
  - Only the failure path (church_map.py:~808-822) sets it. The retry finishes the department and clears it.
  - A department saved as a draft on purpose never matches.
  - The backfill marks the only rows the failure path could have made.
- **Before the file is applied,** a probe `church_map.step2_state()` on `church_map_changes`, shaped like `state()` (church_map.py:232-245), answers false.
  - The new routes return 503, and Chief's new verbs say the map isn't ready.
  - `ensure_library`, the step-1 routes and their writes run as today and log nothing.
  - In the fixture: `build(..., migrated2=False)`.
- **Rollback:** drop the two tables and the new columns, and restore the old source check. Only do this while no role row says `'template'`.

## 2. The ready-made directory

### 2.1 What each level holds

| Level | What it holds |
|---|---|
| **Role** (key `<tradition>.<row>`, e.g. `baptist.usher_board`) | title, job, definition (what it does), who it answers to (a row key, else the senior role), what it sees (its job's `sees` and `never`), handles, the five switches and `made_for` from its TYPES row (`_r`, church_roles.py:232-241), covers, search words |
| **Department** (e.g. `youth`) | name, area (one of the eight, church_areas.py:72-73), support duty (a `church_duties.CATALOG` key), leader role (one row key per tradition), overseer (a role that can oversee; the shape picks which), suggested units (a space, Serve-team words, ministry-group words), weekly rhythm (one line), search words |
| **Shape** (e.g. `pastor_deacons`) | label, about, the traditions it fits, roles (row keys, with switch overrides), departments (each with its overseer role), suggested pastor's-yes and office-overseer roles, who shepherds, families per shepherd. A shape never sets money levels. |

A shape's switch overrides apply only to the church's copy. For example, Deacons shepherd and oversee in `pastor_deacons`, as Grace's fixture flips them.

### 2.2 Seed list

**Roles:** the 101 TYPES rows (8 traditions; 85 written out plus 16 from `_prayer_rows()`, 69 distinct titles), plus six that the departments need and no tradition names:
- `any.media_lead` (team)
- `any.facilities_lead` (team)
- `any.outreach_lead` (welcome)
- `any.mens_lead` (ministry)
- `any.womens_lead` (ministry)
- `any.missions_lead` (ministry)

**Departments (14):**
1. Worship & Arts
2. Media & Production
3. Youth
4. Children
5. Prayer
6. Care & Visitation
7. Welcome & Guest Services
8. Ushers & Greeters
9. Outreach & Evangelism
10. Classes & Groups
11. Men's Ministry
12. Women's Ministry
13. Missions
14. Facilities & Safety

There is no Finance department. Money runs through the office's levels and duties, and an office-job role can't be asked of a member (church_follow_up.py:861-862).

**Shapes (6):**
- **Pastor & deacons**
- **Pastor & elders**
- **Bishop-led**
- **Elder-led:** no "pastor" title; the top is shared, as in the Church of Christ row (church_roles.py:390).
- **Multi-staff:** an executive pastor over the office, associate pastors over departments, and elders with the board's yes.
- **Pastor-led:** a small church; the pastor oversees every department, with a few team leads.

### 2.3 Search

Search runs in-process over every title variant, the keys, the department and shape names, and a `WORDS` synonym table:
- greeter → welcome, usher, hospitality, guest
- music → worship, praise, choir
- kids → children, nursery
- teens → youth, student, ypww, ypd
- sound → media, production
- money → treasurer, trustee, financial

How it matches and ranks:
- The query is casefolded, punctuation is stripped, and a plural "s" is dropped.
- Results rank an exact title first, then a synonym hit, then a word in the definition.
- The church's own tradition comes first.

Example: "greeter" returns Welcome Team lead, Usher Board president, Hospitality lead and Hospitality ministry lead.

Each result shows what it does, who it answers to, what it sees, and its switches in words (`church_map.says`, church_map.py:354). Rule (a) holds: search is a lookup and decides nothing.

### 2.4 Adopting makes the church its own copy

**A role** becomes one draft role:
- `status='draft'`, `source='template'`, with `template_key` and `template_version` set.
- `catalog_key` is the row key, so the closed path's key readers see what `ensure_library` would have made.
- The title is the church's tradition's, unless a different title is named.
- It is made through `create_role` (church_roles.py:867-909), which keeps keys unique.

**A department** becomes a draft department (`source='template'`):
- It also makes draft roles for any leader role the church lacks.
- Units are filled only where exactly one thing matches the suggestion, and that match is stored as data.
- No people are named.

**A shape** adds every missing role and department as drafts:
- Its settings, and any switch overrides on live roles, go in as one pending change.
- It never edits a live row.

Conflicts:
- A non-archived role or department with the same `template_key`, or the same title or name (casefolded), counts as "already yours". Nothing is made, and the answer names the existing one.
- Passing `name` makes a second copy.
- A department name clash is step 1's plain 400.

Idempotence:
- Adopting the same thing again makes nothing and logs nothing.
- Two racing clicks on a role could make `usher_board` and `usher_board_2`. The button disables while busy and Discard removes a draft, so this is accepted (inferred rare).

Each adoption is one change (origin `'template'`), so Undo removes the drafts it made.

### 2.5 Routes

All go in `church_map_router.py`, behind `CHURCH_MAP`.

| Route | Who |
|---|---|
| `GET /church/map/templates?business_id&q&kind` | manager seat and up |
| `GET /church/map/templates/{kind}/{key}?business_id` (includes what adopting would add here) | manager seat and up |
| `POST /church/map/templates/adopt` `{kind, key, tradition?, name?}` | owner or admin |

**As built in B4a** (`church_templates.py`; the two GET routes in church_map_router.py):
- **Seats.** A department's leader and a shape's roles name a seat (`SEATS`): each tradition's own row, else a stated fallback. The youth seat is Love City's Youth Pastor and Grace's Youth Minister; a tradition without the row takes the fallback's (an AME church's Deacons are the non-denominational row).
- **Support duties picked:** Worship & Arts `production_schedule`, Media & Production `stream`, Youth `youth`, Children `kids`, Prayer `prayer`, Care & Visitation `care_visits`, Welcome & Guest Services `first_guests`, Ushers & Greeters `serve_schedule`, Classes & Groups `groups`, Facilities & Safety `building`; Outreach & Evangelism, Men's, Women's and Missions `events` (`outreach_nights` names Love City's own nights).
- **A department's overseer** is the church's senior role unless a shape picks one. Prayer's leader is a prayer job, which doesn't lead, so Prayer carries `lead_can: {can_lead: true}`, as Love City's fixture flips it: in B4b a flip on a new copy, a pending change on a live role.
- **Who shepherds** in a shape is read off its roles with its flips, per tradition, never stored, so the two can't disagree. Pastor & deacons flips Deacons to shepherd and oversee (Grace's fixture). Multi-staff gives the Elders the board's yes, a switch and so the owner's in B4b, never a level.
- **Versions:** each `version` comes from `VERSIONS`, and the hash is sha256 of the canonical JSON of the rest. `python church_templates.py` prints the pins and bumps each one that changed. Roles hash their TYPES rows, so an edit to TYPES fails the pin test too.
- **Search** ranks four ways, not three: an exact title, a word of its name (title, row key, tradition, search words), a word like one (`WORDS`), a word in what it says. Only the query's own words are looked for in what it says, so "greeter" returns exactly the four titles. The plural rule also takes -sses and -ies (classes, ministries). There is one card per title and job (69 titles, Deacons on two jobs), shown as the church's own tradition's row when it has one, with `also` naming the other traditions.
- **The church's tradition** is its type, else Chief's guess, else its name's (`guess_type` on the name alone). The routes read only: Riverside stays unseeded.
- **Already the church's own** (`church_templates.mine`, for B4b's adopt too): the same `template_key`, the same title or name casefolded, or, extending §2.4, a role seeded from the same row on the same job (`catalog_key`), so New Hope's retitled Youth Director is its Youth Pastor.
- **`here`** lists `new`, `yours` and `waits`: a flip an active role of the church's doesn't have yet, and a shape's picks the settings don't name, each in before → after words. A draft of the church's gets no waits.
- **Both routes are a 503 before step 2's file** (§1.3), though search names no step-2 column.

**As built in B4b** (`church_templates.adopt`; `POST /church/map/templates/adopt`):
- **Up to two rows, not one.** The drafts are one applied change (origin `'template'`), which Undo takes out. What a live row would get waits as a second, pending change: a flip an active copy lacks, a shape's two picks, and the board's yes even on a new copy. That covers a department too: Prayer's `can_lead` on a live leader role waits. A draft the church already has gets no waits and is never edited.
- **Money.** The board's yes always waits for the owner. An admin may adopt multi-staff: staging isn't making, and only the owner applies or discards it (B3a's rule).
- **Picks** go in unchecked, since a pick may be a draft this adoption made. B10's launch makes roles live before it applies changes. Applying sooner is a 409 ("A draft role can be picked once it’s live", new `save_settings` wording).
- **Already yours** (`mine`) means nothing is made. For a role or a department the church has, that includes its leader role: correcting B4a's `here()`, which listed that leader as new. `here()` and `adopt()` now share one reading, so the waits `here()` lists are the pending change's lines.
- **`name`** makes a second copy of a role or a department. A role whose title is taken is a 400 like a department's ("There’s already a role called …"). A shape takes no name, and `tradition` picks only a department's or a shape's seats: a role's key names its row.
- **A role copy** is made as `ensure_library` makes the row, through `create_role` (key from the title):
  - its handles and teams come from the Serve card, its switches are its row's plus the flips (but the board's yes), and its definition is filled;
  - it answers to the church's copy of the role its row names, else to the active senior role;
  - a draft made in the same adoption isn't linked yet (session 3, or launch).
- **Units:** a suggestion fills a unit only when exactly one of the church's things matches it: the space, one Serve team, one group (by `words`). A thing that already hangs from a department, or that an earlier department in the same adoption took, is passed over.
- **Again** stages nothing that a waiting ready-made change already holds. After a discard, adopting again suggests it again.

**Corrected in B5** (#1728's review): `adopt()` reads what already waits before it makes any draft, so a failed read is the plain 503 with nothing made. And a draft copy of the same ready-made (its `template_key`) still waits for what a new copy would (`WAITS`: the board's yes) while that isn't set, so when the waiting change's row failed to save after the drafts went in, "Add it again to finish" finishes it, once. `here()` lists that wait too (amending B4a's "a draft of the church's gets no waits"), so the two still share one reading.

## 3. Church setup sessions

### 3.1 Reusing the Academy engine

The Business Track already proved the pattern: a second coach with its own table, phases, prompt and verbs, sharing the chat machinery (business_track_actions.py:102-118 and :779-956; `COACH_MODES`, chief_of_staff.py:825). The church coach is a third one.

**Shared, unchanged:**
- `/agents/chief/chat` with `mode`;
- `COACH_MODES` isolation: no operational injectors and no native tools (chief_of_staff.py:15368, :15773);
- the deep lane (chief_models.py:225-235);
- open and pause sentinel handling (chief_of_staff.py:15630-15651);
- the `session_log` shape and its 50-entry cap;
- the session screen's chat shell.

**Church-specific** (new `church_setup.py`, `church_coach.py`):
- mode `church_coach`, with sentinels `[SYSTEM:church_coach_open]` and `[SYSTEM:church_coach_pause]`;
- `CHURCH_PHASES`;
- `build_church_coach_prompt`, which carries the map in words (from `church_map.view`) and a compact ready-made list in the cached part;
- coach verbs `draft_map`, `plan_ask`, `save_church_phase` and `church_session_summary`;
- launch.

**Why not reuse `strategy_tracks`:**
- Its reader takes the newest row per business (chief_strategy_actions.py:83-92), so a church row would take over a church's own Academy.
- The browser reads and writes it directly (StrategySession.tsx:175-190), which breaks the service-role-only rule.
- Its outputs are written reports.

The church track is `church_setup_tracks`, and it is read only through `GET /church/setup`.

Every coach verb only stages: drafts, pending changes or planned asks. The coach can't make anything active, and a test proves that no coach verb writes an active row. The verbs check that the turn's person is the owner or an admin (`_caller_role`, chief_church_actions.py:56) and that `CHURCH_SETUP` is open for them.

### 3.2 The six sessions and what each saves

Everything a session saves is a draft or a pending change.

| Session | Saves |
|---|---|
| 1. Your church: who leads with the pastor, size, who runs the office | The shape, adopted as drafts. The church type (pending). Pastor's-yes and office-overseer picks (pending settings). Size, in `phases.church`. |
| 2. Ministries | Draft departments, from ready-mades or the church's own: name, area, units. |
| 3. Leaders & overseers | The leader and overseer on each draft department. The draft roles they need. `can_lead` / `can_oversee` on live roles (pending). Who answers to whom (pending). Planned asks, in `asks`. |
| 4. Shepherding | `can_shepherd` on draft roles, or on live roles (pending). Ministers, families per shepherd, and the lead's number (pending, via `church_shepherding.save_settings` :139-160). |
| 5. Office help | Each draft department's support duty. Office-overseer roles (pending). |
| 6. Rhythm & launch | The meeting rhythm, in `rhythm`. Money levels, only if the owner says so (pending, owner only). Then Review and launch. |

How the sessions stay short:
- `save_church_phase` stores one line of what was decided (≤300 characters), never a report.
- The prompt keeps the phases invisible to the church, aims for 8-12 exchanges, and offers to pause.
- After 18 owner turns in one session (`turns`, reset by each open), the prompt tells the coach to wrap up and save.

People on drafts:
- A **draft** department may name people who don't qualify yet, as long as they are among the church's people.
- `view()` lists what each person will need, for example "asked into Youth Pastor at launch".
- An **active** department keeps today's check (church_map.py:765-778), widened one way: someone with an `invited` row on an active role with the right switch is accepted, with the gap "asked, hasn't said yes" (decision 2).
- `chain_for` already passes over anyone who doesn't hold an active role (`_seat`, church_map.py:385), so nothing reaches them before they say yes.
- Turning a department from draft to active checks its people too.

### 3.3 Reopening a session

- `POST /church/setup/phase/{phase}/reopen` marks that session reopened and makes it current.
- The coach reads the map as it stands now, drafts and live alike, not the old transcript.
- After launch, a reopened session makes new drafts and pending changes, and the review becomes "Launch these changes".

### 3.4 Launch, on the owner's yes

`GET /church/setup/review` lists exactly what launch will do, each item with a keep toggle:
- roles to make active;
- departments to make active;
- each pending change, in before → after words;
- the asks ("6 people get an email asking them to…").

It blocks launch when:
- there would be no active senior role;
- an ask is for an office or kids role (church_follow_up.py:861-864);
- an ask for a team role names no team.

`POST /church/setup/launch` (owner only) runs these steps, each safe to run again, all recorded in one `'launch'` change:
1. The kept draft roles go active. A catalog row marked `office` names itself an office overseer, as `_office_overseers` does (church_roles.py:593-599).
2. The kept pending changes apply.
3. The asks are sent through `add_role` and `send_invite` (church_follow_up.py:853-948). Its dedupe (:888-890) makes running it again safe.
4. The kept draft departments go active, under §3.2's rule.
5. The track is marked launched.

After launch:
- Anything not kept stays a draft.
- A failed step stops there, and pressing Launch again continues from it.
- Undoing a launch reverses steps 4, 2 and 1 where nothing has changed since. It never touches a role someone now holds or was asked into.
- Emails can't be unsent. A separate "Take back the asks" removes holder rows still `invited` (`remove_role`, church_follow_up.py:951).

### 3.5 Cost per church setup (open question 4)

The coach runs on the plan's deep-lane ladder: Small on Sonnet 5, Growing on Opus 5.5, Established and Large on Fable 5 (chief_models.py:146-150). Prices come from api_usage_logger.py:79-105: $2/$10, $4/$20 and $10/$50 per million tokens in and out.

The estimate assumes (inferred):
- a 20-minute session is 16 calls (14 exchanges plus the open and the pause);
- each call sends about 9k tokens in (about 6k of prompt and map, about 3k of history);
- each call returns about 0.9k tokens out (the reply, action tags and high-effort thinking).

| Plan | One session | Six sessions | Six plus 2 reopens |
|---|---|---|---|
| Small (Sonnet 5) | ~$0.43 | ~$2.60 | ~$3.50 |
| Growing (Opus 5.5) | ~$0.86 | ~$5.20 | ~$7 |
| Established and Large (Fable 5) | ~$2.15 | ~$13 | ~$17 |

How the cost comes down:
- The church coach prompt carries `[[CHIEF_CACHE_SPLIT]]` (chief_of_staff.py:1569-1573) between the stable persona and catalog and the map.
- Opus 5.5 cache reads cost 0.05× (api_usage_logger.py:180), so six sessions on Growing come to about $3.50 (inferred).
- The 18-turn wrap-up caps the worst case.

### 3.6 Love City goes first

B8 fills in `church_map.propose` (a stub, church_map.py:496-505) as its TODO says:
- Each active group of kind `'ministry'`, and each active role with `oversees_teams`, that doesn't already hang from a department becomes a proposed department, with those units.
- A leader is named only where exactly one person holds the source and leads. An overseer is never named.

`POST /church/setup/start {from:'live'}` writes the proposal as draft departments (`source='chief'`, one change, tagged to session 2) and sets `started_from='live'`. Love City's live roles are untouched. Session 1 confirms its shape and adds only the missing roles, as drafts. Kevin's correction pass stays in step 4.

## 4. Chief verbs

The verbs live in a new `chief_map.py`. They are action tags, `chief_only` in the registry.

| Verb | Args | Writes |
|---|---|---|
| `list_map` (read, sensitive) | | Nothing. It reads departments, their people and helpers, gaps, each role's switches in words, settings, pending changes, and the last ten changes with ids. |
| `change_map` (A) | `{changes:[…], said, stage?}` | One change. It applies at once when the owner or an admin asked (decision 1). `stage:true`, for Chief's own idea, leaves it pending on the sheet. |
| `draft_map` (A, coach) | the same, plus `phase` | Always staged. |
| `undo_map_change` (A) | `{change_id}` | Puts one change back (§4.2). |
| `apply_map_change`, `discard_map_change` (A) | `{change_id}` | Acts on a pending change. |
| `search_templates` (read) | `{q, kind?}` | Nothing. |
| `adopt_template` (A) | `{kind, key, tradition?, name?}` | Drafts (§2.4). |
| `ask_into_role` (C, it sends an email) | `{person, role, scope?}` | `add_role` and `send_invite`. Today Chief can only `draft_church_role` (chief_church_actions.py:243-272). |
| `plan_ask`, `save_church_phase`, `church_session_summary` (A, coach) | | The track. |

The parts of a change, and the step-1 write each one goes through (each write already checks its own rules):

| Part | Fields | Goes through |
|---|---|---|
| `department` | department (name or id), name, leader, overseer, support_duty, area, units, status | `church_map.save_department` (:719) and `archive_department` (:836) |
| `role` | role, title, definition, reports_to, the five switches, made_for, status | `church_roles.update_role` (:912); a new role goes through `create_role` as a draft |
| `answers_to` | person, role, to | `church_map.set_answers_to` (:842) |
| `settings` | pastor_yes_roles, office_overseer_roles, the levels | `church_map.save_settings` (:866) |
| `shepherding` | ministers, cap, lead_cap | `church_shepherding.save_settings` |

Kevin's examples:
- **"Make Deacon Brown the overseer of Youth"** is `department {department:"Youth", overseer:"Deacon Brown"}`. If Brown's role can't oversee, the change fails and says why. Chief asks the owner, then adds `role {role:"Deacons", can_oversee:true}` to the same change.
- **"Deacons shepherd families now"** is `role {role:"Deacons", can_shepherd:true}`.
- **"Add a Media department, helped by the office"** is `adopt_template` Media & Production, then `department {support_duty:"stream"}`, or a department of the church's own.

Names resolve the way `chief_duties.resolve` does (chief_duties.py:159):
- a whole name, or a first name only one person has;
- role holders first, then the church's people;
- no match, or more than one, fails.

Every handler:
- returns `{result, label}`;
- refuses unattended runs (as chief_duties.py:294);
- checks `church_map.open_to` for the person in the turn (as `_switched_on`, chief_duties.py:98);
- is placed in `chief_areas.OWNERS`, except `list_map` and `search_templates`, which go in `ALL` with their handlers keeping a manager seat;
- gives a receipt in before → now words, ending "Undo puts it back".

### 4.1 One change, one row

`church_map_batch.apply(biz, changes, by, origin, stage, phase)`:
1. Resolves names to ids and reads the before state from `load()` and `defs()`.
2. Checks every part first, with the writes' own Python checks.
3. Writes the parts in order. Each is stored as `{kind, id, before, after}`, where `before` null means this change made the thing and `after` null means it archived it.

The step-1 routes (PUT departments, PUT answers-to, PUT settings) and role-switch saves also log through it, with origin `'office'`, so the sheet's Undo covers edits made on screen.

There is no transaction, as in step 1 (no RPC; CHURCH_LEADERS_MAP.md "As built in PR 5"). A part that fails marks the change `failed`, with a record of what got in. Running it again is safe, because every write sets the after state.

### 4.2 Undo

Undo follows the duties model (church_duties.py:948-984), per change.

When it's allowed:
- for 30 days (as `expense_categories.UNDO_DAYS`);
- only while every field the change touched still equals its after state.

Otherwise the answer is a 409 that names what changed since ("Youth's overseer was changed again on Nov 9; change it directly"). It never does a half undo.

How it puts things back:
- Parts go back in reverse: a draft the change made is deleted, an active department it made is archived, and every other field returns to its before value.
- The undo is itself a change (`undoes` points to the original), and the original gets `undone_at`.
- `action_inverse` gains `change_map → undo_map_change` and `adopt_template → undo_map_change`, on the `move_duty` pattern (action_inverse.py:295-299). `ask_into_role` has no inverse.

### 4.3 Permissions

- **Reads:** a manager seat and up.
- **Every write:** the owner or an admin.
- **Money levels:** the owner only, as in step 1 (church_map.py:882). Undoing or launching a change that touches money is owner only too; the `money` column marks those changes.
- **Role switches (decision 3, B3b):** today any Manager seat can PATCH a role's switches (`CARE_MIN_ROLE="manager"`, church_router.py:68 and :261-266), though no screen offers it yet. After B3b, a PATCH carrying `can_*` or `made_for` needs an admin seat, and `can_board_yes` needs the owner.

**As built in B3a** (`church_map_batch.py`; the routes in church_map_router.py):
- **Checked first** means each part's own write run with `dry=True` (new on `save_department`, `set_answers_to`, `save_settings`, `update_role`, `create_role` and Shepherding's `save_settings`) against a copy of the map that the earlier parts have moved on. So order matters: in "Make Deacon Brown the overseer of Youth", the `role` part goes before the `department` part.
- **A part** is `{kind, id, label, before, after}` with only the fields it changes. `label` is the thing's name when logged, for the sheet and the 409s. A failed change marks the parts that didn't go in `done: false`; a draft taken out by an undo is `deleted: true` (after null).
- **Nothing is logged for nothing.** A part that changes nothing is left out, and a change of nothing writes no row (the same levels again; archiving an archived department). A single part whose write fails logs nothing and answers as the write does, so every step-1 message is unchanged. A failure after another part went in keeps the change `failed`, and the answer ends "apply it again to finish it".
- **Running it again** is `POST …/{id}/apply` on a failed change too. A part already as its after is passed over; one whose fields each read as before or after is written; anything else is a 409. A pending change whose fields changed after it was saved is a 409 as well (risk 7: never a silent overwrite).
- **Money** also covers a role part that changes `can_board_yes` (decision 3). Discarding a money change is owner-only too. Every call takes the caller's seat as `role` (owner or admin, else 403), which §4.1's signature didn't have.
- **Undo** works only on an applied change that isn't itself an undo, within 30 days of `applied_at`. A write's own refusal during the check, such as a name or thing someone has taken since, is a 409 ("That can't be put back: …").
- **Names** are minimal: `department`, `role` (key or title), `person`, `leader`, `overseer` and `to` take an id or an exact name, and B5 replaces this. The step-1 keys (`id`, `*_contact_id`, `holder_id`, role id lists) pass through to the writes unchanged.
- **The row is written after the parts**, since there is no transaction. If that insert fails, the save stands, `change` is null and a `[church_map_batch]` line is printed. Once logged, the step-1 routes add `change: {id, status, money}` to their answers.
- **Fixture:** `build(..., migrated2=False)` refuses the two tables and B2's columns. ThreeDB now merges a `merge-duplicates` post on `on_conflict=business_id` (Shepherding's settings), as PostgREST does.

**As built in B3b** (church_map.py, `church_map_batch.save_role`, church_router.py):
- **People on a draft** must be among the church's people, nothing more. The gaps say what each needs: "Gloria Hunt needs a role that leads." (`leader_needs`, `overseer_needs`), and, on a draft or an active department, "… was asked into Associate Pastor and hasn't said yes yet." (`leader_asked`, `overseer_asked`). "Asked into Youth Pastor at launch" is a planned ask, which lives in the track's `asks`; they have no shape until B9, so B10 adds that line.
- **An active department** takes a person who holds, or has an `invited` row on, an active role with the switch. Going live checks the leader and overseer even when the request names neither: a draft made active, a retry finished as active, and an Undo that brings an archived department back (a 409 when its people no longer qualify). Archiving keeps step 1's rule (only what it names).
- **The chain:** `_seat` now passes over a holder row that isn't `active` too, so `chain_for` and `team_head` skip someone asked even if a caller hands in invited rows. Every caller already passes `active_holders`. The tests swap each church's Youth overseer for someone asked: the late task and follow-up go exactly where they go with the seat vacant.
- **`unfinished_at`:**
  - Set only by `save_department`'s failure path, and only once `step2_state()` is True.
  - Read only by the same-name check of a new save with units: a one-row read. `load()`'s select is unchanged, so the engine never names B2's columns.
  - The retry clears it in its last patch, once its units are in. A save to a draft by its id clears it as well, because the office then owns that draft.
  - The ten-minute, same-login guess is gone. The mark decides, so another login's retry finishes the department too.
- **Correction (before step 2's file):** nothing can be marked. The failure path still makes the department a draft and answers LEFT_EMPTY's 503 ("archive it … then try again"), and no retry takes anything over. This is the one change to the step-2-absent path, and it is deliberate: B2 is applied.
- **`?with=choices`** returns `{kind: [{ref, label, department}]}` for the seven unit kinds:
  - by id: active groups, active and draft roles, boards, worship ministries;
  - by label: Serve teams, budget lines, youth and kids.
  `department` is `{id, name, status}` (draft or active), else null. Any other `with` value is ignored.
- **Switch seats:**
  - A refusal is a 403 with words, as for money levels, not business_access's 404, because the seat already reaches the route.
  - A board yes sent as it already reads isn't a change, as with a money level.
  - **Extension to §4.3:** `POST /church/roles` takes the same rule. Otherwise a Manager could make a new role with the board's yes.
  - A Manager's job change still resets a role's switches to the new job's defaults (PR 3). No job's defaults turn on the board's yes.
- **The seat rule holds at every church; the log only where the map is open.** The 403s apply whether or not `CHURCH_MAP` is open: no screen sends a switch yet, so nothing visible changes. Logging follows the change routes: only where `open_to(user)`.
- **Logged switch saves:** where the map is open and `step2_state()` is True, a PATCH that names a switch is one change (origin `'office'`, a `role` part) holding the fields a role part keeps: title, definition, reports_to, status, the switches and made_for. Its other fields (job, covers, handles, sees, oversees_teams, term_months, needs_class) are written first through `update_role`, unlogged as today, so Undo leaves them. A PATCH without a switch is today's write.
- **`role_name`** reads `covers` from the definition it is given, or else from the LEGACY row for the stored key (structure, §0 rule (a)). test_church_no_title_words never listed it (it is display), so its marks are unchanged.

**Corrected in B4a** (#1726's review; `church_map_batch.switch_seat`, `save_role`):
- **A job change is a switch change** once the map's columns are there, since it resets the switches to the new job's. It needs an admin seat (a 403: "Only the owner or an admin changes a role's job…"), and one that would take a board yes away needs the owner. Where the map is open and step 2 is there, it is one change: a role part with each switch's before and after. Undo puts the switches back and leaves the job. B3b's "a Manager's job change still resets a role's switches" no longer holds: a Manager's job change on Leaders & roles is now refused at every church, the one visible change.
- **A switch save is checked whole and written at once.** The batch's dry run checks the whole PATCH, then one `update_role` writes it, its unlogged fields with it. A refused part no longer leaves them saved (B3b wrote them first).

**As built in B5** (`chief_map.py`):
- **Names, extended.** A person may also be a role's title (its key, or the start of its title) and a last name, among that role's holders: "Deacon Brown", which finds Grace's Deacon Board. Holders include someone asked who hasn't said yes. A role or a department matches exactly first (case aside), then by the same words (a plural s aside); a unit's group, role, board or worship ministry by its name. The batch still gets ids.
- **Receipts** are the sheet's own lines (`church_map_batch.recent`). A made change ends "Undo puts it back."; one that waits says where it waits and who says yes, never Undo; an undo says it is a change too. A failure after a part went in carries that change's id, so `apply_map_change` finishes it.
- **The reads are mid-turn too** (list_duties' pattern), and both are `sensitive`: every Chief-only read is, and the search reads the turn's church. Every verb refuses an unattended run, the reads included. Before step 2's file every verb says the map isn't ready.
- **`draft_map`** is registered (origin `'session'`, always waiting). Its words are `chief_map.COACH_WORDS`, for B9's coach prompt; the main prompt teaches `change_map`'s `stage` for Chief's own idea.
- **Inverses:** `apply_map_change` → `undo_map_change` too, since it ends "Undo puts it back". A change that only waits has none.
- **`adopt_template`** also takes a ready-made's name as its key (a role's among the church's tradition and any church's).

## 5. The department sheet (frontend, Leaders & roles)

`LibView` (LeadersRoles.tsx:36-40) gains the views `map`, `dept`, `ready` and `setup`. When `GET /church/map` answers 404, the switch is closed for this login and none of them show.

**Top of the library:**
- a "Your departments" strip with counts and gaps;
- a "Set up with Chief" card with six session tiles (not started, saved or reopened), each with Start, Continue or Reopen;
- a "Browse ready-made" link.

**DepartmentSheet** (`GET /church/map`):
- Drafts sit apart from active departments.
- One card per department shows:
  - the leader and overseer, with face and name, or "No overseer" in the need tone;
  - the office helper: the duty's label, and who does it today (`support_duty.holders`);
  - chips for its teams, groups, roles, boards, spaces and budget lines;
  - its gaps inline, worded as `view()` gives them (church_map.py:941-955).
- Filters: All, Needs something, Drafts.
- Below the cards:
  - **Waiting for your yes:** pending changes, with Apply and Discard.
  - **Recent changes** (`GET /church/map/changes`), with Undo.

**DepartmentEditor:**
- name and area;
- leader and overseer pickers, with qualifying holders first. Picking someone who doesn't qualify explains why and offers a fix ("Let Deacons oversee departments");
- the office helper, from the duties catalog (`GET /church/duties`);
- unit pickers, fed by `GET /church/map?with=choices` (new in B3b): Serve teams, groups, roles, boards, worship ministries, budget lines and spaces.

It calls PUT departments, archive and PUT answers-to, and offers Undo after each save.

**RoleDetail** gets a seventh panel, "What this role can do", saved through PATCH `/church/roles/{id}`:
- Shepherds families: on, off, or follows the Ministers setting (pastoral roles only);
- Can oversee a department;
- Leads (sits in the leaders room);
- Gives the board's yes on money (the owner only; read-only for others);
- Sees everything;
- First in line for: `made_for` chips, among its handles.

`RoleDef` gains the six fields `library` already returns (church_roles.py:1064). LeadersRoles.tsx:119 stops reading `key==='team_leader'`. The team role becomes the team-covering role with the most scoped holders, with ties broken by sort.

**Ready-made (the directory):**
- a search box, and the tabs Whole church, Ministries and Roles;
- each card says what it does, who it answers to, what it sees, and what it can do;
- opening one shows "What this adds here" and an **Add as a draft** button.

**Setup:**
- **ChurchSession:** a full-screen chat on a lean version of the BusinessSession shell, text first. It never reads Supabase from the browser; the track comes from `GET /church/setup`.
- **Review & launch:** §3.4's list with keep toggles, and Launch for the owner.

**Mobile:**
- one column under 640px;
- editors are full views, as today;
- pickers are bottom sheets;
- toggles are 44px rows;
- search stays at the top.

Each FE PR adds one What's New entry in `src/core/updates/whatsNew.ts`, with area Operate and `areas: ['office','people_care']`.

## 6. New churches start from a draft map

Today `ensure_library` (church_roles.py:673-745) seeds the guessed type's roles as active the first time it runs (:715). B7 changes that, behind `CHURCH_SETUP`.

**Who is new:** a church with no `seeded_at`, no role row in any status, and no holder row.

A new church gets:
- the same rows as today, as drafts (`status='draft'`, `source='template'`, `template_key=<type>.<row>`);
- `seeded_as='draft'`;
- no office overseer until it confirms.

Every other church takes today's path, byte for byte. That includes every seeded church, and a church with roles but no `seeded_at`, which the step-1 backfill can leave (APPLY-2026-11-04-church-map.sql:199-205).

Confirming and changing type:
- `POST /church/map/confirm` (owner or admin) makes the kept seed drafts active as one undoable change, applies the office-overseer rule, and stamps `confirmed_at`.
- `set_type` on an unconfirmed library swaps the seed drafts (which have no holders) for the new type's. Today it only adds (:992-1044).
- Leaders & roles shows one "Your draft leaders" section (Confirm, Set up with Chief, Change type) instead of a Draft card per role (17 for a non-denominational church, 14 for AME) (LeadersRoles.tsx:174, :429).
- Until it confirms, every card goes to the office, as for a church whose roles nobody holds yet.

Tests:
- Riverside seeds drafts, routes like an empty library, confirms, and undoes the confirm.
- Love City, Grace and New Hope with `CHURCH_SETUP=on` equal test_church_three_today's baseline, `library()` included.
- On Riverside before it confirms, pin every reader that assumes an active senior role, such as the pastor's yes and Shepherding's lead (inferred risk).

## 7. PRs, in order

Each PR is one change, not stacked, about 700 lines at most, and runs the three churches. B is backend (kmj-intake-server), F is frontend (solutionist-studio).

| # | PR (~lines) | Switch | Tests |
|---|---|---|---|
| B1 | This doc, Riverside in the fixture, and a baseline proving step 2 changes nothing (~450) | | the baseline with every new switch on |
| B2 | **Migration**, plus `church_map_step2_db.mjs` (PGlite: shape, RLS, revokes, a second run changes nothing, existing rows' md5s unchanged apart from the `unfinished_at` backfill) and a MIGRATIONS.md row. **Applied before B3a merges.** (~400) | | as listed |
| B3a | `church_map_batch`: changes, undo, apply and discard; routes `GET /church/map/changes` and `POST …/{id}/undo` `/apply` `/discard`; the step-1 routes log through it (~650) | CHURCH_MAP | undo on drift gives 409; partial replay; money owner only; 404 closed; 503 with migrated2=False |
| B3b | The rules for people on drafts, the activation check, `unfinished_at`, `?with=choices`, switch permissions on PATCH roles (decision 3), and `role_name` no longer reading `team_leader` (church_follow_up.py:909) (~500) | CHURCH_MAP | the chain passes over invited leaders; a deliberate draft is never taken over |
| F1 | RoleDetail toggles, `RoleDef` fields, LeadersRoles.tsx:119 (~350) | shown only when the switches come back | |
| B4a | The `church_templates` catalog, search and versions; GET routes (~650) | CHURCH_MAP | every TYPES row is a template with equal switches; the version-hash test; "greeter" |
| B4b | Adopt a role, a department or a shape (~550) | CHURCH_MAP | fork; conflicts; idempotence; all three churches adopt the same shape and differ only in titles |
| F2 | The department sheet (read): gaps, pending, recent and Undo (~600) | hidden on 404 | |
| F3 | The department editor (~650) | | |
| F4 | Ready-made browse, search and adopt (~550) | | |
| B5 | Chief verbs except `ask_into_role`: registry, inverses, `chief_areas`, prompt lines on the chief_prompt.py:2127-2132 pattern (~650) | CHURCH_MAP, checked for the person in the turn | name ambiguity; refusals by seat; `{result, label}` |
| B6 | `ask_into_role`, class C (~250) | CHURCH_MAP | draft, office and kids refusals |
| B7 | New-church drafts, confirm, type swap (~450) | CHURCH_SETUP | §6 |
| F5 | The draft leaders section and Confirm (~300) | | |
| B8 | `propose()`, `church_setup.py`, the setup routes, start from live, reopen (~600) | CHURCH_SETUP | Love City's proposal names no overseer |
| B9 | The church coach: mode, sentinels, lane, prompt, coach verbs, turn cap (~650) | CHURCH_SETUP | no coach verb writes an active row; the prompt carries no Love City name |
| F6 | The setup tiles and ChurchSession (~700) | | |
| B10 | Review and launch, undo launch, take back asks (~600) | CHURCH_SETUP; launch is owner only | launching again is safe; Grace's launch sends exactly its asks |
| F7 | The Review & launch screen (~450) | | |

Rollout:
1. `CHURCH_MAP` stays `owner` through F4.
2. Love City runs the sessions once F7 is in.
3. Then `CHURCH_MAP=on`, then `CHURCH_SETUP=on`, each on both services.

## 8. Risks

1. **People named on drafts who don't qualify yet.** Safety rests on `chain_for` passing over anyone who doesn't qualify. B3b pins this for each church.
2. **A change's parts aren't one transaction.** Safe replays and Undo's 409 on drift cover this, but it is still a new failure the sheet has to explain.
3. **Templates drifting from TYPES.** The backfill vectors and the version hashes fail loudly.
4. **The coach.** Cost is high on Fable plans, and a coach that wrote live rows by mistake would be a surprise. The turn cap, stage-only verbs, and launching only from the screen guard against both.
5. **Chief naming the wrong person.** Exact matching, refusing ambiguity, before → now receipts, and Undo.
6. **New-church drafts and readers that assume an active senior role.** Confirmed by B1's baseline: with nobody holding the senior role, `church_money_levels.pastors` has no one, so a request at or above the pastor's level can't pass (owner only when `pastor_yes_roles` is `'{}'`). Kept as designed, not changed: the money page says "No one holds the senior pastor's role yet" (test_church_checks `test_the_page_says_what_no_one_can_approve`), and letting the owner stand in would let one person give both the treasurer's and the pastor's step where the owner already stands in for the treasurer, breaking the two-person rule. Setup closes it instead: launch is blocked with no active senior role (§3.4), and B7's draft library shows the gap until the church confirms and asks its pastor in. The Riverside tests cover the rest.
7. **Two editors at once** (the coach and the office). The before-state checks give a 409, never a silent overwrite.
