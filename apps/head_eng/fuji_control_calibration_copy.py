"""
Copy shim for fuji_control_calibration.

This module intentionally leaves the original calibration utility untouched.
Runtime migration code can import from this copy module while preserving the
original file as the known-good baseline.
"""

from fuji_control_calibration import *  # noqa: F401,F403
