from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import simu_loop
from simu.definition_editing import atomic_write_text as real_atomic_write_text
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

    def test_device_update_rejects_topology_fields(self):
        _source, _runtime, service = self._make_service()
        cases = (
            ("ACBranch", "diesel_line", {"i_node": 99}),
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

    def test_device_update_rejects_stale_revision_without_mutating_state(self):
        source, _runtime, service = self._make_service()
        initial_revision = service.definition_snapshot.revision

        first = service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": initial_revision,
                "changes": {"r": 0.0025},
            }
        )
        active_revision = service.definition_snapshot.revision
        persisted_before = (source / "model.e").read_bytes()

        with self.assertRaisesRegex(ValueError, "revision"):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": initial_revision,
                    "changes": {"r": 0.0035},
                }
            )

        row = next(
            item
            for item in service.definition_snapshot.model_book.data["ACBranch"].data
            if item["name"] == "diesel_line"
        )
        self.assertEqual(first["revision"], active_revision)
        self.assertEqual(service.definition_snapshot.revision, active_revision)
        self.assertEqual(row["r"], "0.0025")
        self.assertEqual((source / "model.e").read_bytes(), persisted_before)

    def test_device_update_rejects_duplicate_identity_without_mutating_state(self):
        source, _runtime, service = self._make_service()
        current = service.definition_snapshot
        model_book = simu_loop._clone_ebook(current.model_book)
        block = model_book.data["ACBranch"]
        duplicate = next(row for row in block.data if row["name"] == "diesel_line")
        block.data.append(dict(duplicate))
        service._publish_definition_snapshot(replace(current, model_book=model_book))
        revision_before = service.definition_snapshot.revision
        persisted_before = (source / "model.e").read_bytes()

        with self.assertRaisesRegex(ValueError, "unique"):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": revision_before,
                    "changes": {"r": 0.0035},
                }
            )

        self.assertEqual(service.definition_snapshot.revision, revision_before)
        self.assertEqual((source / "model.e").read_bytes(), persisted_before)

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

    def test_measurement_update_persists_fixed_status_and_applies_fixed_value(self):
        source, _runtime, service = self._make_service()
        name = "p_gen_diesel_300kw"

        result = service.update_measurement_definition(
            {
                "name": name,
                "changes": {"status": "fixed", "fixed_value": 12.5},
            }
        )

        definition = next(row for row in service.measurements()["definitions"] if row["name"] == name)
        self.assertEqual(definition["status"], "fixed")
        self.assertEqual(definition["fixed_value"], 12.5)
        self.assertEqual(result["record"]["status"], "fixed")
        self.assertEqual(result["record"]["fixed_value"], 12.5)
        self.assertEqual(service.local_settings["measurement_statuses"][name]["status"], "fixed")
        self.assertEqual(service.local_settings["measurement_statuses"][name]["fixed_value"], 12.5)
        self.assertIn('"status": "fixed"', (service.settings_file).read_text(encoding="utf-8"))

        reloaded = PolarMicrogridSimulator(source, _runtime, model_id="hot-swap", kernel=lambda _config: None)
        reloaded_definition = next(
            row for row in reloaded.measurements()["definitions"] if row["name"] == name
        )
        self.assertEqual(reloaded_definition["status"], "fixed")
        self.assertEqual(reloaded_definition["fixed_value"], 12.5)

        service.latest_scada_rows = [
            list(row)
            for row in service.definition_snapshot.measurement_rows
            if row[1] == name
        ]
        service._apply_measurement_statuses(0, 0)
        fixed_row = next(row for row in service.latest_scada_rows if row[1] == name)
        self.assertEqual(float(fixed_row[7]), 12.5)

    def test_measurement_update_rejects_unknown_measurement(self):
        _source, _runtime, service = self._make_service()

        with self.assertRaisesRegex(ValueError, "Unknown measurement"):
            service.update_measurement_definition(
                {
                    "name": "missing.measurement",
                    "changes": {"weight": 100},
                }
            )

    def test_measurement_update_rejects_stale_revision_without_mutating_state(self):
        source, _runtime, service = self._make_service()
        name = "p_gen_diesel_300kw"
        initial_revision = service.definition_snapshot.revision

        first = service.update_measurement_definition(
            {
                "name": name,
                "revision": initial_revision,
                "changes": {"weight": 400},
            }
        )
        active_revision = service.definition_snapshot.revision
        persisted_before = (source / "meas.e").read_bytes()

        with self.assertRaisesRegex(ValueError, "revision"):
            service.update_measurement_definition(
                {
                    "name": name,
                    "revision": initial_revision,
                    "changes": {"weight": 625},
                }
            )

        definition = next(
            row for row in service.measurements()["definitions"] if row["name"] == name
        )
        self.assertEqual(first["revision"], active_revision)
        self.assertEqual(service.definition_snapshot.revision, active_revision)
        self.assertEqual(float(definition["weight"]), 400.0)
        self.assertEqual((source / "meas.e").read_bytes(), persisted_before)

    def test_measurement_update_rejects_duplicate_identity_without_mutating_state(self):
        source, _runtime, service = self._make_service()
        current = service.definition_snapshot
        name = "p_gen_diesel_300kw"
        duplicate = next(
            row for row in current.measurement_rows if row[1] == name
        )
        service._publish_definition_snapshot(
            replace(
                current,
                measurement_rows=current.measurement_rows + (duplicate,),
            )
        )
        revision_before = service.definition_snapshot.revision
        persisted_before = (source / "meas.e").read_bytes()

        with self.assertRaisesRegex(ValueError, "unique"):
            service.update_measurement_definition(
                {
                    "name": name,
                    "revision": revision_before,
                    "changes": {"weight": 400},
                }
            )

        self.assertEqual(service.definition_snapshot.revision, revision_before)
        self.assertEqual((source / "meas.e").read_bytes(), persisted_before)

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

    def test_measurement_update_does_not_pause_kernel_or_touch_runtime_files(self):
        entered = threading.Event()
        release = threading.Event()
        captured = []
        worker_errors = []

        def blocking_kernel(config):
            captured.append(config)
            entered.set()
            release.wait(5)
            return None

        _source, runtime, service = self._make_service(kernel=blocking_kernel)
        service.clock.state = "running"
        name = "p_gen_diesel_300kw"

        def run_step():
            try:
                service.step()
            except Exception as exc:  # pragma: no cover - asserted below.
                worker_errors.append(exc)

        worker = threading.Thread(target=run_step, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(2))
        runtime_before = self._tree_fingerprint(runtime)

        started = time.monotonic()
        result = service.update_measurement_definition(
            {
                "name": name,
                "revision": service.definition_snapshot.revision,
                "changes": {"error_sigma": 0.05, "valid": 0},
            }
        )
        elapsed = time.monotonic() - started

        first_row = next(row for row in captured[0].meas_rows if row[1] == name)
        self.assertLess(elapsed, 1.0)
        self.assertNotEqual(float(first_row[5]), 400.0)
        self.assertTrue(result["memory_updated"])
        self.assertEqual(service.clock.state, "running")
        self.assertEqual(self._tree_fingerprint(runtime), runtime_before)

        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])

        service.kernel = lambda config: captured.append(config) or None
        service.step()
        second_row = next(row for row in captured[1].meas_rows if row[1] == name)
        self.assertEqual(float(second_row[5]), 400.0)
        self.assertEqual(int(float(second_row[6])), 0)

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

        def fail_after_publish(path, text):
            active = next(
                row
                for row in service.definition_snapshot.model_book.data["ACBranch"].data
                if row["name"] == "diesel_line"
            )
            observed["active_r"] = active["r"]
            if Path(path).name == "model.e":
                raise OSError("disk full")
            return real_atomic_write_text(path, text)

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

    def test_definition_snapshot_reader_never_observes_mixed_publish_generation(self):
        _source, _runtime, service = self._make_service()
        before = service.definition_snapshot
        next_model_book = simu_loop._clone_ebook(before.model_book)
        next_capability_book = simu_loop._clone_ebook(before.dev_define_book)
        next_model_row = next_model_book.data["ACBranch"].data[0]
        next_model_row["r"] = "new-model-generation"
        capability_block = next(
            block for block in next_capability_book.data.values() if block.data
        )
        capability_block.data[0][capability_block.header_list[0]] = "new-capability-generation"
        next_measurement_rows = [list(row) for row in before.measurement_rows]
        next_measurement_rows[0][7] = "new-measurement-generation"
        candidate = replace(
            before,
            revision=before.revision + 1,
            model_book=next_model_book,
            dev_define_book=next_capability_book,
            measurement_rows=tuple(tuple(row) for row in next_measurement_rows),
        )

        service_lock_held = threading.Event()
        release_service_lock = threading.Event()
        publish_midpoint = threading.Event()
        release_publish = threading.Event()
        reader_done = threading.Event()
        errors = []
        observed = {}
        original_setattr = PolarMicrogridSimulator.__setattr__
        publisher_thread = None

        def hold_service_lock():
            with service.lock:
                service_lock_held.set()
                release_service_lock.wait(timeout=5.0)

        def coordinated_setattr(instance, name, value):
            if (
                instance is service
                and threading.current_thread() is publisher_thread
                and name == "dev_define_book"
                and value is candidate.dev_define_book
            ):
                publish_midpoint.set()
                if not release_publish.wait(timeout=5.0):
                    raise AssertionError("definition publish barrier timed out")
            return original_setattr(instance, name, value)

        def publish_candidate():
            try:
                service._publish_definition_snapshot(candidate)
            except Exception as exc:  # pragma: no cover - asserted below.
                errors.append(exc)

        def read_snapshot():
            try:
                observed["snapshot"] = service.definition_snapshot
            except Exception as exc:  # pragma: no cover - asserted below.
                errors.append(exc)
            finally:
                reader_done.set()

        lock_holder = threading.Thread(target=hold_service_lock, daemon=True)
        publisher_thread = threading.Thread(target=publish_candidate, daemon=True)
        reader_thread = threading.Thread(target=read_snapshot, daemon=True)
        try:
            lock_holder.start()
            self.assertTrue(service_lock_held.wait(timeout=2.0))
            with patch.object(
                PolarMicrogridSimulator,
                "__setattr__",
                new=coordinated_setattr,
            ):
                publisher_thread.start()
                self.assertTrue(
                    publish_midpoint.wait(timeout=2.0),
                    "definition publish unexpectedly waited for service.lock",
                )
                reader_thread.start()
                self.assertTrue(
                    reader_done.wait(timeout=1.0),
                    "definition snapshot reader waited for service.lock or the publisher",
                )
                release_publish.set()
                publisher_thread.join(timeout=2.0)
                reader_thread.join(timeout=2.0)
        finally:
            release_publish.set()
            release_service_lock.set()
            publisher_thread.join(timeout=2.0)
            reader_thread.join(timeout=2.0)
            lock_holder.join(timeout=2.0)

        self.assertEqual(errors, [])
        reader_snapshot = observed["snapshot"]
        self.assertTrue(
            reader_snapshot is before or reader_snapshot is candidate,
            "reader observed a synthesized mixed-generation snapshot",
        )
        if reader_snapshot is before:
            self.assertIs(reader_snapshot.model_book, before.model_book)
            self.assertIs(reader_snapshot.dev_define_book, before.dev_define_book)
            self.assertEqual(reader_snapshot.measurement_rows, before.measurement_rows)
        else:
            self.assertIs(reader_snapshot.model_book, candidate.model_book)
            self.assertIs(reader_snapshot.dev_define_book, candidate.dev_define_book)
            self.assertEqual(reader_snapshot.measurement_rows, candidate.measurement_rows)
        final_snapshot = service.definition_snapshot
        self.assertEqual(final_snapshot.revision, before.revision + 1)
        self.assertIs(final_snapshot.model_book, candidate.model_book)
        self.assertIs(final_snapshot.dev_define_book, candidate.dev_define_book)
        self.assertEqual(final_snapshot.measurement_rows, candidate.measurement_rows)

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
