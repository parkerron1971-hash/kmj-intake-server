---
title: Member directory — opt-in, members only, never minors (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27: "member directory is a go sense we have safety room" (he had said no for v1; the member-messaging safety room is why it is a yes now)'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the office section and the tab option, next)]
migrations: []
left_undone:
  - "Thursday switch-on is in the frontend (memberDirectoryRollout.ts OPEN_TO_EVERYONE): until then only the platform owner sees the office section, so only that church can turn it on"
  - "Members count as members by contacts.status active or vip. A church that imported its people as leads (the import's default without a status column) shows an empty directory and 'ask the office to mark you as a member' until the office marks them. Check Love City's statuses before Thursday"
  - "No People door row yet: the church-menu worker adds 'Member directory' there with the office component"
  - "Photos follow member_photos' rule: a listed member with no birthdate on their record shows initials, not their photo"
decisions:
  - "Lane: Build, under 'Love City leaves Subsplash (M-1)' (Subsplash has a directory)"
  - "No migration. The church's switch is settings.member_portal.directory = {on}; each member's yes and what shows is contacts.metadata.directory = {listed, phone, email, household, at, removed}"
  - "Off by default; /my/directory redirects to /my while off and POST /my/directory/me says it's closed. Only the owner turns it on or off (PUT /member-portal/{biz}/directory, _require_owner); turning it off takes it off the member app's bar"
  - "The office list and take-out/let-back (GET and POST /member-portal/{biz}/directory/...) are the owner or an admin seat (business_access.assert_access 'admin'), the rule member_spaces' leaders follow"
  - "Nobody is listed until they say yes (My details, or the directory page's 'Show me in the directory'). Name and photo always; phone, email and household each behind its own switch, all off. Saying no always works and turns every field off"
  - "Minors never listed and never see it: under 18 by birthdate, a child on a family (children.contact_id), a teen linked for messaging (msg_guardians), or a whole tag youth/kids/teen/child/minor. No birthdate known = an adult for listing"
  - "Visitors (status lead) and anyone not active/vip aren't listed and see 'the directory is for members'. Youth and Kids spaces never show it"
  - "Households show together only between listed adults who each turned household on; one alone shows nothing about the household"
  - "Message goes to /my/messages/to/<id> (member messaging, screened and watched by the safety officers) only while the church has messaging on and that person can message; otherwise only what each person chose shows"
  - "The office takes someone out with a reason the member sees on the directory and My details; they can't put themselves back until the office lets them back, and then they say yes again themselves"
  - "A failed read shows nothing (503), never more"
  - "'directory' is an optional member-app tab (member_app_ui.CHURCH_TABS), offered in tab_choices only while it's on; a saved bar drops it while it's off"
related: [2026-10-27-member-app-tabs.md, 2026-10-20-safety-officers-from-pastors.md]
---
The church's member directory in the member app (`member_directory.py`, new).
A member opens it from Connect (a Directory segment beside Groups, Classes and
Messages) or a Directory tab the office added; it searches by name as you
type and puts households together. My details gains a "Member directory"
form. The office's routes feed the frontend section in Settings › Member
page.

- `member_directory.py` (new): the rules (pure), the reads, the member's
  POST, the page, the details block and four office routes.
- `member_portal.py`: serves `/my/directory` (only while on, never in Kids),
  passes the details block, and keeps the tab payload and a saved bar honest
  while it's off.
- `member_portal_church.py`: flash words, `/my/directory` as a way back,
  Connect's Directory segment, and the details page's slot.
- `member_app_ui.py`: the `directory` tab, its icon, hint and colour.
- `kmj_intake_automation.py`: mounts the router before the site catch-all.

Tests: `__tests__/test_member_directory.py` (23). Each rule was broken on
purpose (the minor check, the member check, a phone always shown, a removed
member rejoining, the owner switch, a minor viewer, household grouping,
a removal on a listed record, the church filter) and a test caught every one.
