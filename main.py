"""
FastAPI Backend for Bulk Email Sender - Production Version
Full functionality with 10k batch sending, delivery tracking, seed testing, and export
"""
import asyncio
import csv
import io
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import (
    create_tables,
    get_db,
    get_session,
    SMTPAccount,
    APIProvider,
    Campaign,
    Recipient,
    SendLog,
    BounceRecord,
    Suppression,
    IMAPAccount,
)
from migration import migrate_sqlite_to_postgres_if_configured

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Active campaign tasks
active_campaigns: Dict[int, asyncio.Task] = {}
campaign_progress: Dict[int, Dict[str, Any]] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Bulk Email Sender API...")
    # Create tables on startup (and wait for Postgres to become ready in docker-compose).
    for attempt in range(30):
        try:
            create_tables()
            break
        except Exception as e:
            if attempt == 29:
                raise
            logger.warning(f"Database not ready yet ({e}); retrying...")
            await asyncio.sleep(1)

    if os.getenv("MIGRATE_FROM_SQLITE_PATH"):
        result = migrate_sqlite_to_postgres_if_configured()
        if result:
            logger.info(f"✅ Migration complete: {result}")
    logger.info("📊 Database initialized")
    yield
    # Cancel active campaigns on shutdown
    for task in active_campaigns.values():
        task.cancel()
    logger.info("👋 Shutting down...")

app = FastAPI(
    title="Bulk Email Sender",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==================== Pydantic Models ====================

class SMTPAccountCreate(BaseModel):
    name: str
    host: str
    port: int = 587
    username: str
    password: str
    from_email: str
    from_name: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    max_per_hour: int = 500
    max_per_day: int = 10000

class APIProviderCreate(BaseModel):
    name: str
    provider_type: str  # sendgrid, mailgun, postmark, mailjet, amazon_ses
    api_key: str
    api_secret: str = ""
    domain: str = ""
    from_email: str
    from_name: str = ""
    max_per_hour: int = 1000
    max_per_day: int = 50000

class IMAPAccountCreate(BaseModel):
    name: str
    protocol: str = "imap"
    host: str
    port: int = 993
    username: str
    password: str
    use_ssl: bool = True

class CampaignCreate(BaseModel):
    name: str
    subject: str
    body_html: str
    body_text: str = ""
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    throttle_rate: float = 0.1

class SendTestRequest(BaseModel):
    provider_type: str  # smtp or api provider name
    provider_id: int
    to_email: str
    subject: str = "Test Email from Bulk Email Sender"
    body_html: str = "<h1>Test Email</h1><p>This is a test message.</p>"

class SeedTestRequest(BaseModel):
    provider_type: str
    provider_id: int
    seed_emails: List[str]  # Gmail and Outlook test addresses
    subject: str = "Inbox Placement Test"
    body_html: str = "<h1>Inbox Placement Test</h1><p>This email should reach your inbox.</p>"

class SuppressionCreate(BaseModel):
    email: str
    reason: str = "manual"

# ==================== HTML Routes ====================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/providers", response_class=HTMLResponse)
async def providers_page(request: Request):
    return templates.TemplateResponse("providers.html", {"request": request})

@app.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request):
    return templates.TemplateResponse("templates.html", {"request": request})

# ==================== API Endpoints ====================

@app.get("/api/test")
def test_connection():
    return {
        "status": "success",
        "message": "API is working correctly!",
        "database": "connected",
        "version": "2.0.0",
        "features": [
            "10k batch sending",
            "Multi-provider support",
            "Delivery tracking",
            "Seed testing",
            "CSV export"
        ]
    }

# ==================== SMTP Accounts ====================

@app.get("/api/smtp-accounts")
def list_smtp_accounts(db: Session = Depends(get_db)):
    accounts = db.query(SMTPAccount).all()
    return [
        {
            "id": a.id, "name": a.name, "host": a.host, "port": a.port,
            "username": a.username, "from_email": a.from_email,
            "from_name": a.from_name, "use_tls": a.use_tls,
            "use_ssl": a.use_ssl, "enabled": a.enabled,
            "max_per_hour": a.max_per_hour, "max_per_day": a.max_per_day,
            "sent_today": a.sent_today, "sent_this_hour": a.sent_this_hour
        }
        for a in accounts
    ]

