---
title: "Member app new look (Look 5.1): Home's stories show up, with the newest message and the member's class"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin's Home plan (2026-11-21, 'yes to everything'), gap one: the stories row never shows at Love City. It needs two moments and the church has one (tomorrow's service). Also count last Sunday's message, a class the member is in and their groups' next meeting; each new moment gets the viewer's treatment (kicker, serif line, one button), Share only on the message. Order: pastor, Sunday, last week's message, groups, class, events."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "A private class at a church with no class anyone can see is not a moment: the class read only runs where member_portal_classes.classes_on says the church has a public class (kept a minute), so a church without classes asks nothing more. Connect still shows the private class."
  - "The class moment opens the member's classes (/my/classes, which shows that class and its way into the classroom), not the classroom itself."
decisions:
  - "The newest message is member_feed_more.message_of (preached in the last seven days, never a sample), from Home's own library: no read. It comes after Sunday and is left out when Sunday's moment already carries that message (the message dated the service's day). Under the circle: Today, Yesterday, 'Last week' for last Sunday's, else the weekday. The viewer: 'New message · Sunday, November 15', the title, who preached it and the series, Watch (Listen for audio alone, ?listen=1), Share through member_lumen_share (kind moment, id message:<id>, its public /sermons/<id> page and the picture it already shows)."
  - "The class is member_portal_lumen.my_class: academy_member_classes' first 'mine' class that isn't completed (and has lessons left), as Connect's Classes row picks it. One RPC (member_portal_classes.member_classes, split out of classes_for so Home skips the church clock's two reads), kept two minutes per (church, member) in a member_cache.Kept; a failed read leaves the moment out and isn't kept. The moment: 'Your class · Lesson n of m', the class's title, the next lesson's name, Continue to /my/classes, no Share (a class has no public page)."
  - "No new CSS: the new moments use the viewer's existing classes. No route, no write."
related: [2026-11-20-lumen-tidy-ups.md, 2026-11-21-lumen-tab-tops.md]
---
Home's stories at a church like Love City now carry the service, last Sunday's message, the member's
groups and their class, so the row shows.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main in both modes. Reads with the switch on (warm), per page
and table in four looks: Home harness 1984 / 1984 over 328 page-looks, Bible harness 1288 / 1288 over 236, no
page differs. Cold (nothing kept): one more GET (academy_courses, member_portal_classes.classes_on, kept a
minute), and at a church with classes one RPC (academy_member_classes, kept two minutes per member). Member
suites with -n 2: 1593 passed (9 new in __tests__/test_member_lumen_home_stories.py). Shots before and after
(Chromium and WebKit, light and dark, 390x844 @2x, the rich sample church and a church with no posts, the
viewer on the message and the class) in the session scratchpad's home-build-shots/pr1-stories/.
