"""church_money_gate.py — the one place that says who may see or work money.

Kevin, 2026-11-01: Love City's treasurer holds an Admin seat, and most of her
week was refused: matching Sunday's deposit, filing and matching the bank,
reconciling, the categories, the bills and the store orders all asked one
question, "is this the business's owner?", so even an Admin seat got a 403.

Kevin, 2026-11-18 ("One sheet per person", step three): giving becomes its
own tick on a person's sheet. Before that could be built, every door that
asks "may this login see or work the church's money?" had to ask it in one
place. Until this file the answer was written about forty times, in ten
slightly different ways. This change moves them here and changes nobody's
answer: each row of RULES reproduces one of the old gates exactly, the same
people, the same status code, the same words.

    THE GATE ....... require_money(business_id, user, need, part): the
                     person passes, or an HTTPException with the row's own
                     status and words. may_money() is the same question
                     answered yes or no. `need` is "see" or "work"; `part`
                     names what is being opened (PARTS). Today the two needs
                     share a row in every part but the books, the bank and
                     the bills, where reading and changing were already
                     different gates
    THE OLD NAMES .. giving_records.require_finance,
                     giving_records.require_ministry_finance and
                     require_money_writer() below keep their signatures and
                     ask here, so the routes that call them didn't change
    THE TICK ....... giving as its own tick on a person's sheet (2026-11-18,
                     church_money_ticks): eight more standings in
                     _Facts.has() and one more name in the rows that take
                     it (RULES_ON). It is read only while CHURCH_MONEY_TICKS
                     is on for the church; off, RULES alone decides, exactly
                     as before, and nothing more is read. The tick's
                     standings come last in every row, so the owner, an
                     Admin and the accountant pass as they always did
    THE CHURCH WALL  "books" and "bank" at "see" are NOT a full answer. They
                     are only the wall a church or nonprofit puts in front
                     of its ledger, reports and bank; every other business
                     is "not asked" (NOT_ASKED), and the door's own ladder
                     (owner, accountant, any seat) decides after it. So
                     require_money passes a shop with by == NOT_ASKED,
                     may_money refuses to answer for those rows at all, and
                     money_standing() says which it was
    THE KEEPER ..... not here, and not moved: the doors behind a church's
                     Giving keeper still call church_keys.wall(..,
                     "giving_money") after this gate, so a church that names
                     a Giving keeper locks its Admins out, the owner too,
                     until a keeper gives them a key
    KEPT OWNER-ONLY  linking or unlinking a bank, which bank accounts count
                     in the books, the church's payout and Stripe accounts,
                     giving's own setup and the housing allowance: part
                     "setup", the owner alone

A read that fails is a refusal (404 for no business row, no seat read as no
seat), never a yes.
"""
from __future__ import annotations

from typing import Any, Dict, NamedTuple, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

# ─── The standings a rule can admit ───────────────────────────────────
OWNER = "owner"              # businesses.owner_id is this person
ADMIN = "admin"              # an active Admin seat (business_users)
ACCOUNTANT = "accountant"    # an active accountant collaborator (business_collaborators)
# The accountant, but only one who holds no seat here: a login with a seat
# is its seat (church check requests resolved it so: a seat, else the
# accountant).
ACCOUNTANT_NO_SEAT = "accountant_no_seat"
SEAT = "seat"                # any active seat, Viewer and up
# LEGACY, a church's check requests and help requests only: an office login
# that isn't an Admin but whose areas, as Who sees what works them out,
# include Giving & money.
# The app's own saves refuse that area for a login (church_areas
# .clean_login_areas), so in practice it is Chief's GUESS from a leader role
# the login's person holds ("Treasurer", "Trustee", "Finance ...": the word
# list in church_areas._AREA_WORDS, or the church's own placement of that
# role). The giving tick replaces this row; until it exists the row stays,
# because a treasurer somewhere may be working by it.
MONEY_AREA = "money_area"

