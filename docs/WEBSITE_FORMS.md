# Website contact submissions

POST /sites/{business_id}/contact-submit accepts JSON. Existing sites can keep
sending name, email, message, optional phone and sms_consent unchanged.

Optional form values connect_card and prayer_request (also connect-card and
prayer-request) select the church paths. Both accept an optional fields object;
unknown structured fields are rejected with a bounded error. Name and email
remain required. A plain submission requires message. Structured cards can omit
message; structured prayer requests require fields.request. Legacy church forms
with no fields retain their readable message.

## Limits

Church forms enforce the limits below. Plain contact forms accept each text
field up to 100,000 characters so existing published scripts do not lose longer
letters. KMJ's textarea limits new letters to 10,000 characters. Limits count
Unicode characters before trimming surrounding whitespace. Over-limit or
incorrectly typed answers return HTTP 400 with ok:false. Full accepted text is
retained in the submission's event/note; only metadata summaries are shortened.

| Church field | Limit |
| --- | --- |
| name, email | 200 characters each |
| phone | 40 characters |
| message | 5,000 characters |
| form, optional submission_id | 80 characters each |
| fields.first_name, fields.last_name | 90 characters each |
| Connect: fields.visits | 120 characters |
| Connect: fields.heard_from | 200 characters |
| Connect: fields.notes | 2,500 characters |
| Connect: fields.interests | Up to 20 nonempty strings, 120 characters each |
| Prayer: fields.request | 4,000 characters |
| Prayer: fields.follow_up | Boolean; requests personal follow-up only |

## Storage, retries and privacy

Connect cards use contacts (shown as Members for ministry businesses), deduped
within the business using existing email/phone/name identity rules. Source stays
website_contact_form; the form kind distinguishes cards. Existing status,
consent and office metadata are preserved. metadata.website_form_messages holds
at most ten recent summaries: message previews are 1,000 characters; name/email
200 and raw phone 40. Latest structured card answers also live in
metadata.website_connect_card. Complete card answers are stored in contact_note
events, visible in Members → select the person → Notes. Complete plain submissions
are stored in contact_form_submitted events, including the full message and raw
phone. Both contact and event writes must succeed before acknowledging storage.
The readable note/email uses message plus phone, or fields when message is empty.

Updates use updated_at compare-and-swap, retrying conflicts up to three times.
All synchronous database work runs via asyncio.to_thread. Each submission's
receipt id includes the business, normalized payload and optional submission_id.
The church browser retains that key after failures and creates a fresh one after
success or changed answers. Primary-key ignore-duplicate inserts and scoped
receipt reads prevent retries from adding history, notes, prayer rows or alerts,
and never reset a reviewed request or dismissed alert. Legacy callers without a
key coalesce identical payloads; use a fresh submission_id to deliberately send
identical answers again. Different answers or businesses never share a receipt.
Concurrent distinct first-time visitors may still produce duplicate contacts;
the existing schema permits shared household emails. No migration is needed.

Prayer requests use ministry_care_requests and its existing owner-only Prayer &
care reader. They never write contacts, SMS consent or lead events, capture
attribution, score leads, enter marketing/autopilot, or send visitor auto-replies.
Connect cards intentionally omit attribution, lead scoring and automatic lead
events, keeping ministry interests out of marketing analytics and outreach.

After church storage, a content-free chief_notifications alert points to Members
or Client Forms (the owner-only private-care panel). It contains no submitted
name, email, phone or answers. Alert failures print to Railway logs without
turning a stored submission into a visitor error; retries can retry the alert.

Church email recipients come exclusively from verified business sending settings,
never public overrides or platform fallbacks. Prayer email contains only a notice
and app link: no request, name or Reply-To identity. The explicit
website_forms.PRAYER_EMAIL_INCLUDE_CONTENT constant defaults to False; change it
only if Kevin approves full-content email. Plain forms retain their existing
server-side recipient rules. Visitors cannot choose a recipient.

## Responses

- HTTP 200, {"ok":true,"notification_sent":true}: stored; email accepted.
- HTTP 200, {"ok":true,"notification_sent":false}: stored; email unavailable or
  failed. The visitor should not resend; the submission is readable in Solutionist.
- HTTP 400, {"ok":false,"error":"..."}: invalid or over-limit answer; nothing saved.
- HTTP 429, {"ok":false,"error":"..."}: rate limited; nothing saved.
- HTTP 503, {"ok":false,"error":"..."}: storage failed or could not be confirmed.
  Plain forms still attempt the notification email as a fallback copy. Church
  forms do not notify before storage is confirmed.

The rate limit is five attempts per minute per IP, in memory on each replica.
Storage failures print their operation and exception to Railway logs. Optional
lead processing and notification failures cannot undo confirmed storage.
