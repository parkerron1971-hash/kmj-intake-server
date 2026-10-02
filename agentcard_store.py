"""Cross-worker lease and encrypted state bound to the business, user, mode and client."""
import json
import os
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from chief_errands import rpc
from agentcard_client import AgentcardError, binding


def cipher():
    try:
        return Fernet(os.environ['AGENTCARD_ENCRYPTION_KEY'].encode())
    except Exception:
        raise AgentcardError('Wallet storage is not configured.', status=503) from None


class Wallet:
    def __init__(self, bid, uid):
        self.identity = dict(business_id=str(UUID(bid)), user_id=str(UUID(uid)), binding=binding())
        self.args = {'p_business_id': self.identity['business_id'], 'p_user_id': self.identity['user_id'],
                     'p_binding': self.identity['binding'], 'p_lease': str(uuid4())}
        self.state = {}
        self.revision = 0

    def __enter__(self):
        row = rpc('agentcard_wallet_acquire', **self.args)
        if not row:
            raise AgentcardError('Your wallet is processing another request. Please wait, then refresh.', status=409)
        self.revision = row['revision']
        try:
            if row['encrypted_state']:
                value = json.loads(cipher().decrypt(row['encrypted_state'].encode()))
                if value['identity'] != self.identity or not isinstance(value['state'], dict):
                    raise ValueError()
                self.state = value['state']
        except Exception:
            self.__exit__(None, None, None)
            raise AgentcardError('This wallet cannot be opened safely. Contact support.', status=503) from None
        return self

    def save(self):
        encrypted = cipher().encrypt(json.dumps({'identity': self.identity, 'state': self.state}).encode()).decode()
        revision = rpc('agentcard_wallet_save', **self.args, p_revision=self.revision, p_state=encrypted)
        if revision is None:
            raise AgentcardError('Wallet changed during this request. Refresh its status; do not repeat checkout.', status=409)
        self.revision = revision

    def __exit__(self, *_):
        try:
            rpc('agentcard_wallet_release', **self.args)
        except Exception:
            pass  # Lease expires; persisted in-flight markers are never reset here.
