---
title: "Member app new look (Lumen Next) — the moments in Prayer, Give and Messages"
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the Lumen Next mock (artifact 2nFp9X3q…): "go with font A and build all the moments". This piece: the moments in Prayer (the flame, I''m praying), Give (the rolling amount, the spinner, the drawn check) and Messages (a sent bubble''s flight, reactions that spring). Fonts, Home, Watch/Live and the Bible are other helpers'' pieces.'
status: in review
prs: [kmj-intake-server (moments: Prayer, Give, Messages)]
migrations: []
left_undone:
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844, motion on (frame by frame) and reduced motion (at rest)."
  - "Typing dots: they need a live connection between phones (out of scope)."
  - "The wallet-style pay sheet (Apple Pay / Google Pay): each church's address registered with Apple through the payment company (out of scope)."
  - "The mock's sent prayer page lists the group's requests under the flame ('Young Adults are praying', with I prayed): that page reads nothing today, and the wall would be reads of its own. The flame and the words are built; the wall stays on the group's Prayer tab, where I'm praying now lights."
  - "'I prayed' on the church's own requests is the Lead tab's (leaders handed a request), which keeps today's look; members see no church requests to pray for."
  - "Private chats and the church's conversation have no reactions today, so the springy reactions are a group's chat (and the leaders' room, which draws the same messages)."
decisions:
  - "Every move waits for the phone's yes to motion (prefers-reduced-motion: no-preference); at rest the pages read the same. The one exception is the Give button's spinner while the payment form loads (it says something is happening)."
  - "Prayer, sent: the flame kindles (scale from its foot, spring), flickers gently, sends out three soft rings three times (then rests); 'Your pastors have it.' and its line rise after it. The words are the page's own (who will see it), not the mock's 'We'll tell you when someone prays for you.' The italic word stays the church's colour; the flame is the mock's flame orange."
  - "I'm praying (a group's prayer wall): the tap is still the plain form post (group_prayer's form, unchanged; the old look's markup is shared). The script remembers which request (session storage, only when it turns on) and the page that comes back (?done=praying) scrolls to that request and lights it: flame-coloured, the icon pops, a ring goes out. Praying stays flame-coloured at rest (only the praying form: Praise God keeps its colour). No storage (a private window): nothing is remembered, nothing breaks."
  - "Give, the amount: each digit a column of 0–9 that slides to its number on a spring (tabular figures); a new shape (25 to 100, 50 to 1,250.50) starts its columns at 0 and rolls them up. Lumen's own give script draws it (member_lumen_give.GIVE_JS); the give page's payment script is byte for byte the same (the test still pins it). A long amount steps down a size to stay on one line (it wrapped under the $ before)."
  - "Give, while the payment form loads: the payment script disables the Give button (as always); the new sheet turns that into a spinner on the button. Nothing else changes."
  - "Give, the thank-you (back from a gift, ?thanks=1): a ring spins round and closes (1 s), fills with the church's colour, the check draws over it, then 'Thank you, Ana.' and today's words rise. At rest: the filled circle and the check."
  - "Messages, sent: instant send's bubble (li.mis-pending) flies up from the box on a spring. Instant send replaces it with the server's message as soon as the answer comes (often mid-flight here); the script watches the list and gives the new bubble the same flight from where the old one was (a negative delay), so nothing jumps. Instant send itself is untouched: ids, JSON, its script, sent / refused (words back in the box) / held, all tested in Chromium and WebKit in the church's conversation, a private chat and a group's chat."
  - "Messages, reactions (a group's chat): the picker (Love, Praying, Amen, Reply, Report) springs open from the bubble, its buttons one after another. A reaction lands in place: the same /my/messages/<t>/react route, asked for the JSON it already gives ({ok, on}); the chip pops in (or its count moves, or it leaves), the picker closes, focus returns to the message. The server refuses (a preview, a gone message): the plain post runs, so its own message shows. The answer is lost: the page reloads, so what it shows is true."
  - "The send button gives a little under the thumb (spring)."
  - "Reads: the same on and off and the same as main on every page touched (give, the thank-you, prayer sent, a group's prayer wall and chat, the church's conversation, a private chat). Server-Timing equal (harness, median of 20). Off: byte for byte main on 108 page and scene dumps (96 identical as bytes, 12 differing only in the clock time of rows the harness seeds relative to now, between two runs a minute apart)."
  - "Where it lives: member_lumen_moments.py (CSS, the flame and check markup, the pages' script). The CSS joins the hashed Lumen file through member_lumen_ui.templates(), every rule under body.lm; the script rides only on a conversation (member_portal._lumen_frame's head) and a group's prayer wall. In the sheet the block sits after the motion block (member_lumen_motion) and before the type block, which stays last."
related: [2026-11-18-member-lumen-people.md, 2026-11-19-member-lumen-give.md, 2026-11-18-member-instant-send.md]
---

Harness, scripts and frames: the session scratchpad's `lnext-moments` folder (harness.py, flows.py, rest.py, dump.py,
reads.py, timing.py; shots/, rest/, side-by-side/).
