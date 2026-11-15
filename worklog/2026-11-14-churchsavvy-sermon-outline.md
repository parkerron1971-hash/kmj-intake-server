---
title: "ChurchSavvy sermon notes as an outline: points, statements, scripture, and how each point shows"
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: "for notes there should be spots to place points and different statements under that point. etc from proclaim they had dividers like -- that could create another slide so it was easy to separate points but I think we can make something better." On the mock (Notes, idea 2 of 3): "build and merge everything"'
status: in progress
prs: ["kmj-intake-server (this PR): the text item keeps sermon notes and compiles them", "solutionist-studio: the notes editor, the slides, the confidence screen"]
migrations: []
left_undone: ["Kevin reviews and merges both PRs (backend first is safe: nothing changes for text typed slide by slide)", "the editor is behind CHURCHSAVVY_SUNDAY_TOOLS (owner first, kmj-intake-server#1861); the What's New entry goes in the switch-on PR"]
decisions: ["a text item's slides stay the points; a point of sermon notes adds `lines` (statement or verse, each with an optional `note` and `br` for the --) and `mode` (build | each | all); the typed words ride along in `outline`, kept exactly", "a passage in the notes is found when it's planned and kept by its full name and Bible version, then turned into verses when the show is made, like a Scripture item", "text typed slide by slide compiles exactly as before (a test holds it to the old code)", "build marks the line it just added (`newest`); one each puts the point in the small heading; all at once puts the point and its lines on one slide and -- splits it; a passage always gets its own verse slides", "numbered points carry `point` (1, 2, 3) so the pastor's screen still says Point 2 of 3 through builds and verses", "the pastor's notes (a point's, a line's, a passage's) ride on the slides for the confidence screen; a screen's own link now drops `notes` from every slide unless it's a stage screen", "caps: 24 lines a point, 20 passages, 150 slides an item, 20,000 characters of notes"]
related: [2026-11-14-churchsavvy-sunday-tools.md, 2026-10-26-churchsavvy-slide-backgrounds.md, 2026-10-20-churchsavvy-confidence-server.md]
---
`worship_show.py`: `_clean_point` checks a point's lines and press inside
`clean_item` (text), which also keeps `outline` and holds the caps;
`_point_slides` and `_outline_verses` make the slides in `compile_item`, where a
point's own background now rides on every slide it makes (verses too).
`worship_show_router.screen_show` drops `notes` from every slide kind for
non-stage screens. Tests: `test_worship_show.py` (old items identical, the
mock's sermon, all at once, numbering and backgrounds, 15 refusals) and
`test_worship_show_router.py` (saved as typed; notes reach the stage only).

The app reads the typed outline (lib/worshipOutline.ts in solutionist-studio)
and sends the points; the server never parses the words.
