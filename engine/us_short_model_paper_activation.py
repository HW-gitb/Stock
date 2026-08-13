# -*- coding: utf-8 -*-
"""The single dormant/authorized door for the model-paper execution path."""
from __future__ import annotations

from typing import Any

from engine.us_short_market_diagnostic_start_receipt import DEFAULT_ROOT, load_start_receipt

MODEL_PAPER_ACTIVATION_ROOT = DEFAULT_ROOT


def resolve_model_paper_activation() -> dict[str, Any]:
    """Re-check the existing design receipt and return only dormant/authorized."""
    receipt = load_start_receipt(
        MODEL_PAPER_ACTIVATION_ROOT,
        verify_design_against_disk=True,
    )
    if receipt is None:
        return {"status": "dormant", "receipt": None}
    return {"status": "authorized", "receipt": receipt}


__all__ = ["MODEL_PAPER_ACTIVATION_ROOT", "resolve_model_paper_activation"]
