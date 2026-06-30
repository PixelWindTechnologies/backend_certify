"""
Storage abstraction. Defaults to local disk; switches to S3 / Cloudflare R2
when STORAGE_BACKEND is set to "s3" or "r2" (R2 is just S3-compatible).
IMPORTANT: rendering code (ReportLab, qrcode/PIL) needs a real local file
handle to write to / read from — it can't write straight to S3. So every
storage backend supports `save(relative_path, data)` which takes bytes,
writes them to a local temp/working copy, AND uploads them when the
backend is remote. Callers never need to special-case the backend.
"""
from pathlib import Path
import tempfile
from app.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_storage_path(relative_path: str | Path) -> Path:
    """Resolve a relative_path to a LOCAL filesystem path. Only meaningful
    for the LocalStorage backend (or as a local working-copy location).
    Do NOT assume this path exists when STORAGE_BACKEND is s3/r2 unless
    you've just called storage.save() with the same relative_path on a
    LocalStorage instance."""
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
        return relative_path

    def get(self, relative_path: str) -> bytes:
        return resolve_storage_path(relative_path).read_bytes()

    def local_path_for(self, relative_path: str) -> str:
        """Path usable for rendering libs that need a real file handle."""
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
        )
        self.bucket = settings.S3_BUCKET

    def save(self, relative_path: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=relative_path, Body=data)
        return relative_path

    def get(self, relative_path: str) -> bytes:
        """Downloads and returns the object's bytes from S3/R2."""
        obj = self.client.get_object(Bucket=self.bucket, Key=relative_path)
        return obj["Body"].read()

    def local_path_for(self, relative_path: str) -> str:
        """S3-backed storage has no durable local file — callers that need
        a real file handle for rendering (PDF backgrounds, QR images, etc.)
        should use save_to_local_temp() instead and keep that path separate
        from the storage key."""
        raise NotImplementedError(
            "S3Storage has no local path; use save_to_local_temp() for a "
            "renderable file, and save()/the returned relative_path for "
            "the durable storage key."
        )

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


def save_to_local_temp(data: bytes, suffix: str = "") -> str:
    """Writes bytes to a local temp file and returns its absolute path.
    Use this whenever a rendering library (ReportLab's ImageReader,
    PIL, etc.) needs to open the content as a real file, regardless of
    which storage backend is configured. The caller is responsible for
    deleting the temp file once rendering is done."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
    finally:
        tmp.close()
    return tmp.name


def resolve_to_local_temp(relative_path: str, suffix: str = "") -> str:
    """Returns a LOCAL filesystem path that is guaranteed to actually exist
    and contain the file's current bytes, regardless of storage backend.

    For LocalStorage this is just the real path on disk (no copy needed).
    For S3Storage this downloads the object's bytes into a fresh local
    temp file and returns that path.

    Callers should check `is_temp_path` (returned alongside, see
    resolve_to_local_temp_with_flag) if they need to know whether to
    delete the file afterward. This simple version is for callers that
    don't need that distinction immediately."""
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        return storage.local_path_for(relative_path)
    data = storage.get(relative_path)
    suffix = suffix or Path(relative_path).suffix
    return save_to_local_temp(data, suffix=suffix)
