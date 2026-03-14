"""
Functional checks for Zoom Feedback PTR damping:
- feedback=1 -> no damping (multiplier 1.0)
- feedback=10, full zoom -> strong limit (multiplier ~1/10)
- Full-zoom PTR limit behavior and schema defaults.
Run from repo root: python -m apps.controller.test_zoom_feedback_damping
"""

from __future__ import annotations

import sys
import os

# Allow importing from apps.controller
sys.path.insert(0, os.path.join(os.path.dirname(__file__), *([os.pardir] * 2)))

from mvp_bridge_adc_shape import _ptr_damping_multiplier


def test_feedback_1_no_damping() -> None:
    """feedback=1 yields no damping: multiplier 1.0 at any zoom_norm."""
    assert _ptr_damping_multiplier(1.0, 0.0) == 1.0
    assert _ptr_damping_multiplier(1.0, 0.5) == 1.0
    assert _ptr_damping_multiplier(1.0, 1.0) == 1.0


def test_feedback_10_full_zoom_limit() -> None:
    """feedback=10 at full zoom (zoom_norm=1) yields mult_end = 1/10."""
    mult = _ptr_damping_multiplier(10.0, 1.0)
    assert abs(mult - 0.1) < 1e-6, f"expected ~0.1, got {mult}"


def test_feedback_10_zero_zoom_no_damping() -> None:
    """feedback=10 at zoom_norm=0 yields 1.0 (no damping at wide)."""
    assert _ptr_damping_multiplier(10.0, 0.0) == 1.0


def test_full_zoom_ptr_limit_progression() -> None:
    """As zoom_norm increases, multiplier decreases toward 1/feedback."""
    mult_end = 1.0 / 10.0
    m0 = _ptr_damping_multiplier(10.0, 0.0)
    m05 = _ptr_damping_multiplier(10.0, 0.5)
    m1 = _ptr_damping_multiplier(10.0, 1.0)
    assert m0 == 1.0 and m1 <= mult_end + 1e-6
    assert m0 >= m05 >= m1


def test_schema_default_zoom_feedback() -> None:
    """Shaping schema includes zoom_feedback default 1."""
    from mvp_slow_bridge import _default_shaping_profile, _normalized_shaping_profile

    default = _default_shaping_profile()
    assert "zoom_feedback" in default
    assert default["zoom_feedback"] == 1.0

    # Backward compat: raw without zoom_feedback gets 1.0
    normalized = _normalized_shaping_profile({"expo": 5.0})
    assert normalized.get("zoom_feedback") == 1.0

    normalized_with = _normalized_shaping_profile({"expo": 5.0, "zoom_feedback": 7.0})
    assert normalized_with.get("zoom_feedback") == 7.0


if __name__ == "__main__":
    test_feedback_1_no_damping()
    test_feedback_10_full_zoom_limit()
    test_feedback_10_zero_zoom_no_damping()
    test_full_zoom_ptr_limit_progression()
    test_schema_default_zoom_feedback()
    print("All zoom feedback damping checks passed.")
