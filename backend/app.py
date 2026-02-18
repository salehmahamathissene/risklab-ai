from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse

from backend.soc.detections import detect_bruteforce
from backend.soc.report import generate_soc_report

from backend.airline.routes import router as airline_router
from backend.cfd.routes import router as cfd_router
from fastapi import Response

@app.get("/health")
def health():
    return {"ok": True}

# Optional: Render sometimes sends HEAD /
@app.head("/")
def home_head():
    return Response(status_code=200)

app = FastAPI(title="RiskLab AI")

SOC_REPORT = Path("outputs/reports/soc_report.pdf")


@app.get("/")
def home():
    return {"status": "RiskLab AI online 🚀"}


# ---------- SOC ----------
@app.post("/soc/upload")
async def soc_upload(file: UploadFile):
    content = await file.read()
    lines = content.decode("utf-8", errors="replace").splitlines()

    finding = detect_bruteforce(lines)
    SOC_REPORT.parent.mkdir(parents=True, exist_ok=True)
    generate_soc_report(finding, str(SOC_REPORT))

    return {
        "severity": finding.severity,
        "summary": finding.summary,
        "total_failed": finding.total_failed,
        "unique_ips": finding.unique_ips,
        "top_ips": finding.top_ips,
        "top_users": finding.top_users,
        "report_url": "/soc/report/latest",
    }


@app.get("/soc/report/latest")
def soc_report_latest():
    if not SOC_REPORT.exists():
        raise HTTPException(status_code=404, detail="No SOC report yet. Upload a log first.")
    return FileResponse(str(SOC_REPORT), media_type="application/pdf", filename="soc_report.pdf")

@app.get("/health")
def health():
    return {"ok": True}


# ---------- Routers ----------
app.include_router(airline_router)
app.include_router(cfd_router)
