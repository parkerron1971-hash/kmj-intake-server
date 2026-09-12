"""Repair confirmed-order bookkeeping without ever re-running a browser."""
import re
import chief_errands as ce


def lifecycle(row,kind):
    verbs={'planned':'errand_planned','approved':'errand_approved',
           'secret_filled':'errand_secret_filled','done':'order_placed',
           'failed':'errand_failed','stopped':'errand_stopped',
           'paused':'errand_paused','resumed':'errand_resumed'}
    if kind not in verbs: return
    if kind=='done' and row.get('kind','reorder')!='reorder': verbs['done']='errand_done'
    import audit_log
    receipt=row.get('receipt') or {}
    payload={'errand_id':row['id'],'status':row['status']}
    if kind=='done':
        payload.update(charged_cents=receipt.get('charged_cents'),host=receipt.get('confirmation_host'))
        last4=re.search(r'(\d{4})$',receipt.get('paid_with') or '')
        if last4: payload['last4']=last4[1]
    return audit_log.record(row['business_id'],actor_type='chief',actor_id=row.get('approved_by') or row.get('user_id'),
        verb=verbs[kind],target_type='errand',target_id=row['id'],source='chief-computer',
        authorized_by='errand:'+str(row.get('approval_scope') or 'plan-only'),
        ok=kind!='failed',error='Errand stopped without a verified completion.' if kind=='failed' else None,
        summary=verbs[kind].replace('_',' '),payload=payload)


def repair(row,store=ce):
    if row['status']!='done' or row['kind']!='reorder': return row
    if not (row.get('receipt') or {}).get('document_id'):
        from errand_driver import write_receipt
        receipt={**row['receipt'],**write_receipt(row,row['receipt'],row['plan'].get('__confirmation_text',''),storage=store)}
        row=store.transition(row,('done',),{'receipt':receipt})
    return store.rpc('chief_errand_complete',p_business_id=row['business_id'],p_id=row['id'])


def reports(business_id):
    rows=ce.db('GET',f'/chief_errands?business_id=eq.{ce.uid(business_id)}'
        f'&status=in.(done,failed,stopped,interrupted)&select={ce.ERRAND_COLUMNS}&order=finished_at.desc&limit=20') or []
    result=[]
    for row in rows:
        if row['status']=='done' and (not row['plan'].get('__completion_done') or not (row.get('receipt') or {}).get('document_id')):
            try: row=repair(row)
            except Exception: pass  # durable receipt still prevents a second purchase
        if not row['plan'].get('__shown'):
            result.append(ce.card(row,replay=True))
    return result
