"""Explicit device-role and converter power-sign helpers.

Device names are identifiers only. Runtime classification may use stable model
relations and the explicit ``dev_type`` field, but never descriptive names.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


AC_TO_DC = "AC_TO_DC"


def _control_token(value: Any) -> str:
    return str(value or "").strip().upper()


def canonical_generator_type(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    return {
        "acgenerator": "ACGenerator",
        "dcgenerator": "DCGenerator",
    }.get(normalized, "")


def device_role_from_type(value: Any) -> str:
    """Return a semantic resource role from an explicit type value."""
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return ""
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalized)
        if token
    }
    collapsed = "".join(tokens)
    if tokens.intersection({"storage", "battery", "ess"}) or "energystorage" in collapsed:
        return "storage"
    if tokens.intersection({"wind", "windgen", "windgenerator", "turbine"}) or "windsource" in collapsed:
        return "wind"
    if tokens.intersection({"pv", "solar", "photovoltaic"}) or "pvsource" in collapsed:
        return "pv"
    if tokens.intersection({"diesel", "genset"}) or "dieselgenerator" in collapsed:
        return "diesel"
    return ""


def converter_direction_from_type(value: Any, fallback_device_type: Any = "") -> str:
    """Recognize compatible AC/DC converter classes with the P_AC convention."""
    for candidate in (value, fallback_device_type):
        collapsed = re.sub(
            r"[^a-z0-9]+",
            "",
            str(candidate or "").strip().casefold(),
        )
        if "acdc" in collapsed or "dcac" in collapsed:
            return AC_TO_DC
    return ""


def converter_role_from_type(value: Any, fallback_device_type: Any = "") -> str:
    """Return the explicit grid/internal role without consulting a device name."""
    if not converter_direction_from_type(value, fallback_device_type):
        return ""
    normalized = str(value or "").strip().casefold()
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalized)
        if token
    }
    if device_role_from_type(value) in {"wind", "pv", "storage"}:
        return "internal"
    if tokens.intersection({"grid", "intertie", "boundary", "coupling", "link"}):
        return "grid"
    return ""


def converter_balance_coefficients(direction: Any) -> tuple[float, float]:
    """Return converter coefficients for the AC and DC adjustment balances."""
    normalized = str(direction or "").strip().upper()
    if normalized == AC_TO_DC:
        return -1.0, 1.0
    raise ValueError(f"unsupported converter direction: {direction!r}")


def converter_control_mode(row: Mapping[str, Any]) -> str:
    """Return the active converter-side control mode.

    Explicit DC active-power control has priority over AC-terminal control.
    A converter whose AC and DC modes are both disabled falls back to DC
    active-power control so the model remains controllable through
    ``p_dc_set``. ``DCACConverter`` no longer exposes a combined
    ``control_type`` field.
    """
    ac_mode, dc_mode = converter_effective_control_types(row)
    if dc_mode and dc_mode != "NONE":
        return dc_mode
    if ac_mode and ac_mode != "NONE":
        return ac_mode
    return ""


def converter_effective_control_types(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return terminal modes after applying the explicit DC-power fallback.

    The load-flow kernel accepts one active-power controller per converter.
    ``dc_control_type=P`` therefore disables AC-side power control, including
    malformed dual-active rows. Explicit ``NONE/NONE`` (and legacy rows with
    an explicit disabled DC side but no AC mode) use the required ``p_dc_set``
    fallback without mutating the source model.
    """
    ac_mode = _control_token(row.get("ac_control_type"))
    dc_mode = _control_token(row.get("dc_control_type"))
    if dc_mode == "P":
        return "NONE", "P"
    if dc_mode == "NONE" and ac_mode in {"", "NONE"}:
        return "NONE", "P"
    return ac_mode, dc_mode


def converter_active_power_setpoint_field(row: Mapping[str, Any]) -> str:
    """Select the terminal power setpoint from explicit DC control state.

    ``dc_control_type=P`` selects ``p_dc_set``. Explicit ``NONE/NONE`` also
    selects ``p_dc_set``. Otherwise an explicitly disabled DC power controller
    selects ``p_ac_set`` when the AC terminal declares an active-power-capable
    control mode.
    """
    ac_mode, dc_mode = converter_effective_control_types(row)
    if dc_mode == "P":
        return "p_dc_set"
    if dc_mode in {"", "NONE"} and ac_mode in {"PQ", "PV", "PH"}:
        return "p_ac_set"
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
