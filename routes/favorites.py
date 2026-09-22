"""routes/favorites.py (user) — favoris sync."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from session import get_db
from models import Favorite, FoundFile, UploadedFile

router = APIRouter(prefix="/favorites", tags=["favorites"])


class ToggleRequest(BaseModel):
    session_key: str
    found_file_id: Optional[str] = None
    uploaded_file_id: Optional[str] = None


@router.get("/")
def list_favorites(db: Session = Depends(get_db)):
    favs = db.scalars(select(Favorite)).all()
    out = []
    for fav in favs:
        if fav.found_file_id:
            f = db.scalars(select(FoundFile).where(FoundFile.id == fav.found_file_id)).first()
            if f:
                out.append({"id": str(fav.id), "session_key": fav.session_key,
                            "found_file_id": str(f.id), "uploaded_file_id": None,
                            "file_id": str(f.id), "source": "found",
                            "filename": f.filename, "file_size": f.file_size,
                            "has_thumbnail": bool(f.thumbnail_r2_key),
                            "added_at": fav.added_at})
        elif fav.uploaded_file_id:
            f = db.scalars(select(UploadedFile).where(UploadedFile.id == fav.uploaded_file_id)).first()
            if f:
                out.append({"id": str(fav.id), "session_key": fav.session_key,
                            "found_file_id": None, "uploaded_file_id": str(f.id),
                            "file_id": str(f.id), "source": "uploaded",
                            "filename": f.filename, "file_size": f.file_size,
                            "has_thumbnail": bool(f.thumbnail_r2_key),
                            "added_at": fav.added_at})
    return out


@router.post("/toggle")
def toggle_favorite(payload: ToggleRequest, db: Session = Depends(get_db)):
    if not payload.found_file_id and not payload.uploaded_file_id:
        raise HTTPException(status_code=400, detail="found_file_id ou uploaded_file_id requis")
    stmt = select(Favorite).filter_by(session_key=payload.session_key)
    if payload.found_file_id:
        stmt = stmt.where(Favorite.found_file_id == payload.found_file_id)
    else:
        stmt = stmt.where(Favorite.uploaded_file_id == payload.uploaded_file_id)
    existing = db.scalars(stmt).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"action": "removed"}
    fav = Favorite(session_key=payload.session_key,
                   found_file_id=payload.found_file_id,
                   uploaded_file_id=payload.uploaded_file_id)
    db.add(fav)
    db.commit()
    db.refresh(fav)
    return {"action": "added", "fav_id": str(fav.id)}


@router.delete("/{fav_id}", status_code=204)
def remove_favorite(fav_id: str, db: Session = Depends(get_db)):
    fav = db.scalars(select(Favorite).where(Favorite.id == fav_id)).first()
    if not fav:
        raise HTTPException(status_code=404)
    db.delete(fav)
    db.commit()
