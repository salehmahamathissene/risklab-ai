from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.airline.report import generate_airline_report

router = APIRouter(prefix="/airline", tags=["airline"])

OUT_DIR = Path("outputs/airline")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LATEST_STATS = OUT_DIR / "stats.json"
LATEST_REPORT = OUT_DIR / "airline_report.pdf"

# Your PIE demo config inside the submodule:
DEMO_CONFIG = Path("vendor/passenger-impact-engine/configs/demo_eu261_realistic.yml")


def _run_pie_cli(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        raise HTTPException(status_code=500, detail=f"PIE config not found: {config_path}")

    # run PIE and write outputs into outputs/airline/
    cmd = ["pie", "run-all", "--config", str(config_path), "--out", str(OUT_DIR)]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="PIE CLI not found. Ensure you installed PIE in the SAME venv: pip install -e vendor/passenger-impact-engine",
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"PIE CLI failed.\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}",
        )

    if not LATEST_STATS.exists():
        raise HTTPException(status_code=500, detail="PIE ran but outputs/airline/stats.json not found.")

    return json.loads(LATEST_STATS.read_text(encoding="utf-8"))


@router.get("/run-demo")
def run_demo() -> Dict[str, Any]:
    stats = _run_pie_cli(DEMO_CONFIG)
    generate_airline_report(stats, str(LATEST_REPORT))
    return stats


@router.get("/stats/latest")
def stats_latest():
    if not LATEST_STATS.exists():
        raise HTTPException(status_code=404, detail="No airline stats yet. Call /airline/run-demo first.")
    return json.loads(LATEST_STATS.read_text(encoding="utf-8"))


@router.get("/report/latest")
def report_latest():
    if not LATEST_REPORT.exists():
        raise HTTPException(status_code=404, detail="No airline report yet. Call /airline/run-demo first.")
    return FileResponse(str(LATEST_REPORT), media_type="application/pdf", filename="airline_report.pdf")
