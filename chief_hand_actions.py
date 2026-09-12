"""
chief_hand_actions.py — Chief proposes the browser hand; a person
approves it; the job runner runs it.

One verb, use_browser_hand (class C). It never touches a browser. It
validates the ask (browser_hand.make_spec), files a proposal in the
Approval Queue on channel "hand", and tells the practitioner where to
approve it. The run itself starts from _do_approve_one — the same core
the approvals endpoint and the approve_draft verb share — so there is
exactly one path from "approved" to "running", and it is the audited
one.

Why a queue row and not a job straight away: the brief says
proposal-gated, and the queue is where proposals already live. The
practitioner sees the task, the start page, the allowed sites and the
budget in the same room as every other draft, with the same Approve
and Dismiss.

HOST HELPERS through chief_host (call-time), REGISTRATION by named
import, like every split module.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import browser_hand
from chief_host import _sb, _fail, _nav

logger = logging.getLogger("chief_of_staff")


def _errand_user():
    from chief_of_staff import _TURN_USER_ID
    from types import SimpleNamespace
    import chief_errands
    return SimpleNamespace(id=chief_errands.uid(_TURN_USER_ID.get()))


async def _errand_action(client, biz, action, operation):
    import asyncio
    import chief_errands as ce
    from fastapi import HTTPException
    try:
        user=_errand_user()
        current=await asyncio.to_thread(ce.business,biz['id'],user,
                                        'viewer' if operation=='status' else 'manager')
        if operation=='plan':
            result=await ce.plan(current,user.id,action,client)
            if result.get('action'): return result['action']
            from chief_of_staff import _TURN_ERRAND_PLANS
            _TURN_ERRAND_PLANS.set((*_TURN_ERRAND_PLANS.get(),result['errand']['id']))
            return ce.card(result['errand'],planned=True)
        row=await asyncio.to_thread(ce.authorized,action.get('errand_id'),user,
                                    'viewer' if operation=='status' else 'manager')
        if row['business_id']!=biz['id']:
            raise HTTPException(404,'Errand not found.')
        if operation=='approve':
            from chief_of_staff import _TURN_ERRAND_CONFIRMED, _TURN_ERRAND_PLANS
            if row['id'] in _TURN_ERRAND_PLANS.get():
                raise HTTPException(403,'Review this new plan first, then approve it in a separate turn or on its card.')
            if not _TURN_ERRAND_CONFIRMED.get():
                raise HTTPException(403,'Say "approve this errand" now, or use its Approve button.')
            row=await ce.approve(row,user,None,via_chat=True)
        elif operation=='stop' and row['status'] not in ce.TERMINAL:
            row=await asyncio.to_thread(ce.transition,row,ce.ACTIVE,
                {'status':'stopped','hold':None,'finished_at':ce.now()},'stopped',
                'Stopped by the owner or manager. A submitted order may still need cancellation.')
        return ce.card(row)
    except HTTPException as exc:
        detail=exc.detail if isinstance(exc.detail,str) else exc.detail.get('message','Open the errand card.')
        return _fail(action.get('type','plan_errand'),detail)


async def handle_plan_errand(client,biz,action):
    return await _errand_action(client,biz,action,'plan')


async def handle_approve_errand(client,biz,action):
    return await _errand_action(client,biz,action,'approve')


async def handle_stop_errand(client,biz,action):
    return await _errand_action(client,biz,action,'stop')


async def handle_errand_status(client,biz,action):
    return await _errand_action(client,biz,action,'status')


async def handle_use_browser_hand(client, biz, action) -> Dict[str, Any]:
    """Propose a bounded browser task for approval.

    action: {task, start_url, domains?: [..], max_steps?: int}
    """
    try:
        spec = browser_hand.make_spec(
            action.get("task") or "", action.get("start_url") or "",
            action.get("domains") or [], action.get("max_steps"))
    except ValueError as e:
        return _fail("use_browser_hand", str(e))

    row = await _sb(client, "POST", "/agent_queue", {
        "business_id": biz["id"],
        "contact_id": action.get("contact_id") or None,
        "agent": "chief",
        "action_type": "browser_hand",
        "channel": "hand",
        "subject": f"Browser hand: {spec['task'][:90]}",
        "body": browser_hand.spec_to_body(spec),
        "status": "draft",
        "priority": "medium",
        "ai_reasoning": (action.get("why") or
                         "No integration exists for this site, so the hand is the door. "
                         "It runs only after you approve, only on the sites named, "
                         "and records every screen."),
    })
    qid = (row[0] if isinstance(row, list) and row else row or {}).get("id") if row else None
    if not qid:
        return _fail("use_browser_hand", "could not file the proposal")

    sites = ", ".join(spec["domains"])
    return {
        "type": "use_browser_hand",
        "result": "proposed",
        "label": f"🖐 Proposed for approval: {spec['task'][:70]} (on {sites})",
        "queue_id": qid,
        "spec": spec,
        "signal": {"proposed": True, "queue_id": qid, "domains": spec["domains"],
                   "max_steps": spec["max_steps"]},
        "nav": _nav("operate", "queue"),
    }
