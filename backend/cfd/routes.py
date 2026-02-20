from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

# =========================
# Router (DEFINE FIRST!)
# =========================
router = APIRouter(prefix="/cfd", tags=["cfd"])

# Shared output root
CFD_OUT_DIR = Path(os.environ.get("CFD_OUT_DIR", "/tmp/cfd")).resolve()
CFD_OUT_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Pro auth (NO DB NEEDED)
# =========================
# Set these in Render environment:
#   PRO_SIGNING_KEY = long random string
# Optional:
#   PRO_STATIC_KEY = some key you can give manually to paying users (fallback)
PRO_SIGNING_KEY = os.environ.get("PRO_SIGNING_KEY", "")
PRO_STATIC_KEY = os.environ.get("PRO_STATIC_KEY", "")

COOKIE_NAME = "risklab_pro"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_pro_token(ttl_days: int = 30) -> str:
    if not PRO_SIGNING_KEY:
        # Token system disabled until you set PRO_SIGNING_KEY
        return ""
    now = int(time.time())
    exp = now + ttl_days * 24 * 3600
    payload = {"exp": exp, "iat": now}
    payload_b = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_s = _b64url(payload_b)

    sig = hmac.new(PRO_SIGNING_KEY.encode("utf-8"), payload_s.encode("utf-8"), hashlib.sha256).digest()
    sig_s = _b64url(sig)
    return f"{payload_s}.{sig_s}"


def verify_pro_token(token: str) -> bool:
    if not token or not PRO_SIGNING_KEY:
        return False
    try:
        payload_s, sig_s = token.split(".", 1)
        expected = hmac.new(PRO_SIGNING_KEY.encode("utf-8"), payload_s.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), sig_s):
            return False
        payload = json.loads(_b64url_decode(payload_s).decode("utf-8"))
        exp = int(payload.get("exp", 0))
        return int(time.time()) < exp
    except Exception:
        return False


def is_pro(request: Request) -> bool:
    # 1) cookie token
    tok = request.cookies.get(COOKIE_NAME, "")
    if verify_pro_token(tok):
        return True

    # 2) header key (for API customers / internal testing)
    hdr = request.headers.get("X-Pro-Key", "")
    if PRO_STATIC_KEY and hdr and hmac.compare_digest(hdr, PRO_STATIC_KEY):
        return True

    return False


# =========================
# Limits (FREE vs PRO)
# =========================
FREE_LIMITS = {
    "n_max": 64,
    "t_end_max": 0.5,
}
PRO_LIMITS = {
    "n_max": 256,
    "t_end_max": 10.0,
}


def enforce_limits(request: Request, n: int, t_end: float) -> None:
    limits = PRO_LIMITS if is_pro(request) else FREE_LIMITS
    if n > limits["n_max"] or t_end > limits["t_end_max"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "upgrade_required",
                "message": "Upgrade to Pro to run higher resolution or longer simulations.",
                "free_limits": FREE_LIMITS,
                "requested": {"n": n, "t_end": t_end},
            },
        )


# =========================
# Helpers
# =========================
def make_job_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"cfd_{ts}_{uuid.uuid4().hex[:6]}"


def run_cavity_fast(job_dir: Path, n: int, re: float, dt: float, t_end: float) -> subprocess.CompletedProcess[str]:
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

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )


def tail_lines(s: str, k: int = 30) -> list[str]:
    lines = (s or "").splitlines()
    return lines[-k:]


# =========================
# API: run -> JSON
# =========================
@router.get("/cavity-fast")
def cavity_fast(
    request: Request,
    n: int = 64,
    re: float = 1000.0,
    dt: float = 0.005,
    t_end: float = 0.5,
) -> Dict[str, Any]:
    """
    Run lid-driven cavity and write images into /tmp/cfd/<job_id>/...
    Returns JSON with view link + file links.
    """
    enforce_limits(request, n=n, t_end=t_end)

    job_id = make_job_id()
    job_dir = (CFD_OUT_DIR / job_id).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        proc = run_cavity_fast(job_dir, n=n, re=re, dt=dt, t_end=t_end)
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "CFD run failed.\n"
                f"STDOUT:\n{e.stdout}\n\n"
                f"STDERR:\n{e.stderr}\n"
            ),
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(status_code=504, detail=f"CFD run timed out after {e.timeout}s.")

    speed = job_dir / "cavity_fast_speed.png"
    vort = job_dir / "cavity_fast_vorticity.png"

    if not speed.exists() or not vort.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "CFD finished but output files missing.\n"
                f"Expected:\n- {speed}\n- {vort}\n\n"
                f"STDOUT:\n{proc.stdout}\n\n"
                f"STDERR:\n{proc.stderr}\n"
            ),
        )

    return {
        "ok": True,
        "pro": is_pro(request),
        "job_id": job_id,
        "params": {"n": n, "re": re, "dt": dt, "t_end": t_end},
        "view_url": f"/cfd/jobs/{job_id}/view",
        "report_url": f"/cfd/jobs/{job_id}/report.pdf",
        "files": {
            "speed": f"/cfd/jobs/{job_id}/file/cavity_fast_speed.png",
            "vorticity": f"/cfd/jobs/{job_id}/file/cavity_fast_vorticity.png",
        },
        "stdout_tail": tail_lines(proc.stdout, 20),
    }


