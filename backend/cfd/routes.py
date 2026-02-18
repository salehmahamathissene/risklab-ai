from __future__ import annotations

from pathlib import Path
import importlib
import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/cfd", tags=["cfd"])

ROOT = Path(__file__).resolve().parents[2]  # repo root
OUTDIR = ROOT / "outputs" / "cfd"
OUTDIR.mkdir(parents=True, exist_ok=True)

SPEED = OUTDIR / "cavity_fast_speed.png"
VORT = OUTDIR / "cavity_fast_vorticity.png"


def _try_run_from_package() -> None:
    """
    Preferred: run CFD by importing navier_stokes_lab.
    This avoids vendor submodules and works on Render.
    """
    try:
        # You will create this module/function in navier-stokes-lab repo
        mod = importlib.import_module("navier_stokes_lab.scripts.run_cavity_fast")
    except Exception:
        raise HTTPException(
            status_code=500,
            detail=(
                "CFD package not importable yet.\n"
                "Expected module: navier_stokes_lab.scripts.run_cavity_fast\n\n"
                "Fix: update navier-stokes-lab packaging to include src/navier_stokes_lab/...\n"
                f"Import error:\n{traceback.format_exc()}"
            ),
        )

    # Convention: module provides main(outdir=Path)
    if not hasattr(mod, "main"):
        raise HTTPException(
            status_code=500,
            detail="navier_stokes_lab.scripts.run_cavity_fast has no main(outdir=Path) function.",
        )

    try:
        mod.main(outdir=OUTDIR)  # type: ignore[attr-defined]
    except TypeError:
        # fallback if function signature is main() and writes internally
        mod.main()  # type: ignore[attr-defined]
    except Exception:
        raise HTTPException(
            status_code=500,
            detail=f"CFD run failed inside navier_stokes_lab.\n{traceback.format_exc()}",
        )

    if not SPEED.exists() or not VORT.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "CFD run completed but PNG outputs not found.\n"
                f"Expected:\n- {SPEED}\n- {VORT}\n"
                "Ensure run_cavity_fast writes these filenames into the outdir."
            ),
        )


@router.get("/cavity-fast")
def cavity_fast():
    _try_run_from_package()
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
