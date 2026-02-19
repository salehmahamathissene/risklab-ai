from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

# IMPORTANT: adjust these imports to your real function names
from .detections import analyze_log
from .report import render_soc_pdf

router = APIRouter(prefix="/soc", tags=["soc"])

OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)
LATEST_PDF = OUT_DIR / "soc_report.pdf"

@router.post("/upload")
async def soc_upload(file: UploadFile = File(...)):
    raw = await file.read()
    text = raw.decode("utf-8", errors="ignore")

    result = analyze_log(text)  # dict

    pdf_bytes = render_soc_pdf(result)  # bytes (recommended)
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise HTTPException(status_code=500, detail="render_soc_pdf must return PDF bytes.")

    LATEST_PDF.write_bytes(pdf_bytes)

    return {**result, "report_url": "/soc/report/latest"}

@router.get("/report/latest")
def soc_report_latest():
    if not LATEST_PDF.exists():
        raise HTTPException(status_code=404, detail="No SOC report yet. POST /soc/upload first.")
    return FileResponse(str(LATEST_PDF), media_type="application/pdf", filename="soc_report.pdf")
