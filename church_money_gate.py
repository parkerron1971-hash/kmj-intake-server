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
    THE TICK ....... not here yet. When giving is its own tick it becomes
                     one more standing in _Facts.has() and one more name in
                     the rows that take it; no door changes again
    THE WALL ....... not here, and not moved: the doors behind a church's
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

NEEDS = ("see", "work")
PARTS = ("giving", "books", "bank", "bills", "store", "checks", "help", "rentals", "my_week", "count_reopen",
         "setup")

PASS = ("*",)                # `elsewhere`: the question isn't asked of that kind of business
PASSED = "pass"

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


_FINANCE = Rule(who=(OWNER, ADMIN, ACCOUNTANT), detail=GIVING_403)
_WALL = Rule(who=(OWNER, ADMIN, ACCOUNTANT), detail=GIVING_403, split="nonprofit", elsewhere=PASS,
             missing="Business not found")
_WRITER = Rule(who=(OWNER, ADMIN), owner_by="row", split="church", elsewhere=(OWNER,))
_TOP = Rule(who=(OWNER, ADMIN))
_TREASURER = Rule(who=(OWNER, ADMIN, ACCOUNTANT, MONEY_AREA), detail=CHECKS_403)
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
    # (owner, accountant, any seat) decides alone.
    ("books", "see"): _WALL,
    # Changing the books: the expense categories. Was church_money_gate
    # .require_money_writer: the owner; in a church an active Admin seat
    # too; no accountant.
    ("books", "work"): _WRITER,
    # Reading the bank. Was plaid_router._require_reader's call of
    # require_ministry_finance: the same wall as the books.
    ("bank", "see"): _WALL,
    # Changing the bank's records (categorize, match, sync, rules, Sunday's
    # deposit). Was plaid_router._require_money_writer → require_money_writer.
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
    # the owner, an Admin, the accountant, or the LEGACY area row above. The
    # caller resolves the role itself (a seat, or "accountant" for an
    # accountant with no seat) and passes it in.
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
            if rule.owner_by == "row" and self._role is _UNREAD:
                return str(self.row(rule, "owner_id").get("owner_id")) == self.uid
            return self.role == OWNER
        if standing == ADMIN:
            return self.role == ADMIN
        if standing == ACCOUNTANT:
            if self._accountant is None:
                from business_collaborators_router import is_active_accountant
                self._accountant = bool(is_active_accountant(self.business_id, self.uid))
            return self._accountant
        if standing == SEAT:
            from business_users_router import _ROLE_RANK
            return _ROLE_RANK.get(self.role or "", 0) >= _ROLE_RANK["viewer"]
        if standing == MONEY_AREA:
            return self.money_area()
        return False

    def money_area(self) -> bool:
        """The LEGACY row (see MONEY_AREA). A login with every area, or none
        read, isn't one. A view that couldn't be read is a 503, never a yes."""
        if self._areas is not _UNREAD:
            return isinstance(self._areas, list) and MONEY_AREA_KEY in self._areas
        import church_areas
        if church_areas.mode() != "on":
            return False
        view = church_areas.my_areas(self.business_id, self.uid, self.role)
        if view is None:
            raise HTTPException(503, AREAS_503)
        areas = view.get("areas")
        return isinstance(areas, list) and MONEY_AREA_KEY in areas


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
    f = _Facts(business_id, user, role, accountant, business, areas)
    if rule.owner_by == "row" and role is _UNREAD:
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
    own HTTPException. Who they are to the business is read in _Facts: the
    business row's owner_id, their seat (business_users_router.role_of) and
    whether they are its accountant.

    `role`: the caller already resolved this person's role on the business
    (a door that reads it for other reasons), so the owner and Admin
    standings read nothing again. `accountant`: the caller already knows.
    `business`: the caller's own business row, used when it carries the
    columns the rule reads. `areas`: the caller already read this login's
    areas (church_areas.my_areas). `detail`: the door's own words for the
    refusal, where it had them."""
    by, rule, f, outside = _decide(business_id, user, need, part, role, accountant, business, areas)
    if by is None:
        raise HTTPException(rule.status, detail or (rule.detail_elsewhere if outside else None) or rule.detail)
    return Pass(by, f.known_role, f.business)


def may_money(business_id: Any, user: Any, need: str, part: str, *, role: Any = _UNREAD,
              accountant: Optional[bool] = None, business: Optional[Dict[str, Any]] = None,
              areas: Any = _UNREAD) -> bool:
    """require_money as a yes or no. A refusal is a no. A read that could
    not be made raises as it does in require_money (the 404 for no business,
    the 503 of the areas read), so a caller that wants "any failure is a no"
    says so itself."""
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
