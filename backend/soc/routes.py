from __future__ import annotations

from pathlib import Path
import inspect
import traceback
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from backend.soc import detections, report
from backend.soc.detections import SOCFinding  # important

router = APIRouter(prefix="/soc", tags=["soc"])

ROUTES_VERSION = "soc-2026-02-19-UPGRADED"

# Render writable
OUT_DIR = Path("/tmp/risklab")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LATEST_PDF = OUT_DIR / "soc_report.pdf"


def _looks_like_finding(obj: Any) -> bool:
    if isinstance(obj, SOCFinding):
        return True
    # report expects f.severity
    return hasattr(obj, "severity")


def _flatten_findings(x: Any) -> list[Any]:
    """Normalize ANY detector output into a flat list of findings objects."""
    out: list[Any] = []

    def walk(v: Any):
        if v is None:
            return

        if isinstance(v, dict):
            for key in ("findings", "alerts", "items", "events", "results"):
                if key in v:
                    walk(v[key])
                    return
            return

        if isinstance(v, (list, tuple)):
            for it in v:
                walk(it)
            return

        if _looks_like_finding(v):
            out.append(v)
            return

        return

    walk(x)
    return out


def _finding_to_dict(f: Any) -> dict:
    if is_dataclass(f):
        return asdict(f)
    if hasattr(f, "model_dump") and callable(getattr(f, "model_dump")):
        return f.model_dump()
    if hasattr(f, "dict") and callable(getattr(f, "dict")):
        return f.dict()
    return {"text": str(f)}


def _call_generate_soc_report(findings: list[Any], out_path: Path) -> Path:
# Defensive: flatten nested lists/tuples so report never crashes
flat = []
for item in findings or []:
    if isinstance(item, (list, tuple)):
        flat.extend(item)
    else:
        flat.append(item)
findings = flat

for f in findings:
    if isinstance(f, (list, tuple)):
        continue
    # drawString(... f.severity ...)

    """
    Calls report.generate_soc_report flexibly:
      - generate_soc_report(findings, out_path=Path)
      - generate_soc_report(findings, path=Path)
      - generate_soc_report(findings, output_path=Path)
      - generate_soc_report(findings) -> bytes or Path/str or writes default
    """
    fn = report.generate_soc_report
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())

    kwargs: dict[str, Any] = {}
    for p in params:
        if p.name in ("out_path", "path", "output_path", "pdf_path", "dest", "dst"):
            kwargs[p.name] = out_path
        if p.name in ("findings", "items", "alerts", "events"):
            kwargs[p.name] = findings

    args: list[Any] = []
    if not any(k in kwargs for k in ("findings", "items", "alerts", "events")):
        args.append(findings)

    res = fn(*args, **kwargs)

    if isinstance(res, (bytes, bytearray)):
        out_path.write_bytes(bytes(res))
        return out_path

    if isinstance(res, (str, Path)):
        return Path(res)

    if out_path.exists():
        return out_path

    raise RuntimeError("generate_soc_report did not write PDF to expected out_path.")


@router.post("/upload")
async def soc_upload(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")

        findings_raw = detections.detect_bruteforce(text)
        findings = _flatten_findings(findings_raw)

        pdf_path = _call_generate_soc_report(findings, LATEST_PDF)

        return {
            "ok": True,
            "routes_version": ROUTES_VERSION,
            "findings": len(findings),
            "findings_preview": [_finding_to_dict(f) for f in findings[:5]],
            "report_url": "/soc/report/latest",
            "report_path": str(pdf_path),
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "routes_version": ROUTES_VERSION,
                "error": str(e),
                "traceback": traceback.format_exc(),
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
