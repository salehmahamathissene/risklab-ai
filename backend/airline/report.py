from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def generate_airline_report(stats: Dict[str, Any], out_path: str) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(out_path, pagesize=letter)
    w, h = letter
    y = h - 60

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "RiskLab AI — Airline Disruption Cost Report")
    y -= 22

    c.setFont("Helvetica", 10)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    c.drawString(50, y, f"Generated: {ts} (UTC)")
    y -= 25

    # Stats format varies; these keys are based on your earlier output
    summary = stats.get("summary", {}) if isinstance(stats.get("summary"), dict) else {}
    expected = summary.get("expected_eur") or summary.get("expected") or stats.get("expected_eur")
    p50 = summary.get("p50_eur") or summary.get("p50")
    p95 = summary.get("p95_eur") or summary.get("p95")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Key Risk Metrics")
    y -= 18

    c.setFont("Helvetica", 11)
    c.drawString(60, y, f"Expected Exposure: {expected}")
    y -= 16
    c.drawString(60, y, f"P50 Exposure: {p50}")
    y -= 16
    c.drawString(60, y, f"P95 Worst Case: {p95}")
    y -= 22

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Notes")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(60, y, "Monte Carlo estimate based on configured scenario.")
    y -= 16

    c.showPage()
    c.save()
    return out_path
