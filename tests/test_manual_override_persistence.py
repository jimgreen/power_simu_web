from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import simu_loop
from simu.definition_editing import atomic_write_text, render_ebook_aligned
from simu.service import EBook, PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"


class ManualOverridePersistenceTest(unittest.TestCase):
    def _make_workspace(self):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(FIXTURE, source)
        self.addCleanup(workspace.cleanup)
        return source, runtime

    @staticmethod
    def _source_bytes(source: Path):
        return {
            name: (source / name).read_bytes()
            for name in ("model.e", "meas.e", "stat.e", "control.e")
        }

    @staticmethod
    def _device_row(service: PolarMicrogridSimulator, block_name: str, name: str):
        return next(
            row
            for row in service.definition_snapshot.model_book.data[block_name].data
            if row.get("name") == name
        )

    @staticmethod
    def _measurement(service: PolarMicrogridSimulator, name: str):
        return next(
            row
            for row in service.definitions()["measurement"]
            if row.get("name") == name
        )

    @staticmethod
    def _manual_changes(service: PolarMicrogridSimulator):
        return {
            (item["kind"], item["field"]): item
            for item in service.manual_definition_changes()["changes"]
        }

    def test_device_and_measurement_overrides_leave_source_immutable_and_replay_after_restart(self):
        source, runtime = self._make_workspace()
        source_before = self._source_bytes(source)
        service = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)

        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"idx": "2", "name": "diesel_line"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        service.update_measurement_definition(
            {
                "name": "p_gen_diesel_300kw",
                "revision": service.definition_snapshot.revision,
                "changes": {
                    "error_sigma": 0.02,
                    "median_deviation": -0.35,
                    "valid": 0,
                    "status": "fixed",
                    "fixed_value": 12.5,
                },
            }
        )

        self.assertEqual(self._source_bytes(source), source_before)
        self.assertTrue(service.manual_definition_changes_file.is_file())
        self.assertEqual(service.manual_definition_changes_file.parent, runtime.resolve())
        self.assertFalse((runtime / "model.e").exists())
        self.assertFalse((runtime / "meas.e").exists())

        restarted = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        self.assertEqual(self._device_row(restarted, "ACBranch", "diesel_line")["r"], "0.0025")
        measurement = self._measurement(restarted, "p_gen_diesel_300kw")
        self.assertEqual(float(measurement["weight"]), 2500.0)
        self.assertAlmostEqual(measurement["median_deviation"], -0.35)
        self.assertEqual(measurement["status"], "fixed")
        self.assertEqual(float(measurement["fixed_value"]), 12.5)
        changes = self._manual_changes(restarted)
        self.assertEqual(
            set(changes),
            {
                ("device", "r"),
                ("measurement", "weight"),
                ("measurement", "median_deviation"),
                ("measurement", "status"),
                ("measurement", "fixed_value"),
            },
        )

        restarted.reset_manual_definition_changes(
            {
                "revision": restarted.definition_snapshot.revision,
                "change_ids": [item["id"] for item in changes.values()],
            }
        )

        self.assertEqual(self._device_row(restarted, "ACBranch", "diesel_line")["r"], "0.001")
        measurement = self._measurement(restarted, "p_gen_diesel_300kw")
        self.assertEqual(float(measurement["weight"]), 25.0)
        self.assertEqual(measurement["median_deviation"], 0.0)
        self.assertEqual(int(float(measurement["valid"])), 1)
        self.assertEqual(measurement["status"], "valid")
        self.assertIsNone(measurement["fixed_value"])
        self.assertEqual(restarted.manual_definition_changes()["count"], 0)
        self.assertEqual(self._source_bytes(source), source_before)

    def test_simulator_runtime_control_overrides_use_overlay_and_restore_source_defaults(self):
        source, runtime = self._make_workspace()
        source_before = self._source_bytes(source)
        service = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)

        service.update_device_parameters(
            {
                "block_name": "ACGenerator",
                "row_key": {"idx": "2", "name": "diesel_300kw"},
                "revision": service.definition_snapshot.revision,
                "changes": {"run_stat": 0, "p_set": 95},
            }
        )

        self.assertEqual(self._source_bytes(source), source_before)
        restarted = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        model_row = self._device_row(restarted, "ACGenerator", "diesel_300kw")
        self.assertEqual(model_row["run_stat"], "0")
        self.assertEqual(model_row["p_set"], "95")
        run_row = next(
            row
            for row in restarted.source_stat_book.data["RunStat"].data
            if row["dev_type"] == "ACGenerator" and row["dev_name"] == "diesel_300kw"
        )
        set_row = next(
            row
            for row in restarted.source_stat_book.data["SetValue"].data
            if row["dev_type"] == "ACGenerator"
            and row["dev_name"] == "diesel_300kw"
            and row["set_type"] == "p_set"
        )
        self.assertEqual(run_row["run_stat"], "0")
        self.assertEqual(set_row["set_value"], "95")

        changes = self._manual_changes(restarted)
        restarted.reset_manual_definition_changes(
            {
                "revision": restarted.definition_snapshot.revision,
                "change_ids": [changes[("device", "run_stat")]["id"], changes[("device", "p_set")]["id"]],
            }
        )

        restored_row = self._device_row(restarted, "ACGenerator", "diesel_300kw")
        self.assertEqual(restored_row["run_stat"], "1")
        self.assertEqual(restored_row["p_set"], "80")
        self.assertEqual(self._source_bytes(source), source_before)

    def test_replaced_source_definition_invalidates_persisted_overrides(self):
        source, runtime = self._make_workspace()
        service = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"idx": "2", "name": "diesel_line"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        override_file = service.manual_definition_changes_file
        self.assertTrue(override_file.exists())

        source_book = EBook(source / "model.e")
        source_row = next(
            row
            for row in source_book.data["ACBranch"].data
            if row.get("name") == "diesel_line"
        )
        source_row["r"] = "0.0035"
        atomic_write_text(source / "model.e", render_ebook_aligned(source_book))

        restarted = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)

        self.assertEqual(self._device_row(restarted, "ACBranch", "diesel_line")["r"], "0.0035")
        self.assertEqual(restarted.manual_definition_changes()["count"], 0)
        self.assertFalse(override_file.exists())
        self.assertTrue(list(runtime.glob("manual_overrides.stale.*.json")))


if __name__ == "__main__":
    unittest.main()
