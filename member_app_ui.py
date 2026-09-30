"""
member_app_ui.py — the member app's look ("Broadcast", Kevin 2026-09-30).

The member page (/my, member_portal.py + member_portal_church.py +
member_portal_sermons.py) is one small app on a church's own address:
Home · Sermons · Groups · Me along the bottom, a dark ground, and the
church's own accent colour on the buttons. Kevin picked this direction
from the member-app mockups after walking through his church's current
app: keep its strengths (series artwork up front, a real "me" page) and
fix its gaps (nothing timely on Home, sermons hard to browse, forms that
change look mid-app).

The ground is fixed (dark navy) so every church's page reads well; the
accent comes from the church's brand and is swapped for warm gold only
when it would be too dark to see on the ground. Series have no uploaded
artwork yet, so each gets a typographic "poster" in a stable colour.

Pure functions, no I/O.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from public_form_theme import contrast, color, readable

GROUND = "#07142B"
SURFACE = "#0F2146"
SURFACE_2 = "#132D57"
LINE = "#1F3764"
LINE_2 = "#2A4677"
TEXT = "#F7F1E6"
MUTED = "#B8C6DC"
DIM = "#8FA0BD"
NAV = "#0A1A38"
GOLD = "#F2C77E"
ERROR = "#FFB4A6"

# Poster colours for series and groups (text colour is worked out per
# poster so it always reads).
POSTERS = ("#F2C77E", "#E07B4F", "#3E7BE0", "#A9D3FA", "#F4EBDD", "#7FC8A9")

TABS = (
    ("home", "/my", "Home",
     '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>'),
    ("sermons", "/my/sermons", "Sermons",
     '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>'),
    ("groups", "/my/groups", "Groups",
     '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
     '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'),
    ("me", "/my/me", "Me",
     '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
)

ICONS = {
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "play": '<polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="none"/>',
    "chevron": '<path d="m9 18 6-6-6-6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "back": '<path d="m15 18-6-6 6-6"/>',
}


def icon(name: str, size: int = 20) -> str:
    return (f'<svg class="mb-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true" focusable="false">{ICONS[name]}</svg>')


def accent_for(theme: Dict[str, Any]) -> str:
    """The church's accent when it shows up on the dark ground, else gold."""
    a = color(theme.get("accent")) or GOLD
    return a if contrast(a, GROUND) >= 3 else GOLD


def poster_colour(key: Any) -> str:
    """A stable colour per series/group id: the same series is the same
    colour on Home, the shelf and its own page."""
    n = int(hashlib.sha256(str(key or "").encode()).hexdigest()[:8], 16)
    return POSTERS[n % len(POSTERS)]


def poster_style(key: Any) -> str:
    bg = poster_colour(key)
    return f"background:{bg};color:{readable(bg)}"


