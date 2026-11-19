---
title: Member app new look (Lumen) — the switch, then the foundation (top bar, tab bar, Home, Connect)
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the member app: it "feels like ai built it but not creative designer". He approved the "clean Lumen" mock (version 29, accent level 2) after several rounds. Step one: the switch every Lumen page asks. Step two: the foundation (the look as its own file, the bars, Home, Connect, Messages from the bubble).'
status: in review
prs: [kmj-intake-server#1952, "kmj-intake-server (the foundation)"]
migrations: []
left_undone:
  - "Follow-up PRs, each in today's look under Lumen's white tokens and bars until then: Bible and its reader, Give, Watch and Live, the Messages inbox and a thread, Classes, Prayer, Events, a group's page, Me (and its details and notifications), News."
  - "The bell's dot: member_lumen.bell_dot(biz, me) answers False until the recent-alerts list lands (its alerts_unseen must not read the database on every page)."
  - "The 'I'm new here' card: member_lumen.new_here_card(biz, me) answers '' until it lands; Connect's Your next step has the slot."
  - "Under Lumen the tab bar is the approved five (Home · Watch · Bible · Connect · Give, plus Serve/Lead or Board as today); a church's own pick of tabs (Settings → Member page) applies to today's look only. Needs Kevin's call before MEMBER_LUMEN=on."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 with reduced motion, and one 1280 wide check. The sliding tab line is a view transition; headless Chromium doesn't paint after one, so it was not seen moving."
  - "Headless WebKit on Windows draws Geist at one weight (today's look too), so its screenshots read lighter than a phone will."
decisions:
  - "MEMBER_LUMEN = off | preview | owner | on, preview by default. preview: only the platform owner, at a church they own (member_asks.platform_church): their Preview as a member session, or their own member sign-in (the record's email or the address they signed in with is PLATFORM_OWNER_EMAIL). owner: every member at that church. on: every church. Anything else is off."
  - "Another church's owner previewing their own app keeps today's look under preview: the first pastor previews this week, and the new look isn't switched on for anyone but the platform owner yet."
  - "member_portal.serve decides once per page, after the session (member_lumen.decide); a page reads member_lumen.page(): here(), for a signed-in member in Church. Youth, Kids and the sign-in pages keep their looks."
  - "The look is one more shared file, /my/lumen.<hash>.css (member_app_ui.SHEETS), linked after the app's sheet only on a Lumen page; every rule sits under body.lm. Colours come from the app's own tokens worked out on the white base: member_app_ui.base_of answers white on a Lumen page, so the church's base applies to today's look only."
  - "Off is byte for byte today's look: 39 pages (three scenes) compared against the switch branch, all identical; the app, youth, kids and sign-in sheets keep their hashes."
  - "The top bar keeps <header class=\"mb-top\"> (the preview banner and the scroll script find it); body.lm-tab / body.lm-push says which bar it is. A pushed page with no back link of its own gets Back, which goes back in history when the page before was ours (Messages, Me, alerts open over any tab)."
  - "The bubble's count is the one serve() already reads (member_portal_threads.BADGE, kept 15 s); the bell's hook (member_lumen.bell_dot) runs in a thread beside serve()'s first reads, only for someone who sees the new look, and answers no dot until the alerts list lands. Home's reads are the same as today's Home (a test counts them); the news block is built once."
  - "Home under Lumen: the lead is the first thing on the calendar (as today), Today on its day, Live wins; the check-in card is a compact one-tap card (all of the family, as the full card starts ticked; Choose who opens the full card), the full card once checked in. The hero photo is in colour unless the church chose a look for it. The church's own tiles show only when it saved some (the default four repeat what's on the page). The Messages card is gone (the bubble carries the count)."
  - "Connect (/my/connect, new): your group, serving (next date, Details, Can't make it), prayer, events, classes, your next step (keep going on a class; Get baptized and Ask for a visit or help only when those asks are on), find a group, directory (when on), news. Groups, Classes and Directory are pushed from it with a back bar; their segmented Connect tabs are gone under Lumen. Off, /my/connect goes to /my/groups."
  - "Classes' card says 'Your classes', not '<church> Academy': the mock's 'Grace Academy' is a name no church has chosen."
related: [2026-11-18-member-app-tabs-fast.md, 2026-11-18-member-app-cache.md, 2026-11-18-member-app-stopwatch.md]
---
`member_lumen.py` holds the switch for the member app's new look. `visible(request, ctx)`
answers for a request and its session (ctx = {"business", "session"}); `serve()` keeps the
answer for the page (`here()`, `page()`), so the bell, "I'm new here" and the Lumen pages all
ask the same thing.

The foundation: `member_lumen_ui.py` (the sheet, the bars, the small blocks),
`member_portal_lumen.py` (Home and Connect), and a Lumen branch in `member_portal._shell`
(`_lumen_frame`). Every other page draws in today's markup under Lumen's white tokens and
bars, with its large title in the serif. Tests: `__tests__/test_member_lumen.py` (switch),
`__tests__/test_member_lumen_pages.py` (pages, reads, hooks).

Measured locally (harness over the test fake, so database time is ~0; 30 warm requests,
median Server-Timing total): Home 4.7 ms off / 4.3 ms on, Watch 2.2 / 2.5, Bible 2.3 / 2.4,
Messages 3.9 / 4.2, Give 1.7 / 1.7, Groups 3.3 / 2.5, Connect 2.7 (new). Reads per page the
same off and on. Home's HTML 46 KB → 35 KB.

Before building, both repos' worklog/ had nothing on a member app redesign (the 2026-11-18
speed work, the stopwatch and the new-here room are other pieces).
