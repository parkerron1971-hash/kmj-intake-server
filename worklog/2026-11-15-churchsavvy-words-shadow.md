---
title: ChurchSavvy's soft shadow behind the words, a switch in the church's look
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-15, on the one piece of the approved mock left out of the fonts build: "yes add the shadow switch too"'
status: shipped-on-merge
prs: [kmj-intake-server (this PR), solutionist-studio (the switch and the screens)]
migrations: []
left_undone: []
decisions: ["look.shadow, True unless the church turns it off: a look saved before the switch comes back True (its songs always had the shadow); anything but true, false or nothing is refused", "the church's own, like the size and capitals: a sermon series changes the fonts and the background only, so its Sundays keep the church's shadow"]
related: [2026-11-14-churchsavvy-fonts-backgrounds.md, 2026-11-14-churchsavvy-sunday-tools.md]
---
`worship_show.clean_look` keeps `shadow` (DEFAULT_LOOK True). The screens draw it
(the app's ShowSlideView and church-worship-show.css): on, songs keep their soft
shadow and passages and sermon points get the same; off, none.