# THE GIVING TICK (church_money_ticks, church_money_holders): what the owner
# ticked on this login's sheet. Read only while the switch is on for the
# church. "Work" is never a Viewer seat's, whatever its row says.
TICK = "tick"                        # holds giving at any level: See and up
TICK_WORK = "tick_work"              # Work or Lead, on a seat that may change rows
TICK_LEAD = "tick_lead"              # Lead, on such a seat
TICK_WHO = "tick_who"                # ... and may see who gave
TICK_WHO_WORK = "tick_who_work"      # ... who gave, and works it
TICK_BANK = "tick_bank"              # ... and the bank and payouts
TICK_BANK_WORK = "tick_bank_work"    # ... the bank and payouts, and works them
TICK_BANK_WHO = "tick_bank_who"      # ... the bank and who gave (a charge names its giver)
TICKS = (TICK, TICK_WORK, TICK_LEAD, TICK_WHO, TICK_WHO_WORK, TICK_BANK, TICK_BANK_WORK, TICK_BANK_WHO)

NEEDS = ("see", "work")
PARTS = ("giving", "books", "bank", "bills", "store", "checks", "help", "rentals", "my_week", "count_reopen",
         "setup", "send")

PASS = ("*",)                # `elsewhere`: the question isn't asked of that kind of business
NOT_ASKED = "not_asked"      # what "passed", when it was that: nobody was checked
PASSED = NOT_ASKED

GIVING_403 = "Giving records require owner, admin, or accountant access."
CHECKS_403 = ("Check requests are kept with the treasurer: the owner, admins, the accountant, or a login that works "
              "Giving & money.")
MONEY_AREA_KEY = "giving_money"
AREAS_503 = "Your areas couldn't be read just now. Try again."


class Rule(NamedTuple):
    who: Tuple[str, ...]                      # the standings that pass, tried in this order
    status: int = 403
    detail: str = "not authorized"
    owner_by: str = "role"                    # "role": business_users_router.role_of says "owner";
    #                                           "row": the business row's owner_id (a missing row is a 404)
    split: Optional[str] = None               # "church" | "nonprofit": `who` is for that kind of business ...
    elsewhere: Optional[Tuple[str, ...]] = None   # ... and this is for every other (PASS: not asked there)
    detail_elsewhere: Optional[str] = None
    missing: str = "business not found"       # the 404 when the business row isn't there
    no_login: Optional[Tuple[int, str]] = None   # the refusal for someone with no seat here who passed nothing


_FINANCE = Rule(who=(OWNER, ADMIN, ACCOUNTANT), detail=GIVING_403)
# THE CHURCH WALL ONLY, not a full answer: outside a church or nonprofit
# nobody is checked (see the module's note). Never read it as "may read the
# books".
_CHURCH_WALL_ONLY = Rule(who=(OWNER, ADMIN, ACCOUNTANT), detail=GIVING_403, split="nonprofit", elsewhere=PASS,
                         missing="Business not found")
_WRITER = Rule(who=(OWNER, ADMIN), owner_by="row", split="church", elsewhere=(OWNER,))
_TOP = Rule(who=(OWNER, ADMIN))
_TREASURER = Rule(who=(OWNER, ADMIN, ACCOUNTANT_NO_SEAT, MONEY_AREA), detail=CHECKS_403,
                  no_login=(404, "business not found"))
_OWNER_ONLY = Rule(who=(OWNER,), owner_by="row")

