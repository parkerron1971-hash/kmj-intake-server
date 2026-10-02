# Forms that match the published website

Hosted client forms and public event registration resolve their appearance from the business's published website. Both site-domain and API-host form routes load the same business-scoped style source. No Chief chat prompt or action changes are required: existing forms benefit as well as newly created ones.

## Resolution

1. Start with neutral accessible defaults and the saved brand kit. Both flat keys and nested colors/font_pair are supported.
2. Read simple semantic CSS values from the published website's stored HTML: body surface/text, heading/body fonts, primary button color and corner radius. Parsing is capped at 512 KiB and cached for 32 source documents. Source HTML, scripts, selectors and arbitrary stylesheets are never copied into a form.
3. Apply optional validated site_config.form_theme values: accent, surface, text_primary, text_secondary, font_heading, font_body, radius. This is the explicit adapter for websites whose design lives in external stylesheets or complex CSS not understood by the small extractor. Form settings appearance=brand opts out of website inheritance.
4. Derive readable text, button text, focus and error colors. Named fonts load through a generated Google Fonts URL; unavailable fonts retain browser fallback behavior.

Only a published site belonging to the form's business can contribute styles. An absent/unrecognized website falls back to the brand kit. No database migration, paid model call, or website fetch occurs when a visitor opens a form. Business and site metadata are loaded concurrently on the API route.

## Hosted and embedded behavior

The server renders the original field definitions, required fields, honeypot and confirmation message. Validation, failure messages and confirmation use the same theme. The event form button says Register. The responsive page has introductory context beside the form on desktop and stacks on phones.

New Client Forms embed code points to the shared renderer with embed=1, keeping fields and design current and avoiding a second set of inline submission scripts. The iframe has an accessible title, full width, and a scrollable 800px height. Existing pasted legacy snippets must be replaced once. Nothing rewrites third-party websites automatically.

## Checks

Run pytest for test_public_form_theme.py, test_site_matched_form_routes.py, test_events_on_the_site.py, test_intake_reads_as_the_server.py, test_events_rsvp.py and test_booking_page.py. Run scripts/site-matched-forms-preview.py then scripts/site-matched-forms-browser-check.py for local synthetic browser checks. Submissions are intercepted, and the preview refuses real POSTs.

Frontend CI exercises the embed contract. No Chief chat source files are modified in either repository.

## Event details and flyers

Chief-created event registration forms require a description, start date/time, IANA timezone, location/attendance instructions, and admission information. The durable form work order asks for one missing fact at a time before any insert. Create/update handlers independently validate those facts. They are stored as settings.event_details and rendered as escaped, selectable text with the local time and timezone.

Chief also asks include_flyer (yes/no). A yes requires the selected flyer_url, a public HTTPS image link; no removes the saved flyer. The form workflow never generates or spends on an image merely because a flyer is optional. If the owner requests creation, use the existing flyer workflow, publish the chosen image through its normal process, and attach its public URL with update_client_form. Generated private previews are not attachment URLs.

The flyer is responsive, opens at full size, and disappears cleanly if its image fails to load. Written event information and registration remain usable. Legacy event links remain available while their saved details are filled in. The manual editor preserves settings it does not edit, including event details, flyer preference and module linkage.
