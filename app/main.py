from contextlib import asynccontextmanager
from pathlib import Path
import concurrent.futures
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import (
    auth,
    colleges,
    courses,
    students,
    enrollments,
    certificates,
    verify,
    reports,
    audit,
)
from app.core.config import settings
from app.services.certificate_job import generate_pending_certificates

logger = logging.getLogger(__name__)

# How long the certificate job is allowed to run before being forcibly
# abandoned. Set to 5 minutes — generous enough for a large batch,
# but short enough to release the lock before the next 2-minute tick
# stacks up too many skips.
JOB_TIMEOUT_SECONDS = 300


def generate_pending_certificates_with_timeout():
    """Wrapper that runs generate_pending_certificates in a separate thread
    with a hard timeout. If the job hangs (e.g. S3 fetch stalls, DB query
    never returns), it will be abandoned after JOB_TIMEOUT_SECONDS and the
    APScheduler lock will be released so the next tick can run cleanly."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(generate_pending_certificates)
        try:
            result = future.result(timeout=JOB_TIMEOUT_SECONDS)
            logger.info(f"Certificate job completed: {result} certificates generated.")
        except concurrent.futures.TimeoutError:
            logger.error(
                f"Certificate job timed out after {JOB_TIMEOUT_SECONDS}s and was abandoned. "
                "Check for slow S3 fetches, hanging DB queries, or large batches."
            )
        except Exception as exc:
            logger.error(f"Certificate job failed with exception: {exc}", exc_info=True)


scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(1)},
    job_defaults={
        "max_instances": 1,
        "misfire_grace_time": 60,
        "coalesce": True,
    },
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.LOCAL_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    scheduler.add_job(
        generate_pending_certificates_with_timeout,
        "interval",
        seconds=settings.CERTIFICATE_JOB_INTERVAL_SECONDS,
        id="generate_pending_certificates",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Certificate issuance, verification and student lifecycle management API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

Path(settings.LOCAL_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=settings.LOCAL_STORAGE_PATH), name="files")

PREFIX = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=PREFIX)
app.include_router(colleges.router, prefix=PREFIX)
app.include_router(courses.router, prefix=PREFIX)
app.include_router(students.router, prefix=PREFIX)
app.include_router(enrollments.router, prefix=PREFIX)
app.include_router(certificates.router, prefix=PREFIX)
app.include_router(verify.router, prefix=PREFIX)
app.include_router(reports.router, prefix=PREFIX)
app.include_router(audit.router, prefix=PREFIX)


@app.get("/")
def root():
    return {"name": settings.APP_NAME, "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}
