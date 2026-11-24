---
title: A change Chief holds for your go-ahead runs when you give it (the assignment that was held three times)
date: 2026-11-23
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-23: "check out a conversation Jessica was having with Chief and the response chief was given"; then "yes" to fixing the confirm loop'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "take_back_assignment and send_handover (class C) keep two holds in turn: the sends' gate (chief_holds, kept in the process) and then the module's own. A go-ahead turn that looks first is still held again there. Only what the person reads was fixed (it was the instruction to Chief cut at 80 letters)"
  - "The leaders schedule's writes (chief_church_schedule._held), an event's volunteers (chief_event_volunteers) and the team's draft (chief_church_structure, a mid-turn read only the model sees) keep their own holds"
  - "Sensitive sends (the general gate, chief_holds) still keep what waits in the process, and the web tier runs several replicas: a go-ahead that lands on another replica holds again. The ledger here would fix that too; not changed"
  - "A written job description is up to 8,000 letters and only what fits in 1,800 is shown whole, so a long one on a marked turn is never held for a go-ahead: the person is told to ask in a message of its own"
  - "Two alike asks for the same person held together: if Chief words both differently on the go-ahead, neither is released and both are shown again (sending them as shown releases both)"
  - "The yes is spent before the handler succeeds: a handler that then fails (a read that didn't land, 'could be X or Y') means asking again"
  - "A connection that drops after Chief's first sentences streamed and before the reply's final part arrived (and the app doesn't send the message again), or a turn that fails after its reply was built: the hold was kept though its words were never read. A go-ahead as the very next message within ten minutes, with Chief sending the same change again, would run it. Hardening: on the stream, count a hold as shown only when the final part is sent"
  - "A lapse that fails twice leaves an answered 'no' releasable by a go-ahead within ten minutes, if nothing was held in between and Chief sends the same change again"
  - "Not checked: whether a background plan started from a chat turn can run one of these verbs with that turn's id and words (the handlers refuse an unattended run)"
  - "Staff turns are not saved (chief_conversations is owner-only and the turn is archived as the person): Jessica's words could not be read, only what Chief tried to do (audit_log) and the server's log. Kevin said yes to saving them; that is its own PR, with a migration"
  - "No live Chief eval was run (they bill production): the hold, what the person is shown and the release are tested through Chief's own door; that Chief sends the action again on her go-ahead is its own instruction, not measured"
decisions:
  - "What happened, from audit_log and the server's log (her words weren't kept): on her phone, 12:20, 12:24 and 12:29 PM Eastern, give_assignment for Shapretta McClain ('Put together the December announcements') was HELD each time. Each of those turns made two lookups first, the lookups marked the turn (other people's words), and the write waited 'until she says it again'. No give_assignment has ever gone through at Love City"
  - "What she was shown each time was the hold's instruction to Chief cut at 80 characters ('HELD — something read this turn was shaped like an instruction to you, so this w'): a single held action's label is the whole reply (chief_of_staff._deterministic_fallback_reply), and the label was msg[:80]"
  - "The first ask on a marked turn still waits. What waits is kept in the shared ledger (member_push_sends, kind chief_held_write, one row for exactly those fields), not the process"
  - "The person is shown what waits by the server: the verb in words, then every field that would run, each on its own line, whole, and what the verb does when a field is left out ('done: yes'). Something that can't be shown whole and plainly is never kept and never released: longer than 1,800 letters; a field the verb isn't known to take (an id in `person` outranks `who`, `clear` outranks a description); an odd field name; hidden or reordering characters; a line the reply's own cleaner would cut"
  - "A hold counts only once its words are in the reply the person read, whole (confirm_shown, after the reply is final): another action's words ahead of it can cut the reply short"
  - "A go-ahead is the person's own message (chief_of_staff.turn_words), whole and nothing else: 40 letters at most, letters and plain punctuation only, only words of yes ('go ahead', 'yes', 'do it', 'that's right'). Spoken, a bare yes is not one. Any other message lets what waited lapse, at the very start of the turn and before every reply path; what the app sends by itself (a greeting pull, a room's opening line) lapses nothing"
  - "Only the last turn that showed them something can be released, by the same login, within ten minutes, once (one write marks it used, so two sends or two replicas can't both run it)"
  - "What runs is exactly what was kept and shown, never what the later turn sent in its place, on a marked turn or a clean one; the handler's own rules of who may give whom what run again"
  - "Wired into the ordinary changes (class A) of the modules that held this way: assignments (give, start, mark done, mark stuck, send up, set the day), job descriptions (save, put back), the church's own jobs (save, remove)"
  - "A hold counts only once its words are in the reply as the person reads it: the turn checks the reply cleaned until it holds still, and the stream's own door checks again against what it actually sends (it can still replace a reply)"
  - "Four rounds of independent review ran before the merge. Round one: a 'no' or the person's name counted as a yes, the label left out fields that ran, two asks at once never released. Round two: a label could be cut from the reply and still be released, fields outranked what was shown, the lapse had gaps. Round three: the stream's second clean and its first track. Round four: the stream's stitch. Each finding fixed has a test that replays it; the last round found nothing a model can steer"
related: [2026-11-22-chief-church-lookups.md, 2026-11-12-church-assignments.md, 2026-11-17-chief-office-roster-exec.md]
---
Before building I read both repos' work logs: church assignments (11-12, the
review that added the taint on other people's words), the office roster that
tells Chief to hand out work for whoever is over the lanes (11-17), and
`chief_holds.py`, which closed this same trap for sensitive sends on 2026-09-23
("Kevin ... said 'Go ahead', and heard the same paragraph three times").

My own step 1 (#2072, 11-22) likely made this more common: it put the team and
assignment lookups in Chief's hand on a church's turn, so Chief looks before it
acts more often, and each look marks the turn. There were no earlier attempts
to compare with.

New: `chief_said_again.py` (`gate`, `wait`, `release`, `shown`, `go_ahead`,
`same_thing`, `turn_begins`, `confirm_shown`) and
`__tests__/test_chief_said_again.py`. `chief_of_staff` keeps the person's own
message for the turn (`turn_words`), starts each turn with `turn_begins`, and
checks `confirm_shown` once the reply is final.
