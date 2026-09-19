import asyncio
from types import SimpleNamespace
from form_page_renderer import render_form_page
import public_form_theme

BIZ={'id':'biz-1','name':'Example','settings':{}}
FORM={'id':'f1','business_id':'biz-1','name':'Workshop registration','form_type':'event','fields':[{'name':'name','label':'Your name','required':True}], 'settings':{}}
SITE={'business_id':'biz-1','slug':'example','status':'published','html_content':'<style>:root{--accent:#D4A72C;--surface:#F7F4EE;--font-body:Work Sans}</style>'}

def test_form_route_loads_only_the_own_published_site(monkeypatch):
    import intake_endpoint,chief_form_actions
    paths=[]
    async def db(client,method,path,body=None):
        paths.append(path)
        if path.startswith('/intake_forms'):return [FORM]
        if path.startswith('/business_sites'):return [SITE]
        return [BIZ]
    monkeypatch.setattr(intake_endpoint,'supabase_request',db)
    monkeypatch.setattr(chief_form_actions,'public_form_url',lambda b,f:'https://example.mysolutionist.app/public/widget/form/f1')
    req=SimpleNamespace(url=SimpleNamespace(hostname='api.example',port=None),query_params={'embed':'1'})
    response=asyncio.run(intake_endpoint.public_form_page('f1',req))
    body=response.body.decode()
    assert '--accent: #D4A72C' in body and 'data-embedded="true"' in body
    assert any('/business_sites?business_id=eq.biz-1&status=eq.published&select=' in p for p in paths)
    assert 'form_id' in body and 'action="https://api.example/intake/submit"' in body

def test_site_domain_route_passes_the_same_published_style(monkeypatch):
    import public_site
    async def db(client,path):
        if path.startswith('/intake_forms'):return [FORM]
        if path.startswith('/business_sites'):return [SITE]
        return [BIZ]
    monkeypatch.setattr(public_site,'_sb_service',db)
    response=asyncio.run(public_site._serve_form_page(None,'biz-1','example','f1'))
    assert '--accent: #D4A72C' in response.body.decode()

def test_registration_and_confirmation_share_the_website_theme():
    rendered=render_form_page(BIZ,FORM,site=SITE,submit_url='https://api.example/intake/submit',canonical_url='https://example.mysolutionist.app/public/widget/form/f1')
    assert 'Register</button>' in rendered and 'fonts.googleapis.com/css2?' in rendered
    assert 'background:var(--input-surface)' in rendered
    assert 'data-style-source="website"' in rendered
    assert 'href="https://example.mysolutionist.app/"' in rendered

def test_site_css_never_becomes_executable_form_markup():
    malicious={**SITE,'html_content':'<style>:root{--accent:#123456}</style><script>alert(999)</script><img src=x onerror=alert(999)>'}
    body=render_form_page(BIZ,FORM,site=malicious,submit_url='https://api.example/intake/submit',canonical_url='https://example.mysolutionist.app/form')
    assert 'alert(999)' not in body and '--accent: #123456' in body


def test_event_registration_controls_use_website_style():
    from events_rsvp_router import render_events_page
    html=render_events_page(BIZ,[],'https://example.mysolutionist.app/events','example',api_origin='https://api.example',site=SITE)
    assert '--accent: #D4A72C' in html and '--surface: #F7F4EE' in html
    assert 'color:var(--accent-text)' in html and 'border-radius:var(--radius)' in html
    assert 'fonts.googleapis.com/css2?' in html
