from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from simu.service import EBook, PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"


class LiveDefinitionHotSwapTest(unittest.TestCase):
    def _make_service(self, kernel=None):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(FIXTURE, source)
        service = PolarMicrogridSimulator(
            source,
            runtime,
            model_id="hot-swap",
            kernel=kernel or (lambda _config: None),
        )
        self.addCleanup(workspace.cleanup)
        return source, runtime, service

    def _tree_fingerprint(self, root: Path):
        result = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def test_device_update_publishes_new_snapshot_without_mutating_old_book(self):
        source, _runtime, service = self._make_service()
        before = service.definition_snapshot
        old_row = next(
            row
            for row in before.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )

        result = service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "changes": {"r": 0.0025},
            }
        )

        after = service.definition_snapshot
        new_row = next(
            row
            for row in after.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        persisted = next(
            row
            for row in EBook(source / "model.e").data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertIsNot(before, after)
        self.assertIsNot(before.model_book, after.model_book)
        self.assertEqual(old_row["r"], "0.001")
        self.assertEqual(new_row["r"], "0.0025")
        self.assertEqual(persisted["r"], "0.0025")
        self.assertEqual(after.revision, before.revision + 1)
        self.assertTrue(result["memory_updated"])
        self.assertTrue(result["persisted"])
        self.assertEqual(result["record"]["r"], 0.0025)

    def test_device_update_rejects_topology_runtime_and_setpoint_fields(self):
        _source, _runtime, service = self._make_service()
        cases = (
            ("ACBranch", "diesel_line", {"i_node": 99}),
            ("ACGenerator", "diesel_300kw", {"run_stat": 0}),
            ("ACGenerator", "diesel_300kw", {"p_set": 12}),
        )
        for block_name, name, changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.update_device_parameters(
                    {
                        "block_name": block_name,
                        "row_key": {"name": name},
                        "changes": changes,
                    }
                )

    def test_measurement_update_changes_definition_and_persists_weight_and_status(self):
        source, _runtime, service = self._make_service()
        name = "p_gen_diesel_300kw"

        result = service.update_measurement_definition(
            {
                "name": name,
                "changes": {"error_sigma": 0.02, "valid": 0},
            }
        )

        definition = next(
            row for row in service.measurements()["definitions"] if row["name"] == name
        )
        persisted = next(
            row
            for row in EBook(source / "meas.e").data["Measurement"].data
            if row["name"] == name
        )
        self.assertAlmostEqual(float(definition["weight"]), 2500.0)
        self.assertEqual(definition["valid"], 0)
        self.assertAlmostEqual(float(persisted["weight"]), 2500.0)
        self.assertEqual(int(float(persisted["valid"])), 0)
        self.assertAlmostEqual(result["record"]["error_sigma"], 0.02)
        self.assertEqual(result["record"]["valid"], 0)

    def test_measurement_update_rejects_unknown_measurement(self):
        _source, _runtime, service = self._make_service()

        with self.assertRaisesRegex(ValueError, "Unknown measurement"):
            service.update_measurement_definition(
                {
                    "name": "missing.measurement",
                    "changes": {"weight": 100},
                }
            )

    def test_definition_update_does_not_wait_for_running_kernel_and_applies_next_step(self):
        entered = threading.Event()
        release = threading.Event()
        captured = []
        worker_errors = []

        def blocking_kernel(config):
            captured.append(config)
            entered.set()
            release.wait(5)
            return None

        _source, _runtime, service = self._make_service(kernel=blocking_kernel)

        def run_step():
            try:
                service.step()
            except Exception as exc:  # pragma: no cover - asserted below.
                worker_errors.append(exc)

        worker = threading.Thread(target=run_step, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(2))

        started = time.monotonic()
        result = service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line"},
                "changes": {"r": 0.003},
            }
        )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 1.0)
        self.assertTrue(result["memory_updated"])
        first_row = next(
            row
            for row in captured[0].model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(first_row["r"], "0.001")

        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])

        service.kernel = lambda config: captured.append(config) or None
        service.step()
        second_row = next(
            row
            for row in captured[1].model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(second_row["r"], "0.003")

    def test_edit_does_not_create_or_change_runtime_files_or_clock_state(self):
        _source, runtime, service = self._make_service()
        service.clock.state = "running"
        before = self._tree_fingerprint(runtime)

        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line"},
                "changes": {"r": 0.004},
            }
        )

        self.assertEqual(self._tree_fingerprint(runtime), before)
        self.assertEqual(service.clock.state, "running")

    def test_persistence_failure_keeps_new_memory_snapshot_and_old_source_file(self):
        source, _runtime, service = self._make_service()
        old_text = (source / "model.e").read_text(encoding="utf-8")
        observed = {}

        def fail_after_publish(_path, _text):
            active = next(
                row
                for row in service.definition_snapshot.model_book.data["ACBranch"].data
                if row["name"] == "diesel_line"
            )
            observed["active_r"] = active["r"]
            raise OSError("disk full")

        with patch("simu.service.atomic_write_text", side_effect=fail_after_publish):
            result = service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line"},
                    "changes": {"r": 0.005},
                }
            )

        active = next(
            row
            for row in service.definition_snapshot.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(observed["active_r"], "0.005")
        self.assertEqual(active["r"], "0.005")
        self.assertEqual((source / "model.e").read_text(encoding="utf-8"), old_text)
        self.assertTrue(result["memory_updated"])
        self.assertFalse(result["persisted"])
        self.assertIn("E 文件保存失败", result["warning"])

    def test_edit_response_and_static_metadata_publish_the_active_revision(self):
        _source, _runtime, service = self._make_service()

        result = service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line"},
                "changes": {"x": 0.0075},
            }
        )

        revision = service.definition_snapshot.revision
        self.assertEqual(result["revision"], revision)
        self.assertEqual(result["static_meta"]["definitions"]["revision"], revision)
        self.assertEqual(result["static_meta"]["device_parameters"]["revision"], revision)
        self.assertEqual(service.static_meta()["definitions"]["revision"], revision)
        self.assertEqual(service.static_meta()["device_parameters"]["revision"], revision)

    def test_definition_readers_use_one_captured_snapshot_when_an_edit_publishes_mid_read(self):
        _source, _runtime, service = self._make_service()
        before = service.definition_snapshot
        original_stat_maps = service._stat_maps

        def publish_during_read():
            service.update_device_parameters(
                {
                    "block_name": "DCStorageGen",
                    "row_key": {"idx": "1"},
                    "changes": {"energy_capacity": 222},
                }
            )
            return original_stat_maps()

        with patch.object(service, "_stat_maps", side_effect=publish_during_read):
            devices = service.devices()

        storage = next(item for item in devices if item["dev_name"] == "ess01_vsrc")
        self.assertEqual(before.revision + 1, service.definition_snapshot.revision)
        self.assertEqual(storage["raw"]["emva"], 100.0)


if __name__ == "__main__":
    unittest.main()
