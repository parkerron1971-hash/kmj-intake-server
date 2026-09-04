"""
action_proposals.py — class C through a tool: propose, a person
approves, then it runs.

THE RULE THIS KEEPS. A class C verb — a text that leaves at once, an
invoice that touches Stripe, a payment recorded on the ledger — is
never a tool an agent can execute. That was true before this module
and is true after it: exposed_tools() still lists none of them, the
tool loop still refuses them, and the connector's flat "not available"
still answers a call to `send_sms`.

WHAT CHANGES. An agent that is not the practitioner — the standing
agent between conversations, or a ChatGPT / Claude connected through
the connector with the write scope — can now PROPOSE one of a reviewed
set of class C actions. A proposal is an agent_queue row on channel
"action": the practitioner sees it in the same Approval Queue as every
draft, with the exact action in plain words, and Approve runs it
through _execute_actions with prompted=True — because a person just
asked — surface "approval". Dismiss throws it away. Nothing happens in
between. This is the browser hand's pattern, generalised.

WHY NOT ON THE CHAT TURN. When the practitioner themselves asks Chief
to text Maria, the [ACTION:] tag path already runs it, with the
spoken-confirmation hold and the class-C gate. Filing a proposal for a
person who is sitting right there would be a slower way to say yes.
So the propose_* tools are offered only off the chat turn; on it the
loop answers "do it directly".

THE REVIEWED SET. Each entry names the verb it proposes, the arguments
it accepts, and how it reads in the queue. Recipients are always a
known contact (contact_id or name), never a raw number or address —
an outside agent cannot aim a text at a stranger.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import action_registry
import sb_clients

logger = logging.getLogger("action_proposals")

CHANNEL = "action"
ACTION_TYPE = "chief_action"
SMS_MAX = 320


def _obj(props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props,
            "required": required or [], "additionalProperties": False}


# tool name → (verb, description, schema). Descriptions say what a
# proposal IS every time, so a model never reads "send" as sent.
PROPOSALS: Dict[str, Tuple[str, str, Dict[str, Any]]] = {
    "propose_send_sms": (
        "send_sms",
        "PROPOSE a text message to one contact. Nothing is sent: the "
        "practitioner sees the exact words in their Approval Queue and "
        "sends or dismisses. Use for a confirmation, a reminder, a reply "
        "they would want to send. Under 320 characters, warm, first name.",
        _obj({"contact_id": {"type": "string", "description": "The contact's uuid, when known."},
              "contact_name": {"type": "string", "description": "Their name, if you do not have the id."},
              "message": {"type": "string", "maxLength": SMS_MAX}},
             ["message"])),
    "propose_send_invoice": (
        "send_invoice",
        "PROPOSE sending an existing invoice to its contact. Nothing is "
        "sent until the practitioner approves it in their queue.",
        _obj({"invoice_id": {"type": "string"}}, ["invoice_id"])),
    "propose_mark_invoice_paid": (
        "mark_invoice_paid",
        "PROPOSE recording an invoice as paid (a ledger fact). Recorded "
        "only when the practitioner approves it.",
        _obj({"invoice_id": {"type": "string"},
              "payment_method": {"type": "string",
                                 "description": "cash | check | card | transfer | other"}},
             ["invoice_id"])),
    "propose_generate_payment_link": (
        "generate_payment_link",
        "PROPOSE creating a Stripe payment link for a product. Created "
        "only when the practitioner approves it.",
        _obj({"product_id": {"type": "string"},
              "name": {"type": "string", "description": "The product's name, if you do not have the id."}})),
    "propose_publish_to_site": (
        "publish_to_site",
        "PROPOSE publishing a planned post to the business's own news "
        "page. Published only when the practitioner approves it.",
        _obj({"post_id": {"type": "string"},
              "post_title": {"type": "string", "description": "The planned post's title, if you do not have the id."}})),
}

# Arguments a proposal may never carry: a raw recipient. A text goes to
# a contact on file or it does not go.
_FORBIDDEN_ARGS = {"to", "phone", "email", "customer_email"}


def verbs() -> List[str]:
    return sorted({v for v, _, _ in PROPOSALS.values()})


def tool_for_verb(verb: str) -> Optional[str]:
    for name, (v, _, _) in PROPOSALS.items():
        if v == verb:
            return name
    return None


def tool_definitions() -> List[Dict[str, Any]]:
    """MCP-shaped descriptors for the connector; the tool loop reshapes."""
    return [{"name": name, "description": desc, "inputSchema": schema}
            for name, (_, desc, schema) in PROPOSALS.items()]


def action_for(tool: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The [ACTION:]-shaped dict a proposal will run as. Validates the
    tool, the arguments, and the recipient rule; raises ValueError with
    a sentence the calling model can read."""
    if tool not in PROPOSALS:
        raise ValueError(f"{tool!r} is not a proposal tool")
    verb, _, schema = PROPOSALS[tool]
    args = dict(arguments or {})
    bad = sorted(k for k in args if k in _FORBIDDEN_ARGS)
    if bad:
        raise ValueError("a proposal goes to a contact on file, not to a raw "
                         f"number or address ({', '.join(bad)} not accepted)")
    unknown = sorted(k for k in args if k not in schema["properties"])
    if unknown:
        raise ValueError(f"{tool} does not take {', '.join(unknown)}")
    missing = [k for k in schema.get("required", []) if not str(args.get(k) or "").strip()]
    if missing:
        raise ValueError(f"{tool} needs {', '.join(missing)}")
    for k, v in list(args.items()):
        if isinstance(v, str):
            args[k] = v.strip()
    if verb == "send_sms":
        if not (args.get("contact_id") or args.get("contact_name")):
            raise ValueError("propose_send_sms needs contact_id or contact_name")
        if len(args["message"]) > SMS_MAX:
            raise ValueError(f"keep the text under {SMS_MAX} characters")
    if verb == "generate_payment_link" and not (args.get("product_id") or args.get("name")):
        raise ValueError("propose_generate_payment_link needs product_id or name")
    if verb == "publish_to_site" and not (args.get("post_id") or args.get("post_title")):
        raise ValueError("propose_publish_to_site needs post_id or post_title")
    return {"type": verb, **args}


