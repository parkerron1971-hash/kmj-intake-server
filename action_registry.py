"""
action_registry.py — what each Chief action DOES, as data (S1.1 steps 1-2).

WHY THIS EXISTS
  `chief_of_staff.ACTION_HANDLERS` is a bare {verb: handler} dict. Nothing in
  it says whether a verb reads or writes, whether a write can be undone, or
  whether it reaches the outside world. Three things need that answer and each
  currently invents its own:

    - Chief autonomy — "may Chief do this without asking?" (the A/B/C
      reversibility model in docs/extensibility_and_autonomy.md §2.4)
    - An agent-facing MCP surface — "which verbs may an outside agent call?"
      (docs/future_architecture.md §3, and PERSONAL_AGENT_ARCHITECTURE.md §4's
      open-on-read / closed-on-write rule in the frontend repo)
    - `chief_action_reasoner.SAFE_REMAP_ACTIONS` — a hand-maintained subset
      that a comment merely *asks* to stay in sync with the registry

WHY IT IS NOT DERIVED FROM THE CODE
  Static analysis was tried and is not merely imperfect, it is confidently
  wrong in the worst places. A detector keyed on `"POST"/"PATCH"/"DELETE"` in
  the handler body reports `send_sms` as read-only (it delegates to
  `/sms/send`), and `draft_and_send` as a pure read (the verb sends email).
  Roughly 44% of verbs contain no local write yet a majority of those still
  have effects, because handlers delegate to routers, services and
  `asyncio.to_thread`. So every entry here is a HUMAN judgment with a written
  reason, and a wrong entry is a security bug, not a lint failure.

THE TWO AXES
  `effect` answers "what kind of thing is this?"

    read   — returns information, changes nothing. The set an agent-facing
             read-only surface may expose.
    ui     — a client-side directive (navigate, open a panel, start a timer).
             Touches no business data and is MEANINGLESS off the app surface:
             these are excluded from any agent surface rather than exposed.
    write  — changes state. Carries a `reversibility` (below).

  `reversibility` answers "if this write was wrong, what then?" — the A/B/C
  model from extensibility_and_autonomy.md §2.4, applied only to writes:

    A — cleanly undoable. Records, drafts, soft-deletes, deactivations.
        A wrong one is an edit away from right. Auto-eligible.
    B — recall window. Leaves the system but not instantly (a delayed send).
        Auto-eligible only with an explicit granted scope.
    C — irreversible or money-touching. Hard deletes, sends, payments, GL
        posts, anything that leaves a compliance trail. PROPOSAL-ONLY,
        FOREVER. Not a tuning knob.

WHAT CLASS C DOES AND DOES NOT MEAN
  It does NOT mean Chief cannot do the thing. It means Chief will not do it
  *unprompted*. A practitioner who says "send that invoice" has supplied the
  approval; `is_autonomy_eligible` only governs acting without being asked.
  So classing a verb C costs nothing on the explicit-request path and is the
  cheap, safe answer whenever money or the outside world is involved.

  Note the corollary for class B: §2.4 defines it as a send with a recall
  window, and this system has no delayed-send outbox — every send is
  immediate and final. So NOTHING is class B today. Each outbound verb below
  records that it becomes B on the day an outbox exists. Inventing a B now
  would hand out autonomy against a safety net that isn't there.

DEFAULT-DENY IS WHAT MAKES A PARTIAL REGISTRY SAFE
  All 149 verbs are classified. `UNCLASSIFIED` is empty and should stay that way,
  but it exists because "not decided yet" is a better entry than a guess.
  Every accessor below returns the *refusing* answer for a verb it does not
  know: not exposable, not autonomy-eligible, reversibility None. So an
  unclassified verb behaves exactly like a class-C one until somebody rules
  on it. Never add a fallback that guesses — an unknown verb must stay
  unknown.

KEEPING IT HONEST
  `__tests__/test_action_registry.py` asserts the registry and
  `ACTION_HANDLERS` describe the same verb set. A verb added to Chief without
  a classification (or an UNCLASSIFIED note) fails there instead of silently
  defaulting to denied and quietly not working. Same discipline as
  `vertical_registry.KNOWN_GAPS` + `test_vertical_registry.py`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

# ── effect kinds ─────────────────────────────────────────────────────
READ = "read"
UI = "ui"
WRITE = "write"

EFFECTS = (READ, UI, WRITE)
REVERSIBILITY_CLASSES = ("A", "B", "C")


def _r(why: str, sensitive: bool = False) -> Dict[str, Any]:
    """A read. `sensitive=True` marks one that must NOT leave the app even
    though it changes nothing.

    Until this existed, `read` and `safe to hand an outside agent` were the
    same bit, and exposure was derived from effect alone. Donor giving
    records are where those two come apart: a church's giving history is
    among the most confidential data it holds — many churches restrict it
    from their own staff — and it is unambiguously a read.

    'Cannot break anything' and 'may be read by a third party' are different
    questions. This is the second one."""
    entry: Dict[str, Any] = {"effect": READ, "why": why}
    if sensitive:
        entry["sensitive"] = True
    return entry


def _ui(why: str) -> Dict[str, str]:
    return {"effect": UI, "why": why}


def _w(rev: str, why: str, bulk: bool = False) -> Dict[str, Any]:
    """A write. `bulk=True` marks a verb that acts on a whole set at once —
    those are never autonomy-eligible whatever their class, because the
    reversibility of one row says nothing about undoing forty of them."""
    entry: Dict[str, Any] = {"effect": WRITE, "reversibility": rev, "why": why}
    if bulk:
        entry["bulk"] = True
    return entry


# ─────────────────────────────────────────────────────────────────────
# REGISTRY — every entry verified against its handler, 2026-07-27.
# ─────────────────────────────────────────────────────────────────────

REGISTRY: Dict[str, Dict[str, Any]] = {

    # ── reads ────────────────────────────────────────────────────────
    # Verified: each fetches and formats, and reaches nothing that writes.
    "catch_up":            _r("summarizes recent activity from reads only"),
    "check_goals":         _r("computes goal progress from business settings + live data"),
    "contact_deep_dive":   _r("assembles one contact's history"),
    "list_availability":   _r("reads the availability configuration"),
    "list_module_entries": _r("lists rows of a custom module"),
    "list_offerings":      _r("lists offerings"),
    "list_products":       _r("lists products"),
    "list_projects":       _r("lists projects"),
    "list_scheduled":      _r("reads queued chief_scheduled_actions"),
    "offering_readiness":  _r("offering_profiles.business_readiness — pure report"),
    "recall_conversation": _r("searches prior conversation"),
    # GUIDES, never narrates: returns a filter + a count and sends the
    # reader to the rows. Chief is deliberately given no row contents,
    # so it cannot summarise the ledger any more than the navigator can.
    # SENSITIVE, so it never reaches the MCP agent surface. Read-ness
    # asks "can this break anything"; sensitivity asks "may a third party
    # see it" — and this is the record of who did what to which client.
    # It is also the one surface now behind step-up authentication for
    # signed-in humans, and a long-lived agent token must not be the way
    # around that.
    "search_ledger":       _r("turns a question into a FILTER over the action "
                              "ledger and points at the rows. Returns counts, "
                              "never row contents", sensitive=True),
    "show_revenue":        _r("reads revenue figures"),
    "site_health":         _r("reads site + booking config and reports"),
    "what_undo":           _r("reports what undo_last WOULD reverse. Pure read — undo is "
                              "frightening in proportion to how vague it is"),
    "check_balance":       _r("reads the customer_balances view — what a client has "
                              "prepaid and not yet consumed"),
    "unbilled_time":       _r("totals unbilled time_entries — hours worked and not yet "
                              "charged, for one client or the whole firm"),
    "campaign_status":     _r("campaigns + send progress from the campaign_sends ledger; "
                              "replies/bookings surfaced as activity, not attribution"),
    "list_expenses":       _r("lists business_expenses rows with an honest total; same "
                              "financial class as show_revenue, which is already exposed"),
    "check_inventory":     _r("stock levels + low-stock list for store products, computed "
                              "from offerings.inventory_qty and the settings thresholds. "
                              "Fetches and formats; reaches nothing that writes. Same "
                              "operational class as list_offerings/list_products"),
    # SENSITIVE. Reads, and they change nothing — but a congregation's giving
    # history is among the most confidential data a church holds. Many
    # churches deliberately keep it from their own staff, and Chief's own
    # ministry reminder is that "giving is access-isolated, not
    # transactional". It does not go on an agent surface.
    "giving_statement":    _r("one donor's annual contribution statement (IRS Pub 1771 "
                              "shape). Computes from paid gifts; persists nothing",
                              sensitive=True),
    "giving_statements_run": _r("every donor's giving totals for a tax year — the January "
                                "mailing list. Read-only", sensitive=True),

    # ── UI directives ────────────────────────────────────────────────
    # Verified: pass-throughs the frontend acts on. No persistence.
    # Deliberately NOT exposable — an off-app caller has no UI to drive.
    "navigate":         _ui("tells the app which tab to open"),
    "open_calendar":    _ui("opens the calendar panel"),
    "open_documents":   _ui("opens the documents panel"),
    "set_chat_window":  _ui("opens/closes the chat window; voice keep-alive"),
    "set_timer":        _ui("returns timer metadata; timerManager runs it client-side"),

    # ── writes, class A ──────────────────────────────────────────────
    # The first 26 adopt chief_action_reasoner.SAFE_REMAP_ACTIONS, whose
    # own contract is "reversible + non-sending + non-financial". That is
    # a documented prior judgment; re-deriving it would only risk
    # disagreeing with the code that already relies on it.
    "create_contact":                _w("A", "creates an editable contact row"),
    "update_contact":                _w("A", "edits a contact; prior values re-enterable"),
    "update_contact_status":         _w("A", "sets a status field"),
    "create_note":                   _w("A", "creates a note"),
    "create_task":                   _w("A", "creates a task"),
    "complete_task":                 _w("A", "flips a task's done flag; re-openable"),
    "create_goal":                   _w("A", "creates a goal"),
    "add_reminder":                  _w("A", "creates a reminder"),
    "capture_idea":                  _w("A", "stores an idea"),
    "log_activity":                  _w("A", "appends an activity row"),
    "create_session":                _w("A", "inserts a /sessions row; verified to send nothing"),
    "update_session":                _w("A", "edits a session row"),
    "create_project":                _w("A", "creates a project"),
    "update_project":                _w("A", "edits a project"),
    "create_module_entry":           _w("A", "creates a module row"),
    "update_module_entry":           _w("A", "edits a module row"),
    "ensure_module":                 _w("A", "creates a module if absent"),
    "create_offering":               _w("A", "creates an offering"),
    "update_offering":               _w("A", "edits an offering"),
    "draft_email":                   _w("A", "queues a draft to /agent_queue — approval still required to send"),
    "draft_nurture":                 _w("A", "queues a check-in draft; not sent"),
    "set_business_policy":           _w("A", "records a policy value"),
    "add_faq":                       _w("A", "adds an FAQ entry"),
    "remember":                      _w("A", "writes a chief_memories row; deactivatable via forget"),
    "add_testimonial":               _w("A", "adds a testimonial"),
    "update_business_profile_field": _w("A", "sets one profile field"),

    # Verified individually beyond the adopted set.
    "forget":               _w("A", "deactivates a memory (is_active flip), does not delete"),
    "delete_module_entry":  _w("A", "SOFT delete — flips status to 'deleted', row survives"),
    "analyze_trends":       _w("A", "runs the insight engine now; writes insight memories + an "
                                    "activity row, both deactivatable. Note: invokes the model, "
                                    "so it is a spend vector on any metered surface"),

    # Reads that compute rather than fetch. They persist nothing, so an
    # agent surface may call them — but each spends model tokens, which is
    # why the note says so out loud.
    "propose_brand_kit_from_context": _r("generates a brand-kit proposal and returns it; the "
                                         "docstring is explicit that it does NOT save. Model spend"),
    "propose_voice_rule":            _r("returns a proposed rule; 'We do NOT store the rule here' "
                                        "— the frontend calls add_voice_rule on accept"),
    "list_bookkeeping_proposals":    _r("lists existing proposal rows"),

    # ── writes, class A (continued) ──────────────────────────────────
    "accept_module_spec":     _w("A", "materializes a draft spec into a custom_modules row; "
                                      "idempotent, and the module can be archived after"),
    "add_block_range":        _w("A", "blocks a date range; remove_block_range is the exact undo"),
    "remove_block_range":     _w("A", "removes a block; add_block_range restores it"),
    "add_voice_rule":         _w("A", "adds a voice rule; remove_voice_rule is the undo"),
    "remove_voice_rule":      _w("A", "removes a voice rule; add_voice_rule restores it"),
    "update_voice_style":     _w("A", "edits voice style fields"),
    "update_voice_sample":    _w("A", "edits a voice sample"),
    "update_voice_profile":   _w("A", "merges free-text fields into businesses.voice_profile"),
    "advance_phase":          _w("A", "moves a strategy track's phase pointer; re-settable"),
    "advance_business_phase": _w("A", "moves a business track's phase pointer; re-settable"),
    "archive_offering":       _w("A", "SOFT delete — is_active=false + archived_at, and existing "
                                      "references keep working off denormalized fields"),
    "dismiss_draft":          _w("A", "flips a queued draft's status to dismissed; the row survives"),
    "edit_draft":             _w("A", "edits a queued draft in place — still a draft, still unsent"),
    "rewrite_draft":          _w("A", "regenerates a queued draft's body; still unsent"),
    "bulk_dismiss":           _w("A", "flips status to dismissed across a filtered set; each row "
                                      "survives, but forty at once is not one undo", bulk=True),
    "cancel_scheduled":       _w("A", "cancels a queued scheduled action; schedule_action re-adds it"),
    "cancel_booking":         _w("A", "cancels an appointment. Verified it sends NO client email — "
                                      "only create_booking does. §2.4 lists scheduling as class A. "
                                      "Worth noting separately that a silently-cancelled client "
                                      "appointment is a product question, not a classification one"),
    "reschedule_booking":     _w("A", "moves an appointment; sends nothing, same as cancel"),
    "create_course":          _w("A", "scaffolds academy_courses + academy_lessons rows"),
    "create_growth_objective": _w("A", "materializes an objective plus its modules/workflows/"
                                       "milestones — a lot of rows, all ordinary records"),
    "enroll_student":         _w("A", "inserts an academy_enrollments row"),
    "mark_reply_read":        _w("A", "flips email_replies.read; re-markable"),
    "mark_sms_read":          _w("A", "flips sms_messages.read; re-markable"),
    "notify_practitioner":    _w("A", "in-app notification + push to the OWNER. It does leave the "
                                      "device, but never reaches a client, so it is not the "
                                      "client-facing send class B exists for"),
    "plan_content":           _w("A", "adds a planned post to settings.content_calendar"),
    "propose_module_from_intake": _w("A", "writes ModuleSpec DRAFTS that accept_module_spec later "
                                          "materializes — the draft itself changes nothing live"),
    "record_edit_pattern":    _w("A", "silent observation row in edit_observations"),
    "reject_bookkeeping_proposal": _w("A", "the module's own docstring: 'Rejecting is inert'"),
    "reject_module_spec":     _w("A", "marks a draft spec rejected; nothing was live yet"),
    "remove_testimonial":     _w("A", "removes one entry from the testimonials array; re-addable"),
    "restore_previous_site":  _w("A", "the undo verb itself — swaps the live site back to the "
                                      "previous compose. Docstring: 'no external effects, fully "
                                      "reversible (the swap is symmetric)'"),
    "run_agent":              _w("A", "dispatches an agent whose output lands in /agent_queue as a "
                                      "DRAFT. Verified: it writes queue rows, it does not send. "
                                      "Sending is approve_draft, which is class C"),
    "generate_briefing":      _w("A", "delegates to run_agent('briefing') — inherits its class"),
    "generate_insights":      _w("A", "runs the insight engine; writes insight memories, which "
                                      "forget deactivates. Model spend"),
    "review_books":           _w("A", "writes bookkeeping PROPOSALS only — inert until approved"),
    "run_market_research":    _w("A", "writes analysis onto the strategy track. Model spend"),
    "save_business_model":    _w("A", "saves a strategy-track deliverable"),
    "save_launch_plan":       _w("A", "saves a strategy-track deliverable"),
    "save_packages":          _w("A", "saves a strategy-track deliverable"),
    "save_phase":             _w("A", "saves a strategy-track phase deliverable"),
    "save_business_phase":    _w("A", "saves a business-track phase deliverable onto the track "
                                      "row; re-saving overwrites that phase only"),
    "business_session_summary": _w("A", "appends a Business Track session summary to "
                                        "phases.session_log"),
    "complete_business_track": _w("A", "flips the business track to completed and stamps "
                                       "settings.business_track_done. Deliberately NOT the "
                                       "composite that complete_strategy_track is — it generates "
                                       "no site, seeds no module, sends nothing. The work it "
                                       "points at is the plug-in list, which the practitioner "
                                       "drives by hand"),
    "save_pricing":           _w("A", "saves a strategy-track deliverable"),
    "save_projections":       _w("A", "saves a strategy-track deliverable"),
    "save_swot":              _w("A", "saves a strategy-track deliverable"),
    "session_summary":        _w("A", "appends a coaching-session summary to phases.session_log"),
    "save_email_template":    _w("A", "saves a reusable template into settings; editable"),
    "save_note":              _w("A", "files a note (chief_memories, category='note')"),
    "set_availability_day":       _w("A", "sets one day's weekly hours; re-settable"),
    "set_availability_override":  _w("A", "sets a date-specific override; re-settable"),
    "set_lead_time":              _w("A", "sets required booking lead time"),
    "set_slot_granularity":       _w("A", "sets the slot grid spacing"),
    "set_business_timezone":      _w("A", "sets the canonical timezone"),
    "set_site_capability":        _w("A", "records a capability into the discovery dossier"),
    "update_contact_health":      _w("A", "sets a contact's health score"),
    "update_practitioner_profile_field": _w("A", "sets one practitioner_profiles field (owner-scoped)"),
    "upgrade_module_archetype":   _w("A", "refines an existing module's archetype params"),
    "contract_pdf":           _w("A", "renders an existing draft as a branded PDF and returns the "
                                      "URL. Produces an artifact; sends nothing"),
    "undo_last":              _w("A", "runs the INVERSE of the most recent reversible action, "
                                      "from action_inverse's hand-judged table. Its own class is "
                                      "A because every inverse it can build is itself a class A "
                                      "handler — it cannot reach a class C verb, because no class "
                                      "C verb has an inverse registered. A failed undo leaves the "
                                      "row undoable rather than marking it done"),
    "grant_balance":          _w("A", "appends a POSITIVE row to customer_ledger — records that a "
                                      "client prepaid for sessions/hours/a deposit. Money-ADJACENT "
                                      "but not money-touching: reaches no Stripe object and posts "
                                      "no GL entry, so the create_invoice reasoning for C does not "
                                      "apply. The ledger is append-only, so a wrong grant is "
                                      "corrected by an adjusting row rather than an edit — which is "
                                      "the class A test, not a weaker version of it"),
    "consume_balance":        _w("A", "appends a NEGATIVE row — records that a prepaid session or "
                                      "hour was delivered. Refuses to overdraw unless explicitly "
                                      "told to, and reverses its own row if it loses a concurrent "
                                      "draw. Same reasoning as grant_balance"),
    "log_time":               _w("A", "inserts a time_entries row — records that work was done. "
                                      "Status starts 'unbilled', so nothing has been charged to "
                                      "anyone; a wrong entry is edited or written off"),
    "bill_time_to_retainer":  _w("A", "moves a prepaid retainer balance the client already funded "
                                      "and flips the entry to 'billed'. Posts no GL entry and "
                                      "reaches no Stripe object — same reasoning as "
                                      "consume_balance, which it delegates to. The ledger row id "
                                      "is stored on the entry so the same hours cannot be billed "
                                      "twice"),
    "write_off_time":         _w("A", "flips an unbilled entry to 'written_off'. The row survives "
                                      "and the status is editable back"),
    "draft_contract":         _w("A", "drafts an engagement letter for one contact — a draft, and "
                                      "there is no send_for_signature verb to pair it with yet"),
    "generate_document":      _w("A", "generates a formal document from the template library into "
                                      "ONE agent_queue draft row — same reasoning as draft_contract: "
                                      "reviewable, editable, deletable, inert until approved. The "
                                      "handler refuses to invent required fields (fee, scope, "
                                      "amount) — it asks instead, so a wrong number can't enter a "
                                      "contract without a human typing it"),
    "compose_template":       _w("A", "drafts a brand-new reusable agreement TEMPLATE into ONE "
                                      "business_doc_templates row — no document, no draft, nothing "
                                      "client-facing; generating FROM it still goes through the "
                                      "approve-first queue. The row is deletable in the picker. The "
                                      "model writes only deal-specific clauses; the server splices "
                                      "the spine (dispute, general terms, signatures), so a composed "
                                      "contract cannot omit severability or invent a signature block"),
    "plan_campaign":          _w("A", "inserts a campaigns row with status='draft' — the same "
                                      "shape as draft_email: a reviewable artifact, and nothing "
                                      "sends until launch_campaign (which is class C). The drafting "
                                      "call is model spend, said out loud as ever"),
    "log_expense":            _w("A", "creates a business_expenses row — bookkeeping ABOUT money "
                                      "already spent, not movement of it (grant_balance reasoning). "
                                      "The GL pickup is the same trigger path as a UI-created "
                                      "expense; a wrong row is an edit or delete away from right. "
                                      "Refuses closed-period dates rather than writing into them"),

    # ── writes, class C ──────────────────────────────────────────────
    # Two families: what leaves the system, and what touches money.
    #
    # On outbound: §2.4 reserves class B for a send with a recall window
    # (its example is a 60-second delayed send). No such outbox exists in
    # this system today — every send is immediate and final — so there is
    # currently NOTHING that can honestly be class B, and each entry below
    # records that it becomes B on the day an outbox lands. Inventing a B
    # here would grant autonomy against a safety net that does not exist.
    "delete_contact":       _w("C", "HARD delete — issues DELETE /contacts; `contacts` has no "
                                    "soft-delete column and no archive, so the row is gone. Now "
                                    "guarded: Chief refuses when anything is attached (sessions "
                                    "and academy_enrollments CASCADE, eight more tables orphan), "
                                    "so it can only reach a contact with no history. Stays C — "
                                    "the guard bounds the blast radius, it does not make the "
                                    "delete undoable"),
    "approve_draft":        _w("C", "approves AND SENDS a queued draft — the result string is "
                                    "literally 'approved and sent'. Becomes B with an outbox"),
    "draft_and_send":       _w("C", "drafts and sends in one step; the name is the whole story. "
                                    "Becomes B with an outbox"),
    "send_report":          _w("C", "emails a report out. Becomes B with an outbox"),
    "send_sms":             _w("C", "Telnyx, immediate, no recall. Becomes B with an outbox"),
    "batch_email":          _w("C", "sends the same body to a list of contacts. Outbound AND bulk",
                               bulk=True),
    "launch_campaign":      _w("C", "arms a campaign's touches to send to the WHOLE audience over "
                                    "the following days — outbound AND bulk, batch_email's shape "
                                    "stretched across a schedule. The chat gate holds it toward "
                                    "the Campaigns screen (the campaign is already its own "
                                    "reviewable draft) unless nurture autopilot is full. Becomes "
                                    "no less C with an outbox — the sweep already spaces sends, "
                                    "and pausing recalls only what hasn't gone yet", bulk=True),
    "pause_campaign":       _w("C", "stops a running campaign — protective, single-target, and "
                                    "run immediately on request. C rather than A because the "
                                    "campaign lifecycle stays proposal-only end to end: "
                                    "pause/resume reshapes the send schedule of an in-flight bulk "
                                    "outreach, and Chief silently pausing a practitioner's launched "
                                    "campaign is a marketing decision, not a bookkeeping edit"),
    "update_expense":       _w("C", "edits a financial record: the GL trigger reverses and reposts "
                                    "the row's journal entries. The edit itself is one PATCH, but "
                                    "the books it rewrites carry a compliance trail — same family "
                                    "as mark_invoice_paid. Refuses closed-period dates (both the "
                                    "row's date and any new one) toward the audited override flow"),
    "delete_expense":       _w("C", "HARD delete of a business_expenses row; the GL trigger "
                                    "reverses its ledger entries. Refuses when the expense sits in "
                                    "a closed accounting period. Also the documented MANUAL "
                                    "inverse of log_expense until action_inverse rules on an "
                                    "automatic one"),
    "bulk_approve":         _w("C", "approves and sends every draft matching a filter. Outbound "
                                    "AND bulk — the worst combination in the registry", bulk=True),
    "publish_post":         _w("C", "publishes to Facebook/Instagram via Meta. There is an unpublish, "
                                    "but a post that was seen cannot be unseen"),
    "create_booking":       _w("C", "creates the appointment AND emails the client a confirmation "
                                    "(send_confirmation defaults true). The send is what makes this "
                                    "C while cancel/reschedule are A"),
    "create_recurring_booking": _w("C", "books a weekly series (up to 26 occurrences) onto a "
                                        "client's calendar in one verb. Sends NO email (unlike "
                                        "create_booking — verified), but a standing commitment on "
                                        "a client's next six months is not something Chief should "
                                        "invent unprompted; mirrors create_booking's C. Single "
                                        "series target, not the bulk flag — one client, one slot"),
    "cancel_recurring_booking": _w("C", "cancels every FUTURE occurrence of a series in one verb "
                                        "(past entries untouched, rescheduled-detached ones "
                                        "skipped). One cancel_booking is class A; erasing a "
                                        "client's standing slot for months is a different blast "
                                        "radius, so the cheap safe answer applies. Single series "
                                        "target, not bulk"),
    "create_invoice":       _w("C", "money-touching, which §2.4 makes C on its own. Also accepts "
                                    "auto_send on a recurrence, arming future unattended sends — a "
                                    "standing rule, not a one-off write. (Revised from an earlier "
                                    "'A' recommendation made before reading the handler.)"),
    "send_invoice":         _w("C", "sends an invoice and touches Stripe"),
    "mark_invoice_paid":    _w("C", "records payment — a ledger fact with a compliance trail"),
    "cancel_recurring_invoice": _w("C", "stops or cancels recurring billing; money-touching"),
    "approve_bookkeeping_proposal": _w("C", "executes a categorization/match against the books. The "
                                            "module's own header refuses to offer bulk approval "
                                            "because financial records are 'exactly the action a "
                                            "practitioner cannot un-see'"),
    "generate_payment_link": _w("C", "creates a Stripe Price + PaymentLink — external money object"),
    "create_product":       _w("C", "creates the product AND its Stripe counterpart"),
    "update_product":       _w("C", "edits the product and its Stripe counterpart"),
    "enqueue_job":          _w("C", "queues heavy server-side work such as rebuild_site. Spends real "
                                    "money and can replace a live site — the failure mode behind the "
                                    "canvas-overwrite incident"),
    "complete_strategy_track": _w("C", "composite finaliser: creates a products module and entries, "
                                       "seeds an intake form, GENERATES THE SITE, and flips the "
                                       "business to launched. Site generation alone earns the C"),
    "queue_build_request":  _w("C", "the builder bridge — files a GitHub issue for the owner, a "
                                    "support ticket for everyone else. Leaves the system"),
    "schedule_action":      _w("C", "meta-verb: schedules ANY toolkit action for later. Its own "
                                    "class is whatever it schedules, so it inherits the worst — "
                                    "otherwise it is a hole straight through this table. The "
                                    "scheduled verb must be checked at execution time too"),
    "adjust_stock":         _w("C", "patches offerings.inventory_qty (delta or set, floor 0) and "
                                    "drops a stock_adjusted movement row on the event spine. The "
                                    "PATCH itself is one edit from right, but the number it "
                                    "rewrites is the one checkout gates on: stock that silently "
                                    "diverges from the shelf oversells real customer orders or "
                                    "blocks real sales — the setup_store shape (reversible "
                                    "switch, unattended downstream money effect). Chief inventing "
                                    "a stock count unprompted is exactly the failure mode; the "
                                    "practitioner saying 'add 10 tees' is the approval"),
    "setup_store":          _w("C", "sets storefront tax rate and flat shipping. The Stripe leg "
                                    "turned out to be a READ (select=stripe_account_id, to warn "
                                    "when checkout would refuse) — it creates no Stripe objects, "
                                    "so that was not what decided this.\n"
                                    "        What decided it: the SETTING is cleanly reversible, "
                                    "but its effect is not. A wrong tax rate is corrected in one "
                                    "edit, while the orders that checked out at that rate in the "
                                    "meantime already charged real customers the wrong amount. "
                                    "Fixing the value does not unwind them. Same shape as "
                                    "create_invoice's auto_send: reversible switch, unattended "
                                    "downstream money effect.\n"
                                    "        Note also that with no arguments this verb is a "
                                    "pure status check. A verb classes at its most dangerous "
                                    "path, not its most common one"),
}


# ─────────────────────────────────────────────────────────────────────
# UNCLASSIFIED — known-pending, NOT unknown (S1.1 steps 3-4).
#
# Listed explicitly so the drift test can tell "we haven't ruled on this
# yet" apart from "somebody added a verb and skipped the decision". Every
# one behaves as denied until it moves into REGISTRY above.
#
# The entries carrying a specific note are the contested calls that need a
# ruling rather than an afternoon; the rest are simply not yet worked.
# ─────────────────────────────────────────────────────────────────────

_PENDING = "not yet classified"

UNCLASSIFIED: Dict[str, str] = {
    # Empty, and the drift test keeps it honest: a verb added to
    # ACTION_HANDLERS without a classification fails there rather than
    # silently inheriting deny-by-default and quietly not working.
    #
    # Adding an entry here is a legitimate move — "I have not decided yet"
    # beats a guess, and default-deny makes a pending verb behave as class
    # C meanwhile. What is NOT legitimate is leaving a verb in neither map.
}


# ─────────────────────────────────────────────────────────────────────
# Accessors. Every one denies on anything it does not know.
# ─────────────────────────────────────────────────────────────────────

def classification(verb: str) -> Optional[Dict[str, str]]:
    """The entry for `verb`, or None if unclassified/unknown. None is the
    honest answer, not an error — callers must treat it as denied."""
    return REGISTRY.get(verb)


def effect(verb: str) -> Optional[str]:
    """'read' | 'ui' | 'write', or None when unknown."""
    entry = REGISTRY.get(verb)
    return entry["effect"] if entry else None


def reversibility(verb: str) -> Optional[str]:
    """'A' | 'B' | 'C' for a classified write; None for reads, UI verbs,
    and anything unclassified."""
    entry = REGISTRY.get(verb)
    if not entry or entry["effect"] != WRITE:
        return None
    return entry.get("reversibility")


def is_read_only(verb: str) -> bool:
    """True only for a verb VERIFIED to change nothing. The gate for any
    read-only agent surface. Unknown → False."""
    return effect(verb) == READ


def is_sensitive(verb: str) -> bool:
    """Confidential enough that it never leaves the app, whatever its
    effect. Unknown verbs answer True — the refusing answer, consistent
    with every other accessor here."""
    entry = REGISTRY.get(verb)
    if not entry:
        return True
    return bool(entry.get("sensitive"))


def may_expose_to_agent(verb: str, allow_writes: bool = False) -> bool:
    """May an outside agent call this verb?

    Default (`allow_writes=False`) is the read-mostly posture: reads only.
    UI verbs are never exposed — an off-app caller has no UI to drive, so
    exposing them would be noise at best. With `allow_writes=True` a
    granted-scope surface may additionally reach class A and B writes;
    class C never qualifies, and neither does anything unclassified.

    A verb marked `sensitive` is refused regardless. Read-ness answers
    "can this break anything"; sensitivity answers "may a third party see
    it". Those are different questions and donor giving records are where
    they diverge."""
    if is_sensitive(verb):
        return False
    kind = effect(verb)
    if kind == READ:
        return True
    if kind == WRITE and allow_writes:
        return reversibility(verb) in ("A", "B")
    return False


def is_bulk(verb: str) -> bool:
    """Does this verb act on a whole set at once? Bulk verbs are never
    autonomy-eligible whatever their class — the reversibility of one row
    says nothing about undoing forty of them."""
    entry = REGISTRY.get(verb)
    return bool(entry and entry.get("bulk"))


def is_autonomy_eligible(verb: str, granted_scope: bool = False) -> bool:
    """May Chief perform this without asking first?

    Class A yes. Class B only with an explicit granted scope. Class C never
    — that is the §2.4 rule and not a knob. Bulk verbs never, at any class.
    Reads are not 'actions' in the autonomy sense and answer False; so does
    everything unclassified.

    This is about acting UNPROMPTED. A practitioner who asked for the thing
    has already supplied the approval — see the module docstring."""
    if is_bulk(verb):
        return False
    rev = reversibility(verb)
    if rev == "A":
        return True
    if rev == "B":
        return bool(granted_scope)
    return False


def classified_verbs() -> Set[str]:
    return set(REGISTRY)


def unclassified_verbs() -> Set[str]:
    return set(UNCLASSIFIED)


def known_verbs() -> Set[str]:
    """Every verb this module accounts for, classified or explicitly pending.
    The drift test compares this against ACTION_HANDLERS."""
    return set(REGISTRY) | set(UNCLASSIFIED)


def coverage() -> Dict[str, int]:
    """Progress, for the S1.1 build-out and for Mission Control if it ever
    wants to show it."""
    by_class = {"read": 0, "ui": 0, "A": 0, "B": 0, "C": 0}
    for entry in REGISTRY.values():
        if entry["effect"] == WRITE:
            by_class[entry.get("reversibility", "?")] += 1
        else:
            by_class[entry["effect"]] += 1
    return {
        "classified": len(REGISTRY),
        "unclassified": len(UNCLASSIFIED),
        "total": len(REGISTRY) + len(UNCLASSIFIED),
        **by_class,
    }
