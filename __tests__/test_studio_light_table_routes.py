"""The Light Table's routes reach the Light Table in the deployed app.

2026-11-10: after #1784 deployed, every GET /ai/images/studio/{business_id}
answered 422. image_studio registers GET /ai/images/{business_id}/{image_id}
first, so "studio" was read as a business id and refused, and the app fell
back to the older Studio. The router tests mount studio_light_table alone,
so they could not see it. This walks the real app's route table in order,
the way Starlette does, and asks which handler a request lands on.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from starlette.routing import Match

import kmj_intake_automation as kia
import studio_light_table

BIZ = '009e9a2c-3e81-4bfc-a92a-205a8806aa99'


def first_handler(method: str, path: str):
    scope = {'type': 'http', 'method': method, 'path': path, 'root_path': '',
             'query_string': b'', 'headers': []}
    partial = None
    for route in kia.app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route.endpoint
        if match == Match.PARTIAL and partial is None:
            partial = route  # path matched, method didn't: Starlette keeps looking
    return partial.endpoint if partial is not None else None


@pytest.mark.parametrize('method,path,handler', [
    ('GET', f'/ai/images/studio/{BIZ}', studio_light_table.studio_status),
    ('POST', f'/ai/images/studio/{BIZ}/design', studio_light_table.studio_design),
])
def test_the_light_table_answers_its_own_routes(method, path, handler):
    assert first_handler(method, path) is handler


def test_image_studio_still_answers_an_image_read():
    """Moving the Light Table first must not take image reads with it."""
    import image_studio
    got = first_handler('GET', f'/ai/images/{BIZ}/00000000-0000-4000-8000-0000000000d1')
    assert got is not None and got.__module__ == image_studio.__name__
