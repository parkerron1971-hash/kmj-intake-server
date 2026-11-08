---
title: The church home's hero names the rooms in the glass, the products are a rooms tour, and the week is seven windows
date: 2026-11-08
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-08, after the mock rounds (hero take three, then "now website the other sections i mentioned about being upgrade"): "merge it. i think this is good"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The later Member App and Office sections now repeat what the rooms tour shows. Folding them into the tour would shorten the page; offered, not done"
  - "Lanes say features switch on on Thursdays. Kevin asked for this merged on a Sunday, so it is live on merge, as with #1739. The rollback for the whole home is HOME_EDITION=v3 (business home) or CHURCH_SITE=off; there is no separate switch for the new sections"
  - "History doesn't list everything Chief does: church_follow_up.py, church_shepherding.py and church_prayer.py never call audit_log.record, so card hand-offs, shepherd emails and prayer hand-offs don't show there. The tour now says 'What you ask of it, listed in plain words', but the Chief section ('What Chief does, including anything that failed, is listed...') and the room pages ('It lists what it does on your History page') still read wider. Either those writers record to History (the better fix) or those lines narrow"
  - "The window film's posters and the tour screens are captures of the room pages as they stand on 2026-11-08. If a room page's hero device changes, re-capture its tour-*.webp (session scratchpad tour/capture.py) or the tour shows the old screen"
decisions:
  - "The page is the approved mock (claude.ai/artifact/ACaUESdWrwfCyh5ZsLYGQT, version 8) and only it: hero take three, the rooms tour and the seven-window week. Built by the session's scratchpad port_home.py into the live template; the new style and script sit in church_site/overview.css and overview.js"
  - "The hero's glass has one job: each petal is a room, in the same colour, name and order as the sentence under the headline and the tour. The hub is your people. No words inside the window except the room name as the light reaches it; the S stays the logo"
  - "Every tour headline is the room page's own h1, and its three facts are that page's chips (Chief's are condensed from the Chief section). test_the_tour_says_what_each_room_page_says keeps them equal, so a room page edit fails the test until the tour follows"
  - "Tour screens are transparent captures of each room page's hero devices, shown with Grace Fellowship, a sample church. The page says so under the tour"
  - "/assets/home/ now serves webp and mp4 as well as jpg; mp4 goes through _brand_file_ranged so video seeks with range requests. Names stay a strict lowercase pattern"
  - "Week classes are lwp-*: the live page already uses .ln on 16 runtime elements. The old week module is removed from overview.js; it would throw on the new markup and stop later scripts"
  - "An independent read checked the 16 new or condensed sentences against the code; four read wider than it and were narrowed. A card goes to the leader whose role takes it, not always the welcome lead (church_roles.py), so it now says 'Chief hands it to the right leader', as the room page does. Standing permission lets Chief send some kinds on its own (standing_permissions.py), so 'Your yes comes first' now says 'until you tell it it may'. History is the audit log, which the church hand-offs don't write, so 'Shows its work' now says 'What you ask of it'. Statements go only to givers with an email (giving_statement_mail.py), fixed in the tour, the overview's giving screen and the Giving page's chip"
  - "The film lightbox carries its own [hidden] rule: the live page has no global one, unlike the artifact skeleton the mock was built in"
related: [2026-11-04-church-first-home.md, 2026-10-14-home-third-edition.md]
---
mysolutionist.app's church home gets the three upgrades Kevin approved on 11-08. The hero's stained-glass window now plays a short film (it flies together once, then holds while one light walks the petals) and names each room on the glass as the light reaches it; the sentence under the headline lists the same rooms as coloured links in the same order, and Watch the film opens the 1:42 product reel. The product bento is replaced by a rooms tour: a flat rose of the same window picks one of eight rooms, with the room page's headline, three facts and its real screens, walking on by itself every 7 seconds on a computer and by tap on a phone. The week reel is replaced by seven lancet windows, one per day in the colour of the part of church life it served; the open window shows that day's real screen.

Checked locally at 1440, 1280, 1024 and 390 wide: the window film plays (wide 1280 on a computer, square 720 on a phone), the film loads, no script errors, no sideways scroll. Every new sentence was checked against the code before merge. `__tests__/test_church_home.py` pins the order of sections, the hero's room order, the tour matching the room pages, and the new asset routes.
