"""
QR code generation. Every certificate gets exactly one QR code encoding the
public verification URL.
"""
import io
import qrcode
from app.core.config import settings
from app.services.storage import get_storage, save_to_local_temp


def generate_qr_for_certificate(certificate_id: str) -> tuple[str, str]:
    """Generates a QR PNG for a certificate.

    Returns (local_render_path, storage_relative_path):
      - local_render_path: an actual file on local disk, suitable for
        ReportLab's ImageReader during PDF rendering. ALWAYS exists,
        regardless of storage backend. Caller should delete it once done.
      - storage_relative_path: the durable storage key (uploaded to S3/R2
        when STORAGE_BACKEND is remote, or the same local file when
        STORAGE_BACKEND is local) — use this for url_for()/DB persistence,
        never for rendering.
    """
    url = f"{settings.VERIFICATION_BASE_URL}/{certificate_id}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    data = buffer.getvalue()

    relative_path = f"qrcodes/{certificate_id}.png"
    storage = get_storage()
    storage.save(relative_path, data)

    # Always produce a real local file for rendering, independent of backend.
    local_render_path = save_to_local_temp(data, suffix=".png")

    return local_render_path, relative_path
