from __future__ import annotations

import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simu.definition_editing import (
    atomic_write_text,
    editable_device_field,
    normalize_device_changes,
    normalize_measurement_changes,
    render_ebook_aligned,
)
from simu.service import EBlock, EBook


class DefinitionEditingHelpersTest(unittest.TestCase):
    def test_identity_topology_fields_remain_protected_and_runtime_controls_become_editable(self):
        protected = {
            "idx",
            "name",
            "dev_type",
            "node",
            "i_node",
            "j_node",
            "ac_node",
            "dc_node",
            "idx_acgenerator",
            "idx_dcgenerator",
            "isl",
        }
        for field in protected:
            with self.subTest(field=field):
                self.assertFalse(editable_device_field(field))

        editable = {
            "run_stat",
            "status",
            "p_set",
            "q_set",
            "v_set",
            "i_set",
            "p_ac_set",
            "q_ac_set",
            "v_ac_set",
            "v_dc_set",
            "p_dc_set",
            "q_dc_set",
            "p_from_set",
            "q_from_set",
            "v_from_set",
            "p_to_set",
            "q_to_set",
            "v_to_set",
        }
        for field in editable:
            with self.subTest(field=field):
                self.assertTrue(editable_device_field(field))

        for field in (
            "p_max",
            "p_min",
            "rated_capacity",
            "r",
            "x",
            "soc_upper_limit",
            "wind_turbine_model",
        ):
            with self.subTest(field=field):
                self.assertTrue(editable_device_field(field))

    def test_device_changes_preserve_string_fields_and_require_finite_numbers(self):
        current = {
            "p_min": "20",
            "p_max": "100",
            "rated_capacity": "120",
            "wind_turbine_model": "WT-A",
        }

        normalized = normalize_device_changes(
            current,
            {
                "p_min": 25,
                "p_max": "110.5",
                "wind_turbine_model": "WT-B",
            },
        )

        self.assertEqual(normalized["p_min"], "25")
        self.assertEqual(normalized["p_max"], "110.5")
        self.assertEqual(normalized["wind_turbine_model"], "WT-B")
        with self.assertRaisesRegex(ValueError, "finite"):
            normalize_device_changes(current, {"p_max": math.inf})

    def test_device_changes_reject_protected_unknown_and_inverted_bounds(self):
        current = {"idx": "1", "name": "gen-1", "p_min": "20", "p_max": "100"}

        with self.assertRaisesRegex(ValueError, "not editable"):
            normalize_device_changes(current, {"name": "renamed"})
        with self.assertRaisesRegex(ValueError, "Unknown"):
            normalize_device_changes(current, {"missing": 1})
        with self.assertRaisesRegex(ValueError, "p_min.*p_max"):
            normalize_device_changes(current, {"p_min": 120})

    def test_device_changes_reject_negative_capacity_fields(self):
        current = {"rated_capacity": "100", "r": "0.01"}

        with self.assertRaisesRegex(ValueError, "negative"):
            normalize_device_changes(current, {"rated_capacity": -1})
        self.assertEqual(normalize_device_changes(current, {"r": -0.01})["r"], "-0.01")

    def test_device_changes_reject_invalid_runtime_control_binary_values(self):
        current = {
            "run_stat": "1",
            "status": "0",
            "p_set": "80",
            "q_set": "0",
            "v_set": "380",
        }

        with self.assertRaisesRegex(ValueError, "run_stat"):
            normalize_device_changes(current, {"run_stat": 2})
        with self.assertRaisesRegex(ValueError, "status"):
            normalize_device_changes(current, {"status": -1})
        self.assertEqual(normalize_device_changes(current, {"run_stat": 0})["run_stat"], "0")
        self.assertEqual(normalize_device_changes(current, {"status": 1})["status"], "1")

    def test_device_changes_normalize_percentage_cells_and_validate_ratio_bounds(self):
        current = {
            "energy_capacity": "100",
            "soc_lower_limit": "20%",
            "soc_upper_limit": "90%",
        }

        normalized = normalize_device_changes(
            current,
            {"energy_capacity": 222, "soc_upper_limit": "85%"},
        )

        self.assertEqual(normalized["energy_capacity"], "222")
        self.assertEqual(normalized["soc_upper_limit"], "0.85")
        with self.assertRaisesRegex(ValueError, "soc_lower_limit.*soc_upper_limit"):
            normalize_device_changes(current, {"soc_lower_limit": "95%"})

    def test_measurement_sigma_and_weight_are_bidirectionally_normalized(self):
        from_sigma = normalize_measurement_changes(
            {"weight": "25", "valid": "1"},
            {"error_sigma": 0.1},
        )
        self.assertAlmostEqual(float(from_sigma["weight"]), 100.0)
        self.assertAlmostEqual(from_sigma["error_sigma"], 0.1)

        from_weight = normalize_measurement_changes(
            {"weight": "25", "valid": "1"},
            {"weight": 400},
        )
        self.assertEqual(from_weight["weight"], "400")
        self.assertAlmostEqual(from_weight["error_sigma"], 0.05)

    def test_measurement_changes_reject_nonpositive_weight_and_invalid_status(self):
        with self.assertRaisesRegex(ValueError, "weight"):
            normalize_measurement_changes(
                {"weight": "25", "valid": "1"},
                {"weight": 0},
            )
        with self.assertRaisesRegex(ValueError, "valid"):
            normalize_measurement_changes(
                {"weight": "25", "valid": "1"},
                {"valid": 2},
            )

    def test_measurement_changes_reject_inconsistent_sigma_and_weight(self):
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            normalize_measurement_changes(
                {"weight": "25", "valid": "1"},
                {"weight": 100, "error_sigma": 0.2},
            )

    def test_measurement_statuses_accept_fault_modes_and_require_fixed_value(self):
        current = {"weight": "25", "valid": "1"}
        for status in ("valid", "invalid", "undefined", "dead", "zero"):
            with self.subTest(status=status):
                normalized = normalize_measurement_changes(current, {"status": status})
                self.assertEqual(normalized["status"], status)
                self.assertEqual(normalized["fixed_value"], None)

        fixed = normalize_measurement_changes(
            current,
            {"status": "fixed", "fixed_value": "12.5"},
        )
        self.assertEqual(fixed["status"], "fixed")
        self.assertEqual(fixed["fixed_value"], 12.5)
        self.assertEqual(fixed["valid"], "1")

        with self.assertRaisesRegex(ValueError, "fixed_value"):
            normalize_measurement_changes(current, {"status": "fixed"})
        with self.assertRaisesRegex(ValueError, "status"):
            normalize_measurement_changes(current, {"status": "not-a-status"})

    def test_render_ebook_aligned_preserves_block_headers_and_rows(self):
        book = EBook({})
        block = EBlock("ACBranch")
        block.header_list = ["idx", "name", "r"]
        block.data = [{"idx": "1", "name": "line-1", "r": "0.0025"}]
        book.data["ACBranch"] = block

        text = render_ebook_aligned(book)

        self.assertIn("<ACBranch>\n", text)
        self.assertIn("@ idx  name    r\n", text)
        self.assertIn("# 1    line-1  0.0025\n", text)
        self.assertTrue(text.endswith("</ACBranch>\n"))

    def test_atomic_write_text_replaces_complete_sibling_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "model.e"
            target.write_text("old", encoding="utf-8")
            observed = {}
            real_replace = os.replace

            def inspect_replace(source, destination):
                source_path = Path(source)
                observed["parent"] = source_path.parent
                observed["text"] = source_path.read_text(encoding="utf-8")
                observed["old"] = Path(destination).read_text(encoding="utf-8")
                real_replace(source, destination)

            with patch("simu.definition_editing.os.replace", side_effect=inspect_replace):
                atomic_write_text(target, "new complete text\n")

            self.assertEqual(observed["parent"], root)
            self.assertEqual(observed["text"], "new complete text\n")
            self.assertEqual(observed["old"], "old")
            self.assertEqual(target.read_text(encoding="utf-8"), "new complete text\n")
            self.assertEqual(list(root.glob(".model.e.*.tmp")), [])

    def test_atomic_write_text_retries_transient_windows_replace_denial(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "model.e"
            target.write_text("old", encoding="utf-8")
            real_replace = os.replace
            attempts = []

            def transient_replace(source, destination):
                attempts.append((source, destination))
                if len(attempts) < 3:
                    error = PermissionError("file is temporarily open")
                    error.winerror = 5
                    raise error
                real_replace(source, destination)

            with (
                patch("simu.definition_editing.os.replace", side_effect=transient_replace),
                patch("simu.definition_editing.time.sleep") as sleep,
            ):
                atomic_write_text(target, "new")

            self.assertEqual(len(attempts), 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertEqual(list(root.glob(".model.e.*.tmp")), [])

    def test_atomic_write_text_cleans_temp_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "meas.e"
            target.write_text("old", encoding="utf-8")

            with patch("simu.definition_editing.os.replace", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    atomic_write_text(target, "new")

            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(root.glob(".meas.e.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
