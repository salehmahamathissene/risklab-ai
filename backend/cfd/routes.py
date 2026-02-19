from pathlib import Path
import subprocess
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/cfd", tags=["cfd"])

OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)

SPEED = OUT_DIR / "cavity_fast_speed.png"
VORT  = OUT_DIR / "cavity_fast_vorticity.png"

def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)

def _run_cavity_fast() -> None:
    # Try a few likely module entrypoints
    candidates = [
        ["python", "-m", "navier_stokes_lab.scripts.run_cavity_fast", "--out", str(OUT_DIR)],
        ["python", "-m", "navier_stokes_lab.run_cavity_fast", "--out", str(OUT_DIR)],
        ["python", "-m", "navier_stokes_lab.cavity_fast", "--out", str(OUT_DIR)],
    ]

    last = None
    for cmd in candidates:
        p = _run_cmd(cmd)
        last = p
        if p.returncode == 0:
            break

    if last is None or last.returncode != 0:
        raise HTTPException(
            500,
            "CFD run failed. Your navier-stokes-lab package needs a runnable module.\n"
            f"STDOUT:\n{(last.stdout if last else '')}\n\nSTDERR:\n{(last.stderr if last else '')}"
        )

    if not SPEED.exists() or not VORT.exists():
        raise HTTPException(500, "CFD run completed but PNG outputs not found in outputs/.")

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
