---
title: "The home page, edited: the product leads the hero as eight real screens"
date: 2026-11-10
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-10: "take a look at mysolutionist.app and see if there is anything you think we should consider upgrading as it relates to design. I am about top tier"; after six rounds on a mock, "hero product is it! i like that one.", then Build and merge.'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Between 901 and 1240px wide the Coaches and consultants link leaves the top menu (it is still in the footer)."
  - "The window-film hero's styles and markup stay in overview.html/.css/.js as the HOME_EDIT=off rollback; remove them once the edit has stood for a while."
  - "There are still no photos of people on the page beyond the pastor on the sample website. Kevin's call."
  - "Kevin's idea: show both heroes to a few pastors from different traditions and ask who it is for. Not done."
decisions:
  - "The product leads the hero (Kevin picked it over the glass hero). The window stays as the light on the floor, the tour's drawn window, the closing rose and the film."
  - "It is one layer (church_site/overview_edit.css and .js) switched by two classes on <html>. HOME_EDIT=off sends the page as it was, with no deploy."
  - "Live on Kevin's word on a Tuesday, like #1739 and #1769, not held for Thursday."
related: [2026-11-08-home-rooms-and-week.md, 2026-11-09-home-fold-app-and-office.md]
---
Kevin asked for a design review of mysolutionist.app, then approved a mock round by round
(claude.ai/artifact/R4urMgT3cttrinQTBybFp5, version 6). This ships it.

The hero is now a centred headline over eight real screens, one for each room, cut from the room
pages' own captures (static/home/pf-*.webp). The window is not in the picture; its light lies on the
floor under them. One light walks the eight twice and rests; pointing at a screen or at its word in the
sentence brings that room forward. The window's film is no longer fetched on the home page.

Below the hero: one accent for headline flourishes, looser big type, no rainbow bar at the seams, the
mission's second window gone, Chief as one conversation with its four promises pinned to the lines that
prove them, the rooms tour with a screen big enough to read, the move as a moving sheet on paper, and on
phones one top bar, Start free on the first screen and pricing folded to the plan for your size.

Before building more here: the layer overrides overview.css with rules under `html.ep`; edit
overview_edit.css for anything the edit owns. Every class the layer adds is prefixed (ep-, pf-, cx-, ms-):
an unprefixed `ph` collided with a live rule and pushed the whole page in. The strip is hidden with
visibility, not display, because every other copy of the mark borrows its gradient from the strip's SVG.
Check any hero change at 2690x1340, 1366x650 and 390x844 as well as a laptop: Kevin's screen is large.
The layer's sample words (the moving sheet's counts) are marked as samples; its two lines that read as
claims are the page's own.
