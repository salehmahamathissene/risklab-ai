from __future__ import annotations

from pathlib import Path
import inspect
import traceback
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from backend.soc import detections, report

router = APIRouter(prefix="/soc", tags=["soc"])

ROUTES_VERSION = "soc-2026-02-19-v4"

# On Render, /tmp is writable.
OUT_DIR = Path("/tmp/risklab")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LATEST_PDF = OUT_DIR / "soc_report.pdf"


def _as_findings_list(x: Any) -> list[Any]:
    """Normalize detector output into a list."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)

    # If it's already an iterable of findings (but not a string/bytes), convert safely.
    # IMPORTANT: many finding objects are NOT iterable (dataclass), so we treat unknown objects as single.
    if isinstance(x, (str, bytes, bytearray)):
        return [x]

    # Common case: single SOCFinding dataclass/object
    return [x]


def _finding_to_dict(f: Any) -> dict:
    if is_dataclass(f):
        return asdict(f)
    if hasattr(f, "model_dump") and callable(getattr(f, "model_dump")):
        return f.model_dump()
    if hasattr(f, "dict") and callable(getattr(f, "dict")):
        return f.dict()
    # last resort
    return {"text": str(f)}


def _call_generate_soc_report(findings: list[Any], out_path: Path) -> Path:
    """
    Calls report.generate_soc_report in a flexible way, because signature may vary.

    Supported patterns:
      - generate_soc_report(findings, out_path=Path)
      - generate_soc_report(findings, path=Path)
      - generate_soc_report(findings, output_path=Path)
      - generate_soc_report(findings) -> bytes or Path/str or writes default
    """
    fn = report.generate_soc_report
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())

    kwargs: dict[str, Any] = {}

    # Named params
    for p in params:
        if p.name in ("out_path", "path", "output_path", "pdf_path", "dest", "dst"):
            kwargs[p.name] = out_path
        if p.name in ("findings", "items", "alerts", "events"):
            kwargs[p.name] = findings

    # Positional fallback: assume first positional is findings if not provided
    args: list[Any] = []
    if not any(k in kwargs for k in ("findings", "items", "alerts", "events")):
        args.append(findings)

    res = fn(*args, **kwargs)

    # Interpret return value
    if isinstance(res, (bytes, bytearray)):
        out_path.write_bytes(bytes(res))
        return out_path

    if isinstance(res, (str, Path)):
        p = Path(res)
        # if it returned a relative path, make it relative to CWD
        return p

    # If res is None, assume it wrote to out_path (or default path)
    if out_path.exists():
        return out_path

    raise RuntimeError(
        "generate_soc_report did not return bytes/path and did not write the expected out_path."
    )


@router.post("/upload")
async def soc_upload(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")

        # Your detections.py exports detect_bruteforce()
        findings_raw = detections.detect_bruteforce(text)
        findings = _as_findings_list(findings_raw)

        # Always create a PDF, even if empty findings
        pdf_path = _call_generate_soc_report(findings, LATEST_PDF)

        return {
            "ok": True,
            "routes_version": ROUTES_VERSION,
            "findings": len(findings),
            "findings_preview": [_finding_to_dict(f) for f in findings[:5]],
            "report_path": str(pdf_path),
            "report_url": "/soc/report/latest",
        }

    except Exception as e:
        tb = traceback.format_exc()
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "routes_version": ROUTES_VERSION,
                "error": str(e),
                "traceback": tb,
            },
        )


@router.get("/report/latest")
def soc_report_latest():
    if not LATEST_PDF.exists():
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "routes_version": ROUTES_VERSION,
                "error": "No SOC report generated yet. POST /soc/upload first.",
            },
        )

    return FileResponse(
        str(LATEST_PDF),
        media_type="application/pdf",
        filename="soc_report.pdf",
    )
