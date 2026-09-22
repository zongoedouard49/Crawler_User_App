"""routes/auth.py (user) — login, me, refresh — routes sync."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel

from session import get_db
from models import User
from routes.auth import verify_password, create_access_token, require_auth

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalars(select(User).filter_by(username=payload.username)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    token = create_access_token(user.id, user.username, user.role.value)
    return TokenResponse(access_token=token, role=user.role.value, username=user.username)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(current_user: User = Depends(require_auth)):
    token = create_access_token(current_user.id, current_user.username, current_user.role.value)
    return TokenResponse(access_token=token, role=current_user.role.value, username=current_user.username)


@router.get("/me")
def me(current_user: User = Depends(require_auth)):
    return {"id": current_user.id, "username": current_user.username, "role": current_user.role.value}
