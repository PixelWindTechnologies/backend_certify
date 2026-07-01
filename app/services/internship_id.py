"""
Generates the unique internship / certificate identifier:
    PW/VSP/<CourseCode>/<StudentNumber>
Example: PW/VSP/DA/0001
"""
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.models import Course, Enrollment


def build_internship_id(course: Course, student_sequence: int) -> str:
    student_part = f"{student_sequence:04d}"
    return f"PW/VSP/{course.code}/{student_part}"


def next_student_sequence(db: Session, course_id: str, college_id: str) -> int:
    """Returns the next available sequence number that produces a unique
    internship_id. Uses MAX(student_sequence) + 1 to avoid collisions
    caused by deletions or gaps, then verifies the generated ID doesn't
    already exist and increments further if needed."""
    max_seq = (
        db.query(func.max(Enrollment.student_sequence))
        .filter(
            Enrollment.course_id == course_id,
            Enrollment.college_id == college_id,
        )
        .scalar()
    ) or 0

    sequence = max_seq + 1

    # Safety check: keep incrementing until the generated ID is truly unused
    course = db.query(Course).filter(Course.id == course_id).first()
    while True:
        candidate_id = build_internship_id(course, sequence)
        exists = (
            db.query(Enrollment)
            .filter(Enrollment.internship_id == candidate_id)
            .first()
        )
        if not exists:
            return sequence
        sequence += 1
