"""Ministry readiness regressions. No live services or customer mutations."""
import asyncio
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import pytest
from fastapi import HTTPException
import giving_records as gr
import giving_statements as gs
import giving_router as giving
import private_care
import sb_clients

def test_giving_pages_past_server_cap_and_excludes_sales(monkeypatch):
    rows=[dict(id=f"{i:05}",is_gift=True,total=1,paid_at="2025-12-31T23:59:59.999Z",contact_id="c",contacts={"name":"A"}) for i in range(5201)]
    seen=[]
    def get(path):
        seen.append(path)
        q=parse_qs(urlsplit(path).query)
        cursor=q.get("id",["gt."])[0][3:]
        return [r for r in rows if r["id"]>cursor][:127]
    monkeypatch.setattr(sb_clients,"sb_get_as_service",get)
    statement=gs.statement_for_contact("b","c",2025)
    assert statement["total"]==5201
    assert len(seen)>40
    assert all("paid_at=lt.2026-01-01T00:00:00Z" in p and "is_gift=eq.true" in p for p in seen)

@pytest.mark.parametrize("failure",[None,{"error":"unavailable"}])
def test_failed_gift_read_is_not_an_empty_statement(monkeypatch,failure):
    monkeypatch.setattr(sb_clients,"sb_get_as_service",lambda p:failure)
    with pytest.raises(HTTPException) as e:gs.statement_for_contact("b","c",2025)
    assert e.value.status_code==503

def test_sale_excluded_and_identical_names_stay_separate(monkeypatch):
    import gl_reports_t4 as reports
    rows=[
      dict(id="1",is_gift=True,total=100,contact_id="c1",contacts={"name":"Denise"}),
      dict(id="2",is_gift=True,total=50,contact_id="c2",contacts={"name":"Denise"}),
      dict(id="3",is_gift=False,total=500,contact_id="c1",contacts={"name":"Denise"})]
    monkeypatch.setattr(sb_clients,"sb_get_as_service",lambda p: [] if "id=gt." in p or not p.startswith("/invoices") else rows)
    monkeypatch.setattr(reports.gl_reports,"gl_active",lambda b:False)
    out=reports.donor_report("b","custom","2025-01-01","2025-12-31")
    assert out["total_gifts"]==150
    assert {r["contact_id"] for r in out["donors"]}=={"c1","c2"}

@pytest.mark.parametrize("role",["viewer","member","manager",None])
@pytest.mark.parametrize("gate",["reports","gl","bank","giving"])
def test_ministry_finances_deny_ordinary_seats(monkeypatch,role,gate):
    import reports_router,gl_router,plaid_router
    monkeypatch.setattr(sb_clients,"sb_get_as_service",lambda p:[{"id":"b","type":"ministry","owner_id":"owner"}])
    with patch("business_users_router.role_of",return_value=role),patch("business_collaborators_router.is_active_accountant",return_value=False):
        fn={"reports":reports_router._owner_or_reader,"gl":gl_router._access,"bank":plaid_router._require_reader,"giving":gr.require_finance}[gate]
        with pytest.raises(HTTPException) as e:fn("b",SimpleNamespace(id="staff"))
        assert e.value.status_code==403

@pytest.mark.parametrize("role,accountant",[("owner",False),("admin",False),(None,True)])
def test_finance_access_allowed(role,accountant):
    with patch("business_users_router.role_of",return_value=role),patch("business_collaborators_router.is_active_accountant",return_value=accountant):
        gr.require_finance("b",SimpleNamespace(id="finance"))

@pytest.mark.parametrize("form,data",[
 ({"name":"Prayer Request"},{"request":"Sensitive"}),
 ({"name":"Contact"},{"confidential":"Yes","request":"Sensitive"}),
 ({"settings":{"private_care":True}},{"request":"Sensitive"}),
 ({},{"prayer_request":"Sensitive"})])
