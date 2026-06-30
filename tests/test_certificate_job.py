from datetime import date, timedelta
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.certificate_engine import render_certificate_pdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import Base
from app.models.models import (
    CertificateApproval,
    College,
    Course,
    Enrollment,
    EnrollmentStatus,
    Student,
)
from app.services.certificate_job import finalize_enrollment_if_eligible


def test_finalize_enrollment_if_eligible_marks_completed_and_approved_when_relieving_date_passed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        college = College(name="Test College", code="TC01")
        course = Course(name="Test Course", code="TC")
        student = Student(
            college=college,
            full_name="Test Student",
            phone="1234567890",
            email="student@example.com",
        )
        enrollment = Enrollment(
            student=student,
            course=course,
            college=college,
            internship_id="INT-001",
            student_sequence=1,
            status=EnrollmentStatus.ACTIVE,
            certificate_approval=CertificateApproval.PENDING,
            relieving_date=date.today() - timedelta(days=1),
        )
        db.add_all([college, course, student, enrollment])
        db.commit()

        changed = finalize_enrollment_if_eligible(db, enrollment)

        assert changed is True
        assert enrollment.status == EnrollmentStatus.COMPLETED
        assert enrollment.certificate_approval == CertificateApproval.APPROVED
    finally:
        db.close()


def test_render_certificate_pdf_accepts_aicte_id(tmp_path):
    output_path = tmp_path / "certificate.pdf"
    result_path = render_certificate_pdf(
        output_path=str(output_path),
        student_name="Test Student",
        father_name="Test Father",
        college_name="Test College",
        course_name="Test Course",
        internship_id="INT-001",
        certificate_id="cert-1",
        issue_date="2026-06-29",
        performance_grade="A",
        admission_date="2026-01-01",
        relieving_date="2026-06-01",
        template_bg_path=None,
        signature_path=None,
        gender="male",
        aicte_internship_id="AICTE-123",
    )

    assert result_path == str(output_path)
    assert output_path.exists()
    assert output_path.stat().st_size > 0
