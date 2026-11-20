from __future__ import annotations

from typing import Any


SIGNAL_POINT_TYPES = frozenset(("RUN_STAT", "STATUS"))


def automatic_point_name(dev_type: Any, dev_name: Any, point_type: Any) -> str:
    """Return the canonical name used for automatically generated points."""
    device_type = str(dev_type or "").strip()
    device_name = str(dev_name or "").strip()
    suffix = str(point_type or "").strip()
    if suffix.upper() in SIGNAL_POINT_TYPES:
        suffix = suffix.lower()
    return f"{device_type}.{device_name}.{suffix}"
