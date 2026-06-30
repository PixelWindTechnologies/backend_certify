from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.models import Certificate, VerificationLog
from app.schemas.schemas import VerificationResponse

router = APIRouter(prefix="/verify", tags=["verification"])


@router.get("/{certificate_id}", response_model=VerificationResponse)
def verify_certificate(certificate_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Public endpoint. Looks a certificate up strictly by its certificate ID
    (never by student ID) and walks Certificate -> Enrollment -> Student ->
    Course -> College to build the verification payload. Only the
    fields explicitly approved for public display are returned.
    """
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    enrollment = cert.enrollment
    student = enrollment.student
    course = enrollment.course
    college = enrollment.college

    db.add(
        VerificationLog(
            certificate_id=cert.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    db.commit()

    return VerificationResponse(
        verification_status=cert.verification_status,
        student_id=student.id,
        student_name=student.full_name,
        father_name=student.father_name,
        college_name=college.name,
        course_name=course.name,
        internship_id=enrollment.internship_id,
        training_type=enrollment.training_type.value if enrollment.training_type else None,
        admission_date=enrollment.admission_date,
        relieving_date=enrollment.relieving_date,
        performance_grade=enrollment.performance_grade,
        certificate_id=cert.id,
        issue_date=cert.issue_date,
        issued_by=settings.ISSUER_NAME or "Pixelwind Technologies",
        verified_at=datetime.utcnow(),
    )
