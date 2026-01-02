"""
Email Deliverability Utilities
Best practices for achieving 95%+ inbox rates across major providers
"""
import re
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Major email providers and their domains
MAJOR_PROVIDERS = {
    "gmail": ["gmail.com", "googlemail.com"],
    "outlook": ["outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.co.uk"],
    "yahoo": ["yahoo.com", "yahoo.co.uk", "yahoo.ca", "ymail.com", "rocketmail.com"],
    "aol": ["aol.com", "aim.com"],
    "icloud": ["icloud.com", "me.com", "mac.com"],
    "protonmail": ["protonmail.com", "protonmail.ch", "pm.me"],
    "zoho": ["zoho.com", "zohomail.com"],
    "gmx": ["gmx.de", "gmx.com", "gmx.net"],
    "mail": ["mail.com"]
}

# Spam trigger words to avoid
SPAM_TRIGGERS = [
    "free", "winner", "congratulations", "urgent", "act now", "limited time",
    "click here", "buy now", "order now", "special offer", "amazing offer",
    "100% free", "no obligation", "risk free", "guarantee", "million dollars",
    "cash bonus", "earn money", "work from home", "make money", "double your",
    "no cost", "no fees", "no credit check", "winner", "you have been selected",
    "claim your prize", "lottery", "casino", "poker", "betting"
]

def identify_provider(email: str) -> str:
    """Identify which major provider an email belongs to"""
    domain = email.split("@")[-1].lower()
    
    for provider, domains in MAJOR_PROVIDERS.items():
        if domain in domains:
            return provider
    
    return "other"

def get_provider_stats(recipients: List[str]) -> Dict[str, int]:
    """Get breakdown of recipients by email provider"""
    stats = {}
    for email in recipients:
        provider = identify_provider(email)
        stats[provider] = stats.get(provider, 0) + 1
    return stats

def check_spam_score(subject: str, body_html: str) -> Tuple[int, List[str]]:
    """
    Check content for spam triggers.
    Returns (score, list of triggers found)
    Lower score is better (0 = clean)
    """
    triggers_found = []
    text = f"{subject} {body_html}".lower()
    
    for trigger in SPAM_TRIGGERS:
        if trigger.lower() in text:
            triggers_found.append(trigger)
    
    # Additional checks
    caps_ratio = sum(1 for c in subject if c.isupper()) / max(len(subject), 1)
    if caps_ratio > 0.5:
        triggers_found.append("EXCESSIVE_CAPS")
    
    exclamation_count = subject.count("!") + body_html.count("!")
    if exclamation_count > 3:
        triggers_found.append("TOO_MANY_EXCLAMATIONS")
    
    # Check for suspicious links
    link_count = body_html.lower().count("href=")
    if link_count > 10:
        triggers_found.append("TOO_MANY_LINKS")
    
    return len(triggers_found), triggers_found

def get_deliverability_recommendations(
    from_domain: str,
    recipients: List[str],
    subject: str,
    body_html: str
) -> Dict:
    """
    Get comprehensive deliverability recommendations
    """
    recommendations = {
        "score": 100,
        "issues": [],
        "warnings": [],
        "provider_breakdown": get_provider_stats(recipients),
        "dns_requirements": [],
        "content_issues": []
    }
    
    # Check DNS requirements
    recommendations["dns_requirements"] = [
        f"Ensure SPF record includes your email provider for {from_domain}",
        f"Configure DKIM signing for {from_domain}",
        f"Set up DMARC policy for {from_domain}",
        "Consider setting up a dedicated sending subdomain (e.g., mail.yourdomain.com)"
    ]
    
    # Check content
    spam_score, triggers = check_spam_score(subject, body_html)
    if spam_score > 0:
        recommendations["score"] -= spam_score * 5
        recommendations["content_issues"] = triggers
        recommendations["warnings"].append(
            f"Found {spam_score} potential spam triggers: {', '.join(triggers)}"
        )
    
    # Check for plain text version
    if not body_html or len(body_html.strip()) < 50:
        recommendations["score"] -= 10
        recommendations["issues"].append("Email body is too short")
    
    # Check subject line
    if len(subject) < 10:
        recommendations["score"] -= 5
        recommendations["warnings"].append("Subject line is very short")
    elif len(subject) > 60:
        recommendations["score"] -= 5
        recommendations["warnings"].append("Subject line may be truncated in inbox")
    
    # Check for unsubscribe requirement
    if "unsubscribe" not in body_html.lower():
        recommendations["score"] -= 15
        recommendations["issues"].append(
            "Missing unsubscribe link (required for bulk email)"
        )
    
    # Provider-specific warnings
    gmail_count = recommendations["provider_breakdown"].get("gmail", 0)
    outlook_count = recommendations["provider_breakdown"].get("outlook", 0)
    
    if gmail_count > 0:
        recommendations["warnings"].append(
            f"Sending to {gmail_count} Gmail recipients - ensure SPF/DKIM/DMARC are configured"
        )
    
    if outlook_count > 0:
        recommendations["warnings"].append(
            f"Sending to {outlook_count} Outlook recipients - consider registering with Microsoft SNDS"
        )
    
    return recommendations

