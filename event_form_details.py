"""Public event copy and explicit optional flyer selection. No network calls."""
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import ipaddress
from public_form_theme import safe_url

DETAIL_KEYS = ('description', 'starts_at', 'timezone', 'location', 'admission', 'include_flyer', 'flyer_url')

def is_event(form):
    return form.get('form_type') == 'event' or (form.get('settings') or {}).get('requested_form_type') == 'event'

def event_values(action, previous=None):
    values = dict(previous) if isinstance(previous,dict) else {}
    nested = action.get('event_details')
    if isinstance(nested, dict):
        values.update({k: nested[k] for k in DETAIL_KEYS if k in nested})
    values.update({k: action[k] for k in DETAIL_KEYS if k in action})
    for key in DETAIL_KEYS:
        if isinstance(values.get(key), str): values[key] = values[key].strip()
    if isinstance(values.get('include_flyer'),str): values['include_flyer']=values['include_flyer'].lower()
    if values.get('include_flyer') in ('yes','true'): values['include_flyer'] = True
    if values.get('include_flyer') in ('no','false'): values['include_flyer'] = False
    if not values.get('admission') and type(action.get('price')) in (int,float) and action['price']==0:
        values['admission'] = 'Free'
    return values

def flyer_url(value):
    value = safe_url(value)
    if not value: return ''
    host = urlsplit(value).hostname.lower()
    if host in ('localhost','localhost.localdomain') or host.endswith(('.local','.internal')): return ''
    try:
        if not ipaddress.ip_address(host).is_global: return ''
    except ValueError:
        if '.' not in host: return ''
    return value if len(value) <= 2000 else ''

def details_question(values, *, require_flyer_choice=True):
    prompts = [('description', 'What should visitors know about this event?'),
        ('starts_at', 'What date and time does the event start?'),
        ('timezone', 'Which time zone is the event in?'),
        ('location', 'Where does the event take place? Include the address or online attendance details.'),
        ('admission', 'What should the page say about admission or cost?')]
    for key, text in prompts:
        value = values.get(key)
        if not isinstance(value,str) or not value.strip(): return {'field':key,'text':text}
        if len(value)>4000: return {'field':key,'text':'Please keep this event detail under 4,000 characters.'}
    try:
        zone = ZoneInfo(values['timezone'])
    except Exception:
        return {'field':'timezone','text':'Which time zone should I use? For example, America/Detroit.'}
    try:
        raw = values['starts_at']
        if 'T' not in raw and ' ' not in raw: raise ValueError('time missing')
        dt = datetime.fromisoformat(raw.replace('Z','+00:00'))
        if dt.tzinfo is None:
            a,b=dt.replace(tzinfo=zone,fold=0),dt.replace(tzinfo=zone,fold=1)
            if a.utcoffset()!=b.utcoffset(): raise ValueError('ambiguous or nonexistent clock hour')
            dt=a
        values['starts_at']=dt.astimezone(zone).isoformat()
    except (ValueError,TypeError):
        return {'field':'starts_at','text':'Please give a valid event date and time, including its UTC offset if the clocks change that day.'}
    choice=values.get('include_flyer')
    if require_flyer_choice and type(choice) is not bool:
        return {'field':'include_flyer','text':'Would you like to include a flyer on the registration page? Say yes or no. The event details will appear either way.'}
    if choice is True and not flyer_url(values.get('flyer_url')):
        return {'field':'flyer_url','text':'Which flyer should appear on the page? Share its public image link, or ask me to prepare a flyer first.'}
    if choice is False: values.pop('flyer_url',None)
    return None

def date_label(values):
    try:
        dt=datetime.fromisoformat(values['starts_at'].replace('Z','+00:00')).astimezone(ZoneInfo(values['timezone']))
        return f"{dt.strftime('%A, %B')} {dt.day}, {dt.year} at {dt.hour%12 or 12}:{dt.minute:02d} {dt.strftime('%p %Z')}"
    except (KeyError,ValueError,TypeError): return ''


