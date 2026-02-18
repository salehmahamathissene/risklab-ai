from __future__ import annotations

from pathlib import Path
import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/cfd", tags=["cfd"])

ROOT = Path(__file__).resolve().parents[2]  # risklab-ai/
NS_REPO = ROOT / "vendor" / "navier-stokes-lab"
RESULTS_DIR = NS_REPO / "results"

SPEED = RESULTS_DIR / "cavity_fast_speed.png"
VORT = RESULTS_DIR / "cavity_fast_vorticity.png"


def _run_cavity_fast() -> None:
    if not NS_REPO.exists():
        raise HTTPException(status_code=500, detail="Missing vendor/navier-stokes-lab (submodule not present).")

    cmd = ["python", "scripts/run_cavity_fast.py"]
    p = subprocess.run(cmd, cwd=str(NS_REPO), capture_output=True, text=True)

    if p.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"CFD run failed.\nSTDOUT:\n{p.stdout}\n\nSTDERR:\n{p.stderr}",
        )

    if not SPEED.exists() or not VORT.exists():
        raise HTTPException(status_code=500, detail="CFD run finished but PNG outputs not found.")


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
        raise HTTPException(status_code=404, detail="Unknown file name.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not generated yet. Call /cfd/cavity-fast first.")
    return FileResponse(str(path), media_type="image/png", filename=name)
