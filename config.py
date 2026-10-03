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


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    AUTO_CREATE_DB = True


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    AUTO_CREATE_DB = True


class ProductionConfig(BaseConfig):
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
