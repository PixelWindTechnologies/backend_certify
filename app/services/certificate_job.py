"""
Scheduled job that auto-generates certificates for every enrollment that's
eligible and doesn't yet have a certificate.

Storage note: ReportLab/PIL need real local file handles. Every asset
(template background, signature, QR code) is fetched to a local temp file
before rendering, then the finished PDF is uploaded to durable storage.
"""
import os
import re
from datetime import date
from pathlib import Path

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.models import (
    Enrollment,
    EnrollmentStatus,
    CertificateApproval,
    Certificate,
    CertificateTemplate,
    Signature,
)
from app.services.certificate_engine import render_certificate_pdf
from app.services.email_service import send_certificate_ready_email, send_certificate_generation_failure_alert
from app.services.qr_engine import generate_qr_for_certificate
from app.services.storage import get_storage, resolve_storage_path, save_to_local_temp


def finalize_enrollment_if_eligible(db: Session, enrollment: Enrollment) -> bool:
    if enrollment.status == EnrollmentStatus.DROPPED:
        return False

    changed = False
    today = date.today()

    if enrollment.relieving_date is not None and enrollment.relieving_date <= today:
        if enrollment.status != EnrollmentStatus.COMPLETED:
            enrollment.status = EnrollmentStatus.COMPLETED
            changed = True

    if enrollment.status == EnrollmentStatus.COMPLETED and enrollment.certificate_approval != CertificateApproval.APPROVED:
        enrollment.certificate_approval = CertificateApproval.APPROVED
        changed = True

    return changed


def render_certificate_for_enrollment(
    db: Session, enrollment: Enrollment, output_path: str, certificate_id: str, issue_date: str
) -> str:
    """Renders a certificate PDF to output_path (a local filesystem path).
    Fetches all assets (template, signature, QR) to local temp files first
    so ReportLab can read them regardless of storage backend.
    Does not upload anything — caller handles persistence."""
    storage = get_storage()

    template = db.query(CertificateTemplate).filter(CertificateTemplate.is_active.is_(True)).first()
    signature = db.query(Signature).filter(Signature.is_active.is_(True)).first()

    student = enrollment.student
    course = enrollment.course
    college = enrollment.college

    # Track temp files to clean up after rendering
    temp_files = []

    try:
        # --- QR code: generate, upload, and get a local render path ---
        qr_local_path, _qr_storage_key = generate_qr_for_certificate(certificate_id)
        temp_files.append(qr_local_path)

        # --- Template background: fetch from storage to a local temp file ---
        template_local_path = None
        if template and template.file_path:
            suffix = Path(template.file_path).suffix or ".png"
            template_local_path = storage.fetch_to_temp(template.file_path, suffix=suffix)
            # Only add to cleanup if it's actually a temp file (S3 backend),
            # not the real local file (LocalStorage.fetch_to_temp returns real path)
            if settings.STORAGE_BACKEND in ("s3", "r2"):
                temp_files.append(template_local_path)

        # --- Signature: fetch from storage to a local temp file ---
        signature_local_path = None
        if signature and signature.image_path:
            suffix = Path(signature.image_path).suffix or ".png"
            signature_local_path = storage.fetch_to_temp(signature.image_path, suffix=suffix)
            if settings.STORAGE_BACKEND in ("s3", "r2"):
                temp_files.append(signature_local_path)

        return render_certificate_pdf(
            output_path=output_path,
            student_name=student.full_name,
            father_name=student.father_name,
            college_name=college.name,
            course_name=course.name,
            internship_id=enrollment.internship_id,
            aicte_internship_id=enrollment.aicte_internship_id,
            certificate_id=certificate_id,
            issue_date=issue_date,
            performance_grade=enrollment.performance_grade,
            admission_date=enrollment.admission_date.isoformat() if enrollment.admission_date else None,
            relieving_date=enrollment.relieving_date.isoformat() if enrollment.relieving_date else None,
            template_bg_path=template_local_path,
            signature_path=signature_local_path,
            gender=student.gender,
            training_type=enrollment.training_type.value if enrollment.training_type else None,
            qr_code_path=qr_local_path,
        )
    finally:
        for path in temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass


def _slugify(value: str | None) -> str:
    if not value:
        return "student"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "student"


def generate_pending_certificates() -> int:
    db = SessionLocal()
    generated = 0
    try:
        today = date.today()
        eligible = db.query(Enrollment).filter(
            Enrollment.certificate == None,
            Enrollment.certificate_approval == CertificateApproval.APPROVED,
            or_(
                Enrollment.status == EnrollmentStatus.COMPLETED,
                and_(
                    Enrollment.status != EnrollmentStatus.DROPPED,
                    Enrollment.relieving_date != None,
                    Enrollment.relieving_date <= today,
                ),
            ),
        ).all()

        for enrollment in eligible:
            try:
                if not finalize_enrollment_if_eligible(db, enrollment):
                    db.flush()

                if enrollment.status != EnrollmentStatus.COMPLETED or enrollment.certificate_approval != CertificateApproval.APPROVED:
                    continue

                certificate = Certificate(enrollment_id=enrollment.id)
                db.add(certificate)
                db.flush()

                template = db.query(CertificateTemplate).filter(CertificateTemplate.is_active.is_(True)).first()
                student_name = _slugify(enrollment.student.full_name) if enrollment.student else "student"
                pdf_relative_path = f"certificates/{student_name}-{certificate.id}.pdf"

                # Render to a local temp file first (ReportLab can't write to S3)
                with __import__('tempfile').NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    pdf_local_path = tmp.name

                try:
                    render_certificate_for_enrollment(
                        db,
                        enrollment,
                        pdf_local_path,
                        certificate.id,
                        certificate.issue_date.isoformat(),
                    )

                    # Upload the rendered PDF to durable storage
                    storage = get_storage()
                    storage.save(pdf_relative_path, Path(pdf_local_path).read_bytes())
                finally:
                    try:
                        os.unlink(pdf_local_path)
                    except OSError:
                        pass

                certificate.pdf_path = pdf_relative_path
                certificate.template_id = template.id if template else None
                generated += 1

                if enrollment.student and enrollment.student.email:
                    verification_url = f"{settings.FRONTEND_ORIGIN}/verify/{certificate.id}"
                    send_certificate_ready_email(
                        enrollment.student.email,
                        enrollment.student.full_name,
                        certificate.id,
                        verification_url,
                    )
            except Exception as exc:
                send_certificate_generation_failure_alert(
                    [settings.FIRST_SUPER_ADMIN_EMAIL],
                    enrollment.id,
                    str(exc),
                )
                continue

        db.commit()
    finally:
        db.close()

    return generated
