from __future__ import annotations

import math
import unittest
from pathlib import Path

import simu.server as server_module
from simu.generate_simple_model import model_blocks
from simu.renewable_control import _renewable_weather_available_kw


ROOT = Path(__file__).resolve().parents[1]
PV_REQUIRED_PARAMETER_FIELDS = {
    "reference_irradiance",
    "reference_temperature",
}
PV_TEMPERATURE_COEFFICIENT_FIELDS = {
    "temp_coefficient",
    "temperature_coefficient",
}


class PvReferenceParametersTest(unittest.TestCase):
    def test_persisted_pv_models_define_weather_reference_parameters(self):
        model_paths = []
        for root in (
            ROOT / "models/simulator/source",
            ROOT / "models/trainee/source",
            ROOT / "tests/fixtures",
        ):
            model_paths.extend(sorted(root.rglob("model.e")))

        checked_rows = 0
        for model_path in model_paths:
            model_book = server_module._book_from_text(model_path.read_text(encoding="utf-8"))
            for block_name in ("ACPVGen", "DCPVGen"):
                block = model_book.data.get(block_name)
                if block is None or not block.data:
                    continue
                header_fields = set(block.header_list)
                with self.subTest(model=str(model_path), block=block_name, check="headers"):
                    self.assertTrue(PV_REQUIRED_PARAMETER_FIELDS.issubset(header_fields))
                    self.assertTrue(PV_TEMPERATURE_COEFFICIENT_FIELDS & header_fields)
                if not PV_REQUIRED_PARAMETER_FIELDS.issubset(header_fields):
                    continue
                coefficient_field = next(
                    (
                        field
                        for field in PV_TEMPERATURE_COEFFICIENT_FIELDS
                        if field in header_fields
                    ),
                    None,
                )
                if coefficient_field is None:
                    continue
                for row in block.data:
                    checked_rows += 1
                    with self.subTest(model=str(model_path), block=block_name, row=row.get("idx")):
                        irradiance = float(row["reference_irradiance"])
                        temperature = float(row["reference_temperature"])
                        coefficient = float(row[coefficient_field])
                        self.assertGreater(irradiance, 0.0)
                        self.assertTrue(math.isfinite(temperature))
                        self.assertTrue(math.isfinite(coefficient))

        self.assertGreater(checked_rows, 0)

    def test_simple_model_generator_defines_pv_weather_reference_parameters(self):
        header, rows = next(
            (header, rows)
            for block_name, header, rows in model_blocks()
            if block_name == "DCPVGen"
        )

        self.assertTrue(PV_REQUIRED_PARAMETER_FIELDS.issubset(set(header)))
        self.assertTrue(PV_TEMPERATURE_COEFFICIENT_FIELDS & set(header))
        self.assertTrue(rows)
        self.assertTrue(all(PV_REQUIRED_PARAMETER_FIELDS.issubset(row) for row in rows))
        self.assertTrue(
            all(PV_TEMPERATURE_COEFFICIENT_FIELDS & set(row) for row in rows)
        )

    def test_pv_reference_parameters_produce_numeric_available_power(self):
        available_kw = _renewable_weather_available_kw(
            "pv",
            {
                "reference_irradiance": 1000,
                "reference_temperature": 25,
                "temp_coefficient": -0.004,
            },
            100,
            wind_speed=None,
            solar_irradiance=500,
            air_temperature=25,
        )

        self.assertIsNotNone(available_kw)
        self.assertAlmostEqual(available_kw, 50.0)


if __name__ == "__main__":
    unittest.main()
