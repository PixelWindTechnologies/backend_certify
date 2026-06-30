from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.models import Certificate, Enrollment, Student
from app.api.routes.certificates import build_certificate_download_filename


def test_build_certificate_download_filename_uses_student_name():
    student = Student(full_name="Jane Doe", phone="1234567890", email="jane@example.com")
    enrollment = Enrollment(student=student, internship_id="INT-100", student_sequence=1)
    certificate = Certificate(id="cert-123", enrollment=enrollment)

    filename = build_certificate_download_filename(certificate)

    assert filename == "jane-doe-cert-123.pdf"
