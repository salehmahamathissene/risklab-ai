from fastapi import FastAPI
from fastapi.responses import Response

app = FastAPI(title="RiskLab AI", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True}

@app.head("/")
def head_root():
    return Response(status_code=200)
