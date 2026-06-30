"""
Storage abstraction. Defaults to local disk; switches to S3 / Cloudflare R2
/ Backblaze B2 when STORAGE_BACKEND is set to "s3" or "r2" (all are S3-compatible).
"""
import tempfile
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

    def get(self, relative_path: str) -> bytes:
        full_path = resolve_storage_path(relative_path)
        if not full_path.exists():
            raise FileNotFoundError(f"{relative_path} not found in local storage")
        return full_path.read_bytes()

    def exists(self, relative_path: str) -> bool:
        return resolve_storage_path(relative_path).exists()

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

    def get(self, relative_path: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=relative_path)
        return response["Body"].read()

    def exists(self, relative_path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=relative_path)
            return True
        except Exception:
            return False

    def url_for(self, relative_path: str) -> str:
        if settings.S3_PUBLIC_URL:
            return f"{settings.S3_PUBLIC_URL}/{relative_path}"
        return f"{settings.S3_ENDPOINT_URL}/{self.bucket}/{relative_path}"


def get_storage():
    if settings.STORAGE_BACKEND in ("s3", "r2"):
        return S3Storage()
    return LocalStorage()


def save_to_local_temp(relative_path: str, suffix: str = "") -> str:
    """
    Downloads a file from storage (S3/B2/local) into a local temp file
    and returns the temp file path. Used by ReportLab and QR engine
    which need a real local filesystem path, not bytes.
    Caller is responsible for deleting the temp file when done.
    """
    storage = get_storage()
    data = storage.get(relative_path)
    ext = suffix or Path(relative_path).suffix or ".tmp"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        return tmp.name
