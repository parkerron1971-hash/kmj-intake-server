"""church_covenant_text.py — the words of the admin covenant, and the page signed.

Kevin, 2026-11-06: "can we create the covenant agreement for each admin to fill
out", then "align the covenant so when they open the app it would pop up. i
want to use e-signature." The working copy is the Claude Doc he edits
(https://claude.ai/artifact/62V8Qy7qbPRt4Httvp7Mw3); this file is what goes out
to sign, so a change there is a change here, and VERSION moves with it.

HTML, because DocuSeal builds the signing form from it (/submissions/html): the
<text-field>, <checkbox-field>, <date-field> and <signature-field> tags are its
own, and each names the signer (`role`) who fills it. Nothing a person typed
into a login ever reaches this page unescaped.
"""
from __future__ import annotations

from html import escape
from typing import Dict, List, Optional, Tuple

VERSION = "1"
ADMIN, EXEC, SENIOR = "Admin", "Executive Pastor", "Senior Pastor"
ORDER = (ADMIN, EXEC, SENIOR)

# What each office lane is for, in a sentence, on that admin's page.
LANE_LINES: Dict[str, str] = {
    "office_leadership": "You keep the church's week running. You coordinate the team's meetings and deadlines, "
                         "and you all answer to {pastor}.",
    "people_care": "You make sure nobody is missed: guests, care, prayer, families, groups, children and youth.",
    "sunday_serving": "You make sure Sundays and events have the people they need: the schedule, the teams, new "
                      "volunteers and sign-ups.",
    "media_comms": "You carry the message: the order of service, the livestream, sermons, clips, posts, graphics "
                   "and the website.",
}

_STYLE = """
<style>
  body { font-family: Georgia, 'Times New Roman', serif; font-size: 13px; line-height: 1.5; color: #16171c; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 15px 0 5px; break-after: avoid; page-break-after: avoid; }
  h3 { font-size: 13px; margin: 14px 0 4px; break-after: avoid; page-break-after: avoid; }
  ul { margin: 4px 0 8px; padding-left: 18px; }
  li { margin: 2px 0; }
  table { width: 100%; border-collapse: collapse; margin: 6px 0; font-size: 12px; }
  .keep { break-inside: avoid; page-break-inside: avoid; }
  th, td { text-align: left; padding: 5px 6px; border-bottom: 1px solid #d9d4c8; vertical-align: top; }
  th { font-size: 11px; }
  .quote { font-style: italic; }
  .pagebreak { page-break-before: always; }
</style>
"""


def _shared(church: str, pastor: str) -> str:
    """The covenant everyone signs, in the Claude Doc's words."""
    return f"""
<h1>{church} Admin Covenant</h1>

<h2>Why we sign this</h2>
<p>This covenant is a promise between you and {church} about how you will serve in the role the church has given
you. It is a commitment of faith and trust. It does not set pay or hours, and it is not an employment contract.</p>
<p>Admins serve the whole church. You will see people's names, families, prayers, children and schedules, and you
will speak for the church in small ways every day. That is a trust, so we put it in writing and sign it together.</p>
<p class="quote">Moreover it is required in stewards, that a man be found faithful. 1 Corinthians 4:2</p>

<h2>What I promise</h2>
<p>As an admin of {church}, I promise the following before God and this church.</p>
<h3>My walk</h3>
<ul>
  <li>I will keep my own walk with God first, and I will worship and pray with this church.</li>
  <li>I will serve with honesty, humility and a willing spirit, in the building and out of it.</li>
  <li>If something in my life gets in the way of serving well, I will tell {pastor} early.</li>
</ul>
<h3>People's trust</h3>
<p class="quote">A talebearer revealeth secrets: but he that is of a faithful spirit concealeth the matter.
Proverbs 11:13</p>
<ul>
  <li>What I learn about people stays with me. That means prayers, care, family matters and anything shared in
  confidence.</li>
  <li>I will share it only with the people whose role needs it, and only as much as they need.</li>
  <li>If I can see something outside my role, I will leave it alone. Being able to open it does not make it mine
  to read.</li>
  <li>I will not copy, photograph or send church records to my personal phone, email or accounts.</li>
  <li>This promise stays with me after I leave this role.</li>
</ul>
<h3>Children and safety</h3>
<ul>
  <li>I will follow the church's child safety policy, and complete the church's background check on its own
  form.</li>
  <li>If I see or hear that a child is being harmed or is at risk, I will tell {pastor} or the Senior Pastor the
  same day.</li>
  <li>I will report it as the law requires, and I will not look into it myself. In an emergency, I will call 911
  first.</li>
</ul>
<h3>The church's money</h3>
<ul>
  <li>The office files and the treasurer approves. I will not approve or pay anything myself.</li>
  <li>I will follow the money levels in this covenant, even when something feels small or urgent.</li>
  <li>I will not use church money, cards, accounts or supplies for myself.</li>
  <li>The counting team counts, and the treasurer receives the count and makes the deposit. I will stay out of
  that unless I am asked.</li>
</ul>
<h3>My role</h3>
<ul>
  <li>I will do the duties on my page, on time, and say early if I cannot.</li>
  <li>I serve departments. I do not direct them. Each department has its own leader and overseer.</li>
  <li>I will use only my own login and never share it.</li>
  <li>I will check what Chief drafts before it goes out. Anything that leaves the church is mine to check.</li>
</ul>
<div class="keep"><h3>Unity</h3>
<ul>
  <li>I will bring questions and concerns to {pastor} first, and I will send office questions from others to
  {pastor} too.</li>
  <li>If I have a problem with someone, I will go to them first, as Matthew 18:15 teaches.</li>
  <li>I will speak well of this church, its pastors and my team, in person and online.</li>
  <li>If I step down, I will give as much notice as I can, and hand over my work, files, keys and logins.</li>
</ul></div>

<h2>What {church} promises you</h2>
<p>A covenant runs both ways, so the church and its pastors promise you this.</p>
<ul>
  <li>We will pray for you by name.</li>
  <li>We will give you a clear role, a page of duties, and one person to go to: {pastor}.</li>
  <li>We will train you and give you the tools the role needs.</li>
  <li>We will back you in public, and if we need to correct you, we will do it privately and kindly.</li>
  <li>We will protect your family and your rest. You are not asked to carry the whole church.</li>
  <li>We will sit down with you once a year to review this covenant and your role.</li>
</ul>

<h2>How we work together</h2>
<p>The admins answer to {pastor}, the Executive Pastor. The Office &amp; Leadership admin coordinates the team's
meetings and deadlines but is not the other admins' boss. The treasurer answers to the Senior Pastor.</p>
<h3>Levels of yes</h3>
<table>
  <tr><th>Level</th><th>What it means</th><th>When it applies</th></tr>
  <tr><td>1. Just do it</td><td>You decide and do it</td><td>Routine work on your page</td></tr>
  <tr><td>2. Do it, then tell</td><td>You decide, then tell {pastor}</td>
      <td>Something people will notice, or a change to how things usually run</td></tr>
  <tr><td>3. Ask first</td><td>You wait for a yes</td><td>Anything new, sensitive, public or about money</td></tr>
</table>
<p>When you are not sure which level it is, treat it as level 3.</p>
<h3>Money levels</h3>
<table>
  <tr><th>Amount</th><th>Who says yes</th></tr>
  <tr><td>Under $500</td><td>The treasurer</td></tr>
  <tr><td>$500 to $2,500</td><td>The treasurer and the Senior Pastor</td></tr>
  <tr><td>Over $2,500, or past the budget</td><td>The treasurer, the Senior Pastor and a board member</td></tr>
</table>
<h3>Our rhythm</h3>
<table>
  <tr><th>Meeting</th><th>How often</th><th>Who leads it</th></tr>
  <tr><td>Admin huddle</td><td>Every Tuesday</td><td>{pastor}</td></tr>
  <tr><td>Check-in on your role</td><td>Every two weeks</td><td>{pastor}</td></tr>
  <tr><td>All-leaders meeting</td><td>Monthly</td><td>Senior Pastor</td></tr>
  <tr><td>Planning</td><td>Quarterly</td><td>Senior Pastor</td></tr>
</table>

<h2>Keeping it</h2>
<p>The church keeps each signed page in its files, and you keep a copy. We will review it together once a year, or
sooner if your role changes.</p>
"""