def generate_list_unsubscribe_header(unsubscribe_url: str, unsubscribe_email: str = None) -> Dict[str, str]:
    """
    Generate List-Unsubscribe headers for one-click unsubscribe
    Required for high-volume senders to Gmail
    """
    headers = {}
    
    if unsubscribe_email:
        headers["List-Unsubscribe"] = f"<mailto:{unsubscribe_email}>, <{unsubscribe_url}>"
    else:
        headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    
    # RFC 8058 - One-Click Unsubscribe
    headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    
    return headers

def generate_tracking_pixel(campaign_id: int, recipient_id: int, base_url: str) -> str:
    """Generate a 1x1 tracking pixel for open tracking"""
    token = hashlib.md5(f"{campaign_id}-{recipient_id}".encode()).hexdigest()
    return f'<img src="{base_url}/track/open/{campaign_id}/{recipient_id}/{token}" width="1" height="1" style="display:none" alt="">'

def wrap_links_for_tracking(html: str, campaign_id: int, recipient_id: int, base_url: str) -> str:
    """Wrap links in HTML for click tracking"""
    import urllib.parse
    
    def replace_link(match):
        original_url = match.group(1)
        encoded_url = urllib.parse.quote(original_url, safe='')
        tracking_url = f"{base_url}/track/click/{campaign_id}/{recipient_id}?url={encoded_url}"
        return f'href="{tracking_url}"'
    
    pattern = r'href="([^"]+)"'
    return re.sub(pattern, replace_link, html)

