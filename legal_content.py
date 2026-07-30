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

LAST_UPDATED_DATE = "July 4, 2026"
BUSINESS_NAME = "The Solutionist System LLC"
# No public postal address by choice (2026-07-04): Kevin works from home
# and a street address is NOT required on the site — A2P checks the SMS
# language, not addresses (the brand address lives privately in Twilio).
# If a mailing address is ever added (PO Box before email marketing per
# CAN-SPAM), set it here and the contact blocks pick it up automatically.
BUSINESS_ADDRESS = ""
CONTACT_EMAIL = "kmjcreativesolution@gmail.com"
DOMAIN = "mysolutionist.app"


# The web app's home — same value marketing_pages.APP_URL uses.
APP_URL = "https://system.mysolutionist.app"


def _address_line() -> str:
    """Postal address line for contact blocks — empty string when no
    public address is configured (renders nothing, no placeholder)."""
    return f"{BUSINESS_ADDRESS}<br>" if BUSINESS_ADDRESS.strip() else ""

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
<title>{title} &middot; The Solutionist System</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title} — The Solutionist System">
<meta property="og:description" content="{description}">
<meta property="og:image" content="https://mysolutionist.app/assets/og.png?v=2">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  /* Mirrors the marketing site so legal pages feel like the same product.
     KEEP IN SYNC with marketing_pages.SHARED_CSS :root — these four pages
     are rendered here, not by the marketing shell, so a repalette there
     does NOT reach them. (It didn't: they sat on the old violet for a
     full pass.) */
  :root {{
    --bg: #08090C;
    --bg-2: #0E1015;
    --surface: rgba(255,255,255,0.035);
    --border: rgba(255,255,255,0.09);
    --text-primary: #F7F8FA;
    --text-secondary: #C9CDD6;
    --text-muted: #949AA6;
    --text-dim: #6B707B;
    --accent: #2E7DFF;
    --info: #22D3EE;
    --glow: rgba(46, 125, 255, 0.30);
    --font-heading: 'Inter Tight', 'Inter', system-ui, sans-serif;
    --font-body: 'Inter', system-ui, sans-serif;
  }}
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{background:var(--bg);color:var(--text-primary);font-family:var(--font-body);line-height:1.65;-webkit-font-smoothing:antialiased;}}
  a{{color:var(--accent);text-decoration:underline;text-decoration-color:color-mix(in srgb, var(--accent) 50%, transparent);text-underline-offset:3px;transition:text-decoration-color 0.15s;}}
  a:hover{{text-decoration-color:var(--accent);}}
  .nav{{position:sticky;top:0;z-index:50;background:rgba(10,10,14,0.78);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--border);}}
  .nav-inner{{max-width:820px;margin:0 auto;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;}}
  .brand{{font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);letter-spacing:-0.01em;text-decoration:none;display:inline-flex;align-items:center;gap:10px;}}
  .brand .logo{{height:32px;width:auto;display:block;filter:drop-shadow(0 0 8px var(--glow));animation:logoGlow 3s ease-in-out infinite;}}
  @keyframes logoGlow {{
    0%, 100% {{ filter: drop-shadow(0 0 8px var(--glow)); }}
    50%      {{ filter: drop-shadow(0 0 14px var(--glow)) drop-shadow(0 0 4px color-mix(in srgb, var(--info) 60%, transparent)); }}
  }}
  .brand-text{{display:inline-block;}}
  @media (max-width: 540px){{.brand-text{{display:none;}}}}
  .nav-links{{display:flex;gap:18px;font-size:13px;font-weight:500;}}
  .nav-links a{{color:var(--text-muted);text-decoration:none;transition:color 0.15s;}}
  .nav-links a:hover{{color:var(--text-primary);}}
  .nav-links{{align-items:center;}}
  .nav-login{{padding:7px 15px;border:1px solid rgba(255,255,255,0.17);border-radius:8px;
    color:var(--text-primary) !important;font-weight:600;transition:border-color .15s, background .15s;}}
  .nav-login:hover{{border-color:var(--accent);background:var(--surface);}}
  .nav-cta{{padding:8px 16px;background:var(--accent);color:#fff !important;border-radius:8px;
    font-weight:700;box-shadow:0 2px 14px color-mix(in srgb, var(--accent) 30%, transparent);
    transition:background .15s;}}
  .nav-cta:hover{{background:#1D63E6;}}
  @media (max-width: 760px){{.nav-links{{gap:10px;font-size:12px;}}
    .nav-links a:not(.nav-cta):not(.nav-login){{display:none;}}}}
  .page{{position:relative;padding:64px 24px 32px;}}
  .page::before{{content:'';position:absolute;inset:-40px 0 auto;height:280px;background:radial-gradient(60% 80% at 50% 0%, var(--glow), transparent 70%);pointer-events:none;opacity:0.6;}}
  .wrap{{max-width:820px;margin:0 auto;position:relative;}}
  .badge{{display:inline-flex;align-items:center;gap:8px;padding:5px 14px;font-size:10px;font-weight:700;letter-spacing:2.4px;text-transform:uppercase;color:var(--accent);background:color-mix(in srgb, var(--accent) 12%, transparent);border:1px solid color-mix(in srgb, var(--accent) 28%, transparent);border-radius:99px;margin-bottom:18px;}}
  h1{{font-family:var(--font-heading);font-size:clamp(32px, 5vw, 48px);font-weight:700;line-height:1.06;letter-spacing:-0.03em;color:var(--text-primary);margin-bottom:8px;}}
  h2{{font-family:var(--font-heading);font-size:24px;font-weight:700;color:var(--text-primary);margin-top:38px;margin-bottom:14px;line-height:1.2;letter-spacing:-0.025em;}}
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
    <a class="brand" href="/">
      <img class="logo" src="/assets/logo-nav.png" alt="The Solutionist System">
      <span class="brand-text">The Solutionist System</span>
    </a>
    <div class="nav-links">
      <a href="/help">Help</a>
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="mailto:{contact_email}">Contact</a>
      <a class="nav-login" href="{app_url}">Log in</a>
      <a class="nav-cta" href="/get-started">Get Started</a>
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
        app_url=APP_URL,
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
  <li><strong>Account information:</strong> the name, email address, and login credentials you
      provide when you create an account.</li>
  <li><strong>Content you create:</strong> posts, drafts, scheduled content, uploaded images, and
      other material you produce within the Service.</li>
  <li><strong>Connected social account information:</strong> when you choose to connect a Facebook
      Page or Instagram Business account, we receive, through Meta&rsquo;s official secure
      login (OAuth), a Page access token and basic information about the Page and linked
      Instagram account (such as the Page name and ID). We never receive or store your
      Facebook or Instagram password.</li>
  <li><strong>Website analytics (anonymous):</strong> when you browse our public
      marketing site we record the page path, the referring site&rsquo;s domain, a coarse
      device type (mobile, tablet or desktop), and a random session identifier that is
      stored only for the life of the browser tab. We deliberately do <strong>not</strong>
      record your IP address, your browser&rsquo;s user-agent string, or any cookie, and this
      data is never linked to your account. It cannot identify you and is not used to
      track you across other websites. We honour the Do Not Track browser setting.</li>
    <li><strong>Usage information:</strong> basic technical data such as log records needed to operate
      and secure the Service.</li>
</ul>

<h2>How we use your information</h2>
<ul>
  <li>To provide and operate the Service, including saving and organizing your content.</li>
  <li>To publish content to your connected Facebook Page or Instagram account, but only
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

<h2>SMS / Text Messaging</h2>
<p><strong>Consent.</strong> When you opt in to receive SMS messages from the Solutionist
System, we collect and use your mobile number solely to send you the messages you
consented to: booking confirmations, appointment reminders, account notifications,
customer-support replies, and occasional service updates. You may opt in by entering
your mobile number and agreeing to receive texts on our website or booking pages
({DOMAIN}), or by texting a keyword to our number to begin a conversation. Consent to
receive text messages is <strong>not</strong> a condition of any purchase.</p>

<p><strong>No sharing of mobile opt-in data.</strong> We do not sell, rent, or share your
mobile opt-in information or phone number with third parties or affiliates for their
marketing or promotional purposes. Mobile opt-in data is not shared with any third
party except subprocessors (such as our messaging delivery provider) strictly for the
purpose of delivering the messages you requested.</p>

<p><strong>Frequency, rates, and opting out.</strong> Message frequency varies. Message
and data rates may apply. Reply <strong>STOP</strong> to unsubscribe at any time, or
<strong>HELP</strong> for assistance. You can also contact us at
<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> to opt out.</p>

<h2>Third-party services</h2>
<p>The Service relies on the following third parties, each with its own privacy
practices:</p>
<ul>
  <li><strong>Anthropic</strong>: the AI provider that powers Chief and the assistant features. Your business data and the content you ask Chief about (which may include your customers&rsquo; names, messages, and contact details) are sent to Anthropic to generate responses. Anthropic does not train its models on data submitted through its API.</li>
  <li><strong>OpenAI</strong>: used for voice transcription, text-to-speech, and related AI features. Audio and text you send to those features are processed by OpenAI. OpenAI does not train its models on data submitted through its API.</li>
  <li><strong>Meta Platforms (Facebook and Instagram)</strong>: for publishing to connected accounts.</li>
  <li><strong>Supabase</strong>: for secure data storage.</li>
  <li><strong>Railway</strong>: for application hosting.</li>
  <li><strong>Twilio</strong>: for delivering SMS messages you have opted in to receive.</li>
  <li><strong>Stripe</strong>: for payment processing.</li>
  <li><strong>Plaid</strong>: for bank connections you authorize.</li>
</ul>

<h2>How we use AI</h2>
<p>Chief and several features of the Service are powered by third-party AI providers
(Anthropic and OpenAI, listed above). To generate responses, draft messages, and
answer questions, we send relevant portions of your business data, which can
include your customers&rsquo; names, email and message content, and contact details
to those providers. They process this data only to return a result to us and,
per their API terms, do not use it to train their models. AI output can be imperfect;
you remain responsible for reviewing anything sent to your customers.</p>

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
{_address_line()}Email: <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
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

<h2>Option 1: Disconnect within the app (immediate)</h2>
<p>To remove a connected Facebook or Instagram account and delete its stored access
data:</p>
<ol>
  <li>Log in to the Solutionist System.</li>
  <li>Go to <strong>Build &rarr; Integrations &rarr; Social Publishing</strong>.</li>
  <li>Find the connected account and click <strong>Disconnect</strong>.</li>
</ol>
<p>This immediately and permanently deletes the access token and associated connection
data for that account from our systems.</p>

<h2>Option 2: Request full data deletion by email</h2>
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
<p>{BUSINESS_NAME} &middot; <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
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

<p>These Terms of Service (&ldquo;Terms&rdquo;) govern your use of the Solutionist System
(the &ldquo;Service&rdquo;), operated by {BUSINESS_NAME} (&ldquo;we,&rdquo; &ldquo;us,&rdquo;
&ldquo;our&rdquo;). By creating an account or using the Service, you agree to these Terms.
If you do not agree, do not use the Service.</p>

<h2>1. The Service</h2>
<p>The Solutionist System is a business operating platform for solo practitioners and
small studios: contacts, scheduling and bookings, invoicing and payments, bookkeeping,
websites and content tools, goals, and an AI assistant (&ldquo;Chief&rdquo;). Features vary
by subscription tier and may change as the Service evolves.</p>

<h2>2. Accounts and eligibility</h2>
<ul>
  <li>You must be at least 18 years old and using the Service for business purposes.</li>
  <li>You are responsible for your account credentials and for all activity under your
      account. Notify us promptly of any unauthorized use.</li>
  <li>You agree to provide accurate information and keep it current.</li>
</ul>

<h2>3. Subscriptions, fees, and usage</h2>
<ul>
  <li><strong>Plans and pricing.</strong> Paid plans, included usage allotments, and any
      usage-based charges are described at the point of purchase. Fees are billed through
      our payment processor (Stripe) on a recurring basis until you cancel.</li>
  <li><strong>Trials.</strong> Free trials, where offered, convert to paid subscriptions
      at the end of the trial unless you cancel first. When a trial ends or a
      subscription lapses, access to the Service may be suspended until payment resumes;
      your data is retained as described in our <a href="/privacy">Privacy Policy</a>.</li>
  <li><strong>Usage-based charges.</strong> Certain AI features are metered. Where
      overage applies, it is billed at the rates disclosed at purchase, and total monthly
      charges are capped as described there.</li>
  <li><strong>Cancellation.</strong> You may cancel at any time via Settings &rarr;
      Billing; cancellation takes effect at the end of the current billing period.
      Except where required by law, fees already paid are non-refundable.</li>
  <li><strong>Changes.</strong> We may change pricing with reasonable advance notice;
      changes apply from your next billing period.</li>
</ul>

<h2>4. SMS / text messaging terms</h2>
<ul>
  <li><strong>Program.</strong> The Service can send SMS messages such as booking
      confirmations, appointment reminders, account notifications, customer-support
      replies, and occasional service updates.</li>
  <li><strong>Opt-in.</strong> You (or your customers) opt in by providing a mobile
      number and agreeing to receive texts on our website or booking pages, or by
      texting a keyword to our number. Consent is not a condition of any purchase.</li>
  <li><strong>Frequency and rates.</strong> Message frequency varies. Message and data
      rates may apply and are charged by your mobile carrier.</li>
  <li><strong>Opting out.</strong> Reply <strong>STOP</strong> to any message to
      unsubscribe, or <strong>HELP</strong> for assistance. You may also contact us at
      <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</li>
  <li><strong>Carriers.</strong> Mobile carriers are not liable for delayed or
      undelivered messages. You are responsible for notifying us if you change or
      release your mobile number.</li>
  <li>Our handling of mobile numbers and opt-in data is described in the
      <a href="/privacy">Privacy Policy</a>, including our commitment not to share
      mobile opt-in data with third parties for marketing.</li>
</ul>

<h2>5. Your content and data</h2>
<ul>
  <li><strong>Yours stays yours.</strong> You retain all rights to the business data and
      content you put into the Service (contacts, invoices, books, content, sites). You
      grant us only the license needed to operate the Service for you.</li>
  <li><strong>Export.</strong> You can export your data at any time from Settings &rarr;
      Your Data.</li>
  <li><strong>Your responsibilities.</strong> You are responsible for the lawfulness of
      the data you upload, for obtaining any consents your customers&rsquo; data requires
      (including SMS consent where you message your customers), and for how you use
      outputs of the Service in your business.</li>
</ul>

<h2>6. AI features</h2>
<p>Chief and other AI features generate content and suggestions automatically. They can
be wrong. AI output is provided for convenience and does not constitute legal, tax,
accounting, financial, or other professional advice. Review AI-generated content
(including bookkeeping categorizations, drafts, and reports) before relying on it, and
consult a qualified professional where it matters.</p>

<h2>7. Acceptable use</h2>
<p>You agree not to: use the Service to send spam or unlawful, deceptive, or harassing
messages; violate telecom regulations (including TCPA and carrier requirements) when
messaging your customers; attempt to breach, probe, or overload the Service; infringe
others&rsquo; rights; or resell the Service without our written agreement. We may suspend
or terminate accounts that violate these rules or create risk for the platform or other
users.</p>

<h2>8. Third-party services</h2>
<p>The Service integrates third parties (including Stripe, Plaid, Twilio, Meta, Supabase,
and Railway). Your use of those features is also subject to the applicable third
party&rsquo;s terms, and we are not responsible for third-party services.</p>

<h2>9. Availability and changes</h2>
<p>We work hard to keep the Service available, but it is provided &ldquo;as is&rdquo; and
&ldquo;as available&rdquo; without warranties of any kind, express or implied. We may
modify, add, or remove features, and we may suspend the Service for maintenance. During
beta periods, features may change quickly.</p>

<h2>10. Limitation of liability</h2>
<p>To the maximum extent permitted by law, {BUSINESS_NAME} will not be liable for
indirect, incidental, special, consequential, or punitive damages, or for lost profits,
revenue, or data. Our total liability for any claim relating to the Service is limited
to the amounts you paid us in the twelve (12) months before the claim arose.</p>

<h2>11. Indemnification</h2>
<p>You will indemnify and hold us harmless from claims arising out of your content, your
use of the Service in violation of these Terms, or your violation of law,
including telecom and messaging regulations in connection with messages you direct the
Service to send.</p>

<h2>12. Termination</h2>
<p>You may stop using the Service and delete your account at any time (Settings &rarr;
Your Data). We may suspend or terminate the Service for material breach of these Terms.
Sections that by their nature should survive (including 5, 6, 10, and 11) survive
termination.</p>

<h2>13. Governing law</h2>
<p>These Terms are governed by the laws of the State of Michigan, without regard to its
conflict-of-laws rules. Disputes will be resolved in the state or federal courts located
in Michigan, and you consent to their jurisdiction.</p>

<h2>14. Changes to these Terms</h2>
<p>We may update these Terms from time to time. Material changes will be reflected by
updating the &ldquo;Last updated&rdquo; date above and, where appropriate, by additional
notice in the Service. Continued use after changes take effect constitutes acceptance.</p>

<h2>15. Contact</h2>
<p>{BUSINESS_NAME}<br>
{_address_line()}Email: <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>
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
            "Personal profiles cannot be connected for publishing.</p>"
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
            "guides you through layout, content, and branding. Your generated site is yours. "
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


def render_sms_page_html() -> str:
    """Public SMS opt-in page (/sms) — the A2P CTA fix (2026-07-04).

    The campaign was rejected because reviewers could not publicly see
    the opt-in mechanism (it lived behind the app login). This page IS
    the verifiable CTA: a real, working form with a mobile field, an
    UNCHECKED optional consent checkbox, the full disclosure beside it,
    links to Privacy + Terms, and a description of the keyword path.
    POSTs to /api/sms/opt-in (sms_routing.py) which records the consent
    audit row in sms_consents."""
    body = f"""
<span class="badge">Text Messaging</span>
<h1>Get texts from The Solutionist System</h1>
<span class="meta">Booking confirmations, appointment reminders, and account updates, straight to your phone.</span>

<p>The Solutionist System sends SMS messages such as booking confirmations, appointment
reminders, account notifications, and customer-support replies on behalf of the
businesses that use our platform. You can sign up here, or by texting a
business&rsquo;s keyword to our number.</p>

<h2>Sign up for texts</h2>
<form id="sms-optin-form" style="max-width:480px;margin-top:14px;">
  <label for="sms-name" style="display:block;font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">Name (optional)</label>
  <input id="sms-name" name="name" type="text" autocomplete="name" placeholder="Your name"
         style="width:100%;padding:11px 14px;margin-bottom:14px;border-radius:10px;border:1px solid var(--border);background:var(--surface);color:var(--text-primary);font-family:inherit;font-size:14px;outline:none;">
  <label for="sms-phone" style="display:block;font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">Mobile number</label>
  <input id="sms-phone" name="phone" type="tel" autocomplete="tel" required placeholder="+1 555 123 4567"
         style="width:100%;padding:11px 14px;margin-bottom:14px;border-radius:10px;border:1px solid var(--border);background:var(--surface);color:var(--text-primary);font-family:inherit;font-size:14px;outline:none;">
  <label style="display:flex;gap:10px;align-items:flex-start;font-size:13px;color:var(--text-secondary);line-height:1.6;cursor:pointer;">
    <input id="sms-consent" name="consent" type="checkbox" style="margin-top:3px;flex-shrink:0;">
    <span>By checking this box, I agree to receive recurring SMS messages from
    <strong style="color:var(--text-primary);">The Solutionist System</strong> (booking confirmations,
    appointment reminders, account notifications, and support replies). Consent is not a
    condition of any purchase. Message frequency varies. Message and data rates may apply.
    Reply <strong>STOP</strong> to opt out at any time, or <strong>HELP</strong> for help.
    See our <a href="/privacy">Privacy Policy</a> and <a href="/terms">Terms of Service</a>.</span>
  </label>
  <button id="sms-submit" type="submit" disabled
          style="margin-top:16px;padding:12px 26px;border-radius:11px;border:0;cursor:pointer;font-family:inherit;font-size:14px;font-weight:700;color:#fff;background:var(--accent);opacity:.5;">
    Sign up for texts
  </button>
  <div id="sms-msg" style="margin-top:12px;font-size:13px;"></div>
</form>

<h2>What you&rsquo;ll receive when you sign up</h2>
<p>After you opt in, we send one confirmation message. It looks exactly like this:</p>
<div style="margin:10px 0 4px;padding:13px 16px;border-radius:14px;border:1px solid var(--line);background:var(--panel);font-size:13.5px;line-height:1.55;max-width:430px;">
  Solutionist System: You&rsquo;re now connected with [Business Name]. Msg frequency varies.
  Msg &amp; data rates may apply. Reply HELP for help, STOP to opt out.
</div>
<p style="font-size:12.5px;">Ongoing messages are things like booking confirmations, appointment
reminders, account notifications, and replies to your questions. Reply <strong>STOP</strong> at any
time and messaging ends immediately; reply <strong>HELP</strong> for help.</p>

<h2>Or text a keyword</h2>
<p>Each business on our platform has its own keyword. Text that keyword to our number and
you&rsquo;ll be connected with them. Texting the keyword is your opt-in, and we&rsquo;ll
confirm with the same message shown above.</p>

<h2>The fine print</h2>
<ul>
  <li>Message frequency varies. Message and data rates may apply.</li>
  <li>Reply <strong>STOP</strong> to cancel at any time; reply <strong>HELP</strong> for help,
      or email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</li>
  <li>We never sell, rent, or share your mobile opt-in information. Details are in our
      <a href="/privacy">Privacy Policy</a>.</li>
  <li>Carriers are not liable for delayed or undelivered messages.</li>
</ul>

<script>
(function() {{
  var box = document.getElementById('sms-consent');
  var btn = document.getElementById('sms-submit');
  var msg = document.getElementById('sms-msg');
  box.addEventListener('change', function() {{
    btn.disabled = !box.checked;
    btn.style.opacity = box.checked ? '1' : '.5';
  }});
  document.getElementById('sms-optin-form').addEventListener('submit', function(e) {{
    e.preventDefault();
    if (!box.checked) return;
    btn.disabled = true; btn.textContent = 'Signing up…';
    fetch('/api/sms/opt-in', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{
        phone: document.getElementById('sms-phone').value,
        name: document.getElementById('sms-name').value,
        consent: true
      }})
    }}).then(function(r) {{ return r.json().then(function(j) {{ return {{ ok: r.ok, j: j }}; }}); }})
      .then(function(res) {{
        if (res.ok) {{
          msg.style.color = 'var(--info)';
          msg.textContent = "You're signed up. Watch for a confirmation once messaging goes live — reply STOP anytime to opt out.";
          btn.textContent = 'Signed up ✓';
        }} else {{
          msg.style.color = '#f87171';
          msg.textContent = (res.j && res.j.error) || 'Something went wrong — try again.';
          btn.disabled = false; btn.textContent = 'Sign up for texts';
        }}
      }})
      .catch(function() {{
        msg.style.color = '#f87171';
        msg.textContent = 'Network error — try again.';
        btn.disabled = false; btn.textContent = 'Sign up for texts';
      }});
  }});
}})();
</script>
"""
    return render_page(
        title="Text Messaging",
        description="Sign up for SMS updates from The Solutionist System — booking confirmations, reminders, and account notifications.",
        content_html=body,
    )


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
