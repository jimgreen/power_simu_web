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
                ("id", "name", "p_max", "p_min", "rated_power", "rated_wind_speed", "cut_in_speed", "cut_out_speed"),
                [{"id": 1, "name": "wt01_rect", "p_max": 10, "p_min": 0, "rated_power": 10, "rated_wind_speed": 15, "cut_in_speed": 5, "cut_out_speed": 50}],
            )
            + _efile_block(
                "pv_generator",
                ("id", "name", "p_max", "p_min", "rated_power", "temp_coefficient", "reference_irradiance", "reference_temperature"),
                [{"id": 1, "name": "pv01_dcdc", "p_max": 50, "p_min": 0, "rated_power": 50, "temp_coefficient": 0, "reference_irradiance": 1000, "reference_temperature": 25}],
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
                ("idx", "name", "p_ac_set", "q_ac_set", "v_ac_set", "run_stat"),
                [
                    {"idx": 1, "name": "wind_alpha_rect", "p_ac_set": 99, "q_ac_set": 0, "v_ac_set": 0, "run_stat": 1},
                    {"idx": 2, "name": "grid_inv_acp", "p_ac_set": -45, "q_ac_set": 0, "v_ac_set": 0, "run_stat": 1},
                ],
            )
            + _efile_block(
                "DCDCConverter",
                ("idx", "name", "p_set", "run_stat"),
                [{"idx": 1, "name": "solar_alpha_dcdc", "p_set": 88, "run_stat": 1}],
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
        self.assertAlmostEqual(seen["grid"], -25.725)

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
        self.assertAlmostEqual(seen["grid"], -25.725)

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
        self.assertAlmostEqual(seen["grid"], -10.78)


if __name__ == "__main__":
    unittest.main()
