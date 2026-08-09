"""Converter control and power-sign helpers.

Runtime device roles come from model relations and topology. Device names and
row-level ``dev_type`` values are protocol identifiers or display metadata;
this module deliberately does not interpret their text as semantic roles.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


AC_TO_DC = "AC_TO_DC"


def _control_token(value: Any) -> str:
    return str(value or "").strip().upper()


def converter_balance_coefficients(direction: Any) -> tuple[float, float]:
    """Return converter coefficients for the AC and DC adjustment balances."""
    normalized = str(direction or "").strip().upper()
    if normalized == AC_TO_DC:
        return -1.0, 1.0
    raise ValueError(f"unsupported converter direction: {direction!r}")


def converter_control_mode(row: Mapping[str, Any]) -> str:
    """Return the active converter-side control mode.

    Explicit DC-terminal control has priority over AC-terminal control, and
    both take precedence over the legacy combined mode. ``NONE`` is a real
    model token but not an active mode, so it must not hide a valid control
    configured on the opposite terminal.
    """
    ac_mode = _control_token(row.get("ac_control_type"))
    dc_mode = _control_token(row.get("dc_control_type"))
    if dc_mode and dc_mode != "NONE":
        return dc_mode
    if ac_mode and ac_mode != "NONE":
        return ac_mode
    return _control_token(row.get("control_type") or row.get("mode"))


def converter_active_power_setpoint_field(row: Mapping[str, Any]) -> str:
    """Return the power setpoint, preferring an active DC-side controller."""
    ac_mode = _control_token(row.get("ac_control_type"))
    dc_mode = _control_token(row.get("dc_control_type"))
    legacy_mode = _control_token(row.get("control_type") or row.get("mode"))
    if dc_mode == "P":
        return "p_dc_set"
    if "dc_control_type" in row and dc_mode in {"", "NONE"}:
        return "p_ac_set"
    if ac_mode in {"PQ", "PV"}:
        return "p_ac_set"
    if legacy_mode in {"ACP", "DCV", "PQ", "PV"}:
        return "p_ac_set"
    if legacy_mode == "DCP":
        return "p_dc_set"
    return ""


def converter_power_setpoint_fields(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return valid converter active-power fields in control-priority order."""
    active_field = converter_active_power_setpoint_field(row)
    if active_field == "p_ac_set":
        return "p_ac_set", "p_set"
    if active_field == "p_dc_set":
        return ("p_dc_set",)
    return "p_ac_set", "p_dc_set", "p_set"


def converter_power_in_dc_to_ac_convention(
    value: Any,
    direction: Any,
    power_field: Any = "P_AC",
) -> float:
    """Normalize terminal power so physical DC-to-AC transfer is positive.

    AC-terminal powers are positive into the converter, while DC-terminal
    powers are positive from the DC grid into the converter.  Therefore a
    DC-to-AC transfer has ``P_AC < 0`` and ``P_DC > 0``.
    """
    number = float(value)
    normalized = str(direction or "").strip().upper()
    if normalized != AC_TO_DC:
        raise ValueError(f"unsupported converter direction: {direction!r}")
    field = re.sub(r"[^A-Z0-9]+", "", str(power_field or "P_AC").strip().upper())
    if field in {"PDC", "PDCSET"}:
        return number
    if field in {"P", "PSET", "PAC", "PACSET"}:
        return -number
    raise ValueError(f"unsupported converter power field: {power_field!r}")


def converter_power_in_ac_terminal_convention(
    value: Any,
    direction: Any,
    power_field: Any = "P_AC",
) -> float:
    """Normalize converter power to the signed AC-terminal convention.

    The returned value follows ``P_AC``/``p_ac_set``: AC-to-DC is positive
    and DC-to-AC is negative. This is the convention used by converter limits
    and automatic-control setpoints.
    """
    return -converter_power_in_dc_to_ac_convention(
        value,
        direction,
        power_field,
    )


def converter_setpoint_from_p_ac_convention(
    value: Any,
    direction: Any,
    set_field: Any = "p_ac_set",
) -> float:
    """Convert an internal AC-terminal target to the selected control point.

    Renewable dispatch optimizes converter power in the ``P_AC`` convention.
    AC-terminal setpoints keep that sign, while DC-terminal setpoints use the
    opposite sign: DC-to-AC therefore means ``p_ac_set < 0`` and
    ``p_dc_set > 0``.
    """
    number = float(value)
    normalized = str(direction or "").strip().upper()
    if normalized != AC_TO_DC:
        raise ValueError(f"unsupported converter direction: {direction!r}")
    field = re.sub(
        r"[^A-Z0-9]+",
        "",
        str(set_field or "p_ac_set").strip().upper(),
    )
    if field in {"PDC", "PDCSET"}:
        return -number
    if field in {"P", "PSET", "PAC", "PACSET"}:
        return number
    raise ValueError(f"unsupported converter setpoint field: {set_field!r}")
