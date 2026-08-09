from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from .point_names import automatic_point_name
except ImportError:  # pragma: no cover - direct script execution.
    from point_names import automatic_point_name


ROOT = Path(__file__).resolve().parents[1]
SIMPLE_MODEL_NAME = "\u7b80\u5355\u6a21\u578b"
TARGET_DIRS = (
    ROOT / "models" / "simulator" / "source" / SIMPLE_MODEL_NAME,
    ROOT / "models" / "simulator" / "runtime" / SIMPLE_MODEL_NAME,
)


Block = tuple[str, Sequence[str], Sequence[Mapping[str, Any]]]


def _format_cell(value: Any) -> str:
    if isinstance(value, float):
        if abs(value) < 5e-13:
            value = 0.0
        text = f"{value:.10g}"
        return "0" if text == "-0" else text
    return str(value)


def aligned_efile_text(blocks: Iterable[Block]) -> str:
    parts: list[str] = []
    for name, header, rows in blocks:
        widths = [len(column) for column in header]
        for row in rows:
            for idx, column in enumerate(header):
                widths[idx] = max(widths[idx], len(_format_cell(row.get(column, ""))))
        parts.append(f"<{name}>\n")
        parts.append("@ " + "  ".join(f"{header[idx]:<{widths[idx]}}" for idx in range(len(header))).rstrip() + "\n")
        for row in rows:
            parts.append(
                "# "
                + "  ".join(
                    f"{_format_cell(row.get(column, '')):<{widths[idx]}}" for idx, column in enumerate(header)
                ).rstrip()
                + "\n"
            )
        parts.append(f"</{name}>\n")
    return "".join(parts)


