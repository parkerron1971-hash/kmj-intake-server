"""RPC boundary fake; actual SQL behavior is covered by lifecycle-email-db-check.mjs."""
from copy import deepcopy
import lifecycle_delivery

class DeliveryDB:
    def __init__(self):
        self.rows = {}
        self.fail_finish = False

    def rpc(self, name, data):
        key = data['p_key']
        if name == 'lifecycle_claim':
            row = self.rows.setdefault(key, {'state': 'pending', 'payload': deepcopy(data['p_payload'])})
            if row['state'] == 'sent':
                return {'state': 'sent', 'provider_id': row['provider_id']}
            if row['state'] in ('sending', 'review'):
                return {'state': 'busy' if row['state'] == 'sending' else 'review'}
            row['state'] = 'sending'
            return {'state': 'claimed', 'token': 'token', 'payload': deepcopy(row['payload'])}
        if name == 'lifecycle_finish':
            if self.fail_finish:
                raise RuntimeError('DB acknowledgement lost')
            self.rows[key].update(state='sent', provider_id=data['p_provider_id'])
            return True
        if name == 'lifecycle_fail':
            self.rows[key]['state'] = 'pending'
            return True
        raise AssertionError(name)

def install_delivery_fake(monkeypatch):
    fake = DeliveryDB()
    monkeypatch.setattr(lifecycle_delivery, 'rpc', fake.rpc)
    return fake
