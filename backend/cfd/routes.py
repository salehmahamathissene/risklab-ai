from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/cfd", tags=["cfd"])

# Render-safe writable dir
OUT_DIR = Path("/tmp/risklab_cfd")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SPEED = OUT_DIR / "cavity_fast_speed.png"
VORT  = OUT_DIR / "cavity_fast_vorticity.png"


def _run_cmd(cmd: list[str], timeout_s: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)


def _run_cavity_fast() -> None:
    # Always use the current interpreter on Render
    cmd = [
        sys.executable,
        "-m",
        "navier_stokes_lab.scripts.run_cavity_fast",
        "--out",
        str(OUT_DIR),
        "--nx",
        "64",
        "--ny",
        "64",
        "--steps",
        "200",
        "--dt",
        "0.005",
    ]

    p = _run_cmd(cmd, timeout_s=120)

    if p.returncode != 0:
        raise HTTPException(
            500,
            "CFD run failed.\n"
            f"CMD: {' '.join(cmd)}\n\n"
            f"STDOUT:\n{p.stdout}\n\n"
            f"STDERR:\n{p.stderr}\n"
        )

    if not SPEED.exists() or not VORT.exists():
        raise HTTPException(500, f"CFD run finished but expected outputs not found in {OUT_DIR}")


@router.get("/cavity-fast")
def cavity_fast():
    _run_cavity_fast()
    return {
        "ok": True,
        "outputs": {
            "speed_png": "/cfd/file/cavity_fast_speed.png",
            "vorticity_png": "/cfd/file/cavity_fast_vorticity.png",
        },
    }


@router.get("/file/{name}")
def get_file(name: str):
    allowed = {
        "cavity_fast_speed.png": SPEED,
        "cavity_fast_vorticity.png": VORT,
    }
    path = allowed.get(name)
    if path is None:
        raise HTTPException(404, "Unknown file name.")
    if not path.exists():
        raise HTTPException(404, "File not generated yet. Call /cfd/cavity-fast first.")
    return FileResponse(str(path), media_type="image/png", filename=name)
