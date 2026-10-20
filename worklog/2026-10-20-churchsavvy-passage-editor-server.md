---
title: ChurchSavvy — a planned passage goes up its own way (server for the Bible passage editor)
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"the bible area. i like the search ability… we need to have the layout look like proclaim but better… the plan mode edit in real time needs to be a little better" then "these are a go" (Kevin, 2026-10-20; canvas board 32)'
status: in progress
prs: [kmj-intake-server#1528]
migrations: []
left_undone: ["the editor itself (solutionist-studio, next PR)", "stage notes and the confidence screen's layouts (step 4)"]
decisions: ["a fix changes this Sunday's slides only (stage, next-slide, phones read the same compiled slides); the Bible text never changes", "breaks picked by hand win over the split; a break naming a verse that isn't in the passage does nothing", "show_ref, show_nums and show_version default on, so every plan saved before this reads exactly as it did", "size and align on a passage are None unless set: the church's look decides"]
related: [solutionist-studio worklog/2026-10-20-churchsavvy-sunday-workspace.md]
---
This is step 3 of the approved round-4 ChurchSavvy build, server side. It holds what the Bible passage editor (canvas board 32) needs to save.

**A planned passage** (`worship_show.clean_item`, `_clean_passage_choices`) now keeps:
- `split`: `fit` (about 220 letters a slide, as before), `verse` (one verse a slide) or `block` (up to 600 letters);
- `breaks`: the verses that start a slide, when the booth picked them by hand;
- `fixes`: this Sunday's own words for a verse, at most 60 verses of at most 600 letters each;
- `show_ref`, `show_nums` and `show_version`: what shows beside the words;
- `size` and `align`: this passage's own size and alignment.

Each refusal is in plain words.

**Its slides** (`_scripture_slides`, `worship_scripture.slides`) follow those choices. Each verse slide carries `opts {ref, nums, version, size, align}`, so every screen draws it the same way: the room, the stream, the stage and members' phones.

**The search** (`GET /worship/scripture`):
- When the text typed isn't a passage, it finds verses by their words with `bible_text.search` ("still waters" → Psalm 23:2, and the rest).
- A passage now comes back with `verses`, every verse plainly, for the editor's word list.

**Checks:** `test_worship_scripture.py` and `test_worship_show.py` pass (56), as do `test_worship_router.py` and `test_worship_show_router.py` (31). The new pins:
- splits and breaks;
- a fix is Sunday-only;
- word search;
- `opts` on the slides;
- seven refusals.
