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

app = FastAPI(title="KMJ Intake Automation")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
                    json=notification
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
    
    print(f"📬 New form submission: {submission.get('name', 'Unknown')}")
    
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
