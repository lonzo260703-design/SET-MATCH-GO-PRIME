import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SECRET = "dev-insecure-change-me"


def _database_url():
    url = os.getenv("DATABASE_URL")
    if url and url.startswith("postgres://"):  # Render entrega este formato
        url = url.replace("postgres://", "postgresql://", 1)
    return url or "sqlite:///setmatchgo.db"


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET)
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    AUTO_CREATE_DB = False
    # En producción con varios workers usa Redis: LIMITER_STORAGE_URI=redis://...
    RATELIMIT_STORAGE_URI = os.getenv("LIMITER_STORAGE_URI", "memory://")

    # CONFIGURACIÓN SMTP (FLASK-MAIL)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    AUTO_CREATE_DB = True


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    AUTO_CREATE_DB = True


class ProductionConfig(BaseConfig):
    PROXY_FIX = True  # Render está detrás de un proxy: respeta X-Forwarded-For
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}