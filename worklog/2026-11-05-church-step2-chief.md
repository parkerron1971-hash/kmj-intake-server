---
title: Church leaders step 2, PR B5 — Chief changes the leaders map in plain words, with Undo
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: approved step 2 (design 4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas"), decision 1: Chief changes the map at once when the owner or an admin asks, with Undo; its own idea waits'
status: in progress
prs: [kmj-intake-server#1729]
migrations: [supabase/APPLY-2026-11-05-church-map-step2.sql (applied 2026-11-03, B2)]
left_undone:
  - "B6: ask_into_role (class C, it sends an email)"
  - "B9: the church coach puts chief_map.COACH_WORDS (draft_map) in its prompt and checks CHURCH_SETUP"
decisions:
  - "chief_map.py: list_map and search_templates (reads, a Manager seat and up, mid-turn too); change_map, draft_map, undo_map_change, apply_map_change, discard_map_change and adopt_template (class A, the owner or an admin); all Chief's alone"
  - "change_map is made at once when the owner or an admin asks (origin 'chief'); stage:true, Chief's own idea, waits; draft_map always waits (origin 'session')"
  - "Names resolve before the batch: a whole name, a first name only one person has, or a role's title and a last name ('Deacon Brown'), holders first, then the church's people; none or two changes nothing"
  - "A money part (a level, the board's yes) is the owner's alone, through church_map_batch's own seats"
  - "Separate commit (#1728 review): adopt() reads what waits before it makes a draft, and a retry after the waiting change failed to save rebuilds it"
  - "#1729 review: a part that went in names the change that call acted on (church_map_batch._failed's change_id), or says its record didn't save; a change made but not logged, or whose receipt can't be read back, is still a success, and only a logged change promises Undo; a finished undo promises none"
  - "#1729 review: a person not among the holders is found by a server-side name filter, never a capped read of everyone; receipts read the change by id (lines_of)"
  - "#1729 review: an undo lets go of the waiting changes that name a draft it took out (a ready-made's board's yes), money ones too, since they can never be made"
  - "#1729 review: the church_three fixture keeps order, caps reads at 1,000 rows and takes ilike wildcards; all 16 files that use it pass"
related: [2026-11-05-church-step2-adopt.md, 2026-11-05-church-step2-changes.md, 2026-11-02-chief-duties.md]
---
Chief reads and changes a church's leaders map through the same change log the sheet uses
(`church_map_batch`), so every change it makes is one row with before and after, and Undo puts it back
(docs/CHURCH_LEADERS_STEP2.md §4). Kevin's three examples are in the prompt and the tests: an overseer whose
role can't oversee is refused with words, then made with the role part first; "Deacons shepherd families
now"; a Media department from the ready-made list. Details are in "As built in B5" (§4).
