"""
crawler.py — Crawl async (httpx) + DB sync (psycopg2/SessionLocal)

Architecture :
  - Le crawl tourne dans un ThreadPoolExecutor dédié (route_crawls.py)
  - Chaque thread crée son propre event loop via asyncio.run()
  - Dans cet event loop isolé, on peut appeler httpx (async) et
    SQLAlchemy sync (db.add / db.commit) sans bloquer l'event loop principal
  - Cache in-memory _crawl_state[job_id] mis à jour à chaque fichier trouvé
    → endpoint /filenames retourne ce cache sans toucher la DB
"""
import asyncio
import re
import os
import hashlib
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Set
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from sqlalchemy import select

from models import CrawlJob, FoundFile, CrawlStatus, Header
from config import get_settings
from storage_r2 import upload_bytes, make_key

settings = get_settings()

_HTTP_CONCURRENCY     = 8
_DOWNLOAD_CONCURRENCY = 4
_MAX_RETRIES          = 3
_RETRY_BACKOFF        = [1, 3, 7]
_MAX_QUEUE_SIZE       = 5000
_BATCH_SIZE           = 15

_SKIP_EXTENSIONS = {
    '.jpg','.jpeg','.png','.gif','.webp','.svg','.ico',
    '.mp4','.mp3','.avi','.zip','.rar','.exe','.css',
    '.js','.xml','.json','.txt','.csv','.xlsx','.docx',
}
_NO_RETRY_CODES = {400, 401, 403, 404, 410, 503, 508}


# ── Cache in-memory des crawls actifs ────────────────────────────
_crawl_state: Dict[str, Dict] = {}


def get_crawl_filenames(job_id: str) -> Dict:
    """Retourne le cache mémoire — AUCUNE requête DB."""
    s = _crawl_state.get(job_id, {})
    return {"filenames": list(s.get("filenames", [])),
            "count": s.get("count", 0),
            "active": s.get("active", False)}


def _init_crawl_state(job_id: str):
    _crawl_state[job_id] = {"filenames": [], "count": 0, "active": True}


def _add_filename(job_id: str, filename: str):
    if job_id in _crawl_state:
        _crawl_state[job_id]["filenames"].append(filename)
        _crawl_state[job_id]["count"] += 1


def _close_crawl_state(job_id: str):
    if job_id in _crawl_state:
        _crawl_state[job_id]["active"] = False


def cleanup_crawl_state(job_id: str):
    _crawl_state.pop(job_id, None)


# ── Helpers ───────────────────────────────────────────────────────

def _has_skip_ext(url: str) -> bool:
    _, ext = os.path.splitext(urlparse(url).path.lower())
    return ext in _SKIP_EXTENSIONS


def extract_filename(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    return re.sub(r'^\d+[-_\s]*', '', name).strip()


def canonical_name(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    cleaned = re.sub(r'^\d+[-_]', '', name).strip('-').strip()
    return (cleaned + ext) if cleaned else filename


def build_headers(header_obj: Optional[Header]) -> Dict[str, str]:
    return dict(header_obj.values) if header_obj else {}


def is_url_complete(url: str, header_obj: Optional[Header]) -> bool:
    if header_obj and header_obj.url_complete:
        return True
    u = url.lower().rstrip("/")
    return any(u.endswith(e) for e in (".pdf",".doc",".docx",".xls",".xlsx","/download"))


def resolve_download_url(url: str, header_obj: Optional[Header], fallback: str = "") -> str:
    if is_url_complete(url, header_obj):
        return url
    suffix = header_obj.suffix_file if (header_obj and header_obj.suffix_file is not None) else fallback
    return f'{url.rstrip("/")}{suffix}'


def keywords_match(url: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    u = url.lower()
    return all(k.lower() in u for k in keywords)


def generate_thumbnail(pdf_bytes: bytes, max_size: int = 300) -> Optional[bytes]:
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if not doc.page_count:
            return None
        zoom = max_size / max(doc[0].rect.width, 1)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB)
        data = pix.tobytes("jpeg")
        doc.close()
        return data
    except Exception as e:
        print(f"[THUMB] {e}")
        return None


def extract_links(html: str, base_url: str) -> Set[str]:
    soup = BeautifulSoup(html, "lxml")
    links: Set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        full = urljoin(base_url, href).split("#")[0]
        if not _has_skip_ext(full):
            links.add(full)
    return links


# ── HTTP helpers ──────────────────────────────────────────────────

async def fetch_page(url: str, headers: Dict, client: httpx.AsyncClient) -> Optional[str]:
    for attempt in range(_MAX_RETRIES):
        try:
            r = await client.get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT)
            if r.status_code in _NO_RETRY_CODES:
                return None
            r.raise_for_status()
            return r.text
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BACKOFF[attempt])
        except Exception:
            break
    return None


