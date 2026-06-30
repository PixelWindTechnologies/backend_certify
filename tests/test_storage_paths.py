import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config
from app.services.storage import S3Storage, resolve_storage_path


def test_relative_storage_path_is_resolved_from_app_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "LOCAL_STORAGE_PATH", "storage")
    monkeypatch.chdir(tmp_path)

    resolved = resolve_storage_path("certificates/demo.pdf")

    expected = Path(__file__).resolve().parents[1] / "storage" / "certificates" / "demo.pdf"
    assert resolved == expected


def test_s3_storage_uses_public_url_when_configured(monkeypatch):
    monkeypatch.setattr(config.settings, "S3_PUBLIC_URL", "https://cdn.example.com")
    monkeypatch.setattr(config.settings, "S3_ENDPOINT_URL", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setattr(config.settings, "S3_BUCKET", "certificates")

    storage = S3Storage()

    assert storage.url_for("certificates/demo.pdf") == "https://cdn.example.com/certificates/demo.pdf"
