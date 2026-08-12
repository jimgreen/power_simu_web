from __future__ import annotations

import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class DefinitionSnapshot:
    revision: int
    model_book: Any
    dev_define_book: Any
    measurement_before: Tuple[str, ...]
    measurement_rows: Tuple[Tuple[str, ...], ...]
    measurement_after: Tuple[str, ...]
    measurement_median_deviations: Tuple[Tuple[str, float], ...] = ()


class DefinitionRevisionConflict(ValueError):
    def __init__(self, expected_revision: int, current_revision: int) -> None:
        super().__init__(
            "Definition revision conflict: "
            f"expected {expected_revision}, current {current_revision}"
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision


PROTECTED_DEVICE_FIELDS = {
    "idx",
    "name",
    "dev_name",
    "dev_type",
    "path",
    "node",
    "i_node",
    "j_node",
    "ac_node",
    "dc_node",
    "isl",
}

BINARY_DEVICE_FIELDS = {"run_stat", "status"}

DIAGRAM_RATIO_DEVICE_FIELDS = {
    "state_of_charge",
    "soc",
    "soc_curr",
    "soc_cur",
    "soc_min",
    "soc_max",
    "soc_lower_limit",
    "soc_upper_limit",
}

NONNEGATIVE_DEVICE_FIELD_TOKENS = (
    "capacity",
    "efficiency",
    "count",
    "area",
    "diameter",
    "height",
    "rated_power",
    "rated_voltage",
    "wind_speed",
)

MEASUREMENT_STATUS_TOKENS = (
    "valid",
    "invalid",
    "undefined",
    "dead",
    "zero",
    "fixed",
)

MEASUREMENT_STATUS_VALIDITY = {
    "valid": 1,
    "invalid": 0,
    "undefined": 0,
    "dead": 1,
    "zero": 1,
    "fixed": 1,
}


def editable_device_field(field: str) -> bool:
    name = str(field or "").strip().casefold()
    return bool(name) and name not in PROTECTED_DEVICE_FIELDS and not name.startswith("idx_")


def _finite_number(value: Any, field: str) -> float:
    raw = str(value).strip()
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    try:
        number = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _number_text(value: float) -> str:
    text = format(float(value), ".15g")
    return "0" if text in {"-0", "-0.0"} else text


def _normalized_field_name(field: Any) -> str:
    return str(field or "").strip().casefold()


def is_soc_parameter_field(field: Any) -> bool:
    name = _normalized_field_name(field)
    return name in DIAGRAM_RATIO_DEVICE_FIELDS or name.startswith("soc_")


def is_efficiency_parameter_field(field: Any) -> bool:
    name = _normalized_field_name(field)
    return bool(
        "efficiency" in name
        or name == "eta"
        or name.startswith("eta_")
        or name.endswith("_eta")
        or name.endswith("_eff")
    )


def is_ratio_parameter_field(field: Any) -> bool:
    return is_soc_parameter_field(field) or is_efficiency_parameter_field(field)


def ratio_parameter_number(
    field: Any,
    value: Any,
    *,
    legacy_percent_points: bool = False,
) -> float:
    raw = str(value).strip()
    number = _finite_number(value, str(field))
    if raw.endswith("%"):
        return number / 100.0
    if legacy_percent_points:
        if is_efficiency_parameter_field(field) and 1.0 < number <= 100.0:
            return number / 100.0
        if is_soc_parameter_field(field) and 2.0 < abs(number) <= 100.0:
            return number / 100.0
    return number


def canonical_ratio_parameter_text(
    field: Any,
    value: Any,
    *,
    legacy_percent_points: bool = False,
    allow_out_of_range: bool = False,
) -> str:
    number = ratio_parameter_number(
        field,
        value,
        legacy_percent_points=legacy_percent_points,
    )
    if not allow_out_of_range and not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return _number_text(number)


def _numeric_cell(value: Any) -> bool:
    try:
        raw = str(value).strip()
        if raw.endswith("%"):
            raw = raw[:-1].strip()
        return math.isfinite(float(raw))
    except (TypeError, ValueError):
        return False


def _bound_pairs(fields: Sequence[str]) -> set[tuple[str, str]]:
    available = set(fields)
    pairs: set[tuple[str, str]] = set()
    for field in available:
        if field.endswith("_min"):
            counterpart = f"{field[:-4]}_max"
            if counterpart in available:
                pairs.add((field, counterpart))
        if field.endswith("_lower_limit"):
            counterpart = f"{field[:-12]}_upper_limit"
            if counterpart in available:
                pairs.add((field, counterpart))
    return pairs


def _configured_number(row: Mapping[str, Any], field: str) -> float | None:
    value = row.get(field)
    if value in (None, "", "-"):
        return None
    try:
        return _finite_number(value, field)
    except ValueError:
        return None


def _setpoint_bound_candidates(
    current: Mapping[str, Any],
    setpoint: str,
) -> list[tuple[str, str]]:
    field = _normalized_field_name(setpoint)
    if not field.endswith("_set"):
        return []
    stem = field[:-4]
    candidates: list[tuple[str, str]] = [(f"{stem}_min", f"{stem}_max")]
    terminal_aliases = {
        "p_ac": "ac_p",
        "q_ac": "ac_q",
        "v_ac": "ac_v",
        "i_ac": "ac_i",
        "p_dc": "dc_p",
        "q_dc": "dc_q",
        "v_dc": "dc_v",
        "i_dc": "dc_i",
        "p_from": "i_p",
        "q_from": "i_q",
        "v_from": "i_v",
        "i_from": "i_i",
        "p_to": "j_p",
        "q_to": "j_q",
        "v_to": "j_v",
        "i_to": "j_i",
    }
    alias = terminal_aliases.get(stem)
    if alias:
        candidates.append((f"{alias}_min", f"{alias}_max"))

    quantity = stem if stem in {"p", "q", "v", "i"} else ""
    if quantity and any(
        key in current
        for key in (
            "i_control_type",
            "j_control_type",
            f"i_{quantity}_min",
            f"i_{quantity}_max",
            f"j_{quantity}_min",
            f"j_{quantity}_max",
        )
    ):
        mode_tokens = {
            "p": {"P", "PQ", "CTRL_P"},
            "q": {"Q", "PQ", "CTRL_Q"},
            "v": {"V", "PV", "CTRL_V", "SLACK"},
            "i": {"I", "CTRL_I"},
        }[quantity]
        selected_sides = [
            side
            for side in ("i", "j")
            if str(current.get(f"{side}_control_type", "")).strip().upper()
            in mode_tokens
        ]
        sides = selected_sides or ["i", "j"]
        candidates.extend(
            (f"{side}_{quantity}_min", f"{side}_{quantity}_max")
            for side in sides
        )
    return list(dict.fromkeys(candidates))


def configured_setpoint_bounds(
    current: Mapping[str, Any],
    setpoint: Any,
) -> tuple[str, float | None, str, float | None] | None:
    """Return the effective configured bounds for one analog setpoint.

    A complete terminal-specific pair takes precedence. If a dual-terminal
    device does not declare a unique controlled side, all configured terminal
    limits form a conservative intersection instead of guessing by name.
    """

    candidates = _setpoint_bound_candidates(current, str(setpoint))
    configured: list[tuple[str, float | None, str, float | None]] = []
    for lower, upper in candidates:
        lower_number = _configured_number(current, lower)
        upper_number = _configured_number(current, upper)
        if lower_number is None and upper_number is None:
            continue
        configured.append((lower, lower_number, upper, upper_number))

    if not configured:
        return None
    lower_options = list(enumerate(item for item in configured if item[1] is not None))
    upper_options = list(enumerate(item for item in configured if item[3] is not None))
    lower_entry = (
        max(lower_options, key=lambda entry: (float(entry[1][1]), entry[0]))
        if lower_options
        else None
    )
    upper_entry = (
        min(upper_options, key=lambda entry: (float(entry[1][3]), -entry[0]))
        if upper_options
        else None
    )
    lower_item = lower_entry[1] if lower_entry else None
    upper_item = upper_entry[1] if upper_entry else None
    return (
        lower_item[0] if lower_item else "",
        lower_item[1] if lower_item else None,
        upper_item[2] if upper_item else "",
        upper_item[3] if upper_item else None,
    )


def validate_setpoint_safety_bounds(
    current: Mapping[str, Any],
    setpoint: Any,
    value: Any,
) -> tuple[float, tuple[str, float | None, str, float | None] | None]:
    field = str(setpoint or "").strip()
    number = _finite_number(value, field or "set_value")
    bounds = configured_setpoint_bounds(current, field)
    if bounds is None:
        return number, None
    lower_name, lower, upper_name, upper = bounds
    tolerance = 1e-9 * max(
        1.0,
        abs(number),
        abs(lower) if lower is not None else 0.0,
        abs(upper) if upper is not None else 0.0,
    )
    if lower is not None and number < lower - tolerance:
        raise ValueError(f"{field}={_number_text(number)} must not be below {lower_name}={_number_text(lower)}")
    if upper is not None and number > upper + tolerance:
        raise ValueError(f"{field}={_number_text(number)} must not exceed {upper_name}={_number_text(upper)}")
    return number, bounds


def normalize_device_changes(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("At least one device parameter change is required")
    unknown = [field for field in changes if field not in current]
    if unknown:
        raise ValueError(f"Unknown device parameter: {unknown[0]}")
    protected = [field for field in changes if not editable_device_field(field)]
    if protected:
        raise ValueError(f"Device parameter is not editable: {protected[0]}")

    normalized: dict[str, str] = {}
    for field, value in changes.items():
        if _numeric_cell(current.get(field)):
            ratio_field = is_ratio_parameter_field(field)
            number = (
                ratio_parameter_number(field, value)
                if ratio_field
                else _finite_number(value, field)
            )
            normalized_field = str(field).casefold()
            if normalized_field in BINARY_DEVICE_FIELDS and number not in (0.0, 1.0):
                raise ValueError(f"{field} must be 0 or 1")
            if ratio_field and not 0.0 <= number <= 1.0:
                raise ValueError(f"{field} must be between 0 and 1")
            if any(token in normalized_field for token in NONNEGATIVE_DEVICE_FIELD_TOKENS) and number < 0:
                raise ValueError(f"{field} must not be negative")
            normalized[field] = _number_text(number)
        else:
            normalized[field] = str(value).strip()

    merged = {key: str(value) for key, value in current.items()}
    merged.update(normalized)
    for lower, upper in _bound_pairs(tuple(merged)):
        lower_number = (
            ratio_parameter_number(lower, merged[lower], legacy_percent_points=True)
            if is_ratio_parameter_field(lower)
            else _finite_number(merged[lower], lower)
        )
        upper_number = (
            ratio_parameter_number(upper, merged[upper], legacy_percent_points=True)
            if is_ratio_parameter_field(upper)
            else _finite_number(merged[upper], upper)
        )
        if lower_number > upper_number:
            raise ValueError(f"{lower} must not exceed {upper}")
    changed_fields = {_normalized_field_name(field) for field in changes}
    for setpoint in (field for field in merged if str(field).endswith("_set")):
        candidates = _setpoint_bound_candidates(merged, setpoint)
        related_fields = {setpoint, *(field for pair in candidates for field in pair)}
        if not (related_fields & changed_fields):
            continue
        validate_setpoint_safety_bounds(merged, setpoint, merged[setpoint])
    return normalized


def normalize_measurement_changes(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("At least one measurement parameter change is required")
    allowed = {"weight", "error_sigma", "median_deviation", "valid", "status", "fixed_value"}
    unknown = [field for field in changes if field not in allowed]
    if unknown:
        raise ValueError(f"Unknown measurement parameter: {unknown[0]}")

    current_weight = _finite_number(current.get("weight"), "weight")
    weight = _finite_number(changes.get("weight", current_weight), "weight")
    if weight <= 0:
        raise ValueError("weight must be greater than zero")

    sigma_value = changes.get("error_sigma")
    if sigma_value is not None:
        sigma = _finite_number(sigma_value, "error_sigma")
        if sigma <= 0:
            raise ValueError("error_sigma must be greater than zero")
        sigma_weight = 1.0 / (sigma * sigma)
        if "weight" in changes and not math.isclose(weight, sigma_weight, rel_tol=1e-6, abs_tol=1e-12):
            raise ValueError("weight and error_sigma are inconsistent")
        weight = sigma_weight
    else:
        sigma = 1.0 / math.sqrt(weight)

    median_deviation = _finite_number(
        changes.get("median_deviation", current.get("median_deviation", 0.0)),
        "median_deviation",
    )

    current_status = str(current.get("status", "")).strip().casefold()
    if not current_status:
        current_status = "valid" if int(_finite_number(current.get("valid", 1), "valid")) == 1 else "invalid"
    if current_status not in MEASUREMENT_STATUS_TOKENS:
        current_status = "valid" if int(_finite_number(current.get("valid", 1), "valid")) == 1 else "invalid"
    status = str(changes.get("status", current_status)).strip().casefold()
    if status not in MEASUREMENT_STATUS_TOKENS:
        raise ValueError(
            "status must be one of: " + ", ".join(MEASUREMENT_STATUS_TOKENS)
        )

    if "status" not in changes:
        valid_number = _finite_number(changes.get("valid", current.get("valid", 1)), "valid")
        if valid_number not in (0.0, 1.0):
            raise ValueError("valid must be 0 or 1")
        valid = int(valid_number)
        status = "valid" if valid else "invalid"
    else:
        valid = MEASUREMENT_STATUS_VALIDITY[status]

    fixed_value = None
    if status == "fixed":
        raw_fixed_value = changes.get("fixed_value", current.get("fixed_value"))
        if raw_fixed_value in (None, ""):
            raise ValueError("fixed_value is required when status is fixed")
        fixed_value = _finite_number(raw_fixed_value, "fixed_value")
    elif "fixed_value" in changes and changes.get("fixed_value") not in (None, ""):
        raise ValueError("fixed_value is only allowed when status is fixed")
    return {
        "weight": _number_text(weight),
        "valid": str(valid),
        "error_sigma": sigma,
        "median_deviation": median_deviation,
        "status": status,
        "fixed_value": fixed_value,
    }


def require_definition_revision(payload: Mapping[str, Any], current_revision: int) -> None:
    if "revision" not in payload or payload.get("revision") is None:
        return
    revision = _finite_number(payload.get("revision"), "revision")
    if not revision.is_integer() or revision < 0:
        raise ValueError("revision must be a non-negative integer")
    expected_revision = int(revision)
    if expected_revision != current_revision:
        raise DefinitionRevisionConflict(expected_revision, current_revision)


def render_ebook_aligned(book: Any) -> str:
    parts: list[str] = []
    for block in book.data.values():
        header = list(block.header_list)
        widths = [len(name) for name in header]
        for row in block.data:
            for index, name in enumerate(header):
                widths[index] = max(widths[index], len(str(row.get(name, ""))))
        parts.append(f"<{block.name}>\n")
        parts.append(
            "@ "
            + "  ".join(f"{header[index]:<{widths[index]}}" for index in range(len(header))).rstrip()
            + "\n"
        )
        for row in block.data:
            parts.append(
                "# "
                + "  ".join(
                    f"{str(row.get(name, '')):<{widths[index]}}"
                    for index, name in enumerate(header)
                ).rstrip()
                + "\n"
            )
        parts.append(f"</{block.name}>\n")
    return "".join(parts)


def atomic_write_text(path: Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(temp_path, target)
                break
            except OSError as exc:
                transient_windows_denial = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32}
                if not transient_windows_denial or attempt >= 4:
                    raise
                time.sleep(0.05)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise
