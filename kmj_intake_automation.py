# kmj_intake_automation.py
# KMJ Creative Solutions — 24/7 Intake Automation Backend
#
# Handles:
#   1. Netlify form webhook → auto-qualify lead → notify Kevin
#   2. Scheduled follow-up sequences (runs every hour)
#   3. Testimonial requests (30 days post-delivery)
#
# Deploy to: Railway / Render / your existing FastAPI server
#
# Install: pip install fastapi uvicorn anthropic python-dotenv apscheduler httpx

import os
import json
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Any
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from anthropic import Anthropic
from ai_proxy import router as ai_proxy_router
from intake_endpoint import router as intake_router
from nurture_agent import router as nurture_router
from session_agent import router as session_router
from contract_agent import router as contract_router
from payment_agent import router as payment_router
from growth_engine import router as growth_router
from module_agent import router as module_router
from chief_of_staff import router as chief_router
from notification_engine import router as notification_router

app = FastAPI(title="KMJ Intake Automation")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(ai_proxy_router)
app.include_router(intake_router)
app.include_router(nurture_router)
app.include_router(session_router)
app.include_router(contract_router)
app.include_router(payment_router)
app.include_router(growth_router)
app.include_router(module_router)
app.include_router(chief_router)
app.include_router(notification_router)

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "kevin@kmjcreative.com")
OWNER_NAME = os.getenv("OWNER_NAME", "Kevin McCloud Jr.")
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "KMJ Creative Solutions")

# In production: replace with Supabase/DB
PENDING_FOLLOWUPS: list[dict] = []
COMPLETED_PROJECTS: list[dict] = []

# ─────────────────────────────────────────────────────────────
# SOLUTION TYPES (mirrors agentService.ts)
# ─────────────────────────────────────────────────────────────

PACKAGES = """
DONE-IN-A-DAY ($800, 1 day): Fast-track for churches/ministries/simple businesses.
THE CONNECT ($750–$1,000, 5–7 days): Connect tools, one automation, brand pass.
THE LAUNCHPAD ($1,500–$2,500, 10–14 days): Full brand, multi-page site, email automation.
THE FULL SOLUTION ($3,500–$6,000, 3–4 weeks): Everything + AI agent, full automation, 90-day support.
"""

# ─────────────────────────────────────────────────────────────
# AUTO-QUALIFY — runs when a form submission comes in
# ─────────────────────────────────────────────────────────────