def download_file_sync(url: str, headers: Dict, ff: FoundFile, db: Session) -> bool:
    """Téléchargement synchrone — utilisé depuis les routes utilisateur."""
    import httpx as _httpx
    try:
        with _httpx.Client(timeout=60, follow_redirects=True) as client:
            r = client.get(url, headers=headers)
            r.raise_for_status()
            data = r.content
            mime = r.headers.get("content-type", "application/octet-stream").split(";")[0]
        r2_key = upload_bytes(make_key("found_files", ff.filename), data, mime)
        thumb_key = None
        if mime == "application/pdf":
            thumb = generate_thumbnail(data)
            if thumb:
                thumb_key = upload_bytes(
                    make_key("found_files_thumbs", f"{ff.filename}.jpg"), thumb, "image/jpeg"
                )
        ff.is_downloaded      = True
        ff.r2_key             = r2_key
        ff.thumbnail_r2_key   = thumb_key
        ff.file_size          = len(data)
        ff.mime_type          = mime
        ff.downloaded_at      = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        print(f"[DL ERROR] {url}: {e}")
        return False


async def _download_async(url: str, headers: Dict, ff: FoundFile, db: Session) -> bool:
    """Téléchargement async — utilisé pendant un crawl (thread dédié)."""
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.content
            mime = r.headers.get("content-type", "application/octet-stream").split(";")[0]
        r2_key = upload_bytes(make_key("found_files", ff.filename), data, mime)
        thumb_key = None
        if mime == "application/pdf":
            thumb = generate_thumbnail(data)
            if thumb:
                thumb_key = upload_bytes(
                    make_key("found_files_thumbs", f"{ff.filename}.jpg"), thumb, "image/jpeg"
                )
        ff.is_downloaded    = True
        ff.r2_key           = r2_key
        ff.thumbnail_r2_key = thumb_key
        ff.file_size        = len(data)
        ff.mime_type        = mime
        ff.downloaded_at    = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        print(f"[DL ASYNC ERROR] {url}: {e}")
        return False


# ── Batch processing ──────────────────────────────────────────────

async def _process_links_batch(
    links: Set[str],
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    job: CrawlJob,
    hdrs: Dict,
    db: Session,
    dl_sem: asyncio.Semaphore,
    seen: Set[str],
):
    async def _one(link: str):
        if not keywords_match(link, job.keywords or []):
            return
        filename = extract_filename(link)
        if not filename or filename in seen:
            return
        seen.add(filename)

        dl_url = resolve_download_url(link, job.header, job.file_prefix or "")
        ff = FoundFile(
            crawl_job_id       = job.id,
            url                = link,
            resolved_url       = dl_url,
            filename           = filename,
            canonical_name     = canonical_name(filename),
            keywords_matched   = [k for k in (job.keywords or []) if k.lower() in link.lower()],
        )
        db.add(ff)
        job.files_found += 1
        db.commit()
        db.refresh(ff)

        # ── Cache mémoire (pas de requête DB) ──
        _add_filename(job.id, filename)

        if job.auto_download:
            async with dl_sem:
                await _download_async(dl_url, hdrs, ff, db)

    async with sem:
        await asyncio.gather(*[_one(l) for l in links], return_exceptions=True)


# ── Stratégies de crawl ───────────────────────────────────────────

async def _crawl_single(job: CrawlJob, db: Session):
    hdrs = build_headers(job.header)
    sem = asyncio.Semaphore(_HTTP_CONCURRENCY)
    dl_sem = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)
    seen: Set[str] = set()
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        html = await fetch_page(job.base_url, hdrs, client)
        if html:
            job.pages_crawled += 1
            db.commit()
            await _process_links_batch(extract_links(html, job.base_url), client, sem, job, hdrs, db, dl_sem, seen)


