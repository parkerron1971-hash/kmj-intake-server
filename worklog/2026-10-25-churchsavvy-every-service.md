---
title: ChurchSavvy's tagline is "Every service, ready."
date: 2026-10-25
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-25, changed the tagline from "Every Sunday, ready." to "Every service, ready." while reviewing the website upgrade mock (FDAysirAGzcrWosHuzijSA); the session building that mock passed it on for the live site'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions: ["the words only: the hero, the three closing bands, the home page's title and share text, and the closing line (\"have your first service on the screens this week\"); every other Sunday on the site is about Sunday and stays", "the share picture had the tagline drawn into it: only that line is redrawn, in the face it was set in (Segoe UI Bold), after redrawing the old line onto the original matched it to the pixel; the logo and the line under it are untouched", "the picture's name changes (og.png -> og-2.png) because /churchsavvy-assets/* is cached a week as never changing; the same name would keep showing the old words in link previews"]
related: [2026-10-24-churchsavvy-website.md]
---
`churchsavvy_site.py` (six lines), `static/churchsavvy/og-2.png` (was `og.png`), `__tests__/test_churchsavvy_site.py`. The site test now pins the hero's words and the title, says "Every Sunday" is on no page, and follows the share picture the pages name to a served PNG. 5 sabotages caught (the hero, the title, Pricing's band, Solutionist's band, the old picture name); one earlier sabotage stayed green (the hero alone, while the home band still matched) and is why the hero is pinned by its id. Rendered at 1440 and 390: the hero breaks the same way it did.
