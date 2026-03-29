import os
import smtplib
import requests
from email.mime.text import MIMEText
from logger import get_logger

logger = get_logger("alerts")

class AlertManager:
    def __init__(self):
        self.email_from = os.getenv("ALERT_EMAIL_FROM")
        self.email_to = os.getenv("ALERT_EMAIL_TO")
        self.email_password = os.getenv("ALERT_EMAIL_PASSWORD")
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))

    def send(self, subject: str, body: str, level: str = "info"):
        """Send alert via all configured channels."""
        self._send_email(subject, body)

    def _send_email(self, subject: str, body: str):
        if not self.email_from or not self.email_to:
            return
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"[Stratex] {subject}"
            msg["From"] = self.email_from
            msg["To"] = self.email_to
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_from, self.email_password)
                server.send_message(msg)
        except Exception as e:
            logger.warning(f"Email alert failed: {e}")

alert_manager = AlertManager()

