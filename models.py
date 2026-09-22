import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, JSON, BigInteger, Enum, Float
)
from sqlalchemy.orm import relationship
import enum
from session import Base


def gen_uuid() -> str:
    """Génère un id string (UUID4). Utilisé pour toutes les clés primaires —
    aucune dépendance à unique_rowid()/SERIAL de la base, donc aucune
    conversion de type n'est jamais nécessaire côté frontend."""
    return str(uuid.uuid4())


ID_LEN = 36  # longueur d'un UUID4 sous forme texte


class CrawlStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER  = "user"


class User(Base):
    __tablename__ = "users"
    id            = Column(String(ID_LEN), primary_key=True, default=gen_uuid, index=True)
    username      = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role          = Column(Enum(UserRole, values_callable=lambda x: [e.value for e in x]), default=UserRole.USER, nullable=False)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Header(Base):
    __tablename__ = "headers"
    id          = Column(String(ID_LEN), primary_key=True, default=gen_uuid, index=True)
    name        = Column(String(50), unique=True, nullable=False)
    values      = Column(JSON, nullable=False)
    # suffix_file : suffixe à ajouter à l'URL pour former l'URL complète du fichier.
    # - Si l'URL est incomplète  → on ajoute ce suffix (ex: "/download", ".pdf")
    # - Si l'URL est déjà complète (se termine par .pdf, /download, etc.)
    #   → suffix_file = "" ou None, et url_complete = True indique qu'aucun ajout n'est nécessaire.
    suffix_file  = Column(String(50), nullable=True, default="")
    # url_complete : True  = l'URL crawlée est déjà l'URL finale du fichier (pas d'ajout de suffix)
    #                False = il faut coller suffix_file au bout de l'URL pour obtenir l'URL de téléchargement
    url_complete = Column(Boolean, nullable=False, default=False)
    # page_param : nom du paramètre de pagination dans l'URL (ex: "start", "SujetId", "page", "offset")
    # Utilisé par crawl_paginated pour construire les URLs paginées : base_url?{page_param}=N
    page_param   = Column(String(50), nullable=True, default="start")
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    crawl_jobs  = relationship("CrawlJob", back_populates="header")


class CrawlJob(Base):
    __tablename__    = "crawl_jobs"
    id               = Column(String(ID_LEN), primary_key=True, default=gen_uuid, index=True)
    base_url         = Column(Text, nullable=False)
    header_id        = Column(String(ID_LEN), ForeignKey("headers.id"), nullable=True)
    file_prefix      = Column(String(500), nullable=False, default="")
    keywords         = Column(JSON, nullable=False, default=list)
    auto_download    = Column(Boolean, default=False)
    crawl_type       = Column(String(50), default="full")
    page_start       = Column(Integer, nullable=True)
    page_step        = Column(Integer, nullable=True)
    page_max         = Column(Integer, nullable=True)
    status           = Column(Enum(CrawlStatus, values_callable=lambda x: [e.value for e in x]), default=CrawlStatus.PENDING)
    error_message    = Column(Text, nullable=True)
    pages_crawled    = Column(Integer, default=0)
    files_found      = Column(Integer, default=0)
    files_downloaded = Column(Integer, default=0)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at      = Column(DateTime, nullable=True)
    header     = relationship("Header", back_populates="crawl_jobs")
    found_files= relationship("FoundFile", back_populates="crawl_job", )


class FoundFile(Base):
    __tablename__     = "found_files"
    id                = Column(String(ID_LEN), primary_key=True, default=gen_uuid, index=True)
    crawl_job_id      = Column(String(ID_LEN), ForeignKey("crawl_jobs.id"), nullable=False)
    url               = Column(Text, nullable=False)
    resolved_url      = Column(Text, nullable=True)
    # nom canonique : entier-prefix retiré, e.g. "452000-bac-2010.pdf" → "bac-2010.pdf"
    canonical_name    = Column(String(500), nullable=True, index=True)
    filename          = Column(String(500), nullable=False)
    keywords_matched  = Column(JSON, default=list)
    is_downloaded     = Column(Boolean, default=False)
    # Le blob du fichier vit sur Cloudflare R2 — on ne garde ici que sa clé.
    r2_key            = Column(String(700), nullable=True)
    thumbnail_r2_key  = Column(String(700), nullable=True)
    file_size         = Column(BigInteger, nullable=True)
    mime_type         = Column(String(200), nullable=True)
    discovered_at     = Column(DateTime, default=datetime.utcnow)
    downloaded_at     = Column(DateTime, nullable=True)
    crawl_job         = relationship("CrawlJob", back_populates="found_files")
    favorites         = relationship("Favorite", back_populates="found_file")


class UploadedFile(Base):
    __tablename__       = "uploaded_files"
    id                  = Column(String(ID_LEN), primary_key=True, default=gen_uuid, index=True)
    original_filename   = Column(String(500), nullable=False)
    filename            = Column(String(500), nullable=False)
    canonical_name      = Column(String(500), nullable=True, index=True)
    # Le blob du fichier vit sur Cloudflare R2 — on ne garde ici que sa clé.
    r2_key              = Column(String(700), nullable=True)
    thumbnail_r2_key    = Column(String(700), nullable=True)
    file_size           = Column(BigInteger, nullable=True)
    mime_type           = Column(String(200), nullable=True)
    uploaded_by         = Column(String(ID_LEN), ForeignKey("users.id"), nullable=True)
    uploaded_at         = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    uploader            = relationship("User")
    favorites           = relationship("Favorite", back_populates="uploaded_file",)


class Favorite(Base):
    """Favoris — peut pointer vers un FoundFile ou un UploadedFile."""
    __tablename__      = "favorites"
    id                 = Column(String(ID_LEN), primary_key=True, default=gen_uuid, index=True)
    # session_key : identifiant anonyme (cookie/localStorage) ou user_id si connecté
    session_key        = Column(String(255), nullable=False, index=True)
    found_file_id      = Column(String(ID_LEN), ForeignKey("found_files.id"), nullable=True)
    uploaded_file_id   = Column(String(ID_LEN), ForeignKey("uploaded_files.id"), nullable=True)
    added_at           = Column(DateTime, default=datetime.utcnow)
    found_file         = relationship("FoundFile",   back_populates="favorites")
    uploaded_file      = relationship("UploadedFile", back_populates="favorites")


class DuplicateGroup(Base):
    """Résultat du scan de doublons — groupe de fichiers similaires."""
    __tablename__ = "duplicate_groups"
    id            = Column(String(ID_LEN), primary_key=True, default=gen_uuid, index=True)
    reason        = Column(String(50), nullable=False)   # "same_size" | "similar_name"
    similarity    = Column(Float, nullable=True)          # 0–1 pour similar_name
    file_ids      = Column(JSON, nullable=False)          # liste d'IDs FoundFile (strings)
    scanned_at    = Column(DateTime, default=datetime.utcnow)
