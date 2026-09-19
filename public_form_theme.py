"""Bounded, deterministic website style inheritance for public forms.
Only validated design values are copied; source HTML/CSS is never embedded.
No browser, external stylesheet fetch, model call, or database write at render time.
"""
from __future__ import annotations
import html
import re
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

DEFAULTS = {'accent':'#334155','surface':'#ffffff','text_primary':'#0f172a',
            'text_secondary':'#475569','font_heading':'system-ui, sans-serif',
            'font_body':'system-ui, sans-serif','radius':'8px'}
SITE_SELECT = 'business_id,slug,status,html_content,form_theme:site_config->form_theme'

def mapping(value):
    return value if isinstance(value, dict) else {}

def color(value):
    value = str(value or '').strip()
    if re.fullmatch(r'#[0-9a-fA-F]{6}', value): return value
    if re.fullmatch(r'#[0-9a-fA-F]{3}', value): return '#' + ''.join(c*2 for c in value[1:])
    m = re.fullmatch(r'rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)', value)
    if m and all(int(c)<=255 for c in m.groups()): return '#%02x%02x%02x' % tuple(map(int,m.groups()))
    return None

def font(value):
    value = str(value or '').strip()
    if len(value)<=180 and re.fullmatch(r"[a-zA-Z0-9 ,'\"_-]+",value):
        return value
    return None

def radius(value):
    value = str(value or '').strip()
    return value if re.fullmatch(r'(?:0|[0-9]|[12][0-9]|3[0-2])(?:px)?',value) else None

def safe_url(value):
    value = str(value or '').strip()
    try:
        p=urlsplit(value)
        return value if p.scheme=='https' and p.hostname and not p.username and not p.password and not any(c in value for c in '\r\n<>') else ''
    except ValueError: return ''

def luminance(value):
    channels=[int(value[i:i+2],16)/255 for i in (1,3,5)]
    channels=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels]
    return sum(a*b for a,b in zip(channels,(.2126,.7152,.0722)))

def contrast(a,b):
    x,y=sorted((luminance(a),luminance(b)))
    return (y+.05)/(x+.05)

def readable(background, preferred=None):
    if color(preferred) and contrast(background,color(preferred))>=4.5: return color(preferred)
    return max(('#17150f','#ffffff'),key=lambda c:contrast(background,c))

