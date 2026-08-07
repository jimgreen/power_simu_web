from __future__ import annotations

import math
import os
import tempfile
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
    "run_stat",
    "status",
    "isl",
    "p_set",
    "q_set",
    "v_set",
    "i_set",
    "p_ac_set",
    "q_ac_set",
    "v_ac_set",
    "v_dc_set",
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
            number = _finite_number(value, field)
            normalized_field = str(field).casefold()
            if any(token in normalized_field for token in NONNEGATIVE_DEVICE_FIELD_TOKENS) and number < 0:
                raise ValueError(f"{field} must not be negative")
            suffix = "%" if str(current.get(field, "")).strip().endswith("%") else ""
            normalized[field] = f"{_number_text(number)}{suffix}"
        else:
            normalized[field] = str(value).strip()

    merged = {key: str(value) for key, value in current.items()}
    merged.update(normalized)
    for lower, upper in _bound_pairs(tuple(merged)):
        if _finite_number(merged[lower], lower) > _finite_number(merged[upper], upper):
            raise ValueError(f"{lower} must not exceed {upper}")
    return normalized


def normalize_measurement_changes(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("At least one measurement parameter change is required")
    allowed = {"weight", "error_sigma", "valid", "status", "fixed_value"}
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
        os.replace(temp_path, target)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise
