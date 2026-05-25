"""
legal_content.py — Public-facing legal + help pages for mysolutionist.app.

All content lives here as Python data so we can edit copy + add articles
without touching the routes in public_site.py. Each page is rendered by
wrapping its content in PAGE_SHELL_HTML which matches the existing
landing page styling (Cormorant Garamond + Inter, #0d0d12 bg, gold accent).
"""

from __future__ import annotations
from typing import List, Dict
import datetime
import html as _html

# ──────────────────────────────────────────────────────────────────────
# Editable copy — change these in place; routes pick up automatically.
# ──────────────────────────────────────────────────────────────────────

LAST_UPDATED_DATE = "May 24, 2026"
BUSINESS_NAME = "KMJ Creative Solutions LLC"
BUSINESS_ADDRESS = "[BUSINESS ADDRESS]"   # Placeholder per brief — fill before launch
CONTACT_EMAIL = "kmjcreativesolution@gmail.com"
DOMAIN = "mysolutionist.app"

# ──────────────────────────────────────────────────────────────────────
# Shared HTML shell — matches the landing page (MARKETING_HTML) styling
# so all pages feel like the same site. Keep this in sync if the
# landing page restyles.
# ──────────────────────────────────────────────────────────────────────

PAGE_SHELL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} — The Solutionist System</title>
<meta name="description" content="{description}">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  /* Mirrors the marketing site so legal pages feel like the same product. */
  :root {{
    --bg: #0a0a0e;
    --bg-2: #11111a;
    --surface: rgba(255,255,255,0.04);
    --border: rgba(255,255,255,0.08);
    --text-primary: #fafafa;
    --text-secondary: #d4d4d4;
    --text-muted: #a1a1a1;
    --text-dim: #737373;
    --accent: #7c3aed;
    --info: #06b6d4;
    --glow: rgba(124, 58, 237, 0.35);
    --font-heading: 'Space Grotesk', system-ui, sans-serif;
    --font-body: 'Inter', system-ui, sans-serif;
  }}
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{background:var(--bg);color:var(--text-primary);font-family:var(--font-body);line-height:1.65;-webkit-font-smoothing:antialiased;}}
  a{{color:var(--accent);text-decoration:underline;text-decoration-color:color-mix(in srgb, var(--accent) 50%, transparent);text-underline-offset:3px;transition:text-decoration-color 0.15s;}}
  a:hover{{text-decoration-color:var(--accent);}}
  .nav{{position:sticky;top:0;z-index:50;background:rgba(10,10,14,0.78);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--border);}}
  .nav-inner{{max-width:820px;margin:0 auto;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;}}
  .brand{{font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);letter-spacing:-0.01em;text-decoration:none;}}
  .brand .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));margin-right:9px;box-shadow:0 0 10px var(--glow);}}
  .nav-links{{display:flex;gap:18px;font-size:13px;font-weight:500;}}
  .nav-links a{{color:var(--text-muted);text-decoration:none;transition:color 0.15s;}}
  .nav-links a:hover{{color:var(--text-primary);}}
  .page{{position:relative;padding:64px 24px 32px;}}
  .page::before{{content:'';position:absolute;inset:-40px 0 auto;height:280px;background:radial-gradient(60% 80% at 50% 0%, var(--glow), transparent 70%);pointer-events:none;opacity:0.6;}}
  .wrap{{max-width:820px;margin:0 auto;position:relative;}}
  .badge{{display:inline-flex;align-items:center;gap:8px;padding:5px 14px;font-size:10px;font-weight:700;letter-spacing:2.4px;text-transform:uppercase;color:var(--accent);background:color-mix(in srgb, var(--accent) 12%, transparent);border:1px solid color-mix(in srgb, var(--accent) 28%, transparent);border-radius:99px;margin-bottom:18px;}}
  h1{{font-family:var(--font-heading);font-size:clamp(32px, 5vw, 48px);font-weight:600;line-height:1.1;letter-spacing:-0.015em;color:var(--text-primary);margin-bottom:8px;}}
  h2{{font-family:var(--font-heading);font-size:24px;font-weight:600;color:var(--text-primary);margin-top:38px;margin-bottom:14px;line-height:1.2;letter-spacing:-0.01em;}}
  h2::before{{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));margin-right:10px;vertical-align:middle;transform:translateY(-2px);box-shadow:0 0 8px var(--glow);}}
  h3{{font-family:var(--font-body);font-size:16px;font-weight:600;color:var(--text-primary);margin-top:22px;margin-bottom:6px;}}
  p{{color:var(--text-secondary);margin-bottom:14px;font-size:15px;}}
  p strong{{color:var(--text-primary);font-weight:600;}}
  ul, ol{{padding-left:24px;margin-bottom:14px;color:var(--text-secondary);}}
  ul li, ol li{{margin-bottom:6px;font-size:15px;}}
  ul li strong, ol li strong{{color:var(--text-primary);}}
  .meta{{color:var(--text-dim);font-size:12px;font-style:italic;margin-bottom:24px;display:block;}}
  /* Help center */
  .help-cat{{margin-top:36px;padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:14px;}}
  .help-cat:first-of-type{{margin-top:32px;}}
  .help-cat-name{{font-family:var(--font-heading);font-size:18px;font-weight:600;color:var(--accent);margin-bottom:18px;letter-spacing:-0.01em;}}
  .help-article{{margin-bottom:18px;padding-bottom:16px;border-bottom:1px solid var(--border);}}
  .help-article:last-child{{margin-bottom:0;padding-bottom:0;border-bottom:none;}}
  .help-article-title{{font-weight:600;color:var(--text-primary);margin-bottom:6px;font-size:15px;}}
  .help-article-body{{color:var(--text-secondary);font-size:14.5px;}}
  .help-article-body p{{margin-bottom:0;font-size:14.5px;color:var(--text-secondary);}}
  /* Footer */
  .footer{{background:var(--bg-2);border-top:1px solid var(--border);padding:32px 24px;margin-top:48px;}}
  .footer-inner{{max-width:820px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--text-dim);}}
  .footer-links{{display:flex;flex-wrap:wrap;gap:16px;}}
  .footer-links a{{color:var(--text-muted);text-decoration:none;transition:color 0.15s;}}
  .footer-links a:hover{{color:var(--text-primary);}}
  @media (max-width: 640px) {{
    .page{{padding:40px 20px 24px;}}
    .nav-inner{{flex-direction:column;gap:10px;align-items:flex-start;}}
    .footer-inner{{flex-direction:column;align-items:flex-start;}}
  }}
</style>
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a class="brand" href="/"><span class="dot"></span>The Solutionist System</a>
    <div class="nav-links">
      <a href="/help">Help</a>
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="mailto:{contact_email}">Contact</a>
    </div>
  </div>
</nav>

<div class="page">
  <div class="wrap">
    {content}
  </div>
</div>

<footer class="footer">
  <div class="footer-inner">
    <span>&copy; {year} {business_name}</span>
    <div class="footer-links">
      <a href="/privacy">Privacy</a>
      <a href="/data-deletion">Data Deletion</a>
      <a href="/help">Help</a>
      <a href="/terms">Terms</a>
      <a href="mailto:{contact_email}">Contact</a>
    </div>
  </div>
</footer>

</body>
</html>"""


def render_page(*, title: str, description: str, content_html: str) -> str:
    """Wrap a page body in the shared shell. `content_html` is the
    already-rendered inner markup (headings, paragraphs, lists)."""
    return PAGE_SHELL_HTML.format(
        title=_html.escape(title),
        description=_html.escape(description),
        contact_email=_html.escape(CONTACT_EMAIL),
        business_name=_html.escape(BUSINESS_NAME),
        year=datetime.date.today().year,
        content=content_html,
    )


# ══════════════════════════════════════════════════════════════════════
# PRIVACY POLICY
# ══════════════════════════════════════════════════════════════════════

def render_privacy_html() -> str:
    body = f"""
<span class="badge">Privacy Policy</span>
<h1>Privacy Policy</h1>
<span class="meta">Last updated: {LAST_UPDATED_DATE}</span>

<p>The Solutionist System (&ldquo;the Service,&rdquo; &ldquo;we,&rdquo; &ldquo;us,&rdquo; or &ldquo;our&rdquo;) is operated by
{BUSINESS_NAME}, a limited liability company registered in Michigan,
United States. This Privacy Policy explains what information we collect, how we
use it, and the choices you have. By using the Service, you agree to the practices
described here.</p>

<h2>Who this policy covers</h2>
<p>This policy describes how the Solutionist System handles your information as a user
of our platform. If you use the Service to build a website for your own business,
that website may have its own separate privacy practices for its visitors, which
are your responsibility and are not covered by this policy.</p>

<h2>Information we collect</h2>
<ul>
  <li><strong>Account information</strong> &mdash; the name, email address, and login credentials you
      provide when you create an account.</li>
  <li><strong>Content you create</strong> &mdash; posts, drafts, scheduled content, uploaded images, and
      other material you produce within the Service.</li>
  <li><strong>Connected social account information</strong> &mdash; when you choose to connect a Facebook
      Page or Instagram Business account, we receive, through Meta&rsquo;s official secure
      login (OAuth), a Page access token and basic information about the Page and linked
      Instagram account (such as the Page name and ID). We never receive or store your
      Facebook or Instagram password.</li>
  <li><strong>Usage information</strong> &mdash; basic technical data such as log records needed to operate
      and secure the Service.</li>
</ul>

<h2>How we use your information</h2>
<ul>
  <li>To provide and operate the Service, including saving and organizing your content.</li>
  <li>To publish content to your connected Facebook Page or Instagram account &mdash; but only
      content that you yourself create, schedule, or approve. We never post on your
      behalf without your action.</li>
  <li>To respond to your support requests.</li>
  <li>To maintain the security and integrity of the Service.</li>
</ul>
<p><strong>We do not sell your personal information. We do not use your connected social
account data for advertising, profiling, or any purpose other than publishing the
content you direct us to publish.</strong></p>

<h2>How your information is stored and protected</h2>
<p>Connected social account tokens are stored securely on our servers and are never
exposed to your web browser. We use Supabase for data storage and Railway for
hosting. Access to credentials is restricted to the server systems that need them
to operate the Service.</p>

<h2>Your choices and control</h2>
<ul>
  <li><strong>Disconnect at any time.</strong> You can disconnect any connected Facebook or Instagram
      account from within the Service at <strong>Build &rarr; Integrations &rarr; Social Publishing</strong>.
      Disconnecting immediately deletes the stored access token for that account.</li>
  <li><strong>Delete your data.</strong> You may request deletion of your data at any time. See our
      <a href="/data-deletion">Data Deletion page</a> for instructions.</li>
  <li><strong>Access and correction.</strong> You may contact us to access or correct your account
      information.</li>
</ul>

<h2>Third-party services</h2>
<p>The Service relies on the following third parties, each with its own privacy
practices:</p>
<ul>
  <li><strong>Meta Platforms (Facebook and Instagram)</strong> &mdash; for publishing to connected accounts.</li>
  <li><strong>Supabase</strong> &mdash; for secure data storage.</li>
  <li><strong>Railway</strong> &mdash; for application hosting.</li>
</ul>

<h2>Data retention</h2>
<p>We retain your information for as long as your account is active or as needed to
provide the Service. When you disconnect a social account, its access token is
deleted immediately. When you delete your account or request data deletion, we
remove your associated data as described on our <a href="/data-deletion">Data Deletion page</a>.</p>

<h2>Children&rsquo;s privacy</h2>
<p>The Service is intended for businesses and professionals and is not directed to
individuals under 18. We do not knowingly collect information from children.</p>

<h2>Changes to this policy</h2>
<p>We may update this policy from time to time. Material changes will be reflected by
updating the &ldquo;Last updated&rdquo; date above.</p>

<h2>Contact us</h2>
<p>For any questions about this policy or your data, contact:<br>
{BUSINESS_NAME}<br>
{BUSINESS_ADDRESS}<br>
Email: <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
"""
    return render_page(
        title="Privacy Policy",
        description="How the Solutionist System collects, uses, and protects your information.",
        content_html=body,
    )


# ══════════════════════════════════════════════════════════════════════
# DATA DELETION
# ══════════════════════════════════════════════════════════════════════

def render_data_deletion_html() -> str:
    body = f"""
<span class="badge">Data Deletion</span>
<h1>Data Deletion Instructions</h1>
<span class="meta">Last updated: {LAST_UPDATED_DATE}</span>

<p>You have the right to delete your data from the Solutionist System at any time.
There are two ways to do this:</p>

