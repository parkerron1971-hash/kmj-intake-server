---
title: The Light Table, step 2 (more to go on, and what a great flyer needs, backend)
date: 2026-11-11
agent: Claude Code (Claude Opus 5.5)
asked: "build it so i can test in full flow. ... make sure we the system would have everything that is needed to make great flyer designs."
status: in progress
prs: [kmj-intake-server#TBD, solutionist-studio#TBD]
migrations: []
left_undone: ["A Scan to sign up code on the flyer (needs a QR image and a protected placement)", "Use our own photos first only nudges for a photo; it doesn't pick one from Media Library", "Three looks before paying (step 4), free word fixes (step 3), every size and Series (step 5)", "The ~$6 engine bench was offered, not run", "Turn STUDIO_LIGHT_TABLE on, on a Thursday"]
decisions: ["Kevin chose the marked-up proof over the ticket", "The picture question is 'What should people see first?': The moment, A person, One symbol, Just the words", "Tell me about it fills the set questions; it never adds questions; nothing prints unless it shows in black on the proof", "Who appears in drawn people is a church setting, a mix of ages and backgrounds by default"]
related: [2026-11-09-light-table-studio.md, 2026-10-05-creative-director-every-business.md]
---
Canvas rows 5 to 7 of https://claude.ai/artifact/Vcma193TFunxdNoUnEKwLv, built.

`studio_light_table.py` now holds the set list of questions (`QUESTIONS`, `ORDER` per
kind of flyer), each choice with what it means to the designer (a feeling becomes
light and palette words, an audience becomes a tone). The status read also returns
the coming events in Services & Events (up to eight, with each one's sign-up prices,
places left and closing day from `church_event_signups`), the styles, the church's
people setting and whether a logo is there to place.

`POST /read` is "Tell me about it": Haiku (the `background` lane, thinking off) fills
the set questions from the owner's words through a schema limited to each question's
own choices. Anything off the list is dropped, and a line to print is kept only when
its words are in the message. Rate-limited per church (`studio_read`, 40 an hour),
spend-guarded, metered at units=0. `PUT /people` saves the "who's in your pictures"
setting under `settings.studio.people`, read just before the write.

What the designer gets now: every printed line with its role (headline, when, where,
prices, anything they asked to print), so the hierarchy is planned; the style the
owner picked from the Director's own seven (`spec.direction`, which outranks a
remembered style; a look reference still outranks both); who appears when people are
drawn (`spec.people`, also in the render prompt); a person with no photo is never
given an invented face; the photo goes in as a subject and the look as a style
reference (before, every picture went in as a subject); the brand kit's logo,
imported once as one of the church's images and placed exactly, fetched only from our
own storage host; and the event's own prices, read on the server as facts, so the
planner's price check doesn't stop a flyer on prices the church set itself.
`handle_design_flyer(extra=, logo=)` takes these from server code only; the chat
door passes neither and is unchanged.
