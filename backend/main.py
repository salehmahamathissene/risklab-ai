# backend/main.py
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import Response

from backend.airline.routes import router as airline_router
from backend.cfd.routes import router as cfd_router
from backend.soc.routes import router as soc_router

from backend.cfd.pro_models import init_db, db_ping  # we’ll add db_ping below


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    yield
    # Shutdown (optional): close pools if you add them later


def create_app() -> FastAPI:
    app = FastAPI(title="RiskLab AI", version="0.1.0", lifespan=lifespan)

    @app.get("/")
    def home():
        return {"status": "RiskLab AI online 🚀"}

    @app.get("/health")
    def health():
        # “Production health” should verify dependencies
        ok_db = db_ping()
        return {"ok": True, "db": ok_db}

    @app.head("/")
    def head_root():
        return Response(status_code=200)

    app.include_router(airline_router)
    app.include_router(cfd_router)
    app.include_router(soc_router)
    return app


app = create_app()