<h2>Option 1 &mdash; Disconnect within the app (immediate)</h2>
<p>To remove a connected Facebook or Instagram account and delete its stored access
data:</p>
<ol>
  <li>Log in to the Solutionist System.</li>
  <li>Go to <strong>Build &rarr; Integrations &rarr; Social Publishing</strong>.</li>
  <li>Find the connected account and click <strong>Disconnect</strong>.</li>
</ol>
<p>This immediately and permanently deletes the access token and associated connection
data for that account from our systems.</p>

<h2>Option 2 &mdash; Request full data deletion by email</h2>
<p>To request deletion of your entire account and all associated data, email us at
<strong><a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></strong> from the email address associated with your
account, with the subject line &ldquo;Data Deletion Request.&rdquo;</p>
<p>We will process your request and delete your data within 30 days, and confirm by
email once complete.</p>

<h2>What gets deleted</h2>
<p>Deletion removes your account information, the content you created within the
Service, and any stored social account access tokens. Note that content you
previously published to your own Facebook Page or Instagram account lives on those
platforms and must be removed there directly, as we do not control content once it
is published to your accounts.</p>

<h2>Contact</h2>
<p>{BUSINESS_NAME} &mdash; <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
"""
    return render_page(
        title="Data Deletion Instructions",
        description="How to delete your data from the Solutionist System.",
        content_html=body,
    )


# ══════════════════════════════════════════════════════════════════════
# TERMS OF SERVICE
# ══════════════════════════════════════════════════════════════════════

def render_terms_html() -> str:
    body = f"""
<span class="badge">Terms of Service</span>
<h1>Terms of Service</h1>
<span class="meta">Last updated: {LAST_UPDATED_DATE}</span>

<p>These Terms of Service govern your use of the Solutionist System, operated by
{BUSINESS_NAME}. By using the Service, you agree to these terms. A full
version of these terms will be provided here. For questions, contact
<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>