# (part, need) → the rule. Each row says which old gate it reproduces.
RULES: Dict[Tuple[str, str], Rule] = {
    # Who gave, the gifts, statements, pledges, counts, giving reports. Was
    # giving_records.require_finance (20 call sites): the owner, an active
    # Admin seat or an active accountant, in any kind of business. Also what
    # church_reports._finance and church_roll._may_give asked by hand.
    ("giving", "see"): _FINANCE,
    ("giving", "work"): _FINANCE,
    # Reading the ledger and the reports. Was giving_records
    # .require_ministry_finance (gl_router._access, reports_router
    # ._owner_or_reader): in a church or nonprofit, the giving rule; in any
    # other business this gate isn't asked, and the door's own ladder
    # (owner, accountant, any seat) decides alone. THE CHURCH WALL ONLY.
    ("books", "see"): _CHURCH_WALL_ONLY,
    # Changing the books. Was church_money_gate.require_money_writer as a
    # door calls it with no part named: the owner; in a church an active
    # Admin seat too; no accountant. (standing() and can_write() ask this
    # row. The expense categories' own writes go through the bank's row
    # below, by plaid_router._require_money_writer.)
    ("books", "work"): _WRITER,
    # Reading the bank. Was plaid_router._require_reader's call of
    # require_ministry_finance: the same wall as the books. THE CHURCH
    # WALL ONLY.
    ("bank", "see"): _CHURCH_WALL_ONLY,
    # Changing the bank's records (categorize, match, sync, rules, the
    # expense categories, Sunday's deposit). Was plaid_router
    # ._require_money_writer → require_money_writer.
    ("bank", "work"): _WRITER,
    # The bills list. Was bills_router._reader: the owner, the accountant,
    # then in a church an Admin seat ("requires admin access or above"), in
    # any other business any seat ("requires viewer access or above").
    ("bills", "see"): Rule(who=(OWNER, ACCOUNTANT, ADMIN), owner_by="row", split="church",
                           elsewhere=(OWNER, ACCOUNTANT, SEAT), detail="requires admin access or above",
                           detail_elsewhere="requires viewer access or above"),
    # Every bill write. Was bills_router._writer → require_money_writer.
    ("bills", "work"): _WRITER,
    # The store's orders and refunds. Was store_router's call of
    # require_money_writer (with the store's own words, passed as `detail`).
    ("store", "see"): _WRITER,
    ("store", "work"): _WRITER,
    # Check requests, the treasurer's desk. Was church_checks.treasurer():
    # the owner, an Admin, the accountant when they hold no seat (a login
    # with a seat is its seat, as church_checks._role resolved it), or the
    # LEGACY area row above. Someone with no seat who is not the accountant
    # gets the door's own 404, as church_checks._role gave it.
    ("checks", "see"): _TREASURER,
    ("checks", "work"): _TREASURER,
    # The treasurer's side of help requests: the amounts only, and paying
    # what the care side sent. Was church_help.view_of's last line: the
    # LEGACY area row alone (the owner and Admins are on the care side, which
    # is People & care's question and stays in church_help). The caller has
    # already read the login's areas and passes them in.
    ("help", "see"): Rule(who=(MONEY_AREA,)),
    ("help", "work"): Rule(who=(MONEY_AREA,)),
    # A room rental's fee, deposit and bill. Was church_spaces.FINANCE: the
    # owner and Admin seats; no accountant.
    ("rentals", "see"): _TOP._replace(detail="Rentals carry money: the owner and admins keep them."),
    ("rentals", "work"): _TOP._replace(detail="Only the owner or an admin bills a rental."),
    # The money lines on My week. Was church_my_week.FINANCE_ROLES: the
    # owner and Admin seats; no accountant.
    ("my_week", "see"): _TOP,
    ("my_week", "work"): _TOP,
    # Reopening a closed count. Was giving_services.reopen_count's own line
    # after the giving gate: the owner or an Admin seat, not the accountant.
    ("count_reopen", "work"): _TOP._replace(detail="Only the owner or an admin can reopen a closed count."),
    # Owner-only doors: giving's setup, linking a bank, the Stripe and payout
    # accounts, the housing allowance. Was each door's own
    # `owner_id != user.id` (plaid_router._require_owner, giving_router
    # ._require_owner, stripe_connect_router._require_owner,
    # housing_allowance.require_owner, and can_change on bank statements).
    ("setup", "see"): _OWNER_ONLY,
    ("setup", "work"): _OWNER_ONLY,
    # Sending money to a 1099 person through Moov, from the church's own bank
    # (moov_payouts, 2026-11-27). Seeing the payouts and their statuses: the
    # giving rule's people (the owner, an Admin, the accountant). Sending:
    # the owner or an Admin, nobody else, and no tick adds to it (RULES_ON
    # keeps the same rows). The church's own Moov account and bank are
    # "setup", the owner's alone.
    ("send", "see"): _FINANCE._replace(detail="Payouts are kept with the owner, the admins and the accountant."),
    ("send", "work"): _TOP._replace(detail="Only the owner or an admin sends money."),
}



