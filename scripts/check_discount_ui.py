"""Run after the isolated Vite coupon preview build. Uses mocked Stripe-backed API responses."""
import argparse
import functools
import http.server
import json
import threading
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--preview-dir', type=Path, default=ROOT / 'output' / 'coupons-qa')
QA = parser.parse_args().preview_dir.resolve()
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(QA / 'build'))
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}/tests/discounts-preview.html'
created = []
requests = []
fail_next = [True]

def intercept(route):
    req = route.request
    path = urlparse(req.url).path
    payload = req.post_data_json if req.method == 'POST' else None
    requests.append((req.method, path, payload))
    headers = {'access-control-allow-origin': '*'}
    def reply(value, status=200):
        route.fulfill(status=status, content_type='application/json', headers=headers, body=json.dumps(value))
    if req.method == 'OPTIONS':
        route.fulfill(status=204, headers={**headers, 'access-control-allow-methods':'GET, POST, OPTIONS', 'access-control-allow-headers':'content-type'})
    elif path == '/billing/discount-targets':
        reply({'items':[{'id':'00000000-0000-0000-0000-000000000001','name':'Sample Studio','subscription_status':'active'}]})
    elif path.endswith('/deactivate'):
        created[0]['active'] = False
        reply(created[0])
    elif path == '/billing/apply-discount':
        reply({'ok':True,'code':payload['code']})
    elif req.method == 'GET':
        reply({'items':created,'next_cursor':None})
    elif fail_next[0]:
        fail_next[0] = False
        reply({'detail':'Stripe is temporarily unavailable. Retry the same request.'},503)
    else:
        item = {'id':'promo_preview','code':payload['code'],'active':True,'livemode':False,'times_redeemed':0,
                'max_redemptions':payload.get('max_redemptions'),'expires_at':payload.get('expires_at'),
                'coupon':{'valid':True,'percent_off':payload.get('percent_off'),'amount_off':payload.get('amount_off'),
                          'currency':payload.get('currency','usd'),'duration':payload['duration'],'duration_in_months':payload.get('duration_in_months')}}
        created.append(item)
        reply(item)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1280,'height':980})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('https://kmj-intake-server-production.up.railway.app/**', intercept)
        page.goto(base)
        expect(page.get_by_text('No coupons yet.', exact=False)).to_be_visible()
        page.get_by_role('button',name='Create coupon').click()
        page.get_by_label('Code',exact=True).fill('welcome20')
        page.get_by_label('Maximum uses',exact=False).fill('50')
        page.screenshot(path=str(QA/'platform-desktop.png'),full_page=True)
        page.get_by_role('button',name='Save coupon to Stripe').click()
        expect(page.get_by_role('alert')).to_contain_text('temporarily unavailable')
        page.get_by_role('button',name='Save coupon to Stripe').click()
        expect(page.locator('.discounts-notice')).to_contain_text('WELCOME20 is saved')
        creates = [r[2] for r in requests if r[0]=='POST' and r[1]=='/billing/discounts']
        assert len(creates)==2 and creates[0]['request_id']==creates[1]['request_id']
        assert creates[1]['percent_off']==20 and creates[1]['max_redemptions']==50
        page.get_by_label('Business',exact=False).select_option('00000000-0000-0000-0000-000000000001')
        page.get_by_label('Coupon code',exact=True).fill('welcome20')
        page.get_by_role('button',name='Apply discount',exact=True).click()
        expect(page.locator('.discounts-notice')).to_contain_text('applied to Sample Studio')
        page.get_by_role('button',name='Deactivate',exact=True).click()
        expect(page.get_by_text('Unavailable',exact=False)).to_be_visible()
        page.goto(base+'?business=business-demo')
        expect(page.get_by_text('CUSTOMER CHECKOUT',exact=True)).to_be_visible()
        assert page.get_by_role('heading',name='Apply to a subscription').count()==0
        page.get_by_role('button',name='Create coupon').click()
        page.get_by_label('Code',exact=True).fill('SAVE5')
        page.get_by_label('Discount type').select_option('amount')
        page.get_by_label('Amount off').fill('5')
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(QA/'business-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.get_by_role('button',name='Save coupon to Stripe').click()
        expect(page.locator('.discounts-notice')).to_contain_text('SAVE5 is saved')
        business_create = [r[2] for r in requests if r[0]=='POST' and r[1]=='/payments/business-demo/discounts'][-1]
        assert business_create['amount_off']==500 and business_create['duration']=='once'
        assert not errors, errors
        browser.close()
        print('PASS: create, retry idempotency, apply, deactivate, business scope, dollar conversion, desktop/mobile, no overflow or JS errors')
finally:
    server.shutdown()
