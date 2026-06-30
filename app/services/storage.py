"""
Storage abstraction. Defaults to local disk; switches to S3 / Cloudflare R2
when STORAGE_BACKEND is set to "s3" or "r2" (R2 is just S3-compatible).
"""
from pathlib import Path

from app.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_storage_path(relative_path: str | Path) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        return path

    base_path = Path(settings.LOCAL_STORAGE_PATH)
    if not base_path.is_absolute():
        base_path = PROJECT_ROOT / base_path
    return base_path / path


class LocalStorage:
    def save(self, relative_path: str, data: bytes) -> str:
        full_path = resolve_storage_path(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        return str(full_path)

    def url_for(self, relative_path: str) -> str:
        return f"/files/{relative_path}"


class S3Storage:
    def __init__(self):
        import boto3

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )
        self.bucket = settings.S3_BUCKET

    def save(self, relative_path: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=relative_path, Body=data)
        return relative_path

    def url_for(self, relative_path: str) -> str:
        if settings.S3_PUBLIC_URL:
            public_base = settings.S3_PUBLIC_URL.rstrip("/")
            return f"{public_base}/{relative_path.lstrip('/')}"
        if settings.S3_ENDPOINT_URL:
            return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self.bucket}/{relative_path.lstrip('/')}"
        return f"/{relative_path.lstrip('/')}"


def get_storage():
    if settings.STORAGE_BACKEND in ("s3", "r2"):
        return S3Storage()
    return LocalStorage()
