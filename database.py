"""
Database Models for Bulk Email Sender - Production Version
SQLAlchemy models with full tracking and delivery capabilities
"""
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean, 
    Float, DateTime, ForeignKey, Index, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()

# ==================== Provider Models ====================

class SMTPAccount(Base):
    """SMTP server configuration for sending emails"""
    __tablename__ = "smtp_accounts"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=587)
    username = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)  # Should be encrypted in production
    from_email = Column(String(255), nullable=False)
    from_name = Column(String(100), default="")
    reply_to = Column(String(255))
    use_tls = Column(Boolean, default=True)
    use_ssl = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    max_per_hour = Column(Integer, default=500)
    max_per_day = Column(Integer, default=10000)
    sent_this_hour = Column(Integer, default=0)
    sent_today = Column(Integer, default=0)
    last_reset_hour = Column(DateTime)
    last_reset_day = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class APIProvider(Base):
    """API-based email provider configuration (SendGrid, Mailgun, etc.)"""
    __tablename__ = "api_providers"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    provider_type = Column(String(50), nullable=False)  # sendgrid, mailgun, postmark, mailjet, amazon_ses
    api_key = Column(String(500), nullable=False)  # Should be encrypted
    api_secret = Column(String(500), default="")
    domain = Column(String(255), default="")  # Required for Mailgun
    region = Column(String(50), default="us")  # For regional endpoints
    from_email = Column(String(255), nullable=False)
    from_name = Column(String(100), default="")
    reply_to = Column(String(255))
    enabled = Column(Boolean, default=True)
    max_per_hour = Column(Integer, default=1000)
    max_per_day = Column(Integer, default=50000)
    sent_this_hour = Column(Integer, default=0)
    sent_today = Column(Integer, default=0)
    last_reset_hour = Column(DateTime)
    last_reset_day = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IMAPAccount(Base):
    """IMAP/POP3 configuration for bounce processing"""
    __tablename__ = "imap_accounts"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    protocol = Column(String(10), default="imap")  # imap or pop3
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=993)
    username = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)
    use_ssl = Column(Boolean, default=True)
    folder = Column(String(100), default="INBOX")
    enabled = Column(Boolean, default=True)
    last_check = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


# ==================== Campaign Models ====================

class Campaign(Base):
    """Email campaign with tracking"""
    __tablename__ = "campaigns"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    subject = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False)
    body_text = Column(Text, default="")
    from_email = Column(String(255))
    from_name = Column(String(100))
    reply_to = Column(String(255))
    
    # Status
    status = Column(String(20), default="draft")  # draft, sending, paused, completed, failed
    
    # Counts
    total_recipients = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    delivered_count = Column(Integer, default=0)
    opened_count = Column(Integer, default=0)
    clicked_count = Column(Integer, default=0)
    bounced_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    
    # Settings
    throttle_rate = Column(Float, default=0.1)  # seconds between sends
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Relationships
    recipients = relationship("Recipient", back_populates="campaign", cascade="all, delete-orphan")
    send_logs = relationship("SendLog", back_populates="campaign", cascade="all, delete-orphan")


class Recipient(Base):
    """Email recipient with personalization and tracking"""
    __tablename__ = "recipients"
    
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    
    # Contact info
    email = Column(String(255), nullable=False)
    first_name = Column(String(100), default="")
    last_name = Column(String(100), default="")
    custom_fields = Column(Text, default="{}")  # JSON for additional personalization
    
    # Delivery status
    status = Column(String(20), default="pending")  # pending, sent, delivered, opened, bounced, failed
    message_id = Column(String(255))
    provider_type = Column(String(50))
    provider_id = Column(Integer)
    
    # Error tracking
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime)
    delivered_at = Column(DateTime)
    opened_at = Column(DateTime)
    bounced_at = Column(DateTime)
    
    # Relationship
    campaign = relationship("Campaign", back_populates="recipients")
    
    __table_args__ = (
        Index("idx_recipient_campaign_email", "campaign_id", "email"),
        Index("idx_recipient_status", "status"),
    )


