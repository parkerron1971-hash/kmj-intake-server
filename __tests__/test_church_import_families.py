"""A church's spreadsheet comes in as a church: members, guests, families.

The 2026-11-05 run-through imported 12 people from a church file with
Membership Status and Household columns. All 12 came in as Guests, with
no families and no children, so Kids check-in found nobody. What matters
here, in order:

  1. A church's membership column is its status: Member → Member,
     Visitor → Guest, Elder → Leader, and the church's own word stays on
     the record when the roll's word says less ("Regular Attender").
  2. People who share a Household become one family, the same
     households / household_adults / children rows Kids check-in reads;
     a child by birthdate, or by the file's own word when there is none.
  3. A child the file gives no status ("Child") takes the family's.
  4. Nothing changes for a business: no household fields, no families.
  5. A second import of the same file makes no second family, and a new
     baby joins the family that is already there.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import church_families as cfam  # noqa: E402
import contact_fields as cf  # noqa: E402
import contacts_import_router as cir  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

CHURCH = "church1"
SHOP = "shop1"


class _Owner:
    id = "owner1"
    email = "owner@x.com"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)

    def post(p, b, prefer="rep"):
        if isinstance(b, list):
            # PostgREST refuses a bulk insert whose rows don't share their
            # keys (PGRST102, "All object keys must match"), and
            # sb_post_as_service turns that into None. A fake that accepts
            # them hid exactly that bug in the 11-05 church import.
            if len({frozenset(x) for x in b}) > 1:
                return None
            return [fb.post(p, x, prefer)[0] for x in b]
        return fb.post(p, b, prefer)

    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": CHURCH, "owner_id": "owner1", "name": "Grace Chapel", "type": "church"})
    fb.rows("businesses").append({"id": SHOP, "owner_id": "owner1", "name": "Northside Cuts", "type": "barber"})
    return fb


# The run-through's own file (kmj-intake-server/.playwright-mcp/rt/people.csv).
HEADERS = ["First Name", "Last Name", "Email", "Mobile Phone", "Address", "City", "State", "Zip",
           "Birthdate", "Gender", "Membership Status", "Household"]
ROWS = [
    ["Marcus", "Hale", "marcus@x.com", "(555) 010-0101", "14 Oak St", "Springfield", "OH", "45501", "1979-03-14", "Male", "Member", "Hale"],
    ["Denise", "Hale", "denise@x.com", "(555) 010-0102", "14 Oak St", "Springfield", "OH", "45501", "1981-07-22", "Female", "Member", "Hale"],
    ["Jordan", "Hale", "", "", "14 Oak St", "Springfield", "OH", "45501", "2016-05-02", "Male", "Child", "Hale"],
    ["Priya", "Nair", "priya@x.com", "(555) 010-0104", "88 Elm Ave", "Springfield", "OH", "45503", "1990-11-30", "Female", "Member", "Nair"],
    ["Lena", "Brooks", "lena@x.com", "(555) 010-0107", "5 Cedar Ct", "Springfield", "OH", "45505", "1995-09-05", "Female", "Visitor", "Brooks"],
    ["Tom", "Brooks", "tom@x.com", "(555) 010-0108", "5 Cedar Ct", "Springfield", "OH", "45505", "1993-02-26", "Male", "Regular Attender", "Brooks"],
    ["Maya", "Brooks", "", "", "5 Cedar Ct", "Springfield", "OH", "45505", "2019-08-12", "Female", "Child", "Brooks"],
    ["Ruth", "Alvarez", "ruth@x.com", "(555) 010-0111", "310 Maple Dr", "Springfield", "OH", "45507", "1952-06-19", "Female", "Elder", "Alvarez"],
]


def _fields(biz_church: bool, headers=HEADERS, rows=ROWS):
    return [c["field"] for c in cf.guess_columns(headers, rows, church=biz_church)]


def _body(biz_church: bool, dry_run: bool, headers=HEADERS, rows=ROWS):
    return cir.ImportBody(table=cir.ImportTable(headers=headers, rows=rows, fields=_fields(biz_church, headers, rows)),
                          dry_run=dry_run)


def _by_name(fb, name):
    return next(c for c in fb.rows("contacts") if c["name"] == name)


# ─── 1. Reading the columns ──────────────────────────────────────────

def test_a_church_reads_membership_as_status_and_household_as_family():
    got = dict(zip(HEADERS, _fields(True)))
    assert got["Membership Status"] == "status"
    assert got["Household"] == "household"
    assert got["Birthdate"] == "birthday"


def test_a_business_reads_the_same_columns_as_details():
    got = dict(zip(HEADERS, _fields(False)))
    assert got["Membership Status"] == "detail"
    assert got["Household"] == "detail"
    assert all(f["id"] not in cf.CHURCH_FIELDS for f in cf.fields_for(False))
    assert {f["id"] for f in cf.fields_for(True)} == set(cf.FIELD_IDS)


def test_planning_center_membership_beats_its_plain_status_column():
    headers = ["Name", "Membership", "Status", "Household Name", "Child"]
    rows = [["Ana Diaz", "Regular Attender", "active", "Diaz Household", "false"]]
    got = dict(zip(headers, [c["field"] for c in cf.guess_columns(headers, rows, church=True)]))
    assert got == {"Name": "name", "Membership": "status", "Status": "detail",
                   "Household Name": "household", "Child": "household_role"}
    # A gym's "Membership" is the plan someone is on, not a status.
    gym = dict(zip(headers, [c["field"] for c in cf.guess_columns(headers, rows)]))
    assert gym["Membership"] == "detail" and gym["Status"] == "status"


@pytest.mark.parametrize("word,status,kept", [
    ("Member", "active", False), ("Visitor", "lead", False), ("Guest", "lead", False),
    ("Regular Attender", "lead", True), ("Elder", "vip", True), ("Leader", "vip", False),
    ("Former Member", "inactive", True), ("Inactive", "inactive", False), ("Gold", "gold", True),
])
def test_church_status_words(word, status, kept):
    row = cf.rows_from_table(["Name", "Membership Status"], [["Ana Diaz", word]], ["name", "status"])[0]
    assert row["status"] == status
    assert ("Membership Status" in row["details"]) is kept


@pytest.mark.parametrize("header,value,role", [
    ("Household Position", "Head of Household", "adult"), ("Household Position", "Spouse", "adult"),
    ("Household Position", "Child", "child"), ("Family Role", "Adult Child", "adult"),
    ("Child", "TRUE", "child"), ("Child", "no", "adult"), ("Age Group", "Preschool", "child"),
    ("Household Role", "Child of head", "child"), ("Household Role", "Cousin", ""),
])
def test_household_role_words(header, value, role):
    assert cf.household_role_of(header, value) == role


def test_child_in_the_membership_column_is_a_place_in_the_family_not_a_status():
    row = cf.rows_from_table(["Name", "Membership Status"], [["Jordan Hale", "Child"]], ["name", "status"])[0]
    assert row["status"] == "" and row["household_role"] == "child"
    assert "Membership Status" not in row["details"]


@pytest.mark.parametrize("raw,iso", [
    ("1979-03-14", "1979-03-14"), ("3/14/1979", "1979-03-14"), ("14/3/1979", "1979-03-14"),
    ("1979-03-14T00:00:00", "1979-03-14"), ("March 14, 1979", "1979-03-14"), ("14 Mar 1979", "1979-03-14"),
    ("3/14/1979 12:00:00 AM", "1979-03-14"),
    ("04/02", ""), ("--03-14", ""), ("3/14/79", ""), ("2099-01-01", ""), ("1899-05-05", ""), ("soon", ""),
])
def test_birthdates_as_a_full_date_or_nothing(raw, iso):
    assert cf.iso_birthdate(raw, today=date(2026, 11, 6)) == iso


def test_family_names_from_the_file():
    people = [{"name": "Marcus Hale", "metadata": {"last_name": "Hale"}}]
    assert cfam.family_name_from_file("Hale", people) == "The Hale family"
    assert cfam.family_name_from_file("hale", people) == "The Hale family"
    assert cfam.family_name_from_file("The Hale Family", people) == "The Hale Family"
    assert cfam.family_name_from_file("Marcus & Denise Hale", people) == "Marcus & Denise Hale"
    assert cfam.family_name_from_file("HH-1023", people) == "The Hale family"
    assert cfam.family_name_from_file("4471", people) == "The Hale family"


# ─── 2–3. The import ─────────────────────────────────────────────────

def test_the_preview_names_the_families_and_writes_nothing(fake):
    out = cir.import_contacts(CHURCH, _body(True, True), _Owner())
    assert out["summary"]["families"] == 2 and out["summary"]["family_children"] == 2
    assert [f["name"] for f in out["families"]] == ["The Brooks family", "The Hale family"]
    hale = next(f for f in out["families"] if f["name"] == "The Hale family")
    assert hale == {"name": "The Hale family", "adults": 2, "children": 1, "joins": False}
    col = next(c for c in out["columns"] if c["header"] == "Household")
    assert col["lands"] == "Makes 2 families, with 2 children for Kids check-in"
    jordan = next(r for r in out["results"] if r["name"] == "Jordan Hale")
    assert jordan["family"] == "The Hale family" and jordan["family_as"] == "child"
    for t in ("contacts", "households", "household_adults", "children"):
        assert fake.rows(t) == []


def test_the_import_makes_members_guests_leaders_and_families(fake):
    out = cir.import_contacts(CHURCH, _body(True, False), _Owner())
    assert out["summary"]["created"] == 8 and out["summary"]["families"] == 2
    assert _by_name(fake, "Marcus Hale")["status"] == "active"
    assert _by_name(fake, "Lena Brooks")["status"] == "lead"
    tom = _by_name(fake, "Tom Brooks")
    assert tom["status"] == "lead" and tom["metadata"]["imported"]["Membership Status"] == "Regular Attender"
    assert _by_name(fake, "Ruth Alvarez")["status"] == "vip"
    # A child takes the family's status: a member family's child is a member.
    assert _by_name(fake, "Jordan Hale")["status"] == "active"
    assert _by_name(fake, "Maya Brooks")["status"] == "lead"
    # The birthdate lands where Kids check-in and the roll read it.
    assert _by_name(fake, "Jordan Hale")["birthdate"] == "2016-05-02"
    # Imported guests are not waiting on a reply.
    assert _by_name(fake, "Lena Brooks")["first_response_at"]
    assert not _by_name(fake, "Jordan Hale").get("first_response_at")

    homes = {h["name"]: h["id"] for h in fake.rows("households")}
    assert set(homes) == {"The Hale family", "The Brooks family"}
    adults = {(a["household_id"], a["contact_id"]) for a in fake.rows("household_adults")}
    assert (homes["The Hale family"], _by_name(fake, "Marcus Hale")["id"]) in adults
    assert (homes["The Hale family"], _by_name(fake, "Denise Hale")["id"]) in adults
    assert all(a["relationship"] == "parent" for a in fake.rows("household_adults"))
    kids = {k["first_name"]: k for k in fake.rows("children")}
    assert set(kids) == {"Jordan", "Maya"}
    assert kids["Jordan"]["household_id"] == homes["The Hale family"]
    assert kids["Jordan"]["contact_id"] == _by_name(fake, "Jordan Hale")["id"]
    assert kids["Jordan"]["last_name"] == "Hale" and kids["Jordan"]["birthdate"] == "2016-05-02"
    # A household of one (Priya, Ruth) stays a person.
    assert len(fake.rows("households")) == 2
    audit = fake.rows("audit_log")
    assert not audit or "2 families made" in audit[-1].get("summary", "")


def test_members_guests_and_people_with_no_birthdate_save_in_one_batch(fake):
    """One chunk holds rows with and without birthdate, first_response_at
    and role. PostgREST takes that only when every row carries every key."""
    headers = ["Name", "Email", "Membership Status", "Birthdate", "Job Title"]
    rows = [["Ana Diaz", "ana@x.com", "Member", "1980-01-01", "Teacher"],
            ["Bo Reed", "bo@x.com", "Visitor", "", ""]]
    out = cir.import_contacts(CHURCH, _body(True, False, headers, rows), _Owner())
    assert out["summary"]["created"] == 2 and out["summary"]["failed"] == 0
    ana, bo = _by_name(fake, "Ana Diaz"), _by_name(fake, "Bo Reed")
    assert ana["birthdate"] == "1980-01-01" and ana["first_response_at"] is None and ana["role"] == "Teacher"
    assert bo["birthdate"] is None and bo["first_response_at"] and bo["role"] is None


def test_without_a_birthdate_the_files_word_decides(fake):
    headers = ["Name", "Household", "Household Position"]
    rows = [["Sam Okafor", "Okafor", "Head"], ["Grace Okafor", "Okafor", "Spouse"], ["Eli Okafor", "Okafor", "Son"]]
    cir.import_contacts(CHURCH, _body(True, False, headers, rows), _Owner())
    assert [k["first_name"] for k in fake.rows("children")] == ["Eli"]
    assert len(fake.rows("household_adults")) == 2


def test_a_birthdate_beats_the_files_word(fake):
    # A grown son still at home is an adult; Kids check-in never sees him.
    headers = ["Name", "Household", "Household Position", "Birthdate"]
    rows = [["Sam Okafor", "Okafor", "Head", "1965-01-09"], ["Eli Okafor", "Okafor", "Son", "2001-04-04"]]
    cir.import_contacts(CHURCH, _body(True, False, headers, rows), _Owner())
    assert fake.rows("children") == [] and len(fake.rows("household_adults")) == 2
    assert all(a["relationship"] == "other" for a in fake.rows("household_adults"))


def test_a_household_of_only_children_is_not_made(fake):
    headers = ["Name", "Household", "Birthdate"]
    rows = [["Ava Lin", "Lin", "2015-01-01"], ["Max Lin", "Lin", "2017-01-01"]]
    out = cir.import_contacts(CHURCH, _body(True, True, headers, rows), _Owner())
    assert out["families"] == []
    assert out["families_not_made"] == [{"name": "The Lin family", "why": "nobody in it is an adult"}]


# ─── 4. A business ───────────────────────────────────────────────────

def test_a_business_gets_no_families_even_if_the_browser_sends_them(fake):
    fields = _fields(True)                      # a church's mapping, sent to a barber
    body = cir.ImportBody(table=cir.ImportTable(headers=HEADERS, rows=ROWS, fields=fields), dry_run=False)
    out = cir.import_contacts(SHOP, body, _Owner())
    assert out["summary"]["created"] == 8 and "families" not in out
    assert fake.rows("households") == [] and fake.rows("children") == []
    marcus = _by_name(fake, "Marcus Hale")
    assert not marcus.get("birthdate") and not marcus.get("first_response_at")
    assert marcus["metadata"]["imported"]["Household"] == "Hale"


def test_the_column_guess_tells_the_dialog_it_is_a_church(fake):
    out = cir.guess_columns(CHURCH, cir.ColumnsBody(headers=HEADERS, sample_rows=ROWS), _Owner())
    assert out["church"] is True and {"household", "household_role"} <= {f["id"] for f in out["fields"]}
    shop = cir.guess_columns(SHOP, cir.ColumnsBody(headers=HEADERS, sample_rows=ROWS), _Owner())
    assert shop["church"] is False and not {"household", "household_role"} & {f["id"] for f in shop["fields"]}


# ─── 5. Again ────────────────────────────────────────────────────────

def test_a_second_import_makes_no_second_family_and_a_new_baby_joins(fake):
    cir.import_contacts(CHURCH, _body(True, False), _Owner())
    again = ROWS + [["Noah", "Hale", "", "", "14 Oak St", "Springfield", "OH", "45501", "2026-02-01", "Male", "", "Hale"]]
    out = cir.import_contacts(CHURCH, _body(True, False, HEADERS, again), _Owner())
    assert out["summary"]["created"] == 1
    assert len(fake.rows("households")) == 2
    hale = next(h["id"] for h in fake.rows("households") if h["name"] == "The Hale family")
    noah = next(k for k in fake.rows("children") if k["first_name"] == "Noah")
    assert noah["household_id"] == hale
    assert out["families"] == [{"name": "The Hale family", "adults": 0, "children": 1, "joins": True}]
    assert _by_name(fake, "Noah Hale")["status"] == "active"  # the Hales are members, so he is too


def test_families_split_across_two_households_are_left_alone(fake):
    fake.rows("households").extend([{"id": "h1", "business_id": CHURCH, "name": "A"},
                                    {"id": "h2", "business_id": CHURCH, "name": "B"}])
    fake.rows("contacts").extend([
        {"id": "c1", "business_id": CHURCH, "name": "Ann Ray", "email": "ann@x.com", "status": "active"},
        {"id": "c2", "business_id": CHURCH, "name": "Bo Ray", "email": "bo@x.com", "status": "active"}])
    fake.rows("household_adults").extend([{"household_id": "h1", "contact_id": "c1", "business_id": CHURCH},
                                          {"household_id": "h2", "contact_id": "c2", "business_id": CHURCH}])
    headers = ["Name", "Email", "Household"]
    rows = [["Ann Ray", "ann@x.com", "Ray"], ["Bo Ray", "bo@x.com", "Ray"], ["Cy Ray", "cy@x.com", "Ray"]]
    out = cir.import_contacts(CHURCH, _body(True, True, headers, rows), _Owner())
    assert out["families"] == []
    assert out["families_not_made"][0]["why"] == "some of them are already in different families"


def test_a_family_whose_people_did_not_save_is_not_made(fake, monkeypatch):
    import sb_clients
    real = sb_clients.sb_post_as_service

    def flaky(p, b, prefer="rep"):
        if p == "/households":
            return None
        return real(p, b, prefer)

    monkeypatch.setattr(sb_clients, "sb_post_as_service", flaky)
    out = cir.import_contacts(CHURCH, _body(True, False), _Owner())
    assert out["summary"]["created"] == 8 and out["summary"]["families"] == 0
    assert out["summary"]["families_failed"] == 2
    assert fake.rows("household_adults") == [] and fake.rows("children") == []
