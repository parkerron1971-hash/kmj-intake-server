---
title: Church mail in the Email room — read, answer and write church mail in the app
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'this is good build it (the Email room mock, artifact HuNVNSzCydvvzJ4vE5iu88)'
status: in progress
prs: ["kmj-intake-server#1817", "solutionist-studio#1532"]
migrations: [supabase/APPLY-2026-11-13-church-mail-room.sql]
left_undone:
  - "Sending from the room is plain text with a signature: no attachments yet (received files open by a fresh link from the mail service while it keeps them)."
  - "Lists show the latest 100 a tray; no paging."
  - "Read and answered start from today: mail that came in before the room shows unread and unanswered."
  - "A Chief-drafted reply uses the draft lane like the Text room's; it reads the message and the church's public facts, never the rest of the inbox."
decisions:
  - "Who reads a box is who it reaches now (church_mail.reach, which now carries each target's login): the person, the office box's logins, whoever holds the role when they have a login, else where it falls. The pastor reads only the boxes that reach them, never everyone's own box. Mail to an address with no box sits in the office box that catches it, else in the pastor's Other addresses."
  - "prayer@ is a count and a link to the Prayer list, for the pastor, Admins, the church email duty and People & care; never a tray. A forward is never read in the room."
  - "Held mail is the owner's, the Admins' and the church email duty's (chief_church_mail._may_give): let through (copied to whoever the box reaches now, by the stored text; files stay with the mail service) or deleted for good. A virus, our own copy coming back, or a refused relay reply can only be deleted."
  - "A send goes from the box (reply-to the box, so the answer comes back to it and its copies), threads on the message it answers, marks that message answered for everyone on the box, sits in church_mail as direction 'out' (the box's Sent), and logs email_sent on the contact when the address is one of the church's people. No List-Unsubscribe: a person's own mail. Nothing goes before mail to the domain comes here, so no answer is lost."
  - "Nobody sends from an address they don't read. The church's own sending address is the pastor's, the Admins' and the church email duty's."
  - "A reply by email to a copy (the relay) now marks the message answered and shows in the box's Sent."
  - "Copies to your own email stay on by default; a person turns theirs off in the room (church_mail_people). Then deliver() keeps the mail for the room and sends no copy; a read of the setting that fails sends the copy."
  - "Chief's mail (the room's old trays) stays for the logins that had the room before: the owner, Admins, and logins whose areas take in People & care or the Office. Every other login sees its church mail alone; Email is in every church login's menu."
  - "Rate limits per login: 60 sends and 60 drafts an hour (church_mail_send, church_mail_draft)."
related: [2026-11-13-church-mail.md]
---
Kevin approved the Email room mock (HuNVNSzCydvvzJ4vE5iu88) with "this is
good build it".

Built:
- `church_mail_room.py` (`/church-mail/*`): the room, a tray's list, one
  message (marks it read), read/unread, send as a box, a draft to check,
  a received file's fresh link, copies on/off, held let-through and delete,
  addresses (who has which, give, take back), and the pastor's first-time
  setup (turn receiving on, the one MX record, ALIAS and existing-mail
  warnings).
- `church_mail.py`: targets carry their login, copies off is honored, the
  relay marks the message answered, the welcome note names the room.
- `supabase/APPLY-2026-11-13-church-mail-room.sql`: church_mail gets
  direction, read_by, answered_at/answered_name, sent_by and the 'sent'
  outcome; church_mail_people holds each login's copies setting. Additive.
- `__tests__/test_church_mail_room.py`: 13 tests.
