from contextlib import asynccontextmanager
from pathlib import Path

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.LOCAL_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    yield


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
