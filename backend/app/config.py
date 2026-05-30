import os
from datetime import timedelta


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    JSON_SORT_KEYS = False
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    # Public-facing site origin used for sitemap.xml/robots.txt absolute URLs.
    # Override per env (e.g. SITE_URL=https://healthmatrix.com).
    SITE_URL = os.getenv("SITE_URL", "http://localhost:5173")
    RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "true").lower() == "true"
    RATELIMIT_STORAGE_URI = os.getenv("REDIS_URL", "memory://")
    RATELIMIT_DEFAULT = "10000 per hour"
    CACHE_TTL = timedelta(minutes=10)

    # Meilisearch — optional. When MEILI_URL + MEILI_MASTER_KEY are set, the
    # public listing/suggest endpoints route through Meilisearch for fuzzy/typo-
    # tolerant search. If unset (or unreachable at runtime) the routes fall back
    # to the SQL ILIKE path, so search keeps working even when the engine is down.
    MEILI_URL = os.getenv("MEILI_URL", "")
    MEILI_MASTER_KEY = os.getenv("MEILI_MASTER_KEY", "")
    MEILI_INDEX = os.getenv("MEILI_INDEX", "supplements")
    # Sync the index inline on admin writes when True (small catalog, low write
    # volume — keeps things simple). Set False if you'd rather rely on a
    # nightly reindex job.
    MEILI_AUTO_SYNC = os.getenv("MEILI_AUTO_SYNC", "true").lower() == "true"


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///healthmatrix.db")


class ProductionConfig(BaseConfig):
    DEBUG = False
    _raw_db_url = os.getenv("DATABASE_URL", "")
    if _raw_db_url.startswith("postgres://"):
        _raw_db_url = _raw_db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif _raw_db_url.startswith("postgresql://"):
        _raw_db_url = _raw_db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    SQLALCHEMY_DATABASE_URI = _raw_db_url


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    RATELIMIT_ENABLED = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    env = os.getenv("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
