from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

import backend.soc.detections as detections
import backend.soc.report as report

router = APIRouter(prefix="/soc", tags=["soc"])

OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)
LATEST_PDF = OUT_DIR / "soc_report.pdf"


def _pick_callable(mod, candidates: list[str]):
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


# Try common names first (change nothing else in your project)
ANALYZE_FN = _pick_callable(detections, ["analyze_log", "analyze", "scan_log", "parse_log", "detect"])
PDF_FN = _pick_callable(report, ["render_soc_pdf", "render_pdf", "make_soc_pdf", "build_pdf", "create_pdf", "render"])


def _must(fn, what: str):
    if fn is None:
        raise RuntimeError(
            f"{what} function not found. Update backend/soc/routes.py to import the correct function "
            f"from {what.split()[0]}."
        )
    return fn


@router.post("/upload")
async def soc_upload(file: UploadFile = File(...)):
    analyze = _must(ANALYZE_FN, "detections")
    render_pdf = _must(PDF_FN, "report")

    raw = await file.read()
    text = raw.decode("utf-8", errors="ignore")

    result = analyze(text)
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="SOC analyzer must return a dict.")

    pdf_bytes = render_pdf(result)
    if isinstance(pdf_bytes, (bytes, bytearray)):
        LATEST_PDF.write_bytes(pdf_bytes)
    else:
        # If your report generator writes to disk instead of returning bytes, try to find the output
        if not LATEST_PDF.exists():
            raise HTTPException(
                status_code=500,
                detail="PDF generator did not return bytes and soc_report.pdf not found in outputs/."
            )

    return {**result, "report_url": "/soc/report/latest"}


@router.get("/report/latest")
def soc_report_latest():
    if not LATEST_PDF.exists():
        raise HTTPException(status_code=404, detail="No SOC report yet. POST /soc/upload first.")
    return FileResponse(str(LATEST_PDF), media_type="application/pdf", filename="soc_report.pdf")
