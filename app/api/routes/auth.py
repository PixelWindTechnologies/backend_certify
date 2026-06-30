from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    create_password_reset_token,
)
from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.models import User
from app.services.email_service import send_password_reset_email
from app.schemas.schemas import (
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    user.last_login_at = datetime.utcnow()
    db.commit()

    full_name = None
    if user.student_profile:
        full_name = user.student_profile.full_name

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value, user.college_id),
        refresh_token=create_refresh_token(user.id, user.role.value),
        role=user.role,
        user_id=user.id,
        full_name=full_name,
        must_change_password=user.must_change_password,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        data = decode_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if data.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user = db.query(User).filter(User.id == data["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value, user.college_id),
        refresh_token=create_refresh_token(user.id, user.role.value),
        role=user.role,
        user_id=user.id,
        must_change_password=user.must_change_password,
    )


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        return {"message": "If an account exists for this email, a reset link has been sent."}

    token = create_password_reset_token(user.id)
    reset_url = f"{settings.FRONTEND_ORIGIN}/reset-password?token={token}"
    send_password_reset_email(user.email, reset_url)
    return {"message": "If an account exists for this email, a reset link has been sent."}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Used both for a voluntary password change and for the forced
    first-login change after an Excel import or an admin-triggered reset."""
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    return {"message": "Password updated successfully"}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        data = decode_token(payload.token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset link")

    if data.get("type") != "password_reset":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")

    user = db.query(User).filter(User.id == data["sub"]).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password updated successfully"}