class Styles(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.inside=False;self.css=[]
    def handle_starttag(self,tag,attrs):
        if tag=='style':self.inside=True
    def handle_endtag(self,tag):
        if tag=='style':self.inside=False
    def handle_data(self,data):
        if self.inside:self.css.append(data)

@lru_cache(maxsize=32)
def website_values(document):
    parser=Styles();parser.feed(document)
    css=re.sub(r'/\*.*?\*/','', '\n'.join(parser.css),flags=re.S)
    variables={};rules={}
    # Read simple semantic rules only. Unrecognized/cascading constructs fall
    # back to the saved brand; never pretend to execute arbitrary site CSS.
    for block in css.split('}'):
        if '{' not in block: continue
        selectors,body=block.rsplit('{',1)
        declarations={}
        for declaration in body.split(';'):
            key,sep,value=declaration.partition(':')
            key=key.strip().lower();value=value.strip()
            if sep and len(key)<=64 and re.fullmatch(r'[\w-]+',key) and len(value)<=512:
                declarations[key]=value
        for selector in selectors.split(','):
            selector=selector.strip()
            if selector==':root':variables.update(declarations)
            if selector in ('body','h1','.disp','.display','button','.btn','.button','.btn-primary','.btn-gold'):
                rules.setdefault(selector,{}).update(declarations)
    def resolve(value):
        for _ in range(5):
            m=re.fullmatch(r'var\((--[\w-]+)(?:,\s*([^()]+))?\)',value or '')
            if not m:break
            value=variables.get(m[1],m[2] or '')
        return value
    def pick(*names):
        return next((resolve(variables[n]) for n in names if n in variables),'')
    body=rules.get('body',{});head={};button={}
    for key in ('h1','.display','.disp'):head.update(rules.get(key,{}))
    for key in ('button','.button','.btn','.btn-primary','.btn-gold'):button.update(rules.get(key,{}))
    return {'surface':resolve(body.get('background-color') or body.get('background')) or pick('--surface','--background','--bg','--cream'),
            'text_primary':resolve(body.get('color')) or pick('--text-primary','--text','--foreground','--ink'),
            'text_secondary':pick('--text-secondary','--body','--muted'),
            'accent':resolve(button.get('background-color') or button.get('background')) or pick('--accent','--primary','--brand','--gold'),
            'font_body':resolve(body.get('font-family')) or pick('--font-body','--font-sans'),
            'font_heading':resolve(head.get('font-family')) or pick('--font-heading','--font-display'),
            'radius':resolve(button.get('border-radius')) or pick('--radius-control','--radius') or ('0px' if button else '')}

def resolve_theme(business, site=None, form_settings=None):
    brand=mapping(mapping(business.get('settings')).get('brand_kit'))
    colors=mapping(brand.get('colors'));fonts=mapping(brand.get('font_pair'))
    theme=dict(DEFAULTS)
    def apply(values):
        for k in ('accent','surface','text_primary','text_secondary'):
            if (v:=color(values.get(k))):theme[k]=v
        for k in ('font_heading','font_body'):
            if (v:=font(values.get(k))):theme[k]=v
        if (v:=radius(values.get('radius'))):theme['radius']=v
    apply({'accent':brand.get('accent') or colors.get('accent') or brand.get('primary_color') or colors.get('primary'),
           'surface':brand.get('surface') or colors.get('background'),
           'text_primary':brand.get('text_primary') or colors.get('text'),
           'text_secondary':brand.get('text_secondary'),
           'font_heading':brand.get('font_heading') or fonts.get('heading'),
           'font_body':brand.get('font_body') or fonts.get('body'), 'radius':brand.get('radius')})
    site=mapping(site);theme['source']='brand'
    if (mapping(form_settings).get('appearance')!='brand' and site.get('status')=='published'
            and str(site.get('business_id'))==str(business.get('id'))):
        document=site.get('html_content')
        values=website_values(document[:524288]) if isinstance(document,str) else {}
        if any(color(values.get(k)) for k in ('surface','accent')) or font(values.get('font_body')):
            apply(values);theme['source']='website'
        overrides=mapping(site.get('form_theme') or mapping(site.get('site_config')).get('form_theme'))
        if overrides:apply(overrides);theme['source']='website'
    theme['text_primary']=readable(theme['surface'],theme['text_primary'])
    theme['text_secondary']=readable(theme['surface'],theme['text_secondary'])
    theme['text_muted']=theme['text_secondary']
    theme['accent_text']=readable(theme['accent'])
    theme['accent_hover']=theme['accent']
    theme['focus']=readable(theme['surface'],theme['accent'])
    theme['border']=theme['text_secondary']
    theme['error']=readable(theme['surface'],'#b91c1c')
    theme['input_surface']=theme['surface']
    theme['logo_url']=safe_url(brand.get('logo_url') or brand.get('logo') or mapping(brand.get('assets')).get('primary'))
    return theme

def css_vars(theme):
    keys=tuple(DEFAULTS)+('text_muted','accent_text','accent_hover','focus','border','input_surface','error')
    return ':root{' + ''.join('--'+k.replace('_','-')+': '+theme[k]+';' for k in keys) + '}'

def font_links(theme):
    # Load validated named fonts, not arbitrary source stylesheet URLs.
    families=[]
    for k in ('font_heading','font_body'):
        name=theme[k].split(',')[0].strip().strip('\"\'')
        if name.lower() not in ('inherit','system-ui','sans-serif','serif','monospace','arial','georgia','helvetica','verdana','times new roman','segoe ui') and name not in families:
            families.append(name)
    if not families:return ''
    url='https://fonts.googleapis.com/css2?'+'&'.join('family='+quote(n)+':wght@400;500;600;700;800' for n in families)+'&display=swap'
    return '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="'+html.escape(url,quote=True)+'">'