<p><em>(Full Terms of Service to be completed.)</em></p>
"""
    return render_page(
        title="Terms of Service",
        description="Terms governing your use of the Solutionist System.",
        content_html=body,
    )


# ══════════════════════════════════════════════════════════════════════
# HELP CENTER — editable data
# ══════════════════════════════════════════════════════════════════════
# Add articles by appending to this list. Each article has a category
# (which groups it on the page), a title, and a body (HTML allowed in
# the body so we can include links, lists, etc.).

HELP_ARTICLES: List[Dict[str, str]] = [
    # ─── Getting Started ─────────────────────────────────────────
    {
        "category": "Getting Started",
        "title": "Welcome to the Solutionist System",
        "body": (
            "<p>The Solutionist System is your command center for building, growing, and managing "
            "your business online. After you create your account and log in, you&rsquo;ll land on your "
            "dashboard. From here you can build websites, plan and publish content, and connect "
            "your tools. If this is your first time, start by completing your profile in Settings.</p>"
        ),
    },
    {
        "category": "Getting Started",
        "title": "Logging in and account setup",
        "body": (
            "<p>Use the email and password you registered with. If you forget your password, use the "
            "&ldquo;Forgot password&rdquo; link on the login screen. You can update your profile, business "
            "details, and preferences anytime under Settings.</p>"
        ),
    },

    # ─── Connecting Social Accounts ──────────────────────────────
    {
        "category": "Connecting Social Accounts",
        "title": "Connecting your Facebook Page",
        "body": (
            "<p>Go to <strong>Build &rarr; Integrations &rarr; Social Publishing</strong> and click "
            "&ldquo;Connect Facebook.&rdquo; A secure Facebook login window will open. Sign in, choose the Page "
            "you want to connect, and approve the permissions. Your Page will then appear in your connected "
            "accounts list. Note: you must connect a Facebook <strong>Page</strong> (a business/brand page) "
            "&mdash; personal profiles cannot be connected for publishing.</p>"
        ),
    },
    {
        "category": "Connecting Social Accounts",
        "title": "Connecting Instagram",
        "body": (
            "<p>Instagram publishing works through your connected Facebook Page. Your Instagram "
            "account must be a <strong>Business or Creator account</strong> and must be <strong>linked to your "
            "Facebook Page</strong>. Once connected, the integration card will show &ldquo;IG linked.&rdquo; If it "
            "shows &ldquo;no Instagram linked,&rdquo; link your Instagram to your Facebook Page in your "
            "Facebook Page settings, then reconnect.</p>"
        ),
    },
    {
        "category": "Connecting Social Accounts",
        "title": "Troubleshooting: \"No pages found\"",
        "body": (
            "<p>If no Pages appear after connecting, it usually means the Facebook account you logged "
            "in with isn&rsquo;t an admin of any Page, or you didn&rsquo;t grant Page permissions during "
            "login. Make sure you&rsquo;re an admin of at least one Facebook Page and approve all "
            "requested permissions when connecting.</p>"
        ),
    },

    # ─── Publishing Posts ────────────────────────────────────────
    {
        "category": "Publishing Posts",
        "title": "Publishing a post",
        "body": (
            "<p>Go to <strong>Grow &rarr; Content</strong>, create or select a planned post, and click "
            "&ldquo;Publish Now.&rdquo; Your post will appear on your connected Facebook Page within a few seconds, "
            "and the post will be marked as Posted with a link to view it.</p>"
        ),
    },
    {
        "category": "Publishing Posts",
        "title": "Image requirements for Instagram",
        "body": (
            "<p>Instagram posts require an image. When planning a post you want to send to Instagram, "
            "make sure it includes an image and that your connected account has Instagram linked. "
            "Text-only posts can go to Facebook but not Instagram.</p>"
        ),
    },
    {
        "category": "Publishing Posts",
        "title": "Scheduling content",
        "body": (
            "<p>You can plan posts ahead of time from the Content area and publish them when ready.</p>"
        ),
    },

    # ─── Building Websites ───────────────────────────────────────
    {
        "category": "Building Websites",
        "title": "Building your first site",
        "body": (
            "<p>Use the Build tools to create a website for your business. The Solutionist System "
            "guides you through layout, content, and branding. Your generated site is yours &mdash; "
            "remember that any site you publish for your own customers may need its own privacy "
            "policy for its visitors.</p>"
        ),
    },

    # ─── Billing & Account ───────────────────────────────────────
    {
        "category": "Billing & Account",
        "title": "Closing your account",
        "body": (
            f"<p>To close your account and delete your data, see our <a href=\"/data-deletion\">Data Deletion page</a> "
            f"or email <a href=\"mailto:{CONTACT_EMAIL}\">{CONTACT_EMAIL}</a>.</p>"
        ),
    },

    # ─── Contact Support ─────────────────────────────────────────
    {
        "category": "Contact Support",
        "title": "Need more help?",
        "body": (
            f"<p>We&rsquo;re here to help. Email us at <strong><a href=\"mailto:{CONTACT_EMAIL}\">{CONTACT_EMAIL}</a></strong> "
            "and we&rsquo;ll get back to you. Please include your account email and a description of what you need.</p>"
        ),
    },
]


def render_help_html() -> str:
    # Group articles by category in insertion order so the editor controls
    # ordering by just rearranging the list.
    seen_cats: List[str] = []
    by_cat: Dict[str, List[Dict[str, str]]] = {}
    for a in HELP_ARTICLES:
        cat = a.get("category") or "Other"
        if cat not in seen_cats:
            seen_cats.append(cat)
            by_cat[cat] = []
        by_cat[cat].append(a)

    cats_html_parts: List[str] = []
    for cat in seen_cats:
        articles_html = "".join(
            f'<div class="help-article">'
            f'  <div class="help-article-title">{_html.escape(a["title"])}</div>'
            f'  <div class="help-article-body">{a["body"]}</div>'
            f'</div>'
            for a in by_cat[cat]
        )
        cats_html_parts.append(
            f'<section class="help-cat">'
            f'  <div class="help-cat-name">{_html.escape(cat)}</div>'
            f'  {articles_html}'
            f'</section>'
        )
    cats_html = "".join(cats_html_parts)

    body = f"""
<span class="badge">Help Center</span>
<h1>Help &amp; Documentation</h1>
<p>Quick answers for getting set up, connecting your accounts, and publishing.
Can&rsquo;t find what you need? Email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> and we&rsquo;ll help.</p>

{cats_html}
"""
    return render_page(
        title="Help Center",
        description="Guides + answers for the Solutionist System.",
        content_html=body,
    )
