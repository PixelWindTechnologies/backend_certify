import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import extract, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.core.config import settings
from app.db.database import get_db
from app.models.models import (
    Certificate,
    College,
    Course,
    Enrollment,
    EnrollmentStatus,
    FutureAssessment,
    FutureAttendance,
    FutureProject,
    Student,
    TrainingType,
    User,
    UserRole,
    VerificationLog,
)
from app.schemas.schemas import EnrollmentCreate, EnrollmentOut, EnrollmentUpdate
from app.services.audit import record
from app.services.certificate_job import finalize_enrollment_if_eligible
from app.services.storage import resolve_storage_path
from app.services.internship_id import build_internship_id, next_student_sequence

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("", response_model=list[EnrollmentOut])
def list_enrollments(
    student_id: str | None = None,
    search: str | None = None,
    status: EnrollmentStatus | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Enrollment)
    student_joined = False

    if user.role == UserRole.COLLEGE_ADMIN:
        query = query.filter(Enrollment.college_id == user.college_id)
    elif user.role == UserRole.STUDENT:
        query = query.join(Student)
        student_joined = True
        query = query.filter(Student.user_id == user.id)

    if status:
        query = query.filter(Enrollment.status == status)

    if search:
        if not student_joined:
            query = query.join(Student)
        query = query.join(College, Enrollment.college_id == College.id).join(Course)

        search_term = f"%{search}%"
        search_filters = [
            Enrollment.internship_id.ilike(search_term),
            Enrollment.roll_number.ilike(search_term),
            Student.full_name.ilike(search_term),
            Student.id.ilike(search_term),
            Course.name.ilike(search_term),
            College.name.ilike(search_term),
        ]
        if search.isdigit():
            year = int(search)
            search_filters.append(extract("year", Enrollment.admission_date) == year)
        query = query.filter(or_(*search_filters))

    if student_id:
        query = query.filter(Enrollment.student_id == student_id)

    total = query.count()
    items = query.order_by(Enrollment.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return JSONResponse(content=jsonable_encoder(items), headers={"X-Total-Count": str(total)})


@router.post("", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
def create_enrollment(
    payload: EnrollmentCreate, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    student = db.query(Student).filter(Student.id == payload.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    sequence = next_student_sequence(db, course.id, student.college_id)
    internship_id = build_internship_id(course, sequence)

    training_type = payload.training_type or TrainingType.INTERNSHIP
    enrollment = Enrollment(
        student_id=payload.student_id,
        course_id=payload.course_id,
        college_id=student.college_id,
        training_type=training_type,
        internship_id=internship_id,
        roll_number=payload.roll_number,
        student_sequence=sequence,
        admission_date=payload.admission_date,
        relieving_date=payload.relieving_date,
    )
    db.add(enrollment)
    finalize_enrollment_if_eligible(db, enrollment)
    db.commit()
    record(db, user.id, "ENROLLMENT_CREATED", "Enrollment", enrollment.id, None, {"internship_id": internship_id})
    return enrollment


@router.put("/{enrollment_id}", response_model=EnrollmentOut)
def update_enrollment(
    enrollment_id: str,
    payload: EnrollmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    old_value = {
        "status": enrollment.status.value,
        "certificate_approval": enrollment.certificate_approval.value,
        "relieving_date": str(enrollment.relieving_date) if enrollment.relieving_date else None,
    }
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(enrollment, field, value)
    finalize_enrollment_if_eligible(db, enrollment)
    db.commit()

    record(db, user.id, "ENROLLMENT_UPDATED", "Enrollment", enrollment.id, old_value, payload.model_dump(exclude_unset=True, mode="json"))
    return enrollment


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_enrollment(enrollment_id: str, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    certificate = db.query(Certificate).filter(Certificate.enrollment_id == enrollment.id).first()
    if certificate:
        db.query(FutureAssessment).filter(FutureAssessment.enrollment_id == enrollment.id).delete(synchronize_session=False)
        db.query(FutureAttendance).filter(FutureAttendance.enrollment_id == enrollment.id).delete(synchronize_session=False)
        db.query(FutureProject).filter(FutureProject.enrollment_id == enrollment.id).delete(synchronize_session=False)
        db.query(VerificationLog).filter(VerificationLog.certificate_id == certificate.id).delete(synchronize_session=False)

        # Remove stored artifact files too.
        for path_value in (certificate.pdf_path, certificate.qr_code_path):
            if path_value:
                full_path = resolve_storage_path(path_value)
                if full_path.exists():
                    try:
                        full_path.unlink()
                    except OSError:
                        pass

        db.delete(certificate)

    db.delete(enrollment)
    db.commit()
    record(db, user.id, "ENROLLMENT_DELETED", "Enrollment", enrollment.id, None, {"internship_id": enrollment.internship_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
