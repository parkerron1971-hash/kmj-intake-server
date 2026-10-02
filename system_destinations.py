"""Destinations shared with the app. A successful action must lead somewhere real."""
import json
from pathlib import Path
from uuid import UUID

CONTRACT = json.loads(Path(__file__).with_name('system_destinations.json').read_text())

def destination(tab, sub=None, *, dashboard=False):
    tab = str(tab or '').strip().lower()
    tab = {'command_center': 'home', 'my_dashboard': 'home', 'mission_control': 'home'}.get(tab, tab)
    sub = str(sub or '').strip()
    alias = CONTRACT['aliases'].get(f'{tab}/{sub}')
    if alias:
        tab, sub = alias.split('/', 1)
    if tab not in CONTRACT['routes']:
        raise ValueError('That destination is not available in your workspace.')
    if sub.startswith('module:') and tab in ('operate', 'build'):
        try:
            UUID(sub[7:])
        except ValueError:
            raise ValueError('Choose an existing tool in this business.')
    elif sub and sub not in CONTRACT['routes'][tab]:
        if not dashboard and (sub in CONTRACT['groups'] and sub.startswith(f'{tab}:') or
                (tab == 'build' and sub.startswith('foundation-phase:') and sub.split(':')[-1] in ('1','2','3','4','5','6','7','8'))):
            pass
        else:
            raise ValueError('That page is not available. Choose an existing workspace page.')
    if dashboard and (tab == 'home' or not sub or sub == 'dashboard' or tab == 'build' and not sub.startswith('module:')):
        raise ValueError('Choose a work page or an existing tool to feature on the dashboard.')
    return {'tab': tab, **({'sub': sub} if sub else {})}

def module_destination(module):
    from module_spec_generator import ARCHETYPE_METADATA
    metadata = ARCHETYPE_METADATA.get(module.get('archetype') or 'fallback_generic', {})
    tab = metadata.get('daily_use_surface') or metadata.get('config_surface') or 'build'
    # These are the two module hosts the app actually mounts.
    if tab not in ('operate', 'build'):
        tab = 'build'
    return {'tab': tab, 'sub': f"module:{module['id']}"}