def _and(rule: Rule, *more: str, drop: Tuple[str, ...] = ()) -> Rule:
    return rule._replace(who=tuple(s for s in rule.who if s not in drop) + more)


# The same rows WITH THE GIVING TICK SWITCHED ON for the church
# (church_money_ticks.open_for). Each is its RULES row with the tick's
# standing added last, so nobody who passed before is asked anything new.
#   giving ......... the gift records, statements, pledges, counts and
#                    giving reports all name the giver, so they take the
#                    "who gave" tick; a login that only Sees giving reads
#                    the books, the bills and what is owed, not who gave
#   books, bills,
#   store, rentals,
#   my week ........ any tick reads; Work or Lead changes
#   bank ........... only with "bank and payouts"
#   checks, help ... the LEGACY area row is gone (it admitted nobody in
#                    production on 2026-11-18): the tick is the treasurer
#   reopen a count . Lead
#   setup .......... the owner alone, as ever
RULES_ON: Dict[Tuple[str, str], Rule] = {
    ("giving", "see"): _and(_FINANCE, TICK_WHO),
    ("giving", "work"): _and(_FINANCE, TICK_WHO_WORK),
    ("books", "see"): _and(_CHURCH_WALL_ONLY, TICK),
    ("books", "work"): _and(_WRITER, TICK_WORK),
    ("bank", "see"): _and(_CHURCH_WALL_ONLY, TICK_BANK),
    ("bank", "work"): _and(_WRITER, TICK_BANK_WORK),
    ("bills", "see"): _and(RULES[("bills", "see")], TICK),
    ("bills", "work"): _and(_WRITER, TICK_WORK),
    ("store", "see"): _and(_WRITER, TICK),
    ("store", "work"): _and(_WRITER, TICK_WORK),
    ("checks", "see"): _and(_TREASURER, TICK, drop=(MONEY_AREA,)),
    ("checks", "work"): _and(_TREASURER, TICK_WORK, drop=(MONEY_AREA,)),
    ("help", "see"): Rule(who=(TICK,)),
    ("help", "work"): Rule(who=(TICK_WORK,)),
    ("rentals", "see"): _and(RULES[("rentals", "see")], TICK),
    ("rentals", "work"): _and(RULES[("rentals", "work")], TICK_WORK),
    ("my_week", "see"): _and(_TOP, TICK),
    ("my_week", "work"): _and(_TOP, TICK_WORK),
    ("count_reopen", "work"): _and(RULES[("count_reopen", "work")], TICK_LEAD),
    ("setup", "see"): _OWNER_ONLY,
    ("setup", "work"): _OWNER_ONLY,
    ("send", "see"): RULES[("send", "see")],
    ("send", "work"): RULES[("send", "work")],
}

# Doors that are not rows of RULES (they stay the owner's while the switch
# is off, each by its own line): what a holder's OWN tick opens there when
# it is on. tick_admits() answers; the door still asks about the owner itself.
TICK_DOORS: Dict[Tuple[str, str], str] = {
    ("payouts", "see"): TICK_BANK,           # the payouts and refunds lists
    ("payouts", "work"): TICK_BANK_WORK,     # a refund
    ("charges", "see"): TICK_BANK_WHO,       # charges and customers name the giver
}

