import base64
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from supabase import Client, create_client

from app.config import settings


logger = logging.getLogger(__name__)

class StorageService:
    _client: Optional[Client] = None
    _bucket: str = settings.supabase_bucket
    _allowed_content_types = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }

    @classmethod
    def _get_client(cls) -> Client:
        """Create Supabase client lazily to avoid startup failures in local dev."""
        if cls._client is None:
            if not settings.supabase_url or not settings.service_role_key:
                raise ValueError("SUPABASE_URL and SERVICE_ROLE_KEY are required for storage operations")
            cls._validate_service_role_key(settings.service_role_key)
            cls._client = create_client(settings.supabase_url, settings.service_role_key)
        return cls._client

    @staticmethod
    def _decode_jwt_payload(token: str) -> dict:
        try:
            payload = token.split(".")[1]
            padding = "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode("utf-8"))
            return json.loads(decoded.decode("utf-8"))
        except Exception as exc:
            raise ValueError("SERVICE_ROLE_KEY must be a valid JWT") from exc

    @classmethod
    def _validate_service_role_key(cls, service_role_key: str) -> None:
        claims = cls._decode_jwt_payload(service_role_key)
        if claims.get("role") != "service_role":
            raise ValueError("SERVICE_ROLE_KEY must use a service_role token")
        exp = claims.get("exp")
        if exp and int(exp) <= int(time.time()):
            raise ValueError("SERVICE_ROLE_KEY is expired")

    @classmethod
    def _build_storage_headers(cls) -> dict:
        cls._validate_service_role_key(settings.service_role_key)
        return {
            "apikey": settings.service_role_key,
            "Authorization": f"Bearer {settings.service_role_key}",
        }

    @classmethod
    def _upload_via_rest(
        cls,
        file_content: bytes,
        cloud_path: str,
        content_type: str,
    ) -> None:
        if not settings.supabase_url:
            raise ValueError("SUPABASE_URL is required for storage operations")

        upload_url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{cls._bucket}/{quote(cloud_path, safe='/')}"
        response = requests.post(
            upload_url,
            headers={
                **cls._build_storage_headers(),
                "x-upsert": "true",
            },
            files={"file": (Path(cloud_path).name, file_content, content_type)},
            timeout=60,
        )

        if response.ok:
            return

        error_message = response.text
        try:
            error_payload = response.json()
            error_message = error_payload.get("message") or error_payload.get("error") or error_message
        except Exception:
            pass

        raise ValueError(f"Supabase Storage upload failed: {response.status_code} {error_message}")

    @classmethod
    async def upload_to_supabase(
        cls,
        file_content: bytes,
        filename: str,
        user_id: str,
        document_type: str = "uncategorized",
    ):
        """
        Uploads file to a user-specific folder in Supabase.
        Path: user_{user_id}/{document_type}/{uuid}.{ext}
        """
        try:
            file_ext = Path(filename).suffix.lower()
            unique_filename = f"{uuid.uuid4()}{file_ext}"
            safe_doc_type = (document_type or "uncategorized").strip().lower().replace(" ", "_")
            cloud_path = f"user_{user_id}/{safe_doc_type}/{unique_filename}"
            
            content_type = cls._allowed_content_types.get(file_ext)
            if not content_type:
                allowed_types = ", ".join(sorted(set(cls._allowed_content_types.values())))
                return None, f"Unsupported file type '{file_ext or 'unknown'}'. Allowed MIME types: {allowed_types}"

            cls._get_client()
            cls._upload_via_rest(file_content, cloud_path, content_type)

            return cloud_path, None
        except Exception as e:
            logger.exception("Supabase upload failed for %s", filename)
            return None, str(e)

    @classmethod
    def get_temporary_url(cls, cloud_path: str, expires_in: int = 3600):
        """Generates a signed URL so teammates can view private docs"""
        client = cls._get_client()
        res = client.storage.from_(cls._bucket).create_signed_url(cloud_path, expires_in)
        return res.get("signedURL")

    @classmethod
    def download_from_supabase(cls, cloud_path: str):
        """Download file bytes from Supabase storage bucket."""
        client = cls._get_client()
        return client.storage.from_(cls._bucket).download(cloud_path)

    @classmethod
    def delete_from_supabase(cls, cloud_path: str):
        """Delete a file from Supabase storage bucket."""
        client = cls._get_client()
        response = client.storage.from_(cls._bucket).remove([cloud_path])
        return response