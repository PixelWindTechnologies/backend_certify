from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import email_service


class FakeSMTP:
    def __init__(self, host, port=0):
        self.host = host
        self.port = port
        self.login_calls = []
        self.sent_messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, username, password):
        self.login_calls.append((username, password))

    def send_message(self, message):
        self.sent_messages.append(message)

    def quit(self):
        return None


def test_send_password_reset_email_uses_smtp_when_configured(monkeypatch):
    sent = {}

    def fake_smtp(host, port=0):
        smtp = FakeSMTP(host, port)
        sent["smtp"] = smtp
        return smtp

    monkeypatch.setattr(email_service.smtplib, "SMTP", fake_smtp)
    monkeypatch.setattr(email_service.settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(email_service.settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(email_service.settings, "SMTP_PORT", 2525)
    monkeypatch.setattr(email_service.settings, "SMTP_USERNAME", "user")
    monkeypatch.setattr(email_service.settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(email_service.settings, "SMTP_FROM_EMAIL", "noreply@example.test")
    monkeypatch.setattr(email_service.settings, "SMTP_FROM_NAME", "Pixelwind")

    result = email_service.send_password_reset_email("student@example.test", "https://example.test/reset")

    assert result is True
    assert sent["smtp"].host == "smtp.example.test"
    assert sent["smtp"].sent_messages
