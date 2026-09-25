"""Chief can prepare Lane drafts and report saved status, never approve or execute checkout."""
import asyncio
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import business_access
import lane_purchases as purchases
import lane_store


async def handle_lane_wallet(client, biz, action):
    from chief_host import _fail
    return _fail("lane_wallet", "Lane requires the authenticated Chief chat action door.")


async def dispatch(client, biz, action, *, surface, prompted, user_id):
    from chief_of_staff import _TURN_USER_ID
    from chief_host import _fail
    if surface != "chat" or not prompted or not user_id or user_id != _TURN_USER_ID.get():
        return _fail("lane_wallet", "Lane is available only in your current authenticated chat.")
    if set(action) - {"type", "operation", "prompt"} or action.get("operation") not in {"draft", "status"}:
        return _fail("lane_wallet", "Chief can prepare a purchase or read its saved status. Review and checkout happen in Wallet.")
    def run():
        bid = str(biz["id"])
        business_access.assert_access(bid, SimpleNamespace(id=user_id), "owner")
        key = purchases.credentials(bid, user_id)
        if action["operation"] == "draft":
            prompt = purchases.text(action.get("prompt"), 4000)
            # Duplicate tool/tag emissions with identical requests return the same draft.
            pid = str(uuid5(NAMESPACE_URL, "solutionist-lane:" + bid + ":" + user_id + ":" + prompt))
            result = purchases.draft(bid, user_id, pid, prompt)
        else:
            result = {"purchases": [purchases.snapshot(r) for r in lane_store.listing(bid, user_id, key)]}
        return {"type": "lane_wallet", "label": "Lane wallet", "lane": result,
                "result": "Lane request saved or status read. Open Settings > Wallet to review. This tool cannot approve or start a purchase."}
    try:
        return await asyncio.to_thread(run)
    except purchases.mcp.LaneError as exc:
        return _fail("lane_wallet", str(exc))
    except Exception:
        return _fail("lane_wallet", "Lane could not finish safely. Check Wallet status before another request.")


def tool_definition():
    return {"name": "lane_wallet",
            "description": "Prepare a Lane purchase draft from the user's buying request, or read saved purchase status. Never claim a saved status was freshly verified. Share the returned Lane approval URL exactly and direct the owner to Settings > Wallet. Only the real user can approve and start checkout there. No spending, card collection, passwords, or codes through this tool. Pass the user's request verbatim; never invent a budget, product, or consent.",
            "input_schema": {"type": "object", "properties": {
                "operation": {"type": "string", "enum": ["draft", "status"]},
                "prompt": {"type": "string", "maxLength": 4000}},
                "required": ["operation"], "additionalProperties": False}}
