from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
import io

from app.api.deps import get_current_user, require_super_admin
from app.core.config import settings
from app.core.security import hash_password
from app.db.database import get_db
from app.models.models import College, Student, User, UserRole, Enrollment
from app.schemas.schemas import StudentCreate, StudentOut, StudentUpdate, ImportReport, AdminResetPasswordResponse
from app.services.audit import record
from app.services.email_service import send_student_import_notification
from app.services.excel_service import build_template_workbook, process_import, default_password_for_phone

router = APIRouter(prefix="/students", tags=["students"])


@router.get("", response_model=list[StudentOut])
def list_students(
    college_id: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Student).join(College)
    if user.role == UserRole.COLLEGE_ADMIN:
        query = query.filter(Student.college_id == user.college_id)
    elif college_id:
        query = query.filter(Student.college_id == college_id)
    if search:
        query = query.filter(
            or_(
                Student.full_name.ilike(f"%{search}%"),
                Student.id.ilike(f"%{search}%"),
                Student.email.ilike(f"%{search}%"),
                Student.roll_number.ilike(f"%{search}%"),
                College.name.ilike(f"%{search}%"),
                Student.graduation_year == int(search) if search.isdigit() else False,
            )
        )
    total = query.count()
    items = query.order_by(Student.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return JSONResponse(content=jsonable_encoder(items), headers={"X-Total-Count": str(total)})


@router.get("/template")
def download_template():
    content = build_template_workbook()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=student_import_template.xlsx"},
    )


@router.post("/import", response_model=ImportReport)
def import_students(
    college_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    report = process_import(db, college_id, file.file.read())
    record(db, user.id, "STUDENTS_IMPORTED", "Student", None, None, {"success": report["success_count"], "failed": report["failure_count"]})

    college = db.query(College).filter(College.id == college_id).first()
    if college and college.contact_email and report["success_count"]:
        send_student_import_notification(
            college.contact_email,
            college.name,
            report["success_count"],
            f"{settings.FRONTEND_ORIGIN}/login",
        )
    return report


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(payload: StudentCreate, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    existing = db.query(Student).filter(Student.college_id == payload.college_id, Student.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="A student with this email already exists at this college")

    student = Student(**payload.model_dump())
    db.add(student)
    db.flush()

    existing_user = db.query(User).filter(User.email == student.email).first()
    if existing_user:
        if existing_user.role == UserRole.STUDENT and not existing_user.student_profile:
            student.user_id = existing_user.id
    else:
        login_user = User(
            email=student.email,
            password_hash=hash_password(default_password_for_phone(student.phone)),
            role=UserRole.STUDENT,
            college_id=student.college_id,
            must_change_password=True,
        )
        db.add(login_user)
        db.flush()
        student.user_id = login_user.id

    db.commit()
    record(db, user.id, "STUDENT_CREATED", "Student", student.id, None, {"full_name": student.full_name})
    return student


@router.put("/{student_id}", response_model=StudentOut)
def update_student(
    student_id: str, payload: StudentUpdate, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    old_value = {"full_name": student.full_name, "phone": student.phone, "email": student.email}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    db.commit()

    record(db, user.id, "STUDENT_UPDATED", "Student", student.id, old_value, payload.model_dump(exclude_unset=True))
    return student


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(student_id: str, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if db.query(Enrollment).filter(Enrollment.student_id == student_id).first():
        raise HTTPException(status_code=400, detail="Cannot delete a student with enrollments. Remove related enrollments first.")

    login_user = None
    if student.user_id:
        login_user = db.query(User).filter(User.id == student.user_id).first()

    db.delete(student)
    if login_user and login_user.role == UserRole.STUDENT:
        db.delete(login_user)

    db.commit()
    record(db, user.id, "STUDENT_DELETED", "Student", student.id, None, {"full_name": student.full_name, "email": student.email})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{student_id}/reset-password", response_model=AdminResetPasswordResponse)
def reset_student_password(
    student_id: str, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    """Resets a student's password back to the PW@+last-4-digits default and
    forces them to choose a new one on next login. There's no email
    integration in V1, so the temporary password is returned directly to the
    admin to pass along to the student."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    temp_password = default_password_for_phone(student.phone)

    if student.user_id:
        login_user = db.query(User).filter(User.id == student.user_id).first()
    else:
        login_user = None

    if login_user:
        login_user.password_hash = hash_password(temp_password)
        login_user.must_change_password = True
        login_user.is_active = True
    else:
        login_user = User(
            email=student.email,
            password_hash=hash_password(temp_password),
            role=UserRole.STUDENT,
            college_id=student.college_id,
            must_change_password=True,
        )
        db.add(login_user)
        db.flush()
        student.user_id = login_user.id

    db.commit()
    record(db, user.id, "STUDENT_PASSWORD_RESET", "Student", student.id)
    return AdminResetPasswordResponse(temporary_password=temp_password, must_change_password=True)
