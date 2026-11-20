"""Polar microgrid time-series simulation service and web consoles."""

from __future__ import annotations

import os


NUMERIC_THREAD_ENV_NAMES = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def _configure_numeric_thread_limits() -> str:
    raw_limit = str(os.environ.get("POWER_SIMU_NUMERIC_THREADS", "1") or "1").strip()
    try:
        limit = str(max(1, min(64, int(float(raw_limit)))))
    except (TypeError, ValueError):
        limit = "1"
    os.environ["POWER_SIMU_NUMERIC_THREADS"] = limit
    for name in NUMERIC_THREAD_ENV_NAMES:
        os.environ.setdefault(name, limit)
    return limit


NUMERIC_THREAD_LIMIT = _configure_numeric_thread_limits()

from .service import MultiModelSimulator, PolarMicrogridSimulator, SimulationModelSpec

__all__ = [
    "MultiModelSimulator",
    "PolarMicrogridSimulator",
    "SimulationModelSpec",
    "NUMERIC_THREAD_ENV_NAMES",
    "NUMERIC_THREAD_LIMIT",
]
