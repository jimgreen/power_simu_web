from __future__ import annotations

import unittest
from pathlib import Path

import simu.server as server_module
from simu.definition_editing import (
    canonical_ratio_parameter_text,
    is_ratio_parameter_field,
    normalize_device_changes,
)
from simu.generate_simple_model import model_blocks
from simu.service import EBook


ROOT = Path(__file__).resolve().parents[1]


class RatioParameterUnitsTest(unittest.TestCase):
    def test_ratio_field_detection_covers_soc_and_efficiency_aliases(self):
        ratio_fields = (
            "state_of_charge",
            "soc_curr",
            "soc_lower_limit",
            "soc_upper_limit",
            "module_efficiency",
            "charge_discharge_efficiency",
            "charge_efficiency",
            "discharge_efficiency",
            "round_trip_efficiency",
            "conversion_efficiency",
            "eta",
            "eta_charge",
            "discharge_eta",
        )
        for field in ratio_fields:
            with self.subTest(field=field):
                self.assertTrue(is_ratio_parameter_field(field))

        for field in ("energy_capacity", "p_set", "humidity_pct", "power_factor"):
            with self.subTest(field=field):
                self.assertFalse(is_ratio_parameter_field(field))

    def test_ratio_text_is_canonical_decimal_even_when_input_is_percent(self):
        self.assertEqual(canonical_ratio_parameter_text("module_efficiency", "21.3%"), "0.213")
        self.assertEqual(canonical_ratio_parameter_text("soc_upper_limit", "90%"), "0.9")
        self.assertEqual(canonical_ratio_parameter_text("charge_efficiency", 0.99), "0.99")

    def test_device_edits_store_ratio_fields_as_decimals_and_validate_range(self):
        current = {
            "state_of_charge": "0.5",
            "soc_lower_limit": "0.1",
            "soc_upper_limit": "0.9",
            "charge_discharge_efficiency": "0.95",
            "module_efficiency": "0.213",
        }

        normalized = normalize_device_changes(
            current,
            {
                "soc_upper_limit": "85%",
                "charge_discharge_efficiency": "99%",
                "module_efficiency": 0.22,
            },
        )

        self.assertEqual(normalized["soc_upper_limit"], "0.85")
        self.assertEqual(normalized["charge_discharge_efficiency"], "0.99")
        self.assertEqual(normalized["module_efficiency"], "0.22")
        with self.assertRaisesRegex(ValueError, "0 and 1"):
            normalize_device_changes(current, {"charge_discharge_efficiency": 99})
        with self.assertRaisesRegex(ValueError, "0 and 1"):
            normalize_device_changes(current, {"module_efficiency": 1.01})
        with self.assertRaisesRegex(ValueError, "0 and 1"):
            normalize_device_changes(current, {"soc_lower_limit": -0.01})

    def test_generated_simple_model_uses_decimal_ratios(self):
        blocks = {name: rows for name, _headers, rows in model_blocks()}
        pv = blocks["DCPVGen"][0]
        storage = blocks["DCStorageGen"][0]

        self.assertEqual(pv["module_efficiency"], 0.2)
        self.assertEqual(storage["charge_discharge_efficiency"], 0.95)
        self.assertEqual(storage["state_of_charge"], 0.55)
        self.assertEqual(storage["soc_lower_limit"], 0.2)
        self.assertEqual(storage["soc_upper_limit"], 0.9)

    def test_imported_legacy_percent_points_are_written_as_decimal_ratios(self):
        artifacts = server_module._generated_model_artifacts(
            """<DCGenerator>
@ idx  name  node  control_type  p_set  v_set  i_set  run_stat
# 1  pv  1  P  0  720  0  1
# 2  storage  1  P  0  720  0  1
</DCGenerator>
<DCPVGen>
@ idx  idx_dcgenerator  module_efficiency  array_area
# 1  1  21.3  100
</DCPVGen>
<DCStorageGen>
@ idx  idx_dcgenerator  charge_discharge_efficiency  state_of_charge  soc_lower_limit  soc_upper_limit
# 1  2  90  50  10  90
</DCStorageGen>
"""
        )
        book = artifacts["model_book"]
        pv = book.data["DCPVGen"].data[0]
        storage = book.data["DCStorageGen"].data[0]

        self.assertEqual(float(pv["module_efficiency"]), 0.213)
        self.assertEqual(float(storage["charge_discharge_efficiency"]), 0.9)
        self.assertEqual(float(storage["state_of_charge"]), 0.5)
        self.assertEqual(float(storage["soc_lower_limit"]), 0.1)
        self.assertEqual(float(storage["soc_upper_limit"]), 0.9)

    def test_storage_soc_parser_accepts_legacy_percent_points_without_clamping_runtime_overshoot(self):
        self.assertEqual(server_module._storage_soc_value(50), 0.5)
        self.assertEqual(server_module._storage_soc_value("50"), 0.5)
        self.assertEqual(server_module._storage_soc_value("50%"), 0.5)
        self.assertEqual(server_module._storage_soc_value(1.08), 1.08)
        self.assertEqual(server_module._storage_soc_value(-0.05), -0.05)

    def test_built_in_model_ratio_parameters_are_decimal_values_in_zero_one_range(self):
        model_paths = [ROOT / "model.e", ROOT / "tests/fixtures/simple_model/model.e"]
        model_paths.extend(sorted((ROOT / "models/simulator/source").glob("*/model.e")))
        model_paths.extend(sorted((ROOT / "models/trainee/source").glob("*/model.e")))

        checked = 0
        for path in model_paths:
            book = EBook(path)
            for block_name, block in book.data.items():
                for field in block.header_list:
                    if not is_ratio_parameter_field(field):
                        continue
                    for row_index, row in enumerate(block.data, start=1):
                        raw = str(row.get(field, "")).strip()
                        if not raw:
                            continue
                        with self.subTest(path=path, block=block_name, row=row_index, field=field):
                            self.assertNotIn("%", raw)
                            value = float(raw)
                            self.assertGreaterEqual(value, 0.0)
                            self.assertLessEqual(value, 1.0)
                        checked += 1
        self.assertGreater(checked, 0)

    def test_built_in_initial_soc_state_is_stored_as_decimal_ratio(self):
        roots = [ROOT]
        roots.extend(sorted((ROOT / "models/simulator/source").iterdir()))
        roots.extend(sorted((ROOT / "models/trainee/source").iterdir()))

        checked = 0
        for model_root in roots:
            if not model_root.is_dir():
                continue
            for file_name in ("control.e", "stat.e"):
                path = model_root / file_name
                if not path.exists():
                    continue
                block = EBook(path).data.get("StorageSoc")
                for row_index, row in enumerate(getattr(block, "data", []), start=1):
                    with self.subTest(path=path, row=row_index):
                        value = float(row["soc_curr"])
                        self.assertGreaterEqual(value, 0.0)
                        self.assertLessEqual(value, 1.0)
                    checked += 1

            measurement_path = model_root / "meas.e"
            if not measurement_path.exists():
                continue
            measurement_block = EBook(measurement_path).data.get("Measurement")
            for row_index, row in enumerate(getattr(measurement_block, "data", []), start=1):
                if str(row.get("meas_type", "")).strip().upper() != "SOC":
                    continue
                with self.subTest(path=measurement_path, row=row_index):
                    value = float(row["value"])
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)
                checked += 1
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
