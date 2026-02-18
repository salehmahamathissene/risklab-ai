from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/airline", tags=["airline"])

# Add vendored PIE to import path (submodule)
PIE_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "passenger-impact-engine"
if PIE_ROOT.exists():
    sys.path.insert(0, str(PIE_ROOT))


@router.get("/run-demo")
def run_demo() -> Dict[str, Any]:
    """
    Try to call PIE's demo runner if available; otherwise return a static demo.
    """
    # 1) Try a few common entrypoints safely
    candidates = [
        ("pie.api.app", "run_demo"),
        ("pie.cli", "run_demo"),
        ("pie.app", "run_demo"),
    ]

    for mod, fn in candidates:
        try:
            m = __import__(mod, fromlist=[fn])
            f = getattr(m, fn)
            out = f()

            # If PIE returns a JSON string, parse it
            if isinstance(out, str):
                try:
                    return json.loads(out)
                except Exception:
                    return {"raw": out}

            # If PIE returns dict already
            if isinstance(out, dict):
                return out

            return {"result": out}
        except Exception:
            continue

    # 2) Fallback: static demo (always works)
    return {
        "carrier": "DemoAir",
        "flight": "DA123",
        "event": "delay",
        "delay_min": 190,
        "passengers": 180,
        "currency": "EUR",
        "mode": "Monte Carlo",
        "n_sim": 5000,
        "expected_exposure": 104890,
        "expected_eu261": 73959,
        "expected_ops": 30931,
        "p50": 109067,
        "p95": 114670,
        "quantiles": {
            "q10": 77523,
            "q25": 105650,
            "q50": 109067,
            "q75": 111482,
            "q90": 113527,
            "q95": 114670,
            "q99": 116772,
        },
        "note": "PIE entrypoint not found yet; returned static demo.",
    }