_UNREAD = object()


class Pass(NamedTuple):
    by: str                                  # the standing that passed, or "pass"
    role: Optional[str]                      # the role read or given, if one was
    business: Optional[Dict[str, Any]]       # the business row, if one was read or given


def _business(business_id: Any, missing: str = "business not found") -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(business_id), safe='')}&select=id,name,type,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, missing)
    return rows[0]


def _is_church(business: Dict[str, Any]) -> bool:
    import church_follow_up
    return church_follow_up.is_church(business)


def _is_nonprofit(business: Dict[str, Any]) -> bool:
    import vertical_family
    return bool(vertical_family.is_nonprofit_like((business or {}).get("type")))


class _Facts:
    """What is known about one person on one business, read at most once and
    only when a rule asks."""

    def __init__(self, business_id: Any, user: Any, role: Any, accountant: Optional[bool],
                 business: Optional[Dict[str, Any]], areas: Any = _UNREAD) -> None:
        self.business_id = business_id
        self.uid = str(user.id)
        self._role = role
        self._accountant = accountant
        self._areas = areas
        self.given = business if isinstance(business, dict) and business else None
        self._read: Optional[Dict[str, Any]] = None
        self._tick: Any = _UNREAD

    @property
    def role(self) -> Optional[str]:
        if self._role is _UNREAD:
            from business_users_router import role_of
            self._role = role_of(self.business_id, self.uid)
        return self._role

    @property
    def known_role(self) -> Optional[str]:
        return None if self._role is _UNREAD else self._role

    def row(self, rule: Rule, *keys: str) -> Dict[str, Any]:
        """The business row with these columns: the caller's, if it has
        them; else read once here (a missing row is the rule's 404)."""
        if self._read is not None:
            return self._read
        if self.given is not None and all(k in self.given for k in keys):
            return self.given
        self._read = _business(self.business_id, rule.missing)
        return self._read

    @property
    def business(self) -> Optional[Dict[str, Any]]:
        return self._read if self._read is not None else self.given

    def inside(self, rule: Rule) -> bool:
        row = self.row(rule, "type")
        return _is_church(row) if rule.split == "church" else _is_nonprofit(row)

    def has(self, standing: str, rule: Rule) -> bool:
        if standing == OWNER:
            if rule.owner_by == "row":
                # Never a role someone passed in: the business row says who owns it.
                return str(self.row(rule, "owner_id").get("owner_id")) == self.uid
            return self.role == OWNER
        if standing == ADMIN:
            return self.role == ADMIN
        if standing == ACCOUNTANT:
            if self._accountant is None:
                from business_collaborators_router import is_active_accountant
                self._accountant = bool(is_active_accountant(self.business_id, self.uid))
            return self._accountant
        if standing == ACCOUNTANT_NO_SEAT:
            if self.role == ACCOUNTANT:
                return True                 # the door resolved it: no seat, and the accountant
            if self.role is not None:
                return False                # a seat is a seat
            return self.has(ACCOUNTANT, rule)
        if standing == SEAT:
            from business_users_router import _ROLE_RANK
            return _ROLE_RANK.get(self.role or "", 0) >= _ROLE_RANK["viewer"]
        if standing == MONEY_AREA:
            return self.money_area()
        if standing in TICKS:
            return self.ticked(standing)
        return False

    def ticked(self, standing: str) -> bool:
        """What this login's own giving tick opens (church_money_ticks
        .holder: None with the switch off, with no row, on a seat that is
        gone, or when the read failed)."""
        if self._tick is _UNREAD:
            import church_money_ticks
            self._tick = church_money_ticks.holder(self.business_id, self.uid)
        t = self._tick
        if not t:
            return False
        # An Admin seat works giving and sees who gave by its own standing;
        # the one thing its row adds is the bank and payouts. So for an
        # Admin only `bank` is read from the row, and the row never stores
        # more than that (church_money_ticks.plan).
        admin = t.get("seat_role") == ADMIN
        work = t.get("can_work") is True or admin
        who = t.get("who_gave") is True or admin
        bank = t.get("bank") is True
        return {TICK: True, TICK_WORK: work, TICK_LEAD: work and t.get("level") == "lead", TICK_WHO: who,
                TICK_WHO_WORK: who and work, TICK_BANK: bank, TICK_BANK_WORK: bank and work,
                TICK_BANK_WHO: bank and who}.get(standing, False)

    def money_area(self) -> bool:
        """The LEGACY row (see MONEY_AREA). A login with every area, or none
        read, isn't one. A view that couldn't be read is a 503, never a yes."""
        if self._areas is not _UNREAD:
            return isinstance(self._areas, list) and MONEY_AREA_KEY in self._areas
        if not self.role or self.role == ACCOUNTANT:
            return False                    # no seat, no areas: a refusal, not "couldn't be read"
        import church_areas
        if church_areas.mode() != "on":
            return False
        view = church_areas.my_areas(self.business_id, self.uid, self.role)
        if view is None:
            raise HTTPException(503, AREAS_503)
        areas = view.get("areas")
        return isinstance(areas, list) and MONEY_AREA_KEY in areas