def test_private_intake_never_creates_lead_event_or_draft(monkeypatch,form,data):
    import intake_endpoint as intake
    data = {"name": "Test Member", **data}
    writes=[]
    async def get(client,method,path,body=None):
        assert method=="GET", "ordinary intake must never write"
        if path.startswith("/intake_forms"):
            return [{"id":"form","business_id":"b","fields":[],**form}]
        return [{"id":"b","name":"Church","type":"ministry"}]
    monkeypatch.setattr(intake,"supabase_request",get)
    monkeypatch.setattr(intake,"get_supabase_url",lambda:"https://example.test")
    monkeypatch.setattr(intake,"get_supabase_anon",lambda:"test")
    monkeypatch.setattr(intake,"_intake_rate_ok",lambda ip:True)
    monkeypatch.setattr(private_care.sb_clients,"sb_post_as_service",lambda p,b:(writes.append((p,b)) or [{"id":"saved"}]))
    request=SimpleNamespace(headers={},client=SimpleNamespace(host="127.0.0.1"))
    with patch("lead_identity.resolve",side_effect=AssertionError("lead creation")),patch("lead_scoring.score_and_store",side_effect=AssertionError("scoring")),patch.object(intake,"call_claude",side_effect=AssertionError("AI")):
        out=asyncio.run(intake.submit_intake(intake.IntakeSubmission(form_id="form",business_id="b",data=data),request))
    assert out["private"] and not out["queued"] and out["contact_id"] is None
    assert len(writes)==1 and writes[0][0]=="/ministry_care_requests"
    assert writes[0][1]["submission"]==data

def test_private_storage_error_and_nonowner_are_explicit(monkeypatch):
    monkeypatch.setattr(sb_clients,"sb_post_as_service",lambda *a:None)
    with pytest.raises(HTTPException) as e:private_care.save_submission("b","f",{})
    assert e.value.status_code==503
    monkeypatch.setattr(sb_clients,"sb_get_as_service",lambda *a:[{"owner_id":"owner"}])
    with pytest.raises(HTTPException) as e:private_care.require_owner("b",SimpleNamespace(id="admin"))
    assert e.value.status_code==403

@pytest.mark.parametrize("capacity,successes",[(2,2),(1,1)])
def test_concurrent_rsvps_keep_every_success(monkeypatch,capacity,successes):
    import events_rsvp_router as rsvp
    from __tests__.test_events_rsvp import FakeSB,_entry,_body,_request
    fake=FakeSB(entry=_entry(capacity=capacity))
    barrier=threading.Barrier(2);lock=threading.Lock();seen=threading.local()
    original_get=fake.sb_get_as_service
    def get(path):
        if path.startswith("/module_entries"):
            with lock:row=copy.deepcopy(fake.entry)
            if not getattr(seen,"read",False):seen.read=True;barrier.wait(timeout=5)
            return [row]
        return original_get(path)
    original_patch=fake.sb_patch_as_service
    def cas(path,body):
        with lock:return original_patch(path,body)
    monkeypatch.setattr(fake,"sb_get_as_service",get)
    monkeypatch.setattr(fake,"sb_patch_as_service",cas)
    monkeypatch.setattr(rsvp,"sb_clients",fake)
    monkeypatch.setattr(rsvp,"_check_rsvp_rate",lambda ip:True)
    monkeypatch.setattr(rsvp,"_find_or_create_attendee",lambda b,n,e:e)
    def signup(n):
        try:return asyncio.run(rsvp.public_event_rsvp("first-light",_body(name=n,email=n+"@example.test",role=None),_request()))["ok"]
        except HTTPException as e:assert e.status_code==409;return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(signup,["A","B"]))
    assert sum(results)==successes
    assert len(fake.entry["data"]["signups"])==successes
    assert len({s["contact_id"] for s in fake.entry["data"]["signups"]})==successes

def test_manual_gift_validation_and_contact_scope(monkeypatch):
    body={"amount_cents":1000,"received_on":"2025-12-31","method":"check","fund":"Missions"}
    assert giving._manual_gift_fields("b",body)["gift_fund"]=="Missions"
    for amount in [0,-1,"NaN",1.5]:
        with pytest.raises(HTTPException):giving._manual_gift_fields("b",{**body,"amount_cents":amount})
    monkeypatch.setattr(sb_clients,"sb_get_as_service",lambda p:[])
    with pytest.raises(HTTPException) as e:giving._manual_gift_fields("b",{**body,"contact_id":"00000000-0000-4000-8000-000000000001"})
    assert e.value.status_code==400

