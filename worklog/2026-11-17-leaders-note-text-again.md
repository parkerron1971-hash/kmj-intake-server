---
title: Text them again, when the leaders note's text didn't go through to some leaders
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17, on resending a leaders-note text that failed: "build that"'
status: in review
prs: [kmj-intake-server (this PR), "solutionist-studio (the frontend PR)"]
migrations: []
left_undone:
  - "A Text them again that breaks partway (an exception mid-send, not a failed text) is kept as unsure: who got it can't be told, so it never goes again that week. Same for the note's own send"
  - "A try whose record won't save (the give-back after nothing went, or the save after the texts went; each asked twice) or whose replica died mid-send stays at texts.state 'sending': 'going out now' for 10 minutes (STUCK), then unsure, and never pressed again that week. It fails closed: the leaders it missed don't get a second try. The 503 / the response's `warning` say so, and Railway gets a [leaders_note] print"
  - "After an email-only send, the 'Text it to N leaders' offer shows when the page is opened again (the send's own response doesn't read who said yes, so it can't count them)"
  - "Chief and My week don't say a text failed; only the leaders note page does"
decisions:
  - "Lane: Fix (the 11-17 leaders-note-text log's first left_undone item), Kevin's go-ahead"
  - "The send keeps texts.failed_ids (contact ids of the leaders a failed text missed, never numbers, at most 200) and texts.short (the exact words it passed to sms_routing.text_people). Read back strictly (church_leaders_note.again_of): anything not a list of uuids, a short over 300 letters, or tries that aren't 0..2 offers nothing"
  - "POST /church/leaders-note/text-again {business_id}: the note's gate (_access), this week's record only (Monday-start, the church's clock), at most AGAIN_MOST = 2 a week, billing_limits.require_card, quiet hours refuse (409, quiet_words(again=True): 'Send the text after 7 AM'), rate_limit 'church_leaders_note_text_again' (4 an hour). Then the record is taken under a new id (so two presses text once), the same words go through text_people to those leaders only (yes and STOP checked again as it goes), and the record keeps who it still missed, the tries and a short 'again' list {at, by_name, sent, failed}. Nothing went (who said yes unreadable): the record is put back and it's a 503"
  - "Only leaders still in the leaders room are texted again (recipients() is read fresh); one who has left, said STOP or no longer says yes is counted as skipped and never tried again"
  - "'first' mode: when the email went without the text (or the text stopped before any went: none_went), the same button sends the week's text_version to every leader who says yes, once; it counts as one of the two tries"
  - "GET /church/leaders-note adds text_failed (leaders a failed text missed this week) and text_again {mode, leaders, body (as phones get it), tries_left, allowed, why}; the send's response carries both too"
  - "The record stays in businesses.settings.church_leaders_note, a SERVER_KEY (business_settings.py), so the app can't write who gets a text again. No migration"
related: [2026-11-17-leaders-note-text.md, 2026-10-27-church-leaders-note.md, 2026-11-14-texting-hours.md, 2026-11-17-settings-server-keys.md]
---
Before building I read both repos' `worklog/`: the leaders note's text
(11-17, BE #1911 / FE #1619) left "a text that couldn't go can't be sent
again that week" undone; texting hours (11-14) set the quiet-hours rule and
settings server keys (11-17) put the record out of the app's reach. Nothing
else resends texts to a drawn list.

`church_leaders_note.py` (_text, text_leaders keeps failed_ids and short,
again_of, text_failed_of, again_view, text_again, the route, quiet_words'
`again`), `rate_limit.py` (the bucket), `docs/CHURCH_DUTIES.md`'s
leaders_note row.

Tests: `test_church_leaders_note_text_again.py` (23): who gets it, never a
STOP or no-yes number (even one the record names), a leader who left the
room, still-failed kept, twice a week, this week only, the gate, quiet
hours, the card, every failed read a 503 with the try given back, two
presses, a send that breaks partway, a give-back or a save that won't
save (review on #1914), the first-time text, a record in a
shape no send writes. `test_church_leaders_note_text.py` pins the record's
new keys.