def _ticks_on(business_id: Any) -> bool:
    """Whether the giving tick is switched on for this church. Off (the
    default) is answered from the environment alone: nothing is read."""
    import church_money_ticks
    return church_money_ticks.mode() != "off" and church_money_ticks.open_for(business_id)


def tick_admits(business_id: Any, user: Any, need: str, door: str) -> bool:
    """For a door outside RULES (TICK_DOORS): whether this login's OWN
    giving tick opens it. False with the switch off (nothing is read), for
    anyone with no tick, and for the owner or an Admin as such: the door
    asks about those itself."""
    standing = TICK_DOORS.get((door, need))
    if standing is None:
        raise ValueError(f"church_money_gate has no tick door {door!r} / {need!r}")
    if not _ticks_on(business_id):
        return False
    return _Facts(business_id, user, None, False, None).ticked(standing)


GIVERS_403 = ("Who gave is kept for the owner, an admin, the accountant, or a login the owner ticked "
              "“who gave” for.")
SEES_ONLY_403 = "This login sees Giving & money but doesn't change it."
# A door that reads the bank's own rows, balances or descriptions (2026-11-20)
# asks require_money(.., "see", "bank", detail=BANK_403). With the switch off
# the people it admits in a church are the books' and giving's own (owner,
# Admin, accountant), so the words only ever reach a tick holder.
BANK_403 = ("The bank is kept for the owner, an admin, the accountant, or a login the owner ticked "
            "“bank and payouts” for.")


def sees_givers(business_id: Any, user: Any, business: Optional[Dict[str, Any]] = None) -> bool:
    """Whether a door that this person has ALREADY passed may put a name
    beside a gift, or show any one person's giving.

    With the giving tick switched off for the business: yes, always (each
    door and the Giving keeper decide, exactly as before; nothing is read).
    Switched on: in a church or nonprofit, the giving rule ("giving" at
    "see": the owner, an Admin, the accountant, or the "who gave" tick); in
    any other business, yes. A read that fails is a no."""
    if not _ticks_on(business_id):
        return True
    try:
        by, _rule_, _f, _out = _decide(business_id, user, "see", "books", _UNREAD, None, business)
        if by == NOT_ASKED:
            return True
        return _decide(business_id, user, "see", "giving", _UNREAD, None, business)[0] is not None
    except HTTPException:
        return False


