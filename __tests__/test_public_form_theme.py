import pathlib
import pytest
from public_form_theme import resolve_theme, css_vars, font_links, contrast

BIZ={'id':'biz','settings':{'brand_kit':{'colors':{'accent':'#009133','background':'#F7FAFC','text':'#2D3748'},'font_pair':{'heading':'Montserrat','body':'Open Sans'}}}}
def site(css,**kw):
    return {'business_id':'biz','status':'published','html_content':'<style>'+css+'</style>',**kw}

def test_nested_brand_colors_are_understood():
    t=resolve_theme(BIZ)
    assert t['accent']=='#009133' and t['surface']=='#F7FAFC'
    assert t['font_heading']=='Montserrat'
    assert 'family=Open%20Sans' in font_links(t)

def test_real_kmj_website_styles_take_precedence_over_old_brand():
    css=(pathlib.Path(__file__).parents[1]/'sites/kmj-creative-solutions/site.css').read_text()
    t=resolve_theme(BIZ,site(css))
    assert t['source']=='website' and t['surface']=='#F7F4EE' and t['accent']=='#D4A72C'
    assert 'Bricolage Grotesque' in t['font_heading'] and 'Work Sans' in t['font_body']
    assert t['radius']=='0px'
    assert '&#x27;' not in css_vars(t)
    assert contrast(t['accent'],t['accent_text'])>=4.5

@pytest.mark.parametrize('changes',[{'business_id':'someone-else'},{'status':'draft'}])
def test_only_own_published_site_is_inherited(changes):
    t=resolve_theme(BIZ,site(':root{--accent:#ff0000}',**changes))
    assert t['source']=='brand' and t['accent']=='#009133'

def test_updated_site_changes_theme_without_saved_form_rewrite():
    assert resolve_theme(BIZ,site(':root{--accent:#123456}'))['accent']=='#123456'
    assert resolve_theme(BIZ,site(':root{--accent:#654321}'))['accent']=='#654321'

def test_explicit_brand_mode_and_safe_site_overrides():
    s=site(':root{--accent:#ff0000}',form_theme={'accent':'#112233','radius':'4px'})
    assert resolve_theme(BIZ,s)['accent']=='#112233'
    assert resolve_theme(BIZ,s,{'appearance':'brand'})['accent']=='#009133'

@pytest.mark.parametrize('attack',['</style><script>alert(1)</script>','url(https://evil.example/a)','red; background:url(x)','var(--loop)','expression(alert(1))'])
def test_style_values_cannot_inject_css_or_html(attack):
    b={'id':'biz','settings':{'brand_kit':{'accent':attack,'font_body':attack,'logo_url':'javascript:alert(1)'}}}
    t=resolve_theme(b,site('',form_theme={'accent':attack,'font_heading':attack}))
    markup=css_vars(t)+font_links(t)
    assert attack not in markup and t['logo_url']==''

@pytest.mark.parametrize('background',['#101010','#ffffff','#D4A72C'])
def test_text_and_focus_remain_readable(background):
    t=resolve_theme(BIZ,site('',form_theme={'surface':background,'text_primary':background,'text_secondary':background,'accent':background}))
    for name in ('text_primary','text_secondary','focus'):assert contrast(t['surface'],t[name])>=4.5
    assert contrast(t['accent'],t['accent_text'])>=4.5

def test_cyclic_css_and_untrusted_markup_are_not_executed():
    s=site(':root{--a:var(--b);--b:var(--a);--accent:var(--a)}')
    s['html_content']+='<script>fetch("https://evil.example")</script>'
    assert resolve_theme(BIZ,s)['accent']=='#009133'
