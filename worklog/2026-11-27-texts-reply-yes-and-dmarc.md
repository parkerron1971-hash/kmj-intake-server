---
title: Welcome texts only after the phone replies YES; DMARC reports kept, not copied
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'M-5 step 1, relayed by KAI: F1, welcome texts only after the phone replies YES (one ''Reply YES to get texts from <church>'' first); rank 5, DMARC aggregate reports are kept but not copied to the pastor'
status: in progress
prs: [kmj-intake-server#2100]
migrations: []
left_undone: ['the New here room (FE NewHereRoom.tsx NO_TEXTS) has no words for texts=''confirm'' yet and shows ''No texts''; a one-line FE change: confirm: ''Asked to reply YES''', 'other doors that keep an unverified web yes (booking widget, event sign-ups, /texts page) were not changed']
decisions: ['only the doors where a stranger types a number on a public page ask first: the website connect card (web) and a church''s guest card (form); the kids desk and the member app ask the person in front of them', 'a ticked box keeps no sms_consents row; the yes is kept when the phone replies (source = the door''s, user_agent ''Replied YES by text'')', a number that already said yes to the church isn't asked again, a YES more than 7 days after the question starts nothing, 'YES, Yes!, y, ''yes please'' (3 words or fewer) count; a sentence that starts with yes is a message', a DMARC report needs both a DMARC sender and a report subject, 'review of #2100: only a verified yes skips the question (kids_checkin, member_app_new, member_app, or a YES reply: connect_card_yes / guest_form_yes); a yes typed on any public page never does', 'a YES reply keeps its own source (connect_card_yes / guest_form_yes), so the carrier record always shows the reply', 'the guest is found by the number the question went to (new_here.confirm_phone), not the number on their record', a YES clears that church's STOP before the question is answered; a STOP still standing starts nothing, 'the question ends ''Reply STOP to end, HELP for help.''; when the welcome waits for the morning, a YES gets one line that they''re in', 'guests put on the path from the web door before this shipped keep their queued texts: platform-wide only 2 web-form contacts in the 30 days before, both with texts off']
related: [2026-11-27-inactive-closes-follow-up.md, 2026-11-27-contact-submit-bot-checks.md]
---
Two website connect cards at Love City (11-22 and 11-26) were one sales
campaign. Both had a fake phone number. A card's "Text me" queued four
texts to whatever number was typed, so anyone could sign a stranger up for
a church's texts.

Now a box ticked on a web page queues one text, "Reply YES to get texts
from <church> about your visit and next steps…", inside the church's
texting hours. When the phone replies YES on the church's own number
(`sms_routing` → `new_here.on_yes`), the yes is kept and that guest's
Welcome Path starts as their door would have started it. No reply means
nothing more is sent.

Church mail: Google, Microsoft and Yahoo DMARC aggregate reports (20 of 25
church mails at Love City in two weeks) are kept in the box with outcome
`stored`. They are never copied to anyone's own inbox and never alerted.