def require_church_wall(business_id: Any, user: Any, need: str = "see", part: str = "books",
                        business: Optional[Dict[str, Any]] = None) -> Pass:
    """The church wall in front of a door that has its OWN seat ladder (the
    ledger, the reports, payroll, contractors, the periods, the bank's
    reads). At "see" it is require_money exactly. At "work" (the door is
    about to change something) a login that got through the wall only by
    its giving tick must hold Work there: the door's ladder would let a
    Manager seat write, and a tick that only Sees must not ride on it. The
    owner, an Admin and the accountant pass as they always did."""
    p = require_money(business_id, user, "see", part, business=business)
    if need == "work" and p.by in TICKS:
        want = TICK_BANK_WORK if part == "bank" else TICK_WORK
        if not _Facts(business_id, user, None, False, None).ticked(want):
            raise HTTPException(403, SEES_ONLY_403)
    return p


# The accountant isn't named: payroll's own seat ladder (payroll_router,
# contractors_router) refuses a login with no seat, and the accountant holds
# none, so naming them would promise a door that doesn't open.
PAY_RECORDS_403 = "Pay and tax records are kept for the owner, an admin, or a login the owner gave giving at Work."


def require_pay_records(business_id: Any, user: Any, business: Optional[Dict[str, Any]] = None) -> Pass:
    """The church wall in front of payroll and contractors, whose pages show
    pay, Social Security and taxpayer numbers' last four (Kevin, 2026-11-19:
    "payroll and contractor reads need Work, never See"). It is
    require_church_wall at "books", except that a login let through only by
    its giving tick must hold Work there to READ as well as to change. The
    owner, an Admin and the accountant pass as they always did; any business
    that is not a church or nonprofit is not asked (by == NOT_ASKED) and the
    door's own seat ladder decides. With the switch off no tick is ever a
    standing, so this is exactly the wall as before."""
    p = require_money(business_id, user, "see", "books", business=business)
    if p.by in TICKS and not _Facts(business_id, user, None, False, None).ticked(TICK_WORK):
        raise HTTPException(403, PAY_RECORDS_403)
    return p


def _rule(need: str, part: str) -> Rule:
    rule = RULES.get((part, need))
    if rule is None:
        raise ValueError(f"church_money_gate has no rule for {part!r} / {need!r}")
    return rule


def _decide(business_id: Any, user: Any, need: str, part: str, role: Any, accountant: Optional[bool],
            business: Optional[Dict[str, Any]], areas: Any = _UNREAD) -> Tuple[Optional[str], Rule, _Facts, bool]:
    """(the standing that passed or None, the rule, the facts, whether the
    business is outside the rule's `split`)."""
    rule = _rule(need, part)
    if _ticks_on(business_id):
        rule = RULES_ON.get((part, need), rule)
    f = _Facts(business_id, user, role, accountant, business, areas)
    if rule.owner_by == "row":
        f.row(rule, "owner_id")                 # no such business is a 404 before anything else
    if rule.split is None:
        for s in rule.who:
            if f.has(s, rule):
                return s, rule, f, False
        return None, rule, f, False
    if rule.elsewhere is PASS:
        if not f.inside(rule):
            return PASSED, rule, f, True
        for s in rule.who:
            if f.has(s, rule):
                return s, rule, f, False
        return None, rule, f, False
    other = rule.elsewhere or ()
    # A standing both kinds of business admit is tried before the kind is
    # read, in the rule's order, as the old gates did.
    for s in rule.who:
        if s in other:
            if f.has(s, rule):
                return s, rule, f, False
        elif f.inside(rule) and f.has(s, rule):
            return s, rule, f, False
    outside = not f.inside(rule)
    if outside:
        for s in other:
            if s not in rule.who and f.has(s, rule):
                return s, rule, f, True
    return None, rule, f, outside


