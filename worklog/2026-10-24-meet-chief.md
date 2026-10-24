---
title: Meet Chief on the church and coach sections, a coach on camera and in the room, and the sample dates put on the 2026 calendar
date: 2026-10-24
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-24: "are we clear on explaining how chief works on these individual pages? for churches coaches etc..." then "yes" to a Meet Chief band mocked on the canvases; "we need to add a picture of a coach or consultant in action. live view of a group or class teaching"; "yes find a workshop photo, then build"; then "pick a better picture for the classes ... we do need a link added that brings people back to the main website especially if they came from there ... even for people that came from a domain that wasn''t the main domain"'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The 30-day overdue alert always says 'Two reminders already sent' (chief_of_staff.py ~7722), even when none were: a backend fix of its own"
  - "The main site's own Meet Chief band (marketing_pages, render_home_v1) still says Chief asks first on anything that messages a client and that undo means undo; earned permission and the undo list say otherwise"
  - "The morning brief reads only the first 200 businesses (notification_engine.py:767)"
  - "On the church pages the Fall Festival (Sat Nov 7) falls on the retreat weekend (Nov 6 to 8); it did in the 2025 samples too"
decisions:
  - "The pages showed Chief at work in every room but never said what Chief is. Each overview now has a #chief band after the hero, the role before the name (the main site's rule, marketing_pages.py:3814): 'A chief of staff for your church/practice. It's called Chief.' Chief is in the overview's menu, and every product page has a 'How Chief works' strip above The rooms next door"
  - "Every line of the band was checked against main first, and three draft lines were wrong. One message to Chief costs chat_price() = 12 AI actions, so the band and the plan meters speak in conversations, computed the main site's way (marketing_pages._credits_in_words), now the CONV_* tokens. 'Asks before it acts' is not absolute: standing_permissions offers to take a kind over after three yeses, so the band says Chief takes a kind of task on itself only after you tell it it may. Only the deep lanes ride the plan, so it says everyday answers are the same on every plan. 'Chief sees what your role sees' was left out: outside the church care and children's actions there is no per-role check"
  - "Loose lines already on the pages are corrected: the coach 30-day overdue question only runs on its own under Autopilot Smart or Full; 'a full audit trail' is the record of changes to a closed month (the audit_trail gate), in the coach Office page's own words; the church Monday note covers families with a shepherd"
  - "A coach on camera: the main site's coach photo (p-maya.jpg) in the overview hero's live-class tablet and in the Courses live room. Live classes do carry the teacher's camera (academy_live_router). The main site calls her Maya, so here she is only ever 'You', the teacher's own view, never Dana Reyes. On phones the coach hero shows that tablet in place of the booking phone"
  - "A coach in the room: a class photo from Unsplash (Vitaly Gariev, a coach at a whiteboard with a small group, Unsplash License), credited in static/home/CREDITS.md as w-class.jpg. Kevin asked for a better one than the first pick (a workshop photo, never shipped). It is a band on /coaches ('Teach the room, and everyone at home', in the Courses page's own checked words), words on the right so the coach stays clear, and it replaces the pastor photo that had stood in for the coach's workshop recording and clips on Marketing"
  - "The way home, on every church and coach page. The top strip's Solutionist mark, which had led to the page's own top or the section overview, is now '< Solutionist home' to the main site, and the footer's Solutionist column starts with the same link. Someone who came from the main site reads 'Back to Solutionist' and returns to the page they left. The main site's pages send a referrer (only learner pages and tenant sites are no-referrer); the host must be the main site's own or its www, so a practitioner's subdomain never counts, and a page inside these sections never counts. Every link to the main site (home, Start free, the founding seat, Privacy, Terms, the other section) now uses its full address from the HOME token (ORIGIN), so on a church's own domain '/' never stands in for Solutionist"
  - "The church samples were drawn on the 2025 calendar: 'Sunday, October 26' is a Monday in 2026. Every church date tied to a weekday or a run of Sundays moved back one day (52 weeks on); fixed dates (year-end, the 1st of the month, bank rows, due dates) stayed. On the coach pages, the Courses class 'Tuesdays since Oct 21', its November calendar and the Marketing week 'Nov 3 to 7' were the same slip"
related: [2026-10-24-coach-site.md, 2026-10-23-church-site.md]
---
Visitors to /churches and /coaches met Chief by name in the hero ("Chief keeps it all moving between Sundays") without ever being told what Chief is. The word "AI" first appeared in the price cards. Now each overview stops right after the hero to introduce Chief.

**The band.** A sample conversation: someone asks out loud, on a call from the phone, "What needs me this week?" Chief answers from the records, then drafts a note that waits to be sent. Around it are four points:
- **Type it or say it:** a real voice call, the same Chief on phone and computer.
- **Ready each morning:** the morning brief, plus the Monday shepherd note for churches.
- **Your yes comes first.**
- **Shows its work:** the History page, and undo for a day on tasks and website text; nothing sent or paid can be undone.

Under them, a line says what the plans buy: about 250, 625 or 1,450 conversations a month, from the dials. The morning notes don't use any, and only long planning sessions think deeper on the bigger plans.

`__tests__/test_meet_chief.py` holds it in place:
- the band, the menu link and the strips on both sections;
- the conversations, which follow the dials and the chat price;
- chat, voice and drafts on one model for every plan, while the deep lane climbs;
- undo, which lasts 24 hours and never covers a send or a payment;
- every weekday beside a date matching 2026, read across calendar tiles too;
- every photo served from static/home.

Checked:
- That file plus the church, coach, brand-voice, home, news, findability and public-site URL suites: 512 passed.
- The rendered templates were screenshotted at 1440 and 390 in headless Chromium.
- The design canvases carry the same changes: churches version 18, coaches version 9.
- The way home is tested two ways. Every page links to https://mysolutionist.app/ from the strip and the footer, with no relative main-site links left. The back-link script runs in Node for six referrers: the main site, www, a section page, a practitioner subdomain, another site, and none.
