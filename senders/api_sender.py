"""
API Email Senders - Production-Ready Implementations
Supports SendGrid, Mailgun, Postmark, Mailjet, Amazon SES
"""
import asyncio
import httpx
import hmac
import hashlib
import base64
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import re
import json

logger = logging.getLogger(__name__)

@dataclass
class SendResult:
    success: bool
    message_id: Optional[str] = None
    provider: str = ""
    recipient: str = ""
    error: Optional[str] = None
    response: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

class BaseAPISender(ABC):
    """Abstract base class for API email senders"""
    
    def __init__(self, from_email: str, from_name: str = ""):
        self.from_email = from_email
        self.from_name = from_name
        self._client: Optional[httpx.AsyncClient] = None
    
    @abstractmethod
    async def send(self, to_email: str, subject: str, body_html: str, body_text: str = "") -> SendResult:
        pass
    
    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        pass
    
    def _personalize(self, template: str, data: Dict[str, str]) -> str:
        """Replace {{variable}} placeholders"""
        result = template
        for key, value in data.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, str(value) if value else "")
        return result
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text"""
        text = re.sub(r'<[^>]+>', '', html)
        return re.sub(r'\s+', ' ', text).strip()
    
    async def send_batch(
        self,
        recipients: List[Dict[str, Any]],
        subject: str,
        body_html: str,
        body_text: str = "",
        throttle_rate: float = 0.05,
        progress_callback=None
    ) -> List[SendResult]:
        """Send batch of emails with throttling"""
        results = []
        total = len(recipients)
        
        for i, recipient in enumerate(recipients):
            email = recipient.get('email')
            if not email:
                continue
            
            personalization = {
                'email': email,
                'first_name': recipient.get('first_name', ''),
                'last_name': recipient.get('last_name', ''),
                **{k: v for k, v in recipient.items() if k not in ['email', 'first_name', 'last_name']}
            }
            
            personalized_subject = self._personalize(subject, personalization)
            personalized_html = self._personalize(body_html, personalization)
            personalized_text = self._personalize(body_text, personalization) if body_text else ""
            
            result = await self.send(
                to_email=email,
                subject=personalized_subject,
                body_html=personalized_html,
                body_text=personalized_text
            )
            
            results.append(result)
            
            if progress_callback:
                await progress_callback(i + 1, total, result)
            
            if throttle_rate > 0 and i < total - 1:
                await asyncio.sleep(throttle_rate)
        
        return results


class SendGridSender(BaseAPISender):
    """SendGrid Mail Send API v3"""
    
    API_URL = "https://api.sendgrid.com/v3/mail/send"
    
    def __init__(self, api_key: str, from_email: str, from_name: str = ""):
        super().__init__(from_email, from_name)
        self.api_key = api_key
        self.provider_name = "sendgrid"
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test SendGrid API connection"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.sendgrid.com/v3/user/profile",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                if response.status_code == 200:
                    return {"success": True, "message": "SendGrid API connected", "provider": self.provider_name}
                else:
                    return {"success": False, "message": f"API error: {response.status_code}", "provider": self.provider_name}
        except Exception as e:
            return {"success": False, "message": str(e), "provider": self.provider_name}
    
    async def send(self, to_email: str, subject: str, body_html: str, body_text: str = "") -> SendResult:
        """Send email via SendGrid API"""
        try:
            payload = {
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": self.from_email, "name": self.from_name} if self.from_name else {"email": self.from_email},
                "subject": subject,
                "content": []
            }
            
            if body_text:
                payload["content"].append({"type": "text/plain", "value": body_text})
            else:
                payload["content"].append({"type": "text/plain", "value": self._html_to_text(body_html)})
            
            payload["content"].append({"type": "text/html", "value": body_html})
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code in [200, 202]:
                    message_id = response.headers.get("X-Message-Id", "")
                    return SendResult(
                        success=True,
                        message_id=message_id,
                        provider=self.provider_name,
                        recipient=to_email,
                        response=f"Status: {response.status_code}"
                    )
                else:
                    return SendResult(
                        success=False,
                        provider=self.provider_name,
                        recipient=to_email,
                        error=f"API error: {response.status_code} - {response.text}"
                    )
                    
        except Exception as e:
            logger.error(f"SendGrid send error: {e}")
            return SendResult(success=False, provider=self.provider_name, recipient=to_email, error=str(e))


class MailgunSender(BaseAPISender):
    """Mailgun Send API"""
    
    def __init__(self, api_key: str, domain: str, from_email: str, from_name: str = "", region: str = "us"):
        super().__init__(from_email, from_name)
        self.api_key = api_key
        self.domain = domain
        self.provider_name = "mailgun"
        self.base_url = f"https://api.{'eu.' if region == 'eu' else ''}mailgun.net/v3/{domain}"
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test Mailgun API connection"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/stats/total",
                    auth=("api", self.api_key),
                    params={"event": "accepted", "duration": "1h"}
                )
                if response.status_code == 200:
                    return {"success": True, "message": "Mailgun API connected", "provider": self.provider_name}
                else:
                    return {"success": False, "message": f"API error: {response.status_code}", "provider": self.provider_name}
        except Exception as e:
            return {"success": False, "message": str(e), "provider": self.provider_name}
    
    async def send(self, to_email: str, subject: str, body_html: str, body_text: str = "") -> SendResult:
        """Send email via Mailgun API"""
        try:
            from_addr = f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email
            
            data = {
                "from": from_addr,
                "to": to_email,
                "subject": subject,
                "html": body_html,
                "text": body_text if body_text else self._html_to_text(body_html)
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    auth=("api", self.api_key),
                    data=data,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    message_id = result.get("id", "")
                    return SendResult(
                        success=True,
                        message_id=message_id,
                        provider=self.provider_name,
                        recipient=to_email,
                        response=result.get("message", "")
                    )
                else:
                    return SendResult(
                        success=False,
                        provider=self.provider_name,
                        recipient=to_email,
                        error=f"API error: {response.status_code} - {response.text}"
                    )
                    
        except Exception as e:
            logger.error(f"Mailgun send error: {e}")
            return SendResult(success=False, provider=self.provider_name, recipient=to_email, error=str(e))


class PostmarkSender(BaseAPISender):
    """Postmark Email API - Best for transactional email, 99%+ inbox rate"""
    
    API_URL = "https://api.postmarkapp.com/email"
    
    def __init__(self, server_token: str, from_email: str, from_name: str = ""):
        super().__init__(from_email, from_name)
        self.server_token = server_token
        self.provider_name = "postmark"
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test Postmark API connection"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.postmarkapp.com/server",
                    headers={
                        "X-Postmark-Server-Token": self.server_token,
                        "Accept": "application/json"
                    }
                )
                if response.status_code == 200:
                    server_info = response.json()
                    return {
                        "success": True,
                        "message": f"Postmark connected: {server_info.get('Name', 'Unknown')}",
                        "provider": self.provider_name
                    }
                else:
                    return {"success": False, "message": f"API error: {response.status_code}", "provider": self.provider_name}
        except Exception as e:
            return {"success": False, "message": str(e), "provider": self.provider_name}
    
    async def send(self, to_email: str, subject: str, body_html: str, body_text: str = "") -> SendResult:
        """Send email via Postmark API"""
        try:
            payload = {
                "From": f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email,
                "To": to_email,
                "Subject": subject,
                "HtmlBody": body_html,
                "TextBody": body_text if body_text else self._html_to_text(body_html),
                "MessageStream": "outbound"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.API_URL,
                    json=payload,
                    headers={
                        "X-Postmark-Server-Token": self.server_token,
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return SendResult(
                        success=True,
                        message_id=result.get("MessageID", ""),
                        provider=self.provider_name,
                        recipient=to_email,
                        response=result.get("Message", "")
                    )
                else:
                    error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                    return SendResult(
                        success=False,
                        provider=self.provider_name,
                        recipient=to_email,
                        error=error_data.get("Message", f"API error: {response.status_code}")
                    )
                    
        except Exception as e:
            logger.error(f"Postmark send error: {e}")
            return SendResult(success=False, provider=self.provider_name, recipient=to_email, error=str(e))


class MailjetSender(BaseAPISender):
    """Mailjet Send API v3.1"""
    
    API_URL = "https://api.mailjet.com/v3.1/send"
    
    def __init__(self, api_key: str, api_secret: str, from_email: str, from_name: str = ""):
        super().__init__(from_email, from_name)
        self.api_key = api_key
        self.api_secret = api_secret
        self.provider_name = "mailjet"
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test Mailjet API connection"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.mailjet.com/v3/REST/apikey",
                    auth=(self.api_key, self.api_secret)
                )
                if response.status_code == 200:
                    return {"success": True, "message": "Mailjet API connected", "provider": self.provider_name}
                else:
                    return {"success": False, "message": f"API error: {response.status_code}", "provider": self.provider_name}
        except Exception as e:
            return {"success": False, "message": str(e), "provider": self.provider_name}
    
    async def send(self, to_email: str, subject: str, body_html: str, body_text: str = "") -> SendResult:
        """Send email via Mailjet API"""
        try:
            payload = {
                "Messages": [{
                    "From": {"Email": self.from_email, "Name": self.from_name},
                    "To": [{"Email": to_email}],
                    "Subject": subject,
                    "HTMLPart": body_html,
                    "TextPart": body_text if body_text else self._html_to_text(body_html)
                }]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.API_URL,
                    json=payload,
                    auth=(self.api_key, self.api_secret),
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    messages = result.get("Messages", [{}])
                    if messages and messages[0].get("Status") == "success":
                        return SendResult(
                            success=True,
                            message_id=str(messages[0].get("To", [{}])[0].get("MessageID", "")),
                            provider=self.provider_name,
                            recipient=to_email,
                            response="success"
                        )
                    else:
                        return SendResult(
                            success=False,
                            provider=self.provider_name,
                            recipient=to_email,
                            error=str(messages[0].get("Errors", "Unknown error"))
                        )
                else:
                    return SendResult(
                        success=False,
                        provider=self.provider_name,
                        recipient=to_email,
                        error=f"API error: {response.status_code}"
                    )
                    
        except Exception as e:
            logger.error(f"Mailjet send error: {e}")
            return SendResult(success=False, provider=self.provider_name, recipient=to_email, error=str(e))


class AmazonSESSender(BaseAPISender):
    """Amazon SES via SMTP interface (simpler than SigV4 API)"""
    
    REGIONS = {
        "us-east-1": "email-smtp.us-east-1.amazonaws.com",
        "us-west-2": "email-smtp.us-west-2.amazonaws.com",
        "eu-west-1": "email-smtp.eu-west-1.amazonaws.com",
        "eu-central-1": "email-smtp.eu-central-1.amazonaws.com",
        "ap-southeast-1": "email-smtp.ap-southeast-1.amazonaws.com",
        "ap-southeast-2": "email-smtp.ap-southeast-2.amazonaws.com",
    }
    
    def __init__(self, smtp_username: str, smtp_password: str, from_email: str, from_name: str = "", region: str = "us-east-1"):
        super().__init__(from_email, from_name)
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.region = region
        self.smtp_host = self.REGIONS.get(region, self.REGIONS["us-east-1"])
        self.provider_name = "amazon_ses"
        self._smtp_sender = None
    
    async def _get_smtp_sender(self):
        """Get SMTP sender for SES"""
        if not self._smtp_sender:
            from .smtp_sender import SMTPSender
            self._smtp_sender = SMTPSender(
                host=self.smtp_host,
                port=587,
                username=self.smtp_username,
                password=self.smtp_password,
                from_email=self.from_email,
                from_name=self.from_name,
                use_tls=True
            )
        return self._smtp_sender
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test SES SMTP connection"""
        try:
            sender = await self._get_smtp_sender()
            result = await sender.test_connection()
            result["provider"] = self.provider_name
            return result
        except Exception as e:
            return {"success": False, "message": str(e), "provider": self.provider_name}
    
    async def send(self, to_email: str, subject: str, body_html: str, body_text: str = "") -> SendResult:
        """Send email via Amazon SES SMTP"""
        try:
            sender = await self._get_smtp_sender()
            result = await sender.send(to_email, subject, body_html, body_text)
            result.provider = self.provider_name
            return result
        except Exception as e:
            return SendResult(success=False, provider=self.provider_name, recipient=to_email, error=str(e))


