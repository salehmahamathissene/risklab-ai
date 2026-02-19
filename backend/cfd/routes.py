from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
import time


@router.get("/cavity-fast/view", response_class=HTMLResponse)
def cavity_fast_view():
    """
    Runs cavity-fast and displays results in browser.
    """

    # Run simulation first
    cavity_fast()

    ts = int(time.time())

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>CFD Cavity Fast</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #111;
                color: white;
                text-align: center;
            }}
            img {{
                max-width: 600px;
                border: 2px solid #444;
                margin: 20px;
            }}
            h1 {{
                color: #00ffcc;
            }}
        </style>
    </head>
    <body>
        <h1>🚀 Lid-Driven Cavity Simulation</h1>
        <p>Grid: 64 × 64 | Re = 1000 | t_end = 0.5</p>

        <h2>Velocity Magnitude</h2>
        <img src="/cfd/file/cavity_fast_speed.png?ts={ts}" />

        <h2>Vorticity</h2>
        <img src="/cfd/file/cavity_fast_vorticity.png?ts={ts}" />

        <p>Auto-generated at {ts}</p>
    </body>
    </html>
    """

router = APIRouter(prefix="/cfd", tags=["cfd"])

# One shared output directory for BOTH:
# - the runner writes images here
# - /cfd/file/{name} serves files from here
CFD_OUT_DIR = Path(os.environ.get("CFD_OUT_DIR", "/tmp/cfd")).resolve()
CFD_OUT_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/cavity-fast")
def cavity_fast():
    """
    Run a fast lid-driven cavity simulation and write:
      - cavity_fast_speed.png
      - cavity_fast_vorticity.png
    into CFD_OUT_DIR
    """

    cmd = [
        sys.executable,
        "-m",
        "navier_stokes_lab.scripts.run_cavity_fast",
        "--out",
        str(CFD_OUT_DIR),
        "--n",
        "64",
        "--re",
        "1000",
        "--dt",
        "0.005",
        "--t-end",
        "0.5",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "CFD run failed.\n"
                f"CMD: {' '.join(cmd)}\n\n"
                f"STDOUT:\n{e.stdout}\n\n"
                f"STDERR:\n{e.stderr}\n"
            ),
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(
            status_code=504,
            detail=f"CFD run timed out after {e.timeout}s.",
        )

    speed = CFD_OUT_DIR / "cavity_fast_speed.png"
    vort = CFD_OUT_DIR / "cavity_fast_vorticity.png"

    if not speed.exists() or not vort.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "CFD run finished but expected files were not found.\n"
                f"Expected:\n- {speed}\n- {vort}\n\n"
                f"STDOUT:\n{proc.stdout}\n\n"
                f"STDERR:\n{proc.stderr}\n"
            ),
        )

    return {
        "ok": True,
        "out_dir": str(CFD_OUT_DIR),
        "files": [
            "cavity_fast_speed.png",
            "cavity_fast_vorticity.png",
        ],
        "stdout_tail": proc.stdout.splitlines()[-20:],
    }


@router.get("/file/{name}")
def get_file(name: str):
    """
    Serve any file from CFD_OUT_DIR.
    """
    from fastapi.responses import FileResponse

    path = (CFD_OUT_DIR / name).resolve()
    if not str(path).startswith(str(CFD_OUT_DIR)):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found.")

    return FileResponse(path)