def test_manual_gift_retry_does_not_duplicate(monkeypatch):
    writes=[];saved=[]
    monkeypatch.setattr(gr,"require_finance",lambda *a:None)
    monkeypatch.setattr(sb_clients,"sb_get_as_service",lambda p:[{"type":"ministry"}] if p.startswith("/businesses") else saved)
    def post(p,b):writes.append(b);saved.append({"id":"gift"});return saved
    monkeypatch.setattr(sb_clients,"sb_post_as_service",post)
    body={"request_id":"00000000-0000-4000-8000-000000000001","amount_cents":1000,"received_on":"2025-12-31","method":"cash"}
    user=SimpleNamespace(id="owner")
    giving.create_manual_gift("b",body,user);assert giving.create_manual_gift("b",body,user)["already"]
    assert len(writes)==1 and writes[0]["is_gift"]

def test_both_chief_statement_actions_require_actor():
    import chief_giving_actions as chief
    with patch.object(chief,"_authorize",side_effect=HTTPException(403,"denied")):
        for handler in [chief.handle_giving_statement,chief.handle_giving_statements_run]:
            with pytest.raises(HTTPException):asyncio.run(handler(None,{"id":"b"},{}))

@pytest.mark.parametrize("route",["donors","export"])
def test_donor_routes_stay_private_after_vertical_change(monkeypatch,route):
    import reports_router as reports
    monkeypatch.setattr(reports,"_owner_or_reader",lambda *a:{"id":"b","type":"consultant"})
    with patch("business_users_router.role_of",return_value="viewer"),patch("business_collaborators_router.is_active_accountant",return_value=False):
        with pytest.raises(HTTPException) as e:
            if route=="donors":reports.donors("b",user=SimpleNamespace(id="viewer"))
            else:reports.export("b","donors",user=SimpleNamespace(id="viewer"))
        assert e.value.status_code==403

def test_manual_correction_requires_reason_version_and_auditable_actor(monkeypatch):
    gid="00000000-0000-4000-8000-000000000005"
    original={"id":gid,"invoice_number":"GIVE-manual-request","updated_at":"2026-01-01T00:00:00Z","total":20}
    monkeypatch.setattr(gr,"require_finance",lambda *a:None)
    monkeypatch.setattr(sb_clients,"sb_get_as_service",lambda p:[original])
    writes=[]
    monkeypatch.setattr(sb_clients,"sb_patch_as_service",lambda p,b:(writes.append((p,b)) or [{"id":gid}]))
    body={"amount_cents":1500,"received_on":"2025-12-31","method":"check","reason":"Correct amount","updated_at":original["updated_at"],"refund_amount_cents":500}
    assert giving.correct_manual_gift("b",gid,body,SimpleNamespace(id="finance-user"))["ok"]
    assert "updated_at=eq." in writes[0][0]
    assert "finance-user" in writes[0][1]["notes"]
    assert writes[0][1]["refund_amount_cents"]==500
    for overrides in [{"updated_at":"stale"},{"reason":""},{"refund_amount_cents":1501}]:
        with pytest.raises(HTTPException):giving.correct_manual_gift("b",gid,{**body,**overrides},SimpleNamespace(id="finance-user"))
    assert len(writes)==1


def test_private_ministry_records_follow_owner_archive_and_erasure():
    import account_lifecycle as lifecycle
    for table in ("ministry_care_requests", "ministry_gift_history"):
        assert table in lifecycle.BUSINESS_CHILD_TABLES
        assert lifecycle.BUSINESS_CHILD_TABLES.index(table) < lifecycle.BUSINESS_CHILD_TABLES.index("invoices")
        assert table in lifecycle._IMPORT_SKIP
        assert table not in lifecycle.EXPORT_EXCLUDED
