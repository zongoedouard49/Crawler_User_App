from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict
from datetime import datetime
from models import CrawlStatus


def _as_str(v):
    """Convertit un id en string pour éviter la perte de précision JS sur les
    grands entiers 64 bits (ex: unique_rowid() de CockroachDB)."""
    return None if v is None else str(v)


class HeaderCreate(BaseModel):
    name: str
    values: Dict[str, str]
    suffix_file: Optional[str] = ""
    url_complete: bool = False
    # page_param : nom du paramètre de pagination (ex: "start", "SujetId", "page", "offset")
    page_param: Optional[str] = "start"


class HeaderUpdate(BaseModel):
    name: Optional[str] = None
    values: Optional[Dict[str, str]] = None
    suffix_file: Optional[str] = None
    url_complete: Optional[bool] = None
    page_param: Optional[str] = None


class HeaderOut(BaseModel):
    id: str
    name: str
    values: Dict[str, str]
    suffix_file: Optional[str] = ""
    url_complete: bool = False
    page_param: Optional[str] = "start"
    created_at: datetime
    updated_at: datetime

    _id_str = field_validator("id", mode="before")(_as_str)

    class Config:
        from_attributes = True


class CrawlJobCreate(BaseModel):
    base_url: str
    header_id: Optional[str] = None
    file_prefix: str = ""
    keywords: List[str] = []
    auto_download: bool = False
    crawl_type: str = "full"
    page_start: Optional[int] = None
    page_step: Optional[int] = None
    page_max: Optional[int] = None


class CrawlJobOut(BaseModel):
    id: str
    base_url: str
    header_id: Optional[str]
    file_prefix: str
    keywords: List[str]
    auto_download: bool
    crawl_type: str
    page_start: Optional[int]
    page_step: Optional[int]
    page_max: Optional[int]
    status: CrawlStatus
    error_message: Optional[str]
    pages_crawled: int
    files_found: int
    files_downloaded: int
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]

    _id_str = field_validator("id", "header_id", mode="before")(_as_str)

    class Config:
        from_attributes = True


class FoundFileOut(BaseModel):
    id: str
    crawl_job_id: str
    url: str
    resolved_url: Optional[str]
    filename: str
    keywords_matched: List[str]
    is_downloaded: bool
    has_thumbnail: bool = False
    file_size: Optional[int]
    mime_type: Optional[str]
    discovered_at: datetime
    downloaded_at: Optional[datetime]

    _id_str = field_validator("id", "crawl_job_id", mode="before")(_as_str)

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_safe(cls, obj):
        return cls(
            id=obj.id,
            crawl_job_id=obj.crawl_job_id,
            url=obj.url,
            resolved_url=obj.resolved_url,
            filename=obj.filename,
            keywords_matched=obj.keywords_matched or [],
            is_downloaded=obj.is_downloaded,
            has_thumbnail=bool(obj.thumbnail_r2_key),
            file_size=obj.file_size,
            mime_type=obj.mime_type,
            discovered_at=obj.discovered_at,
            downloaded_at=obj.downloaded_at,
        )


class FileSearchParams(BaseModel):
    keywords: List[str] = []
    downloaded_only: bool = False


class MergeFilesRequest(BaseModel):
    file_ids: List[str]
    output_filename: str = "merged_document.pdf"


class PaginatedFiles(BaseModel):
    items: List[FoundFileOut]
    total: int
    page: int
    page_size: int
    total_pages: int
