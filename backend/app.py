from fastapi import FastAPI
from fastapi.responses import Response

from backend.airline.routes import router as airline_router
from backend.cfd.routes import router as cfd_router
from backend.soc.routes import router as soc_router

app = FastAPI(title="RiskLab AI", version="0.1.0")

@app.get("/")
def home():
    return {"status": "RiskLab AI online 🚀"}

@app.get("/health")
def health():
    return {"ok": True}

@app.head("/")
def head_root():
    return Response(status_code=200)

app.include_router(airline_router)
app.include_router(cfd_router)
app.include_router(soc_router)
