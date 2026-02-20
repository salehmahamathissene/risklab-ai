from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from backend.core.config import settings
from backend.cfd.pro_models import get_db, ProCustomer, CFDJob
from backend.worker import make_queue, run_cfd_job

# =========================
# Router
# =========================
router = APIRouter(prefix="/cfd", tags=["cfd"])

CFD_OUT_DIR = Path(os.environ.get("CFD_OUT_DIR", "/tmp/cfd")).resolve()
CFD_OUT_DIR.mkdir(parents=True, exist_ok=True)

COOKIE_NAME = "risklab_pro"

FREE_LIMITS = {"n_max": 64, "t_end_max": 0.5}
PRO_LIMITS = {"n_max": 256, "t_end_max": 10.0}


# =========================
# Pro token (cookie) with customer_id
# =========================
def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_pro_token(customer_id: str, ttl_days: int = 30) -> str:
    if not settings.pro_signing_key:
        return ""
    now = int(time.time())
    exp = now + ttl_days * 24 * 3600
    payload = {"exp": exp, "iat": now, "cid": customer_id}
    payload_b = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_s = _b64url(payload_b)

    sig = hmac.new(settings.pro_signing_key.encode("utf-8"), payload_s.encode("utf-8"), hashlib.sha256).digest()
    sig_s = _b64url(sig)
    return f"{payload_s}.{sig_s}"


def verify_pro_token(token: str) -> Optional[str]:
    if not token or not settings.pro_signing_key:
        return None
    try:
        payload_s, sig_s = token.split(".", 1)
        expected = hmac.new(settings.pro_signing_key.encode("utf-8"), payload_s.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), sig_s):
            return None
        payload = json.loads(_b64url_decode(payload_s).decode("utf-8"))
        exp = int(payload.get("exp", 0))
        if int(time.time()) >= exp:
            return None
        cid = payload.get("cid")
        return str(cid) if cid else None
    except Exception:
        return None


def is_pro(request: Request, db) -> bool:
    # 1) cookie token -> DB check
    tok = request.cookies.get(COOKIE_NAME, "")
    cid = verify_pro_token(tok)
    if cid:
        row = db.get(ProCustomer, cid)
        if row and row.active:
            return True

    # 2) header fallback (optional)
    hdr = request.headers.get("X-Pro-Key", "")
    if settings.pro_static_key and hdr and hmac.compare_digest(hdr, settings.pro_static_key):
        return True

    return False


def enforce_limits(request: Request, db, n: int, t_end: float) -> bool:
    pro = is_pro(request, db)
    limits = PRO_LIMITS if pro else FREE_LIMITS
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
    return pro


def make_job_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"cfd_{ts}_{uuid.uuid4().hex[:6]}"


def tail_lines(s: str, k: int = 30) -> list[str]:
    lines = (s or "").splitlines()
    return lines[-k:]


# =========================
# API: create job (fast)
# =========================
@router.get("/cavity-fast")
def cavity_fast(
    request: Request,
    db=Depends(get_db),
    n: int = 64,
    re: float = 1000.0,
    dt: float = 0.005,
    t_end: float = 0.5,
) -> Dict[str, Any]:
    """
    Production: creates job + enqueues to worker (does NOT run CFD inside request)
    """
    pro = enforce_limits(request, db, n=n, t_end=t_end)

    job_id = make_job_id()
    params = {"n": n, "re": re, "dt": dt, "t_end": t_end}

    row = CFDJob(
        job_id=job_id,
        status="queued",
        pro=pro,
        params_json=json.dumps(params, separators=(",", ":")),
        output_dir=str((CFD_OUT_DIR / job_id).resolve()),
    )
    db.add(row)
    db.commit()

    # enqueue background job
    q = make_queue()
    q.enqueue(run_cfd_job, job_id, job_timeout=900)  # 15 min

    return {
        "ok": True,
        "pro": pro,
        "job_id": job_id,
        "params": params,
        "status_url": f"/cfd/jobs/{job_id}",
        "view_url": f"/cfd/jobs/{job_id}/view",
        "report_url": f"/cfd/jobs/{job_id}/report.pdf",
        "files": {
            "speed": f"/cfd/jobs/{job_id}/file/cavity_fast_speed.png",
            "vorticity": f"/cfd/jobs/{job_id}/file/cavity_fast_vorticity.png",
        },
        "hint": "Poll status_url until status=='done', then open view_url.",
    }