async def _crawl_full(job: CrawlJob, db: Session):
    hdrs = build_headers(job.header)
    sem = asyncio.Semaphore(_HTTP_CONCURRENCY)
    dl_sem = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)
    seen: Set[str] = set()
    visited: Set[str] = set()
    queue: List[str] = [job.base_url]
    base_domain = urlparse(job.base_url).netloc

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        while queue and job.status != CrawlStatus.CANCELLED:
            batch, queue = queue[:_BATCH_SIZE], queue[_BATCH_SIZE:]
            visited.update(batch)
            next_pages: Set[str] = set()

            async def _fetch_one(url: str):
                try:
                    html = await fetch_page(url, hdrs, client)
                    if not html:
                        return
                    job.pages_crawled += 1
                    db.commit()
                    links = extract_links(html, url)
                    file_links, nav_links = set(), set()
                    for lnk in links:
                        if urlparse(lnk).netloc != base_domain:
                            continue
                        if re.search(r"/\d+-[a-z0-9-]+/?$", lnk.lower()) or lnk.endswith('.pdf'):
                            file_links.add(lnk)
                        elif lnk not in visited and lnk not in queue:
                            nav_links.add(lnk)
                    await _process_links_batch(file_links, client, sem, job, hdrs, db, dl_sem, seen)
                    next_pages.update(nav_links)
                except Exception as e:
                    print(f"[CRAWL WARN] {url}: {e}")

            await asyncio.gather(*[_fetch_one(u) for u in batch], return_exceptions=True)
            for lnk in next_pages:
                if lnk not in visited and lnk not in queue and len(queue) < _MAX_QUEUE_SIZE:
                    queue.append(lnk)


async def _crawl_paginated(job: CrawlJob, db: Session):
    hdrs = build_headers(job.header)
    start = job.page_start or 0
    step  = job.page_step  or 10
    maxp  = job.page_max   or 12
    param = (job.header.page_param or "start") if job.header else "start"
    seen: Set[str] = set()
    sem = asyncio.Semaphore(_HTTP_CONCURRENCY)
    dl_sem = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)
    base = job.base_url
    sep  = "&" if "?" in base else "?"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for offset in range(start, start + step * maxp, step):
            url = f"{base}{sep}{param}={offset}"
            try:
                html = await fetch_page(url, hdrs, client)
                if not html:
                    continue
                job.pages_crawled += 1
                db.commit()
                await _process_links_batch(extract_links(html, url), client, sem, job, hdrs, db, dl_sem, seen)
            except Exception as e:
                print(f"[CRAWL PAGED WARN] {url}: {e}")


# ── Point d'entrée ────────────────────────────────────────────────

async def run_crawl_job(job_id: str, db: Session) -> bool:
    """
    Appelé via asyncio.run() dans un thread dédié (ThreadPoolExecutor).
    Utilise httpx (async) pour les requêtes HTTP et
    la session sync db (psycopg2) pour les écritures DB.
    """
    job = db.scalars(select(CrawlJob).filter_by(id=job_id)).first()
    if not job:
        return False

    job.status     = CrawlStatus.RUNNING
    job.updated_at = datetime.utcnow()
    db.commit()
    _init_crawl_state(job_id)
    disconnected = False

    try:
        if   job.crawl_type == "single":     await _crawl_single(job, db)
        elif job.crawl_type == "paginated":  await _crawl_paginated(job, db)
        else:                                await _crawl_full(job, db)

        if job.status != CrawlStatus.CANCELLED:
            job.status = CrawlStatus.COMPLETED

    except (httpx.RemoteProtocolError, httpx.ConnectError) as e:
        print(f"[CRAWL Disconnect] {job_id}: {e}")
        job.status        = CrawlStatus.PENDING
        job.error_message = f"Disconnect (relance auto): {e}"
        job.finished_at   = None
        db.commit()
        disconnected = True

    except Exception as e:
        import traceback
        job.status        = CrawlStatus.FAILED
        job.error_message = str(e)
        print(f"[CRAWL FAILED] {job_id}: {e}\n{traceback.format_exc()}")

    finally:
        _close_crawl_state(job_id)
        if not disconnected:
            job.finished_at = datetime.utcnow()
            job.updated_at  = datetime.utcnow()
            db.commit()

    return disconnected