_SIZES = {"field": "width: 240px; height: 22px;", "box": "width: 16px; height: 16px; margin-right: 6px;",
          "sig": "width: 200px; height: 44px;", "day": "width: 110px; height: 22px;"}


def _field(tag: str, name: str, role: str, size: str, required: bool = True) -> str:
    """DocuSeal reads a field's box from its own style attribute."""
    need = ' required="true"' if required else ""
    return (f'<{tag} name="{escape(name)}" role="{escape(role)}"{need} '
            f'style="{_SIZES[size]} display: inline-block;"></{tag}>')


def document_html(*, church: str, name: str, lane: str, lane_label: str, duties: List[Tuple[str, str]],
                  pastor: str, exec_name: Optional[str], senior_name: Optional[str]) -> str:
    """One admin's covenant: the shared words, then their own page."""
    c, p, n = escape(church), escape(pastor), escape(name)
    line = escape(LANE_LINES.get(lane, "").format(pastor=pastor))
    rows = "".join(f"<tr><td>{escape(d)}</td><td>{escape(w)}</td></tr>" for d, w in duties)
    details = "".join(
        f"<tr><td>{label}</td><td>{_field('text-field', label, ADMIN, 'field', required)}</td></tr>"
        for label, required in (("Phone", True), ("Email", True), ("Start date in this role", True),
                                ("Emergency contact", True), ("Emergency contact's phone", True)))
    yeses = "".join(
        f"<p>{_field('checkbox-field', text, ADMIN, 'box')}{text}</p>"
        for text in ("I have read the whole covenant and I agree to it.",
                     "I have read my duties and I accept them.",
                     "I will keep what I learn about people in confidence, during this role and after it."))
    signers = [(ADMIN, name), *([(EXEC, exec_name)] if exec_name else []), (SENIOR, senior_name or "")]
    signs = "".join(
        f"<tr><td>{escape(role)}<br>{escape(who)}</td>"
        f"<td>{_field('signature-field', f'{role} signature', role, 'sig')}</td>"
        f"<td>{_field('date-field', f'{role} date', role, 'day')}</td></tr>"
        for role, who in signers)
    return f"""{_STYLE}
{_shared(c, p)}
<div class="pagebreak">
<h1>{n}: covenant page</h1>
<p><b>Role: {escape(lane_label)}.</b> {line}</p>
<h2>Your duties</h2>
<table><tr><th>Duty</th><th>When</th></tr>{rows}</table>
<h2>Your details</h2>
<table><tr><th>Detail</th><th>Your answer</th></tr>{details}</table>
<h2>Your yes</h2>
{yeses}
<div class="keep"><h2>Signatures</h2>
<table><tr><th>Who</th><th>Signature</th><th>Date</th></tr>{signs}</table></div>
</div>
"""