def write_efile(path: Path, blocks: Iterable[Block]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(aligned_efile_text(blocks), encoding="utf-8")


def model_blocks() -> list[Block]:
    return [
        (
            "PowerBase",
            ("p_base", "u_scale", "p_scale", "i_scale"),
            [{"p_base": 100, "u_scale": 1000.0, "p_scale": 1.0, "i_scale": 1000.0}],
        ),
        (
            "ACNode",
            ("idx", "name", "vbase", "voltage", "angle", "isl", "run_stat"),
            [
                {"idx": 1, "name": "wt01_src", "vbase": 300, "voltage": 300, "angle": 0, "isl": 0, "run_stat": 1},
                {"idx": 2, "name": "wt01_rect", "vbase": 300, "voltage": 300, "angle": 0, "isl": 0, "run_stat": 1},
                {"idx": 3, "name": "diesel_node", "vbase": 380, "voltage": 380, "angle": 0, "isl": 0, "run_stat": 1},
                {"idx": 4, "name": "ac_bus", "vbase": 380, "voltage": 380, "angle": 0, "isl": 0, "run_stat": 1},
                {"idx": 5, "name": "grid_inv_ac", "vbase": 380, "voltage": 380, "angle": 0, "isl": 0, "run_stat": 1},
                {
                    "idx": 6,
                    "name": "load_ac_1_node",
                    "vbase": 380,
                    "voltage": 380,
                    "angle": 0,
                    "isl": 0,
                    "run_stat": 1,
                },
            ],
        ),
        (
            "ACRealBs",
            ("idx", "name", "node", "run_stat", "v_max", "v_min"),
            [
                {"idx": 1, "name": "main_ac_bus", "node": 4, "run_stat": 1, "v_max": 1.1, "v_min": 0.9},
            ],
        ),
        (
            "ACBranch",
            ("idx", "name", "i_node", "j_node", "r", "x", "b", "run_stat"),
            [
                {"idx": 1, "name": "wt01_cable", "i_node": 1, "j_node": 2, "r": 0.005, "x": 0.03, "b": 0.0, "run_stat": 1},
                {"idx": 2, "name": "diesel_line", "i_node": 3, "j_node": 4, "r": 0.001, "x": 0.005, "b": 0.0, "run_stat": 1},
                {"idx": 3, "name": "inv_ac_line", "i_node": 5, "j_node": 4, "r": 0.001, "x": 0.005, "b": 0.0, "run_stat": 1},
                {"idx": 4, "name": "load1_line", "i_node": 6, "j_node": 4, "r": 0.001, "x": 0.005, "b": 0.0, "run_stat": 1},
            ],
        ),
        (
            "ACLoad",
            ("idx", "name", "node", "pbase", "pv0", "pv1", "pv2", "qbase", "qv0", "qv1", "qv2", "run_stat"),
            [
                {
                    "idx": 1,
                    "name": "load_ac_1",
                    "node": 6,
                    "pbase": 1.0,
                    "pv0": 90,
                    "pv1": 0,
                    "pv2": 0,
                    "qbase": 1.0,
                    "qv0": 30,
                    "qv1": 0,
                    "qv2": 0,
                    "run_stat": 1,
                }
            ],
        ),
        (
            "ACGenerator",
            (
                "idx",
                "name",
                "dev_type",
                "node",
                "control_type",
                "p_set",
                "q_set",
                "v_set",
                "alpha",
                "p_min",
                "p_max",
                "rated_capacity",
                "run_stat",
            ),
            [
                {"idx": 1, "name": "wt01_10kw", "dev_type": "ac-wind-source", "node": 1, "control_type": "P", "p_set": 0, "q_set": 0, "v_set": 300, "alpha": 1.0, "p_min": 0, "p_max": 10, "rated_capacity": 10, "run_stat": 1},
                {"idx": 2, "name": "diesel_300kw", "dev_type": "ac-diesel-source", "node": 3, "control_type": "V", "p_set": 80, "q_set": 0, "v_set": 380, "alpha": 1.0, "p_min": 30, "p_max": 300, "rated_capacity": 300, "run_stat": 1},
            ],
        ),
        (
            "DCNode",
            ("idx", "name", "vbase", "voltage", "isl", "run_stat"),
            [
                {"idx": 1, "name": "dc_bus_720v", "vbase": 720, "voltage": 720, "isl": 0, "run_stat": 1},
                {"idx": 2, "name": "wt01_dc", "vbase": 720, "voltage": 720, "isl": 0, "run_stat": 1},
                {"idx": 3, "name": "pv01_300v", "vbase": 300, "voltage": 300, "isl": 0, "run_stat": 1},
                {"idx": 4, "name": "pv01_720v", "vbase": 720, "voltage": 720, "isl": 0, "run_stat": 1},
                {"idx": 5, "name": "ess01_300v", "vbase": 300, "voltage": 300, "isl": 0, "run_stat": 1},
                {"idx": 6, "name": "ess01_720v", "vbase": 720, "voltage": 720, "isl": 0, "run_stat": 1},
                {"idx": 7, "name": "grid_inv_dc", "vbase": 720, "voltage": 720, "isl": 0, "run_stat": 1},
            ],
        ),
        (
            "DCRealBs",
            ("idx", "name", "node", "run_stat", "v_max", "v_min"),
            [
                {"idx": 1, "name": "main_dc_bus", "node": 1, "run_stat": 1, "v_max": 1.1, "v_min": 0.9},
            ],
        ),
        (
            "DCBranch",
            ("idx", "name", "i_node", "j_node", "r", "run_stat"),
            [
                {"idx": 1, "name": "wt01_dc_line", "i_node": 2, "j_node": 1, "r": 0.001, "run_stat": 1},
                {"idx": 2, "name": "pv01_dc_line", "i_node": 4, "j_node": 1, "r": 0.001, "run_stat": 1},
                {"idx": 3, "name": "ess01_dc_line", "i_node": 6, "j_node": 1, "r": 0.001, "run_stat": 1},
                {"idx": 4, "name": "inv_dc_line", "i_node": 7, "j_node": 1, "r": 0.001, "run_stat": 1},
            ],
        ),
        (
            "DCGenerator",
            ("idx", "name", "dev_type", "node", "control_type", "v_set", "p_set", "i_set", "p_min", "p_max", "rated_capacity", "run_stat"),
            [
                {"idx": 1, "name": "dc_bus_vctrl", "dev_type": "dc-voltage-source", "node": 1, "control_type": "V", "v_set": 720, "p_set": 0, "i_set": 0, "p_min": -300, "p_max": 300, "rated_capacity": 300, "run_stat": 1},
                {"idx": 2, "name": "pv01_vsrc", "dev_type": "dc-pv-source", "node": 3, "control_type": "P", "v_set": 300, "p_set": 0, "i_set": 0, "p_min": 0, "p_max": 50, "rated_capacity": 50, "run_stat": 1},
                {"idx": 3, "name": "ess01_vsrc", "dev_type": "dc-storage", "node": 5, "control_type": "P", "v_set": 300, "p_set": 0, "i_set": 0, "p_min": -40, "p_max": 40, "rated_capacity": 40, "run_stat": 1},
            ],
        ),
        (
            "DCDCConverter",
            ("idx", "name", "i_node", "j_node", "r1", "r2", "control_type", "p_set", "i_set", "v_set", "run_stat"),
            [
                {"idx": 1, "name": "pv01_dcdc", "i_node": 3, "j_node": 4, "r1": 0.005, "r2": 0.005, "control_type": "V", "p_set": 0, "i_set": 0, "v_set": 300, "run_stat": 1},
                {"idx": 2, "name": "ess01_dcdc", "i_node": 5, "j_node": 6, "r1": 0.005, "r2": 0.005, "control_type": "V", "p_set": 0, "i_set": 0, "v_set": 300, "run_stat": 1},
            ],
        ),
        (
            "DCACConverter",
            (
                "idx",
                "name",
                "dev_type",
                "ac_node",
                "dc_node",
                "r1",
                "r2",
                "control_type",
                "p_ac_set",
                "p_ac_min",
                "p_ac_max",
                "q_ac_set",
                "v_ac_set",
                "v_dc_set",
                "run_stat",
            ),
            [
                {
                    "idx": 1,
                    "name": "wt01_rect",
                    "dev_type": "wind-acdc-converter",
                    "ac_node": 2,
                    "dc_node": 2,
                    "r1": 0.005,
                    "r2": 0.005,
                    "control_type": "ACV",
                    "p_ac_set": 0,
                    "p_ac_min": 0,
                    "p_ac_max": 10,
                    "q_ac_set": 0,
                    "v_ac_set": 300,
                    "v_dc_set": 0,
                    "run_stat": 1,
                },
                {
                    "idx": 2,
                    "name": "grid_inv_acp",
                    "dev_type": "grid-acdc-converter",
                    "ac_node": 5,
                    "dc_node": 7,
                    "r1": 0.005,
                    "r2": 0.005,
                    "control_type": "ACP",
                    "p_ac_set": -45,
                    "p_ac_min": -50,
                    "p_ac_max": 50,
                    "q_ac_set": 0,
                    "v_ac_set": 0,
                    "v_dc_set": 0,
                    "run_stat": 1,
                },
            ],
        ),
        (
            "ACWindGen",
            ("idx", "idx_acgenerator", "wind_turbine_model", "cut_in_wind_speed", "rated_wind_speed", "cut_out_wind_speed", "rated_power", "rotor_diameter", "hub_height"),
            [
                {
                    "idx": 1,
                    "idx_acgenerator": 1,
                    "wind_turbine_model": "WT-10kW",
                    "cut_in_wind_speed": 5.0,
                    "rated_wind_speed": 15.0,
                    "cut_out_wind_speed": 50.0,
                    "rated_power": 10.0,
                    "rotor_diameter": 6.0,
                    "hub_height": 10.0,
                }
            ],
        ),
        (
            "ACDieselGen",
            ("idx", "idx_acgenerator", "rated_power", "p_min", "p_max"),
            [
                {
                    "idx": 1,
                    "idx_acgenerator": 2,
                    "rated_power": 300.0,
                    "p_min": 30.0,
                    "p_max": 300.0,
                }
            ],
        ),
        (
            "DCPVGen",
            ("idx", "idx_dcgenerator", "pv_module_model", "module_efficiency", "array_area", "mppt_count", "rated_power"),
            [
                {
                    "idx": 1,
                    "idx_dcgenerator": 2,
                    "pv_module_model": "Mono-550W",
                    "module_efficiency": 0.2,
                    "array_area": "250_m2",
                    "mppt_count": 1,
                    "rated_power": 50.0,
                }
            ],
        ),
        (
            "DCStorageGen",
            (
                "idx",
                "idx_dcgenerator",
                "storage_technology",
                "battery_rack_count",
                "energy_capacity",
                "charge_discharge_efficiency",
                "max_charge_power",
                "max_discharge_power",
                "state_of_charge",
                "soc_upper_limit",
                "soc_lower_limit",
            ),
            [
                {
                    "idx": 1,
                    "idx_dcgenerator": 3,
                    "storage_technology": "lithium",
                    "battery_rack_count": 1,
                    "energy_capacity": 100.0,
                    "charge_discharge_efficiency": 0.95,
                    "max_charge_power": 40.0,
                    "max_discharge_power": 40.0,
                    "state_of_charge": 0.55,
                    "soc_upper_limit": 0.9,
                    "soc_lower_limit": 0.2,
                }
            ],
        ),
    ]


def device_blocks() -> list[Block]:
    profile: dict[str, Any] = {"id": 1, "name": "load_ac_1"}
    for idx in range(1, 97):
        hour = (idx - 1) / 4.0
        if hour < 6:
            scale = 0.72
        elif hour < 9:
            scale = 0.85
        elif hour < 17:
            scale = 0.95
        elif hour < 22:
            scale = 1.08
        else:
            scale = 0.82
        profile[f"p{idx:03d}"] = f"{scale:.3f}"
    load_header = ("id", "name", *[f"p{idx:03d}" for idx in range(1, 97)])
    return [
        (
            "pv_generator",
            ("id", "name", "p_max", "p_min", "p_fur", "rated_power", "temp_coefficient", "reference_irradiance", "reference_temperature"),
            [
                {
                    "id": 1,
                    "name": "pv01_vsrc",
                    "p_max": 50,
                    "p_min": 0,
                    "p_fur": 0.0,
                    "rated_power": 50,
                    "temp_coefficient": -0.004,
                    "reference_irradiance": 1000.0,
                    "reference_temperature": 25.0,
                }
            ],
        ),
        (
            "wind_generator",
            ("id", "name", "p_max", "p_min", "p_fur", "rated_power", "rated_wind_speed", "cut_in_speed", "cut_out_speed"),
            [
                {
                    "id": 1,
                    "name": "wt01_10kw",
                    "p_max": 10,
                    "p_min": 0,
                    "p_fur": 0.0,
                    "rated_power": 10,
                    "rated_wind_speed": 15.0,
                    "cut_in_speed": 5.0,
                    "cut_out_speed": 50.0,
                }
            ],
        ),
        ("diesel_generator", ("id", "name", "p_max", "p_min"), [{"id": 1, "name": "diesel_300kw", "p_max": 300, "p_min": 30}]),
        ("load_curve_96", load_header, [profile]),
        ("load_temperature", ("id", "name", "temp_base", "temp_factor"), [{"id": 1, "name": "load_ac_1", "temp_base": 5.0, "temp_factor": -0.005}]),
        (
            "estorage",
            ("id", "name", "emva", "soc_max", "soc_min", "soc_cur", "charge_p_max", "dis_charge_p_max"),
            [
                {
                    "id": 1,
                    "name": "ess01",
                    "emva": 100.0,
                    "soc_max": 0.9,
                    "soc_min": 0.2,
                    "soc_cur": 0.55,
                    "charge_p_max": 40.0,
                    "dis_charge_p_max": 40.0,
                }
            ],
        ),
    ]


def stat_blocks() -> list[Block]:
    run_rows: list[dict[str, Any]] = []
    for block_name, header, rows in model_blocks():
        if "run_stat" not in header:
            continue
        for row in rows:
            run_rows.append({"dev_type": block_name, "dev_name": row["name"], "run_stat": row.get("run_stat", 1)})
    run_rows.append({"dev_type": "ESS", "dev_name": "ess01", "run_stat": 1})
    set_rows = [
        {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "set_type": "p_set", "set_value": 0},
        {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "set_type": "q_set", "set_value": 0},
        {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "set_type": "v_set", "set_value": 300},
        {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "set_type": "p_set", "set_value": 80},
        {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "set_type": "q_set", "set_value": 0},
        {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "set_type": "v_set", "set_value": 380},
        {"dev_type": "DCGenerator", "dev_name": "dc_bus_vctrl", "set_type": "v_set", "set_value": 720},
        {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "set_type": "p_set", "set_value": 25},
        {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "set_type": "v_set", "set_value": 300},
        {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 10},
        {"dev_type": "ESS", "dev_name": "ess01", "set_type": "v_set", "set_value": 300},
        {"dev_type": "DCDCConverter", "dev_name": "pv01_dcdc", "set_type": "v_set", "set_value": 300},
        {"dev_type": "DCDCConverter", "dev_name": "ess01_dcdc", "set_type": "v_set", "set_value": 300},
        {"dev_type": "DCACConverter", "dev_name": "wt01_rect", "set_type": "v_set", "set_value": 300},
        {"dev_type": "DCACConverter", "dev_name": "grid_inv_acp", "set_type": "p_set", "set_value": -45},
        {"dev_type": "DCACConverter", "dev_name": "grid_inv_acp", "set_type": "q_set", "set_value": 0},
        {"dev_type": "ACLoad", "dev_name": "load_ac_1", "set_type": "p_set", "set_value": 90},
        {"dev_type": "ACLoad", "dev_name": "load_ac_1", "set_type": "q_set", "set_value": 30},
    ]
    return [
        ("RunStat", ("dev_type", "dev_name", "run_stat"), run_rows),
        ("SetValue", ("dev_type", "dev_name", "set_type", "set_value"), set_rows),
        ("StorageSoc", ("dev_type", "idx", "name", "soc_curr"), [{"dev_type": "ESS", "idx": 1, "name": "ess01", "soc_curr": 0.55}]),
    ]


def measurement_blocks() -> list[Block]:
    rows: list[dict[str, Any]] = []

    def add(dev_type: str, dev_name: str, meas_type: str, weight: float = 25.0, value: float = 0.0) -> None:
        rows.append(
            {
                "idx": len(rows),
                "name": automatic_point_name(dev_type, dev_name, meas_type),
                "dev_type": dev_type,
                "dev_name": dev_name,
                "meas_type": meas_type,
                "weight": f"{weight:.4f}",
                "valid": 1,
                "value": value,
            }
        )

    for node, voltage in (
        ("wt01_src", 300),
        ("wt01_rect", 300),
        ("diesel_node", 380),
        ("ac_bus", 380),
        ("grid_inv_ac", 380),
        ("load_ac_1_node", 380),
    ):
        add("ACNode", node, "V", value=voltage)
    for node, voltage in (
        ("dc_bus_720v", 720),
        ("wt01_dc", 720),
        ("pv01_300v", 300),
        ("pv01_720v", 720),
        ("ess01_300v", 300),
        ("ess01_720v", 720),
        ("grid_inv_dc", 720),
    ):
        add("DCNode", node, "V", value=voltage)
    for gen in ("wt01_10kw", "diesel_300kw"):
        for meas_type in ("P_GEN", "Q_GEN", "V_GEN", "I_GEN"):
            add("ACGenerator", gen, meas_type)
    for gen in ("dc_bus_vctrl", "pv01_vsrc", "ess01_vsrc"):
        for meas_type in ("P_GEN", "V_GEN", "I_GEN"):
            add("DCGenerator", gen, meas_type)
    for meas_type in ("P_LOAD", "Q_LOAD", "V_LOAD", "I_LOAD"):
        add("ACLoad", "load_ac_1", meas_type)
    for conv in ("pv01_dcdc", "ess01_dcdc"):
        for meas_type in ("P_FROM", "V_FROM", "I_FROM", "P_TO", "V_TO", "I_TO"):
            add("DCDCConverter", conv, meas_type)
    for conv in ("wt01_rect", "grid_inv_acp"):
        for meas_type in ("P_DC", "V_DC", "I_DC", "P_AC", "Q_AC", "V_AC", "I_AC"):
            add("DCACConverter", conv, meas_type)
    for meas_type in ("P", "Q", "V", "I", "SOC"):
        add(
            "ESS",
            "ess01",
            meas_type,
            weight=10000.0 if meas_type == "SOC" else 25.0,
            value=0.55 if meas_type == "SOC" else 0.0,
        )
    for meas_type, value in (
        ("WIND_SPEED", 18.0),
        ("AIR_TEMP", -20.0),
        ("HUMIDITY", 72.0),
        ("AIR_PRESSURE", 960.0),
        ("SOLAR_IRRADIANCE", 0.0),
    ):
        add("Environment", "weather", meas_type, weight=1.0, value=value)
    for block_name, _header, stat_rows in stat_blocks():
        if block_name == "RunStat":
            for row in stat_rows:
                add(
                    row["dev_type"],
                    row["dev_name"],
                    "RUN_STAT",
                    weight=1.0,
                    value=row.get("run_stat", 1),
                )
        elif block_name == "CbOpenStat":
            for row in stat_rows:
                add(
                    row["dev_type"],
                    row["dev_name"],
                    "STATUS",
                    weight=1.0,
                    value=row.get("status", 1),
                )
    return [("Measurement", ("idx", "name", "dev_type", "dev_name", "meas_type", "weight", "valid", "value"), rows)]


def weather_blocks() -> list[Block]:
    return [
        (
            "Weather",
            ("time", "wind_speed_mps", "air_temp_c", "air_pressure_hpa", "solar_irradiance_w_m2", "humidity_pct", "load_kw"),
            [
                {
                    "time": "00:00:00",
                    "wind_speed_mps": 18.0,
                    "air_temp_c": -20.0,
                    "air_pressure_hpa": 960.0,
                    "solar_irradiance_w_m2": 0.0,
                    "humidity_pct": 72.0,
                    "load_kw": 90.0,
                }
            ],
        )
    ]


def empty_control_blocks() -> list[Block]:
    return [("SetValue", ("dev_type", "dev_name", "set_type", "set_value"), [])]


def curves_payload() -> dict[str, Any]:
    weather: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    for minute in range(1440):
        day_angle = 2.0 * math.pi * minute / 1440.0
        solar_shape = max(0.0, math.sin(math.pi * (minute - 360) / 720.0))
        wind = max(0.0, min(50.0, 18.0 + 6.0 * math.sin(day_angle - 0.8) + 2.5 * math.sin(5.0 * day_angle)))
        temp = -22.0 + 6.0 * math.sin(day_angle - math.pi / 2.0)
        load = 90.0 + 12.0 * math.sin(day_angle - 1.2) + (18.0 if 1020 <= minute <= 1320 else 0.0)
        weather.append(
            {
                "minute": float(minute),
                "wind_speed_mps": round(wind, 3),
                "air_temp_c": round(temp, 3),
                "air_pressure_hpa": round(960.0 + 3.0 * math.sin(day_angle + 0.5), 3),
                "solar_irradiance_w_m2": round(650.0 * solar_shape, 3),
                "humidity_pct": round(72.0 + 8.0 * math.sin(day_angle + 1.0), 3),
            }
        )
        loads.append({"minute": float(minute), "p_kw": round(max(60.0, load), 3)})
    return {
        "mode": "day",
        "time_step_minutes": 1,
        "point_count": 1440,
        "weather": weather,
        "loads": {"load_ac_1": loads},
    }


def curve_definition_blocks(curves: Mapping[str, Any]) -> list[Block]:
    weather_rows = [
        {
            "idx": idx,
            "minute": point.get("minute", idx - 1),
            "wind_speed_mps": point.get("wind_speed_mps", ""),
            "air_temp_c": point.get("air_temp_c", ""),
            "air_pressure_hpa": point.get("air_pressure_hpa", ""),
            "solar_irradiance_w_m2": point.get("solar_irradiance_w_m2", ""),
            "humidity_pct": point.get("humidity_pct", ""),
        }
        for idx, point in enumerate(curves.get("weather", []), start=1)
        if isinstance(point, Mapping)
    ]
    load_rows: list[dict[str, Any]] = []
    loads = curves.get("loads", {})
    if isinstance(loads, Mapping):
        for load_name, points in loads.items():
            if not isinstance(points, list):
                continue
            for idx, point in enumerate(points, start=1):
                if isinstance(point, Mapping):
                    load_rows.append(
                        {
                            "idx": idx,
                            "load_name": load_name,
                            "minute": point.get("minute", idx - 1),
                            "p_kw": point.get("p_kw", ""),
                        }
                    )
    return [
        (
            "CurveInfo",
            ("mode", "time_step_minutes", "point_count"),
            [
                {
                    "mode": curves.get("mode", "day"),
                    "time_step_minutes": curves.get("time_step_minutes", 1),
                    "point_count": curves.get("point_count", len(weather_rows)),
                }
            ],
        ),
        (
            "EnvironmentCurve",
            (
                "idx",
                "minute",
                "wind_speed_mps",
                "air_temp_c",
                "air_pressure_hpa",
                "solar_irradiance_w_m2",
                "humidity_pct",
            ),
            weather_rows,
        ),
        ("LoadCurve", ("idx", "load_name", "minute", "p_kw"), load_rows),
    ]


def write_model_dir(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    write_efile(target_dir / "model.e", model_blocks())
    write_efile(target_dir / "meas.e", measurement_blocks())
    write_efile(target_dir / "stat.e", stat_blocks())
    write_efile(target_dir / "control.e", stat_blocks())
    write_efile(target_dir / "weather.e", weather_blocks())
    legacy_device = target_dir / "device.e"
    if legacy_device.exists() and legacy_device.is_file():
        legacy_device.unlink()
    curves = curves_payload()
    (target_dir / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_efile(target_dir / "curves.e", curve_definition_blocks(curves))


def main() -> None:
    source_dir, runtime_dir = TARGET_DIRS
    write_model_dir(source_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if runtime_dir.exists():
        for path in runtime_dir.iterdir():
            if path.name == ".simu_loop_work":
                if path.resolve().is_relative_to(runtime_dir.resolve()):
                    shutil.rmtree(path)
                continue
            if path.is_file() and path.name in {
                "model.e",
                "meas.e",
                "control.e",
                "stat.e",
                "weather.e",
                "device.e",
                "curves.e",
            }:
                path.unlink()
    print(f"generated: {source_dir}")
    print(f"prepared runtime: {runtime_dir}")


if __name__ == "__main__":
    main()
