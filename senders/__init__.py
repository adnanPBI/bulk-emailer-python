"""
Email Senders Package
Production-ready email sending implementations for multiple providers
"""

from .smtp_sender import SMTPSender, SendResult
from .api_sender import (
    APISender,
    BaseAPISender,
    SendGridSender,
    MailgunSender,
    PostmarkSender,
    MailjetSender,
    AmazonSESSender
)

__all__ = [
    'SMTPSender',
    'SendResult',
    'APISender',
    'BaseAPISender',
    'SendGridSender',
    'MailgunSender',
    'PostmarkSender',
    'MailjetSender',
    'AmazonSESSender'
]
