# backend/soc/routes.py
from __future__ import annotations

from pathlib import Path
import inspect

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from . import detections, report

router = APIRouter(prefix="/soc", tags=["soc"])

OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)
LATEST_PDF = OUT_DIR / "soc_report.pdf"


def _call_flex(fn, *args, **kwargs):
    """
    Call fn with whatever args it accepts (helps when signatures differ).
    """
    sig = inspect.signature(fn)
    bound = {}
    # Try kwargs first
    for k, v in kwargs.items():
        if k in sig.parameters:
            bound[k] = v
    # Then positional as far as allowed
    params = list(sig.parameters.values())
    max_pos = sum(
        1 for p in params
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    )
    return fn(*args[:max_pos], **bound)


@router.post("/upload")
async def soc_upload(file: UploadFile = File(...)):
    raw = await file.read()
    text = raw.decode("utf-8", errors="ignore")

    # 1) Detect bruteforce (SOCFinding)
    if not hasattr(detections, "detect_bruteforce"):
        raise HTTPException(500, "detect_bruteforce() not found in backend/soc/detections.py")

    finding = _call_flex(detections.detect_bruteforce, text, text.splitlines())

    # 2) Generate PDF
    if not hasattr(report, "generate_soc_report"):
        raise HTTPException(500, "generate_soc_report() not found in backend/soc/report.py")

    # Some implementations return bytes, some write directly. We support both.
    out = _call_flex(report.generate_soc_report, finding, LATEST_PDF, out_path=LATEST_PDF)

    if isinstance(out, (bytes, bytearray)):
        LATEST_PDF.write_bytes(out)

    if not LATEST_PDF.exists():
        raise HTTPException(500, "SOC PDF was not created.")

    # Return the same JSON style you already used
    return {
        "severity": getattr(finding, "severity", None) or "UNKNOWN",
        "summary": getattr(finding, "summary", None) or "SOC report generated.",
        "report_url": "/soc/report/latest",
    }


@router.get("/report/latest")
def soc_report_latest():
    if not LATEST_PDF.exists():
        raise HTTPException(404, "No SOC report yet. POST /soc/upload first.")
    return FileResponse(str(LATEST_PDF), media_type="application/pdf", filename="soc_report.pdf")
