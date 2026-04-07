import uuid
from pathlib import Path
from supabase import create_client, Client
from app.config import settings
from typing import Optional

class StorageService:
    _client: Optional[Client] = None
    _bucket: str = settings.supabase_bucket

    @classmethod
    def _get_client(cls) -> Client:
        """Create Supabase client lazily to avoid startup failures in local dev."""
        if cls._client is None:
            if not settings.supabase_url or not settings.service_role_key:
                raise ValueError("SUPABASE_URL and SERVICE_ROLE_KEY are required for storage operations")
            cls._client = create_client(settings.supabase_url, settings.service_role_key)
        return cls._client

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
            file_ext = Path(filename).suffix
            unique_filename = f"{uuid.uuid4()}{file_ext}"
            safe_doc_type = (document_type or "uncategorized").strip().lower().replace(" ", "_")
            cloud_path = f"user_{user_id}/{safe_doc_type}/{unique_filename}"
            
            # Detect MIME type
            if file_ext == ".pdf":
                content_type = "application/pdf"
            elif file_ext in {".jpg", ".jpeg"}:
                content_type = "image/jpeg"
            elif file_ext == ".png":
                content_type = "image/png"
            elif file_ext == ".json":
                content_type = "application/json"
            else:
                content_type = "application/octet-stream"

            # Upload to Supabase Bucket
            client = cls._get_client()
            response = client.storage.from_(cls._bucket).upload(
                path=cloud_path,
                file=file_content,
                file_options={"content-type": content_type, "upsert": "true"}
            )
            
            return cloud_path, None
        except Exception as e:
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