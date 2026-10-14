"""The Subsplash importer (D3 of the Subsplash exit plan). Synthetic rows
only; Love City's real exports never enter the repo."""
import subsplash_import as si

NOW = "2026-10-14T17:00:00+00:00"
BIZ = "biz-lc"


def person(first, last, **kw):
    row = {k: "" for k in ("first_name", "last_name", "email", "phone", "date_of_birth", "gender",
                           "membership_status", "street", "street_2", "city", "state",
                           "postal_code", "household_id", "household_role", "person_id")}
    row.update(first_name=first, last_name=last, person_id=kw.pop("pid", f"p-{first}-{last}"), **kw)
    return row


def gift(gid, first, last, amount, **kw):
    row = {"Transaction date": "2026-03-01", "Status": "paid", "First name": first,
           "Last name": last, "Email": "", "Gross amount": f"${amount:.2f}", "Fee": "$0.00",
           "Donor covered fee": "$0.00", "Fund": "Tithes", "Payment method": "Cash",
           "Check number": "", "Memo": "", "Gift ID": gid}
    row.update(kw)
    return row


# ─── people: one person, once ─────────────────────────────────────────

def test_a_name_repeated_by_form_fills_is_one_person():
    rows = [person("Maunce", "Wilson", pid=f"p{i}") for i in range(20)]
    plan = si.plan_people(rows, now_iso=NOW)
    assert plan["counts"]["people"] == 1 and plan["counts"]["duplicate_rows_dropped"] == 19
    (row,) = plan["inserts"]
    assert len(row["metadata"]["imported"]["Subsplash person IDs"]) == 20
    assert row["metadata"]["imported"]["Merged Subsplash records"] == 20


def test_same_name_new_email_is_one_person_but_a_different_birthday_is_two():
    rows = [person("Jo", "Lee", email="jo@old.example"),
            person("Jo", "Lee", email="jo@new.example", phone="231-555-0100"),
            person("Sam", "Ray", date_of_birth="1970-01-01"),
            person("Sam", "Ray", date_of_birth="2005-06-01")]
    plan = si.plan_people(rows, now_iso=NOW)
    names = sorted(r["name"] for r in plan["inserts"])
    assert names == ["Jo Lee", "Sam Ray", "Sam Ray"]
    jo = next(r for r in plan["inserts"] if r["name"] == "Jo Lee")
    assert jo["phone"] == "+12315550100"
    assert jo["email"] in ("jo@old.example", "jo@new.example")
    assert jo["metadata"]["imported"]["Other emails"]


def test_family_sharing_an_email_stays_two_people_and_one_holds_it():
    rows = [person("Kid", "Smith", email="mom@example.com", household_role="child",
                   date_of_birth="2014-05-05"),
            person("Mom", "Smith", email="mom@example.com", household_role="parent")]
    plan = si.plan_people(rows, now_iso=NOW)
    by = {r["name"]: r for r in plan["inserts"]}
    assert set(by) == {"Kid Smith", "Mom Smith"}
    # The member page signs in by email; a value on two records signs nobody in.
    assert by["Mom Smith"]["email"] == "mom@example.com"
    assert by["Kid Smith"]["email"] is None
    assert by["Kid Smith"]["metadata"]["imported"]["Email (shared)"] == "mom@example.com"
    assert "child" in by["Kid Smith"]["tags"] and by["Kid Smith"]["birthdate"] == "2014-05-05"
    assert plan["counts"]["shared_email_or_phone_moved"] == 1


def test_a_giver_keeps_the_shared_email_over_a_non_giver():
    rows = [person("Ann", "Doe", email="home@example.com"),
            person("Bob", "Doe", email="home@example.com")]
    plan = si.plan_people(rows, givers=["home@example.com", "bob doe"], now_iso=NOW)
    by = {r["name"]: r for r in plan["inserts"]}
    assert by["Bob Doe"]["email"] == "home@example.com" and by["Ann Doe"]["email"] is None


def test_status_member_active_visitor_lead_answered_and_blank_giver_active():
    rows = [person("A", "Member", membership_status="member"),
            person("B", "Visitor", membership_status="visitor"),
            person("C", "Blank"), person("D", "Giver", email="d@example.com")]
    plan = si.plan_people(rows, givers=["d@example.com"], now_iso=NOW)
    by = {r["name"]: r for r in plan["inserts"]}
    assert by["A Member"]["status"] == "active"
    assert by["D Giver"]["status"] == "active"
    for n in ("B Visitor", "C Blank"):
        # Imported, not waiting: never in "nobody has replied".
        assert by[n]["status"] == "lead" and by[n]["first_response_at"] == NOW == by[n]["created_at"]
    assert "first_response_at" not in by["A Member"]
    assert all(r["source"] == "subsplash_import" and "From Subsplash" in r["tags"]
               for r in plan["inserts"])


