---
title: "Member app new look: the day, one step at a time, as Kevin's Plans design draws it"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Plans, step 3: the day in steps. A top bar (close, 'Day N of M', share), the step segments READ · SCRIPTURE · ACT · PRAY · JOURNAL from the day's own fields (empty ones skipped), a day strip, one step at a time, Back / Next working without script, Listen (reuse what exists, the devotional's own voice where present, never fake one), mark the day done on the last step. Reading and topic plans show their passages plus mark done."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "'In the pastor's own voice': devotionals keep no recording of the pastor (devotionals.voice is one of the app's reading voices and devotionals.audio keeps the readings the app made), so Listen says 'Today's reading, read aloud' and never claims a person's voice."
  - "Sending the group's question to the group's chat, and the reminder: the group-and-reminder step. The day shows the question as 'For your group'."
  - "The day no longer carries the devotional's picture or the reader's moon and Aa: the design's day has neither. Night reading still arrives dark from the reader's cookie; member_lumen_devotional.render_day stays (unused by any page) so its preview test and CSS keep their pins."
decisions:
  - "A devotional's day under the new look is member_lumen_plan_day.render_day, on the reads today's day already makes: no read of its own. Off, today's day byte for byte."
  - "The steps come from the day's own words, an empty one left out: READ (the line to hold on to and the words), SCRIPTURE (up to three passages from the app's Bible in the member's translation, 30 verses each, with a link to the chapter), ACT (Today's step), PRAY, JOURNAL (the day's question and the private note, devotional_progress.journal). The last step also carries 'For your group' (the day's together question), the daily checklist and Mark day N done."
  - "Without script every step is its own address (?step=) and Back / Next are links; the journal, the checklist and Mark done are one form posted to the existing POST /my/bible/plans/day, which now also takes a form (same session, same-site and rate checks as the JSON; only the member's own day, an open day only) and goes back to the last step saying how it went. With script the steps switch in place (the address follows without stacking history), the journal saves itself and Mark done saves without leaving, through the same route as JSON, as before."
  - "Listen: the church's reading voice through the existing devotional_voice route when it can be made; otherwise, and on a plan's day, the phone reads the step aloud in its own voice like the Bible reader's Listen (nothing is sent anywhere; the button shows only where the phone can speak)."
  - "A day of a reading or topic plan the member started (/my/bible/plans/<plan>/<n>, the new look's only): its passages read right there, Mark day N done on the reading plans' own tick route (which now also returns to that day), the days around it; a day not open yet goes back to the plan's page. Continue and the plan's page open these days."
  - "CSS: member_lumen_plan_day.CSS right after the plans block in member_lumen_ui.templates(), so the order still ends share, mini, fonts; every rule under body.lm, tokens only."
related: [2026-11-21-lumen-plans-tab.md, 2026-11-21-lumen-plan-page.md, 2026-11-19-lumen-next-devotional.md]
---
The day in steps, for church devotionals, and a day of a reading or topic plan with its passages.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main, both. Reads with the switch on, per page and table, in four
looks: Home harness 1984 / 1984 over 328 page-looks; Bible harness with the Plans pages and two day pages 1309 on main,
1286 here over 256 page-looks: a devotional's day reads exactly what it read on main, a plan's day reads nothing
coming back (its reads are the plan page's kept ones); /my and /my/directory (500 in that harness) move with their
30-second feed cache on either side. In a real browser (Chromium and WebKit): Next switches in place and the address
follows without stacking history, Mark done and Not done yet save in place as JSON, no script errors; with script
off, Next is a link and Mark done posts the form from the page's own origin and comes back to the last step with the
journal kept (Chromium also Not done yet; WebKit with script off never lets an automated click on it settle, the
route itself is pinned by the tests). Member suites with the Bible and devotional ones: 1724 passed. Shots before and
after (Chromium and WebKit, light and dark, 390x844 @2x, Love City's Consecrate Your Focus day 6 as the design page
writes it) in the session scratchpad's plans-build-shots/pr3/.
