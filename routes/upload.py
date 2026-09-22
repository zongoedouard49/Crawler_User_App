"""routes/upload.py (user) — lecture seule : thumbnail, view, serve."""
import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import select, func, case

from session import get_db
from models import UploadedFile
from crawler import generate_thumbnail
from storage_r2 import download_bytes, upload_bytes, make_key, content_disposition

router = APIRouter(prefix="/upload", tags=["upload"])


@router.get("/")
def list_uploads(
    keywords: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(UploadedFile).order_by(UploadedFile.uploaded_at.desc())
    if keywords:
        for k in [x.strip() for x in keywords.split(",") if x.strip()]:
            stmt = stmt.where(func.lower(UploadedFile.filename).like(f"%{k.lower()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": str(r.id), "filename": r.filename, "file_size": r.file_size,
                       "mime_type": r.mime_type, "has_thumbnail": bool(r.thumbnail_r2_key)} for r in rows],
            "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}


@router.get("/{file_id}/thumbnail")
def get_thumbnail(file_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(UploadedFile.thumbnail_r2_key, UploadedFile.r2_key, UploadedFile.mime_type)
        .where(UploadedFile.id == file_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404)
    thumb = download_bytes(row.thumbnail_r2_key)
    if not thumb and row.r2_key and row.mime_type == "application/pdf":
        original = download_bytes(row.r2_key)
        thumb = generate_thumbnail(original) if original else None
        if thumb:
            key = make_key("uploaded_files_thumbs", f"{file_id}.jpg")
            upload_bytes(key, thumb, "image/jpeg")
            uf = db.scalars(select(UploadedFile).where(UploadedFile.id == file_id)).first()
            if uf:
                uf.thumbnail_r2_key = key
                db.commit()
    if not thumb:
        raise HTTPException(status_code=404)
    return Response(content=bytes(thumb), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{file_id}/view")
def view_file(file_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(UploadedFile.r2_key, UploadedFile.mime_type, UploadedFile.filename)
        .where(UploadedFile.id == file_id)
    ).first()
    if not row or not row.r2_key:
        raise HTTPException(status_code=404)
    data = download_bytes(row.r2_key)
    if not data:
        raise HTTPException(status_code=404)
    return Response(content=data, media_type=row.mime_type or "application/pdf",
                    headers={"Content-Disposition": content_disposition(row.filename, "inline")})


@router.get("/{file_id}/serve")
def serve_file(file_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(UploadedFile.r2_key, UploadedFile.mime_type, UploadedFile.filename)
        .where(UploadedFile.id == file_id)
    ).first()
    if not row or not row.r2_key:
        raise HTTPException(status_code=404)
    data = download_bytes(row.r2_key)
    if not data:
        raise HTTPException(status_code=404)
    return Response(content=data, media_type=row.mime_type or "application/octet-stream",
                    headers={"Content-Disposition": content_disposition(row.filename, "attachment")})