# =========================
# UI: landing page
# =========================
@router.get("/cavity-fast/view", response_class=HTMLResponse)
def cavity_fast_view(request: Request) -> str:
    """
    Browser UI with form + run button (no JS frameworks).
    """
    pro = is_pro(request)
    limits = PRO_LIMITS if pro else FREE_LIMITS

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>RiskLab AI — CFD (Cavity)</title>
  <style>
    body {{ font-family: Arial, sans-serif; background:#0b0f14; color:#e8eef6; margin:0; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    .card {{ background:#101826; border:1px solid #1f2a3a; border-radius:14px; padding:18px; margin:14px 0; }}
    h1 {{ margin:0 0 10px 0; }}
    label {{ display:block; margin:10px 0 6px; color:#cfe2ff; }}
    input {{ width: 100%; padding:10px; border-radius:10px; border:1px solid #25344a; background:#0b1220; color:#e8eef6; }}
    button {{ padding:10px 14px; border-radius:10px; border:0; background:#00d4ff; cursor:pointer; font-weight:700; }}
    button.secondary {{ background:#243247; color:#e8eef6; }}
    .row {{ display:grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .small {{ color:#9fb4cc; font-size: 13px; }}
    .badge {{ display:inline-block; padding:4px 10px; border-radius:999px; font-weight:700; }}
    .free {{ background:#22314a; }}
    .pro {{ background:#1d4ed8; }}
    .warn {{ background:#2a1d1d; border:1px solid #5b2a2a; padding:12px; border-radius:12px; }}
    a {{ color:#7dd3fc; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>🚀 Lid-Driven Cavity Simulation</h1>
    <div class="small">RiskLab AI — Cloud CFD demo (Navier–Stokes). Your plan:
      <span class="badge {'pro' if pro else 'free'}">{'PRO' if pro else 'FREE'}</span>
    </div>

    <div class="card">
      <h3>Run simulation</h3>
      <div class="small">Free limits: n≤{FREE_LIMITS['n_max']}, t_end≤{FREE_LIMITS['t_end_max']} | Pro limits: n≤{PRO_LIMITS['n_max']}, t_end≤{PRO_LIMITS['t_end_max']}</div>

      <form method="get" action="/cfd/cavity-fast">
        <div class="row">
          <div>
            <label>Grid n</label>
            <input name="n" type="number" min="16" max="{limits['n_max']}" value="64" />
          </div>
          <div>
            <label>Re</label>
            <input name="re" type="number" step="1" value="1000" />
          </div>
        </div>
        <div class="row">
          <div>
            <label>dt</label>
            <input name="dt" type="number" step="0.000001" value="0.005" />
          </div>
          <div>
            <label>t_end</label>
            <input name="t_end" type="number" step="0.01" max="{limits['t_end_max']}" value="0.5" />
          </div>
        </div>

        <div style="margin-top:12px; display:flex; gap:10px; align-items:center;">
          <button type="submit">▶ Run (JSON)</button>
          <a class="small" href="/cfd/cavity-fast">Use defaults</a>
          <a class="small" href="/cfd/pro">Pro status</a>
          <a class="small" href="/cfd/billing">Upgrade</a>
        </div>
      </form>

      <div class="warn" style="margin-top:14px;">
        <b>Tip:</b> After you run, open the <b>view_url</b> from the JSON to see images + download PDF.
      </div>
    </div>

    <div class="card">
      <h3>What Pro gives you</h3>
      <ul>
        <li>Higher grid resolution (up to n={PRO_LIMITS['n_max']})</li>
        <li>Longer simulation (up to t_end={PRO_LIMITS['t_end_max']})</li>
        <li>PDF report download per run</li>
        <li>No caching issues (fresh results per Job ID)</li>
      </ul>
    </div>
  </div>
</body>
</html>
"""


# =========================
# Pro status endpoint
# =========================
@router.get("/pro")
def pro_status(request: Request) -> Dict[str, Any]:
    return {
        "pro": is_pro(request),
        "free_limits": FREE_LIMITS,
        "pro_limits": PRO_LIMITS,
        "hint": "To enable Pro: set PRO_SIGNING_KEY and use /cfd/billing (Stripe) or X-Pro-Key header (PRO_STATIC_KEY).",
    }


# =========================
# Job view page
# =========================
@router.get("/jobs/{job_id}/view", response_class=HTMLResponse)
def job_view(job_id: str) -> str:
    job_dir = (CFD_OUT_DIR / job_id).resolve()
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")

    ts = int(time.time())
    speed = f"/cfd/jobs/{job_id}/file/cavity_fast_speed.png?ts={ts}"
    vort = f"/cfd/jobs/{job_id}/file/cavity_fast_vorticity.png?ts={ts}"
    report = f"/cfd/jobs/{job_id}/report.pdf?ts={ts}"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>CFD Job {job_id}</title>
  <style>
    body {{ font-family: Arial, sans-serif; background:#0b0f14; color:#e8eef6; margin:0; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    .card {{ background:#101826; border:1px solid #1f2a3a; border-radius:14px; padding:18px; margin:14px 0; }}
    img {{ max-width: 900px; width: 100%; border-radius:12px; border:1px solid #1f2a3a; }}
    a {{ color:#7dd3fc; }}
    button {{ padding:10px 14px; border-radius:10px; border:0; background:#00d4ff; cursor:pointer; font-weight:700; }}
    button.secondary {{ background:#243247; color:#e8eef6; }}
    .row {{ display:flex; gap:10px; flex-wrap:wrap; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>🚀 Lid-Driven Cavity Simulation</h1>
    <div class="card">
      <div><b>Job:</b> {job_id}</div>
      <div><b>Generated:</b> {datetime.now(timezone.utc).isoformat()}</div>

      <div class="row" style="margin-top:12px;">
        <a href="/cfd/cavity-fast/view"><button class="secondary">⬅ Back</button></a>
        <a href="/cfd/cavity-fast"><button class="secondary">📦 JSON output</button></a>
        <a href="{report}"><button>📄 Download PDF report</button></a>
      </div>
    </div>

    <div class="card">
      <h2>Velocity Magnitude</h2>
      <img src="{speed}" alt="speed" />
    </div>

    <div class="card">
      <h2>Vorticity</h2>
      <img src="{vort}" alt="vorticity" />
    </div>
  </div>
</body>
</html>
"""


# =========================
# Serve job files (NO CACHE)
# =========================
@router.get("/jobs/{job_id}/file/{name}")
def job_file(job_id: str, name: str):
    job_dir = (CFD_OUT_DIR / job_id).resolve()
    path = (job_dir / name).resolve()

    if not str(path).startswith(str(job_dir)):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found.")

    # Force browser to always fetch latest
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return FileResponse(path, headers=headers)


# =========================
# PDF report per job
# =========================
@router.get("/jobs/{job_id}/report.pdf")
def job_report(job_id: str):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    job_dir = (CFD_OUT_DIR / job_id).resolve()
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")

    speed = job_dir / "cavity_fast_speed.png"
    vort = job_dir / "cavity_fast_vorticity.png"
    if not speed.exists() or not vort.exists():
        raise HTTPException(status_code=404, detail="Job outputs missing (PNG not found).")

    out_pdf = job_dir / "report.pdf"

    c = canvas.Canvas(str(out_pdf), pagesize=letter)
    w, h = letter

    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, h - 1 * inch, "RiskLab AI — CFD Report (Lid-Driven Cavity)")

    c.setFont("Helvetica", 10)
    c.drawString(1 * inch, h - 1.25 * inch, f"Job ID: {job_id}")
    c.drawString(1 * inch, h - 1.40 * inch, f"Generated: {datetime.now(timezone.utc).isoformat()}")

    # Put images (scaled)
    y = h - 2.0 * inch
    img_w = 6.8 * inch
    img_h = 3.0 * inch

    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, y, "Velocity Magnitude")
    y -= 0.2 * inch
    c.drawImage(ImageReader(str(speed)), 1 * inch, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask="auto")

    y -= (img_h + 0.6 * inch)
    c.drawString(1 * inch, y, "Vorticity")
    y -= 0.2 * inch
    c.drawImage(ImageReader(str(vort)), 1 * inch, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask="auto")

    c.showPage()
    c.save()

    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "Content-Disposition": f'attachment; filename="cfd_report_{job_id}.pdf"',
    }
    return FileResponse(out_pdf, media_type="application/pdf", headers=headers)


# =========================
# Billing UI (upgrade page)
# =========================
@router.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request) -> str:
    pro = is_pro(request)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Upgrade — RiskLab AI Pro</title>
  <style>
    body {{ font-family: Arial, sans-serif; background:#0b0f14; color:#e8eef6; }}
    .wrap {{ max-width: 820px; margin: 0 auto; padding: 28px; }}
    .card {{ background:#101826; border:1px solid #1f2a3a; border-radius:14px; padding:18px; margin:14px 0; }}
    a {{ color:#7dd3fc; }}
    button {{ padding:10px 14px; border-radius:10px; border:0; background:#00d4ff; cursor:pointer; font-weight:700; }}
    code {{ background:#0b1220; padding:2px 6px; border-radius:8px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>💎 RiskLab AI Pro</h1>
    <div class="card">
      <b>Status:</b> {"PRO ✅" if pro else "FREE"}
      <p>Pro unlocks: higher n, longer t_end, and PDF reports.</p>
      <p><a href="/cfd/cavity-fast/view">Back to CFD</a></p>
    </div>

    <div class="card">
      <h3>Option A (FAST): Manual Pro key</h3>
      <p>Set <code>PRO_STATIC_KEY</code> in Render env and give paying users a key.
      They call API with header <code>X-Pro-Key: &lt;key&gt;</code>.</p>
    </div>

    <div class="card">
      <h3>Option B (REAL PAYMENTS): Stripe Checkout</h3>
      <p>Enable Stripe env vars and use endpoint <code>/cfd/stripe/checkout</code>.</p>
      <ul>
        <li><code>STRIPE_SECRET_KEY</code></li>
        <li><code>STRIPE_PRICE_ID</code> (your Pro subscription price)</li>
        <li><code>PRO_SIGNING_KEY</code> (for Pro cookie tokens)</li>
        <li><code>PUBLIC_BASE_URL</code> (e.g. https://risklab-ai-1.onrender.com)</li>
      </ul>
      <p><a href="/cfd/stripe/checkout"><button>Pay with Stripe</button></a></p>
      <div style="opacity:0.8; font-size:13px;">
        After payment, server sets a Pro cookie and you become PRO automatically.
      </div>
    </div>
  </div>
</body>
</html>
"""


# =========================
# Stripe checkout (optional)
# =========================
@router.get("/stripe/checkout")
def stripe_checkout():
    """
    Creates a Stripe Checkout session. Requires stripe package + env vars.
    """
    secret = os.environ.get("STRIPE_SECRET_KEY", "")
    price_id = os.environ.get("STRIPE_PRICE_ID", "")
    base = os.environ.get("PUBLIC_BASE_URL", "")

    if not secret or not price_id or not base:
        raise HTTPException(
            status_code=501,
            detail="Stripe not configured. Set STRIPE_SECRET_KEY, STRIPE_PRICE_ID, PUBLIC_BASE_URL.",
        )

    try:
        import stripe  # type: ignore
    except Exception:
        raise HTTPException(status_code=500, detail="stripe package not installed. Add stripe to requirements.txt")

    stripe.api_key = secret

    success_url = f"{base}/cfd/stripe/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/cfd/billing"

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
    )

    # Redirect user to Stripe checkout URL
    return {"checkout_url": session.url}


@router.get("/stripe/success", response_class=HTMLResponse)
def stripe_success(session_id: str, response: Response):
    """
    After successful payment, set Pro cookie.
    You can also verify the session with Stripe here (recommended).
    """
    # Minimal: issue token (best: verify with Stripe session first)
    token = issue_pro_token(ttl_days=30)
    if not token:
        raise HTTPException(status_code=500, detail="PRO_SIGNING_KEY not set; cannot issue Pro token cookie.")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Pro Activated</title></head>
<body style="font-family:Arial;background:#0b0f14;color:#e8eef6;padding:30px;">
  <h1>✅ Pro activated</h1>
  <p>Your Pro access cookie has been set.</p>
  <p><a href="/cfd/cavity-fast/view" style="color:#7dd3fc;">Go run higher resolution CFD</a></p>
</body></html>
"""
