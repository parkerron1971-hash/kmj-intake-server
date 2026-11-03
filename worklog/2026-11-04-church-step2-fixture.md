---
title: Church leaders step 2, PR B1 — the step 2 spec, Riverside (a fourth test church nobody set up), today's baseline with CHURCH_SETUP on
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: approved step 2 (design 4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas"): church setup sessions on the Academy engine, a ready-made directory, Chief verbs with undo, the department sheet, drafts for new churches'
status: shipped
prs: [kmj-intake-server#1720]
migrations: []
left_undone:
  - "B2: supabase/APPLY-2026-11-xx-church-map-step2.sql (church_map_changes, church_setup_tracks, template and unfinished_at columns), its PGlite check and a MIGRATIONS.md row; applied by hand before B3a merges"
  - "B3a: church_map_batch (one change per row, undo, apply, discard) and the changes routes; the step-1 routes log through it"
  - "B3b: people on drafts, the activation check, unfinished_at, ?with=choices, admin-only switch PATCH (decision 3), role_name stops reading team_leader"
  - "B4a: the church_templates catalog, search and versions; B4b: adopt a role, a department or a shape"
  - "B5: Chief's map verbs (all but ask_into_role); B6: ask_into_role (class C)"
  - "B7: new churches seed drafts behind CHURCH_SETUP, confirm, type swap; it changes the Riverside first-open pin here only where CHURCH_SETUP is on"
  - "B8: propose(), church_setup.py, the setup routes, start from live, reopen; B9: the church coach; B10: review and launch, undo launch, take back the asks"
  - "Frontend F1-F7: RoleDetail toggles, the department sheet, the editor, ready-made browse, the draft leaders section, the setup tiles and ChurchSession, Review & launch"
  - "Decision 4 is Kevin's: the church coach's model and cost (spec §3.5). Until he answers, B9 uses the plan's deep lane"
decisions:
  - "Chief's changes: asked by the owner or an admin in plain words, they happen at once with Undo; Chief's own idea waits as pending on the sheet"
  - "Launching with leaders who haven't said yes: the department goes live, and chain_for passes over anyone not holding an active role until they say yes"
  - "Changing a role's switches (can_*, made_for) needs an Admin seat; can_board_yes needs the owner"
  - "Open for Kevin: the coach's model and cost (§3.5); B9 uses the plan's deep lane until he answers"
related: [2026-11-04-church-map-fixture.md, 2026-11-04-church-map-core.md, 2026-11-04-church-map-writes.md, 2026-11-04-church-map-chain.md, 2026-11-04-church-map-settings.md, 2026-11-04-church-map-areas.md, 2026-11-04-church-map-serve.md]
---
Tests and the spec only; no production code. `docs/CHURCH_LEADERS_STEP2.md` is the step 2 spec as
approved. `__tests__/church_three.py` gains Riverside: an AME church of 60 people in 20 households, with
no role settings row, no roles, no holders, no logins and no Serve card. Its owner is not the platform
owner, and build() never seeds it. `CHURCHES` stays the three, so step 1's tests are untouched; `FOUR`
adds Riverside. It takes no ids from the fixture's counter, so the three's rows come out as before.

`__tests__/test_church_step2_today.py` pins today at Riverside with the map closed, open and empty, and
open before the migration, and with CHURCH_SETUP unset, off and owner. On its first open, Leaders & roles
or the areas page fills the library with the 14 AME titles, all active (B7 changes that where
CHURCH_SETUP is on). A card, Chief's lines, the leaders room, Shepherding and the money steps never fill
it. Before and after that first open, every card goes to the office and the leaders room is empty. Every
family waits on Shepherding. The owner gives the treasurer's step, and nobody can give the pastor's yes
a $600 request needs, because nobody holds the senior role. The same test file runs every
test_church_three_today baseline, and the three churches' library(), with CHURCH_SETUP=on.

Before building more here: today a church whose senior role nobody holds can't get any request of $500
or more past the pastor's step. Every new church is in that state until someone says yes to Pastor, and
B7's drafts keep it there until the church confirms.
