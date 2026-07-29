import json
import shutil
import tempfile
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator
from simu.service import parse_measurement_rows
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class WeatherTelemetryMeasurementsTest(unittest.TestCase):
    def test_missing_wind_and_solar_boundaries_stay_unknown(self):
        import simu_loop

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            shutil.copytree(SIMPLE_MODEL_SOURCE, source)
            (source / "weather.e").unlink()
            (source / "curves.json").write_text(
                json.dumps(
                    {
                        "mode": "day",
                        "time_step_minutes": 1,
                        "point_count": 1,
                        "weather": [
                            {
                                "minute": 0,
                                "air_temp_c": -18.0,
                                "air_pressure_hpa": 960.0,
                                "humidity_pct": 72.0,
                            }
                        ],
                        "loads": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = PolarMicrogridSimulator(source, runtime, model_id="unknown-weather", kernel=lambda _config: None)
            service._write_current_weather(0, 0)

            weather = simu_loop._weather_values_from_book(service.weather_book)
            self.assertNotIn("wind_speed_mps", weather)
            self.assertNotIn("solar_irradiance_w_m2", weather)

            boundary = service.curve_boundary()["point"]
            self.assertIsNone(boundary["wind_speed_mps"])
            self.assertIsNone(boundary["solar_irradiance_w_m2"])

            renewable_boundary = " ".join(service._renewable_limit_boundary_lines())
            self.assertIn("风速未知", renewable_boundary)
            self.assertIn("辐照未知", renewable_boundary)

            weather_rows = {
                row["meas_type"]: row
                for row in service.snapshot()["measurements"]["scada"]
                if row["dev_type"] == "Environment" and row["dev_name"] == "weather"
            }
            self.assertEqual(weather_rows["WIND_SPEED"]["valid"], 0)
            self.assertEqual(weather_rows["SOLAR_IRRADIANCE"]["valid"], 0)

    def test_run_once_writes_weather_measurement_values_to_real_snapshot(self):
        import simu_loop

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "model.e"
            stat_file = root / "stat.e"
            weather_file = root / "weather.e"
            meas_file = root / "meas.e"
            real_file = root / "real.e"
            scada_file = root / "scada.e"

            model_file.write_text("<Model>\n@ name\n# test\n</Model>\n", encoding="utf-8")
            stat_file.write_text("<RunStat>\n@ dev_type dev_name run_stat\n</RunStat>\n", encoding="utf-8")
            weather_file.write_text(
                "<Weather>\n"
                "@ time wind_speed_mps air_temp_c air_pressure_hpa solar_irradiance_w_m2 humidity_pct load_kw\n"
                "# 00:00:00 12.5 -18.5 955.2 321.0 76.5 90\n"
                "</Weather>\n",
                encoding="utf-8",
            )
            meas_file.write_text(
                "<Measurement>\n"
                "@ idx name dev_type dev_name meas_type weight valid value\n"
                "# 1 weather_wind_speed Environment weather WIND_SPEED 10000 1 0\n"
                "# 2 weather_air_temp Environment weather AIR_TEMP 10000 1 0\n"
                "# 3 weather_air_pressure Environment weather AIR_PRESSURE 10000 1 0\n"
                "# 4 weather_solar_irradiance Environment weather SOLAR_IRRADIANCE 10000 1 0\n"
                "# 5 weather_humidity Environment weather HUMIDITY 10000 1 0\n"
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
                    noise_std=0.0,
                ),
                solver=fake_solver,
            )

            self.assertEqual(result.missing, 0)
            _before, rows, _after = parse_measurement_rows(real_file)
            by_type = {row[4]: float(row[7]) for row in rows}
            self.assertAlmostEqual(by_type["WIND_SPEED"], 12.5)
            self.assertAlmostEqual(by_type["AIR_TEMP"], -18.5)
            self.assertAlmostEqual(by_type["AIR_PRESSURE"], 955.2)
            self.assertAlmostEqual(by_type["SOLAR_IRRADIANCE"], 321.0)
            self.assertAlmostEqual(by_type["HUMIDITY"], 76.5)

    def test_weather_is_exposed_as_scada_telemetry(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                Path(temporary) / "runtime",
                model_id="simple",
            )

            snapshot = service.snapshot()
            weather_rows = [
                row
                for row in snapshot["measurements"]["scada"]
                if row["dev_type"] == "Environment" and row["dev_name"] == "weather"
            ]

            self.assertEqual(len(weather_rows), 5)
            self.assertEqual(
                {row["meas_type"] for row in weather_rows},
                {"WIND_SPEED", "AIR_TEMP", "HUMIDITY", "AIR_PRESSURE", "SOLAR_IRRADIANCE"},
            )
            self.assertEqual({row["valid"] for row in weather_rows}, {1})
            self.assertEqual(snapshot["summary"]["scada_count"], len(snapshot["measurements"]["scada"]))

            _before, meas_rows, _after = parse_measurement_rows(service.files["meas"])
            weather_definition_types = {
                row[4]
                for row in meas_rows
                if row[2] == "Environment" and row[3] == "weather"
            }
            self.assertEqual(
                weather_definition_types,
                {"WIND_SPEED", "AIR_TEMP", "HUMIDITY", "AIR_PRESSURE", "SOLAR_IRRADIANCE"},
            )

        with tempfile.TemporaryDirectory() as temporary:
            service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                Path(temporary) / "runtime",
                model_id="simple",
            )
            service._write_weather_row(
                {
                    "time": "03:15:00",
                    "wind_speed_mps": 27.5,
                    "air_temp_c": -31.25,
                    "air_pressure_hpa": 948.4,
                    "solar_irradiance_w_m2": 632.1,
                    "humidity_pct": 81.2,
                    "load_kw": 95.0,
                }
            )

            first = service.measurements()
            second = service.snapshot()["measurements"]
            for measurements in (first, second):
                weather_by_type = {
                    row["meas_type"]: row["value"]
                    for row in measurements["scada"]
                    if row["dev_type"] == "Environment" and row["dev_name"] == "weather"
                }
                self.assertEqual(len(weather_by_type), 5)
                self.assertAlmostEqual(weather_by_type["WIND_SPEED"], 27.5)
                self.assertAlmostEqual(weather_by_type["AIR_TEMP"], -31.25)
                self.assertAlmostEqual(weather_by_type["AIR_PRESSURE"], 948.4)
                self.assertAlmostEqual(weather_by_type["SOLAR_IRRADIANCE"], 632.1)
                self.assertAlmostEqual(weather_by_type["HUMIDITY"], 81.2)

    def test_weather_telemetry_is_pinned_and_labeled_on_realtime_measurement_pages(self):
        for script_path in (
            ROOT / "simu/web/simulator/app.js",
            ROOT / "simu/web/trainee/app.js",
        ):
            with self.subTest(script=script_path.name):
                script = script_path.read_text(encoding="utf-8")

                self.assertIn("function isWeatherMeasurement", script)
                self.assertIn("function compareMeasurementsForDisplay", script)
                self.assertIn("function sortMeasurementsForDisplay", script)
                self.assertIn("function weatherMeasurementLabel", script)
                self.assertIn("气象", script)
                self.assertIn("WIND_SPEED", script)
                self.assertIn("SOLAR_IRRADIANCE", script)


if __name__ == "__main__":
    unittest.main()
