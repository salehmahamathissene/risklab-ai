from fastapi import FastAPI
from fastapi.responses import Response

# Routers
from backend.cfd.routes import router as cfd_router
from backend.airline.routes import router as airline_router
from backend.soc.routes import router as soc_router

app = FastAPI(title="RiskLab AI", version="0.1.0")


@app.get("/")
def home():
    return {"status": "RiskLab AI online 🚀"}


# Render health check
@app.get("/health")
def health():
    return {"ok": True}


# Render sometimes sends HEAD /
@app.head("/")
def head_root():
    return Response(status_code=200)


# Include feature routers
app.include_router(airline_router, prefix="/airline", tags=["airline"])
app.include_router(soc_router, prefix="/soc", tags=["soc"])
app.include_router(cfd_router, prefix="/cfd", tags=["cfd"])
