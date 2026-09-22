"""merger.py — fusion de PDFs avec déduplication des pages."""
import io
import hashlib
from typing import List, Tuple
import fitz

from storage_r2 import download_bytes


def _page_hash(page: fitz.Page) -> str:
    text = page.get_text("text").strip().encode("utf-8", errors="replace")
    pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), colorspace=fitz.csGRAY)
    return hashlib.md5(text + pix.tobytes()).hexdigest()


def merge_pdf_bytes(files_data: List[Tuple[str, str, bytes]], output_filename: str) -> bytes:
    """
    files_data: liste de (file_id, filename, raw_bytes)
    Retourne les bytes du PDF fusionné, pages dupliquées supprimées.
    """
    merger = fitz.open()
    seen: set = set()
    skipped = 0

    for (_id, filename, data) in files_data:
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as e:
            print(f"[MERGE] Impossible d'ouvrir {filename}: {e}")
            continue

        to_insert = []
        for pnum in range(doc.page_count):
            h = _page_hash(doc[pnum])
            if h in seen:
                skipped += 1
                continue
            seen.add(h)
            to_insert.append(pnum)

        for pnum in to_insert:
            merger.insert_pdf(doc, from_page=pnum, to_page=pnum)
        doc.close()

    if skipped:
        print(f"[MERGE] {skipped} page(s) dupliquée(s) ignorée(s)")

    buf = io.BytesIO()
    merger.save(buf)
    merger.close()
    return buf.getvalue()
