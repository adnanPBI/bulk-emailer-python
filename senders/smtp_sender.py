"""
SMTP Email Sender - Production-Ready Implementation
Supports async sending, connection pooling, retry logic, and delivery tracking
"""
import asyncio
import aiosmtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate, make_msgid
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)

@dataclass
class SendResult:
    success: bool
    message_id: Optional[str] = None
    provider: str = "smtp"
    recipient: str = ""
    error: Optional[str] = None
    response: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

class SMTPSender:
    """
    Async SMTP email sender with connection management and retry logic.
    Optimized for high-volume transactional email sending.
    """
    
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client = None
        
    async def connect(self) -> bool:
        """Establish SMTP connection"""
        try:
            ssl_context = ssl.create_default_context() if (self.use_ssl or self.use_tls) else None
            
            self._client = aiosmtplib.SMTP(
                hostname=self.host,
                port=self.port,
                timeout=self.timeout,
                use_tls=self.use_ssl,
                tls_context=ssl_context if self.use_ssl else None
            )
            
            await self._client.connect()
            
            if self.use_tls and not self.use_ssl:
                await self._client.starttls(tls_context=ssl_context)
            
            await self._client.login(self.username, self.password)
            logger.info(f"Connected to SMTP server {self.host}:{self.port}")
            return True
            
        except Exception as e:
            logger.error(f"SMTP connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Close SMTP connection"""
        if self._client:
            try:
                await self._client.quit()
            except:
                pass
            self._client = None
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test SMTP connection and return status"""
        try:
            connected = await self.connect()
            if connected:
                await self.disconnect()
                return {
                    "success": True,
                    "message": f"Successfully connected to {self.host}:{self.port}",
                    "provider": "smtp"
                }
            else:
                return {
                    "success": False,
                    "message": "Connection failed",
                    "provider": "smtp"
                }
        except Exception as e:
            return {
                "success": False,
                "message": str(e),
                "provider": "smtp"
            }
    
    def _build_message(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str = "",
        reply_to: str = None,
        custom_headers: Dict[str, str] = None
    ) -> MIMEMultipart:
        """Build MIME message with proper headers for deliverability"""
        msg = MIMEMultipart('alternative')
        
        # From header
        if self.from_name:
            msg['From'] = formataddr((self.from_name, self.from_email))
        else:
            msg['From'] = self.from_email
        
        msg['To'] = to_email
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid(domain=self.from_email.split('@')[1])
        
        # Reply-To
        if reply_to:
            msg['Reply-To'] = reply_to
        
        # Headers for better deliverability
        msg['X-Mailer'] = 'BulkEmailPlatform/1.0'
        msg['MIME-Version'] = '1.0'
        msg['X-Priority'] = '3'  # Normal priority
        
        # Custom headers
        if custom_headers:
            for key, value in custom_headers.items():
                msg[key] = value
        
        # Add plain text version (important for deliverability)
        if body_text:
            text_part = MIMEText(body_text, 'plain', 'utf-8')
            msg.attach(text_part)
        else:
            # Auto-generate plain text from HTML
            plain_text = re.sub(r'<[^>]+>', '', body_html)
            plain_text = re.sub(r'\s+', ' ', plain_text).strip()
            text_part = MIMEText(plain_text, 'plain', 'utf-8')
            msg.attach(text_part)
        
        # Add HTML version
        html_part = MIMEText(body_html, 'html', 'utf-8')
        msg.attach(html_part)
        
        return msg
    
    def _personalize(self, template: str, data: Dict[str, str]) -> str:
        """Replace {{variable}} placeholders with actual values"""
        result = template
        for key, value in data.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, str(value) if value else "")
        return result
    
    async def send(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str = "",
        personalization: Dict[str, str] = None,
        reply_to: str = None
    ) -> SendResult:
        """Send a single email with retry logic"""
        
        # Personalize content
        if personalization:
            subject = self._personalize(subject, personalization)
            body_html = self._personalize(body_html, personalization)
            if body_text:
                body_text = self._personalize(body_text, personalization)
        
        last_error = None
        for attempt in range(self.max_retries):
            try:
                # Ensure connection
                if not self._client:
                    await self.connect()
                
                # Build message
                msg = self._build_message(
                    to_email=to_email,
                    subject=subject,
                    body_html=body_html,
                    body_text=body_text,
                    reply_to=reply_to
                )
                
                # Send
                response = await self._client.send_message(msg)
                message_id = msg['Message-ID']
                
                logger.info(f"Email sent to {to_email}, Message-ID: {message_id}")
                
                return SendResult(
                    success=True,
                    message_id=message_id,
                    provider="smtp",
                    recipient=to_email,
                    response=str(response)
                )
                
            except aiosmtplib.SMTPException as e:
                last_error = str(e)
                logger.warning(f"SMTP error (attempt {attempt + 1}): {e}")
                
                # Reconnect on connection errors
                await self.disconnect()
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"Send error: {e}")
                break
        
        return SendResult(
            success=False,
            provider="smtp",
            recipient=to_email,
            error=last_error
        )
    
    async def send_batch(
        self,
        recipients: List[Dict[str, Any]],
        subject: str,
        body_html: str,
        body_text: str = "",
        throttle_rate: float = 0.1,
        progress_callback=None
    ) -> List[SendResult]:
        """
        Send batch of emails with throttling.
        
        recipients: List of dicts with 'email' and optional personalization fields
        throttle_rate: Seconds between emails (0.1 = 600/min)
        progress_callback: async function(sent, total, result) for progress updates
        """
        results = []
        total = len(recipients)
        
        try:
            await self.connect()
            
            for i, recipient in enumerate(recipients):
                email = recipient.get('email')
                if not email:
                    continue
                
                # Build personalization data
                personalization = {
                    'email': email,
                    'first_name': recipient.get('first_name', ''),
                    'last_name': recipient.get('last_name', ''),
                    **{k: v for k, v in recipient.items() if k not in ['email', 'first_name', 'last_name']}
                }
                
                result = await self.send(
                    to_email=email,
                    subject=subject,
                    body_html=body_html,
                    body_text=body_text,
                    personalization=personalization
                )
                
                results.append(result)
                
                # Progress callback
                if progress_callback:
                    await progress_callback(i + 1, total, result)
                
                # Throttle
                if throttle_rate > 0 and i < total - 1:
                    await asyncio.sleep(throttle_rate)
                    
        except Exception as e:
            logger.error(f"Batch send error: {e}")
        finally:
            await self.disconnect()
        
        return results