class DeliverabilityChecker:
    """
    Check and improve email deliverability
    """
    
    def __init__(self, from_domain: str):
        self.from_domain = from_domain
        self.dns_checked = False
        self.spf_valid = False
        self.dkim_valid = False
        self.dmarc_valid = False
    
    async def check_dns_records(self) -> Dict:
        """Check SPF, DKIM, DMARC records for the domain"""
        import dns.resolver
        
        results = {
            "spf": {"found": False, "record": None, "valid": False},
            "dkim": {"found": False, "selectors_checked": []},
            "dmarc": {"found": False, "record": None, "policy": None}
        }
        
        # Check SPF
        try:
            spf_records = dns.resolver.resolve(self.from_domain, 'TXT')
            for record in spf_records:
                txt = str(record).strip('"')
                if txt.startswith('v=spf1'):
                    results["spf"]["found"] = True
                    results["spf"]["record"] = txt
                    results["spf"]["valid"] = True
                    self.spf_valid = True
                    break
        except Exception as e:
            results["spf"]["error"] = str(e)
        
        # Check DMARC
        try:
            dmarc_domain = f"_dmarc.{self.from_domain}"
            dmarc_records = dns.resolver.resolve(dmarc_domain, 'TXT')
            for record in dmarc_records:
                txt = str(record).strip('"')
                if txt.startswith('v=DMARC1'):
                    results["dmarc"]["found"] = True
                    results["dmarc"]["record"] = txt
                    if 'p=reject' in txt:
                        results["dmarc"]["policy"] = "reject"
                    elif 'p=quarantine' in txt:
                        results["dmarc"]["policy"] = "quarantine"
                    else:
                        results["dmarc"]["policy"] = "none"
                    self.dmarc_valid = True
                    break
        except Exception as e:
            results["dmarc"]["error"] = str(e)
        
        # Check common DKIM selectors
        dkim_selectors = ["default", "google", "selector1", "selector2", "k1", "dkim"]
        for selector in dkim_selectors:
            try:
                dkim_domain = f"{selector}._domainkey.{self.from_domain}"
                dkim_records = dns.resolver.resolve(dkim_domain, 'TXT')
                results["dkim"]["found"] = True
                results["dkim"]["selectors_checked"].append({
                    "selector": selector,
                    "found": True
                })
                self.dkim_valid = True
                break
            except:
                results["dkim"]["selectors_checked"].append({
                    "selector": selector,
                    "found": False
                })
        
        self.dns_checked = True
        return results
    
    def get_inbox_probability(self, provider: str) -> Dict:
        """
        Estimate inbox probability based on DNS configuration
        """
        base_probability = {
            "gmail": 0.3,  # Very strict
            "outlook": 0.4,
            "yahoo": 0.5,
            "aol": 0.5,
            "icloud": 0.4,
            "protonmail": 0.6,
            "zoho": 0.7,
            "gmx": 0.7,
            "mail": 0.7,
            "other": 0.6
        }
        
        probability = base_probability.get(provider, 0.5)
        
        # Boost for proper DNS
        if self.spf_valid:
            probability += 0.15
        if self.dkim_valid:
            probability += 0.20
        if self.dmarc_valid:
            probability += 0.10
        
        # Cap at 0.99
        probability = min(probability, 0.99)
        
        return {
            "provider": provider,
            "estimated_probability": round(probability * 100, 1),
            "spf": self.spf_valid,
            "dkim": self.dkim_valid,
            "dmarc": self.dmarc_valid,
            "recommendations": self._get_recommendations(provider, probability)
        }
    
    def _get_recommendations(self, provider: str, current_prob: float) -> List[str]:
        """Get specific recommendations to improve deliverability"""
        recs = []
        
        if not self.spf_valid:
            recs.append("Add SPF record to your DNS")
        if not self.dkim_valid:
            recs.append("Configure DKIM signing with your email provider")
        if not self.dmarc_valid:
            recs.append("Add DMARC policy to your DNS")
        
        if provider == "gmail":
            recs.append("Register with Google Postmaster Tools")
            recs.append("Authenticate with ARC (Authenticated Received Chain)")
        elif provider == "outlook":
            recs.append("Register with Microsoft SNDS (Smart Network Data Services)")
            recs.append("Enroll in JMRP (Junk Mail Reporting Program)")
        elif provider in ["yahoo", "aol"]:
            recs.append("Register with Yahoo CFL (Complaint Feedback Loop)")
        
        if current_prob < 0.8:
            recs.append("Consider using a dedicated sending domain")
            recs.append("Warm up your domain gradually over 2-4 weeks")
        
        return recs


# Pre-built email templates optimized for deliverability
DELIVERABILITY_TEMPLATES = {
    "transactional": {
        "description": "Optimized for transactional emails (receipts, notifications)",
        "subject_template": "[{{company_name}}] {{action_description}}",
        "body_template": """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px;">
        <h1 style="color: #1a1a1a; margin-top: 0;">{{title}}</h1>
        <p>Hi {{first_name}},</p>
        {{content}}
        <p style="margin-top: 30px;">Best regards,<br>{{company_name}} Team</p>
    </div>
    <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #666;">
        <p>You received this email because you have an account with {{company_name}}.</p>
        <p>{{company_address}}</p>
        <p><a href="{{unsubscribe_url}}" style="color: #666;">Unsubscribe</a> | <a href="{{preferences_url}}" style="color: #666;">Email preferences</a></p>
    </div>
</body>
</html>
""",
        "tips": [
            "Use clear, action-oriented subject lines",
            "Include company name in subject",
            "Keep content focused on the transaction",
            "Always include physical address (CAN-SPAM)",
            "Include unsubscribe link even for transactional"
        ]
    },
    "notification": {
        "description": "Optimized for notification emails",
        "subject_template": "{{notification_type}}: {{brief_description}}",
        "tips": [
            "Be specific about the notification type",
            "Keep it brief and scannable",
            "Use clear call-to-action buttons"
        ]
    }
}
