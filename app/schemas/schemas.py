"""
Pydantic schemas used for request validation and response serialization.
"""
from datetime import date, datetime
from typing import Optional, Any

from pydantic import BaseModel, EmailStr, ConfigDict

from app.models.models import (
    UserRole,
    EnrollmentStatus,
    CertificateApproval,
    VerificationStatus,
    TrainingType,
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: str
    full_name: Optional[str] = None
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class AdminResetPasswordResponse(BaseModel):
    temporary_password: str
    must_change_password: bool = True


class RefreshRequest(BaseModel):
    refresh_token: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    role: UserRole
    college_id: Optional[str] = None
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: UserRole
    college_id: Optional[str] = None


# ---------------------------------------------------------------------------
# College
# ---------------------------------------------------------------------------
class CollegeBase(BaseModel):
    name: str
    code: str
    address: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None


class CollegeCreate(CollegeBase):
    admin_email: Optional[EmailStr] = None
    admin_password: Optional[str] = None


class CollegeUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    is_active: Optional[bool] = None


class CollegeOut(CollegeBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------
class CourseBase(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    duration_weeks: Optional[int] = None


class CourseCreate(CourseBase):
    pass


class CourseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    duration_weeks: Optional[int] = None
    is_active: Optional[bool] = None


class CourseOut(CourseBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    is_active: bool


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------
class StudentBase(BaseModel):
    full_name: str
    father_name: Optional[str] = None
    phone: str
    email: EmailStr
    gender: Optional[str] = None
    roll_number: Optional[str] = None
    graduation_year: Optional[int] = None


class StudentCreate(StudentBase):
    college_id: str


class StudentUpdate(BaseModel):
    full_name: Optional[str] = None
    father_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    gender: Optional[str] = None
    roll_number: Optional[str] = None
    graduation_year: Optional[int] = None


class StudentOut(StudentBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    college_id: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
class EnrollmentCreate(BaseModel):
    student_id: str
    course_id: str
    training_type: TrainingType = TrainingType.INTERNSHIP
    admission_date: Optional[date] = None
    relieving_date: Optional[date] = None
    roll_number: Optional[str] = None
    aicte_internship_id: Optional[str] = None


class EnrollmentUpdate(BaseModel):
    status: Optional[EnrollmentStatus] = None
    certificate_approval: Optional[CertificateApproval] = None
    training_type: Optional[TrainingType] = None
    admission_date: Optional[date] = None
    relieving_date: Optional[date] = None
    performance_grade: Optional[str] = None
    roll_number: Optional[str] = None
    aicte_internship_id: Optional[str] = None


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    student_id: str
    course_id: str
    college_id: str
    training_type: TrainingType
    internship_id: str
    roll_number: Optional[str] = None
    aicte_internship_id: Optional[str] = None
    status: EnrollmentStatus
    certificate_approval: CertificateApproval
    admission_date: Optional[date] = None
    relieving_date: Optional[date] = None
    performance_grade: Optional[str] = None


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------
class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    enrollment_id: str
    issue_date: date
    pdf_path: Optional[str] = None
    qr_code_path: Optional[str] = None
    verification_status: VerificationStatus
    version: int


class CertificateRevokeRequest(BaseModel):
    reason: str


class VerificationResponse(BaseModel):
    verification_status: VerificationStatus
    student_id: str
    student_name: str
    father_name: Optional[str] = None
    college_name: str
    course_name: str
    internship_id: str
    training_type: TrainingType
    admission_date: Optional[date] = None
    relieving_date: Optional[date] = None
    performance_grade: Optional[str] = None
    certificate_id: str
    issue_date: date
    issued_by: str = "Pixelwind Technologies"
    verified_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Excel import
# ---------------------------------------------------------------------------
class ImportRowError(BaseModel):
    row_number: int
    errors: list[str]
    raw_data: dict[str, Any]


class ImportReport(BaseModel):
    success_count: int
    failure_count: int
    errors: list[ImportRowError]
    accounts_created: int = 0


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    timestamp: datetime


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class DashboardStats(BaseModel):
    total_colleges: int
    total_students: int
    total_enrollments: int
    active_students: int
    completed_students: int
    dropped_students: int
    certificates_generated: int
    certificates_revoked: int