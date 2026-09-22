"""
routes/files.py (user) — recherche, consultation, téléchargement, fusion
Toutes les routes sont def → FastAPI les exécute dans son ThreadPool.
"""
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, case

from session import get_db
from models import FoundFile, UploadedFile, User

from crawler import download_file_sync, build_headers, generate_thumbnail
from storage_r2 import download_bytes, upload_bytes, make_key, content_disposition
from merger import merge_pdf_bytes

router = APIRouter(prefix="/files", tags=["files"])
_MERGE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="merge")


# ── DTOs ─────────────────────────────────────────────────────────

class FoundFileOut(BaseModel):
    id: str
    crawl_job_id: Optional[str]
    url: Optional[str]
    filename: str
    is_downloaded: bool
    has_thumbnail: bool
    file_size: Optional[int]
    mime_type: Optional[str]
    discovered_at: Optional[datetime]
    downloaded_at: Optional[datetime]

    @field_validator("id", "crawl_job_id", mode="before")
    @classmethod
    def _str(cls, v): return None if v is None else str(v)


class PaginatedFiles(BaseModel):
    items: List[FoundFileOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class UnifiedFileOut(BaseModel):
    id: str
    file_type: str
    filename: str
    file_size: Optional[int]
    mime_type: Optional[str]
    has_thumbnail: bool
    discovered_at: Optional[datetime]

    @field_validator("id", mode="before")
    @classmethod
    def _str(cls, v): return str(v)


class UnifiedPage(BaseModel):
    items: List[UnifiedFileOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class MergeItem(BaseModel):
    id: str
    file_type: str = "found"


class MergeRequest(BaseModel):
    files: Optional[List[MergeItem]] = None
    output_filename: str = "merged_document.pdf"


# ── Helpers ───────────────────────────────────────────────────────

def _thumb_found():
    return case((FoundFile.thumbnail_r2_key != None, True), else_=False)

def _thumb_uploaded():
    return case((UploadedFile.thumbnail_r2_key != None, True), else_=False)

def _kw_found(stmt, kws: Optional[str]):
    if not kws:
        return stmt
    for k in [x.strip() for x in kws.split(",") if x.strip()]:
        p = f"%{k.lower()}%"
        stmt = stmt.where(or_(func.lower(FoundFile.filename).like(p),
                              func.lower(FoundFile.url).like(p)))
    return stmt

def _kw_uploaded(stmt, kws: Optional[str]):
    if not kws:
        return stmt
    for k in [x.strip() for x in kws.split(",") if x.strip()]:
        stmt = stmt.where(func.lower(UploadedFile.filename).like(f"%{k.lower()}%"))
    return stmt


# ── Routes ────────────────────────────────────────────────────────

@router.get("/", response_model=PaginatedFiles)
def search_files(
    keywords: Optional[str] = Query(None),
    downloaded_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(FoundFile).order_by(FoundFile.discovered_at.desc())
    if downloaded_only:
        stmt = stmt.where(FoundFile.is_downloaded == True)
    stmt = _kw_found(stmt, keywords)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    items = [FoundFileOut(
        id=str(r.id), crawl_job_id=str(r.crawl_job_id) if r.crawl_job_id else None,
        url=r.url, filename=r.filename, is_downloaded=r.is_downloaded,
        has_thumbnail=bool(r.thumbnail_r2_key), file_size=r.file_size,
        mime_type=r.mime_type, discovered_at=r.discovered_at, downloaded_at=r.downloaded_at,
    ) for r in rows]
    return PaginatedFiles(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


@router.get("/downloaded", response_model=UnifiedPage)
def get_downloaded(
    keywords: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt_f = select(FoundFile).where(FoundFile.is_downloaded == True)
    stmt_u = select(UploadedFile)
    stmt_f = _kw_found(stmt_f, keywords)
    stmt_u = _kw_uploaded(stmt_u, keywords)

    count_f = db.scalar(select(func.count()).select_from(stmt_f.subquery())) or 0
    count_u = db.scalar(select(func.count()).select_from(stmt_u.subquery())) or 0
    total = count_f + count_u
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    offset = (page - 1) * page_size

    limit = offset + page_size
    found_rows    = db.scalars(stmt_f.order_by(FoundFile.downloaded_at.desc()).limit(limit)).all()
    uploaded_rows = db.scalars(stmt_u.order_by(UploadedFile.uploaded_at.desc()).limit(limit)).all()

    merged = (
        [UnifiedFileOut(id=str(r.id), file_type="found", filename=r.filename,
                        file_size=r.file_size, mime_type=r.mime_type,
                        has_thumbnail=bool(r.thumbnail_r2_key),
                        discovered_at=r.downloaded_at) for r in found_rows] +
        [UnifiedFileOut(id=str(r.id), file_type="uploaded", filename=r.filename,
                        file_size=r.file_size, mime_type=r.mime_type,
                        has_thumbnail=bool(r.thumbnail_r2_key),
                        discovered_at=r.uploaded_at) for r in uploaded_rows]
    )
    merged.sort(key=lambda x: x.discovered_at or datetime.min, reverse=True)
    items = merged[offset: offset + page_size]
    return UnifiedPage(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


@router.get("/{file_id}/thumbnail")
def get_thumbnail(file_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(FoundFile.thumbnail_r2_key, FoundFile.r2_key).where(FoundFile.id == file_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404)
    thumb = download_bytes(row.thumbnail_r2_key)
    if not thumb and row.r2_key:
        original = download_bytes(row.r2_key)
        thumb = generate_thumbnail(original) if original else None
        if thumb:
            key = make_key("found_files_thumbs", f"{file_id}.jpg")
            upload_bytes(key, thumb, "image/jpeg")
            db.execute(
                select(FoundFile).where(FoundFile.id == file_id)
            )
            ff = db.scalars(select(FoundFile).where(FoundFile.id == file_id)).first()
            if ff:
                ff.thumbnail_r2_key = key
                db.commit()
    if not thumb:
        raise HTTPException(status_code=404)
    return Response(content=bytes(thumb), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{file_id}/view")
def view_file(file_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(FoundFile.r2_key, FoundFile.mime_type, FoundFile.filename)
        .where(FoundFile.id == file_id)
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
        select(FoundFile.r2_key, FoundFile.mime_type, FoundFile.filename)
        .where(FoundFile.id == file_id)
    ).first()
    if not row or not row.r2_key:
        raise HTTPException(status_code=404)
    data = download_bytes(row.r2_key)
    if not data:
        raise HTTPException(status_code=404)
    return Response(content=data, media_type=row.mime_type or "application/octet-stream",
                    headers={"Content-Disposition": content_disposition(row.filename, "attachment")})


@router.post("/{file_id}/download")
def trigger_download(file_id: str, db: Session = Depends(get_db),):
    ff = db.scalars(select(FoundFile).where(FoundFile.id == file_id)).first()
    if not ff:
        raise HTTPException(status_code=404)
    hdrs = build_headers(ff.crawl_job.header if ff.crawl_job else None)
    if not download_file_sync(ff.resolved_url or ff.url, hdrs, ff, db):
        raise HTTPException(status_code=500, detail="Téléchargement échoué")
    db.refresh(ff)
    return {"id": str(ff.id), "filename": ff.filename, "is_downloaded": ff.is_downloaded}


@router.post("/merge")
def merge_files(payload: MergeRequest, db: Session = Depends(get_db)):
    items = payload.files or []
    if len(items) < 2:
        raise HTTPException(status_code=400, detail="Au moins 2 fichiers requis")

    files_data = []
    for item in items:
        if item.file_type == "uploaded":
            row = db.execute(
                select(UploadedFile.id, UploadedFile.filename, UploadedFile.r2_key)
                .where(UploadedFile.id == item.id)
            ).first()
        else:
            row = db.execute(
                select(FoundFile.id, FoundFile.filename, FoundFile.r2_key)
                .where(FoundFile.id == item.id)
            ).first()
        data = download_bytes(row.r2_key) if row and row.r2_key else None
        if not row or not data:
            raise HTTPException(status_code=400, detail=f"Fichier introuvable : {item.id}")
        files_data.append((row.id, row.filename, data))

    # merge_pdf_bytes est CPU-bound → tourne dans le thread FastAPI (ThreadPool)
    merged = merge_pdf_bytes(files_data, payload.output_filename)
    return Response(
        content=merged,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(payload.output_filename, "attachment")},
    )