# Trusted SVG exports from the selected event-details reference, never user markup.
_DETAIL_ICONS = ["<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"xMidYMid meet\" fill=\"none\"><g fill=\"none\" stroke=\"currentColor\" stroke-width=\"4\" stroke-linejoin=\"round\"><circle cx=\"50\" cy=\"50\" r=\"46\"/></g><svg x=\"21\" y=\"21\" width=\"58\" height=\"58\" xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\" preserveAspectRatio=\"xMidYMid meet\" fill=\"none\"><path d=\"M12 2V8C12 9.10457 12.8954 10 14 10H20V20C20 21.1046 19.1046 22 18 22H6C4.89543 22 4 21.1046 4 20V4C4 2.89543 4.89543 2 6 2H12ZM13.5 2.5V8C13.5 8.27614 13.7239 8.5 14 8.5H19.5L13.5 2.5Z\" fill=\"currentColor\"/></svg></svg>","<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"xMidYMid meet\" fill=\"none\"><g fill=\"none\" stroke=\"currentColor\" stroke-width=\"4\" stroke-linejoin=\"round\"><circle cx=\"50\" cy=\"50\" r=\"46\"/></g><svg x=\"21\" y=\"21\" width=\"58\" height=\"58\" xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 256 256\" preserveAspectRatio=\"xMidYMid meet\"><rect width=\"256\" height=\"256\" fill=\"none\"/><rect x=\"40\" y=\"40\" width=\"176\" height=\"176\" rx=\"8\" fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"16\"/><line x1=\"176\" y1=\"24\" x2=\"176\" y2=\"56\" fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"16\"/><line x1=\"80\" y1=\"24\" x2=\"80\" y2=\"56\" fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"16\"/><line x1=\"40\" y1=\"88\" x2=\"216\" y2=\"88\" fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"16\"/><polyline points=\"88 128 104 120 104 184\" fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"16\"/><path d=\"M138.14,128a16,16,0,1,1,26.64,17.63L136,184h32\" fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"16\"/></svg></svg>","<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"xMidYMid meet\" fill=\"none\"><g fill=\"none\" stroke=\"currentColor\" stroke-width=\"4\" stroke-linejoin=\"round\"><circle cx=\"50\" cy=\"50\" r=\"46\"/></g><svg x=\"21\" y=\"21\" width=\"58\" height=\"58\" xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\" preserveAspectRatio=\"xMidYMid meet\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 18l-2 -4l-7 -3.5a.55 .55 0 0 1 0 -1l18 -6.5l-2.901 8.034\" /><path d=\"M21.121 20.121a3 3 0 1 0 -4.242 0c.418 .419 1.125 1.045 2.121 1.879c1.051 -.89 1.759 -1.516 2.121 -1.879\" /><path d=\"M19 18v.01\" /></svg></svg>","<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\" width=\"100%\" height=\"100%\" preserveAspectRatio=\"xMidYMid meet\" fill=\"none\"><g fill=\"none\" stroke=\"currentColor\" stroke-width=\"4\" stroke-linejoin=\"round\"><circle cx=\"50\" cy=\"50\" r=\"46\"/></g><svg x=\"21\" y=\"21\" width=\"58\" height=\"58\" xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\" preserveAspectRatio=\"xMidYMid meet\" fill=\"currentColor\"><path d=\"M14 4v2a1 1 0 0 0 2 0v-2h3a3 3 0 0 1 3 3v3a1 1 0 0 1 -.883 .993l-.117 .007a1 1 0 0 0 -.117 1.993l.117 .007a1 1 0 0 1 1 1v3a3 3 0 0 1 -3 3h-3v-2a1 1 0 0 0 -.883 -.993l-.117 -.007a1 1 0 0 0 -1 1v2h-9a3 3 0 0 1 -3 -3v-3a1 1 0 0 1 .883 -.993l.117 -.007a1 1 0 0 0 .117 -1.993l-.117 -.007a1 1 0 0 1 -1 -1v-3a2.995 2.995 0 0 1 2.727 -2.985l.222 -.014zm1 6a1 1 0 0 0 -1 1v2a1 1 0 0 0 2 0v-2a1 1 0 0 0 -1 -1\" /></svg></svg>"]

def details_html(form):
    """Keep written facts readable even if the optional image cannot load."""
    from html import escape
    if not is_event(form): return ''
    values=(form.get('settings') or {}).get('event_details')
    if not isinstance(values,dict): return ''  # Existing legacy links remain usable.
    esc=lambda v:escape(str(v or '')[:4000],quote=True)
    rows=[('About this event',values.get('description')),('Date and time',date_label(values)),
          ('Location',values.get('location')),('Admission',values.get('admission'))]
    items=''.join('<div class="event-detail"><dt><span class="event-detail-icon" aria-hidden="true">'+_DETAIL_ICONS[i]+'</span>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>' for i,(label,value) in enumerate(rows) if value)
    if not items: return ''
    result='<section class="event-details" aria-labelledby="event-details-heading"><h2 id="event-details-heading">Event details</h2><dl>'+items+'</dl></section>'
    image=flyer_url(values.get('flyer_url')) if values.get('include_flyer') is True else ''
    if image:
        result+='<figure class="event-flyer"><a href="'+esc(image)+'" target="_blank" rel="noopener noreferrer"><img src="'+esc(image)+'" alt="'+esc(form.get('name'))+' — event flyer" loading="lazy" decoding="async" referrerpolicy="no-referrer"></a><figcaption><a href="'+esc(image)+'" target="_blank" rel="noopener noreferrer">View full flyer ↗</a></figcaption></figure>'
    return result
