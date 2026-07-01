import io
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_college_admin, require_super_admin
from app.core.config import settings
from app.db.database import get_db
from app.models.models import (
    Certificate,
    Enrollment,
    CertificateTemplate,
    Signature,
    VerificationStatus,
    User,
    UserRole,
)
from app.schemas.schemas import CertificateOut, CertificateRevokeRequest
from app.services.audit import record
from app.services.certificate_job import generate_pending_certificates, render_certificate_for_enrollment
from app.services.storage import get_storage

router = APIRouter(prefix="/certificates", tags=["certificates"])


def build_certificate_download_filename(certificate: Certificate) -> str:
    student_name = "student"
    if certificate.enrollment and certificate.enrollment.student:
        student_name = re.sub(r"[^a-zA-Z0-9]+", "-", certificate.enrollment.student.full_name or "student").strip("-").lower() or "student"
    safe_id = str(certificate.id).replace("/", "-")
    return f"{student_name}-{safe_id}.pdf"


@router.get("", response_model=list[CertificateOut])
def list_certificates(
    page: int = 1,
    page_size: int = 20,
    search: str | None = Query(None),
    issued_from: str | None = Query(None),
    issued_to: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Certificate).join(Enrollment)
    if user.role == UserRole.COLLEGE_ADMIN:
        query = query.filter(Enrollment.college_id == user.college_id)
    elif user.role == UserRole.STUDENT:
        from app.models.models import Student
        query = query.join(Student).filter(Student.user_id == user.id)
    if search:
        query = query.join(Enrollment.student).filter(
            or_(
                Enrollment.internship_id.ilike(f"%{search}%"),
                Certificate.id.ilike(f"%{search}%"),
            )
        )
    if issued_from:
        query = query.filter(Certificate.issue_date >= datetime.strptime(issued_from, "%Y-%m-%d").date())
    if issued_to:
        query = query.filter(Certificate.issue_date <= datetime.strptime(issued_to, "%Y-%m-%d").date())
    total = query.count()
    items = query.order_by(Certificate.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return JSONResponse(content=jsonable_encoder(items), headers={"X-Total-Count": str(total)})


@router.post("/generate-pending")
def trigger_generation(user: User = Depends(require_super_admin)):
    count = generate_pending_certificates()
    return {"generated": count}


@router.get("/preview/{enrollment_id}")
def preview_certificate(
    enrollment_id: str, db: Session = Depends(get_db), user: User = Depends(require_college_admin)
):
    """Renders a certificate preview without creating a Certificate record."""
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if user.role == UserRole.COLLEGE_ADMIN and enrollment.college_id != user.college_id:
        raise HTTPException(status_code=403, detail="Not allowed")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    render_certificate_for_enrollment(
        db, enrollment, tmp_path,
        certificate_id="preview",
        issue_date=datetime.utcnow().date().isoformat(),
    )
    return FileResponse(tmp_path, media_type="application/pdf", filename="certificate_preview.pdf")


@router.get("/{certificate_id}/download")
def download_certificate(
    certificate_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert or not cert.pdf_path:
        raise HTTPException(status_code=404, detail="Certificate PDF not available")

    storage = get_storage()
    if not storage.exists(cert.pdf_path):
        raise HTTPException(status_code=404, detail="Certificate file missing on storage")

    data = storage.get(cert.pdf_path)
    filename = build_certificate_download_filename(cert)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/download-bulk")
def download_certificates_zip(
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
    college_id: str | None = Query(None),
    course_id: str | None = Query(None),
    issued_from: str | None = Query(None),
    issued_to: str | None = Query(None),
    search: str | None = Query(None),
):
    query = db.query(Certificate).join(Enrollment)
    if college_id:
        query = query.filter(Enrollment.college_id == college_id)
    if course_id:
        query = query.filter(Enrollment.course_id == course_id)
    if issued_from:
        query = query.filter(Certificate.issue_date >= datetime.strptime(issued_from, "%Y-%m-%d").date())
    if issued_to:
        query = query.filter(Certificate.issue_date <= datetime.strptime(issued_to, "%Y-%m-%d").date())
    if search:
        query = query.join(Enrollment.student).filter(
            or_(
                Enrollment.internship_id.ilike(f"%{search}%"),
                Certificate.id.ilike(f"%{search}%"),
            )
        )

    certificates = query.order_by(Certificate.created_at.desc()).all()
    if not certificates:
        raise HTTPException(status_code=404, detail="No certificates found")

    storage = get_storage()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for cert in certificates:
            if not cert.pdf_path:
                continue
            if not storage.exists(cert.pdf_path):
                continue
            data = storage.get(cert.pdf_path)
            filename = build_certificate_download_filename(cert)
            zf.writestr(filename, data)

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=certificates.zip"},
    )


@router.post("/{certificate_id}/revoke", response_model=CertificateOut)
def revoke_certificate(
    certificate_id: str,
    payload: CertificateRevokeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    old_value = {"verification_status": cert.verification_status.value}
    cert.verification_status = VerificationStatus.REVOKED
    cert.revoked_at = datetime.utcnow()
    cert.revoked_reason = payload.reason
    db.commit()

    record(db, user.id, "CERTIFICATE_REVOKED", "Certificate", cert.id, old_value, {"reason": payload.reason})
    return cert


# ---------------------------------------------------------------------------
# Certificate templates
# ---------------------------------------------------------------------------
@router.get("/templates/list")
def list_templates(db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    templates = db.query(CertificateTemplate).order_by(CertificateTemplate.created_at.desc()).all()
    return [
        {"id": t.id, "name": t.name, "is_active": t.is_active, "file_path": t.file_path}
        for t in templates
    ]


@router.post("/templates/upload")
def upload_template(
    name: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    ext = Path(file.filename).suffix or ".png"
    relative_path = f"templates/{uuid.uuid4()}{ext}"

    storage = get_storage()
    data = file.file.read()
    storage.save(relative_path, data)

    if not storage.exists(relative_path):
        raise HTTPException(status_code=500, detail="Template upload failed to persist to storage")

    template = CertificateTemplate(name=name, file_path=relative_path, is_active=False)
    db.add(template)
    db.commit()
    record(db, user.id, "TEMPLATE_UPLOADED", "CertificateTemplate", template.id, None, {"name": name})
    return {"id": template.id, "name": template.name}


@router.post("/templates/{template_id}/activate")
def activate_template(
    template_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    db.query(CertificateTemplate).update({CertificateTemplate.is_active: False})
    template = db.query(CertificateTemplate).filter(CertificateTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template.is_active = True
    db.commit()
    record(db, user.id, "TEMPLATE_ACTIVATED", "CertificateTemplate", template.id)
    return {"message": "Template activated"}


@router.post("/templates/{template_id}/deactivate")
def deactivate_template(
    template_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    template = db.query(CertificateTemplate).filter(CertificateTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template.is_active = False
    db.commit()
    record(db, user.id, "TEMPLATE_DEACTIVATED", "CertificateTemplate", template.id)
    return {"message": "Template deactivated"}


# ---------------------------------------------------------------------------
# Authorized signature
# ---------------------------------------------------------------------------
@router.post("/signature/upload")
def upload_signature(
    label: str = "Authorized Signatory",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    ext = Path(file.filename).suffix or ".png"
    relative_path = f"signatures/{uuid.uuid4()}{ext}"

    storage = get_storage()
    data = file.file.read()
    storage.save(relative_path, data)

    if not storage.exists(relative_path):
        raise HTTPException(status_code=500, detail="Signature upload failed to persist to storage")

    db.query(Signature).update({Signature.is_active: False})
    signature = Signature(label=label, image_path=relative_path, is_active=True)
    db.add(signature)
    db.commit()
    record(db, user.id, "SIGNATURE_UPDATED", "Signature", signature.id, None, {"label": label})
    return {"id": signature.id, "label": signature.label}


@router.get("/signature/list")
def list_signatures(db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    signatures = db.query(Signature).order_by(Signature.created_at.desc()).all()
    return [
        {"id": s.id, "label": s.label, "is_active": s.is_active, "image_path": s.image_path}
        for s in signatures
    ]
