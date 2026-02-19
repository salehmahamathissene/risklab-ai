# backend/soc/report.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from backend.soc.detections import SOCFinding


def generate_soc_report(f: SOCFinding, out_path: str) -> str:
# Defensive flatten (prevents list.severity forever)
flat = []
for item in findings or []:
    if isinstance(item, (list, tuple)):
        flat.extend(item)
    else:
        flat.append(item)
findings = flat

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(out_path, pagesize=letter)
    w, h = letter

    y = h - 60
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "RiskLab AI — SOC Incident Report")
    y -= 25

    c.setFont("Helvetica", 10)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    c.drawString(50, y, f"Generated: {ts} (UTC)")
    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, f"Severity: {f.severity}")
    y -= 20

    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Summary: {f.summary}")
    y -= 25

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Key Metrics")
    y -= 18
    c.setFont("Helvetica", 11)
    c.drawString(60, y, f"Total failed logins: {f.total_failed}")
    y -= 16
    c.drawString(60, y, f"Unique source IPs: {f.unique_ips}")
    y -= 24

    def draw_list(title: str, items: list[tuple[str, int]]):
        nonlocal y
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, title)
        y -= 18
        c.setFont("Helvetica", 11)
        if not items:
            c.drawString(60, y, "None")
            y -= 16
            return
        for k, v in items:
            c.drawString(60, y, f"{k}  —  {v}")
            y -= 16

    draw_list("Top attacker IPs", f.top_ips)
    y -= 10
    draw_list("Top targeted usernames", f.top_users)

    c.showPage()
    c.save()
    return out_path
