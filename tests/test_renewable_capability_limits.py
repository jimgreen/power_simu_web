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
                "DCACConverter",
                ("idx", "name", "p_ac_set", "q_ac_set", "v_ac_set", "run_stat"),
                [{"idx": 1, "name": "wind_alpha", "p_ac_set": 0, "q_ac_set": 0, "v_ac_set": 0, "run_stat": 1}],
            )
            + _efile_block(
                "DCDCConverter",
                ("idx", "name", "p_set", "run_stat"),
                [{"idx": 1, "name": "solar_alpha", "p_set": 0, "run_stat": 1}],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "DCACConverter", "dev_name": "wind_alpha", "set_type": "p_set", "set_value": 0.5},
                    {"dev_type": "DCDCConverter", "dev_name": "solar_alpha", "set_type": "p_set", "set_value": 10},
                ],
            ),
            encoding="utf-8",
        )
        yt_ctrl_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "DCACConverter", "dev_name": "wind_alpha", "set_type": "p_set", "set_value": 9},
                    {"dev_type": "DCDCConverter", "dev_name": "solar_alpha", "set_type": "p_set", "set_value": 45},
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
            seen["wind"] = float(book.data["DCACConverter"].data[0]["p_ac_set"])
            seen["pv"] = float(book.data["DCDCConverter"].data[0]["p_set"])
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

        yt_ctrl_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [
                    {"dev_type": "DCACConverter", "dev_name": "wind_alpha", "set_type": "p_set", "set_value": 1},
                    {"dev_type": "DCDCConverter", "dev_name": "solar_alpha", "set_type": "p_set", "set_value": 10},
                ],
            ),
            encoding="utf-8",
        )
        simu_loop.run_once(config, solver=fake_solver)

        self.assertAlmostEqual(seen["wind"], 1.0)
        self.assertAlmostEqual(seen["pv"], 10.0)


if __name__ == "__main__":
    unittest.main()
