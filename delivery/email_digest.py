"""
delivery/email_digest.py — Send HTML digest via SMTP email.
"""
import smtplib, logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL

logger = logging.getLogger("email_digest")


def send_html_email(subject: str, html_body: str, to: str = None) -> bool:
    recipient = to or ALERT_EMAIL
    if not all([SMTP_USER, SMTP_PASS, recipient]):
        logger.info("[EMAIL] Not configured — skipping.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = recipient
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        logger.info("[EMAIL] Sent '%s' to %s", subject, recipient)
        return True
    except Exception as e:
        logger.warning("[EMAIL] Failed: %s", e)
        return False
