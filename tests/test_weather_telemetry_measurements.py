import tempfile
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator
from simu.service import parse_measurement_rows


ROOT = Path(__file__).resolve().parents[1]


class WeatherTelemetryMeasurementsTest(unittest.TestCase):
    def test_weather_is_exposed_as_scada_telemetry(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = PolarMicrogridSimulator(
                ROOT / "models/simulator/source/简单模型",
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
                ROOT / "models/simulator/source/简单模型",
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
