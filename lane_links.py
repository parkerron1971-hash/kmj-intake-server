"""Owner-saved merchant links for the Lane pilot.

A saved link is a starting point, never trust: every look and every proposal
reads the page again, and every purchase still needs the Wallet review and
Lane's approval. Only the page, the merchant's name and the intended account
are kept, encrypted like the purchase journal; never a limit, password or code.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import lane_merchant as merchant
import lane_store as store
from lane_mcp import LaneError

LIMIT = 20  # Mirrors lane_link_save in supabase/APPLY-2026-09-25-lane-saved-links.sql.


def _digest(link):
    # Keyed, so the stored hash does not reveal which public page was saved.
    store.cipher()  # Unconfigured storage fails closed before any write.
    payload = json.dumps({"url": link["merchant_url"], "account": link["account"].casefold()}, sort_keys=True)
    return hmac.new(os.environ["LANE_WALLET_ENCRYPTION_KEY"].encode(), payload.encode(), hashlib.sha256).hexdigest()


def _binding(bid, uid, digest):
    return {"business_id": str(UUID(bid)), "user_id": str(UUID(uid)), "link_hash": digest,
            "kind": "lane_saved_link", "version": 1}


def _public(row_id, state):
    return {"id": row_id, **{k: state[k] for k in ("merchant_name", "merchant_url", "account", "saved_at") if k in state}}


def save(bid, uid, url, account, merchant_name=None):
    """Save or refresh one link; the same page and account is one entry."""
    link = merchant.link(url, account, merchant_name)
    digest = _digest(link)
    state = dict(link, saved_at=datetime.now(timezone.utc).isoformat())
    row_id = store.rpc("lane_link_save", p_business_id=bid, p_user_id=uid, p_id=str(uuid4()),
                       p_link_hash=digest, p_encrypted_state=store.seal(_binding(bid, uid, digest), state))
    if not row_id:
        raise LaneError(f"You already have {LIMIT} saved merchant links. Remove one in Settings > Wallet first.")
    return _public(str(row_id), state)


def listing(bid, uid):
    links = []
    for row in store.rpc("lane_link_list", p_business_id=bid, p_user_id=uid) or []:
        try:
            state = store.unpack(_binding(bid, uid, row["link_hash"]), row)
        except LaneError:
            continue  # Sealed under another key or altered: never shown, never used.
        links.append(_public(str(row["id"]), state))
    return links


def remove(bid, uid, link_id):
    return bool(store.rpc("lane_link_delete", p_business_id=bid, p_user_id=uid, p_id=str(UUID(link_id))))


def matching(bid, uid, url, account=None):
    url = merchant.merchant_url(url)
    want = account.strip().casefold() if isinstance(account, str) and account.strip() else None
    return [link for link in listing(bid, uid)
            if link["merchant_url"] == url and (want is None or link["account"].casefold() == want)]


def forget(bid, uid, url, account=None):
    return len([link for link in matching(bid, uid, url, account) if remove(bid, uid, link["id"])])
