# backend/core/config.py
from __future__ import annotations

import os
from pydantic import BaseModel


def _fix_pg(url: str) -> str:
    # Render sometimes gives postgres:// which SQLAlchemy expects as postgresql://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Settings(BaseModel):
    database_url: str = _fix_pg(os.getenv("DATABASE_URL", "sqlite:////tmp/risklab_dev.db"))
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    stripe_secret_key: str | None = os.getenv("STRIPE_SECRET_KEY")
    stripe_webhook_secret: str | None = os.getenv("STRIPE_WEBHOOK_SECRET")
    stripe_price_id: str | None = os.getenv("STRIPE_PRICE_ID")

    # Pro token signing (cookie)
    pro_signing_key: str = os.getenv("PRO_SIGNING_KEY", "")
    # optional fallback header key
    pro_static_key: str = os.getenv("PRO_STATIC_KEY", "")

    cors_origins: str = os.getenv("CORS_ORIGINS", "")


settings = Settings()
