from __future__ import annotations

from pathlib import Path
import inspect
import traceback
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from backend.soc import detections, report
from backend.soc.detections import SOCFinding

import asyncio

router = APIRouter(prefix="/soc", tags=["soc"])

ROUTES_VERSION = "soc-2026-02-19-STABLE-v2"

OUT_DIR = Path("/tmp/risklab")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LATEST_PDF = OUT_DIR / "soc_report.pdf"


def _looks_like_finding(obj: Any) -> bool:
    if isinstance(obj, SOCFinding):
        return True
    return hasattr(obj, "severity")


def _flatten_findings(x: Any) -> list[Any]:
    out: list[Any] = []

    def walk(v: Any) -> None:
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


def _call_generate_soc_report_sync(findings: list[Any], out_path: Path) -> Path:
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


async def _call_generate_soc_report(findings: list[Any], out_path: Path, timeout_s: float = 8.0) -> Path:
    """
    Run PDF generation in a thread with a hard timeout.
    If it takes too long, we abort and return an error.
    """
    return await asyncio.wait_for(asyncio.to_thread(_call_generate_soc_report_sync, findings, out_path), timeout=timeout_s)


@router.post("/upload")
async def soc_upload(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")

        # 1) Detection (fast)
        findings_raw = detections.detect_bruteforce(text)
        findings = _flatten_findings(findings_raw)

        # 2) PDF generation with timeout
        try:
            pdf_path = await _call_generate_soc_report(findings, LATEST_PDF, timeout_s=8.0)
            pdf_ok = True
            pdf_err = None
        except Exception as pdf_e:
            pdf_ok = False
            pdf_err = f"{type(pdf_e).__name__}: {pdf_e}"
            pdf_path = None

        return {
            "ok": True,
            "routes_version": ROUTES_VERSION,
            "findings": len(findings),
            "findings_preview": [_finding_to_dict(f) for f in findings[:5]],
            "pdf_ok": pdf_ok,
            "pdf_error": pdf_err,
            "report_url": "/soc/report/latest" if pdf_ok else None,
            "report_path": str(pdf_path) if pdf_path else None,
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
    return FileResponse(str(LATEST_PDF), media_type="application/pdf", filename="soc_report.pdf")
