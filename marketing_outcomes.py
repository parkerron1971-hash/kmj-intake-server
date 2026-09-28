"""What came through a Solutionist post's link: clicks, visits, leads, signups, paying.

Every platform marketing post carries its own short link, and the redirect
behind it tags the landing URL with utm_content=<post id>. The marketing
site's attribution stash keeps that tag for the session, the traffic beacon
reports it, the lead form and the /start door carry it, and the app stores
it on the business it creates. So the post id is the one join key, and it is
exact — no window, no fuzzy matching, no campaign-name collisions.

This is a RECORDED relationship, never a causal claim (the same rule as
growth_intelligence): "3 signups came through this post's link", not "this
post brought 3 signups". A person who saw the post and typed the address in
is invisible here, and a person who clicked and would have signed up anyway
is counted. Callers word it that way.

A read that fails is reported as unavailable, never as zero — a broken read
that renders as "0 signups" is a lie with a number in it.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import HTTPException

import platform_marketing as marketing

MEASURES = ('clicks', 'visits', 'leads', 'waitlist', 'signups', 'paying')
BATCH = 100


def _ids(posts):
    """Validated post ids: they are interpolated into PostgREST filters."""
    return [str(UUID(str(p['id']))) for p in posts]


async def _batched(path_for, ids):
    rows = []
    for i in range(0, len(ids), BATCH):
        rows.extend(await marketing.db('GET', path_for(','.join(ids[i:i + BATCH]))))
    return rows


async def _read(fetch):
    try:
        return await fetch(), True
    except HTTPException:
        return [], False


async def for_posts(posts):
    """Per-post and total outcomes for these posts, with each source's status.

    Returns {'posts': {post_id: {measure: n}}, 'totals': {measure: n|None},
             'sources': {measure: 'loaded'|'unavailable'}}.
    """
    ids = _ids(posts)
    per = {pid: {m: 0 for m in MEASURES} for pid in ids}
    sources = {m: 'loaded' for m in MEASURES}
    if not ids:
        return {'posts': per, 'totals': {m: 0 for m in MEASURES}, 'sources': sources}

    (clicks, ok_c), (events, ok_v), (leads, ok_l), (waits, ok_w), (bizs, ok_b) = await asyncio.gather(
        _read(lambda: _batched(lambda s: f'/platform_marketing_link_clicks?post_id=in.({s})&select=post_id,clicks&limit=10000', ids)),
        _read(lambda: _batched(lambda s: f'/site_events?business_id=is.null&data->>utm_content=in.({s})&select=session_id,data&limit=20000', ids)),
        _read(lambda: _batched(lambda s: f'/marketing_leads?attribution->>utm_content=in.({s})&select=id,attribution&limit=5000', ids)),
        _read(lambda: _batched(lambda s: f'/waitlist?attribution->>utm_content=in.({s})&select=id,attribution&limit=5000', ids)),
        _read(lambda: _batched(lambda s: f'/businesses?attribution->>utm_content=in.({s})&select=id,attribution,subscription_status&limit=5000', ids)),
    )

    for row in clicks:
        if row.get('post_id') in per:
            per[row['post_id']]['clicks'] += int(row.get('clicks') or 0)

    sessions = {}
    for row in events:
        pid = (row.get('data') or {}).get('utm_content')
        sid = row.get('session_id')
        if pid in per and sid:
            sessions.setdefault(pid, set()).add(sid)
    for pid, seen in sessions.items():
        per[pid]['visits'] = len(seen)

    def tally(rows, measure):
        for row in rows:
            pid = (row.get('attribution') or {}).get('utm_content')
            if pid in per:
                per[pid][measure] += 1

    tally(leads, 'leads')
    tally(waits, 'waitlist')
    tally(bizs, 'signups')
    tally([b for b in bizs if b.get('subscription_status') == 'active'], 'paying')

    for measure, ok in (('clicks', ok_c), ('visits', ok_v), ('leads', ok_l),
                        ('waitlist', ok_w), ('signups', ok_b), ('paying', ok_b)):
        if not ok:
            sources[measure] = 'unavailable'
    totals = {m: (sum(p[m] for p in per.values()) if sources[m] == 'loaded' else None) for m in MEASURES}
    for pid in per:
        for m in MEASURES:
            if sources[m] != 'loaded':
                per[pid][m] = None
    return {'posts': per, 'totals': totals, 'sources': sources}


def _count(n, one, many):
    return f"{n} {one if n == 1 else many}"


def headline(totals, published):
    """One plain sentence for the owner. Worded as 'came through', never 'brought'."""
    if not published:
        return 'Nothing has been published from Mission Control yet, so there is nothing to measure.'
    if any(totals.get(m) is None for m in ('clicks', 'signups')):
        return 'Some results could not be read just now. Nothing below is a zero because of that; check again shortly.'
    posts = _count(published, 'published post', 'published posts')
    if not totals['clicks'] and not totals['visits']:
        return f"No one has followed the links in your {posts} yet."
    # A click to /start skips the site (no visit), and Do Not Track visits
    # carry no counted click, so the larger of the two is the honest floor.
    parts = [_count(max(totals['clicks'], totals['visits'] or 0), 'visit', 'visits')]
    if totals['leads']:
        parts.append(_count(totals['leads'], 'lead', 'leads'))
    if totals['signups']:
        parts.append(_count(totals['signups'], 'signup', 'signups'))
    if totals['paying']:
        parts.append(_count(totals['paying'], 'paying customer', 'paying customers'))
    listed = parts[0] if len(parts) == 1 else ', '.join(parts[:-1]) + ' and ' + parts[-1]
    return f"{listed} came through the links in your {posts}."
