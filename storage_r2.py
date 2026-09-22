"""
storage_r2.py — client de stockage objet pour Cloudflare R2 (API compatible S3).

Toutes les données binaires (PDF téléchargés, uploads manuels, thumbnails)
sont stockées sur R2. La base de données ne conserve que les métadonnées
légères (nom, taille, mime_type, clé R2, ...).

Nécessite les variables d'environnement suivantes (voir .env.example) :
    R2_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET_NAME
    R2_PUBLIC_URL      (optionnel — si le bucket a un domaine public / R2.dev)
"""
import uuid
import unicodedata
from functools import lru_cache
from typing import Optional
from urllib.parse import quote

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from config import get_settings

settings = get_settings()


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    """Construit un header Content-Disposition valide même avec des noms de
    fichiers contenant des caractères non-Latin-1 (accents, tirets « – », etc.).

    Les headers HTTP doivent être encodables en latin-1 ; on fournit donc un
    nom ASCII de repli (filename=) et le nom complet encodé UTF-8 (filename*=),
    conformément à la RFC 5987/6266. Les navigateurs modernes utilisent filename*.
    """
    filename = filename or "file"
    ascii_fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_fallback = ascii_fallback.replace('"', "'").strip() or "file"
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@lru_cache()
def get_r2_client():
    """Client boto3 configuré pour l'endpoint S3 compatible de Cloudflare R2."""
    endpoint_url = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=BotoConfig(signature_version="s3v4", region_name="auto"),
    )


def make_key(prefix: str, filename: str) -> str:
    """Génère une clé d'objet unique et sans collision.

    ex: make_key("found_files", "bac-2010.pdf")
        -> "found_files/3f9c1e2b7a6d4c5e/bac-2010.pdf"
    """
    safe_name = (filename or "file").replace("/", "_").replace("\\", "_")
    return f"{prefix}/{uuid.uuid4().hex}/{safe_name}"


def upload_bytes(key: str, data: bytes, content_type: Optional[str] = None) -> str:
    """Upload un blob vers R2 et retourne la clé utilisée."""
    if not data:
        return key
    client = get_r2_client()
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=settings.R2_BUCKET_NAME, Key=key, Body=data, **extra)
    return key


def download_bytes(key: str) -> Optional[bytes]:
    """Télécharge un blob depuis R2. Retourne None si absent."""
    if not key:
        return None
    client = get_r2_client()
    try:
        obj = client.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
        return obj["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def delete_object(key: str) -> None:
    """Supprime un blob de R2 (silencieux si absent)."""
    if not key:
        return
    client = get_r2_client()
    try:
        client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    except ClientError:
        pass


def presigned_url(key: str, expires_in: int = 3600, filename: Optional[str] = None,
                   disposition: str = "attachment") -> Optional[str]:
    """Génère une URL signée temporaire pour accès direct au fichier sur R2.

    Utile pour éviter de faire transiter le blob par le serveur FastAPI —
    le navigateur télécharge/affiche directement depuis R2.
    """
    if not key:
        return None
    client = get_r2_client()
    params = {"Bucket": settings.R2_BUCKET_NAME, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'{disposition}; filename="{filename}"'
    return client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)
