---
title: Serving hours and background checks — the Sunday door's Serving page (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27, on the Church Office Prototypes (https://claude.ai/artifact/2vGqaUZUynRuiFVKuQEZWo, the "Serving hours" tab): "lets go with your list"; "make sure that the design is top tier"'
status: shipped, switched off (platform owner only until a Thursday)
prs: [kmj-intake-server (this PR), solutionist-studio (the office page, its own PR)]
migrations: []
left_undone:
  - "Switch-on: CHURCH_SERVING=on on Railway on a Thursday (it defaults to owner), with the app's What's New entry"
  - "Group leaders who aren't on a Sunday team don't get My serving, so their gathering hours show only to the office"
  - "A gathering counts only for a leader marked there; a leader who takes the roll without ticking themselves earns nothing for it"
  - "'Thank the top 10' from the prototype isn't built: the office sees the top people, and thanks them its own way"
  - "No vendor integration: the office's check link is a setting, and the date is typed in when a check comes back"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "No migration. The office's settings live in businesses.settings.church_serving {team_minutes, group_minutes, check_link, check_years}; hours outside the schedule, a check date recorded here and the last reminder in contacts.metadata.serving"
  - "A place counts from the team's arrive-by time (or the plan's Before items, whichever is earlier) to the end of the plan, After included; 90 minutes from the start when the plan has no times; the team's own length when the office sets one. Two places one person holds the same day count their shared time once"
  - "Only a yes counts, for whoever holds the place: a sub who said yes gets it, a pending cover doesn't move it; a no, an unanswered ask, an offered place and an away day never count"
  - "A logged group gathering counts 90 minutes (the office can change it) for each leader of the group marked there; a Sunday team's own group never counts as a gathering"
  - "Who works with kids or youth: the Youth and Kids leaders (space_leaders) and everyone on a Sunday team whose area is Kids & youth (the church's pick, else its name), or scheduled on one. A check is good for 2 years until the office says otherwise (1 to 5)"
  - "Check status: ok, due (within 30 days), overdue, none on record, blocked (none, and on the schedule with kids within 4 weeks: 'Can't serve with kids yet'), teen (under 18: no check)"
  - "A check date recorded here also updates the Youth and Kids leaders page where it's newer"
  - "Check reminders go as a phone alert (member_push 'serving') and an email (serving's own Stop these emails link), with the office's check link when set; once a week at most per person"
  - "Who: the owner and admins, and office logins whose areas are the whole church or include Worship & media, Kids & youth or People & care. Checks: Kids & youth, People & care, the owner and admins. Changes: owner, admin, manager"
  - "The member's side (My serving: hours this year with a thank-you, and their check if they serve with kids or youth) follows CHURCH_SERVING: on for everyone; in owner mode only in the platform owner's own preview of the member app"
related: [2026-10-23-sunday-planning-serving.md, 2026-10-26-serve-tab.md, 2026-10-27-church-spaces.md]
---
`church_serving.py` (new): the switch (`CHURCH_SERVING` off | owner | on,
owner by default, like `church_keys.py`), the hours arithmetic, the checks,
the reminders and eight routes under `/church/serving` (the module docstring
lists them). `/church/serving/status` answers `{enabled, checks, write}` and
is quietly false for a closed switch, a business that isn't a church, or a
login whose areas leave Serving out.

- `member_portal_serving.py`: My serving gains the year's hours with a
  thank-you (gold, Newsreader) and the background check row (a check that
  needs them leads the page; a current one sits lower); `hours_for` decides
  whether the switch shows them here.
- `member_portal_lead.py`: the Serve tab's own My serving gets the same.
- `kmj_intake_automation.py`: mounts the router after Rooms & spaces.

Checks:
- `__tests__/test_church_serving.py`: 21 tests (the arithmetic, subs,
  declines, away days, the shared time, group leaders, added hours, every
  check status, recording a check, reminders once a week, another church,
  areas, the switch, a failed read, the member's own reads, the member page,
  reads the server caps read page by page, a leaders page that didn't take
  the date, a reminder that couldn't be marked).
- Each rule broken on purpose, and a test caught all ten: an unanswered ask
  counting, away days counting, shared time counted twice, a group member
  earning gatherings, "can't serve yet" never shown, areas ignored, checks
  shown to every area, a teen needing a check, reminders every time, and the
  member's reads not filtered to them.
- My serving rendered at 375 px with a due check and its link, a check
  needed before Sunday, and a new volunteer with no hours yet: no sideways
  scroll.
- The serve tab, Lead tab, Sunday serving and pack, the ownership ratchet,
  route type hints, seat access and Rooms & spaces suites pass.
