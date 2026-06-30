"""add training_type to enrollments and migrate legacy batch schema
Revision ID: 0004_add_training_type_to_enrollments
Revises: 0003_aicte_internship_id
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    # Create enum type first (skip if already exists from previous failed run)
    op.execute("DO $$ BEGIN CREATE TYPE trainingtype AS ENUM ('INTERNSHIP', 'INDUSTRIAL_TRAINING'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # Add training_type only if it doesn't exist
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='enrollments' AND column_name='training_type'
            ) THEN
                ALTER TABLE enrollments ADD COLUMN training_type trainingtype NOT NULL DEFAULT 'INTERNSHIP';
            END IF;
        END $$;
    """)

    # Add course_id only if it doesn't exist
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='enrollments' AND column_name='course_id'
            ) THEN
                ALTER TABLE enrollments ADD COLUMN course_id VARCHAR(36) REFERENCES courses(id);
            END IF;
        END $$;
    """)

    # Add college_id only if it doesn't exist
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='enrollments' AND column_name='college_id'
            ) THEN
                ALTER TABLE enrollments ADD COLUMN college_id VARCHAR(36) REFERENCES colleges(id);
            END IF;
        END $$;
    """)

    # Migrate data from batches if table exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'batches' AND table_schema = 'public'
            ) THEN
                UPDATE enrollments
                SET course_id = batches.course_id,
                    college_id = batches.college_id
                FROM batches
                WHERE enrollments.batch_id = batches.id;
            END IF;
        END $$;
    """)

    op.alter_column("enrollments", "course_id", nullable=False)
    op.alter_column("enrollments", "college_id", nullable=False)

    # Drop batch_id if exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'enrollments' AND column_name = 'batch_id' AND table_schema = 'public'
            ) THEN
                ALTER TABLE enrollments DROP COLUMN batch_id;
            END IF;
        END $$;
    """)


def downgrade():
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'enrollments' AND column_name = 'batch_id' AND table_schema = 'public'
            ) THEN
                ALTER TABLE enrollments ADD COLUMN batch_id VARCHAR(36);
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'batches' AND table_schema = 'public'
            ) THEN
                UPDATE enrollments
                SET batch_id = batches.id
                FROM batches
                WHERE enrollments.course_id = batches.course_id
                  AND enrollments.college_id = batches.college_id;
            END IF;
        END $$;
    """)

    op.alter_column("enrollments", "batch_id", nullable=True)
    op.drop_column("enrollments", "college_id")
    op.drop_column("enrollments", "course_id")
    op.drop_column("enrollments", "training_type")
    op.execute("DROP TYPE IF EXISTS trainingtype")
