from contextlib import asynccontextmanager
from pathlib import Path
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
        generate_pending_certificates,
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
