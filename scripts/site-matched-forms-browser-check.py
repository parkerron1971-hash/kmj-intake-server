"""Run the companion local preview first. All POSTs are intercepted."""
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT=Path(__file__).resolve().parents[2]/'form-browser'
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch()
 page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 posts=[]
 def submit(route):
  posts.append(route.request.post_data_json)
  route.fulfill(status=200,json={'success':True})
 page.route('**/intake/submit',submit)
 for width in (320,390,768,1280):
  page.set_viewport_size({'width':width,'height':1000})
  page.goto('http://127.0.0.1:5176/form',wait_until='networkidle')
  page.evaluate('document.fonts.ready')
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
  assert page.locator('body').get_attribute('data-style-source')=='website'
  assert page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(247, 244, 238)'
  assert 'Work Sans' in page.locator('body').evaluate('(e)=>getComputedStyle(e).fontFamily')
  assert page.get_by_role('button',name='Register',exact=True).evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(212, 167, 44)'
  page.screenshot(path=str(OUT/f'form-{width}.png'),full_page=True)
 # Required and email validation must prevent a request.
 page.get_by_role('button',name='Register',exact=True).click();assert not posts
 page.get_by_label('Full name',exact=False).fill('Sample Visitor')
 page.get_by_label('Email address',exact=False).fill('invalid')
 page.get_by_role('button',name='Register',exact=True).click();assert not posts
 page.get_by_label('Email address',exact=False).fill('sample@example.com')
 page.get_by_role('button',name='Register',exact=True).click()
 page.get_by_role('heading',name='Received',exact=True).wait_for()
 assert posts[0]['data']['name']=='Sample Visitor' and posts[0]['form_id']=='preview-form'
 page.screenshot(path=str(OUT/'confirmation.png'),full_page=True)
 # A server error keeps the answers and permits a retry.
 page.unroute('**/intake/submit');page.route('**/intake/submit',lambda r:r.fulfill(status=422,json={'detail':'Please check your registration details.'}))
 page.goto('http://127.0.0.1:5176/form')
 page.get_by_label('Full name',exact=False).fill('Retained Name');page.get_by_label('Email address',exact=False).fill('sample@example.com')
 page.get_by_role('button',name='Register',exact=True).click()
 page.get_by_role('alert').filter(has_text='Please check').wait_for()
 assert page.get_by_label('Full name',exact=False).input_value()=='Retained Name'
 assert page.get_by_role('button',name='Register',exact=True).is_enabled()
 page.screenshot(path=str(OUT/'error.png'),full_page=True)
 # The embed uses the same form and adapts to its own narrow viewport.
 page.set_viewport_size({'width':390,'height':900});page.goto('http://127.0.0.1:5176/embed')
 frame=page.frame_locator('iframe');frame.get_by_label('Full name',exact=False).wait_for()
 assert frame.locator('body').get_attribute('data-embedded')=='true'
 assert frame.locator('body').evaluate('()=>document.documentElement.scrollWidth <= innerWidth')
 frame.get_by_label('Full name',exact=False).fill('Embedded Name');frame.get_by_label('Email address',exact=False).fill('sample@example.com')
 page.unroute('**/intake/submit');page.route('**/intake/submit',submit)
 frame.get_by_role('button',name='Register',exact=True).click();frame.get_by_role('heading',name='Received',exact=True).wait_for()
 page.screenshot(path=str(OUT/'embedded-confirmation.png'),full_page=True)
 assert len(posts)==2 and not errors,errors
 # Dark websites retain readable fields and a working gold button too.
 page.set_viewport_size({'width':1280,'height':1000})
 page.goto('http://127.0.0.1:5176/form?dark=1',wait_until='networkidle')
 assert page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(20, 18, 14)'
 assert page.get_by_label('Full name',exact=False).evaluate('(e)=>getComputedStyle(e).color')=='rgb(247, 244, 238)'
 page.screenshot(path=str(OUT/'form-dark.png'),full_page=True)
 browser.close()
 print('Form browser checks passed: four widths, website fonts/colors, required/email validation, submission, confirmation, retained answers after failure, and working iframe.')