@router.get("/jobs/{job_id}")
def job_status(job_id: str, db=Depends(get_db)) -> Dict[str, Any]:
    row = db.get(CFDJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": row.job_id,
        "status": row.status,
        "pro": row.pro,
        "created_at": row.created_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "error": row.error,
        "view_url": f"/cfd/jobs/{job_id}/view",
        "report_url": f"/cfd/jobs/{job_id}/report.pdf",
    }


# =========================
# UI: landing page
# =========================
@router.get("/cavity-fast/view", response_class=HTMLResponse)
def cavity_fast_view(request: Request, db=Depends(get_db)) -> str:
    pro = is_pro(request, db)
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
          <button type="submit">▶ Create Job (JSON)</button>
          <a class="small" href="/cfd/cavity-fast">Use defaults</a>
          <a class="small" href="/cfd/pro">Pro status</a>
          <a class="small" href="/cfd/billing">Upgrade</a>
        </div>
      </form>

      <div class="warn" style="margin-top:14px;">
        <b>Tip:</b> After you run, poll <b>status_url</b> until <b>done</b>, then open <b>view_url</b>.
      </div>
    </div>

    <div class="card">
      <h3>What Pro gives you</h3>
      <ul>
        <li>Higher grid resolution (up to n={PRO_LIMITS['n_max']})</li>
        <li>Longer simulation (up to t_end={PRO_LIMITS['t_end_max']})</li>
        <li>PDF report download per run</li>
        <li>Background worker (no timeouts)</li>
      </ul>
    </div>
  </div>
</body>
</html>
"""


@router.get("/pro")
def pro_status(request: Request, db=Depends(get_db)) -> Dict[str, Any]:
    return {
        "pro": is_pro(request, db),
        "free_limits": FREE_LIMITS,
        "pro_limits": PRO_LIMITS,
        "hint": "Real Pro comes from Stripe webhooks -> DB active. Cookie alone is not enough.",
    }


# =========================
# Job view page
# =========================
@router.get("/jobs/{job_id}/view", response_class=HTMLResponse)
def job_view(job_id: str, db=Depends(get_db)) -> str:
    row = db.get(CFDJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")

    if row.status != "done":
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>CFD Job {job_id}</title></head>
<body style="font-family:Arial;background:#0b0f14;color:#e8eef6;padding:30px;">
  <h1>⏳ Job not ready</h1>
  <p><b>Job:</b> {job_id}</p>
  <p><b>Status:</b> {row.status}</p>
  <p><a href="/cfd/jobs/{job_id}" style="color:#7dd3fc;">Check JSON status</a></p>
  <p>Refresh this page after status becomes <b>done</b>.</p>
</body></html>"""

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
        <a href="/cfd/jobs/{job_id}"><button class="secondary">📦 JSON status</button></a>
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


@router.get("/jobs/{job_id}/file/{name}")
def job_file(job_id: str, name: str, db=Depends(get_db)):
    row = db.get(CFDJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")
    job_dir = Path(row.output_dir or (CFD_OUT_DIR / job_id)).resolve()
    path = (job_dir / name).resolve()

    if not str(path).startswith(str(job_dir)):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found.")

    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "Expires": "0"}
    return FileResponse(path, headers=headers)


