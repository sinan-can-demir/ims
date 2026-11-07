import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def normalize_database_url(url: str) -> str:
    """Pin bare Postgres URLs to the psycopg2 driver this project installs.

    SQLAlchemy 2.0 treats ``postgresql://`` as psycopg2, but 2.1 treats it as
    psycopg v3 (not installed here). Rewriting the bare scheme keeps every
    existing .env / compose file working on both versions. URLs that already
    name a driver (``postgresql+psycopg://``, ``postgresql+asyncpg://``, ...)
    and non-Postgres URLs (sqlite) are left untouched. The legacy ``postgres://``
    alias is accepted too.
    """
    for bare in ("postgresql://", "postgres://"):
        if url.startswith(bare):
            return "postgresql+psycopg2://" + url[len(bare) :]
    return url


DATABASE_URL = normalize_database_url(
    os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ims")
)

engine = create_engine(
    DATABASE_URL,
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    pool_pre_ping=True,  # drop and replace stale connections (important for cloud RDS)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
