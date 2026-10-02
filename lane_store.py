"""Service-only encrypted purchase journal with cross-worker leases and a permanent checkout claim."""
import hashlib
import json
import os
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from chief_errands import rpc
from lane_mcp import LaneError


def cipher():
    try:
        return Fernet(os.environ["LANE_WALLET_ENCRYPTION_KEY"].encode("ascii"))
    except Exception:
        raise LaneError("Lane purchase storage is not configured.") from None


def binding(bid, uid, key, purchase_id):
    return {"business_id": str(UUID(bid)), "user_id": str(UUID(uid)),
            "purchase_id": str(UUID(purchase_id)),
            "wallet": hashlib.sha256(key.encode()).hexdigest(), "version": 1}


def seal(identity, state):
    return cipher().encrypt(json.dumps({"binding": identity, "state": state}).encode()).decode()


def unpack(identity, row):
    try:
        value = json.loads(cipher().decrypt(row["encrypted_state"].encode()))
        if value["binding"] != identity or not isinstance(value["state"], dict):
            raise ValueError()
        return value["state"]
    except Exception:
        raise LaneError("This purchase belongs to a different wallet connection or cannot be opened safely.") from None


def listing(bid, uid, key):
    rows = rpc("lane_purchase_list", p_business_id=bid, p_user_id=uid) or []
    return [dict(unpack(binding(bid, uid, key, r["id"]), r), id=r["id"],
                 revision=r["revision"], checkout_claimed=r["checkout_claimed"]) for r in rows]


class Purchase:
    def __init__(self, bid, uid, key, purchase_id):
        self.identity = binding(bid, uid, key, purchase_id)
        self.args = {"p_business_id": bid, "p_user_id": uid, "p_id": str(UUID(purchase_id))}
        self.state = {}
        self.revision = 0
        self.claimed = False
        self.lease = str(uuid4())

    def create(self, prompt, details=None):
        state = {"phase": "new", "request": prompt, "purchase_details": details}
        digest = json.dumps({"prompt": prompt, "details": details}, sort_keys=True)
        result = rpc("lane_purchase_create", **self.args,
                     p_encrypted_state=seal(self.identity, state),
                     p_request_hash=hashlib.sha256(digest.encode()).hexdigest())
        if not result:
            raise LaneError("Another purchase is still open. Refresh the wallet before starting another.")
        return result

    def __enter__(self):
        row = rpc("lane_purchase_acquire", **self.args, p_lease=self.lease)
        if not row:
            raise LaneError("This purchase is busy or unavailable. Refresh its status.")
        try:
            self.state = unpack(self.identity, row)
            self.revision = row["revision"]
            self.claimed = row["checkout_claimed"]
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def save(self, *, claim=False):
        result = rpc("lane_purchase_save", **self.args, p_lease=self.lease,
                     p_revision=self.revision, p_phase=self.state["phase"],
                     p_intent_id=self.state.get("intent_id"),
                     p_encrypted_state=seal(self.identity, self.state), p_claim=claim)
        if not result:
            raise LaneError("The purchase changed. Refresh its status; do not repeat checkout.")
        self.revision = result["revision"]
        self.claimed = result["checkout_claimed"]

    def __exit__(self, *_):
        try:
            rpc("lane_purchase_release", **self.args, p_lease=self.lease)
        except Exception:
            pass  # Expiring lease; permanent checkout claim is never released.
