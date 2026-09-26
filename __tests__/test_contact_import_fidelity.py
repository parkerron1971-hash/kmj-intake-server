"""Client-list import keeps everything — and carries every opt-out.

What matters here, in order:
  1. The common exports (Square, Google Contacts, Outlook, Mailchimp)
     are read the way a person would read them: first + last names, the
     mobile over the home phone, company, birthday, address.
  2. Nothing is silently dropped: a column with no home is kept under its
     own heading.
  3. An unsubscribe / cleaned / bounced / "said no" column is honoured —
     on new people AND on people already in contacts — in the records the
     send paths check, scoped to this business.
  4. An import NEVER grants consent: no sms_consents, no sms_bindings, no
     change to email_suppressions, whatever the file says.
  5. Phones in any format dedupe, against the file and against contacts.
  6. The Structure Import's people sheets get the same fidelity through
     the same mapping.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import contact_fields as cf  # noqa: E402
import contacts_import_router as cir  # noqa: E402
import structure_import as si  # noqa: E402
import structure_import_router as sir  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

BIZ = "b1"


class _Owner:
    id = "owner1"
    email = "owner@x.com"


class _Stranger:
    id = "intruder"
    email = "evil@x.com"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)

    def post(p, b, prefer="rep"):
        if isinstance(b, list):
            return [fb.post(p, x, prefer)[0] for x in b]
        return fb.post(p, b, prefer)

    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": BIZ, "owner_id": "owner1", "name": "Northside Cuts", "type": "barber"})
    return fb


# ─── Real export headers ─────────────────────────────────────────────

SQUARE = ["Reference ID", "First Name", "Last Name", "Email Address", "Phone Number", "Nickname",
          "Company Name", "Street Address 1", "Street Address 2", "City", "State", "Postal Code",
          "Birthday", "Memo", "Square Customer ID", "Creation Source", "First Visit", "Last Visit",
          "Transaction Count", "Total Spend", "Email Subscription Status", "Instant Profile"]


def square_row(first, last, email, phone, status="Subscribed", memo=""):
    return ["", first, last, email, phone, "", "Acme Salon", "12 Oak St", "Apt 2", "Akron", "OH",
            "44301", "1990-04-02", memo, "SQ1", "Directory", "2024-01-01", "2026-08-01", "12",
            "$1,240.00", status, "false"]


def _fields(headers, rows):
    return [c["field"] for c in cf.guess_columns(headers, rows)]


def test_square_export_maps_names_company_address_birthday_and_unsubscribes():
    cols = {c["header"]: c["field"] for c in cf.guess_columns(SQUARE, [square_row("Dana", "Whitfield", "d@x.com", "5550102233", memo="hi")])}
    assert cols["First Name"] == "first_name" and cols["Last Name"] == "last_name"
    assert cols["Email Address"] == "email" and cols["Phone Number"] == "phone"
    assert cols["Company Name"] == "company" and cols["Birthday"] == "birthday"
    assert cols["Street Address 1"] == "address" and cols["Street Address 2"] == "address2"
    assert (cols["City"], cols["State"], cols["Postal Code"]) == ("city", "region", "postal_code")
    assert cols["Memo"] == "note"
    assert cols["Email Subscription Status"] == "email_optout"
    # No home of its own → kept, under its own heading. Never dropped.
    assert cols["Last Visit"] == "detail" and cols["Total Spend"] == "detail"


def test_google_contacts_csv():
    headers = ["First Name", "Middle Name", "Last Name", "Nickname", "Organization Name",
               "Organization Title", "Organization Department", "Birthday", "Notes", "Labels",
               "E-mail 1 - Label", "E-mail 1 - Value", "Phone 1 - Label", "Phone 1 - Value",
               "Phone 2 - Label", "Phone 2 - Value", "Address 1 - Formatted", "Address 1 - Street",
               "Address 1 - City", "Address 1 - Region", "Address 1 - Postal Code"]
    row = ["Ana", "M", "Souza", "", "Studio", "Owner", "Ops", "--04-12", "hi", "* myContacts ::: Clients",
           "* Home", "ana@x.com", "Mobile", "+1 330-555-0101", "Home", "330-555-0199",
           "9 Elm, Kent", "9 Elm", "Kent", "OH", "44240"]
    cols = {c["header"]: c["field"] for c in cf.guess_columns(headers, [row])}
    assert cols["Middle Name"] == "detail"          # not the name
    assert cols["Organization Name"] == "company" and cols["Organization Title"] == "title"
    assert cols["Organization Department"] == "detail"
    assert cols["E-mail 1 - Label"] == "skip" and cols["Phone 1 - Label"] == "skip"
    assert cols["E-mail 1 - Value"] == "email" and cols["Phone 1 - Value"] == "phone"
    assert cols["Phone 2 - Value"] == "detail"       # kept, not lost
    assert cols["Labels"] == "tags"
    built = cf.rows_from_table(headers, [row], [cols[h] for h in headers])[0]
    assert built["name"] == "Ana Souza" and built["tags"] == ["Clients"]   # Google's noise label gone
    assert built["address"].startswith("9 Elm") and "Kent" in built["address"]


def test_outlook_csv_prefers_the_mobile_and_is_not_fooled_by_display_name_or_title():
    headers = ["Title", "First Name", "Last Name", "Company", "Job Title", "Business Phone",
               "Home Phone", "Mobile Phone", "Birthday", "E-mail Address", "E-mail Type",
               "E-mail Display Name", "Notes", "Categories", "Priority"]
    row = ["Ms.", "Ann", "Lee", "Co", "Manager", "330-555-0100", "330-555-0102", "330-555-0199",
           "0/0/00", "ann@x.com", "SMTP", "Ann Lee (ann@x.com)", "", "VIP;Friends", "Normal"]
    cols = {c["header"]: c["field"] for c in cf.guess_columns(headers, [row])}
    assert cols["Mobile Phone"] == "phone"
    assert cols["Home Phone"] == "detail" and cols["Business Phone"] == "detail"
    assert cols["E-mail Display Name"] == "detail" and cols["Title"] == "detail"
    assert cols["Job Title"] == "title" and cols["E-mail Type"] == "skip"
    built = cf.rows_from_table(headers, [row], [cols[h] for h in headers])[0]
    assert built["name"] == "Ann Lee" and built["phone"] == "330-555-0199"
    assert built["birthday"] == ""                   # Outlook's 0/0/00 is "no birthday"
    assert built["tags"] == ["VIP", "Friends"] and built["title"] == "Manager"


def test_mailchimp_status_and_unsub_columns_are_unsubscribes():
    headers = ["Email Address", "First Name", "Last Name", "MEMBER_RATING", "OPTIN_TIME",
               "UNSUB_TIME", "UNSUB_REASON", "CLEAN_TIME", "Status"]
    rows = [["a@x.com", "A", "One", "2", "2020-01-01", "2024-01-01 10:00:00", "too many", "", "unsubscribed"],
            ["b@x.com", "B", "Two", "2", "2020-01-01", "", "", "2024-02-02 10:00:00", "cleaned"],
            ["c@x.com", "C", "Three", "2", "2020-01-01", "", "", "", "subscribed"]]
    cols = {c["header"]: c["field"] for c in cf.guess_columns(headers, rows)}
    assert cols["UNSUB_TIME"] == "email_optout" and cols["CLEAN_TIME"] == "email_optout"
    assert cols["Status"] == "email_optout"          # Mailchimp's Status is subscription state
    assert cols["OPTIN_TIME"] == "skip" and cols["UNSUB_REASON"] == "detail"
    built = cf.rows_from_table(headers, rows, [cols[h] for h in headers])
    assert built[0]["email_opt_out"] == "unsubscribed"
    assert built[1]["email_opt_out"].startswith("cleaned")
    assert built[2]["email_opt_out"] == "" and built[2]["sms_opt_out"] == ""


@pytest.mark.parametrize("header,value,out", [
    ("Email Subscription Status", "Unsubscribed", True),
    ("Email Subscription Status", "Subscribed", False),
    ("Email Subscription Status", "unknown", False),
    ("Accepts Email Marketing", "no", True),
    ("Accepts Email Marketing", "yes", False),
    ("SMS Opt In", "FALSE", True),
    ("SMS Opt In", "TRUE", False),
    ("Do Not Email", "TRUE", True),
    ("Do Not Email", "FALSE", False),
    ("Unsubscribed", "3/1/2024", True),
    ("UNSUB_TIME", "2024-01-01 10:00:00", True),
    ("Email Marketing", "not_subscribed", True),
    ("Email Status", "bounced", True),
    ("Status", "cleaned", True),
    ("SMS Status", "STOP", True),
])
def test_opt_out_reading(header, value, out):
    assert bool(cf.opt_out_reason(header, value)) is out


def test_a_yes_never_reads_as_anything():
    # The function can only ever say "do not contact". Every affirmative
    # a file might carry comes back empty.
    for h in ("SMS Opt In", "Accepts SMS Marketing", "Email Opt In", "Newsletter", "Consent"):
        for v in ("yes", "Y", "TRUE", "1", "Subscribed", "opted in", "✓"):
            assert cf.opt_out_reason(h, v) == "", (h, v)


def test_phone_keys_read_every_format_a_phone_exports():
    same = ["+1 (555) 010-2233", "555.010.2233", "(555) 010-2233", "15550102233",
            "tel:+15550102233", "555-010-2233 ext 4", "+1 555 010 2233"]
    assert {cf.phone_key(p) for p in same} == {"+15550102233"}
    assert cf.phone_key("0044 20 7946 0958") == "+442079460958" == cf.phone_key("+44 20 7946 0958")
    # Too short for E.164 — still dedupes against itself, never matches a real number.
    assert cf.phone_key("010-2233") == "" and cf.phone_match_key("010-2233") == "#0102233"


def test_mapping_that_names_no_person_is_refused():
    assert cf.validate_fields(["A", "B"], ["detail", "note"])
    assert cf.validate_fields(["A"], ["email", "note"])       # length mismatch
    assert cf.validate_fields(["A"], ["favourite_colour"])   # not a field
    assert cf.validate_fields(["A", "B"], ["email", "detail"]) == ""


# ─── The endpoint ────────────────────────────────────────────────────

def _table_body(headers, rows, dry_run, **kw):
    return cir.ImportBody(table=cir.ImportTable(headers=headers, rows=rows, fields=_fields(headers, rows)),
                          dry_run=dry_run, **kw)


def test_dry_run_reports_every_column_and_the_opt_outs_and_writes_nothing(fake):
    rows = [square_row("Dana", "Whitfield", "dana@x.com", "(555) 010-2233", status="Unsubscribed"),
            square_row("Marcus", "Lee", "marcus@x.com", "555-010-9911")]
    out = cir.import_contacts(BIZ, _table_body(SQUARE, rows, True), _Owner())
    assert out["dry_run"] is True
    assert out["summary"]["to_create"] == 2 and out["summary"]["email_opt_outs"] == 1
    by = {c["header"]: c for c in out["columns"]}
    assert by["Email Subscription Status"]["lands"] == "1 person will get no marketing email"
    assert by["Last Visit"]["lands"] == "Kept on their record as “Last Visit”"
    assert by["Instant Profile"]["lands"].startswith("Left out")
    assert fake.rows("contacts") == [] and fake.rows("sms_opt_outs") == []


def test_real_run_keeps_everything_on_the_record(fake):
    rows = [square_row("Dana", "Whitfield", "dana@x.com", "(555) 010-2233", memo="likes a skin fade")]
    out = cir.import_contacts(BIZ, _table_body(SQUARE, rows, False), _Owner())
    assert out["summary"]["created"] == 1
    c = fake.rows("contacts")[0]
    assert c["name"] == "Dana Whitfield" and c["phone"] == "+15550102233"
    md = c["metadata"]
    assert md["first_name"] == "Dana" and md["last_name"] == "Whitfield"
    assert md["organization"] == "Acme Salon" and md["birthday"] == "1990-04-02"
    assert md["address"] == "12 Oak St, Apt 2, Akron, OH 44301"
    assert md["import_note"] == "likes a skin fade"
    assert md["imported"]["Last Visit"] == "2026-08-01" and md["imported"]["Total Spend"] == "$1,240.00"
    assert "notes" not in c                          # no such column (PGRST204)
    assert "email_opt_out" not in md                 # "Subscribed" carries nothing


def test_opt_outs_land_where_the_send_paths_look_and_consent_is_never_granted(fake):
    headers = ["First Name", "Last Name", "Email", "Mobile", "Email Subscription Status",
               "SMS Opt In", "Accepts Email Marketing"]
    rows = [["Dana", "W", "dana@x.com", "555-010-2233", "Unsubscribed", "no", "yes"],
            ["Kim", "O", "kim@x.com", "555-010-4444", "Subscribed", "YES", "yes"]]
    body = cir.ImportBody(table=cir.ImportTable(
        headers=headers, rows=rows,
        fields=["first_name", "last_name", "email", "phone", "email_optout", "sms_optout", "email_optout"]),
        dry_run=False)
    out = cir.import_contacts(BIZ, body, _Owner())
    dana, kim = fake.rows("contacts")
    assert dana["metadata"]["email_opt_out"]["reason"] == "unsubscribed"
    assert dana["metadata"]["sms_opt_out"]["reason"] == "did not agree to marketing"
    assert dana["metadata"]["email_opt_out"]["source"] == "import:file"
    assert "email_opt_out" not in kim["metadata"] and "sms_opt_out" not in kim["metadata"]
    # The STOP ledger every text path checks, scoped to THIS business.
    assert fake.rows("sms_opt_outs") == [{"phone": "+15550102233", "business_id": BIZ,
                                          "id": fake.rows("sms_opt_outs")[0]["id"]}]
    # Never consent, never the platform-wide email list.
    assert fake.rows("sms_consents") == [] and fake.rows("sms_bindings") == []
    assert fake.rows("email_suppressions") == []
    # A "yes" is not carried even as a detail — it would read like consent.
    assert "SMS Opt In" not in (kim["metadata"].get("imported") or {})
    assert out["summary"]["email_opt_outs"] == 1 and out["summary"]["sms_opt_outs"] == 1
    assert out["summary"]["sms_numbers_opted_out"] == 1


def test_an_opt_out_reaches_someone_already_here_even_when_told_to_leave_them_alone(fake):
    fake.rows("contacts").append({"id": "c1", "business_id": BIZ, "name": "Dana Whitfield",
                                  "email": "dana@x.com", "phone": "(555) 010-2233", "role": "Regular",
                                  "metadata": {"website_form_messages": [{"message": "hi"}]}})
    body = cir.ImportBody(rows=[cir.ImportRow(name="Dana W.", email="DANA@x.com", phone="",
                                              email_opt_out="unsubscribed", sms_opt_out="texted STOP",
                                              birthday="1990-04-02")],
                          on_duplicate="skip", dry_run=False)
    out = cir.import_contacts(BIZ, body, _Owner())
    assert out["results"][0]["action"] == "matched"
    assert "no marketing email or texts" in out["results"][0]["reason"]
    c = fake.rows("contacts")[0]
    assert c["name"] == "Dana Whitfield" and c["role"] == "Regular"           # left alone
    assert "birthday" not in c["metadata"]                                    # skip = don't fill
    assert c["metadata"]["website_form_messages"] == [{"message": "hi"}]      # merged, not replaced
    assert c["metadata"]["email_opt_out"]["reason"] == "unsubscribed"
    # Their phone on file (not in the import) is opted out of texts.
    assert [r["phone"] for r in fake.rows("sms_opt_outs")] == ["+15550102233"]


def test_fill_fills_blanks_and_never_overwrites(fake):
    fake.rows("contacts").append({"id": "c1", "business_id": BIZ, "name": "Dana", "email": "dana@x.com",
                                  "phone": None, "role": "Regular", "metadata": {"birthday": "1990-01-01"}})
    body = cir.ImportBody(rows=[cir.ImportRow(name="Dana", email="dana@x.com", phone="555-010-2233",
                                              title="Manager", birthday="1991-02-02",
                                              address="12 Oak St", details={"Last Visit": "2026-08-01"})],
                          on_duplicate="fill", dry_run=False)
    cir.import_contacts(BIZ, body, _Owner())
    c = fake.rows("contacts")[0]
    assert c["phone"] == "+15550102233" and c["role"] == "Regular"
    assert c["metadata"]["birthday"] == "1990-01-01"              # hand-entered value kept
    assert c["metadata"]["address"] == "12 Oak St"
    assert c["metadata"]["imported"] == {"Last Visit": "2026-08-01"}


def test_phones_in_different_formats_are_the_same_person(fake):
    fake.rows("contacts").append({"id": "c1", "business_id": BIZ, "name": "Dana", "email": None,
                                  "phone": "(555) 010-2233", "metadata": {}})
    rows = [cir.ImportRow(name="Dana", phone="+1 555-010-2233"),        # already here
            cir.ImportRow(name="Kim", phone="555.010.4444"),
            cir.ImportRow(name="Kim O", phone="+1 (555) 010-4444", sms_opt_out="texted STOP")]
    out = cir.import_contacts(BIZ, cir.ImportBody(rows=rows, dry_run=False), _Owner())
    acts = [r["action"] for r in out["results"]]
    assert acts == ["matched", "created", "skipped"]
    assert "same person as row 2" in out["results"][2]["reason"]
    assert len(fake.rows("contacts")) == 2
    kim = next(c for c in fake.rows("contacts") if c["name"] == "Kim")
    assert kim["phone"] == "+15550104444"
    # The duplicate's STOP follows the person it duplicates.
    assert kim["metadata"]["sms_opt_out"]["reason"] == "texted STOP"
    assert [r["phone"] for r in fake.rows("sms_opt_outs")] == ["+15550104444"]
    # A re-import of the same file creates nobody.
    again = cir.import_contacts(BIZ, cir.ImportBody(rows=rows[:2], dry_run=True), _Owner())
    assert again["summary"]["to_create"] == 0 and again["summary"]["matched"] == 2


def test_a_bad_email_no_longer_throws_the_person_away(fake):
    out = cir.import_contacts(BIZ, cir.ImportBody(
        rows=[cir.ImportRow(name="Tom Reyes", email="tom at gmail", phone="555-010-7777")],
        dry_run=False), _Owner())
    assert out["results"][0]["action"] == "created"
    c = fake.rows("contacts")[0]
    assert c["email"] is None and c["metadata"]["imported"]["Email (as written)"] == "tom at gmail"


def test_import_and_column_guess_are_gated(fake):
    with pytest.raises(HTTPException) as e:
        cir.import_contacts(BIZ, cir.ImportBody(rows=[cir.ImportRow(name="x")]), _Stranger())
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e2:
        cir.guess_columns(BIZ, cir.ColumnsBody(headers=["Name"]), _Stranger())
    assert e2.value.status_code == 403
    out = cir.guess_columns(BIZ, cir.ColumnsBody(headers=SQUARE, sample_rows=[square_row("A", "B", "a@x.com", "")]), _Owner())
    assert {f["id"] for f in out["fields"]} == set(cf.FIELD_IDS)
    assert out["columns"][1]["field"] == "first_name"
    with pytest.raises(HTTPException):
        cir.import_contacts(BIZ, cir.ImportBody(table=cir.ImportTable(
            headers=["A"], rows=[["x"]], fields=["detail"])), _Owner())


# ─── Campaigns honour the imported opt-out ───────────────────────────

def test_campaigns_skip_an_imported_email_opt_out_before_anything_else():
    import campaigns_router as cr

    async def must_not_run(*a, **k):
        raise AssertionError("an opted-out contact reached the send path")

    email_sender = SimpleNamespace(is_suppressed=must_not_run, send_via_resend=must_not_run)
    contact = {"id": "c1", "email": "dana@x.com", "phone": "+15550102233",
               "metadata": {"email_opt_out": {"reason": "unsubscribed"},
                            "sms_opt_out": {"reason": "texted STOP"}}}
    camp = {"id": "k1", "business_id": BIZ}
    for channel in ("email", "sms"):
        res = asyncio.run(cr._send_touch({"id": BIZ, "name": "N"}, camp, 0,
                                         {"channel": channel, "body": "hi"}, contact,
                                         email_sender, SimpleNamespace(alerts_enabled=lambda: True),
                                         must_not_run, must_not_run, lambda p: p))
        assert res == "skipped"
    summary = cr._audience_summary([contact, {"id": "c2", "email": "k@x.com", "phone": "+15550104444"}])
    assert summary["emailable"] == 1 and summary["textable"] == 1


# ─── The Structure Import gets the same fidelity ─────────────────────

def test_structure_import_people_sheet_keeps_last_names_birthdays_and_unsubscribes(fake):
    headers = ["First Name", "Last Name", "Email", "Cell Phone", "Birthday", "Last Visit", "Unsubscribed"]
    rows = [["Dana", "Whitfield", "dana@x.com", "555-010-2233", "04/02", "2026-08-01", "yes"],
            ["Marcus", "Lee", "marcus@x.com", "555-010-9911", "", "2026-07-11", "no"],
            ["Kim", "Ortiz", "kim@x.com", "", "", "", ""],
            ["Lee", "Park", "lee@x.com", "", "", "", ""]]
    sheet = {"name": "Clients.csv", "headers": headers, "sample_rows": rows, "total_rows": 4}
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**sheet)]), _Owner())
    s = proposal["sheets"][0]
    assert s["verdict"] == "existing_surface"
    mapped = {c["header"]: (c["field"] or {}).get("name") for c in s["columns"]}
    assert mapped["First Name"] == "first_name" and mapped["Last Name"] == "last_name"
    assert mapped["Birthday"] == "birthday" and mapped["Last Visit"] == "detail"
    assert mapped["Unsubscribed"] == "email_optout"
    assert proposal["dropped"] == []                  # nothing with anything in it is dropped

    body = sir.RunBody(proposal_id=proposal["proposal_id"],
                       sheets=[sir.RunSheet(sheet=s["sheet"], verdict=s["verdict"], headers=headers,
                                            target=s["target"], columns=s["columns"])],
                       rows={"Clients.csv": rows}, dry_run=False)
    out = sir.run(BIZ, body, _Owner())
    assert out["sheets"][0]["summary"]["created"] == 4
    dana = next(c for c in fake.rows("contacts") if c["email"] == "dana@x.com")
    assert dana["name"] == "Dana Whitfield" and dana["metadata"]["birthday"] == "04/02"
    assert dana["metadata"]["imported"]["Last Visit"] == "2026-08-01"
    assert dana["metadata"]["email_opt_out"]["source"] == "import:structure_import"
    marcus = next(c for c in fake.rows("contacts") if c["email"] == "marcus@x.com")
    assert "email_opt_out" not in marcus["metadata"]
    assert fake.rows("sms_consents") == [] and fake.rows("email_suppressions") == []


def test_structure_import_and_the_dialog_share_one_mapping():
    import inspect
    assert "contact_fields.guess_columns" in inspect.getsource(si._contacts_columns)
    assert "contact_fields.rows_from_table" in inspect.getsource(sir._contacts_rows)
    assert "contact_fields.rows_from_table" in inspect.getsource(cir.import_contacts)


# ─── The frontend's phone-contacts table is read without guessing ────

# solutionist-studio src/core/lib/clientFile.ts PHONE_HEADERS — a vCard or
# the Android contact picker arrives as a table under these headers. If
# either side renames one, this is where it shows.
PHONE_HEADERS = ["Full name", "First name", "Last name", "Email", "Other emails", "Mobile phone",
                 "Other phones", "Street address", "Address line 2", "City", "State",
                 "ZIP or postal code", "Country", "Birthday", "Company", "Job title", "Note",
                 "Nickname", "Website", "Groups"]


def test_phone_contact_headers_map_to_the_intended_fields():
    got = [c["field"] for c in cf.guess_columns(PHONE_HEADERS, [])]
    assert got == ["name", "first_name", "last_name", "email", "detail", "phone", "detail",
                   "address", "address2", "city", "region", "postal_code", "country",
                   "birthday", "company", "title", "note", "detail", "detail", "tags"]


def test_a_column_filled_only_far_down_the_file_is_not_called_empty():
    headers = ["Name", "Email", "Last Visit"]
    sample = [["A", "a@x.com", ""], ["B", "b@x.com", ""]]
    assert cf.guess_columns(headers, sample)[2]["field"] == "skip"
    kept = cf.guess_columns(headers, sample, filled=[2, 2, 1])[2]
    assert kept["field"] == "detail"
    assert cf.guess_columns(headers, sample, filled=[2, 2, 0])[2]["note"] == "Empty in every row."
