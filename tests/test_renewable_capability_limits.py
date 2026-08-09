from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


MEAS_TEXT = """<Measurement>
@ idx  name  dev_type  dev_name  meas_type  weight  valid  value
</Measurement>
"""


def _efile_block(name: str, header: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    parts = [f"<{name}>\n", "@ " + "  ".join(header) + "\n"]
    for row in rows:
        parts.append("# " + "  ".join(str(row.get(column, "")) for column in header) + "\n")
    parts.append(f"</{name}>\n")
    return "".join(parts)


class RenewableCapabilityLimitTest(unittest.TestCase):
    def test_weather_load_kw_with_zero_load_base_reaches_solver_model(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        weather_file = root / "weather.e"
        yt_ctrl_file = root / "yt_ctrl.e"
        meas_file = root / "meas.e"

        model_file.write_text(
            _efile_block(
                "ACLoad",
                ("idx", "name", "node", "pbase", "pv0", "pv1", "pv2", "qbase", "qv0", "qv1", "qv2", "run_stat"),
                [
                    {
                        "idx": 1,
                        "name": "load_alpha",
                        "node": 1,
                        "pbase": 0,
                        "pv0": 1.0,
                        "pv1": 0,
                        "pv2": 0,
                        "qbase": 0,
                        "qv0": 1.0,
                        "qv1": 0,
                        "qv2": 0,
                        "run_stat": 1,
                    }
                ],
            )
            + _efile_block(
                "ACGenerator",
                ("idx", "name", "dev_type", "node", "control_type", "p_set", "q_set", "v_set", "run_stat"),
                [
                    {
                        "idx": 1,
                        "name": "wind_alpha",
                        "dev_type": "ac-wind-source",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 0,
                        "q_set": 0,
                        "v_set": 300,
                        "run_stat": 1,
                    }
                ],
            )
            + _efile_block(
                "ACWindGen",
                (
                    "idx",
                    "idx_acgenerator",
                    "wind_turbine_model",
                    "cut_in_wind_speed",
                    "rated_wind_speed",
                    "cut_out_wind_speed",
                    "rated_power",
                ),
                [
                    {
                        "idx": 1,
                        "idx_acgenerator": 1,
                        "wind_turbine_model": "WT-10kW",
                        "cut_in_wind_speed": 5,
                        "rated_wind_speed": 15,
                        "cut_out_wind_speed": 50,
                        "rated_power": 10,
                    }
                ],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(_efile_block("SetValue", ("dev_type", "dev_name", "set_type", "set_value"), []), encoding="utf-8")
        yt_ctrl_file.write_text(_efile_block("SetValue", ("dev_type", "dev_name", "set_type", "set_value"), []), encoding="utf-8")
        weather_file.write_text(
            _efile_block(
                "Weather",
                ("time", "wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c", "load_kw"),
                [{"time": "00:00:00", "wind_speed_mps": 10, "solar_irradiance_w_m2": 0, "air_temp_c": 25, "load_kw": 120}],
            ),
            encoding="utf-8",
        )
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        seen: dict[str, float] = {}

        def fake_solver(merged_model: Path):
            book = simu_loop.EBook(merged_model)
            row = book.data["ACLoad"].data[0]
            pbase = float(row["pbase"])
            pv0 = float(row["pv0"])
            seen["pbase"] = pbase
            seen["pv0"] = pv0
            seen["kernel_load_kw"] = pbase * pv0
            seen["kernel_load_kvar"] = float(row["qbase"]) * float(row["qv0"])
            return object(), "fake-solver"

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=weather_file,
            dev_stat_file=stat_file,
            yt_ctrl_file=yt_ctrl_file,
            dev_define_file=None,
            real_file=root / "real.e",
            scada_file=root / "scada.e",
            period_seconds=60.0,
        )
        simu_loop.run_once(config, solver=fake_solver)

        self.assertAlmostEqual(seen["kernel_load_kw"], 120.0)
        self.assertAlmostEqual(seen["kernel_load_kvar"], 0.0)
        self.assertNotEqual(seen["pbase"], 0.0)

    def test_limits_wind_and_pv_from_model_embedded_device_blocks_without_device_file(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        weather_file = root / "weather.e"
        yt_ctrl_file = root / "yt_ctrl.e"
        meas_file = root / "meas.e"

        model_file.write_text(
            _efile_block(
                "ACGenerator",
                ("idx", "name", "dev_type", "node", "control_type", "p_set", "q_set", "v_set", "run_stat"),
                [
                    {
                        "idx": 1,
                        "name": "wind_alpha",
                        "dev_type": "ac-wind-source",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 0,
                        "q_set": 0,
                        "v_set": 300,
                        "run_stat": 1,
                    }
                ],
            )
            + _efile_block(
                "ACWindGen",
                (
                    "idx",
                    "idx_acgenerator",
                    "wind_turbine_model",
                    "cut_in_wind_speed",
                    "rated_wind_speed",
                    "cut_out_wind_speed",
                    "rated_power",
                ),
                [
                    {
                        "idx": 1,
                        "idx_acgenerator": 1,
                        "wind_turbine_model": "WT-10kW",
                        "cut_in_wind_speed": 5,
                        "rated_wind_speed": 15,
                        "cut_out_wind_speed": 50,
                        "rated_power": 10,
                    }
                ],
            )
            + _efile_block(
                "DCGenerator",
                ("idx", "name", "dev_type", "node", "control_type", "p_set", "v_set", "i_set", "run_stat"),
                [
                    {
                        "idx": 1,
                        "name": "solar_alpha",
                        "dev_type": "dc-pv-source",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 0,
                        "v_set": 300,
                        "i_set": 0,
                        "run_stat": 1,
                    }
                ],
            )
            + _efile_block(
                "DCPVGen",
                ("idx", "idx_dcgenerator", "pv_module_model", "module_efficiency", "array_area", "mppt_count"),
                [{"idx": 1, "idx_dcgenerator": 1, "pv_module_model": "PV", "module_efficiency": "20%", "array_area": "250_m2", "mppt_count": 1}],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [],
            ),
            encoding="utf-8",
        )
        yt_ctrl_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [],
            ),
            encoding="utf-8",
        )
        weather_file.write_text(
            _efile_block(
                "Weather",
                ("time", "wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c", "load_kw"),
                [{"time": "00:00:00", "wind_speed_mps": 10, "solar_irradiance_w_m2": 500, "air_temp_c": 25, "load_kw": 0}],
            ),
            encoding="utf-8",
        )
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        seen: dict[str, float] = {}

        def fake_solver(merged_model: Path):
            book = simu_loop.EBook(merged_model)
            seen["wind"] = float(book.data["ACGenerator"].data[0]["p_set"])
            seen["pv"] = float(book.data["DCGenerator"].data[0]["p_set"])
            return object(), "fake-solver"

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=weather_file,
            dev_stat_file=stat_file,
            yt_ctrl_file=yt_ctrl_file,
            dev_define_file=None,
            real_file=root / "real.e",
            scada_file=root / "scada.e",
            period_seconds=60.0,
        )
        simu_loop.run_once(config, solver=fake_solver)

        self.assertAlmostEqual(seen["wind"], 1.25)
        self.assertAlmostEqual(seen["pv"], 25.0)

    def test_weather_clamps_structurally_linked_ac_wind_and_ac_dc_pv_after_control_overlay(self):
        import simu_loop

        source_model = simu_loop.EBook(
            {
                "ACGenerator": [
                    {
                        "idx": 24,
                        "name": "设备-甲",
                        "dev_type": "ac-source",
                        "node": 34,
                        "control_type": "PQ",
                        "p_set": 12,
                        "p_max": 12,
                        "run_stat": 1,
                        "rated_capacity": 12,
                    },
                    {
                        "idx": 25,
                        "name": "设备-乙",
                        "dev_type": "ac-source",
                        "node": 35,
                        "control_type": "PV",
                        "p_set": 20,
                        "p_max": 20,
                        "run_stat": 1,
                        "rated_capacity": 20,
                    }
                ],
                "DCGenerator": [
                    {
                        "idx": 3,
                        "name": "设备-丙",
                        "dev_type": "dc-source",
                        "node": 3,
                        "control_type": "P",
                        "p_set": 15,
                        "p_max": 15,
                        "run_stat": 1,
                        "rated_capacity": 15,
                    }
                ],
                "ACWindGen": [
                    {
                        "idx": 1,
                        "idx_acgenerator": 24,
                        "wind_turbine_model": "arbitrary-model-label",
                        "cut_in_wind_speed": 5,
                        "rated_wind_speed": 15,
                        "cut_out_wind_speed": 50,
                        "rated_power": 12,
                    }
                ],
                "ACPVGen": [
                    {
                        "idx": 1,
                        "idx_acgenerator": 25,
                        "pv_module_model": "Mono-550W",
                        "module_efficiency": 0.20,
                        "array_area": 100,
                        "mppt_count": 1,
                    }
                ],
                "DCPVGen": [
                    {
                        "idx": 1,
                        "idx_dcgenerator": 3,
                        "pv_module_model": "Mono-550W",
                        "module_efficiency": 0.20,
                        "array_area": 75,
                        "mppt_count": 1,
                    }
                ],
            }
        )
        weather_book = simu_loop.EBook(
            {
                "Weather": [
                    {
                        "time": "21:15:00",
                        "wind_speed_mps": 10,
                        "solar_irradiance_w_m2": 0,
                        "air_temp_c": -25.26,
                        "load_kw": 231.85,
                    }
                ]
            }
        )
        control_book = simu_loop.EBook(
            {
                "SetValue": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "设备-甲",
                        "set_type": "p_set",
                        "set_value": 12,
                    },
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "设备-乙",
                        "set_type": "p_set",
                        "set_value": 20,
                    },
                    {
                        "dev_type": "DCGenerator",
                        "dev_name": "设备-丙",
                        "set_type": "p_set",
                        "set_value": 15,
                    },
                ]
            }
        )

        _changed, model_book, dev_define, _weather = simu_loop.apply_realtime_input_books(
            source_model,
            weather_book,
            simu_loop.EBook({}),
            control_book,
            None,
        )

        pv_definitions = {
            str(row.get("name", "")): row
            for row in dev_define.data["pv_generator"].data
        }
        self.assertEqual(set(pv_definitions), {"设备-乙", "设备-丙"})
        self.assertEqual(float(pv_definitions["设备-乙"]["rated_power"]), 20.0)
        self.assertAlmostEqual(float(model_book.data["ACGenerator"].data[0]["p_set"]), 1.5)
        self.assertEqual(float(model_book.data["ACGenerator"].data[1]["p_set"]), 0.0)
        self.assertEqual(float(model_book.data["DCGenerator"].data[0]["p_set"]), 0.0)

    def test_wind_limit_uses_rated_capacity_and_wind_speed_thresholds(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        weather_file = root / "weather.e"
        yt_ctrl_file = root / "yt_ctrl.e"
        meas_file = root / "meas.e"

        model_file.write_text(
            _efile_block(
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
                    "run_stat",
                    "rated_capacity",
                ),
                [
                    {
                        "idx": 1,
                        "name": "wind_alpha",
                        "dev_type": "ac-wind-source",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 0,
                        "q_set": 0,
                        "v_set": 300,
                        "run_stat": 1,
                        "rated_capacity": 12,
                    }
                ],
            )
            + _efile_block(
                "ACWindGen",
                (
                    "idx",
                    "idx_acgenerator",
                    "wind_turbine_model",
                    "cut_in_wind_speed",
                    "rated_wind_speed",
                    "cut_out_wind_speed",
                ),
                [
                    {
                        "idx": 1,
                        "idx_acgenerator": 1,
                        "wind_turbine_model": "WT-5MW",
                        "cut_in_wind_speed": 5,
                        "rated_wind_speed": 15,
                        "cut_out_wind_speed": 50,
                    }
                ],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(_efile_block("SetValue", ("dev_type", "dev_name", "set_type", "set_value"), []), encoding="utf-8")
        yt_ctrl_file.write_text(_efile_block("SetValue", ("dev_type", "dev_name", "set_type", "set_value"), []), encoding="utf-8")
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        seen: dict[str, float] = {}

        def fake_solver(merged_model: Path):
            book = simu_loop.EBook(merged_model)
            seen["wind"] = float(book.data["ACGenerator"].data[0]["p_set"])
            return object(), "fake-solver"

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=weather_file,
            dev_stat_file=stat_file,
            yt_ctrl_file=yt_ctrl_file,
            dev_define_file=None,
            real_file=root / "real.e",
            scada_file=root / "scada.e",
            period_seconds=60.0,
        )

        for wind_speed, expected in ((4, 0.0), (10, 1.5), (15, 12.0), (50, 0.0)):
            weather_file.write_text(
                _efile_block(
                    "Weather",
                    ("time", "wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c", "load_kw"),
                    [{"time": "00:00:00", "wind_speed_mps": wind_speed, "solar_irradiance_w_m2": 0, "air_temp_c": 25, "load_kw": 0}],
                ),
                encoding="utf-8",
            )
            simu_loop.run_once(config, solver=fake_solver)
            self.assertAlmostEqual(seen["wind"], expected)

    def test_wind_and_pv_limits_target_source_devices_not_converters(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        weather_file = root / "weather.e"
        device_file = root / "device.e"
        yt_ctrl_file = root / "yt_ctrl.e"
        meas_file = root / "meas.e"

        model_file.write_text(
            _efile_block(
                "ACGenerator",
                ("idx", "name", "node", "control_type", "p_set", "q_set", "v_set", "run_stat"),
                [{"idx": 1, "name": "wt01_10kw", "node": 1, "control_type": "P", "p_set": 0, "q_set": 0, "v_set": 300, "run_stat": 1}],
            )
            + _efile_block(
                "DCACConverter",
                ("idx", "name", "p_ac_set", "q_ac_set", "v_ac_set", "run_stat"),
                [{"idx": 1, "name": "wt01_rect", "p_ac_set": 8, "q_ac_set": 0, "v_ac_set": 0, "run_stat": 1}],
            )
            + _efile_block(
                "DCGenerator",
                ("idx", "name", "node", "control_type", "p_set", "v_set", "i_set", "run_stat"),
                [{"idx": 1, "name": "pv01_vsrc", "node": 1, "control_type": "P", "p_set": 0, "v_set": 300, "i_set": 0, "run_stat": 1}],
            )
            + _efile_block(
                "DCDCConverter",
                ("idx", "name", "p_set", "run_stat"),
                [{"idx": 1, "name": "pv01_dcdc", "p_set": 25, "run_stat": 1}],
            )
            + _efile_block(
                "ACWindGen",
                ("idx", "idx_acgenerator", "rated_power", "rated_wind_speed", "cut_in_wind_speed", "cut_out_wind_speed"),
                [{"idx": 1, "idx_acgenerator": 1, "rated_power": 10, "rated_wind_speed": 15, "cut_in_wind_speed": 5, "cut_out_wind_speed": 50}],
            )
            + _efile_block(
                "DCPVGen",
                ("idx", "idx_dcgenerator", "rated_power", "temp_coefficient", "reference_irradiance", "reference_temperature"),
                [{"idx": 1, "idx_dcgenerator": 1, "rated_power": 50, "temp_coefficient": 0, "reference_irradiance": 1000, "reference_temperature": 25}],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "set_type": "p_set", "set_value": 9},
                    {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "set_type": "p_set", "set_value": 45},
                ],
            ),
            encoding="utf-8",
        )
        yt_ctrl_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "set_type": "p_set", "set_value": 9},
                    {"dev_type": "DCGenerator", "dev_name": "pv01_vsrc", "set_type": "p_set", "set_value": 45},
                ],
            ),
            encoding="utf-8",
        )
        weather_file.write_text(
            _efile_block(
                "Weather",
                ("time", "wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c", "load_kw"),
                [{"time": "00:00:00", "wind_speed_mps": 10, "solar_irradiance_w_m2": 500, "air_temp_c": 25, "load_kw": 0}],
            ),
            encoding="utf-8",
        )
        device_file.write_text(
            _efile_block(
                "wind_generator",
                ("id", "name", "source_name", "dev_type", "p_max", "p_min", "rated_power", "rated_wind_speed", "cut_in_speed", "cut_out_speed"),
                [{"id": 1, "name": "wt01_rect", "source_name": "wt01_10kw", "dev_type": "ACGenerator", "p_max": 10, "p_min": 0, "rated_power": 10, "rated_wind_speed": 15, "cut_in_speed": 5, "cut_out_speed": 50}],
            )
            + _efile_block(
                "pv_generator",
                ("id", "name", "source_name", "dev_type", "p_max", "p_min", "rated_power", "temp_coefficient", "reference_irradiance", "reference_temperature"),
                [{"id": 1, "name": "pv01_dcdc", "source_name": "pv01_vsrc", "dev_type": "DCGenerator", "p_max": 50, "p_min": 0, "rated_power": 50, "temp_coefficient": 0, "reference_irradiance": 1000, "reference_temperature": 25}],
            ),
            encoding="utf-8",
        )
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        seen: dict[str, float] = {}

        def fake_solver(merged_model: Path):
            book = simu_loop.EBook(merged_model)
            seen["wind_source"] = float(book.data["ACGenerator"].data[0]["p_set"])
            seen["wind_converter"] = float(book.data["DCACConverter"].data[0]["p_ac_set"])
            seen["pv_source"] = float(book.data["DCGenerator"].data[0]["p_set"])
            seen["pv_converter"] = float(book.data["DCDCConverter"].data[0]["p_set"])
            return object(), "fake-solver"

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=weather_file,
            dev_stat_file=stat_file,
            yt_ctrl_file=yt_ctrl_file,
            dev_define_file=device_file,
            real_file=root / "real.e",
            scada_file=root / "scada.e",
            period_seconds=60.0,
        )
        simu_loop.run_once(config, solver=fake_solver)

        self.assertAlmostEqual(seen["wind_source"], 1.25)
        self.assertAlmostEqual(seen["wind_converter"], 8.0)
        self.assertAlmostEqual(seen["pv_source"], 25.0)
        self.assertAlmostEqual(seen["pv_converter"], 25.0)

    def test_limits_wind_and_pv_commands_by_weather_after_control_overlay(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        weather_file = root / "weather.e"
        device_file = root / "device.e"
        yt_ctrl_file = root / "yt_ctrl.e"
        meas_file = root / "meas.e"

        model_file.write_text(
            _efile_block(
                "ACGenerator",
                ("idx", "name", "node", "control_type", "p_set", "q_set", "v_set", "run_stat"),
                [{"idx": 1, "name": "wind_alpha", "node": 1, "control_type": "P", "p_set": 0, "q_set": 0, "v_set": 300, "run_stat": 1}],
            )
            + _efile_block(
                "DCGenerator",
                ("idx", "name", "node", "control_type", "p_set", "v_set", "i_set", "run_stat"),
                [{"idx": 1, "name": "solar_alpha", "node": 1, "control_type": "P", "p_set": 0, "v_set": 300, "i_set": 0, "run_stat": 1}],
            )
            + _efile_block(
                "DCACConverter",
                ("idx", "name", "ac_control_type", "p_ac_set", "q_ac_set", "v_ac_set", "run_stat"),
                [
                    {"idx": 1, "name": "wind_alpha_rect", "ac_control_type": "PH", "p_ac_set": 99, "q_ac_set": 0, "v_ac_set": 0, "run_stat": 1},
                    {"idx": 2, "name": "grid_inv_acp", "ac_control_type": "PQ", "p_ac_set": -45, "q_ac_set": 0, "v_ac_set": 0, "run_stat": 1},
                ],
            )
            + _efile_block(
                "DCDCConverter",
                ("idx", "name", "p_set", "run_stat"),
                [{"idx": 1, "name": "solar_alpha_dcdc", "p_set": 88, "run_stat": 1}],
            )
            + _efile_block(
                "ACWindGen",
                ("idx", "idx_acgenerator", "rated_power", "rated_wind_speed", "cut_in_wind_speed", "cut_out_wind_speed"),
                [{"idx": 1, "idx_acgenerator": 1, "rated_power": 10, "rated_wind_speed": 15, "cut_in_wind_speed": 5, "cut_out_wind_speed": 50}],
            )
            + _efile_block(
                "DCPVGen",
                ("idx", "idx_dcgenerator", "rated_power", "temp_coefficient", "reference_irradiance", "reference_temperature"),
                [{"idx": 1, "idx_dcgenerator": 1, "rated_power": 50, "temp_coefficient": 0, "reference_irradiance": 1000, "reference_temperature": 25}],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "ACGenerator", "dev_name": "wind_alpha", "set_type": "p_set", "set_value": 0.5},
                    {"dev_type": "DCGenerator", "dev_name": "solar_alpha", "set_type": "p_set", "set_value": 10},
                    {"dev_type": "DCACConverter", "dev_name": "grid_inv_acp", "set_type": "p_set", "set_value": -45},
                ],
            ),
            encoding="utf-8",
        )
        yt_ctrl_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "ACGenerator", "dev_name": "wind_alpha", "set_type": "p_set", "set_value": 9},
                    {"dev_type": "DCGenerator", "dev_name": "solar_alpha", "set_type": "p_set", "set_value": 45},
                ],
            ),
            encoding="utf-8",
        )
        weather_file.write_text(
            _efile_block(
                "Weather",
                ("time", "wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c", "load_kw"),
                [{"time": "00:00:00", "wind_speed_mps": 10, "solar_irradiance_w_m2": 500, "air_temp_c": 25, "load_kw": 0}],
            ),
            encoding="utf-8",
        )
        device_file.write_text(
            _efile_block(
                "wind_generator",
                ("id", "name", "p_max", "p_min", "rated_power", "rated_wind_speed", "cut_in_speed", "cut_out_speed"),
                [{"id": 1, "name": "wind_alpha", "p_max": 10, "p_min": 0, "rated_power": 10, "rated_wind_speed": 15, "cut_in_speed": 5, "cut_out_speed": 50}],
            )
            + _efile_block(
                "pv_generator",
                ("id", "name", "p_max", "p_min", "rated_power", "temp_coefficient", "reference_irradiance", "reference_temperature"),
                [{"id": 1, "name": "solar_alpha", "p_max": 50, "p_min": 0, "rated_power": 50, "temp_coefficient": 0, "reference_irradiance": 1000, "reference_temperature": 25}],
            ),
            encoding="utf-8",
        )
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        seen: dict[str, float] = {}

        def fake_solver(merged_model: Path):
            book = simu_loop.EBook(merged_model)
            seen["wind"] = float(book.data["ACGenerator"].data[0]["p_set"])
            seen["pv"] = float(book.data["DCGenerator"].data[0]["p_set"])
            seen["wind_converter"] = float(book.data["DCACConverter"].data[0]["p_ac_set"])
            seen["pv_converter"] = float(book.data["DCDCConverter"].data[0]["p_set"])
            seen["grid"] = float(book.data["DCACConverter"].data[1]["p_ac_set"])
            return object(), "fake-solver"

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=weather_file,
            dev_stat_file=stat_file,
            yt_ctrl_file=yt_ctrl_file,
            dev_define_file=device_file,
            real_file=root / "real.e",
            scada_file=root / "scada.e",
            period_seconds=60.0,
        )
        simu_loop.run_once(config, solver=fake_solver)

        self.assertAlmostEqual(seen["wind"], 1.25)
        self.assertAlmostEqual(seen["pv"], 25.0)
        self.assertAlmostEqual(seen["wind_converter"], 99.0)
        self.assertAlmostEqual(seen["pv_converter"], 88.0)
        # The converter has neither an explicit grid role nor physical limits.
        # Do not infer a role from its name or reintroduce an aggregate AC/DC
        # branch-transfer limit; leave this non-actuator setpoint untouched.
        self.assertAlmostEqual(seen["grid"], -45.0)

        yt_ctrl_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [],
            ),
            encoding="utf-8",
        )
        simu_loop.run_once(config, solver=fake_solver)

        self.assertAlmostEqual(seen["wind"], 1.25)
        self.assertAlmostEqual(seen["pv"], 25.0)
        self.assertAlmostEqual(seen["grid"], -45.0)

        yt_ctrl_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "ACGenerator", "dev_name": "wind_alpha", "set_type": "p_set", "set_value": 1},
                    {"dev_type": "DCGenerator", "dev_name": "solar_alpha", "set_type": "p_set", "set_value": 10},
                ],
            ),
            encoding="utf-8",
        )
        simu_loop.run_once(config, solver=fake_solver)

        self.assertAlmostEqual(seen["wind"], 1.0)
        self.assertAlmostEqual(seen["pv"], 10.0)
        self.assertAlmostEqual(seen["grid"], -45.0)


if __name__ == "__main__":
    unittest.main()
