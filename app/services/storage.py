"""
Storage abstraction. Defaults to local disk; switches to S3 / Cloudflare R2
when STORAGE_BACKEND is set to "s3" or "r2" (R2 is just S3-compatible).

IMPORTANT: rendering code (ReportLab, qrcode/PIL) needs real local file
handles. So every backend exposes:
  - save(relative_path, data)      → upload/write bytes
  - exists(relative_path)          → check if the object exists
  - get(relative_path)             → return bytes
  - fetch_to_temp(relative_path)   → write to a local temp file and return
                                     its path (caller must os.unlink() after)

Nothing here assumes a remote file is also on local disk.
"""
import tempfile
from pathlib import Path

from botocore.config import Config
from app.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# How long to wait when connecting to or reading from S3/R2.
# Without these, boto3 can hang indefinitely on a slow/unreachable endpoint.
S3_CONNECT_TIMEOUT = 10
S3_READ_TIMEOUT = 30


def resolve_storage_path(relative_path: str | Path) -> Path:
    """Resolve a relative_path to a LOCAL filesystem path.
    Only meaningful for LocalStorage. Do NOT use this as a renderable path
    when STORAGE_BACKEND is s3/r2 — use storage.fetch_to_temp() instead."""
    path = Path(relative_path)
    if path.is_absolute():
        return path
    base_path = Path(settings.LOCAL_STORAGE_PATH)
    if not base_path.is_absolute():
        base_path = PROJECT_ROOT / base_path
    return base_path / path


def save_to_local_temp(data: bytes, suffix: str = "") -> str:
    """Write bytes to a temp file and return its absolute path.
    The caller is responsible for deleting it after use (os.unlink)."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
    finally:
        tmp.close()
    return tmp.name


class LocalStorage:
    def save(self, relative_path: str, data: bytes) -> str:
        full_path = resolve_storage_path(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        return relative_path

    def exists(self, relative_path: str) -> bool:
        return resolve_storage_path(relative_path).exists()

    def get(self, relative_path: str) -> bytes:
        return resolve_storage_path(relative_path).read_bytes()

    def fetch_to_temp(self, relative_path: str, suffix: str = "") -> str:
        """For LocalStorage, the file is already on disk — just return its path.
        Caller should NOT delete this path (it's the real file, not a temp copy)."""
        return str(resolve_storage_path(relative_path))

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
            config=Config(
                connect_timeout=S3_CONNECT_TIMEOUT,
                read_timeout=S3_READ_TIMEOUT,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        self.bucket = settings.S3_BUCKET

    def save(self, relative_path: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=relative_path, Body=data)
        return relative_path

    def exists(self, relative_path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=relative_path)
            return True
        except self.client.exceptions.ClientError:
            return False
        except Exception:
            return False

    def get(self, relative_path: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=relative_path)
        return response["Body"].read()

    def fetch_to_temp(self, relative_path: str, suffix: str = "") -> str:
        """Download from S3 into a local temp file. Returns the local path.
        Caller MUST os.unlink() this path after use."""
        data = self.get(relative_path)
        return save_to_local_temp(data, suffix=suffix)

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