def require_money(business_id: Any, user: Any, need: str, part: str, *, role: Any = _UNREAD,
                  accountant: Optional[bool] = None, business: Optional[Dict[str, Any]] = None,
                  areas: Any = _UNREAD, detail: Optional[str] = None) -> Pass:
    """This person passes the money gate for `part` at `need`, or the row's
    own HTTPException. Who they are to the business is read in _Facts: who
    owns it, the seat they hold, and whether they are its accountant.

    For the church-wall rows ("books" and "bank" at "see") a pass with
    `by == NOT_ASKED` means nobody was checked: the business is not a church
    or nonprofit, and the door's own ladder still has to decide.

    `role`: the caller already resolved this person's role on the business
    (a door that reads it for other reasons), so the owner and Admin
    standings read nothing again. `accountant`: the caller already knows.
    `business`: the caller's own business row, used when it carries the
    columns the rule reads. `areas`: the caller already read this login's
    areas (church_areas.my_areas). `detail`: the door's own words for the
    refusal, where it had them."""
    by, rule, f, outside = _decide(business_id, user, need, part, role, accountant, business, areas)
    if by is None:
        if rule.no_login and f.role is None:
            raise HTTPException(*rule.no_login)
        raise HTTPException(rule.status, detail or (rule.detail_elsewhere if outside else None) or rule.detail)
    return Pass(by, f.known_role, f.business)


def money_standing(business_id: Any, user: Any, need: str, part: str, *, role: Any = _UNREAD,
                   accountant: Optional[bool] = None, business: Optional[Dict[str, Any]] = None,
                   areas: Any = _UNREAD) -> Optional[str]:
    """What let this person through: a standing ("owner", "admin", ...),
    NOT_ASKED when the row is a church wall and this business isn't one
    (nobody was checked), or None for a refusal."""
    return _decide(business_id, user, need, part, role, accountant, business, areas)[0]


def may_money(business_id: Any, user: Any, need: str, part: str, *, role: Any = _UNREAD,
              accountant: Optional[bool] = None, business: Optional[Dict[str, Any]] = None,
              areas: Any = _UNREAD) -> bool:
    """require_money as a yes or no. A refusal is a no. A read that could
    not be made raises as it does in require_money (the 404 for no business,
    the 503 of the areas read), so a caller that wants "any failure is a no"
    says so itself.

    Not for the church-wall rows ("books" and "bank" at "see"): a yes there
    could only mean "not asked", which is not a yes. Asking is a ValueError;
    use require_money (the wall, before the door's own ladder) or
    money_standing()."""
    if _rule(need, part).elsewhere is PASS:
        raise ValueError(f"church_money_gate: {part!r} / {need!r} is the church wall only, not a full answer; "
                         "may_money can't say yes or no for it. Use require_money or money_standing.")
    return _decide(business_id, user, need, part, role, accountant, business, areas)[0] is not None


# ─── The old names ────────────────────────────────────────────────────

def standing(business_id: Any, user: Any, business: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """'owner', 'admin' (a church's active Admin seat), or None: who may
    change the books."""
    row = business if isinstance(business, dict) and "owner_id" in business else None
    return _decide(business_id, user, "work", "books", _UNREAD, None, row)[0]


def can_write(business_id: Any, user: Any, business: Optional[Dict[str, Any]] = None) -> bool:
    """For a screen's can_change: whether require_money_writer would let them
    in. A read that fails is a no."""
    try:
        return standing(business_id, user, business) is not None
    except Exception:
        return False


def require_money_writer(business_id: Any, user: Any, *, detail: str = "not authorized",
                         part: str = "books") -> Dict[str, Any]:
    """The business row when this person may change its money records: the
    owner_id matches, or the business is a church and they hold an active
    Admin seat (business_users_router.role_of). Else 403 with `detail`, the
    message each door already gave."""
    return require_money(business_id, user, "work", part, detail=detail).business  # type: ignore[return-value]


def require_owner(business_id: Any, user: Any, business: Optional[Dict[str, Any]] = None, *,
                  detail: str = "not authorized") -> Dict[str, Any]:
    """An owner-only money door (part "setup"). The door's own business row,
    when it has read one, is the one returned."""
    return require_money(business_id, user, "work", "setup", business=business,
                         detail=detail).business  # type: ignore[return-value]