@router.get("/jobs/{job_id}/report.pdf")
def job_report(job_id: str, db=Depends(get_db)):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    row = db.get(CFDJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")
    if row.status != "done":
        raise HTTPException(status_code=409, detail="Job not done yet.")

    job_dir = Path(row.output_dir or (CFD_OUT_DIR / job_id)).resolve()
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
# Billing UI
# =========================
@router.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request, db=Depends(get_db)) -> str:
    pro = is_pro(request, db)
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
      <h3>Real payments (Stripe Subscription)</h3>
      <ul>
        <li><code>STRIPE_SECRET_KEY</code></li>
        <li><code>STRIPE_PRICE_ID</code></li>
        <li><code>STRIPE_WEBHOOK_SECRET</code></li>
        <li><code>PRO_SIGNING_KEY</code></li>
        <li><code>PUBLIC_BASE_URL</code> (https://risklab-ai-1.onrender.com)</li>
      </ul>
      <p><a href="/cfd/stripe/checkout"><button>Pay with Stripe</button></a></p>
      <div style="opacity:0.8; font-size:13px;">
        Pro is activated only after Stripe verification + DB update.
      </div>
    </div>
  </div>
</body>
</html>
"""


# =========================
# Stripe checkout: redirect to Stripe
# =========================
@router.get("/stripe/checkout")
def stripe_checkout():
    secret = settings.stripe_secret_key or ""
    price_id = settings.stripe_price_id or ""
    base = settings.public_base_url or ""

    if not secret or not price_id or not base:
        raise HTTPException(501, "Stripe not configured. Set STRIPE_SECRET_KEY, STRIPE_PRICE_ID, PUBLIC_BASE_URL.")

    import stripe  # type: ignore

    stripe.api_key = secret

    success_url = f"{base}/cfd/stripe/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/cfd/billing"

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return RedirectResponse(session.url, status_code=303)


# =========================
# Stripe success: VERIFY session before cookie
# =========================
@router.get("/stripe/success", response_class=HTMLResponse)
def stripe_success(session_id: str, response: Response, db=Depends(get_db)):
    if not settings.stripe_secret_key:
        raise HTTPException(501, "Stripe not configured")

    import stripe  # type: ignore

    stripe.api_key = settings.stripe_secret_key

    # Verify the checkout session
    sess = stripe.checkout.Session.retrieve(session_id, expand=["subscription", "customer"])
    sub = sess.get("subscription")
    cust = sess.get("customer")

    # subscription must be active/trialing
    status = getattr(sub, "status", None) if sub else None
    if status not in ("active", "trialing"):
        raise HTTPException(403, f"Subscription not active (status={status}).")

    customer_id = str(cust)
    subscription_id = getattr(sub, "id", None) if sub else None

    # Update DB: mark as active
    row = db.get(ProCustomer, customer_id)
    if not row:
        row = ProCustomer(customer_id=customer_id, subscription_id=subscription_id, active=True)
        db.add(row)
    else:
        row.subscription_id = subscription_id
        row.active = True
        row.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Issue cookie tied to customer id (DB is source of truth)
    token = issue_pro_token(customer_id=customer_id, ttl_days=30)
    if not token:
        raise HTTPException(500, "PRO_SIGNING_KEY not set; cannot issue Pro cookie.")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )

    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Pro Activated</title></head>
<body style="font-family:Arial;background:#0b0f14;color:#e8eef6;padding:30px;">
  <h1>✅ Pro activated</h1>
  <p>Your subscription is verified and Pro is enabled.</p>
  <p><a href="/cfd/cavity-fast/view" style="color:#7dd3fc;">Go run higher resolution CFD</a></p>
</body></html>
"""


# =========================
# Stripe webhook: SOURCE OF TRUTH
# =========================
@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db=Depends(get_db)):
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise HTTPException(501, "Webhook not configured")

    import stripe  # type: ignore

    stripe.api_key = settings.stripe_secret_key

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except Exception:
        raise HTTPException(400, "Invalid webhook signature")

    et = event["type"]
    obj = event["data"]["object"]

    def _set_customer(customer_id: str, subscription_id: Optional[str], active: bool):
        row = db.get(ProCustomer, customer_id)
        if not row:
            row = ProCustomer(customer_id=customer_id, subscription_id=subscription_id, active=active)
            db.add(row)
        else:
            row.subscription_id = subscription_id or row.subscription_id
            row.active = active
            row.updated_at = datetime.now(timezone.utc)
        db.commit()

    # Activate on paid signals
    if et in ("checkout.session.completed", "invoice.paid"):
        customer_id = str(obj.get("customer"))
        sub_id = obj.get("subscription")
        if customer_id:
            _set_customer(customer_id, str(sub_id) if sub_id else None, True)

    # Deactivate on cancel/failure
    if et in ("customer.subscription.deleted", "invoice.payment_failed"):
        customer_id = str(obj.get("customer"))
        sub_id = obj.get("id") or obj.get("subscription")
        if customer_id:
            _set_customer(customer_id, str(sub_id) if sub_id else None, False)

    return {"ok": True, "event": et}