class APISender:
    """Factory class to create appropriate API sender"""
    
    @staticmethod
    def create(provider_type: str, **kwargs) -> BaseAPISender:
        """Create sender based on provider type"""
        providers = {
            "sendgrid": lambda: SendGridSender(
                api_key=kwargs["api_key"],
                from_email=kwargs["from_email"],
                from_name=kwargs.get("from_name", "")
            ),
            "mailgun": lambda: MailgunSender(
                api_key=kwargs["api_key"],
                domain=kwargs["domain"],
                from_email=kwargs["from_email"],
                from_name=kwargs.get("from_name", ""),
                region=kwargs.get("region", "us")
            ),
            "postmark": lambda: PostmarkSender(
                server_token=kwargs["api_key"],
                from_email=kwargs["from_email"],
                from_name=kwargs.get("from_name", "")
            ),
            "mailjet": lambda: MailjetSender(
                api_key=kwargs["api_key"],
                api_secret=kwargs["api_secret"],
                from_email=kwargs["from_email"],
                from_name=kwargs.get("from_name", "")
            ),
            "amazon_ses": lambda: AmazonSESSender(
                smtp_username=kwargs["api_key"],
                smtp_password=kwargs["api_secret"],
                from_email=kwargs["from_email"],
                from_name=kwargs.get("from_name", ""),
                region=kwargs.get("region", "us-east-1")
            )
        }
        
        if provider_type not in providers:
            raise ValueError(f"Unknown provider: {provider_type}. Supported: {list(providers.keys())}")
        
        return providers[provider_type]()
