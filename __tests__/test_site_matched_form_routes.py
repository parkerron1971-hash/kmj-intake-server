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

def test_a_switched_off_form_shows_its_closed_page_on_the_site_address(monkeypatch):
    import public_site
    paths=[]
    async def db(client,path):
        paths.append(path)
        if path.startswith('/intake_forms'):return [] if 'is_active=eq.true' in path else [FORM]
        if path.startswith('/business_sites'):return [SITE]
        return [BIZ]
    monkeypatch.setattr(public_site,'_sb_service',db)
    response=asyncio.run(public_site._serve_form_page(None,'biz-1','example','f1'))
    body=response.body.decode()
    assert response.status_code==404 and 'Workshop registration' in body
    assert 'isn’t taking answers right now' in body and '<form' not in body and 'intake/submit' not in body
    assert 'href="https://example.mysolutionist.app/"' in body and '--accent: #D4A72C' in body
    # Still only this business's own form.
    assert all('business_id=eq.biz-1' in p for p in paths if p.startswith('/intake_forms'))

def test_a_form_that_does_not_exist_is_still_not_found(monkeypatch):
    import pytest
    from fastapi import HTTPException
    import intake_endpoint,public_site
    async def none_site(client,path):return []
    async def none_api(client,method,path,body=None):return []
    monkeypatch.setattr(public_site,'_sb_service',none_site)
    monkeypatch.setattr(intake_endpoint,'supabase_request',none_api)
    with pytest.raises(HTTPException) as site:
        asyncio.run(public_site._serve_form_page(None,'biz-1','example','nope'))
    req=SimpleNamespace(url=SimpleNamespace(hostname='api.example',port=None),query_params={})
    with pytest.raises(HTTPException) as api:
        asyncio.run(intake_endpoint.public_form_page('nope',req))
    assert site.value.status_code==api.value.status_code==404

def test_the_closed_page_without_a_website_has_no_way_home():
    from form_page_renderer import render_closed_page
    body=render_closed_page(BIZ,{**FORM,'name':'<b>Trip</b>'},canonical_url='https://api.example/public/widget/form/f1')
    assert '&lt;b&gt;Trip&lt;/b&gt;' in body and '<b>Trip' not in body
    assert 'class="home"' not in body and 'Not open right now' in body

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
