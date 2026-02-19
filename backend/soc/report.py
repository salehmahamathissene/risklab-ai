from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from reportlab.pdfgen import canvas


def _safe_str(x: Any) -> str:
    try:
        return str(x)
    except Exception:
        return "<unprintable>"


def _flatten_findings(findings: Any) -> list[Any]:
    """
    Defensive flatten:
    - Accept None / single object / list / nested lists
    - Return ONLY objects that look like findings (have .severity or at least some text)
    """
    out: list[Any] = []

    def walk(v: Any) -> None:
        if v is None:
            return
        if isinstance(v, dict):
            # common wrappers
            for k in ("findings", "alerts", "items", "events", "results"):
                if k in v:
                    walk(v[k])
                    return
            return
        if isinstance(v, (list, tuple)):
            for it in v:
                walk(it)
            return
        # single item
        out.append(v)

    walk(findings)
    return out


def generate_soc_report(findings: Any, out_path: str | Path = "/tmp/risklab/soc_report.pdf") -> Path:
    """
    Generate a PDF SOC report.
    - NEVER crashes if findings contain nested lists or weird types.
    - Writes to out_path and returns Path.
    """
    out_path = Path(out_path)

    # --- CRITICAL: must be inside function (indented) ---
    findings_list = _flatten_findings(findings)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(out_path))
    y = 800

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "SOC Report")
    y -= 30

    c.setFont("Helvetica", 12)

    if not findings_list:
        c.drawString(50, y, "No findings detected.")
        c.save()
        return out_path

    for f in findings_list:
        # Skip if f is still a list/tuple (shouldn't happen, but safe)
        if isinstance(f, (list, tuple)):
            continue

        # Defensive fields
        severity = getattr(f, "severity", "UNKNOWN")
        title = getattr(f, "title", None) or getattr(f, "name", None) or "Finding"
        desc = getattr(f, "description", None) or getattr(f, "text", None) or _safe_str(f)

        c.drawString(50, y, f"Severity: {severity}")
        y -= 16
        c.drawString(50, y, f"Title: {title}")
        y -= 16
        c.drawString(50, y, f"Details: {desc[:140]}")
        y -= 24

        # New page if needed
        if y < 80:
            c.showPage()
            c.setFont("Helvetica", 12)
            y = 800

    c.save()
    return out_path