def describe(action: Dict[str, Any]) -> str:
    """One plain sentence for the queue's subject."""
    verb = action.get("type")
    if verb == "send_sms":
        who = action.get("contact_name") or f"contact {str(action.get('contact_id') or '')[:8]}"
        msg = str(action.get("message") or "")
        return f"Text {who}: “{msg[:120]}{'…' if len(msg) > 120 else ''}”"
    if verb == "send_invoice":
        return f"Send invoice {str(action.get('invoice_id') or '')[:8]} to its contact"
    if verb == "mark_invoice_paid":
        how = f" ({action['payment_method']})" if action.get("payment_method") else ""
        return f"Mark invoice {str(action.get('invoice_id') or '')[:8]} paid{how}"
    if verb == "generate_payment_link":
        return f"Create a payment link for {action.get('name') or 'product ' + str(action.get('product_id') or '')[:8]}"
    if verb == "publish_to_site":
        return f"Publish “{action.get('post_title') or 'post ' + str(action.get('post_id') or '')[:8]}” to the site's news page"
    return f"Run {verb}"


def spec_to_body(spec: Dict[str, Any]) -> str:
    action = spec.get("action") or {}
    lines = [describe(action), ""]
    for k, v in action.items():
        if k == "type" or v in (None, ""):
            continue
        lines.append(f"{k.replace('_', ' ')}: {v}")
    lines += ["",
              "Proposed by " + str(spec.get("actor") or "an agent") +
              ". Nothing has happened yet: Approve runs exactly this, Dismiss throws it away.",
              "", "spec: " + json.dumps(spec, separators=(",", ":"), ensure_ascii=False)]
    return "\n".join(lines)


