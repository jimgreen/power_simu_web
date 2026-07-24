from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


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
            ("idx", "name", "node", "control_type", "p_set", "q_set", "v_set", "alpha", "run_stat"),
            [
                {"idx": 1, "name": "wt01_10kw", "node": 1, "control_type": "V", "p_set": 0, "q_set": 0, "v_set": 300, "alpha": 1.0, "run_stat": 1},
                {"idx": 2, "name": "diesel_300kw", "node": 3, "control_type": "V", "p_set": 80, "q_set": 0, "v_set": 380, "alpha": 1.0, "run_stat": 1},
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
            ("idx", "name", "node", "control_type", "v_set", "p_set", "i_set", "run_stat"),
            [
                {"idx": 1, "name": "dc_bus_vctrl", "node": 1, "control_type": "V", "v_set": 720, "p_set": 0, "i_set": 0, "run_stat": 1},
                {"idx": 2, "name": "pv01_vsrc", "node": 3, "control_type": "V", "v_set": 300, "p_set": 0, "i_set": 0, "run_stat": 1},
                {"idx": 3, "name": "ess01_vsrc", "node": 5, "control_type": "V", "v_set": 300, "p_set": 0, "i_set": 0, "run_stat": 1},
            ],
        ),
        (
            "DCDCConverter",
            ("idx", "name", "i_node", "j_node", "r1", "r2", "control_type", "p_set", "i_set", "v_set", "run_stat"),
            [
                {"idx": 1, "name": "pv01_dcdc", "i_node": 3, "j_node": 4, "r1": 0.005, "r2": 0.005, "control_type": "P", "p_set": 25, "i_set": 0, "v_set": 0, "run_stat": 1},
                {"idx": 2, "name": "ess01_dcdc", "i_node": 5, "j_node": 6, "r1": 0.005, "r2": 0.005, "control_type": "P", "p_set": 10, "i_set": 0, "v_set": 0, "run_stat": 1},
            ],
        ),
        (
            "DCACConverter",
            (
                "idx",
                "name",
                "ac_node",
                "dc_node",
                "r1",
                "r2",
                "control_type",
                "p_ac_set",
                "q_ac_set",
                "v_ac_set",
                "v_dc_set",
                "run_stat",
            ),
            [
                {
                    "idx": 1,
                    "name": "wt01_rect",
                    "ac_node": 2,
                    "dc_node": 2,
                    "r1": 0.005,
                    "r2": 0.005,
                    "control_type": "ACP",
                    "p_ac_set": 8,
                    "q_ac_set": 0,
                    "v_ac_set": 0,
                    "v_dc_set": 0,
                    "run_stat": 1,
                },
                {
                    "idx": 2,
                    "name": "grid_inv_acp",
                    "ac_node": 5,
                    "dc_node": 7,
                    "r1": 0.005,
                    "r2": 0.005,
                    "control_type": "ACP",
                    "p_ac_set": -45,
                    "q_ac_set": 0,
                    "v_ac_set": 0,
                    "v_dc_set": 0,
                    "run_stat": 1,
                },
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
                    "name": "pv01_dcdc",
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
                    "name": "wt01_rect",
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
        {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "set_type": "v_set", "set_value": 300},
        {"dev_type": "DCGenerator", "dev_name": "ess01_vsrc", "set_type": "v_set", "set_value": 300},
        {"dev_type": "DCDCConverter", "dev_name": "pv01_dcdc", "set_type": "p_set", "set_value": 25},
        {"dev_type": "DCDCConverter", "dev_name": "pv01_dcdc", "set_type": "v_set", "set_value": 0},
        {"dev_type": "DCDCConverter", "dev_name": "ess01_dcdc", "set_type": "p_set", "set_value": 10},
        {"dev_type": "DCDCConverter", "dev_name": "ess01_dcdc", "set_type": "v_set", "set_value": 0},
        {"dev_type": "DCACConverter", "dev_name": "wt01_rect", "set_type": "p_set", "set_value": 8},
        {"dev_type": "DCACConverter", "dev_name": "wt01_rect", "set_type": "q_set", "set_value": 0},
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

    def add(name: str, dev_type: str, dev_name: str, meas_type: str, weight: float = 25.0, value: float = 0.0) -> None:
        rows.append(
            {
                "idx": len(rows),
                "name": name,
                "dev_type": dev_type,
                "dev_name": dev_name,
                "meas_type": meas_type,
                "weight": f"{weight:.4f}",
                "valid": 1,
                "value": value,
            }
        )

    for node in ("wt01_src", "wt01_rect", "diesel_node", "ac_bus", "grid_inv_ac", "load_ac_1_node"):
        add(f"v_{node}", "ACNode", node, "V", value=300 if node.startswith("wt") else 380)
    for node in ("dc_bus_720v", "wt01_dc", "pv01_300v", "pv01_720v", "ess01_300v", "ess01_720v", "grid_inv_dc"):
        add(f"v_{node}", "DCNode", node, "V", value=300 if "300v" in node else 720)
    for gen in ("wt01_10kw", "diesel_300kw"):
        for meas_type in ("P_GEN", "Q_GEN", "V_GEN", "I_GEN"):
            add(f"{meas_type.lower()}_{gen}", "ACGenerator", gen, meas_type)
    for meas_type in ("P_LOAD", "Q_LOAD", "V_LOAD", "I_LOAD"):
        add(f"{meas_type.lower()}_load_ac_1", "ACLoad", "load_ac_1", meas_type)
    for conv in ("pv01_dcdc", "ess01_dcdc"):
        for meas_type in ("P_FROM", "V_FROM", "I_FROM", "P_TO", "V_TO", "I_TO"):
            add(f"{meas_type.lower()}_{conv}", "DCDCConverter", conv, meas_type)
    for conv in ("wt01_rect", "grid_inv_acp"):
        for meas_type in ("P_DC", "V_DC", "I_DC", "P_AC", "Q_AC", "V_AC", "I_AC"):
            add(f"{meas_type.lower()}_{conv}", "DCACConverter", conv, meas_type)
    for meas_type in ("P", "Q", "V", "I", "SOC"):
        add(
            f"{meas_type.lower()}_ess01",
            "ESS",
            "ess01",
            meas_type,
            weight=10000.0 if meas_type == "SOC" else 25.0,
            value=0.55 if meas_type == "SOC" else 0.0,
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


def write_model_dir(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    write_efile(target_dir / "model.e", model_blocks())
    write_efile(target_dir / "meas.e", measurement_blocks())
    write_efile(target_dir / "real.e", measurement_blocks())
    write_efile(target_dir / "scada.e", measurement_blocks())
    write_efile(target_dir / "stat.e", stat_blocks())
    write_efile(target_dir / "weather.e", weather_blocks())
    write_efile(target_dir / "device.e", device_blocks())
    write_efile(target_dir / "yt_ctrl.e", empty_control_blocks())
    (target_dir / "commands.json").write_text("[]\n", encoding="utf-8")
    (target_dir / "local_settings.json").write_text(
        json.dumps({"device_faults": [], "measurement_faults": [], "modes": []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target_dir / "curves.json").write_text(json.dumps(curves_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    source_dir, runtime_dir = TARGET_DIRS
    write_model_dir(source_dir)
    if runtime_dir.exists():
        for path in runtime_dir.iterdir():
            if path.name == ".simu_loop_work":
                if path.resolve().is_relative_to(runtime_dir.resolve()):
                    shutil.rmtree(path)
                continue
            if path.is_file():
                path.unlink()
    write_model_dir(runtime_dir)
    print(f"generated: {source_dir}")
    print(f"generated: {runtime_dir}")


if __name__ == "__main__":
    main()
