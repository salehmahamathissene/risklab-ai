from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

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
    path = (CFD_OUT_DIR / name).resolve()

    # prevent path traversal
    if not str(path).startswith(str(CFD_OUT_DIR)):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found.")

    # Optional: hint browsers/CDNs to not cache
    # (querystring ts already busts cache, but this helps too)
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    return FileResponse(path, headers=headers)


@router.get("/cavity-fast/view", response_class=HTMLResponse)
def cavity_fast_view():
    """
    Runs cavity-fast and displays results in browser.
    """

    # Run simulation first (same code path as API)
    cavity_fast()

    ts = int(time.time())

    return HTMLResponse(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8"/>
            <title>CFD Cavity Fast</title>
            <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
            <meta http-equiv="Pragma" content="no-cache" />
            <meta http-equiv="Expires" content="0" />
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background: #111;
                    color: white;
                    text-align: center;
                    margin: 0;
                    padding: 24px;
                }}
                .wrap {{
                    max-width: 980px;
                    margin: 0 auto;
                }}
                img {{
                    width: 100%;
                    max-width: 820px;
                    border: 2px solid #444;
                    border-radius: 10px;
                    margin: 14px 0 30px 0;
                }}
                h1 {{ color: #00ffcc; margin-bottom: 8px; }}
                .meta {{ color: #bbb; margin-bottom: 18px; }}
                .btn {{
                    display: inline-block;
                    padding: 10px 14px;
                    border: 1px solid #444;
                    border-radius: 10px;
                    color: #fff;
                    text-decoration: none;
                    margin: 8px;
                }}
                .btn:hover {{ border-color: #00ffcc; }}
                code {{
                    background: #222;
                    padding: 2px 6px;
                    border-radius: 6px;
                    color: #ddd;
                }}
            </style>
        </head>
        <body>
            <div class="wrap">
                <h1>🚀 Lid-Driven Cavity Simulation</h1>
                <div class="meta">
                    Grid: <code>64×64</code> | Re: <code>1000</code> | dt: <code>0.005</code> | t_end: <code>0.5</code>
                    <br/>Generated at: <code>{ts}</code>
                </div>

                <div>
                    <a class="btn" href="/cfd/cavity-fast/view">🔁 Run again</a>
                    <a class="btn" href="/cfd/cavity-fast">📦 JSON output</a>
                </div>

                <h2>Velocity Magnitude</h2>
                <img src="/cfd/file/cavity_fast_speed.png?ts={ts}" />

                <h2>Vorticity</h2>
                <img src="/cfd/file/cavity_fast_vorticity.png?ts={ts}" />

            </div>
        </body>
        </html>
        """
    )