async def auto_qualify_lead(submission: dict[str, str]) -> dict[str, Any]:
    """Call Claude to qualify a lead and draft a response email."""
    
    submission_text = "\n".join(f"{k}: {v}" for k, v in submission.items())
    
    system = f"""You are the 24/7 Intake Agent for {BUSINESS_NAME}, run by {OWNER_NAME}.
A new lead just submitted a contact form. Qualify them and draft a ready-to-send response.
{OWNER_NAME} will review this before sending. Write in his voice: warm, confident, never corporate.

{PACKAGES}

RESPOND ONLY IN VALID JSON:
{{
  "readinessScore": 8,
  "readinessLabel": "Ready | Almost Ready | Needs Nurturing",
  "recommendedSolution": "WEB_PRESENCE | BRAND_KIT | MARKETING_ENGINE | MINISTRY_PACKAGE | BUSINESS_SYSTEM",
  "recommendedPackage": "DONE-IN-A-DAY | THE CONNECT | THE LAUNCHPAD | THE FULL SOLUTION",
  "estimatedValue": "$X,XXX",
  "responseSubject": "email subject line",
  "responseBody": "complete ready-to-send response email from Kevin — warm, specific, clear next step",
  "internalNotes": "what Kevin should know before following up — read on them, red flags, budget signals",
  "urgencySignals": ["signals this lead has time pressure"],
  "nextAction": "Kevin's single most important next action"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": f"New form submission:\n{submission_text}"}]
    )
    
    raw = response.content[0].text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


async def notify_kevin(submission: dict, qualify_result: dict):
    """Send Kevin a notification with the qualified lead and draft response."""
    
    score = qualify_result.get("readinessScore", 0)
    label = qualify_result.get("readinessLabel", "Unknown")
    package = qualify_result.get("recommendedPackage", "")
    value = qualify_result.get("estimatedValue", "")
    next_action = qualify_result.get("nextAction", "")
    
    # Score emoji
    score_emoji = "🔥" if score >= 8 else "⚡" if score >= 6 else "🌱"
    
    # Notification payload — send to your email/SMS/Slack
    notification = {
        "type": "new_lead",
        "timestamp": datetime.now().isoformat(),
        "subject": f"{score_emoji} New Lead [{label}] — {submission.get('name', 'Unknown')} | {value}",
        "headline": f"{score_emoji} {label} ({score}/10) — {package} | {value}",
        "client_name": submission.get("name", "Unknown"),
        "client_email": submission.get("email", ""),
        "next_action": next_action,
        "internal_notes": qualify_result.get("internalNotes", ""),
        "urgency_signals": qualify_result.get("urgencySignals", []),
        "draft_email": {
            "subject": qualify_result.get("responseSubject", ""),
            "body": qualify_result.get("responseBody", ""),
        },
        "raw_submission": submission,
    }
    
    print(f"\n{'='*60}")
    print(f"NEW LEAD: {notification['subject']}")
    print(f"Next action: {next_action}")
    print(f"{'='*60}\n")
    
    # ── Write to file for the Solutionist Studio to pick up ──
    # The studio polls this directory for new lead notifications
    os.makedirs("./leads", exist_ok=True)
    filename = f"./leads/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{submission.get('name', 'lead').replace(' ', '_')}.json"
    with open(filename, "w") as f:
        json.dump(notification, f, indent=2)
    
    # ── Optionally: POST to Supabase for the studio to read ──
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    if supabase_url and supabase_key:
        try:
            async with httpx.AsyncClient() as http:
                await http.post(
                    f"{supabase_url}/rest/v1/leads",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    json={
                        "client_name": notification.get("client_name"),
                        "client_email": notification.get("client_email"),
                        "organization": submission.get("organization", ""),
                        "business_type": submission.get("business_type", ""),
                        "readiness_score": qualify_result.get("readinessScore", 0),
                        "draft_email": qualify_result.get("responseBody", ""),
                        "internal_notes": qualify_result.get("internalNotes", ""),
                        "urgency": qualify_result.get("urgencySignals", [""]),
                        "status": "pending",
                        "raw_answers": submission
                    }
                )
        except Exception as e:
            print(f"Supabase write failed: {e}")
    
    return notification


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.post("/webhook/netlify-form")
async def netlify_form_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Netlify sends form submissions here automatically.
    Set this URL in Netlify: Site Settings → Forms → Notifications → Webhook
    """
    try:
        body = await request.json()
    except Exception:
        form_data = await request.form()
        body = dict(form_data)
    
    # Netlify wraps form data in a 'data' key
    submission = body.get("data", body)
    
    if not submission:
        raise HTTPException(status_code=400, detail="No form data received")
    
    # Normalize field names from preflight form
    if 'client_name' in submission and 'name' not in submission:
        submission['name'] = submission['client_name']
    if 'email' not in submission and 'client_email' in submission:
        submission['email'] = submission['client_email']

    print(f"📬 New form submission: {submission.get('name', submission.get('client_name', 'Unknown'))}")
    
    # Run qualification in background — don't make Netlify wait
    background_tasks.add_task(process_lead, dict(submission))
    
    return {"status": "received", "message": "Lead processing started"}


async def process_lead(submission: dict):
    """Background task: qualify + notify."""
    try:
        qualify_result = await auto_qualify_lead(submission)
        await notify_kevin(submission, qualify_result)
        print(f"✅ Lead processed: {submission.get('name', 'Unknown')} — {qualify_result.get('readinessLabel')}")
    except Exception as e:
        print(f"❌ Lead processing failed: {e}")


@app.post("/webhook/manual-lead")
async def manual_lead(request: Request, background_tasks: BackgroundTasks):
    """
    Manually submit a lead for qualification.
    Use from Solutionist Studio when you get a walk-in or phone inquiry.
    """
    submission = await request.json()
    background_tasks.add_task(process_lead, submission)
    return {"status": "queued"}


@app.get("/leads/pending")
async def get_pending_leads():
    """Return unreviewed leads for the studio to display."""
    leads = []
    leads_dir = "./leads"
    if os.path.exists(leads_dir):
        for f in sorted(os.listdir(leads_dir), reverse=True)[:20]:
            if f.endswith(".json"):
                with open(os.path.join(leads_dir, f)) as fp:
                    leads.append(json.load(fp))
    return {"leads": leads}


@app.post("/projects/complete")
async def mark_project_complete(request: Request):
    """
    Call this when a project is delivered.
    Schedules automatic follow-up sequence.
    """
    data = await request.json()
    project = {
        "id": data.get("projectId"),
        "clientName": data.get("clientName"),
        "clientEmail": data.get("clientEmail"),
        "packageDelivered": data.get("packageDelivered"),
        "completedAt": datetime.now().isoformat(),
        "followups": [
            {"day": 3,  "type": "Check-in",            "sent": False},
            {"day": 7,  "type": "Feedback Request",     "sent": False},
            {"day": 30, "type": "Testimonial Request",  "sent": False},
            {"day": 60, "type": "Upsell",               "sent": False},
        ]
    }
    COMPLETED_PROJECTS.append(project)
    print(f"📋 Project marked complete: {data.get('clientName')} — follow-up sequence scheduled")
    return {"status": "scheduled", "followups": len(project["followups"])}


# ─────────────────────────────────────────────────────────────
# SCHEDULER — runs every hour, checks for due follow-ups
# ─────────────────────────────────────────────────────────────

