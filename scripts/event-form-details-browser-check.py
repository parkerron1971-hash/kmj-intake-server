"""Synthetic form checks. Intercept all writes and flyer requests."""
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT=Path(__file__).resolve().parents[2]/'event-form-browser';OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch();page=browser.new_page();errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.route('**/intake/submit',lambda r:r.fulfill(status=200,json={'success':True}))
 page.route('https://cdn.example.org/**',lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="#D4A72C"/><text x="35" y="80" font-size="28">Synthetic test flyer</text></svg>'))
 for width in (320,390,768,1280):
  page.set_viewport_size({'width':width,'height':1000})
  for flyer in (False,True):
   page.goto('http://127.0.0.1:5176/form'+('?flyer=1' if flyer else ''),wait_until='networkidle')
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.get_by_role('heading',name='Event details',exact=True).wait_for()
   assert '7:00 PM EDT' in page.locator('.event-details').inner_text()
   assert '1084 Allen Avenue' in page.locator('.event-details').inner_text()
   assert page.locator('.event-flyer').count()==int(flyer)
   if flyer:
    page.locator('.event-flyer').scroll_into_view_if_needed()
    assert page.locator('.event-flyer img').evaluate('(e)=>e.complete && e.naturalWidth>0')
   page.screenshot(path=str(OUT/('event-'+str(width)+'-'+('flyer' if flyer else 'details')+'.png')),full_page=True)
 # A broken optional flyer never replaces or hides the facts or signup.
 page.unroute('https://cdn.example.org/**');page.route('https://cdn.example.org/**',lambda r:r.fulfill(status=404,body='Missing image'))
 page.goto('http://127.0.0.1:5176/form?flyer=1',wait_until='networkidle')
 if page.locator('.event-flyer').is_visible(): page.locator('.event-flyer').scroll_into_view_if_needed()
 page.locator('.event-flyer').wait_for(state='hidden')
 assert page.get_by_role('heading',name='Event details').is_visible()
 page.get_by_label('Full name',exact=False).fill('Sample Visitor');page.get_by_label('Email address',exact=False).fill('sample@example.com')
 page.get_by_role('button',name='Register',exact=True).click()
 page.get_by_role('heading',name='Received',exact=True).wait_for()
 assert page.locator('.event-details').is_visible()
 assert not errors,errors
 browser.close();print('Passed: event details with/without flyer at four widths, broken flyer fallback, and registration confirmation.')