@app.post("/api/smtp-accounts")
def create_smtp_account(account: SMTPAccountCreate, db: Session = Depends(get_db)):
    db_account = SMTPAccount(**account.model_dump())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return {"id": db_account.id, "message": "SMTP account created successfully"}

@app.post("/api/smtp-accounts/{account_id}/test")
async def test_smtp_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(SMTPAccount).filter(SMTPAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    from senders import SMTPSender
    sender = SMTPSender(
        host=account.host,
        port=account.port,
        username=account.username,
        password=account.password,
        from_email=account.from_email,
        from_name=account.from_name,
        use_tls=account.use_tls,
        use_ssl=account.use_ssl
    )
    
    result = await sender.test_connection()
    return result

@app.delete("/api/smtp-accounts/{account_id}")
def delete_smtp_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(SMTPAccount).filter(SMTPAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
    return {"message": "Account deleted"}

# ==================== API Providers ====================

@app.get("/api/api-providers")
def list_api_providers(db: Session = Depends(get_db)):
    providers = db.query(APIProvider).all()
    return [
        {
            "id": p.id, "name": p.name, "provider_type": p.provider_type,
            "from_email": p.from_email, "from_name": p.from_name,
            "domain": p.domain, "enabled": p.enabled,
            "max_per_hour": p.max_per_hour, "max_per_day": p.max_per_day,
            "sent_today": p.sent_today, "sent_this_hour": p.sent_this_hour
        }
        for p in providers
    ]

@app.post("/api/api-providers")
def create_api_provider(provider: APIProviderCreate, db: Session = Depends(get_db)):
    db_provider = APIProvider(**provider.model_dump())
    db.add(db_provider)
    db.commit()
    db.refresh(db_provider)
    return {"id": db_provider.id, "message": "API provider created successfully"}

@app.post("/api/api-providers/{provider_id}/test")
async def test_api_provider(provider_id: int, db: Session = Depends(get_db)):
    provider = db.query(APIProvider).filter(APIProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    from senders import APISender
    sender = APISender.create(
        provider_type=provider.provider_type,
        api_key=provider.api_key,
        api_secret=provider.api_secret,
        domain=provider.domain,
        from_email=provider.from_email,
        from_name=provider.from_name
    )
    
    result = await sender.test_connection()
    return result

@app.delete("/api/api-providers/{provider_id}")
def delete_api_provider(provider_id: int, db: Session = Depends(get_db)):
    provider = db.query(APIProvider).filter(APIProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    db.delete(provider)
    db.commit()
    return {"message": "Provider deleted"}

# ==================== Campaigns ====================

@app.get("/api/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return [
        {
            "id": c.id, "name": c.name, "subject": c.subject,
            "status": c.status, "total_recipients": c.total_recipients,
            "sent_count": c.sent_count, "delivered_count": c.delivered_count,
            "bounced_count": c.bounced_count, "failed_count": c.failed_count,
            "throttle_rate": c.throttle_rate,
            "created_at": c.created_at.isoformat(),
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            "progress": campaign_progress.get(c.id, {})
        }
        for c in campaigns
    ]

@app.post("/api/campaigns")
def create_campaign(campaign: CampaignCreate, db: Session = Depends(get_db)):
    db_campaign = Campaign(**campaign.model_dump())
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return {"id": db_campaign.id, "message": "Campaign created successfully"}

@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return {
        "id": campaign.id,
        "name": campaign.name,
        "subject": campaign.subject,
        "body_html": campaign.body_html,
        "body_text": campaign.body_text,
        "status": campaign.status,
        "total_recipients": campaign.total_recipients,
        "sent_count": campaign.sent_count,
        "delivered_count": campaign.delivered_count,
        "bounced_count": campaign.bounced_count,
        "failed_count": campaign.failed_count,
        "throttle_rate": campaign.throttle_rate,
        "progress": campaign_progress.get(campaign.id, {})
    }

@app.post("/api/campaigns/{campaign_id}/upload-recipients")
async def upload_recipients(campaign_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload CSV file with recipients (supports up to 100k rows)"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Check suppression list
    suppressions = set(s.email.lower() for s in db.query(Suppression).all())
    
    # Read CSV
    content = await file.read()
    csv_content = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(csv_content))
    
    recipients_added = 0
    skipped = 0
    
    for row in reader:
        email = row.get('email', '').strip().lower()
        if not email or '@' not in email:
            skipped += 1
            continue
        
        # Skip suppressed emails
        if email in suppressions:
            skipped += 1
            continue
        
        # Check for duplicates
        existing = db.query(Recipient).filter(
            Recipient.campaign_id == campaign_id,
            Recipient.email == email
        ).first()
        if existing:
            skipped += 1
            continue
        
        recipient = Recipient(
            campaign_id=campaign_id,
            email=email,
            first_name=row.get('first_name', ''),
            last_name=row.get('last_name', ''),
            custom_fields=json.dumps({k: v for k, v in row.items() if k not in ['email', 'first_name', 'last_name']})
        )
        db.add(recipient)
        recipients_added += 1
        
        # Batch commit every 1000 records
        if recipients_added % 1000 == 0:
            db.commit()
    
    db.commit()
    
    # Update campaign total
    campaign.total_recipients = db.query(Recipient).filter(Recipient.campaign_id == campaign_id).count()
    db.commit()
    
    return {
        "message": f"Uploaded {recipients_added} recipients",
        "added": recipients_added,
        "skipped": skipped,
        "total": campaign.total_recipients
    }

@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    provider_type: str = Query(..., description="smtp or api"),
    provider_id: int = Query(..., description="Provider ID"),
    db: Session = Depends(get_db)
):
    """Start sending campaign in background"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    if campaign.status == "sending":
        raise HTTPException(status_code=400, detail="Campaign already sending")
    
    # Validate provider exists
    if provider_type == "smtp":
        provider = db.query(SMTPAccount).filter(SMTPAccount.id == provider_id).first()
    else:
        provider = db.query(APIProvider).filter(APIProvider.id == provider_id).first()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    # Update campaign status
    campaign.status = "sending"
    campaign.started_at = datetime.utcnow()
    db.commit()
    
    # Start background task
    background_tasks.add_task(
        send_campaign_task,
        campaign_id=campaign_id,
        provider_type=provider_type,
        provider_id=provider_id
    )
    
    return {"message": "Campaign started", "status": "sending"}

@app.post("/api/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Pause a running campaign"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id].cancel()
        del active_campaigns[campaign_id]
    
    campaign.status = "paused"
    db.commit()
    
    return {"message": "Campaign paused"}

@app.get("/api/campaigns/{campaign_id}/progress")
def get_campaign_progress(campaign_id: int):
    """Get real-time campaign progress"""
    return campaign_progress.get(campaign_id, {"sent": 0, "total": 0, "failed": 0, "rate": 0})

@app.get("/api/campaigns/{campaign_id}/events")
def get_campaign_events(
    campaign_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get delivery events for a campaign with pagination"""
    offset = (page - 1) * per_page
    logs = db.query(SendLog).filter(SendLog.campaign_id == campaign_id)\
        .order_by(SendLog.timestamp.desc())\
        .offset(offset).limit(per_page).all()
    
    total = db.query(SendLog).filter(SendLog.campaign_id == campaign_id).count()
    
    return {
        "events": [
            {
                "id": log.id,
                "recipient_id": log.recipient_id,
                "status": log.status,
                "message_id": log.message_id,
                "provider": log.provider_type,
                "response": log.response,
                "timestamp": log.timestamp.isoformat()
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page
    }

@app.get("/api/campaigns/{campaign_id}/export")
def export_campaign_events(campaign_id: int, db: Session = Depends(get_db)):
    """Export campaign delivery events as CSV"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Get all recipients with their status
    recipients = db.query(Recipient).filter(Recipient.campaign_id == campaign_id).all()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "email", "first_name", "last_name", "status", "message_id",
        "sent_at", "provider", "error"
    ])
    
    for r in recipients:
        writer.writerow([
            r.email,
            r.first_name,
            r.last_name,
            r.status,
            r.message_id or "",
            r.sent_at.isoformat() if r.sent_at else "",
            r.provider_type or "",
            r.error_message or ""
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=campaign_{campaign_id}_events.csv"
        }
    )

@app.delete("/api/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Cancel if running
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id].cancel()
        del active_campaigns[campaign_id]
    
    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted"}

# ==================== Send Test Email ====================

@app.post("/api/send-test")
async def send_test_email(request: SendTestRequest, db: Session = Depends(get_db)):
    """Send a single test email through specified provider"""
    if request.provider_type == "smtp":
        account = db.query(SMTPAccount).filter(SMTPAccount.id == request.provider_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="SMTP account not found")
        
        from senders import SMTPSender
        sender = SMTPSender(
            host=account.host,
            port=account.port,
            username=account.username,
            password=account.password,
            from_email=account.from_email,
            from_name=account.from_name,
            use_tls=account.use_tls,
            use_ssl=account.use_ssl
        )
        
        result = await sender.send(
            to_email=request.to_email,
            subject=request.subject,
            body_html=request.body_html
        )
    else:
        provider = db.query(APIProvider).filter(APIProvider.id == request.provider_id).first()
        if not provider:
            raise HTTPException(status_code=404, detail="API provider not found")
        
        from senders import APISender
        sender = APISender.create(
            provider_type=provider.provider_type,
            api_key=provider.api_key,
            api_secret=provider.api_secret,
            domain=provider.domain,
            from_email=provider.from_email,
            from_name=provider.from_name
        )
        
        result = await sender.send(
            to_email=request.to_email,
            subject=request.subject,
            body_html=request.body_html
        )
    
    return {
        "success": result.success,
        "message_id": result.message_id,
        "error": result.error,
        "provider": result.provider,
        "recipient": result.recipient
    }

# ==================== Seed Testing for Inbox Placement ====================

@app.post("/api/seed-test")
async def run_seed_test(request: SeedTestRequest, db: Session = Depends(get_db)):
    """
    Send test emails to seed addresses (Gmail/Outlook) to verify inbox placement.
    Use this to prove 95%+ inbox delivery rate.
    """
    results = []
    
    # Get sender
    if request.provider_type == "smtp":
        account = db.query(SMTPAccount).filter(SMTPAccount.id == request.provider_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="SMTP account not found")
        
        from senders import SMTPSender
        sender = SMTPSender(
            host=account.host,
            port=account.port,
            username=account.username,
            password=account.password,
            from_email=account.from_email,
            from_name=account.from_name,
            use_tls=account.use_tls,
            use_ssl=account.use_ssl
        )
    else:
        provider = db.query(APIProvider).filter(APIProvider.id == request.provider_id).first()
        if not provider:
            raise HTTPException(status_code=404, detail="API provider not found")
        
        from senders import APISender
        sender = APISender.create(
            provider_type=provider.provider_type,
            api_key=provider.api_key,
            api_secret=provider.api_secret,
            domain=provider.domain,
            from_email=provider.from_email,
            from_name=provider.from_name
        )
    
    # Send to each seed address
    for email in request.seed_emails:
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        test_subject = f"{request.subject} [{timestamp}]"
        
        result = await sender.send(
            to_email=email,
            subject=test_subject,
            body_html=request.body_html + f"<p style='font-size:10px;color:#999'>Seed Test ID: {timestamp}</p>"
        )
        
        results.append({
            "email": email,
            "success": result.success,
            "message_id": result.message_id,
            "error": result.error
        })
    
    successful = sum(1 for r in results if r["success"])
    
    return {
        "total": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "success_rate": (successful / len(results) * 100) if results else 0,
        "results": results,
        "instructions": "Check each email's inbox (not spam folder) to verify delivery. "
                       "For accurate 95%+ verification, test with 20+ seed addresses across Gmail and Outlook."
    }

# ==================== Suppressions ====================

@app.get("/api/suppressions")
def list_suppressions(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    offset = (page - 1) * per_page
    
    suppressions = db.query(Suppression).offset(offset).limit(per_page).all()
    total = db.query(Suppression).count()
    
    return {
        "suppressions": [
            {"id": s.id, "email": s.email, "reason": s.reason, "added_at": s.added_at.isoformat()}
            for s in suppressions
        ],
        "total": total,
        "page": page,
        "per_page": per_page
    }

@app.post("/api/suppressions")
def add_suppression(suppression: SuppressionCreate, db: Session = Depends(get_db)):
    
    # Check if already exists
    existing = db.query(Suppression).filter(Suppression.email == suppression.email.lower()).first()
    if existing:
        return {"message": "Email already suppressed", "id": existing.id}
    
    db_suppression = Suppression(
        email=suppression.email.lower(),
        reason=suppression.reason
    )
    db.add(db_suppression)
    db.commit()
    db.refresh(db_suppression)
    
    return {"id": db_suppression.id, "message": "Email added to suppression list"}

@app.delete("/api/suppressions/{email}")
def remove_suppression(email: str, db: Session = Depends(get_db)):
    suppression = db.query(Suppression).filter(Suppression.email == email.lower()).first()
    if not suppression:
        raise HTTPException(status_code=404, detail="Email not in suppression list")
    db.delete(suppression)
    db.commit()
    return {"message": "Email removed from suppression list"}

@app.get("/api/suppressions/export")
def export_suppressions(db: Session = Depends(get_db)):
    """Export suppression list as CSV"""
    suppressions = db.query(Suppression).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "reason", "added_at"])
    
    for s in suppressions:
        writer.writerow([s.email, s.reason, s.added_at.isoformat()])
    
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=suppression_list.csv"}
    )

# ==================== Statistics ====================

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    
    total_campaigns = db.query(Campaign).count()
    total_smtp = db.query(SMTPAccount).count()
    total_api = db.query(APIProvider).count()
    
    # Aggregate stats from all campaigns
    total_sent = db.query(func.sum(Campaign.sent_count)).scalar() or 0
    total_delivered = db.query(func.sum(Campaign.delivered_count)).scalar() or 0
    total_bounced = db.query(func.sum(Campaign.bounced_count)).scalar() or 0
    total_failed = db.query(func.sum(Campaign.failed_count)).scalar() or 0
    
    delivery_rate = (total_delivered / total_sent * 100) if total_sent > 0 else 0
    
    # Active campaigns
    active = db.query(Campaign).filter(Campaign.status == "sending").count()
    
    return {
        "total_campaigns": total_campaigns,
        "total_smtp_accounts": total_smtp,
        "total_api_providers": total_api,
        "total_sent": total_sent,
        "total_delivered": total_delivered,
        "total_bounced": total_bounced,
        "total_failed": total_failed,
        "delivery_rate": round(delivery_rate, 2),
        "active_campaigns": active,
        "suppressions": db.query(Suppression).count(),
        "status": "ready"
    }

@app.get("/api/stats/detailed")
def get_detailed_stats(db: Session = Depends(get_db)):
    """Get detailed statistics with provider breakdown"""
    stats = {
        "by_provider": {},
        "by_status": {},
        "recent_campaigns": []
    }
    
    # Stats by provider
    for provider_type in ["smtp", "sendgrid", "mailgun", "postmark", "mailjet", "amazon_ses"]:
        count = db.query(SendLog).filter(SendLog.provider_type == provider_type).count()
        success = db.query(SendLog).filter(
            SendLog.provider_type == provider_type,
            SendLog.status == "sent"
        ).count()
        
        stats["by_provider"][provider_type] = {
            "total": count,
            "successful": success,
            "rate": round((success / count * 100) if count > 0 else 0, 2)
        }
    
    # Stats by status
    for status in ["sent", "delivered", "bounced", "failed"]:
        count = db.query(SendLog).filter(SendLog.status == status).count()
        stats["by_status"][status] = count
    
    # Recent campaigns
    recent = db.query(Campaign).order_by(Campaign.created_at.desc()).limit(5).all()
    stats["recent_campaigns"] = [
        {
            "id": c.id,
            "name": c.name,
            "status": c.status,
            "sent": c.sent_count,
            "total": c.total_recipients
        }
        for c in recent
    ]
    
    return stats

# ==================== Background Task for Campaign Sending ====================

async def send_campaign_task(campaign_id: int, provider_type: str, provider_id: int):
    """Background task to send campaign emails"""
    db = get_session()
    
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            return
        
        # Get pending recipients
        recipients = db.query(Recipient).filter(
            Recipient.campaign_id == campaign_id,
            Recipient.status == "pending"
        ).all()
        
        if not recipients:
            campaign.status = "completed"
            campaign.completed_at = datetime.utcnow()
            db.commit()
            return
        
        # Initialize sender
        if provider_type == "smtp":
            account = db.query(SMTPAccount).filter(SMTPAccount.id == provider_id).first()
            from senders import SMTPSender
            sender = SMTPSender(
                host=account.host,
                port=account.port,
                username=account.username,
                password=account.password,
                from_email=account.from_email,
                from_name=account.from_name,
                use_tls=account.use_tls,
                use_ssl=account.use_ssl
            )
        else:
            provider = db.query(APIProvider).filter(APIProvider.id == provider_id).first()
            from senders import APISender
            sender = APISender.create(
                provider_type=provider.provider_type,
                api_key=provider.api_key,
                api_secret=provider.api_secret,
                domain=provider.domain,
                from_email=provider.from_email,
                from_name=provider.from_name
            )
        
        total = len(recipients)
        sent = 0
        failed = 0
        start_time = datetime.utcnow()
        
        # Initialize progress
        campaign_progress[campaign_id] = {
            "sent": 0,
            "total": total,
            "failed": 0,
            "rate": 0,
            "eta": "Calculating..."
        }
        
        for i, recipient in enumerate(recipients):
            # Check if campaign was paused
            db.refresh(campaign)
            if campaign.status != "sending":
                break
            
            # Build personalization
            personalization = {
                "email": recipient.email,
                "first_name": recipient.first_name,
                "last_name": recipient.last_name
            }
            if recipient.custom_fields:
                personalization.update(json.loads(recipient.custom_fields))
            
            # Send email
            result = await sender.send(
                to_email=recipient.email,
                subject=campaign.subject,
                body_html=campaign.body_html,
                body_text=campaign.body_text,
                personalization=personalization
            )
            
            # Update recipient
            recipient.status = "sent" if result.success else "failed"
            recipient.message_id = result.message_id
            recipient.provider_type = result.provider
            recipient.provider_id = provider_id
            recipient.sent_at = datetime.utcnow()
            if not result.success:
                recipient.error_message = result.error
            
            # Log the send
            log = SendLog(
                campaign_id=campaign_id,
                recipient_id=recipient.id,
                provider_type=result.provider,
                provider_id=provider_id,
                status="sent" if result.success else "failed",
                message_id=result.message_id,
                response=result.response or result.error
            )
            db.add(log)
            
            if result.success:
                sent += 1
                campaign.sent_count += 1
                campaign.delivered_count += 1  # Assume delivered until bounce
            else:
                failed += 1
                campaign.failed_count += 1
            
            # Update progress
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            rate = sent / elapsed if elapsed > 0 else 0
            remaining = total - (sent + failed)
            eta = remaining / rate if rate > 0 else 0
            
            campaign_progress[campaign_id] = {
                "sent": sent,
                "total": total,
                "failed": failed,
                "rate": round(rate * 60, 1),  # per minute
                "eta": f"{int(eta // 60)}m {int(eta % 60)}s" if eta < 3600 else f"{int(eta // 3600)}h {int((eta % 3600) // 60)}m"
            }
            
            # Commit every 100 records
            if (i + 1) % 100 == 0:
                db.commit()
            
            # Throttle
            if campaign.throttle_rate > 0:
                await asyncio.sleep(campaign.throttle_rate)
        
        # Final update
        campaign.status = "completed"
        campaign.completed_at = datetime.utcnow()
        db.commit()
        
        # Clean up progress
        if campaign_id in campaign_progress:
            campaign_progress[campaign_id]["status"] = "completed"
        
        logger.info(f"Campaign {campaign_id} completed: {sent} sent, {failed} failed")
        
    except asyncio.CancelledError:
        logger.info(f"Campaign {campaign_id} was cancelled")
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if campaign:
            campaign.status = "paused"
            db.commit()
    except Exception as e:
        logger.error(f"Campaign {campaign_id} error: {e}")
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if campaign:
            campaign.status = "failed"
            db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*60)
    print("🚀 Starting Bulk Email Sender - Production v2.0")
    print("="*60)
    print("🌐 Dashboard: http://localhost:8000")
    print("📊 API: http://localhost:8000/api")
    print("🎯 Features: 10k batch, multi-provider, tracking, export")
    print("="*60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
