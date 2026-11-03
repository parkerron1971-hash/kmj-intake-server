---
title: Church leaders step 2, PR B4b — adopting a ready-made makes the church its own copy
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: approved step 2 (design 4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas"): a searchable ready-made directory'
status: in progress
prs: [kmj-intake-server#1728]
migrations: [supabase/APPLY-2026-11-05-church-map-step2.sql (applied 2026-11-03, B2)]
left_undone:
  - "F4: the Ready-made screen's Add as a draft button calls POST /church/map/templates/adopt"
  - "B5: Chief's adopt_template verb wraps church_templates.adopt (and action_inverse adopt_template -> undo_map_change)"
  - "B10: launch makes draft roles live before it applies waiting changes, so a shape's picks of drafts can be made"
decisions:
  - "A role, a department or a shape comes in as drafts (source 'template', template_key and template_version; a role's catalog_key is its row) in one applied change, origin 'template', that Undo takes out"
  - "What a live row would get waits as a second, pending change: a flip an active copy lacks, a shape's two picks, and the board's yes even on a new copy (the owner's to apply)"
  - "Already yours (church_templates.mine) makes nothing, a department's leader role included; name makes a second copy; a taken role title or department name is a 400"
  - "A unit is filled only where exactly one of the church's things matches (the space, one Serve team, one group) and no department holds it"
  - "Adopting again makes nothing and stages nothing a waiting ready-made change already holds"
related: [2026-11-05-church-step2-templates.md, 2026-11-05-church-step2-changes.md]
---
`church_templates.adopt` and `POST /church/map/templates/adopt` (the owner or an admin, behind CHURCH_MAP, a
503 before step 2's file) make a ready-made the church's own copy (docs/CHURCH_LEADERS_STEP2.md §2.4). It is a
fork: the platform never writes a copy again, and a later version only changes the catalog. `here()` and
`adopt()` share one reading, so "what this adds here" is what adopting does. Details, and the two corrections
(two rows for a shape, `here()` under a department the church has), are in "As built in B4b" (§2.5).
