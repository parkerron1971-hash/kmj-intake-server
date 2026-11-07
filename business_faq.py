"""One FAQ for a business, and the truth about where it shows.

Love City, 2026-11-07: Kevin gave Chief six answers. Chief saved them to
settings.business_picture.faq and said each was "live on the website FAQ".
Kevin opened the FAQ in Settings → Website concierge and it was empty,
because that screen read settings.concierge.faq, a second list only it
wrote. The church's hand-built site had no FAQ section either. Nothing was
lost, but the only two businesses with FAQ answers were both told something
untrue, and Chief, asked about it, could not say otherwise: the answer check
never saw the list.

So there is one list, settings.business_picture.faq. Chief adds to it, the
Settings screen edits it, and the website and the website assistant read it.
settings.concierge.faq is only read, for a row saved there before this, and
the next save folds it in. `where_it_shows` is the one place that says
where a business's FAQ can be seen; Chief's receipts and its prompt both use
it, so neither can promise a page that does not exist.

No imports of the app at module level: site_composer, site_concierge,
public_site and Chief's actions all read this.
"""
from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, Iterable, List, Optional

FAQ_LIMIT = 24
QUESTION_CHARS = 300
ANSWER_CHARS = 600

# Policies become the question a client would ask.
POLICY_QUESTIONS = (
    ("cancellation", "What is your cancellation policy?"),
    ("deposit", "Do you require a deposit?"),
    ("lateness", "What if I'm running late?"),
    ("refunds", "What is your refund policy?"),
    ("no_show", "What happens if I miss my appointment?"),
)

# A hand-built page marks where its FAQ goes with SLOT, inside the section
# that holds it. With nothing to show, the whole section comes out, so a
# visitor never sees a heading over nothing.
SLOT = "<!--solutionist:faq-->"
_SECTION = re.compile(
    r"<!--solutionist:faq-section-->.*?<!--/solutionist:faq-section-->", re.S)


def normalize_question(question: Any) -> str:
    return " ".join(str(question or "").lower().split()).strip("?.! ")


def _clean(item: Any) -> Optional[Dict[str, str]]:
    if not isinstance(item, dict):
        return None
    q = str(item.get("q") or "").strip()[:QUESTION_CHARS]
    a = str(item.get("a") or "").strip()[:ANSWER_CHARS]
    return {"q": q, "a": a} if q and a else None


def _section(settings: Any, name: str) -> Dict[str, Any]:
    value = settings.get(name) if isinstance(settings, dict) else None
    return value if isinstance(value, dict) else {}


def _deduped(items: Iterable[Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        row = _clean(item)
        if row is None:
            continue
        key = normalize_question(row["q"])
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def rows(settings: Any) -> List[Dict[str, str]]:
    """Every saved question and answer, in order."""
    old_list = _section(settings, "concierge").get("faq")
    return _deduped([*(_section(settings, "business_picture").get("faq") or []),
                     *(old_list if isinstance(old_list, list) else [])])[:FAQ_LIMIT]


def public_rows(settings: Any) -> List[Dict[str, str]]:
    """What a website shows: the policies as questions, then the FAQ. An FAQ
    answer to a policy's question wins, because the owner wrote it
    deliberately."""
    policies = _section(settings, "business_picture").get("policies")
    policies = policies if isinstance(policies, dict) else {}
    out: List[Dict[str, str]] = []
    for key, question in POLICY_QUESTIONS:
        answer = str(policies.get(key) or "").strip()
        if answer:
            out.append({"q": question, "a": answer[:ANSWER_CHARS]})
    by_question = {normalize_question(r["q"]): r for r in out}
    for row in rows(settings):
        key = normalize_question(row["q"])
        if key in by_question:
            by_question[key]["a"] = row["a"]
        else:
            by_question[key] = row
            out.append(row)
    return out[:FAQ_LIMIT]


def _store(settings: Dict[str, Any], items: List[Dict[str, str]]) -> None:
    settings["business_picture"] = {**_section(settings, "business_picture"), "faq": items}
    concierge = _section(settings, "concierge")
    if "faq" in concierge:
        settings["concierge"] = {k: v for k, v in concierge.items() if k != "faq"}


def put(settings: Dict[str, Any], question: Any, answer: Any) -> str:
    """Add one answer, or replace the answer to the same question, in
    `settings`. 'added', 'updated', or 'full' with nothing changed: a full
    list refuses rather than dropping an older answer without a word."""
    row = _clean({"q": question, "a": answer})
    if row is None:
        raise ValueError("a question and an answer are both required")
    current = rows(settings)
    key = normalize_question(row["q"])
    for existing in current:
        if normalize_question(existing["q"]) == key:
            existing["a"] = row["a"]
            _store(settings, current)
            return "updated"
    if len(current) >= FAQ_LIMIT:
        return "full"
    _store(settings, [*current, row])
    return "added"


def replace_all(settings: Dict[str, Any], items: Iterable[Any]) -> List[Dict[str, str]]:
    """The Settings screen's save: its list becomes the list, so a row taken
    off there stays off."""
    cleaned = _deduped(items)[:FAQ_LIMIT]
    _store(settings, cleaned)
    return cleaned


def site_shows(site: Any) -> bool:
    """Whether this published website has a place that shows the FAQ. The
    home page's HTML may be absent (Chief's context does not load it); a
    missing page counts as not showing, never the other way round."""
    if not isinstance(site, dict) or site.get("status") != "published":
        return False
    config = site.get("site_config")
    config = config if isinstance(config, dict) else {}
    secondary = config.get("generated_pages")
    secondary = secondary if isinstance(secondary, dict) else {}
    source = config.get("html_source")
    if source == "manual":
        pages = [site.get("html_content"), *secondary.values()]
        return any(isinstance(page, str) and SLOT in page for page in pages)
    if source == "module-composer":
        spec = config.get("page_spec")
        sections = spec.get("sections") if isinstance(spec, dict) else None
        return (any(isinstance(s, dict) and s.get("module") == "faq" for s in sections or [])
                or any(isinstance(page, str) and "sxm-faq" in page for page in secondary.values()))
    return False


def where_it_shows(business: Any, site: Any) -> List[str]:
    """Plain sentences saying where this business's FAQ can be seen. `site`
    is None when it isn't known, and then the website goes unmentioned."""
    import site_concierge
    lines = ["Your FAQ is listed in Settings → Website concierge.",
             "Your website assistant is on and answers visitors from it."
             if site_concierge.is_enabled(business) else
             "Your website assistant is off, so it isn't answering visitors yet."]
    if site is not None:
        lines.append("Your website shows it." if site_shows(site) else
                     "Your website doesn't show an FAQ yet, so visitors won't see it on a page.")
    return lines


def fill_slots(html: str, settings: Any) -> str:
    """Put the FAQ into a hand-built page. `settings` is None when the read
    failed, and then the section comes out the same as when there is nothing
    to show."""
    if not html or SLOT not in html:
        return html
    items = public_rows(settings) if isinstance(settings, dict) else []
    if not items:
        return _SECTION.sub("", html).replace(SLOT, "")
    esc = html_lib.escape
    listed = "\n".join(
        f'<details class="site-faq-item"><summary>{esc(r["q"])}</summary>'
        f'<p>{esc(r["a"])}</p></details>'
        for r in items)
    return html.replace(SLOT, listed, 1)
