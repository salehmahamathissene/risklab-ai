# backend/worker.py
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis
from rq import Queue

from backend.core.config import settings
from backend.cfd.pro_models import init_db, SessionLocal, CFDJob


CFD_OUT_DIR = Path(os.environ.get("CFD_OUT_DIR", "/tmp/cfd")).resolve()
CFD_OUT_DIR.mkdir(parents=True, exist_ok=True)


def _run_cavity_fast(job_dir: Path, n: int, re: float, dt: float, t_end: float) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "navier_stokes_lab.scripts.run_cavity_fast",
        "--out",
        str(job_dir),
        "--n",
        str(n),
        "--re",
        str(re),
        "--dt",
        str(dt),
        "--t-end",
        str(t_end),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600)


def run_cfd_job(job_id: str) -> None:
    """
    RQ task:
    - marks job running
    - runs CFD
    - marks done/failed
    """
    init_db()
    assert SessionLocal is not None

    db = SessionLocal()
    try:
        job = db.get(CFDJob, job_id)
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        db.commit()

        params = json.loads(job.params_json or "{}")
        n = int(params.get("n", 64))
        re = float(params.get("re", 1000.0))
        dt = float(params.get("dt", 0.005))
        t_end = float(params.get("t_end", 0.5))

        job_dir = (CFD_OUT_DIR / job_id).resolve()
        job_dir.mkdir(parents=True, exist_ok=True)

        _run_cavity_fast(job_dir, n=n, re=re, dt=dt, t_end=t_end)

        # sanity check outputs
        speed = job_dir / "cavity_fast_speed.png"
        vort = job_dir / "cavity_fast_vorticity.png"
        if not speed.exists() or not vort.exists():
            raise RuntimeError("CFD finished but expected PNG outputs missing.")

        job.status = "done"
        job.output_dir = str(job_dir)
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        if "job" in locals() and job:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()


def make_queue() -> Queue:
    r = redis.Redis.from_url(settings.redis_url)
    return Queue("risklab", connection=r)