def spec_from_body(body: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"^spec:\s*(\{.*\})\s*$", body or "", re.M)
    if not m:
        return None
    try:
        spec = json.loads(m.group(1))
    except Exception:
        return None
    action = spec.get("action") if isinstance(spec, dict) else None
    if not isinstance(action, dict) or action.get("type") not in verbs():
        return None
    tool = tool_for_verb(action["type"])
    try:
        # Re-validated on the way out, so a hand-edited body cannot widen
        # what an approval runs.
        action = action_for(tool, {k: v for k, v in action.items() if k != "type"})
    except ValueError:
        return None
    return {**spec, "action": action}


def file(business_id: str, action: Dict[str, Any], *, actor: str,
         surface: str, why: Optional[str] = None,
         contact_id: Optional[str] = None) -> Optional[str]:
    """Put one proposal in the Approval Queue. Sync, service role; the
    caller has already checked the business and the actor. Returns the
    queue row id, or None when the insert failed."""
    verb = action.get("type")
    if verb not in verbs():
        raise ValueError(f"{verb!r} cannot be proposed")
    if action_registry.reversibility(verb) != "C":
        raise ValueError(f"{verb!r} is not class C — do it with its own tool")
    spec = {"action": action, "actor": actor, "surface": surface}
    # A standing permission (standing_permissions, 2026-09-04): the row
    # carries a release time and the spec says so; the release tick runs
    # it unless the practitioner stops it first.
    import standing_permissions
    biz_row = standing_permissions.load_for_filing(business_id)
    standing_extra = standing_permissions.filing_extras(biz_row, str(verb))
    if standing_extra:
        spec["standing"] = True
    row = {
        "business_id": business_id,
        "contact_id": contact_id or action.get("contact_id") or None,
        "agent": "chief" if str(actor).startswith("chief") else "agent",
        "action_type": ACTION_TYPE,
        "channel": CHANNEL,
        "subject": describe(action)[:200],
        "body": spec_to_body(spec),
        "status": "draft",
        "priority": "medium",
        "ai_reasoning": (why or "").strip() or
                        f"Proposed by {actor}: this needs your approval before it runs.",
    }
    # A proposal has a life (proposal_life, 2026-09-04): it expires,
    # it reminds, and it reaches the phone with a button. The columns
    # ride only when the table has them; the push is best-effort.
    import proposal_life
    row.update(proposal_life.filing_extras())
    row.update(standing_extra)
    res = sb_clients.sb_post_as_service("/agent_queue", row)
    qid: Optional[str] = None
    if isinstance(res, list) and res:
        qid = str(res[0].get("id") or "") or None
    elif isinstance(res, dict):
        qid = str(res.get("id") or "") or None
    if qid:
        if standing_extra:
            standing_permissions.announce_standing(
                business_id, (biz_row or {}).get("owner_id"), qid, describe(action))
        else:
            proposal_life.announce_filed(business_id, qid, describe(action))
    return qid


async def execute(client, biz: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Approve = run. Through the door, prompted=True: a person just
    asked. Returns the delivery dict _do_approve_one hands back."""
    spec = spec_from_body(item.get("body") or "")
    if not spec:
        return {"ok": False, "sent": False, "reason": "action_spec_invalid",
                "message": "this proposal's action could not be read back"}
    action = dict(spec["action"])
    import chief_of_staff
    try:
        results = await chief_of_staff._execute_actions(
            client, biz, [action], user_id=str(biz.get("owner_id") or "") or None,
            surface=("standing" if item.get("_standing") else "approval"), prompted=True)
    except Exception as e:
        logger.warning(f"[proposal] {action.get('type')} raised: {e}")
        return {"ok": False, "sent": False, "reason": "action_failed",
                "message": f"{action.get('type')} failed: {type(e).__name__}",
                "action_type": action.get("type")}
    result = results[0] if results else {}
    failed = (not isinstance(result, dict)) or chief_of_staff._action_failed(result)
    return {"ok": not failed, "sent": False,
            "reason": "action_failed" if failed else "action_ran",
            "message": (result.get("result") if isinstance(result, dict) else str(result)),
            "action_type": action.get("type"),
            "action_label": (result.get("label") if isinstance(result, dict) else None),
            "action_result": result}
