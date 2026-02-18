from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse

from backend.soc.detections import detect_bruteforce
from backend.soc.report import generate_soc_report
from backend.airline.routes import router as airline_router  # ✅ ADD THIS

app = FastAPI(title="RiskLab AI")

LATEST_REPORT = Path("outputs/reports/soc_report.pdf")

app.include_router(airline_router)  # ✅ ADD THIS (after app = FastAPI)


@app.get("/")
def home():
    return {"status": "RiskLab AI online 🚀"}


@app.post("/soc/upload")
async def soc_upload(file: UploadFile):
    content = await file.read()
    lines = content.decode("utf-8", errors="replace").splitlines()

    finding = detect_bruteforce(lines)
    generate_soc_report(finding, str(LATEST_REPORT))

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
    if not LATEST_REPORT.exists():
        return {"error": "No report generated yet. Upload a log first."}
    return FileResponse(
        str(LATEST_REPORT),
        media_type="application/pdf",
        filename="soc_report.pdf",
    )
