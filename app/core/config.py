"""
Central application configuration.
All values are read from environment variables (see .env.example).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # General
    APP_NAME: str = "PixelWind Certificate Engine"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"

    # Security / JWT
    SECRET_KEY: str = "change-this-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://pixelwind:pixelwind@localhost:5432/pixelwind"

    # CORS
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # Storage
    STORAGE_BACKEND: str = "local"  # local | s3 | r2
    LOCAL_STORAGE_PATH: str = "./storage"
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""
    S3_PUBLIC_URL: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION: str = "auto"

    # Verification
    VERIFICATION_BASE_URL: str = "https://verify.pixelwind.in"
    ISSUER_NAME: str = "Pixelwind Technologies"
    ISSUER_BRANCH: str = ""

    # Email / SMTP
    EMAIL_ENABLED: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Pixelwind"

    # Certificate job
    CERTIFICATE_JOB_INTERVAL_SECONDS: int = 60

    # Initial super admin (used by seed script)
    FIRST_SUPER_ADMIN_EMAIL: str = "admin@pixelwind.in"
    FIRST_SUPER_ADMIN_PASSWORD: str = "ChangeMe123!"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
