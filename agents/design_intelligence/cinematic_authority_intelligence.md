# The Solutionist Design System — Embrace the Shift Case Study

## How This Site Was Designed: A Complete Design Intelligence Document

This document captures every design decision, philosophy, pattern, animation, spacing rule, and implementation detail that went into building the Embrace the Shift website (embracetheshift.live). This is not a style guide — it's a design brain. Use it to replicate this level of quality on any future site, and to teach the Solutionist System how to think about premium web design.

---

## 0. HOW THE DESIGN CAME TO BE — The Origin Story

### It Started With a Question, Not a Mockup

The Embrace the Shift website didn't start as a design project. It started as a deployment question — "How do I get a landing page live so pastors can inquire about the course?" The first version was purely functional: a form that wrote to Supabase, connected to a Railway agent that scored leads. Navy and gold colors were chosen early because they matched Kevin's brand DNA — KMJ Creative Solutions already used navy (#0A1628) and gold (#C6952F) as brand colors. The design had to feel like it belonged in his ecosystem.

### Version 1 — The Clean Start (Cormorant Garamond + DM Sans)

The first landing page used Cormorant Garamond (a refined serif) and DM Sans (a clean geometric sans). The palette was navy background with white text, gold accents. It was elegant but quiet — thin font weights, centered layouts, standard section padding. It looked good. But it didn't feel like a statement. It felt like a template with better colors.

The initial design had:
- Centered hero with no imagery
- Standard card layouts with thin borders
- Modest font sizes (44-48px headings)
- Subtle hover effects
- A serviceable inquiry form

It worked. But "works" isn't the bar.

### The Turning Point — "Upgrade the Design"

Kevin looked at the live site and said: **"I want to upgrade the design. Make it look more better."** That single request triggered the entire design evolution. But "more better" is vague — it could mean anything. So instead of guessing, we asked diagnostic questions:

**"What feels like it's missing?"**
Kevin selected ALL options: more visual depth, more animation, images (headshot + book cover), and bolder typography. He didn't want one thing improved — he wanted the entire energy elevated.

**"What vibe are you going for?"**
He liked both "high-end masterclass" and "Apple product pages" but also wanted "something unexpected." This was the critical insight — he didn't want to copy a known style. He wanted to be surprised by something that felt original but still premium.

**"Do you have photos?"**
Yes — headshot and book cover. This unlocked the split-screen hero concept. Before photos, centered text was the only option. With photos, we could create a layout with narrative tension: the person on one side, their words on the other.

### Version 2 — The Dark Cinematic Approach

Based on those answers, the redesign went full dark mode:
- Background: #08090C (near-black)
- Fonts switched to **Playfair Display + Outfit** — heavier, more editorial
- Split-screen hero with headshot on the right in a gold-framed glass panel
- Film grain overlay for texture
- Floating gold diamond decorations
- Scroll-triggered reveal animations with custom cubic-bezier easing
- Shimmer animation on the gold CTA button

This version was dramatic. It felt like a movie poster or a luxury watch site. The cinematic depth was there — radial glows, grain, parallax-like reveals. But it was TOO dark. The entire page was variations of black and dark gray with gold accents. It felt like a nightclub, not a financial education platform.

### Version 3 — "Navy, White, and Gold. More Bold."

Kevin's feedback was direct: **"Do some more adjusting. I want a more bold feel with the colors navy blue, white, and gold."** This was the breakthrough direction. He didn't want dark cinematic — he wanted BOLD. Three specific colors. High contrast. Confidence.

This triggered the key design decisions:

1. **Alternating section backgrounds** — instead of everything being dark, sections alternate between navy and white/off-white. This creates a visual rhythm and lets each section have its own identity.

2. **Full-bleed gold band** — the stats section became a solid gold gradient strip spanning the full page width. This was the boldest move — an entire section that's pure gold. It separates the hero from the content and demands attention.

3. **Font weight went to 900** — headings jumped from 400-600 weight to 800-900. The typography stopped whispering and started declaring.

4. **Contrasting package cards** — Foundations got a navy card, Mastery got a white card with gold border. They're not twins anymore — they're distinct choices.

5. **The gold CTA section** — the final call to action became a full gold gradient section, not just a button on navy. The entire bottom of the page glows gold.

### Version 4 — Claude Code's Enhancement (The Bold Enhanced)

Kevin took the bold version and ran it through Claude Code for refinement. Claude Code added several smart touches:

1. **28px border-radius everywhere** — all cards, buttons became pills (999px radius). This was the single biggest visual upgrade. It shifted the feel from "serious editorial" to "premium modern app."

2. **Active nav indicator** — useActiveSection hook that tracks scroll position and highlights the current section in the nav. Smart UX.

3. **Hero metric chips** — small info cards below the hero CTAs showing "Live Teaching", "Practical Format", etc. Added information density without clutter.

4. **Glass-morphism headshot panel** — the photo frame got backdrop-filter blur, rounded corners, and a floating name tag with gradient overlay.

5. **clamp() typography** — heading sizes use CSS clamp() for smooth responsive scaling instead of hard breakpoints.

6. **Topic pills in the About section** — 4 rounded cards listing core topics, giving a scannable preview of the curriculum.

This version became the foundation. Kevin said: **"This is good."**

### The Content Expansion — From 1 Page to 4 Pages

The design was locked, but the content grew. Kevin uploaded a full HTML file with 4 pages of content — Home, Programs, Subscribe, Organizations — with sections for pain points, economic reality, testimonials, membership tiers, mentorship, comparison tables, and FAQs. This was the full Embrace the Shift ecosystem, not just the course booking site.

The challenge: apply the established design system to 4x the content without every page feeling the same. The solution was:
- Each page has a unique hero subtitle and tone
- Section types vary per page (journey ladder on Programs, pain points on Home, subscription cards on Subscribe)
- The shared Nav and Footer tie them together visually
- The alternating navy/white/cream/gold rhythm adapts per page

### The Micro-Decisions That Shaped Everything

Throughout the build, small conversations shaped big outcomes:

**Stats band content:** The original stats were "200+ / 2 / 6-10 / ∞" — standard credibility numbers. Kevin pushed back: "I don't lead 200 churches, I'm just a part of it." Rather than inflating numbers, we went with **purposeful words**: "Prepared / Grounded / Empowered / Positioned." Each word is a transformation, not a metric. Then Kevin refined further: "Scripture" was too narrow for a broad audience, so "In Wisdom and Strategy" replaced "In Scripture and Strategy." Then the font size came down from 54px to 36px because words are wider than numbers. Every detail was a conversation.

**The italic gold word:** This pattern emerged organically. The first heading was "Embrace the _Shift_" with "Shift" in italic gold. It looked so good that it became the rule: every section heading gets one italic gold word that captures the emotional core. "A _transformation._" "Who this is _for._" "Choose your _path._" "How it _works._" This created visual consistency across dozens of headings without a formal decision — it just felt right and became the standard.

**The diamond shape:** The rotated square appeared first as the nav logo — a simple 12px gold square rotated 45 degrees. Then it became the favicon. Then bullet points in lists. Then floating decorations in navy sections. Then the brand mark on the footer. One small design choice proliferated into the brand's visual identity.

**The easing curve:** `cubic-bezier(0.16, 1, 0.3, 1)` was chosen for its feel — it starts fast and decelerates gracefully, like a luxury car braking. The standard `ease` or `ease-out` felt generic. This custom curve was applied to every transition in the system, creating a unified motion language.

**The 0.018 opacity grain:** The film grain started at 0.03 — too visible, looked like a filter. Dropped to 0.01 — too subtle, pointless. 0.018 was the sweet spot: you can't see it, but removing it makes the page feel "too clean." It's subliminal texture.

### Kevin's Inputs — What He Said and Showed, and What It Changed

Every major design decision traces back to something Kevin said, chose, or showed. This is the evidence trail:

---

**Input: "lets' work on landing page and stuff.."**
What it triggered: The entire web build. Before this, we only had a Railway agent processing inquiries from manual Supabase inserts. This kicked off the first Vite + React app with two routes — landing page and inquiry form.

---

**Input: Kevin selected ALL four options when asked what's missing — "More visual depth, More animation, Add images, Bolder typography"**
What it triggered: This told us the entire energy needed to elevate, not just one element. If he'd picked only "add images," we would have dropped photos into the existing design. Selecting everything meant a ground-up redesign was justified. It gave permission to go big.

---

**Input: Kevin liked both "High-end masterclass" and "Bold and modern (Apple)" but chose "Show me something unexpected"**
What it triggered: This prevented us from copying a known style. Instead of cloning MasterClass.com's dark layout or Apple's minimalist white, we had to create a hybrid that felt original. The result was the split-screen hero with editorial typography and cinematic depth — a combination that doesn't map to any single reference site.

---

**Input: "Yes — I have a headshot and book cover"**
What it triggered: The split-screen hero layout. Without photos, the hero would have stayed centered text on a gradient — generic. The headshot enabled the left-text/right-image split, the gold-framed glass panel treatment, and the name plate overlay. The book cover enabled the asymmetric About section with the navy shadow offset. Two images unlocked two of the most distinctive sections on the site.

---

**Input: "do some more adjusting want design to have more bold feel to it with the colors navy blue white and gold."**
What it triggered: This was the most important single input. It killed the dark cinematic direction (#08090C near-black) and established the final palette. Three specific colors named. "Bold" as the adjective. This directly caused:
- The alternating navy/white section rhythm (instead of all-dark)
- The full-bleed gold stats band
- Font weight jumping from 400-600 to 800-900
- The gold CTA section at the bottom
- The contrasting package cards (navy vs white with gold border)
- The gold top accent line on navy sections

Without this input, the site would have stayed in the moody dark direction. Kevin's color instinct was right — his brand DNA is navy and gold, and the design needed to honor that loudly, not subtly.

---

**Input: Kevin uploaded `LandingPage-bold-enhanced.jsx` from Claude Code and said "this is good"**
What it triggered: This locked in the 28px border-radius, pill-shaped buttons (999px radius), clamp() typography, active nav detection, hero metric chips, glass-morphism headshot panel, and topic pills. By approving this version, it became the foundation everything else was built on. The design system document codifies this version's choices as the standard.

---

**Input: "we have to upgrade the other page as well"**
What it triggered: The InquiryForm redesign. Kevin recognized that having a premium landing page and a basic form would break the experience. This forced the form page to inherit the entire design system — navy hero, rounded cards, gold focus rings on inputs, pill buttons, matching footer. Consistency wasn't optional.

---

**Input: Kevin uploaded `embracetheshift-final__3_.html` — a full 4-page HTML site**
What it triggered: The scope expansion from a 1-page site to a 4-page multi-route application. This upload contained content for Home, Programs, Subscribe, and Organizations — including membership tiers, mentorship details, pain points, economic pillars, testimonials, comparison tables, and FAQs. The design system had to scale to 4x the content while maintaining visual coherence. It also revealed that Embrace the Shift wasn't just a course booking site — it was a full ecosystem (subscriptions, mentorship, community, organizations).

---

**Input: "this layout design is what i like but i love how the design feel we have made. so much most of this upload but make the sections in the upload same size font image sizes etc as big as the design we have already. make sense?"**
What it triggered: The full site rebuild spec. This was a precise instruction: take the CONTENT and STRUCTURE from the uploaded HTML, but apply the VISUAL LANGUAGE of the bold enhanced design (big fonts, 900 weight, 28px radius, navy/gold/white, animations). It's the difference between "rebuild from scratch" and "reskin with our system." Kevin wanted the information architecture from his HTML but the design quality from our React build.

---

**Input: "I KEEP SEEING U2014 SHOWING UP"**
What it triggered: A global Unicode escape fix across all JSX files. This was a quality control catch — Kevin spotted rendering artifacts that were easy to miss in development. It showed attention to detail and set the standard that no technical artifacts should be visible to the end user.

---

**Input: "i want to pick better words that we just replace. give me a thoughtful option" (about the stats band)**
What it triggered: The shift from numbers to purposeful words. Kevin rejected the original stats (200+, 2, 6-10, ∞) not because they were wrong, but because they didn't carry meaning. He pushed for words with weight. This led to three rounds of options before landing on "Prepared / Grounded / Empowered / Positioned" — four words that function as a thesis statement for the entire brand.

---

**Input: "what about purposeful words"**
What it triggered: This specific phrase redirected the stats conversation from metrics and features to declarations and identity. "Purposeful" was the keyword — not clever, not catchy, but purposeful. Words that mean something. This influenced the final selection heavily — every option after this was filtered through "does this carry purpose?"

---

**Input: "option c is good. and i just want to take about the scripture word"**
What it triggered: The replacement of "In Scripture and Strategy" with "In Wisdom and Strategy." Kevin recognized that "Scripture" would limit the audience to church contexts, but the program serves nonprofits, corporate teams, youth programs, and Greek orgs too. "Wisdom" keeps the spiritual thread without naming it — a pastor reads wisdom and thinks biblical, a corporate leader reads wisdom and thinks experience. Both are right. This was a branding decision disguised as a word swap.

---

**Input: "words need to have better even spaces and the prepared grounded empowered and positioned, need to be a little smaller words. not to small though"**
What it triggered: Font size reduction from 48-54px to 36px and grid layout enforcement (repeat(4, 1fr)) for even spacing. Kevin's eye caught that words behave differently than numbers at large sizes — "Prepared" at 54px is much wider than "200+" at 54px. The sizing had to account for word length, not just visual impact. "Not too small though" set the floor — 36px was the sweet spot between commanding and proportional.

---

**Input: "mostly everything is aligned in mobile view some things is still not properly aligned"**
What it triggered: A full mobile audit prompt. Kevin tested on his actual phone and caught alignment issues that desktop development missed. This input established that mobile wasn't an afterthought — if it doesn't look right on a phone, it's not done.

---

**Input: "can you add a return point just in case?"**
What it triggered: The git backup branch pattern. Kevin wanted safety before any batch of changes — a one-line rollback. This became standard practice for every subsequent prompt: commit, branch, make changes, commit again. It showed an engineering mindset about protecting working code.

---

**Input: "i want to develop a registration page... I want to setup a way to receive paid registration"**
What it triggered: The entire events system — Supabase schema (4 tables), Studio events management (3 pages), website registration flow (3 routes), Stripe integration, and email confirmations via Resend. What started as "I want a registration page" became a full event engine because Kevin's follow-up answers revealed he wanted flexibility: any event type (live/virtual/hybrid), any pricing structure (free/paid/tiered), and management through Studio.

---

**Input: "which is best?" (when asked how to manage events)**
What it triggered: The "start simple, upgrade later" architecture decision. Instead of building a full admin interface, we started with Supabase for data entry and built toward Studio management. Kevin's willingness to ask "which is best?" rather than dictating a solution allowed us to choose the fastest path to working software.

---

**Input: "if i already have registration setup in solutionist studio, can claude code do it and it doesn't take days to build?"**
What it triggered: The audit prompt. Instead of guessing what existed in Studio, we had Claude Code investigate and report back. Kevin's instinct was right — there was existing Stripe infrastructure, existing module patterns, and existing real-time subscriptions that could be extended rather than rebuilt. This saved significant development time.

---

**Input: "shouldn't the bucket list be named ets_event-files not event-assets?"**
What it triggered: Naming consistency enforcement. Kevin caught that the storage bucket name didn't match the naming convention of everything else in the system (all ETS-related items use the `ets_` prefix). This maintained system coherence — when you see `ets_` you know it belongs to Embrace the Shift.

---

**Input: "i need to have it where after someone pay the return site should be back to embracetheshift.live confirmation page"**
What it triggered: The Stripe return URL fix across the entire codebase. Kevin identified that the payment flow was broken because Stripe was redirecting to the wrong domain after checkout. This exposed that the VITE_SITE_URL variable needed to be set correctly and that all payment link generation in Studio needed to reference the production domain.

---

**Input: "how can emails get sent out as well?"**
What it triggered: The entire Resend email integration on Railway — confirmation emails sent automatically from register@embracetheshift.live when someone registers for an event.

---

**Input: "how to setup for it to be different emails like register@"**
What it triggered: The explanation of domain-verified email addresses with Resend. Kevin didn't just want emails to send — he wanted them to come from the right address. `register@embracetheshift.live` for event confirmations, not a generic `noreply@resend.dev`. This is brand detail — the from address matters.

---

**Input: "do me a favor. i need you to give me a prompt sharing how you design this site. all that went into this design... DO NOT LEAVE DETAILS out."**
What it triggered: This entire design system document. Kevin recognized that the design knowledge lived only in conversation history — if it wasn't captured, it would be lost. The instruction to leave nothing out ensured completeness. The stated purpose — "so the system knows how to wire this into the solutionist system" — revealed the long-term vision: this design intelligence should be teachable to the Solutionist platform so it can produce this quality for any client.

---

**Input: "did you share how the idea came about when it came to the design?"**
What it triggered: Section 0 of this document — the origin story. Kevin recognized that knowing WHAT was built isn't enough without knowing HOW and WHY it evolved. The process matters as much as the output.

---

**Input: This question — "now, in this chat, what did i say or show that influenced your decisions in the design?"**
What it triggered: This subsection. Kevin is documenting not just the design system, but the design COLLABORATION — the specific moments where his input changed the direction. This is the most sophisticated design thinking in the entire project: understanding that great design isn't one person's vision imposed, it's a conversation where the client's instincts and the designer's craft meet. Every entry above is proof that Kevin wasn't a passive client receiving deliverables. He was a co-designer whose words, choices, uploads, and corrections shaped every pixel.

---

### The Pattern of Kevin's Design Influence

Looking across all these inputs, Kevin's design influence follows a consistent pattern:

1. **He knows what he wants emotionally but not technically** — "more bold," "purposeful words," "make it look more better." These are feeling-level instructions that require translation into design decisions.

2. **He catches inconsistencies** — Unicode characters, misaligned mobile elements, wrong bucket names, wrong return URLs. His quality standard is: if anything feels off, it's not done.

3. **He thinks in systems, not pages** — "we have to upgrade the other page as well," "shouldn't the bucket name match everything else?" He sees the whole ecosystem, not isolated components.

4. **He protects his brand truth** — rejecting "200 churches" because it wasn't accurate, changing "Scripture" to "Wisdom" because it was too narrow, choosing navy/gold/white because those are his colors. He never compromised brand integrity for visual impact.

5. **He pushes for better without knowing the solution** — "what about purposeful words," "show me something unexpected." He sets the bar higher and trusts the process to find the answer.

6. **He builds safety nets** — "can you add a return point just in case?" He moves fast but protects his work.

This collaboration pattern is the ideal client-designer dynamic. The Solutionist System should be designed to facilitate this exact kind of exchange: emotional direction from the client, technical translation from the system, iterative refinement through conversation, and quality enforcement from both sides.

1. **Start functional** — get it working first, design second
2. **Ask diagnostic questions** — don't guess what "better" means, find out what's missing
3. **Go extreme first** — the dark cinematic version was too much, but it revealed what worked (animations, depth, typography)
4. **Pull back to the brand truth** — Kevin's instinct for navy/white/gold was right. The palette was in his DNA already.
5. **Let the content shape the layout** — the split-screen hero only became possible when photos were available. The 4-page structure only emerged when the full content scope was clear.
6. **Refine through conversation** — stats content, word choices, font sizes, section order — all evolved through back-and-forth, not a single design brief.
7. **Codify what works** — once patterns emerged (italic gold word, 28px radius, gold line before headings), they became rules applied everywhere.

This process is the Solutionist Design Process. It works for any client, any brand, any industry. Start functional. Ask questions. Go extreme. Pull back to truth. Refine through conversation. Codify the patterns.

---

## 1. DESIGN PHILOSOPHY

### The Core Principle: Cinematic Authority
The site was designed to feel like a **MasterClass meets Apple product page** — cinematic depth, editorial typography, and luxury-level polish applied to a financial education brand. Every section should feel like a frame from a documentary, not a template from a website builder.

### Three Pillars of the Design

**1. Bold Without Shouting**
The design uses extreme font weights (900), large type scales (76px hero), and full-bleed color sections — but never feels aggressive. The restraint comes from generous whitespace, muted secondary text, and slow reveal animations. Bold is about confidence, not volume.

**2. Rhythm Through Contrast**
Pages alternate between dark (navy) and light (white/cream/off-white) sections. This creates a visual rhythm — like chapters in a book. Each section has a distinct identity but belongs to the same story. The gold stats band and gold CTA band act as "punctuation marks" between chapters.

**3. Depth Over Flatness**
Every element has layers: film grain overlay, floating diamond decorations, radial gradient glows, parallax-like scroll animations, hover state transformations, glass-morphism nav bars. Nothing sits flat on the page. The eye always has something subtle to discover.

### The Emotional Progression
The site is designed to take the visitor through an emotional journey:
- **Hero**: Authority + intrigue ("This person knows something I don't")
- **Stats**: Credibility + scale ("This is real and established")
- **About**: Trust + connection ("I like this person and their story")
- **Who It's For**: Belonging ("This was made for people like me")
- **Packages**: Clarity + desire ("I know exactly what I get")
- **How It Works**: Ease ("This is simpler than I thought")
- **CTA**: Urgency + safety ("I should act, and there's no risk")

Every design choice serves this progression. Nothing is decorative for decoration's sake.

---

## 2. COLOR SYSTEM

### Primary Palette

```css
--navy: #0A1628;        /* Primary dark — backgrounds, headings on light */
--navy-mid: #122040;    /* Cards on dark backgrounds */
--navy-light: #1B3060;  /* Hover states, lighter dark elements */
--navy-bright: #243D6B; /* Subtle accents */
```

Navy is the authority color. It's not black — it's a deep, warm blue that has life in it. Pure black feels dead on screen. Navy feels intentional.

```css
--gold: #C6952F;        /* Primary accent — CTAs, highlights, accents */
--gold-light: #DCAD4A;  /* Lighter gold for gradients, text on dark */
--gold-pale: #F0D590;   /* Very light gold for subtle accents */
--gold-glow: rgba(198,149,47,0.14); /* Glow effects behind elements */
```

Gold is the signal color. It says "this matters" — every gold element is either a call to action, a highlight, or a marker of importance. Gold is never used for body text or structural elements. It's reserved for moments of significance.

```css
--white: #FFFFFF;       /* Card backgrounds, text on dark */
--off-white: #F8F6F1;  /* Section backgrounds — warmer than pure white */
--cream: #EDE8DC;       /* Alternate section backgrounds, borders */
```

The whites are warm, not clinical. `#F8F6F1` has a slight warmth that makes the page feel like premium paper, not a spreadsheet. This is critical — cold whites kill luxury.

### Text Colors (Context-Dependent)

```css
/* On dark (navy) backgrounds: */
--text-on-dark: #F4F0E8;    /* Primary text — warm white, not pure white */
--text-on-dark2: #B0A99C;   /* Secondary text — descriptions, subtitles */

/* On light (white/cream) backgrounds: */
--text-on-light: #0A1628;   /* Primary text — full navy */
--text-on-light2: #4A5068;  /* Secondary text — softer navy */
--text-muted: #8890A4;      /* Tertiary — labels, captions, fine print */
```

### Signal Colors

```css
--green: #6BBF59;           /* Confirmed, success, virtual events */
--green-light: #8DD47A;     /* Lighter green for badges */
--red: rgba(220,80,80,0.6); /* Alerts, warnings, "what you're told" */
```

### How Colors Are Applied to Sections

The page follows a strict alternating pattern:

1. **Navy section** — hero, "who it's for", "how it works"
```css
   background: linear-gradient(170deg, var(--navy) 0%, #06101E 50%, var(--navy) 100%);
```
   Text is warm white/gold. Cards use `rgba(255,255,255,0.04)` borders.

2. **White section** — about, add-ons
```css
   background: var(--white);
```
   Text is navy. Cards use `var(--cream)` borders.

3. **Off-white section** — packages, testimonials, FAQ
```css
   background: var(--off-white);
```
   Text is navy. Slightly warmer feel than pure white.

4. **Cream section** — "who it's for" (alternate)
```css
   background: #EDE8DC;
```
   Warm, inviting. Used sparingly.

5. **Gold band** — stats, final CTA
```css
   background: linear-gradient(135deg, var(--gold), var(--gold-light));
```
   Text is navy. Creates a visual "break" that demands attention.

### Gradient Usage

Gradients are never just decorative — they create depth:

```css
/* Navy hero radial glow — creates a "light source" feel */
radial-gradient(ellipse 50% 60% at 70% 30%, rgba(27,48,96,0.6) 0%, transparent 60%)

/* Gold subtle glow — draws eye without overwhelming */
radial-gradient(ellipse 40% 40% at 20% 70%, rgba(198,149,47,0.06) 0%, transparent 50%)

/* Gold CTA glow — energy behind the final call to action */
radial-gradient(ellipse 50% 50% at 50% 50%, rgba(200,151,62,0.06) 0%, transparent 60%)
```

---

## 3. TYPOGRAPHY

### Font Stack

```css
--serif: 'Playfair Display', Georgia, serif;
--sans: 'Outfit', -apple-system, sans-serif;
```

**Playfair Display** — editorial luxury serif. Used for all headings, prices, step numbers, pull quotes. The italic variant is especially beautiful and used for emphasis words. Weight range: 400 (italic emphasis) to 900 (headlines).

**Outfit** — clean geometric sans-serif. More modern than DM Sans, lighter than Inter. Used for body text, buttons, labels, navigation, descriptions. Weight range: 200 (light descriptions) to 800 (buttons, labels).

### Why These Two Fonts

Playfair + Outfit is the typographic equivalent of a tailored suit with clean sneakers. Playfair brings the gravitas — it says "this is important, this is established." Outfit brings the modernity — it says "but we're not stuck in the past." The contrast between the two creates visual hierarchy naturally.

### The Typography Scale

This scale is deliberately oversized. In a world of 16px headings and timid design, going to 76px with weight 900 is a statement. It says "we're not whispering."

```
Hero h1:          clamp(3.7rem, 9vw, 5.4rem)  — weight 900, letter-spacing -2.4px
Section h2:       clamp(2.4rem, 5vw, 3.5rem)  — weight 800, letter-spacing -1.6px
Card titles:      40px                         — weight 800
Sub-headings:     24px                         — weight 700
Prices:           56-58px                      — weight 900
Body text:        16-18px                      — weight 300-400, line-height 1.8-1.9
Descriptions:     14-15px                      — weight 300, line-height 1.7
Eyebrow labels:   12px                         — weight 700-800, letter-spacing 4-5px, uppercase
Button text:      12-13px                      — weight 800, letter-spacing 2.5-3px, uppercase
Nav links:        11px                         — weight 700, letter-spacing 2.6px, uppercase
Fine print:       11-12px                      — weight 300-400
```

### The Heading Pattern

Every section heading follows this exact structure:

```
1. Gold accent line (3px height, 48px width, gradient)
2. Eyebrow text (sans, 12px, weight 700-800, gold, uppercase, letter-spacing 4-5px)
3. Main heading (serif, clamp size, weight 800-900, with one italic gold word)
4. Optional subtitle (sans, 16px, weight 300, muted color)
```

The italic gold word in every heading is **the most important design decision in the typography**. It creates a visual anchor — the eye goes to the gold word first, then reads the full heading. Examples:

- "Embrace the **_Shift_**"
- "Not a seminar. **_A transformation._**"
- "Who this is **_for_**"
- "Choose your **_path_**"
- "How it **_works_**"

The italic word is always the emotional core of the heading. It's styled:
```css
font-style: italic;
font-weight: 400-500; /* lighter than the 800-900 heading */
color: var(--gold) or var(--gold-light);
```

This creates a rhythm: HEAVY heavy heavy *light* — like a musical accent.

### Letter-Spacing Rules

- Headings: **negative** letter-spacing (-1.5px to -2.4px) — pulls letters tight, feels confident
- Body text: **neutral** (0) — natural reading
- Labels/buttons: **positive** letter-spacing (2.5-5px) — spreads letters apart, feels premium and deliberate
- Navigation: **positive** (2.6px) — scannability

The contrast between tight headings and spread labels creates another layer of visual hierarchy.

### Line-Height Rules

- Headings: 1.0-1.1 — tight, impactful, lets the weight speak
- Body text: 1.8-1.9 — generous, breathable, easy to read
- Descriptions: 1.6-1.7 — comfortable but more compact
- Labels: 1.0 — single line, no breathing needed

---

## 4. SPACING SYSTEM

### Section Padding

```
Hero sections:    140px top, 100-120px bottom, 48px sides
Regular sections: 120-140px top/bottom, 48px sides
Gold bands:       64-80px top/bottom, 48px sides
Footer:           48px all around
```

These are deliberately generous. Most templates use 60-80px for sections. Using 120-140px creates a sense of space and importance — each section has room to breathe. The content doesn't feel crammed.

### Mobile Section Padding

```
Hero sections:    100px top, 60px bottom, 20px sides
Regular sections: 80px top/bottom, 20px sides
Gold bands:       48px top/bottom, 20px sides
```

### Content Max Widths

```
Full page:        1200px (hero split layouts)
Content sections: 1100px (packages, cards)
Text sections:    800-900px (about, how it works)
Centered text:    440-560px (subtitles, descriptions)
Form containers:  640-700px
```

### Card Spacing

```
Card padding:     48px 40px (desktop), 28px 22px (mobile)
Card gap:         28px between cards
Card border-radius: 28px (the signature rounded corner)
```

### The 28px Radius

28px border-radius is the signature shape of this design. It appears on:
- All cards
- Button pills (999px for full pill, 28px for card-like buttons)
- Image frames
- Input fields use 16px (slightly less, feels appropriate for interactive elements)

Why 28px? It's large enough to be noticeable and feel intentional, but not so large that it becomes cartoonish. It sits in the "premium app" zone — think iOS cards, modern SaaS dashboards.

### Element Spacing

```
Between eyebrow and heading:     24-28px
Between heading and subtitle:    16px
Between subtitle and content:    48-56px
Between items in a list:         12-14px
Between cards in a grid:         28px
Between sections:                0 (sections are flush, background color change creates the "gap")
Icon to label in chips:          8-10px
```

---

## 5. COMPONENT LIBRARY

### Navigation Bar

```
Position: fixed, top 0, full width
z-index: 100
Height: ~64px
Padding: 24px 48px (desktop), 16px (mobile)

Default state:
  background: transparent (over hero) → rgba(10,22,40,0.92) (after scrolling 60-80px)
  backdrop-filter: blur(20px) when scrolled
  border-bottom: transparent → 1px solid rgba(198,149,47,0.15) when scrolled
  transition: all 0.4s

Brand: gold diamond (14px, rotate 45deg) + "KMJ Creative" or "Embrace the Shift" (sans, 12px, weight 700, letter-spacing 4px, gold)

Links: sans, 11px, weight 700, letter-spacing 2.6px, uppercase
  Color: rgba(255,255,255,0.65) → var(--gold) on hover
  Underline: ::after pseudo-element, 2px height, gold, width 0 → 100% on hover
  Transition: 0.3s

Active link: detected via useLocation(), gold color + underline visible

CTA button in nav: smaller version of btn-gold, padding 12px 28px

Mobile (below 860px): hamburger button, slide-out panel with all links + CTA
```

### Buttons

All buttons are pill-shaped (border-radius: 999px). This is non-negotiable — it's the signature interactive element.

**btn-gold (Primary CTA):**
```css
padding: 20px 48px;
font: 800 13px/1 var(--sans);
letter-spacing: 3px;
text-transform: uppercase;
color: var(--navy);
background: linear-gradient(135deg, var(--gold), var(--gold-light), var(--gold));
background-size: 200% 100%;
border: none;
border-radius: 999px;
box-shadow: 0 16px 40px rgba(198,149,47,0.25);
position: relative;
overflow: hidden;

/* Shimmer animation */
::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.22), transparent);
  background-size: 200% 100%;
  animation: shimmer 2.5s linear infinite;
}

/* Hover */
:hover {
  transform: translateY(-3px);
  box-shadow: 0 20px 50px rgba(198,149,47,0.35), 0 0 0 1px var(--gold);
}
```

The shimmer animation is the signature touch — a subtle light sweep that keeps the button alive even when the user isn't hovering. It says "this is interactive" without being distracting.

**btn-navy (Secondary CTA on light backgrounds):**
```css
padding: 18px 44px;
background: var(--navy);
color: var(--white);
font-weight: 800;
border: none;
border-radius: 999px;
box-shadow: 0 12px 32px rgba(10,22,40,0.15);

:hover {
  background: var(--navy-light);
  transform: translateY(-2px);
  box-shadow: 0 16px 40px rgba(10,22,40,0.25);
}
```

**btn-white (Secondary CTA on dark backgrounds):**
```css
Same structure as btn-navy but:
background: var(--white);
color: var(--navy);
```

**btn-outline-gold (Tertiary CTA):**
```css
padding: 18px 44px;
background: transparent;
color: var(--gold);
border: 2px solid var(--gold);
border-radius: 999px;

:hover {
  background: var(--gold);
  color: var(--navy);
}
```

**btn-ghost (On dark backgrounds, very subtle):**
```css
padding: 18px 40px;
background: transparent;
color: var(--text-on-dark2);
border: 1px solid var(--text3);
border-radius: 999px;

:hover {
  border-color: var(--gold);
  color: var(--gold);
}
```

### Cards

**Standard card (light background):**
```css
background: var(--white);
border: 1px solid var(--cream);
border-radius: 28px;
padding: 48px 40px;
box-shadow: 0 22px 60px rgba(10,22,40,0.10);

:hover {
  transform: translateY(-8px);
  box-shadow: 0 40px 80px rgba(10,22,40,0.15);
  border-color: var(--gold);
}

transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
```

**Dark card (navy backgrounds):**
```css
background: var(--navy-mid); /* or rgba(255,255,255,0.02) */
border: 1px solid rgba(255,255,255,0.04);
border-radius: 28px;

::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
  opacity: 0;
  transition: opacity 0.5s;
}

:hover {
  border-color: rgba(198,149,47,0.15);
  transform: translateY(-6px);
  box-shadow: 0 30px 80px rgba(0,0,0,0.4), 0 0 60px rgba(198,149,47,0.04);
}

:hover::before {
  opacity: 1;
}
```

The gold line appearing on hover is a signature card effect — it rewards interaction with a subtle reveal.

**Featured card (the "Most Popular" or highlighted option):**
Same as dark card but with:
- Gold border: `border: 2px solid var(--gold)`
- "Most Popular" badge: absolute positioned, top right
- Badge: gold background, navy text, 10px font, weight 800, letter-spacing 2px, uppercase

### Audience Chips

```css
display: inline-flex;
align-items: center;
gap: 10px;
padding: 14px 28px;
background: rgba(255,255,255,0.04); /* on dark */
/* OR var(--white) on light backgrounds */
border: 1px solid rgba(255,255,255,0.08);
border-radius: 100px; /* full pill */
font: 400 14px var(--sans);
color: var(--text-on-dark);

/* Gold dot before text */
::before or child div {
  width: 6px;
  height: 6px;
  background: var(--gold);
  border-radius: 50%;
}

:hover {
  border-color: var(--gold);
  background: var(--gold);
  color: var(--navy);
}
```

### Form Inputs

```css
width: 100%;
padding: 16px 20px;
font: 400 15px var(--sans);
color: var(--navy);
background: var(--white);
border: 2px solid var(--cream);
border-radius: 16px;
outline: none;
transition: border-color 0.3s, box-shadow 0.3s;

:focus {
  border-color: var(--gold);
  box-shadow: 0 0 0 4px rgba(198,149,47,0.08);
}
```

The gold focus ring is critical — it provides clear feedback while staying on-brand. The 4px spread with low opacity creates a soft glow rather than a harsh outline.

### Status Badges

```css
display: inline-flex;
align-items: center;
gap: 6px;
padding: 6px 14px;
border-radius: 999px;
font: 700 11px var(--sans);
letter-spacing: 1.5px;
text-transform: uppercase;

/* Variants: */
confirmed:  background: rgba(107,191,89,0.12); color: #6BBF59; border: 1px solid rgba(107,191,89,0.2);
pending:    background: rgba(198,149,47,0.12); color: var(--gold); border: 1px solid rgba(198,149,47,0.2); + pulse animation
cancelled:  background: rgba(220,80,80,0.08); color: rgba(220,80,80,0.8); border: 1px solid rgba(220,80,80,0.15);
draft:      background: rgba(0,0,0,0.04); color: var(--text-muted); border: 1px solid var(--cream);
published:  background: rgba(107,191,89,0.12); color: #6BBF59;
```

### Gold Accent Line

```jsx
function GoldLine({ width = 48, style = {} }) {
  return ;
}
```

Used before every section heading. Width is always 48px. Height is always 3px. It's a small element that creates massive visual consistency — the eye learns to look for it as a section marker.

### Floating Diamonds

```jsx
function Diamond({ size = 120, style = {}, filled = false }) {
  return (
    
  );
}
```

Diamonds are placed in navy sections only. They're always very subtle — either a faint fill (0.04 opacity) or a thin border (0.08 opacity). They float with a gentle up-and-down animation. Typical placement: 2-4 per section, at least one in each corner region, varying sizes (40px-200px).

The diamond is the brand shape — it represents the "shift" (a square rotated, transformed, repositioned). It's used in the logo, as bullet points, as decorative elements, and as the favicon.

---

## 6. ANIMATION SYSTEM

### The Philosophy: Earned Attention

Every animation in this design serves a purpose: it either reveals content (scroll animations), provides feedback (hover states), or creates atmosphere (floating diamonds, grain). There are no animations that exist purely to be flashy.

### Scroll Reveal Animation

```jsx
function Reveal({ children, delay = 0, direction = "up", style = {} }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setVisible(true); },
      { threshold: 0.1 }
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  const transforms = {
    up: "translate3d(0,48px,0)",
    down: "translate3d(0,-48px,0)",
    left: "translate3d(48px,0,0)",
    right: "translate3d(-48px,0,0)",
  };

  return (
    
      {children}
    
  );
}
```

**Key details:**
- Distance: 48px (enough to notice, not enough to feel jarring)
- Duration: 0.9s (longer than typical — feels intentional, not rushed)
- Easing: `cubic-bezier(0.16, 1, 0.3, 1)` — this is the signature easing curve. It starts fast and decelerates smoothly. Feels like the element is settling into place with confidence.
- Threshold: 0.1 (triggers early — content starts animating before it's fully in view)
- Triggers once: never re-animates when scrolling back up
- Stagger: 0.08-0.15s between sibling elements. Multiple items cascade in sequence.

### Stagger Delays

When multiple items appear together (card grids, list items, stats):
```
Item 1: delay 0
Item 2: delay 0.1
Item 3: delay 0.2
Item 4: delay 0.3
```

The stagger creates a "wave" effect — elements cascade in rather than appearing all at once. This guides the eye through the content in order.

### Hover Transitions

**Cards:**
```css
transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
:hover { transform: translateY(-8px); }
```

**Buttons:**
```css
transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
:hover { transform: translateY(-3px); }
```

**Nav links:**
```css
transition: color 0.3s, width 0.3s;
```

**Images:**
```css
transition: transform 0.8s cubic-bezier(0.16, 1, 0.3, 1);
:hover { transform: scale(1.04); }
```

### Keyframe Animations

```css
/* Shimmer on gold buttons */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
/* Duration: 2.5s, linear, infinite */

/* Float for diamonds */
@keyframes float {
  0%, 100% { transform: rotate(45deg) translateY(0); }
  50% { transform: rotate(45deg) translateY(-14px); }
}
/* Duration: 5-7s, ease-in-out, infinite, staggered delays */

/* Film grain */
@keyframes grain {
  0%, 100% { transform: translate(0, 0); }
  10% { transform: translate(-5%, -10%); }
  30% { transform: translate(3%, -15%); }
  50% { transform: translate(12%, 9%); }
  70% { transform: translate(9%, 4%); }
  90% { transform: translate(-1%, 7%); }
}
/* Duration: 8s, steps(10), infinite */

/* Pulse for pending badges */
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
/* Duration: 2s, ease-in-out, infinite */

/* Pulsing glow on headshot frame */
@keyframes pulseGlow {
  0%, 100% { box-shadow: 0 0 40px rgba(198,149,47,0.15); }
  50% { box-shadow: 0 0 80px rgba(198,149,47,0.25); }
}
/* Duration: 4s, ease-in-out, infinite */

/* Fade up for confirmation page elements */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(30px); }
  to { opacity: 1; transform: translateY(0); }
}
/* Duration: 0.8s, ease, with staggered animation-delay */
```

### Film Grain Overlay

```css
.grain {
  position: fixed;
  inset: -50%;
  width: 200%;
  height: 200%;
  opacity: 0.018; /* VERY subtle — barely perceptible */
  pointer-events: none;
  z-index: 1;
  background-image: url("data:image/svg+xml,...feTurbulence noise...");
  animation: grain 8s steps(10) infinite;
}
```

The grain adds a filmic, analog texture to the entire page. At 0.018 opacity, most people won't consciously notice it — but they'll feel the difference. It prevents the "too clean" feeling that digital designs often have.

---

## 7. LAYOUT PATTERNS

### Hero — Split Screen

```
Desktop: flex, gap 80px, align center
  Left (flex 1.1, max-width 600px): eyebrow → h1 → subtitle → CTAs → metric chips
  Right (flex 0.9, max-width 460px): headshot in glass frame

Mobile: flex-direction column-reverse (image on top, text below)
```

The split screen hero is more engaging than centered text because it creates two entry points for the eye. The headshot adds human connection. The asymmetric flex (1.1 vs 0.9) gives the text slightly more space — content leads, image supports.

### Two-Column Content (About Section)

```
Desktop: grid, columns 1fr 380-400px, gap 80px, align center
  Left: text content
  Right: book cover image

Mobile: grid-template-columns 1fr (stacked)
```

### Three-Column Cards (Packages, Pathways)

```
Desktop: flex, gap 28px, justify center, align stretch
  Each card: flex 1, min-width 300px, max-width 520-540px

Mobile: flex-direction column, align center, max-width 100%
```

### Stat Grid

```
Desktop: grid, repeat(4, 1fr), gap 40px, text-align center
Mobile: grid, repeat(2, 1fr), gap 24px (2x2)
```

### Step List (How It Works)

```
Each step: flex, gap 36-40px, padding 32px 0
  Left: step number (serif, 44px, weight 900, gold)
  Right: title (serif, 24px, weight 700) + description (sans, 15px, weight 300)
  Border-bottom: 1px solid rgba(255,255,255,0.04) between steps
```

---

## 8. IMAGE TREATMENT

### Headshot Frame

```
Container: relative
  Gold frame: absolute, top -20px, right -20px, width 85%, height 85%, border 2px solid var(--gold), opacity 0.25, pulseGlow animation
  Small gold square: absolute, bottom -16px, left -16px, 120x120px, gold-glow fill, subtle border
  Image: relative z-2, aspect-ratio 4/5, overflow hidden, object-fit cover
  Name plate: absolute, bottom -28px, left 28px, z-3, gold background, navy text, padding 18px 32px
```

### Book Cover Frame

```
Container: relative
  Navy shadow: absolute, top -20px, left -20px, right 20px, bottom 20px, background navy
  Image: relative z-2, aspect-ratio 2/3, border 3px solid var(--gold), box-shadow deep
```

### Event Cover Images

```
Container: overflow hidden, rounded top corners (28px 28px 0 0)
  Image: width 100%, aspect-ratio 16:9, object-fit cover
  Fade-in: start opacity 0, onLoad set opacity 1, transition 0.4s
  Fallback: cream background placeholder if image fails
```

### Glass Panel Effect (hero headshot)

```css
background: rgba(255,255,255,0.03);
backdrop-filter: blur(10px);
border: 1px solid rgba(255,255,255,0.06);
border-radius: 28px;
```

---

## 9. RESPONSIVE STRATEGY

### Breakpoints

```
Desktop: > 900px (full layouts)
Tablet: 601-900px (simplified grids, some stacking)
Mobile: ≤ 600px (single column, adjusted padding)
Small mobile: 375px (iPhone SE — the stress test)
```

### What Changes at Each Breakpoint

**Below 900px:**
- Hero split → single column (image on top for column-reverse)
- Three-column grids → single column
- Two-column grids → single column
- Desktop nav links → hamburger menu
- Hero title: clamp reduces from 5.4rem to ~2.8rem

**Below 768px:**
- Stats grid: 4 columns → 2x2 grid
- Form grids: 2 columns → single column
- Card padding: 48px 40px → 28px 22px
- Section padding: 140px → 80px

**Below 600px:**
- Footer: flex row → column, center aligned
- CTA button rows: side by side → stacked, full width
- Section side padding: 48px → 16px

**Below 480px:**
- Hero CTAs: full width stacked
- All buttons: full width

### The Golden Rule

At every breakpoint, check:
1. No horizontal scrollbar
2. All text readable without zooming
3. All tap targets ≥ 44px
4. Consistent left/right padding (16px minimum)
5. No orphaned words in headings

---

## 10. THE EMOTIONAL DESIGN DETAILS

These are the details that separate "good" from "premium." Most people won't consciously notice them, but they contribute to the overall feeling of quality.

### Warm Whites
`#F8F6F1` instead of `#FFFFFF` for backgrounds. Adds warmth.

### Warm Text on Dark
`#F4F0E8` instead of `#FFFFFF` for text on navy. Pure white on dark blue is harsh. This warm white is gentler on the eyes.

### Negative Letter-Spacing on Headings
Pulling letters tighter at large sizes creates confidence. Default spacing looks loose at 56px+.

### The 0.9s Animation Duration
Longer than the standard 0.3-0.5s. Creates a sense of importance — things don't rush in, they arrive.

### Cubic-Bezier (0.16, 1, 0.3, 1)
This custom easing curve starts fast and decelerates gracefully. It feels like a luxury car braking — controlled, smooth, intentional.

### Film Grain at 0.018 Opacity
Subliminal texture. Removes the "too digital" feeling without being visible.

### Gold Shimmer on CTA
The constant subtle animation keeps the button alive. It's always ready, always inviting.

### Staggered Reveals
Content cascades in sequence rather than appearing all at once. This guides the eye and creates a sense of unfolding narrative.

### The Gold Word in Every Heading
One word highlighted per heading. Creates visual consistency and draws the eye to the most important concept.

### Diamond as Brand Shape
The rotated square appears everywhere: logo, bullets, decorations, section markers. It's the visual thread that ties everything together.

### Pull Quotes in Serif Italic
Testimonials and key quotes use the italic serif variant at a larger size. This creates "magazine spread" moments within the page.

### Color Blocking
Entire sections are a single color (navy, white, gold). This is braver than gradients or patterns — it requires confidence in the content.

---

## 11. APPLYING THIS DESIGN SYSTEM TO NEW SITES

### The Transfer Formula

This design system isn't locked to Embrace the Shift. It's a **framework for premium authority sites**. To apply it to a new brand:

1. **Keep the structure:** Split hero, alternating dark/light sections, gold/accent CTA bands, same component library
2. **Swap the palette:** Replace navy with the brand's dark color, gold with their accent. Keep the same value relationships (dark primary, warm accent, warm whites)
3. **Keep the fonts:** Playfair + Outfit work for almost any premium brand. Only change if the brand explicitly needs a different personality.
4. **Keep the typography scale:** The oversized headings, tight letter-spacing, and italic highlight word pattern work universally.
5. **Keep the animations:** The Reveal system, shimmer buttons, floating decorations, and grain overlay work on any site.
6. **Adjust the content structure:** The section types (hero, stats, about, audience, packages, process, CTA) map to almost any service business.

### What Makes It "Solutionist Quality"

- Headings are 2-3x larger than the template default
- Fonts are weight 800-900, not 600
- Button border-radius is 999px (full pill), never 4-8px
- Card border-radius is 28px, never 8-12px
- Section padding is 120-140px, never 40-60px
- Animations use 0.9s duration with custom cubic-bezier, never 0.3s ease
- Colors use warm whites, never pure white
- Text on dark uses warm off-white, never #FFFFFF
- Every heading has one italic accent word in the brand color
- Gold accent lines precede every section heading
- Film grain overlay on every page
- Scroll-triggered reveals on every element

This is the bar. Every site that comes through the Solutionist System should meet or exceed this standard.

---

## 12. TECH IMPLEMENTATION NOTES

### Stack
- Vite + React (JSX, not TSX for the website)
- React Router for multi-page navigation
- Supabase JS client for data
- Vercel for deployment
- No CSS framework — all inline styles + CSS-in-JS via <style> tags
- No component library — everything custom

### Why Inline Styles
The entire site uses inline React styles instead of CSS files or Tailwind. This was intentional:
- Every component is self-contained
- No class name conflicts
- Easy to see exactly what an element looks like by reading the JSX
- Dynamic styles (hover states, scroll effects) work naturally with useState
- No build step complexity

### Shared Components Architecture
```
src/components/
├── Nav.jsx              — Shared navigation
├── Footer.jsx           — Shared footer
├── Reveal.jsx           — Scroll animation wrapper
├── GoldBand.jsx         — Reusable gold CTA section
├── GoldLine.jsx         — Gold accent line
├── Diamond.jsx          — Floating diamond decoration
├── SectionHeading.jsx   — Eyebrow + h2 pattern
└── SharedStyles.jsx     — CSS variables, keyframes

src/styles/
└── global.css           — CSS variables, keyframe definitions, utility classes
```

### Performance Considerations
- Fonts loaded via Google Fonts with display=swap
- Images lazy-load with opacity transition
- IntersectionObserver only triggers once (no re-animation)
- willChange: "opacity, transform" on animated elements
- Film grain uses SVG filter, not image file
- No external JavaScript libraries beyond React + Router + Supabase

---

*This document is the design intelligence behind every pixel of embracetheshift.live. Use it to build with the same intention, quality, and confidence.*
