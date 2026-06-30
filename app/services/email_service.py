import smtplib
from email.message import EmailMessage
from typing import Iterable

from app.core.config import settings


def _normalize_recipients(recipients: Iterable[str] | None) -> list[str]:
    if not recipients:
        return []
    return [recipient.strip() for recipient in recipients if recipient and recipient.strip()]


def send_mail(subject: str, body: str, to_email: str | None, html_body: str | None = None) -> bool:
    if not settings.EMAIL_ENABLED or not to_email:
        return False

    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        return False

    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = to_email
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT or 587) as smtp:
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        return True
    except Exception:
        return False


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    subject = "Reset your Pixelwind certificate portal password"
    body = (
        "Hello,\n\n"
        "A password reset was requested for your Pixelwind certificate portal account.\n"
        f"Use the following link to continue: {reset_url}\n\n"
        "If you did not request this change, you can safely ignore this email."
    )
    html_body = (
        f"<p>Hello,</p>"
        f"<p>A password reset was requested for your account.</p>"
        f"<p><a href=\"{reset_url}\">Reset your password</a></p>"
        "<p>If you did not request this change, you can safely ignore this email.</p>"
    )
    return send_mail(subject=subject, body=body, to_email=to_email, html_body=html_body)


def send_certificate_ready_email(to_email: str, student_name: str, certificate_id: str, verification_url: str) -> bool:
    subject = "Your internship certificate is ready"
    body = (
        f"Hello {student_name},\n\n"
        "Your internship certificate has been generated and is now ready for verification.\n"
        f"Certificate ID: {certificate_id}\n"
        f"Verification link: {verification_url}\n"
    )
    html_body = (
        f"<p>Hello {student_name},</p>"
        "<p>Your internship certificate has been generated and is now ready for verification.</p>"
        f"<p><strong>Certificate ID:</strong> {certificate_id}</p>"
        f"<p><a href=\"{verification_url}\">Open certificate verification</a></p>"
    )
    return send_mail(subject=subject, body=body, to_email=to_email, html_body=html_body)


def send_student_import_notification(to_email: str, college_name: str, count: int, login_url: str) -> bool:
    subject = "New student accounts have been imported"
    body = (
        f"Hello,\n\n"
        f"{count} student accounts were imported for {college_name}.\n"
        f"Sign in here to review the latest data: {login_url}"
    )
    html_body = (
        f"<p>Hello,</p>"
        f"<p>{count} student accounts were imported for <strong>{college_name}</strong>.</p>"
        f"<p><a href=\"{login_url}\">Open the portal</a></p>"
    )
    return send_mail(subject=subject, body=body, to_email=to_email, html_body=html_body)


def send_certificate_generation_failure_alert(to_emails: Iterable[str], enrollment_id: str, error_message: str) -> bool:
    recipients = _normalize_recipients(to_emails)
    if not recipients:
        return False

    subject = "Certificate generation failed"
    body = (
        "A certificate generation job failed and requires attention.\n"
        f"Enrollment ID: {enrollment_id}\n"
        f"Error: {error_message}"
    )
    html_body = (
        "<p>A certificate generation job failed and requires attention.</p>"
        f"<p><strong>Enrollment ID:</strong> {enrollment_id}</p>"
        f"<p><strong>Error:</strong> {error_message}</p>"
    )

    success = False
    for recipient in recipients:
        success = send_mail(subject=subject, body=body, to_email=recipient, html_body=html_body) or success
    return success
