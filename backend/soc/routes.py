from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse

from .detections import analyze_log  # adjust if your function name differs
from .report import render_soc_pdf   # adjust if your function name differs

router = APIRouter(prefix="/soc", tags=["soc"])

OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)
LATEST_PDF = OUT_DIR / "soc_report.pdf"

@router.post("/upload")
async def soc_upload(file: UploadFile = File(...)):
    raw = await file.read()
    text = raw.decode("utf-8", errors="ignore")

    result = analyze_log(text)  # returns dict summary

    pdf_bytes = render_soc_pdf(result)  # returns bytes OR writes file (depends on your implementation)

    # If render_soc_pdf returns bytes:
    if isinstance(pdf_bytes, (bytes, bytearray)):
        LATEST_PDF.write_bytes(pdf_bytes)

    return {**result, "report_url": "/soc/report/latest"}

@router.get("/report/latest")
def soc_report_latest():
    if not LATEST_PDF.exists():
        return {"detail": "No SOC report yet. POST /soc/upload first."}
    return FileResponse(str(LATEST_PDF), media_type="application/pdf", filename="soc_report.pdf")
