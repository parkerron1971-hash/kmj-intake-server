---
title: Chief reads and moves a church's duties, with the owner's word and an undo
date: 2026-11-02
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "give chief the ability to make adjustment and help the churches make adjustments like these … you would make the changes for love city directly but chief would do other churches"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Live check on a church other than Love City once CHURCH_DUTIES is on for everyone (a Thursday): owner says 'Jessica does the monthly report now', Chief moves it and says undo"
  - "One move_duty per duty: a several-duty change is several tags, each its own undo (no batch verb)"
  - "The FE Duties tab doesn't refresh on its own after Chief moves a duty (the result carries data_changed and nav to Operate → Logins & areas)"
decisions:
  - "Action tags only, never native write tools: WRITE_TOOL_SCHEMAS is also the outside agent's list and carries no signed-in person; all three verbs chief_only, list_duties also sensitive (the registry's rule for Chief-only reads)"
  - "One code path: church_duties.move() and undo() came out of the PUT and the undo route; the routes and Chief both call them"
  - "chief_areas placement: list_duties is everyone's (*), as any Manager may open the duties page; move_duty and undo_duty are in OWNERS (owner's and admins'), not the Office, so a lane's login hears it's the owner's or an admin's, never 'ask whoever has the Office'"
  - "Names resolve exactly: a whole name (case and spaces aside), a first name only one login has, or a login id; unknown or shared changes nothing and names the candidates"
  - "move_duty's inverse is undo_duty with the change id: undo_last puts a move back only while it is still the duty's last change (409 otherwise)"
  - "The switch: CHURCH_DUTIES, owner meaning the signed-in person is the platform owner (email read by id through platform_suite, kept per process); an unread email is not a yes. The THIS LOGIN line isn't switched, since the job gates read duties whatever it says"
  - "The THIS LOGIN line is read fresh each turn (church_duties' minute cache, cleared on a move), carried on the turn's who, never in a cached prompt segment; a church whose duties can't be read says so; a business whose row can't be read gets no line"
  - "list_duties' mid-turn result may run to 12000 chars, like the bank list: cut short, Chief would guess whose the missing duties are"
related: [2026-11-01-church-duties.md, 2026-11-01-office-gates-duties.md, 2026-11-01-media-gates-duties.md, 2026-10-28-church-office-lanes.md]
---
`chief_duties.py` (list_duties, move_duty, undo_duty, jobs_line), wired in
`chief_of_staff.ACTION_HANDLERS`, `action_registry`, `action_inverse`,
`chief_areas` (placement, and the "Their jobs here" line through `turn_for` and
`block`), `chief_tool_loop` (list_duties mid-turn) and `chief_prompt` (a short
CHURCH DUTIES block in the universal segment). `church_duties.move()`/`undo()`
are now the routes' own code. Tests: `__tests__/test_chief_duties.py`, plus the
whole-turn test in `test_chief_areas.py`. docs/CHURCH_DUTIES.md has step 3.
