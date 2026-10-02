"""Personal dashboard placement, persisted under the verified caller's own JWT."""
from urllib.parse import quote
import json
from chief_host import _sb, _fail
import sb_clients
from system_destinations import destination, module_destination

async def _identity(biz):
    import chief_of_staff as chief
    uid = chief._TURN_USER_ID.get()
    if not uid or not biz.get('id') or not sb_clients.get_current_user_jwt():
        raise ValueError('Open Chief in your signed-in workspace to arrange your dashboard.')
    return str(uid), str(biz['id'])

async def _read(client, uid, bid):
    rows = await _sb(client, 'GET', f'/user_ui_prefs?user_id=eq.{uid}&business_id=eq.{bid}&select=prefs&limit=1')
    if rows is None:
        raise ValueError("I couldn't read your saved layout. Nothing was changed.")
    return dict((rows[0].get('prefs') or {}) if rows else {}), bool(rows)

async def _target(client, biz, action, dashboard=False):
    module_ref = action.get('module_id') or action.get('module')
    sub = action.get('sub') or action.get('page')
    if not module_ref and isinstance(sub, str) and sub.startswith('module:'):
        module_ref = sub[7:]
    if module_ref:
        # Resolve against this business, never by an unscoped module id.
        rows = await _sb(client, 'GET', f"/custom_modules?business_id=eq.{biz['id']}&is_active=eq.true&select=id,name,slug,archetype")
        matches = [r for r in rows or [] if str(module_ref).casefold() in
                   (str(r.get('id','')).casefold(), str(r.get('slug','')).casefold(), str(r.get('name','')).casefold())]
        if len(matches) != 1:
            raise ValueError('Choose one existing tool in this business by its name or ID.')
        mod = matches[0]
        return {**module_destination(mod), 'label': mod.get('name') or mod.get('slug')}
    nav = destination(action.get('tab'), sub, dashboard=dashboard)
    return {**nav, 'label': str(action.get('label') or nav.get('sub') or nav['tab']).replace('-', ' ')[:100]}

async def handle_get_dashboard_layout(client, biz, action):
    try:
        uid, bid = await _identity(biz)
        prefs, _ = await _read(client, uid, bid)
        layout = {k: prefs.get(k) for k in ('dashboardFocus', 'startPage')}
        return {'type':'get_dashboard_layout', 'result':json.dumps(layout), 'label':'Your saved dashboard arrangement', **layout}
    except (ValueError, TypeError) as exc:
        return _fail('get_dashboard_layout', str(exc))

async def _save(client, biz, action, kind):
    try:
        uid, bid = await _identity(biz)
        prefs, exists = await _read(client, uid, bid)
        clear = action.get('clear') is True
        target = None if clear else await _target(client, biz, action, dashboard=kind == 'set_dashboard_focus')
        if kind == 'set_dashboard_focus':
            dashboard = str(action.get('dashboard') or 'home').lower()
            if dashboard not in ('home', 'operate', 'grow'):
                raise ValueError('Choose Home, Operate, or Grow for this dashboard.')
            focus = dict(prefs.get('dashboardFocus') or {})
            if clear:
                focus.pop(dashboard, None)
            else:
                focus[dashboard] = target
            prefs['dashboardFocus'] = focus
            nav = {'tab':dashboard, **({'sub':'dashboard'} if dashboard != 'home' else {})}
            label = f"{dashboard.title()} dashboard restored" if clear else f"{target['label']} now appears first on your {dashboard.title()} dashboard"
        else:
            prefs['startPage'] = target
            nav = target or {'tab':'home'}
            label = 'Your app opens on Home again' if clear else f"Your app now opens on {target['label']}"
        path = f'/user_ui_prefs?user_id=eq.{uid}&business_id=eq.{bid}'
        if exists:
            await _sb(client, 'PATCH', path, {'prefs':prefs})
        else:
            await _sb(client, 'POST', '/user_ui_prefs', {'user_id':uid,'business_id':bid,'prefs':prefs})
        saved, _ = await _read(client, uid, bid)
        key = 'dashboardFocus' if kind == 'set_dashboard_focus' else 'startPage'
        if saved.get(key) != prefs.get(key):
            raise ValueError("I couldn't confirm that your layout was saved. Please try again.")
        return {'type':kind,'result':'saved','label':label,'nav':nav,
                'frontend_event':{'name':'solutionist-dashboard-preferences', 'detail':{
                    'user_id':uid,'business_id':bid, **{k:saved.get(k) for k in ('dashboardFocus','startPage')}}}}
    except (ValueError, TypeError) as exc:
        return _fail(kind, str(exc))

async def handle_set_dashboard_focus(client, biz, action):
    return await _save(client, biz, action, 'set_dashboard_focus')

async def handle_set_start_page(client, biz, action):
    return await _save(client, biz, action, 'set_start_page')
