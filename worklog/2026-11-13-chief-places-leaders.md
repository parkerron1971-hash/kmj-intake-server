---
title: Chief puts people into leader roles, and says members, not clients
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: '"allow for chief to be able to place people in leaders position in the system so upon request, chief can do it. also make sure chief is aware that they are members not clients."'
status: shipped
prs: [kmj-intake-server#1831]
migrations: []
left_undone: []
decisions:
  - "Step 2's B6 (ask_into_role), built as Leaders & roles' Ask: church_follow_up.add_role + send_invite. The row starts asked and the person says yes on their member page; Chief says asked, never yes. Placing them as a department's leader is change_map, which already takes someone asked."
  - "take_off_role is the page's Remove (remove_role): an unanswered ask is taken back; a role they said yes to goes with what it handed them, and the receipt says what went where and which department still names them."
  - "Both class C (an email; work sent back), chief_only, action tags. No undo: no inverse may be class C (test_no_inverse_is_a_class_c_verb). Taking back an ask Chief just made is take_off_role with the same who and role and only_if_asked, which refuses after a yes."
  - "No feature switch, as the page has none (the spec put B6 behind CHURCH_MAP; the route it calls is open to every church). Seat = the route's: owner, Admin or Manager (CARE_MIN_ROLE via business_access). Area: the Office, beside draft_church_role."
  - "Members, not clients: the 10-27 fix put client → Member in the church word list, but vertical_context's Vocabulary line only shows customer, so Chief never saw it. The ministry lens, the vertical reminders and the church prompt section now say members (guests when new), never clients, customers or leads."
  - "Independent review (11-13) fixes: an ask counts everyone at once, so a first name two people share asks which (holders-first would have emailed the holder); taking back an unanswered ask no longer hands their other work back (church_follow_up.remove_role skips the hand-back for an invited row, the page too); the handlers no longer hold a tainted turn themselves (the class C gate does, and its go-ahead must run it); a hold reads back who and which role; a role id that is not the church's is refused; take_off_role matches a team as the ask does; the map line shows only where the map is on."
related: [2026-11-05-church-step2-chief.md, 2026-10-27-church-chief-words.md, 2026-11-12-church-job-descriptions.md]
---
New `chief_church_roles.py` (ask_into_role, take_off_role), wired into
ACTION_HANDLERS, the registry, chief_areas and the church section of the
prompt. Names resolve as change_map's (chief_map._Names); a team leader's
role names a team on the Serve card. `__tests__/test_chief_church_roles.py`
(21) runs at the three-church fixture: the ask and its email, the page's
refusals, someone asked named a department's leader at once, taking back,
taking off with the work returned, seats, unattended and tainted turns, and
the members words.
