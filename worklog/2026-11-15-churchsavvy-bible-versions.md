---
title: "ChurchSavvy Bible versions: BSB and ASV added, a version for each passage in sermon notes, and passages pasted from the church's own Bible with the publisher's notice"
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-15, on the ChurchSavvy upgrade: "let''s do it you can just start building ... and make sure to add the other free version of the bible"'
status: in progress
prs: [kmj-intake-server#1869, solutionist-studio#1577]
migrations: []
left_undone: ["Kevin reviews and merges: this backend PR first, then the app's (the app's new versions and pasted passages need this server)", "the stream's lower third shows the notice too (ShowSlideView); the lower-thirds build running in parallel may want to restyle it"]
decisions: ["BSB and ASV from eBible.org's verse-per-line zips (engbsb_vpl.zip, eng-asv_vpl.zip, the 2026-10-30 builds), 66 books and 31,086 verses each; both leave out the 16 verses modern texts footnote; the ASV's unclosed [Selah is written Selah (bible_data/README.md)", "the ASV keeps its [supplied words] like the KJV: italics in the member app, plain on slides (bible_text.SUPPLIED); a lone bracket (ASV John 7:53 and 8:11) is dropped on slides", "bible_text.LICENSED is the one table of versions a church pastes from its own Bible (NIV, ESV, NKJV, NLT, CSB, HCSB, NASB, AMP, AMPC, MSG, NRSV, NRSVue, RSV), each with its publisher's standard notice and where it was read", "a passage in one of them is a verse line with `words` (what the pastor pasted, tidied: links, the reference and copyright lines, footnote letters off; at most 2,000 letters, 4,000 before tidying); it splits at its verse numbers like real verses, else between sentences, and its last slide carries `notice`", "nothing licensed is ever fetched; a licensed passage with no words is refused, and the app keeps it a statement line until there are some, so old notes never break", "a Scripture item and the church's look keep to the four free versions"]
related: [2026-11-14-churchsavvy-sermon-outline.md, 2026-10-19-member-app-bible.md, 2026-11-14-churchsavvy-sunday-tools.md]
---
`bible_text.py`: `TRANSLATIONS` has bsb and asv (the member app's switcher, its
search and the booth read it, so they list all four); `SUPPLIED`, `PARAGRAPHS`;
`LICENSED` with the notices. `worship_scripture.py`: `clean_pasted`,
`pasted_slides` (and `labelled`, split out of `slides`, unchanged output).
`worship_show.py`: `_clean_pasted_line` in `_clean_point`, `_pasted_verses` in
`_outline_verses`. Old notes and old Scripture items compile exactly as before
(checked against origin/main's code). Tests: `test_worship_bible_versions.py`
(73), `test_bible_text.py` over the four; five sabotages of the new code each
went red.
