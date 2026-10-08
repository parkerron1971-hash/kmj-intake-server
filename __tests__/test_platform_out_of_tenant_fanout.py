"""Solutionist's own business never gets a tenant marketing week while it
runs on Buffer (platform_suite.kept_out).

Kevin, 2026-10-08: Buffer is for Solutionist's own marketing (the Mission
Control desk); Post for Me is for the businesses on the platform (the tenant
suite). While the suite is not active (MC_MARKETING_SUITE off, or
PLATFORM_BUSINESS_ID unset, invalid or unread) the tenant suite's fan-out,
scheduled runs and manual runs leave Solutionist's own business out: the
validated id, else the owner-checked flag lookup (books_business). A failed
lookup keeps out only rows whose own settings say platform_books, that hour.
A tenant that flags its own row is still planned. Suite active: unchanged.

No network: the verdict's reads are test_platform_marketing_suite's fakes
(its autouse `verdicts` fixture), the planner's are the B9 suite's (`w`).
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '__tests__'))

import pytest

import business_marketing_planner as plan
import platform_suite

from test_business_marketing_planner import PRO, PRO_OWNER  # noqa: E402
from test_business_marketing_week import w  # noqa: E402,F401  (B9's fixture: the planner's seams)
from test_platform_marketing_suite import (  # noqa: E402,F401  (B15's fakes; `verdicts` is autouse)
    KEVIN, PID, _platform_in_w, platform_row, switch, verdicts)
import test_business_marketing_api as api  # noqa: E402

run = asyncio.run
TENANT_ID_BY_MISTAKE = api.BIZ             # a tenant's id put in PLATFORM_BUSINESS_ID


def planned(w):
    return {r['business_id'] for r in w.db.runs.values()}


def tick(w):
    w.db.runs.clear()
    w.db.posts.clear()
    return run(plan.marketing_tick())


def _with_platform_business(w, monkeypatch):
    _platform_in_w(w, monkeypatch)
    w.svc.businesses[PID]['comp_tier'] = 'practice'        # a plan with the week: it would be planned if let in


# ── the fan-out ───────────────────────────────────────────────────────

@pytest.mark.parametrize('on, pid', [(False, None), (True, None), (False, PID), (False, TENANT_ID_BY_MISTAKE),
                                     (True, TENANT_ID_BY_MISTAKE)],
                         ids=['id unset', 'switch on, id unset', 'id valid, switch off', 'tenant id, switch off',
                              'tenant id, switch on'])
def test_off_the_suite_solutionists_own_business_is_not_in_the_tenant_fan_out(w, monkeypatch, on, pid):
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=on, pid=pid)
    assert plan.desk_scope() == '*'                                    # MARKETING_DESK '*' names everyone
    assert plan.desk_on_for(PID) is False and plan.desk_on_for(PID, platform_row()) is False
    assert plan.desk_on_for(PRO) is True and plan.desk_on_for(TENANT_ID_BY_MISTAKE) is True   # tenants, as before
    tally = tick(w)
    assert PID not in planned(w), tally                                # the Buffer desk's loop owns its week
    assert PRO in planned(w), tally                                    # every other business as before
    other = str(uuid4())
    monkeypatch.setenv('MARKETING_DESK', f'{PID},{other}')
    assert plan.desk_scope() == frozenset({other}) and plan.desk_on_for(other)
    monkeypatch.setenv('MARKETING_DESK', PID)
    assert plan.desk_scope() is None


def test_with_the_suite_active_the_platform_business_is_planned_as_b15_built(w, monkeypatch, verdicts):
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=True)
    assert plan.desk_on_for(PID) is True and plan.own_desk(PID) is False
    tally = tick(w)
    assert PID in planned(w) and PRO in planned(w), tally
    assert ('flagged', None) not in verdicts.reads                     # the validated id: no flag lookup


def test_the_flag_lookup_is_owner_checked_so_a_tenant_flagging_its_own_row_is_still_planned(w, monkeypatch,
                                                                                         verdicts):
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=False, pid=None)
    w.svc.businesses[PRO]['settings']['platform_books'] = True        # the tenant's own JSON says so
    verdicts.rows[PRO] = {'id': PRO, 'owner_id': PRO_OWNER, 'platform_books': 'true'}
    verdicts.emails[PRO_OWNER] = 'owner@proshop.example'
    assert platform_suite.books_business() == (platform_suite.VALID, {'id': PID, 'owner_id': KEVIN})
    assert plan.desk_on_for(PRO, w.svc.businesses[PRO]) is True and plan.own_desk(PRO) is False
    tally = tick(w)
    assert PRO in planned(w) and PID not in planned(w), tally
    # No platform business at all: the flagger is still only a tenant.
    platform_suite.forget()
    del verdicts.rows[PID]
    assert platform_suite.books_business() == (platform_suite.INVALID, None)
    assert plan.desk_on_for(PRO, w.svc.businesses[PRO]) is True
    w.user = PRO_OWNER
    r = w.client.post(f'/marketing/{PRO}/engine/run')
    assert r.json().get('detail') != platform_suite.OWN_DESK, r.json()


@pytest.mark.parametrize('failure', ['owner unreadable', 'flags unreadable'])
def test_a_failed_lookup_keeps_out_only_rows_flagged_platform_books_that_hour(w, monkeypatch, verdicts, caplog,
                                                                             failure):
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=False, pid=None)
    w.svc.businesses[PRO]['settings']['platform_books'] = True        # a tenant that flagged its own row
    verdicts.rows[PRO] = {'id': PRO, 'owner_id': PRO_OWNER, 'platform_books': 'true'}
    if failure == 'owner unreadable':
        verdicts.fail_auth = True
    else:
        verdicts.fail_rows = True
    assert platform_suite.books_business()[0] == platform_suite.UNKNOWN
    with caplog.at_level('WARNING', logger='platform_suite'):
        tally = tick(w)
    assert PID not in planned(w) and PRO not in planned(w), tally      # fail closed for the flagged rows only
    assert planned(w), tally                                           # every other business still planned
    assert 'left out of the tenant marketing suite this hour' in caplog.text
    unflagged = {**platform_row(id=str(uuid4()), owner_id=str(uuid4())), 'settings': {}}
    assert plan.desk_on_for(unflagged['id'], unflagged) is True
    assert plan.own_desk(PID) is False                                 # unconfirmed is never "Solutionist's"
    # The next hour the lookup reads: Solutionist's own stays out, the flagging tenant is back.
    platform_suite.forget()
    verdicts.fail_auth = verdicts.fail_rows = False
    tally = tick(w)
    assert PRO in planned(w) and PID not in planned(w), tally


def test_a_desk_that_is_off_asks_no_flag_lookup(w, monkeypatch, verdicts):
    switch(monkeypatch, on=False, pid=None)
    for raw in ('', 'off'):
        monkeypatch.setenv('MARKETING_DESK', raw)
        run(platform_suite.ready())
        assert plan.desk_on_for(PID) is False and plan.own_desk(PID) is False
        assert run(plan.marketing_tick()) == {'skipped': 'off'}
    assert verdicts.reads == []


# ── manual runs: refused in plain words, the owner only ───────────────

@pytest.mark.parametrize('on, pid', [(False, None), (True, None), (False, PID)],
                         ids=['id unset', 'switch on, id unset', 'id valid, switch off'])
def test_a_manual_run_of_solutionists_own_business_is_refused_while_the_suite_is_off(w, monkeypatch, on, pid):
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=on, pid=pid)
    w.user = KEVIN
    r = w.client.post(f'/marketing/{PID}/engine/run')
    assert r.status_code == 409 and r.json()['detail'] == platform_suite.OWN_DESK
    assert "Solutionist's own marketing runs on the Mission Control desk" in platform_suite.OWN_DESK
    assert not any(r_['business_id'] == PID for r_ in w.db.runs.values())       # nothing queued
    w.user = PRO_OWNER                                                # anyone else: the owner rule first
    r = w.client.post(f'/marketing/{PID}/engine/run')
    assert r.status_code == 403


def test_chiefs_replan_of_solutionists_own_business_is_refused_while_the_suite_is_off(w, monkeypatch):
    import chief_marketing_actions as cma
    import chief_of_staff as cos
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=False, pid=None)
    asked = []

    async def run_route(business_id, user):
        asked.append(str(business_id))
        raise AssertionError('never queued')
    monkeypatch.setattr(plan, 'run_route', run_route)
    token = cos._TURN_USER_ID.set(KEVIN)
    try:
        out = run(cma.handle_marketing_replan(None, {'id': PID}, {'type': 'marketing_replan'}))
        assert out['ok'] is False and out['failed'] is True and asked == []
        assert out['result'].startswith("Solutionist's own marketing runs on the Mission Control desk, so nothing "
                                        'was queued.')
        assert out['label'] == 'Runs on the Mission Control desk'
        cos._TURN_USER_ID.set(PRO_OWNER)                               # not the owner: never told that
        out = run(cma.handle_marketing_replan(None, {'id': PID}, {'type': 'marketing_replan'}))
        assert out['ok'] is False and 'Mission Control' not in out['result'] and asked == []
        # A tenant is untouched by any of it.
        cos._TURN_USER_ID.set(PRO_OWNER)
        out = run(cma.handle_marketing_replan(None, {'id': PRO}, {'type': 'marketing_replan'}))
        assert asked == [PRO] and 'Mission Control' not in out['result']
    finally:
        cos._TURN_USER_ID.reset(token)


def test_with_the_suite_active_a_manual_run_of_the_platform_business_is_not_refused(w, monkeypatch):
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=True)
    w.user = KEVIN
    r = w.client.post(f'/marketing/{PID}/engine/run')
    assert r.status_code == 202, r.json()
    assert r.json()['queued'] is True


# ── never a blocking read on the event loop ───────────────────────────

def test_the_flag_lookup_never_reads_on_the_event_loop(w, monkeypatch, verdicts, caplog):
    """The pc fixture's rule (test_platform_chief_suite): every verdict read
    runs in a worker thread, and no sync form is asked cold on the loop."""
    import chief_marketing_actions as cma
    import chief_of_staff as cos
    _with_platform_business(w, monkeypatch)
    switch(monkeypatch, on=False, pid=None)
    for name in ('_read_business', '_flagged_rows', '_owner_email'):
        real = getattr(platform_suite, name)

        def guarded(*a, _real=real, _name=name):
            assert not platform_suite._on_loop(), f'{_name} ran on the event loop'
            return _real(*a)
        monkeypatch.setattr(platform_suite, name, guarded)

    def cold():
        platform_suite.forget()
        verdicts.reads.clear()

    def asked():
        assert ('flagged', None) in verdicts.reads, 'this path asked the flag lookup'
        assert 'was asked on the event loop' not in caplog.text, 'a sync form was asked cold on the event loop'

    caplog.set_level('WARNING', logger='platform_suite')
    cold()
    tally = run(plan.marketing_tick())
    assert PID not in planned(w), tally
    asked()
    cold()
    run(plan.manual_tick())
    asked()
    cold()
    run(plan.marketing_design_tick())
    asked()
    cold()
    run(plan.openings_watch_tick())
    asked()
    cold()
    w.user = KEVIN
    assert w.client.post(f'/marketing/{PID}/engine/run').json()['detail'] == platform_suite.OWN_DESK
    asked()
    cold()
    token = cos._TURN_USER_ID.set(KEVIN)
    try:
        out = run(cma.handle_marketing_replan(None, {'id': PID}, {'type': 'marketing_replan'}))
    finally:
        cos._TURN_USER_ID.reset(token)
    assert 'Mission Control desk' in out['result']
    asked()


# ── the docs and the work log ─────────────────────────────────────────

def test_the_docs_and_worklog_say_what_was_built():
    doc = (ROOT / 'docs' / 'MARKETING_DESK.md').read_text(encoding='utf-8')
    section = ' '.join(doc.split("## Solutionist's own desk on the suite (B15)", 1)[1].split())
    assert "Buffer is for Solutionist's own marketing" in section and 'platform_suite.kept_out' in section
    import worklog
    path = 'worklog/2026-10-08-platform-out-of-tenant-fanout.md'
    text = (ROOT / path).read_text(encoding='utf-8')
    entry = worklog.parse_entry(text, 'kmj-intake-server', path)
    assert entry and entry['agent'] == 'Claude Code (Claude Opus 5.5)'
    assert entry['asked'] == 'Buffer is for me and post for me is for platform. is the wiring correct in the backend?'
    assert re.search(r'^migrations: \[\]$', text.split('---')[1], re.M)