def initials(name: Any) -> str:
    parts = [p for p in str(name or "").split() if p[:1].isalpha()]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def nav(active: Optional[str]) -> str:
    items = []
    for key, href, label, paths in TABS:
        cur = ' aria-current="page"' if key == active else ""
        items.append(f'<a class="mb-tab" href="{href}"{cur}><svg width="22" height="22" viewBox="0 0 24 24" '
                     f'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                     f'stroke-linejoin="round" aria-hidden="true" focusable="false">{paths}</svg>{label}</a>')
    return f'<nav class="mb-nav mp-noprint" aria-label="Main">{"".join(items)}</nav>'


def css(theme: Dict[str, Any]) -> str:
    """The Broadcast palette on top of the church's theme variables: the
    existing mp-* classes pick it up through the same --tokens."""
    acc = accent_for(theme)
    acc_text = readable(acc)
    return f""":root{{--surface:{GROUND};--input-surface:{SURFACE_2};--text-primary:{TEXT};--text-secondary:{MUTED};
--text-muted:{DIM};--border:{LINE_2};--accent:{acc};--accent-text:{acc_text};--focus:{acc};--error:{ERROR};
--mb-surface:{SURFACE};--mb-surface-2:{SURFACE_2};--mb-line:{LINE};--mb-nav:{NAV};color-scheme:dark;}}
html,body{{margin:0;padding:0;font-family:var(--font-body);color:var(--text-primary);background:var(--surface);min-height:100vh;}}
*{{box-sizing:border-box;}}
a{{color:var(--accent);}}
.mp-shell{{max-width:520px;margin:0 auto;padding:18px 16px 40px;}}
.mp-shell.mb-has-nav{{padding-bottom:calc(104px + env(safe-area-inset-bottom,0px));}}
.mb-top{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px;}}
.mb-brand{{display:flex;align-items:center;gap:10px;min-width:0;}}
.mp-logo{{max-width:36px;max-height:36px;border-radius:8px;display:block;}}
.mp-church{{font-family:var(--font-heading);font-size:15px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;margin:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.mb-avatar{{width:40px;height:40px;flex:none;border-radius:50%;background:var(--accent);color:var(--accent-text);display:grid;place-items:center;
  font-weight:800;font-size:14px;text-decoration:none;}}
h1{{font-family:var(--font-heading);font-size:30px;font-weight:800;line-height:1.08;letter-spacing:-.01em;margin:0 0 6px;text-wrap:balance;}}
h2{{font-family:var(--font-heading);font-size:19px;font-weight:800;margin:0 0 8px;}}
p{{line-height:1.55;margin:0 0 12px;}}
.mp-muted{{color:var(--text-secondary);font-size:14px;}}
.mp-card{{background:var(--mb-surface);border:1px solid var(--mb-line);border-radius:16px;padding:16px;margin-bottom:14px;}}
.mp-card>:last-child{{margin-bottom:0;}}
.mp-form{{display:flex;flex-direction:column;gap:10px;}}
label{{font-size:14px;font-weight:600;}}
.mp-input{{width:100%;padding:12px 14px;font-size:16px;border:1px solid var(--border);border-radius:12px;background:var(--input-surface);
  color:var(--text-primary);min-height:48px;font-family:var(--font-body);}}
select.mp-input{{appearance:auto;}}
.mp-code{{letter-spacing:.4em;text-align:center;font-size:24px;font-variant-numeric:tabular-nums;}}
.mp-go{{width:100%;padding:13px 16px;font-size:15px;font-weight:700;border:0;border-radius:12px;background:var(--accent);color:var(--accent-text);
  cursor:pointer;min-height:48px;font-family:var(--font-body);text-align:center;text-decoration:none;display:inline-flex;align-items:center;
  justify-content:center;gap:8px;}}
.mp-go-2{{width:auto;background:transparent;color:var(--text-primary);border:1px solid var(--border);}}
.mp-link{{background:none;border:0;padding:10px 0;min-height:44px;font:inherit;font-size:14px;color:var(--text-secondary);cursor:pointer;
  text-decoration:underline;text-underline-offset:3px;}}
.mb-back{{display:inline-flex;align-items:center;gap:4px;min-height:44px;color:var(--text-secondary);text-decoration:none;font-size:14px;
  margin:-6px 0 6px;}}
.mp-err{{color:var(--error);font-size:14px;font-weight:600;}}
.mp-flash{{padding:12px 14px;border-radius:12px;background:var(--mb-surface-2);border:1px solid var(--mb-line);margin:4px 0 14px;}}
.mp-ok{{color:var(--text-primary);font-weight:600;font-size:14px;}}
.mp-total{{font-family:var(--font-heading);font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;margin:2px 0 4px;}}
.mp-gifts{{list-style:none;margin:8px 0 0;padding:0;}}
.mp-gifts li{{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--mb-line);font-size:15px;}}
.mp-gifts li span:last-child{{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600;}}
.mp-years{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px;}}
.mp-years a{{padding:8px 14px;min-height:40px;border:1px solid var(--border);border-radius:999px;color:var(--text-primary);text-decoration:none;
  font-size:14px;display:inline-flex;align-items:center;}}
.mp-years a[aria-current]{{background:var(--accent);color:var(--accent-text);border-color:var(--accent);font-weight:700;}}
.mp-row{{display:flex;flex-direction:column;gap:10px;}}
.mp-person{{width:100%;text-align:left;padding:14px 16px;min-height:52px;border:1px solid var(--border);border-radius:12px;
  background:var(--input-surface);color:var(--text-primary);font:inherit;font-size:16px;cursor:pointer;}}
.mp-sect{{font-family:var(--font-body);font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--text-secondary);
  margin:22px 0 10px;}}
.mp-when{{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0 0 4px;}}
.mp-occ h2,.mp-occ h3{{font-family:var(--font-heading);font-size:19px;font-weight:800;line-height:1.25;margin:0 0 4px;}}
.mp-mine{{font-size:14px;font-weight:600;margin:6px 0 0;color:var(--accent);}}
.mp-actions{{display:flex;flex-direction:column;gap:8px;margin-top:12px;}}
.mp-actions:empty{{display:none;}}
.mp-serve{{display:flex;gap:8px;flex-wrap:wrap;}}
.mp-serve select{{flex:1 1 180px;min-width:0;}}
.mp-text{{min-height:140px;resize:vertical;line-height:1.5;}}
.mp-check{{display:flex;gap:10px;align-items:flex-start;font-weight:500;}}
.mp-check input{{width:20px;height:20px;margin:2px 0 0;accent-color:var(--accent);}}
.mp-sr{{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}}
.mp-foot{{text-align:center;font-size:12px;color:var(--text-muted);margin-top:28px;padding-top:14px;border-top:1px solid var(--mb-line);}}
.mb-strip{{display:flex;align-items:center;gap:10px;min-height:52px;padding:10px 14px;border-radius:12px;background:var(--mb-surface);
  border:1px solid var(--mb-line);color:var(--text-primary);text-decoration:none;margin-bottom:14px;font-size:14px;}}
.mb-strip .mb-ic{{color:var(--accent);flex:none;}}
.mb-strip span{{flex:1;min-width:0;}}
.mb-strip strong{{font-weight:700;}}
.mb-hero{{background:var(--mb-surface);border:1px solid var(--mb-line);border-radius:18px;overflow:hidden;margin-bottom:14px;}}
.mb-poster{{display:flex;flex-direction:column;justify-content:flex-end;padding:14px 16px;min-height:150px;text-decoration:none;}}
.mb-poster-eyebrow{{font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;opacity:.85;margin-bottom:6px;}}
.mb-poster-title{{font-family:var(--font-heading);font-size:34px;font-weight:800;line-height:.95;letter-spacing:-.01em;text-transform:uppercase;
  overflow-wrap:anywhere;}}
.mb-hero-body{{padding:14px 16px 16px;display:flex;flex-direction:column;gap:10px;}}
.mb-hero-title{{font-family:var(--font-heading);font-size:19px;font-weight:800;margin:0;line-height:1.2;}}
.mb-hero-title a{{color:inherit;text-decoration:none;}}
.mb-meta{{font-size:13px;color:var(--text-secondary);margin:0;}}
.mb-week{{list-style:none;margin:0 0 6px;padding:0;}}
.mb-week li+li{{border-top:1px solid var(--mb-line);}}
.mb-week a,.mb-week .mb-week-row{{display:flex;align-items:center;gap:12px;min-height:56px;padding:6px 0;color:var(--text-primary);text-decoration:none;}}
.mb-date{{width:44px;flex:none;text-align:center;font-size:11px;font-weight:700;letter-spacing:.06em;color:var(--accent);line-height:1.15;
  text-transform:uppercase;}}
.mb-week-text{{flex:1;min-width:0;display:flex;flex-direction:column;}}
.mb-week-text strong{{font-size:15px;}}
.mb-week-text span{{font-size:12px;color:var(--text-secondary);}}
.mb-quick{{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:8px;margin:14px 0;}}
.mb-quick a{{min-height:56px;border-radius:12px;background:var(--mb-surface);border:1px solid var(--mb-line);display:flex;align-items:center;
  justify-content:center;gap:8px;color:var(--text-primary);text-decoration:none;font-weight:700;font-size:14px;}}
.mb-quick .mb-ic{{color:var(--accent);}}
.mb-shelf{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:6px;}}
.mb-shelf a{{min-height:140px;border-radius:14px;padding:12px;display:flex;flex-direction:column;justify-content:space-between;text-decoration:none;}}
.mb-shelf .mb-count{{font-size:11px;font-weight:700;}}
.mb-shelf .mb-poster-title{{font-size:21px;}}
.mb-list{{list-style:none;margin:0;padding:0;}}
.mb-list li+li{{border-top:1px solid var(--mb-line);}}
.mb-list a{{display:flex;align-items:center;gap:12px;min-height:60px;padding:8px 0;color:var(--text-primary);text-decoration:none;}}
.mb-list .mb-ic{{color:var(--text-muted);flex:none;}}
.mb-list .mb-thumb .mb-ic,.mb-week .mb-thumb .mb-ic{{color:inherit;}}
.mb-list-text{{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}}
.mb-list-text strong{{font-size:15px;}}
.mb-list-text span{{font-size:12px;color:var(--text-secondary);}}
.mb-thumb{{width:52px;height:52px;flex:none;border-radius:10px;display:grid;place-items:center;}}
.mb-video{{position:relative;width:100%;aspect-ratio:16/9;border-radius:14px;overflow:hidden;background:#000;margin:12px 0;}}
.mb-video iframe{{position:absolute;inset:0;width:100%;height:100%;border:0;}}
.mb-text{{font-size:16px;line-height:1.65;white-space:pre-line;margin:0;}}
.mb-group-band{{min-height:92px;padding:12px 14px;display:flex;flex-direction:column;justify-content:flex-end;margin:-16px -16px 12px;
  border-radius:15px 15px 0 0;}}
.mp-occ .mb-group-band h3{{font-family:var(--font-heading);font-size:22px;font-weight:800;line-height:1;text-transform:uppercase;margin:0;color:inherit;}}
.mb-profile{{display:flex;align-items:center;gap:14px;margin-bottom:16px;}}
.mb-profile .mb-avatar{{width:56px;height:56px;font-size:19px;}}
.mb-nav{{position:fixed;left:0;right:0;bottom:0;z-index:10;background:var(--mb-nav);border-top:1px solid var(--mb-line);
  padding:6px 6px calc(8px + env(safe-area-inset-bottom,0px));display:grid;grid-template-columns:repeat(4,minmax(0,1fr));}}
.mb-tab{{min-height:56px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;text-decoration:none;
  color:var(--text-muted);font-size:11px;font-weight:600;}}
.mb-tab[aria-current]{{color:var(--accent);font-weight:800;}}
@media (min-width:600px){{.mb-nav{{max-width:520px;margin:0 auto;border-left:1px solid var(--mb-line);border-right:1px solid var(--mb-line);
  border-radius:16px 16px 0 0;}}}}
.mp-go:focus-visible,.mp-input:focus-visible,.mp-link:focus-visible,.mp-person:focus-visible,.mp-years a:focus-visible,.mb-tab:focus-visible,
.mb-quick a:focus-visible,.mb-list a:focus-visible,.mb-week a:focus-visible,.mb-shelf a:focus-visible,.mb-strip:focus-visible,.mb-back:focus-visible,
.mb-poster:focus-visible,.mb-avatar:focus-visible{{outline:2px solid var(--focus);outline-offset:3px;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--mb-line);}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;}}
@media print{{.mp-noprint{{display:none!important;}} html,body{{background:#fff;color:#000;}} .mp-shell{{max-width:none;padding:0;}}
  .mp-card{{background:#fff;border-color:#999;}} th,td{{border-color:#999;}} .mp-muted{{color:#333;}}}}"""
