"""E-mail notifications through the organization's own mail server (SMTP).

Disabled unless SMTP_HOST is set. Messages go only to the addresses configured in REQUEST_NOTIFY_EMAILS, never
to addresses taken from user input or model output.
"""

import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Optional

from src.core.config import (
    ORGANIZATION_NAME,
    REQUEST_NOTIFY_EMAILS,
    REQUEST_NOTIFY_INCLUDE_DETAILS,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_STARTTLS,
    SMTP_TIMEOUT_SECONDS,
    SMTP_USERNAME,
)
from src.core.logger import get_logger

logger = get_logger("Notifier")


def email_enabled() -> bool:
    return bool(SMTP_HOST)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text e-mail; returns False (and logs) when e-mail is disabled or sending fails."""
    if not email_enabled() or not to:
        return False
    message = EmailMessage()
    message["From"] = SMTP_FROM or SMTP_USERNAME
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            if SMTP_STARTTLS:
                smtp.starttls()
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.error(f"E-mail to {to} could not be sent: {e}")
        return False


def request_recipient(category: str) -> Optional[str]:
    """Address responsible for a request category ('default' covers categories without their own address)."""
    return REQUEST_NOTIFY_EMAILS.get(category) or REQUEST_NOTIFY_EMAILS.get("default")


def notify_new_request(request: Dict[str, Any]) -> bool:
    """E-mail the responsible unit about a new service request; True if a message was sent."""
    to = request_recipient(request["category"])
    if not to:
        return False
    sender = ORGANIZATION_NAME or "AI Assistant"
    subject = f"[{sender}] New request #{request['id']} ({request['category']})"
    body = (
        f"A new service request was filed through the AI assistant.\n\n"
        f"Request:   #{request['id']}\n"
        f"Category:  {request['category']}\n"
        f"Created:   {request['created_at']}\n"
    )
    if REQUEST_NOTIFY_INCLUDE_DETAILS:
        subject += f": {request['title']}"
        body += (
            f"Requester: {request['username']}\n"
            f"Title:     {request['title']}\n\n"
            f"{request.get('description') or ''}\n"
        )
    else:
        body += "\nThe details are available to staff in the application (My Requests > all users).\n"
    sent = send_email(to, subject, body)
    if sent:
        logger.info(f"Request #{request['id']} notification sent to {to}.")
    return sent