class SendLog(Base):
    """Detailed log of every send attempt"""
    __tablename__ = "send_logs"
    
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("recipients.id", ondelete="CASCADE"), nullable=False)
    
    # Provider info
    provider_type = Column(String(50))  # smtp, sendgrid, mailgun, etc.
    provider_id = Column(Integer)
    
    # Status
    status = Column(String(20))  # sent, failed, bounced
    message_id = Column(String(255))
    response = Column(Text)  # Provider response or error message
    
    # Timestamp
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    campaign = relationship("Campaign", back_populates="send_logs")
    
    __table_args__ = (
        Index("idx_sendlog_campaign", "campaign_id"),
        Index("idx_sendlog_timestamp", "timestamp"),
    )


class BounceRecord(Base):
    """Bounce tracking for deliverability management"""
    __tablename__ = "bounces"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    bounce_type = Column(String(20))  # hard, soft
    bounce_code = Column(String(20))
    reason = Column(Text)
    message_id = Column(String(255))
    provider = Column(String(50))
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="SET NULL"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_bounce_email", "email"),
    )


# ==================== Suppression and Settings ====================

class Suppression(Base):
    """Email suppression list (unsubscribes, bounces, complaints)"""
    __tablename__ = "suppressions"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    reason = Column(String(50), default="manual")  # bounce, complaint, unsubscribe, manual
    source = Column(String(100))  # Where this suppression came from
    added_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_suppression_email", "email"),
    )


class EmailTemplate(Base):
    """Reusable email templates"""
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    subject = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False)
    body_text = Column(Text, default="")
    category = Column(String(50), default="general")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Setting(Base):
    """Application settings"""
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(Text)
    description = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==================== Seed Test Tracking ====================

class SeedTest(Base):
    """Track inbox placement seed tests"""
    __tablename__ = "seed_tests"
    
    id = Column(Integer, primary_key=True)
    provider_type = Column(String(50), nullable=False)
    provider_id = Column(Integer)
    
    # Test configuration
    subject = Column(String(500))
    total_seeds = Column(Integer, default=0)
    
    # Results
    sent_count = Column(Integer, default=0)
    inbox_count = Column(Integer, default=0)  # Confirmed in inbox
    spam_count = Column(Integer, default=0)   # Found in spam
    missing_count = Column(Integer, default=0)  # Not found
    
    # Calculated rate
    inbox_rate = Column(Float, default=0.0)  # Percentage reaching inbox
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    # Relationship
    results = relationship("SeedTestResult", back_populates="test", cascade="all, delete-orphan")


class SeedTestResult(Base):
    """Individual seed test results"""
    __tablename__ = "seed_test_results"
    
    id = Column(Integer, primary_key=True)
    test_id = Column(Integer, ForeignKey("seed_tests.id", ondelete="CASCADE"), nullable=False)
    
    email = Column(String(255), nullable=False)
    email_type = Column(String(20))  # gmail, outlook, yahoo, other
    message_id = Column(String(255))
    
    # Status: sent, inbox, spam, missing, pending
    status = Column(String(20), default="pending")
    
    # Timestamps
    sent_at = Column(DateTime)
    checked_at = Column(DateTime)
    
    # Relationship
    test = relationship("SeedTest", back_populates="results")


# ==================== Database Initialization ====================

DEFAULT_DATABASE_URL = "postgresql+psycopg2://bulk_email:bulk_email@localhost:5432/bulk_email"


def get_database_url() -> str:
    """
    Resolve the database URL from environment.

    Expected format (PostgreSQL):
      postgresql+psycopg2://user:password@host:5432/dbname
    """
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if url.startswith("sqlite:"):
        raise ValueError("SQLite is not supported in this repo anymore; set DATABASE_URL to a PostgreSQL URL.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if not (url.startswith("postgresql://") or url.startswith("postgresql+")):
        raise ValueError(
            "Unsupported DATABASE_URL scheme; expected a PostgreSQL URL starting with 'postgresql://', 'postgresql+', or 'postgres://'."
        )
    return url


def init_db(database_url: str | None = None):
    """Initialize the database engine and session factory (PostgreSQL by default)."""
    url = database_url or get_database_url()
    engine = create_engine(url, echo=False, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, SessionLocal

engine, SessionLocal = init_db()


def create_tables():
    """Create all tables (intended to run on app startup)."""
    Base.metadata.create_all(bind=engine)


def get_session():
    """Get a new database session (caller must close)."""
    return SessionLocal()


def get_db():
    """FastAPI dependency that provides a DB session and guarantees cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
