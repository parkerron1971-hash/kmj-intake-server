---
title: One messaging place — Messages holds the church's conversation, the groups and the chats
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17: "make sure that the section where the messages are in group chat are not two messaging chats in the system."'
status: in review
prs: [kmj-intake-server#1904]
migrations: []
left_undone:
  - "Only while CHURCH_THREADS is open for a church (owner by default). Churches with it closed keep Messages exactly as before: chats only, no count on the header icon, no Home card."
  - "The group chat's poll still reloads the page when something new arrives (now also when a group note arrives); notes are not pushed into the open page without that reload."
  - "The office side is unchanged (church_threads office API, the frontend's screen)."
decisions:
  - "/my/messages is the one inbox while threads are open: (a) the church's conversation pinned first, (b) chat requests, (c) one row per group the member is in, newest first, (d) private chats. The All group leaders room sits with the groups."
  - "A group row's count is its chat's unread plus its unread notes. It opens /my/groups/<gid>/chat when the chat is open to the member (church chats on, the group's chat on, the member let in and the guidelines agreed), else the group's notes (/my/inbox/group/<gid>), whose back link goes to Messages."
  - "Every group the member is in gets a row, even before anything is in it ('No messages yet', after the dated rows)."
  - "With the church's chats off, Messages shows the church and the groups only. A member not let into chats (or who hasn't agreed to the guidelines) sees the same, with why (and a link to the guidelines at /my/messages?join=1)."
  - "A group's notes sit inside its chat as small cards at their time with their button (newest 30; none older than the oldest message shown when the chat shows a long run). The poll feed adds a notes count, so a new note reloads the chat like a new message. Opening the chat marks the group's notes read. The chat tab, while it asks the member to agree to the guidelines or says chats aren't on for them, shows the notes under that."
  - "/my/inbox 302s to /my/messages; /my/inbox/group/<gid> 302s to the chat when it's open to the member, else shows the notes; /my/inbox/church stays. A new group note's lock screen opens the group's chat when the church's chats and the group's chat are on, else the notes."
  - "One door: the header's chat icon shows whenever chats or threads are on, with one unread count (church, groups, chats) only while threads are open. Me keeps one Messages line; the separate line is gone. Home's card says Messages and opens /my/messages. Connect's Messages tab and a church's saved Messages tab show whenever either is on."
  - "Counts are kept 15 seconds per member per replica (opening the church conversation, a group's notes or a group's chat forgets them), and never computed for a chat's or the live page's poll."
related: [2026-11-17-church-threads.md]
---
Kevin saw two inboxes in the member app for a church with chats on:
Messages (group chats and private chats) and From your church (the church's
conversation and the groups' notes). Now there is one.

- `member_portal_threads.py`: `messages_page` / `render_messages` (the one
  inbox), `counts` (the header's count and Home's card), `chat_notes` and
  `note_card` (a group's notes inside its chat), the `/my/inbox` redirects.
- `member_portal_messaging.py`: `serve` hands the inbox to the above while
  threads are open; `inbox_on`; `inbox_rows` rows carry `at`; the chat feed
  counts a group's notes.
- `member_portal_groups.py`: `chat_view` reads and marks the group's notes;
  `_chat_body` puts them in the stream; the poll compares notes too; the
  chat tab shows them when the chat isn't open to the member yet.
- `member_portal.py`: the header icon and its count, Me's one Messages line,
  Home's card.
- `member_portal_church.connect_tabs`, `member_app_ui._tab_ready`:
  Messages shows when chats or threads are on.
- `church_threads.group_url`: a group note's lock screen opens its chat.
- `member_push.sweep_held`: inbox notes that waited overnight open Messages.
- `__tests__/test_church_threads.py`: 43 tests (7 new for this).
