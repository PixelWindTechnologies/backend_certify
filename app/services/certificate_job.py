"""
Scheduled job that auto-generates certificates for every enrollment that's
eligible and doesn't yet have a certificate. Wired up via APScheduler in
app/main.py, and can also be invoked manually / via a cron container for
a "serverless" deployment style.

An enrollment is eligible once Certificate Approval = Approved, and
either:
  - Status is explicitly Completed, or
  - Status isn't Dropped and the relieving date has already passed.

That second path exists because requiring every single enrollment to be
flipped to "Completed" by hand doesn't scale for bulk-imported students —
once their relieving date (set via Excel or the Enrollments page) is in
the past and nobody's marked them Dropped, the internship is over in
practice. When this path fires, the enrollment's status is also updated
to Completed so the Enrollments page reflects reality.

`render_certificate_for_enrollment` is shared with the certificate preview
endpoint so "preview" and "generate" always produce an identical document —
the only difference is whether a Certificate row gets persisted.
"""
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
from app.services.storage import resolve_storage_path


def finalize_enrollment_if_eligible(db: Session, enrollment: Enrollment) -> bool:
    """Finalize an enrollment when it has become eligible for certificate issuance.

    Eligibility is reached when the enrollment is already marked Completed or its
    relieving date has arrived. In either case, the record is moved to the
    completed state and approved for certificate issuance automatically so the
    manual approval step is no longer required for routine cases.
    """
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
    """Renders a certificate PDF for the given enrollment to output_path
    using whatever template/signature is currently active. Does not touch
    the database — the caller decides whether/how to persist a Certificate
    row."""
    template = db.query(CertificateTemplate).filter(CertificateTemplate.is_active.is_(True)).first()
    signature = db.query(Signature).filter(Signature.is_active.is_(True)).first()

    student = enrollment.student
    course = enrollment.course
    college = enrollment.college

    # The built-in layout never draws this; the custom-background layout
    # (PixelWind's branded template) does. Generating it is cheap either way.
    qr_relative_path = generate_qr_for_certificate(certificate_id)
    qr_absolute_path = str(resolve_storage_path(qr_relative_path))

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
        template_bg_path=str(resolve_storage_path(template.file_path)) if template else None,
        signature_path=str(resolve_storage_path(signature.image_path)) if signature else None,
        gender=student.gender,
        training_type=enrollment.training_type.value if enrollment.training_type else None,
        qr_code_path=qr_absolute_path,
    )


def _slugify(value: str | None) -> str:
    if not value:
        return "student"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "student"


def generate_pending_certificates() -> int:
    """Generate certificates for all eligible enrollments that do not yet have a certificate."""
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
                pdf_absolute_path = str(resolve_storage_path(pdf_relative_path))

                render_certificate_for_enrollment(
                    db,
                    enrollment,
                    pdf_absolute_path,
                    certificate.id,
                    certificate.issue_date.isoformat(),
                )

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