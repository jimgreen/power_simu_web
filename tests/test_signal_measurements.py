from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator
from simu.service import parse_measurement_rows


class SignalMeasurementsTest(unittest.TestCase):
    def test_run_once_writes_run_status_and_breaker_status_without_scada_noise(self):
        import simu_loop

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "model.e"
            stat_file = root / "stat.e"
            weather_file = root / "weather.e"
            meas_file = root / "meas.e"
            real_file = root / "real.e"
            scada_file = root / "scada.e"

            model_file.write_text(
                "<ACGenerator>\n"
                "@ idx name run_stat\n"
                "# 1 gen1 1\n"
                "</ACGenerator>\n"
                "<ACBreak>\n"
                "@ idx name status run_stat\n"
                "# 1 br1 1 1\n"
                "</ACBreak>\n",
                encoding="utf-8",
            )
            stat_file.write_text(
                "<RunStat>\n"
                "@ dev_type dev_name run_stat\n"
                "# ACGenerator gen1 0\n"
                "# ACBreak br1 1\n"
                "</RunStat>\n"
                "<CbOpenStat>\n"
                "@ dev_type dev_name status\n"
                "# ACBreak br1 0\n"
                "</CbOpenStat>\n",
                encoding="utf-8",
            )
            weather_file.write_text(
                "<Weather>\n"
                "@ time wind_speed_mps air_temp_c air_pressure_hpa solar_irradiance_w_m2 humidity_pct load_kw\n"
                "# 00:00:00 12 -20 960 0 70 80\n"
                "</Weather>\n",
                encoding="utf-8",
            )
            meas_file.write_text(
                "<Measurement>\n"
                "@ idx name dev_type dev_name meas_type weight valid value\n"
                "# 1 ACGenerator.gen1.run_stat ACGenerator gen1 RUN_STAT 1 1 1\n"
                "# 2 ACBreak.br1.status ACBreak br1 STATUS 1 1 1\n"
                "</Measurement>\n",
                encoding="utf-8",
            )

            def fake_solver(_merged_model: Path):
                class FakeSnapshot:
                    ac_devices = {"ACBreak": {}}
                    dc_devices = {"DCBreak": {}}

                    def value(self, _dev_type, _dev_name, _meas_type):
                        return None

                return FakeSnapshot(), "fake-solver"

            result = simu_loop.run_once(
                simu_loop.SimulationConfig(
                    model_file=model_file,
                    meas_file=meas_file,
                    weather_file=weather_file,
                    dev_stat_file=stat_file,
                    yt_ctrl_file=root / "yt_ctrl.e",
                    dev_define_file=None,
                    real_file=real_file,
                    scada_file=scada_file,
                    period_seconds=60.0,
                    noise_std=10.0,
                    random_seed=123,
                ),
                solver=fake_solver,
            )

            self.assertEqual(result.missing, 0)
            _before, real_rows, _after = parse_measurement_rows(real_file)
            _before, scada_rows, _after = parse_measurement_rows(scada_file)
            real_by_type = {row[4]: row[7] for row in real_rows}
            scada_by_type = {row[4]: row[7] for row in scada_rows}
            self.assertEqual(real_by_type, {"RUN_STAT": "0", "STATUS": "0"})
            self.assertEqual(scada_by_type, {"RUN_STAT": "0", "STATUS": "0"})

    def test_service_generates_signal_measurements_from_control_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            runtime = Path(temporary) / "runtime"
            source.mkdir()
            (source / "model.e").write_text(
                "<ACGenerator>\n"
                "@ idx name run_stat\n"
                "# 1 gen1 1\n"
                "</ACGenerator>\n"
                "<ACBreak>\n"
                "@ idx name status run_stat\n"
                "# 1 br1 1 1\n"
                "</ACBreak>\n",
                encoding="utf-8",
            )
            (source / "stat.e").write_text(
                "<RunStat>\n"
                "@ dev_type dev_name run_stat\n"
                "# ACGenerator gen1 0\n"
                "# ACBreak br1 1\n"
                "</RunStat>\n"
                "<CbOpenStat>\n"
                "@ dev_type dev_name status\n"
                "# ACBreak br1 0\n"
                "</CbOpenStat>\n",
                encoding="utf-8",
            )
            (source / "control.e").write_text((source / "stat.e").read_text(encoding="utf-8"), encoding="utf-8")
            (source / "weather.e").write_text(
                "<Weather>\n"
                "@ time wind_speed_mps air_temp_c air_pressure_hpa solar_irradiance_w_m2 humidity_pct load_kw\n"
                "# 00:00:00 12 -20 960 0 70 80\n"
                "</Weather>\n",
                encoding="utf-8",
            )
            (source / "meas.e").write_text(
                "<Measurement>\n"
                "@ idx name dev_type dev_name meas_type weight valid value\n"
                "# 1 p_gen1 ACGenerator gen1 P_GEN 25 1 0\n"
                "</Measurement>\n",
                encoding="utf-8",
            )

            service = PolarMicrogridSimulator(source, runtime, model_id="signals", kernel=lambda _config: None)
            snapshot = service.snapshot()
            signal_definitions = [
                row
                for row in snapshot["definitions"]["measurement"]
                if str(row["meas_type"]).upper() in {"RUN_STAT", "STATUS"}
            ]
            signal_scada = [
                row
                for row in snapshot["measurements"]["scada"]
                if str(row["meas_type"]).upper() in {"RUN_STAT", "STATUS"}
            ]

            self.assertEqual(
                {(row["dev_type"], row["dev_name"], row["meas_type"]) for row in signal_definitions},
                {
                    ("ACGenerator", "gen1", "RUN_STAT"),
                    ("ACBreak", "br1", "RUN_STAT"),
                    ("ACBreak", "br1", "STATUS"),
                },
            )
            self.assertEqual(
                {(row["dev_type"], row["dev_name"], row["meas_type"], row["value"]) for row in signal_scada},
                {
                    ("ACGenerator", "gen1", "RUN_STAT", 0.0),
                    ("ACBreak", "br1", "RUN_STAT", 1.0),
                    ("ACBreak", "br1", "STATUS", 0.0),
                },
            )

            _before, meas_rows, _after = parse_measurement_rows(service.files["meas"])
            self.assertEqual(sum(1 for row in meas_rows if row[4].upper() in {"RUN_STAT", "STATUS"}), 3)

    def test_realtime_measurement_pages_label_signal_points(self):
        root = Path(__file__).resolve().parents[1]
        for script_path in (
            root / "simu/web/simulator/app.js",
            root / "simu/web/trainee/app.js",
        ):
            with self.subTest(script=script_path.name):
                script = script_path.read_text(encoding="utf-8")

                self.assertIn("function isSignalMeasurement", script)
                self.assertIn("SIGNAL_MEASUREMENT_LABELS", script)
                self.assertIn("RUN_STAT", script)
                self.assertIn("STATUS", script)
                self.assertIn("运行状态", script)
                self.assertIn("开关状态", script)


if __name__ == "__main__":
    unittest.main()
