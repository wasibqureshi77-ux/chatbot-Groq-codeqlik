import os
import logging
from email.message import EmailMessage
from smtplib import SMTP
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_ENABLED = os.getenv("SMTP_ENABLED", "true").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "anuraglawaniya913@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or os.getenv("SMTP_PASS") or "aqob onef lwrk xuzw"
MAIL_FROM = os.getenv("MAIL_FROM") or os.getenv("FROM_EMAIL") or "no-reply@example.com"
FROM_NAME = os.getenv("FROM_NAME") or "CodeQlik Chatbot"
ADMIN_NOTIFY_EMAIL = os.getenv("ADMIN_NOTIFY_EMAIL") or os.getenv("SMTP_USER") or "anuraglawaniya913@gmail.com"


def send_email(to: str, subject: str, html: str, text: str = "", from_email: str = None, from_name: str = None) -> dict:
    """
    Sends an email using standard SMTP.
    Matches the signature of the old mail-service client send_email function.
    """
    if not SMTP_ENABLED:
        logger.info("SMTP is disabled. Skipping email.")
        return {"success": False, "error": "SMTP disabled"}

    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        logger.warning("SMTP host, user or password missing. Email not sent.")
        return {"success": False, "error": "SMTP configuration missing"}

    message = EmailMessage()
    sender_name = from_name or FROM_NAME
    sender_email = from_email or MAIL_FROM
    message["From"] = f"{sender_name} <{sender_email}>"
    message["To"] = to
    message["Subject"] = subject

    if html:
        message.set_content(text or html)
        message.add_alternative(html, subtype="html")
    else:
        message.set_content(text or "")

    try:
        with SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            if SMTP_PORT == 587:
                smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)
        logger.info(f"Email sent successfully to {to}.")
        return {"success": True}
    except Exception as e:
        logger.exception(f"Failed to send email to {to}: {e}")
        return {"success": False, "error": str(e)}


def send_chat_started_email(
    visitor_message: str,
    visitor_id: str | None = None,
    page_url: str | None = None,
    notify_email: str | None = None,
    company_name: str | None = "CodeQlik",
):
    """
    Runs in FastAPI BackgroundTasks to send email when chat is started.
    """
    to_email = notify_email or ADMIN_NOTIFY_EMAIL
    if not to_email:
        logger.warning("Admin notify email missing. Skipping chat started email.")
        return

    subject = f"New chat started - {company_name}"
    body = f"""
New chat has started on the chatbot.

Company: {company_name}
Visitor ID / Thread ID: {visitor_id or "Unknown"}
Page URL: {page_url or "Unknown"}

First Message:
{visitor_message}
"""
    send_email(to=to_email, subject=subject, html="", text=body)