async def generate_followup_email(project: dict, followup_type: str) -> dict:
    """Generate a follow-up email for a specific touch."""
    
    system = f"""You are writing a follow-up email on behalf of {OWNER_NAME} at {BUSINESS_NAME}.
Write in his voice — warm, genuine, never salesy or corporate.
This is a {followup_type} email. Keep it short (3-5 sentences max).
RESPOND ONLY IN VALID JSON: {{"subject": "...", "body": "full email text"}}"""

    msg = f"""Client: {project['clientName']}
Package delivered: {project['packageDelivered']}
Days since delivery: {followup_type}
Type: {followup_type}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": msg}]
    )
    raw = response.content[0].text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


async def check_followup_sequences():
    """Runs every hour. Finds due follow-ups and generates emails."""
    now = datetime.now()
    due_count = 0
    
    for project in COMPLETED_PROJECTS:
        completed_at = datetime.fromisoformat(project["completedAt"])
        
        for followup in project["followups"]:
            if followup["sent"]:
                continue
            
            due_date = completed_at + timedelta(days=followup["day"])
            if now >= due_date:
                print(f"⏰ Follow-up due: {followup['type']} for {project['clientName']}")
                
                try:
                    email = await generate_followup_email(project, followup["type"])
                    
                    # Write to leads dir for studio to pick up
                    os.makedirs("./followups", exist_ok=True)
                    filename = f"./followups/{now.strftime('%Y%m%d_%H%M%S')}_{project['clientName'].replace(' ', '_')}_{followup['type'].replace(' ', '_')}.json"
                    with open(filename, "w") as f:
                        json.dump({
                            "type": "followup",
                            "followupType": followup["type"],
                            "client": project,
                            "email": email,
                            "dueAt": due_date.isoformat(),
                            "generatedAt": now.isoformat(),
                        }, f, indent=2)
                    
                    followup["sent"] = True
                    due_count += 1
                    print(f"✅ Follow-up email drafted: {followup['type']} for {project['clientName']}")
                    
                except Exception as e:
                    print(f"❌ Follow-up generation failed: {e}")
    
    if due_count > 0:
        print(f"📬 {due_count} follow-up(s) ready for review")


# ─────────────────────────────────────────────────────────────
# STARTUP / SHUTDOWN
# ─────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup():
    scheduler.add_job(check_followup_sequences, "interval", hours=1, id="followup_check")
    scheduler.start()
    print(f"🚀 KMJ Intake Automation running")
    print(f"   Owner: {OWNER_NAME} | {BUSINESS_NAME}")
    print(f"   Scheduler: checking follow-ups every hour")
    print(f"   Webhook: POST /webhook/netlify-form")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()



# ─────────────────────────────────────────────────────────────
# STRATEGIC PULSE — live web research briefing
# ─────────────────────────────────────────────────────────────

@app.post("/pulse")
async def run_pulse(request: Request):
    """
    Strategic Pulse Agent v2 — with live web search + observation context.
    Called automatically by Solutionist Studio on app open (morning window).
    Reads accumulated observations from the observer layer.
    Returns full briefing JSON.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    owner_name      = data.get("ownerName", "Kevin")
    business_name   = data.get("businessName", "KMJ Creative Solutions")
    income_this_month   = data.get("incomeThisMonth", 0)
    income_goal         = data.get("incomeGoal", 7000)
    active_projects     = data.get("activeProjects", 0)
    total_projects      = data.get("totalProjects", 0)
    completed_projects  = data.get("completedProjects", 0)
    pending_proposals   = data.get("pendingProposals", 0)
    pending_invoices    = data.get("pendingInvoices", 0)
    invoices_past_due   = data.get("invoicesPastDue", 0)
    queue_item_count    = data.get("queueItemCount", 0)
    high_urgency_count  = data.get("highUrgencyCount", 0)
    recent_clients      = data.get("recentClients", [])
    top_package         = data.get("topPackage", "")
    avg_project_value   = data.get("avgProjectValue", 0)
    days_into_month     = data.get("daysIntoMonth", 1)
    api_calls_this_month = data.get("totalApiCallsThisMonth", 0)
    current_month       = data.get("currentMonth", "")
    day_of_week         = data.get("dayOfWeek", "")
    observations        = data.get("observations", [])  # from pulseObserver

    days_left    = 30 - days_into_month
    pct_to_goal  = round((income_this_month / income_goal * 100)) if income_goal > 0 else 0
    pace_needed  = round((income_goal - income_this_month) / max(days_left, 1))

    # Format observations for context
    obs_text = ""
    if observations:
        critical = [o for o in observations if o.get("severity") == "critical"]
        warnings = [o for o in observations if o.get("severity") == "warning"]
        info     = [o for o in observations if o.get("severity") == "info"]
        obs_lines = []
        for o in critical:
            obs_lines.append(f"  🔴 CRITICAL: {o.get('note', '')}")
        for o in warnings:
            obs_lines.append(f"  🟡 WARNING: {o.get('note', '')}")
        for o in info[:3]:
            obs_lines.append(f"  ℹ️ INFO: {o.get('note', '')}")
        obs_text = "\n".join(obs_lines)
    else:
        obs_text = "  No observations logged yet."

    system = f"""You are the Strategic Pulse Agent for {business_name}, run by {owner_name}.
{owner_name} is a Solutionist who builds AI-powered tools, websites, and automation for small businesses, churches, and nonprofits in Muskegon, MI.

HIS FULL STACK:
- Solutionist Studio — AI client pipeline (proposals, invoices, content, docs)
- WiseStat — prop firm trading analytics + AI coach
- Sermon Studio — AI sermon prep for pastors
- Mina — church accounting with OCR
- MT5 EAs — automated trading bots (Hunter, Sniper, Trapper, First Strike, etc.)
- Services: Web presence, brand kits, marketing engines, ministry packages, business systems
- Income goal: $7–15K/month (services + trading + productized tools)

YOUR ROLE: Act as his overnight chief of staff who:
1. Reviewed the observations his monitoring system flagged
2. Did web research on market trends and opportunities
3. Is now delivering a morning briefing that is specific, honest, and actionable

SEARCH THESE TOPICS WITH web_search (do all 5 before writing JSON):
1. "AI tools small business 2025 2026 trends"
2. "church management software AI automation 2025"
3. "website builder AI competition pricing 2026"
4. "productized service business pricing models 2025"
5. One search specifically relevant to the most critical observation below

Be direct, warm, punchy — not corporate. Reference real tool names and prices from your searches.

RESPOND ONLY IN VALID JSON after completing all searches:
{{
  "greeting": "2-sentence punchy opener — reference the day + something specific from observations or data",
  "energyRead": "building | momentum | plateau | reset",
  "energyLabel": "short phrase like Gaining Speed or Time to Push",
  "incomeSnapshot": {{
    "thisMonthTotal": {income_this_month},
    "goalAmount": {income_goal},
    "percentToGoal": {pct_to_goal},
    "projectedEOM": 0,
    "gap": 0,
    "verdict": "1 honest sentence on income trajectory"
  }},
  "pipelineHealth": {{
    "activeCount": {active_projects},
    "stuckCount": 0,
    "proposalsPending": {pending_proposals},
    "urgentFollowUps": ["client — specific reason"],
    "verdict": "1 honest sentence on pipeline health"
  }},
  "observationSummary": {{
    "criticalCount": 0,
    "warningCount": 0,
    "topFlags": ["2-3 most important things the observer flagged"],
    "verdict": "1 sentence on overall system health from observations"
  }},
  "researchBrief": [
    {{
      "topic": "topic that was searched",
      "finding": "2-3 sentences with SPECIFIC real tool names, prices, trends found",
      "relevance": "why this matters to Kevin right now",
      "source": "tool name or publication"
    }}
  ],
  "systemImprovements": [
    {{
      "system": "WiseStat | Sermon Studio | Mina | Solutionist Studio | Trading EAs | Services",
      "issue": "specific gap identified",
      "suggestion": "specific improvement with detail",
      "impact": "high | medium | low",
      "effort": "quick | weekend | project"
    }}
  ],
  "addOnOpportunities": [
    {{
      "title": "short bold title",
      "description": "2 sentences — what it is and why Kevin is positioned to offer it now",
      "estimatedValue": "$X–$Y per client or /month",
      "whyNow": "specific reason this window is open",
      "action": "exact first step"
    }}
  ],
  "costWatch": {{
    "estimatedMonthlyCost": "$X–$Y estimate based on usage",
    "biggestCostDriver": "what agent/feature uses most tokens",
    "savingOpportunity": "specific way to reduce cost",
    "verdict": "1 sentence cost health read"
  }},
  "relevanceScore": {{
    "score": 0,
    "label": "Cutting Edge | Ahead of Curve | Current | Falling Behind",
    "strengths": ["specific things Kevin does that are ahead of market"],
    "threats": ["specific tools or trends that could displace services"],
    "nextMove": "1 bold move to extend his lead"
  }},
  "weeklyBoldPlays": [
    {{"day": "Today", "play": "specific action", "why": "why today", "value": "$X or outcome"}},
    {{"day": "Tomorrow", "play": "specific action", "why": "why", "value": "outcome"}},
    {{"day": "This Week", "play": "strategic action", "why": "strategic reason", "value": "impact"}}
  ],
  "topOpportunity": {{
    "title": "bold title",
    "description": "1-2 sentences",
    "estimatedValue": "$X–$Y",
    "action": "exact next step"
  }},
  "blindSpot": {{
    "title": "bold title",
    "description": "1-2 sentences",
    "fix": "specific fix"
  }},
  "boldMove": {{
    "title": "bold title",
    "why": "1 sentence",
    "how": "2-3 sentences exactly how to execute",
    "timeToExecute": "time estimate"
  }},
  "focusBlocks": [
    {{"time": "Morning", "task": "specific task", "why": "why this matters"}},
    {{"time": "Midday", "task": "specific task", "why": "why"}},
    {{"time": "Afternoon", "task": "specific task", "why": "why"}}
  ],
  "closingWord": "1 punchy line to send Kevin into the day with intention"
}}"""

    user_msg = f"""Today: {day_of_week}, {current_month}
Day {days_into_month} of ~30 ({days_left} days left)

INCOME:
- This month: ${income_this_month:,}
- Goal: ${income_goal:,} | {pct_to_goal}% complete
- Need ${pace_needed:,}/day to hit goal
- Avg project value: ${avg_project_value:,}

PIPELINE:
- Active: {active_projects} | Completed: {completed_projects} | Total: {total_projects}
- Proposals pending: {pending_proposals}
- Invoices: {pending_invoices} pending, {invoices_past_due} past due
- Queue: {queue_item_count} items ({high_urgency_count} high urgency)
- Recent clients: {", ".join(recent_clients) or "none yet"}
- Top package: {top_package or "none yet"}

API USAGE: ~{api_calls_this_month} calls this month

OBSERVER FLAGS (what the system noticed since last briefing):
{obs_text}

Now search the 5 topics, factor in the observer flags, and generate the full briefing."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_msg}]
        )

        # Extract all text blocks (web search produces multiple content blocks)
        full_text = ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                full_text += block.text

        full_text = full_text.replace("```json", "").replace("```", "").strip()

        # Find JSON in response
        start_idx = full_text.find("{")
        end_idx   = full_text.rfind("}") + 1
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No JSON found in response")

        json_str  = full_text[start_idx:end_idx]
        briefing  = json.loads(json_str)
        return briefing

    except json.JSONDecodeError as e:
        print(f"Pulse JSON parse error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse briefing: {str(e)}")
    except Exception as e:
        print(f"Pulse agent error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/canva-callback")
async def canva_callback(request: Request):
    """
    Relay Canva OAuth callback to the local Tauri/dev app.
    Canva redirects here → we immediately redirect to localhost with the same params.
    """
    from fastapi.responses import HTMLResponse
    params = str(request.url.query)
    query = f"?{params}" if params else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <title>Connecting Canva...</title>
  <style>
    body {{ margin:0; background:#0f0f14; color:#fff; font-family:system-ui,sans-serif;
           display:flex; align-items:center; justify-content:center; height:100vh;
           flex-direction:column; gap:16px; }}
    .spinner {{ width:40px; height:40px; border:3px solid #333;
                border-top-color:#a855f7; border-radius:50%;
                animation:spin 0.8s linear infinite; }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
    p {{ color:#888; font-size:14px; margin:0; }}
  </style>
</head>
<body>
  <div class="spinner"></div>
  <p>Connecting Canva to KMJ Studio...</p>
  <script>
    var DEV  = 'http://localhost:5173/canva-callback{query}';
    var PROD = 'http://127.0.0.1:1420/canva-callback{query}';
    window.location.href = DEV;
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/health")
async def health():
    return {
        "status": "running",
        "business": BUSINESS_NAME,
        "owner": OWNER_NAME,
        "active_projects": len(COMPLETED_PROJECTS),
        "scheduler": scheduler.running,
        "next_followup_check": str(scheduler.get_job("followup_check").next_run_time),
    }


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))
    uvicorn.run("kmj_intake_automation:app", host="0.0.0.0", port=port)

# ─────────────────────────────────────────────────────────────
# DEPLOYMENT NOTES
# ─────────────────────────────────────────────────────────────
#
# 1. Environment variables needed:
#    ANTHROPIC_API_KEY=sk-...
#    OWNER_EMAIL=kevin@kmjcreative.com
#    SUPABASE_URL=https://brqjgbpzackdihgjsorf.supabase.co
#    SUPABASE_ANON_KEY=eyJ...
#
# 2. Deploy to Railway (free tier works):
#    railway login
#    railway init
#    railway up
#
# 3. Connect Netlify webhook:
#    Netlify Dashboard → Site Settings → Forms → Notifications
#    → Add Webhook → URL: https://your-railway-url.railway.app/webhook/netlify-form
#
# 4. In production, replace COMPLETED_PROJECTS list with Supabase query:
#    supabase.table('projects').select('*').eq('status', 'delivered').execute()
