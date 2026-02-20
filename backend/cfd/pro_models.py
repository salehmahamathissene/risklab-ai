# backend/cfd/pro_models.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.core.config import settings


class Base(DeclarativeBase):
    pass


class ProCustomer(Base):
    __tablename__ = "pro_customers"

    customer_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subscription_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CFDJob(Base):
    __tablename__ = "cfd_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued|running|done|failed
    pro: Mapped[bool] = mapped_column(Boolean, default=False)

    params_json: Mapped[str] = mapped_column(Text, default="{}")
    output_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


_ENGINE = None
SessionLocal = None


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
        )
    return _ENGINE


def init_db() -> None:
    global SessionLocal
    eng = _get_engine()
    SessionLocal = sessionmaker(bind=eng, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=eng)


def db_ping() -> bool:
    try:
        eng = _get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db():
    # FastAPI dependency generator
    if SessionLocal is None:
        init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
