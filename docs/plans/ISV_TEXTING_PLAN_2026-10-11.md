# Texting under each business's own name (Twilio ISV) — plan

2026-10-11. Kevin: "write up the isv build plan and start it."

## Why

Every business on Solutionist texts today under ONE registration: our
Primary Customer Profile (The Solutionist System LLC, identity "Direct
customer"), one A2P brand, one campaign, one Messaging Service, and every
number (the shared platform number and each business's own line) in its pool.

Twilio's rules for a platform like ours (researched 2026-10-11, Twilio pages
dated 2026):

- We are an ISV by Twilio's own definition ("a company that provides
  communication services to hair salons").
- A campaign that represents more than one company is rejected by name:
  error 30926, "Multiple companies cannot share a single campaign"; 30894
  when the registration uses the platform's details instead of the
  customer's. Carriers judge whose message it is (who the person signed up
  with, who the text is about), not which number or prefix sends it.
- One narrow exception: fixed templates the businesses cannot change (our
  booking confirmations and appointment reminders) may stay under the
  platform. Owner-written texts, broadcasts, editable automatic notes and
  texts Chief writes may not.
- One campaign shares one T-Mobile daily cap (per EIN), and one business's
  bad traffic can suspend everyone.

So each business that texts gets its OWN registration: its business as the
brand, its own campaign and Messaging Service, its own number, with us as
the ISV doing it for them. To the business's customers nothing changes.

## What a registration is (per business)

Twilio's ISV API sequence (Standard / Low-Volume Standard):

1. **Secondary Customer Profile** (Trust Hub): the business's legal name,
   type, EIN, address, website, industry, authorized representative.
   (Twilio recommends a subaccount per business; see decision D3.)
2. **A2P trust product** (messaging profile) tied to that profile.
3. **Brand** (BrandRegistration): Low-Volume Standard by default, Sole
   Proprietor when the business has no EIN.
4. **Messaging Service** for the business (inbound and status webhooks ours).
5. **Campaign** (UsAppToPerson) on that service: use case Low Volume Mixed
   (reminders, replies AND offers in one, so no use-case change is ever
   needed: a use case can't be edited, only deleted and re-registered).
   Description, message flow (how people opt in), 2+ sample messages naming
   the business, opt-in/opt-out/help keywords and replies, privacy policy
   URL and terms URL (required on every campaign since June 2026).
6. **Number**: bought as today (sms_numbers_router), attached to the
   business's Messaging Service instead of ours.

Costs per business (Twilio, Aug 2025+ fees): brand $4.50 + campaign vetting
$15 once; campaign $1.50/month (Low Volume Mixed) or $2 (Sole Proprietor);
number $1.15/month; texts ~1.3 cents each. A typical small business: about
$19.50 once and about $9/month at 500 texts.

Timelines: our primary profile change (support ticket #29903903, filed
2026-10-11) "72 hours or more"; each business's brand usually minutes;
campaign review 10–15 days currently (Twilio's pages range from 5 days to
several weeks); a rejection restarts the review. Businesses go in parallel.

## Decisions (defaults proposed; Kevin decides)

- **D1 Who pays the Twilio fees.** Default: included for businesses on a
  plan that texts; we absorb ~$19.50 once and ~$2.65/month per business plus
  the texts. Alternative: a texting add-on price on lower plans.
- **D2 Who registers.** Under ISV, owner-written texting needs the
  business's own registration AND its own number (a number belongs to one
  campaign). Default: any business that wants two-way texting, broadcasts or
  automatic notes registers (and gets a number); fixed confirmations and
  reminders keep going out from the shared number for everyone meanwhile.
- **D3 Subaccount per business.** Twilio recommends it (isolates billing and
  suspensions). Default: wait for Twilio's answer on the ticket, then decide.
- **D4 EIN.** Default: never stored by us. The owner types it at submit time
  and it goes straight to Twilio; we keep only whether one was given.
- **D5 No EIN (sole proprietors).** Default: the Sole Proprietor path ($4.50
  + $2/month, one number, the owner confirms by a code texted to their own
  mobile within 24 hours).
- **D6 Use case.** Default: Low Volume Mixed for everyone (covers marketing
  too, up to ~6,000 texts a day); Standard only for a business that outgrows
  it.

## The build, in order

**Step 1: everything Twilio's reviewers check, built and visible (no Twilio
calls, no money).** *Started 2026-10-11.*
- Each business site serves `/texting-terms` and `/texting-privacy`: who
  texts, what about, how often, STOP and HELP, "msg & data rates", and the
  privacy line reviewers look for ("We do not sell or share your SMS opt-in
  data..."), in the business's own name. These are the campaign's privacy
  policy and terms URLs.
- The campaign's words, generated from the business: description, message
  flow (the booking-page and contact-form checkboxes, quoted, which already
  name the business), sample messages, keywords and replies.
- A readiness check: the site is live, booking is live, the pages answer,
  the registration answers are complete.
- The owner's registration answers, saved (never the EIN):
  `texting_registrations` (one row per business: answers, status draft).

**Step 2: the owner's screen.** In the app: "Texting under your own name":
the answers form, the readiness checklist, the exact words Twilio will see,
and later the approval status ("Being approved, usually about 2 weeks").

**Step 3: submit to Twilio (after the ticket and D1–D3).** A Twilio ISV
client: create the profile, trust product, brand, Messaging Service and
campaign through the API; the EIN typed at submit; a sweep (and Twilio's
status callbacks) moves the status along and shows a rejection's reason in
plain words with what to fix. Pilot on one of Kevin's own businesses first
(KMJ Creative Solutions or Love City), because a rejection costs two weeks.

- The booking page's booking-texts checkbox names "Solutionist System",
  not the business, and links our privacy and terms pages. Under ISV the
  opt-in proof must name the business (error 30927), but our approved
  Direct campaign quotes today's words verbatim. So at submit, that
  business's checkbox switches to "from {business}" and links its own
  `/texting-terms` and `/texting-privacy`; other businesses keep today's
  words. (The site contact form already names the business first.)

**Step 4: send under the business's name.** On approval: buy or move the
business's number into its own Messaging Service; `sms_routing.sender_brand()`
returns the business; owner-written texts, broadcasts and automatic notes go
from its line; journeys may text (marketing is inside Low Volume Mixed), so
the JOURNEY_TEXTS platform switch is replaced by "this business is approved".

**Step 5: move everyone.** Each texting business registers; the shared
number keeps only fixed confirmations and reminders (the templated
exception) and replies for businesses not yet approved.

## Risks and how they're handled

- A rejection costs two weeks: the readiness check and the generated words
  follow Twilio's published rejection reasons (vague description, samples
  without the business name, opt-in proof that names someone else, missing
  privacy line, URL shorteners), and the pilot runs on our own business.
- Our current campaign must keep working while businesses move: asked in the
  ticket; nothing in steps 1–2 touches it.
- EIN and the representative's details are sensitive: the EIN is never
  stored; the rest is the owner's own data, service-role only (RLS on).