def test_people_already_in_the_workspace_are_not_added_again():
    rows = [person("Eve", "Adams", email="eve@example.com", pid="s-1"),
            person("Ike", "Bell", phone="(231) 555-0111", pid="s-2"),
            person("Una", "Cole", pid="s-3"),
            person("Val", "Dunn", pid="s-4")]
    existing = [{"id": "c1", "name": "Someone", "email": "EVE@example.com", "metadata": {}},
                {"id": "c2", "name": "Ike B", "phone": "+12315550111", "metadata": {}},
                {"id": "c3", "name": "Una Cole", "metadata": {}},
                {"id": "c4", "name": "x", "metadata": {"imported": {"Subsplash person IDs": ["s-4"]}}}]
    plan = si.plan_people(rows, existing=existing, now_iso=NOW)
    assert plan["inserts"] == [] and plan["counts"]["already_in_workspace"] == 4
    assert sorted(cid for _, cid in plan["matched"]) == ["c1", "c2", "c3", "c4"]


def test_birthdates_are_only_real_dates():
    assert si._birthdate("1985-02-03") == "1985-02-03"
    for bad in ("", "1899-12-31", "3000-01-01", "02/03/1985", "nonsense"):
        assert si._birthdate(bad) is None


# ─── gifts ────────────────────────────────────────────────────────────

def _plan(rows, contacts=None, existing=()):
    contacts = contacts or {}
    return si.plan_gifts(rows, contact_for=lambda e, f, l: contacts.get(e or f"{f} {l}".lower()),
                         business_id=BIZ, existing_numbers=existing)


def test_methods_map_to_the_books_and_the_manual_ledger():
    rows = [gift("g1", "A", "B", 50, **{"Payment method": "Cash"}),
            gift("g2", "A", "B", 60, **{"Payment method": "Check", "Check number": "1042"}),
            gift("g3", "A", "B", 70, **{"Payment method": "Other (PayPal, Zelle, Cash App)"}),
            gift("g4", "A", "B", 103.39, **{"Payment method": "Visa", "Fee": "$3.39",
                                            "Donor covered fee": "$3.39"}),
            gift("g5", "A", "B", 80, **{"Payment method": "ACH"})]
    plan = _plan(rows, {"a b": "c-ab"})
    by = {g["notes"].split("gift ")[1].split(" ")[0]: g for g in plan["inserts"]}
    assert by["g1"]["payment_method"] == "cash" and by["g1"]["invoice_number"].startswith("GIVE-manual-")
    assert by["g2"]["payment_method"] == "check" and "check #1042" in by["g2"]["notes"]
    assert by["g3"]["payment_method"] == "other"
    # Card and bank gifts were deposited by Subsplash: the bank, not Stripe clearing.
    for k in ("g4", "g5"):
        assert by[k]["payment_method"] == "subsplash bank payout"
        assert by[k]["invoice_number"] == f"GIVE-subsplash-{k}"
    assert by["g4"]["total"] == 103.39 and "giver covered $3.39" in by["g4"]["notes"]
    assert all(g["is_gift"] and g["status"] == "paid" and g["contact_id"] == "c-ab"
               and g["paid_at"] == "2026-03-01T12:00:00Z" == g["sent_at"]
               and g["due_date"] == "2026-03-01" for g in plan["inserts"])


def test_tax_statements_never_carry_non_deductible_or_anonymous_gifts():
    rows = [gift("n1", "A", "B", 20, **{"Payment method": "Other (Non tax deductible)"}),
            gift("n2", "A", "B", 500, **{"Payment method": "Donor-advised fund"}),
            gift("n3", "Loose", "cash", 40)]
    plan = _plan(rows, {"a b": "c-ab"})
    assert [g["contact_id"] for g in plan["inserts"]] == [None, None, None]
    assert "kept off giving statements" in plan["inserts"][0]["notes"]
    assert plan["counts"]["no_giver"] == 3 and plan["total"] == 560.0


def test_failed_gifts_are_skipped_and_split_gifts_are_each_kept():
    rows = [gift("s1", "A", "B", 190, **{"Payment method": "MasterCard"}),
            gift("s1", "A", "B", 10, Fund="Offering", **{"Payment method": "MasterCard"}),
            gift("f1", "A", "B", 99, Status="failed")]
    plan = _plan(rows, {"a b": "c-ab"})
    assert [g["invoice_number"] for g in plan["inserts"]] == ["GIVE-subsplash-s1", "GIVE-subsplash-s1-2"]
    assert plan["counts"]["skipped_failed"] == 1 and plan["total"] == 200.0


def test_a_second_run_adds_nothing():
    rows = [gift("r1", "A", "B", 10), gift("r2", "A", "B", 20, **{"Payment method": "Visa"})]
    first = _plan(rows)
    again = _plan(rows, existing=[g["invoice_number"] for g in first["inserts"]])
    assert again["inserts"] == [] and again["counts"]["already_imported"] == 2


def test_tithes_and_offering_are_general_and_building_is_restricted():
    rows = [gift("t1", "A", "B", 10), gift("t2", "A", "B", 10, Fund="Offering"),
            gift("t3", "A", "B", 10, Fund="Building Fund")]
    cats = [g["category"] for g in _plan(rows)["inserts"]]
    assert cats == [None, None, "restricted"]
