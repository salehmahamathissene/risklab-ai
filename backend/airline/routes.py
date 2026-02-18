from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/airline", tags=["airline"])

OUT_DIR = Path("outputs/airline")
OUT_DIR.mkdir(parents=True, exist_ok=True)

STATS_JSON = OUT_DIR / "stats.json"
REPORT_PDF = OUT_DIR / "latest_report.pdf"

DEMO_CONFIG = Path("vendor/passenger-impact-engine/configs/demo_eu261_realistic.yml")


def _cli(*args: str) -> list[str]:
    # Always use module execution (works even without "pie" console script)
    return ["python", "-m", "passenger_impact_engine.cli", *args]


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Command failed:\nCMD: {' '.join(cmd)}\n\n"
                f"STDOUT:\n{e.stdout}\n\nSTDERR:\n{e.stderr}"
            ),
        )


@router.get("/run-demo")
def run_demo() -> Dict[str, Any]:
    if not DEMO_CONFIG.exists():
        raise HTTPException(status_code=500, detail=f"Demo config not found: {DEMO_CONFIG}")

    # 1) simulate -> writes outputs (ledger / mc etc.)
    _run(_cli("simulate", "--config", str(DEMO_CONFIG), "--out", str(OUT_DIR)))

    # 2) stats -> writes stats.json
    _run(_cli("stats", "--out", str(OUT_DIR)))

    if not STATS_JSON.exists():
        raise HTTPException(status_code=500, detail="PIE stats finished but outputs/airline/stats.json not found.")

    # 3) report -> writes PDF with stable name
    _run(_cli("report", "--out", str(OUT_DIR), "--filename", REPORT_PDF.name))

    stats = json.loads(STATS_JSON.read_text(encoding="utf-8"))
    stats["_links"] = {"stats": "/airline/stats/latest", "report": "/airline/report/latest"}
    return stats


@router.get("/stats/latest")
def stats_latest():
    if not STATS_JSON.exists():
        raise HTTPException(status_code=404, detail="No stats yet. Run /airline/run-demo first.")
    return json.loads(STATS_JSON.read_text(encoding="utf-8"))


@router.get("/report/latest")
def report_latest():
    if not REPORT_PDF.exists():
        raise HTTPException(status_code=404, detail="No report yet. Run /airline/run-demo first.")
    return FileResponse(str(REPORT_PDF), media_type="application/pdf", filename="eu261_report.pdf")
