---
title: Member app round three, part 1 - the colour family, photo looks, default pictures, a shorter Home top and the Today card
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"ok this design is cool. much better. lets go with it ... lets build it" (the Member App, Round Three canvas)'
status: shipped
prs: [kmj-intake-server#1502]
migrations: []
left_undone: ["part 2: the photo editor (Change on every photo, upload, pick from the church's photos, the look, Use the default) for admins and the people they name, like the media team; members keep changing only their own profile picture", "part 3: the Bible reader (Old Testament first book picker, highlights, private notes)", "part 4: plans and the church's own devotionals"]
decisions: ["no photo is picked by chance any more: a spot shows the picture the church chose, else a photo whose file name names it, else its default picture", "an event's picture spot is keyed by its name so a weekly gathering keeps its picture", "the church colour keeps every main button; a family colour within 35 degrees of it takes the church colour; member_portal.colours = church turns the family off", "photos the church hasn't chosen stay black and white, except Home's top, which is washed in the church colour as on the canvas"]
related: [canvas https://claude.ai/artifact/WzjBoY73aPBUkwy1PsEArU]
---
The member app gets the colour family Kevin approved: gold for the Word, teal for people, violet for listening, coral for dates. Each sits beside the church's own colour, which still owns every main button. Tabs, quick ways in, section links, the verse, reading rings, date tabs and the prayer card each wear theirs (`member_app_ui.FAMILY`, `_FAMILY_CSS`).

Photos now show in a look: colour, black and white, or washed in the church colour. `member_app_photos.choose` decides every spot: the church's pick (`settings.member_portal.pictures[key]`, written by part 2), else a photo named for the thing, else the spot's default picture (`member_app_ui.default_art`, 12 kinds). The old by-chance `pick` is no longer used on any screen.

Home's top card drops from 392 to 236 points tall. The verse of the day and today's reading (or where they left off) now share one Today card, with a round button that marks the reading done. Tests: `__tests__/test_member_app_round_three.py`; the no-random rule was rehearsed by putting the old pick back, and 2 tests failed.
