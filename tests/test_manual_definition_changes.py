from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

import simu_loop
from simu.definition_editing import (
    atomic_write_text as real_atomic_write_text,
    render_ebook_aligned,
)
from simu.server import make_http_server
from simu.service import EBook, MultiModelSimulator, PolarMicrogridSimulator, SimulationModelSpec


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"
CHANGE_FILE = ".manual_definition_changes.json"


class PausingDefinitionLock:
    def __init__(self, worker_name: str):
        self._lock = threading.RLock()
        self._meta_lock = threading.Lock()
        self._worker_name = worker_name
        self._paused = False
        self.waiting = threading.Event()
        self.release_worker = threading.Event()

    def acquire(self, blocking=True, timeout=-1):
        should_pause = False
        with self._meta_lock:
            if threading.current_thread().name == self._worker_name and not self._paused:
                self._paused = True
                should_pause = True
        if should_pause:
            self.waiting.set()
            if not self.release_worker.wait(timeout=3.0):
                raise TimeoutError("manual definition mutation was not released by the test")
        if timeout == -1:
            return self._lock.acquire(blocking)
        return self._lock.acquire(blocking, timeout)

    def release(self):
        self._lock.release()

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError("manual definition mutation could not acquire its lock")
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.release()
        return False


class ManualDefinitionChangesTest(unittest.TestCase):
    def _make_service(self):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(FIXTURE, source)
        service = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        self.addCleanup(workspace.cleanup)
        return root, source, runtime, service

    @staticmethod
    def _by_field(payload):
        return {item["field"]: item for item in payload["changes"]}

    @staticmethod
    def _tree_bytes(root: Path):
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def _run_old_mutation_after_same_id_recreate(self, prepare, mutate, configure_new=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            for model_id in ("alpha", "beta"):
                shutil.copytree(FIXTURE, source_root / model_id)
            manager = MultiModelSimulator(
                [
                    SimulationModelSpec("alpha", source_root / "alpha", "Alpha"),
                    SimulationModelSpec("beta", source_root / "beta", "Beta"),
                ],
                runtime_dir=root / "runtime",
                models_root=source_root,
                kernel=lambda _config: None,
            )
            old_service = manager.service_for("alpha")
            context = prepare(old_service)
            worker_name = "old-manual-definition-request"
            coordinated_lock = PausingDefinitionLock(worker_name)
            old_service.definition_update_lock = coordinated_lock
            result = {}

            def run_mutation():
                try:
                    result["value"] = mutate(old_service, context)
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    result["error"] = exc

            worker = threading.Thread(target=run_mutation, name=worker_name, daemon=True)
            worker.start()
            try:
                self.assertTrue(coordinated_lock.waiting.wait(timeout=2.0))
                manager.delete_model("alpha")
                manager.create_model_slot("alpha")
                new_service = manager.service_for("alpha")
                if configure_new is not None:
                    configure_new(new_service)
                snapshot_before = new_service.definition_snapshot
                source_before = self._tree_bytes(new_service.sim_dir)
                runtime_before = self._tree_bytes(new_service.runtime_dir)

                coordinated_lock.release_worker.set()
                worker.join(timeout=3.0)
                self.assertFalse(worker.is_alive())
                source_after = self._tree_bytes(new_service.sim_dir)
                runtime_after = self._tree_bytes(new_service.runtime_dir)
            finally:
                coordinated_lock.release_worker.set()
                worker.join(timeout=2.0)

        return {
            "result": result,
            "old_service": old_service,
            "new_service": new_service,
            "snapshot_before": snapshot_before,
            "snapshot_after": new_service.definition_snapshot,
            "source_before": source_before,
            "source_after": source_after,
            "runtime_before": runtime_before,
            "runtime_after": runtime_after,
        }

    def _assert_retired_mutation_cancelled(self, outcome):
        self.assertNotIn("value", outcome["result"])
        self.assertIsInstance(outcome["result"].get("error"), RuntimeError)
        self.assertRegex(str(outcome["result"]["error"]), "生命周期|失效|删除|退休")
        self.assertFalse(outcome["old_service"].service_instance_active())
        self.assertIsNot(outcome["old_service"], outcome["new_service"])
        self.assertIs(outcome["snapshot_after"], outcome["snapshot_before"])
        self.assertEqual(outcome["source_after"], outcome["source_before"])
        self.assertEqual(outcome["runtime_after"], outcome["runtime_before"])

    def test_device_and_measurement_changes_persist_across_web_restart(self):
        root, source, _runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        service.update_measurement_definition(
            {
                "name": "p_gen_diesel_300kw",
                "revision": service.definition_snapshot.revision,
                "changes": {"error_sigma": 0.02, "valid": 0},
            }
        )

        changes = service.manual_definition_changes()
        by_field = self._by_field(changes)
        self.assertEqual(changes["count"], 3)
        self.assertEqual(set(by_field), {"r", "weight", "valid"})
        self.assertEqual(by_field["r"]["default_value"], "0.001")
        self.assertEqual(by_field["r"]["current_value"], "0.0025")
        self.assertEqual(by_field["valid"]["default_value"], "1")
        self.assertEqual(by_field["valid"]["current_value"], "0")
        self.assertTrue((source / CHANGE_FILE).is_file())
        self.assertFalse((root / "runtime" / CHANGE_FILE).exists())

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        reloaded_changes = reloaded.manual_definition_changes()
        self.assertEqual(
            {item["id"] for item in reloaded_changes["changes"]},
            {item["id"] for item in changes["changes"]},
        )
        self.assertEqual(reloaded_changes["count"], 3)

    def test_reset_selected_changes_restores_defaults_and_keeps_other_changes(self):
        root, source, runtime, service = self._make_service()
        service.clock.state = "running"
        runtime_before = sorted(path.relative_to(runtime) for path in runtime.rglob("*") if path.is_file())
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025, "x": 0.006},
            }
        )
        service.update_measurement_definition(
            {
                "name": "p_gen_diesel_300kw",
                "revision": service.definition_snapshot.revision,
                "changes": {"error_sigma": 0.02, "valid": 0},
            }
        )
        before_reset = self._by_field(service.manual_definition_changes())

        result = service.reset_manual_definition_changes(
            {
                "revision": service.definition_snapshot.revision,
                "change_ids": [before_reset["r"]["id"], before_reset["valid"]["id"]],
            }
        )

        active_row = next(
            row
            for row in service.definition_snapshot.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        active_measurement = next(
            row
            for row in service.measurements()["definitions"]
            if row["name"] == "p_gen_diesel_300kw"
        )
        persisted_row = next(
            row
            for row in EBook(source / "model.e").data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        persisted_measurement = next(
            row
            for row in EBook(source / "meas.e").data["Measurement"].data
            if row["name"] == "p_gen_diesel_300kw"
        )
        remaining = self._by_field(service.manual_definition_changes())

        self.assertEqual(result["reset_count"], 2)
        self.assertEqual(active_row["r"], "0.001")
        self.assertEqual(active_row["x"], "0.006")
        self.assertEqual(int(active_measurement["valid"]), 1)
        self.assertEqual(float(active_measurement["weight"]), 2500.0)
        self.assertEqual(persisted_row["r"], "0.001")
        self.assertEqual(persisted_row["x"], "0.006")
        self.assertEqual(int(float(persisted_measurement["valid"])), 1)
        self.assertEqual(float(persisted_measurement["weight"]), 2500.0)
        self.assertEqual(set(remaining), {"x", "weight"})
        self.assertEqual(service.clock.state, "running")
        self.assertEqual(
            sorted(path.relative_to(runtime) for path in runtime.rglob("*") if path.is_file()),
            runtime_before,
        )

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        self.assertEqual(set(self._by_field(reloaded.manual_definition_changes())), {"x", "weight"})

    def test_model_change_reset_clears_persisted_manual_change_records(self):
        _root, source, _runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "changes": {"r": 0.0025},
            }
        )
        self.assertTrue((source / CHANGE_FILE).is_file())
        self.assertEqual(service.manual_definition_changes()["count"], 1)

        service.clock.state = "stopped"
        service.reset_runtime_for_model_change()

        self.assertEqual(service.manual_definition_changes()["count"], 0)
        self.assertFalse((source / CHANGE_FILE).exists())

    def test_external_model_replacement_invalidates_stale_manual_change_journal(self):
        root, source, _runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        journal = json.loads((source / CHANGE_FILE).read_text(encoding="utf-8"))
        self.assertTrue(journal["source_fingerprint"])
        model_text = (source / "model.e").read_text(encoding="utf-8")
        self.assertIn("0.0025", model_text)
        real_atomic_write_text(source / "model.e", model_text.replace("0.0025", "0.0035", 1))

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-replaced",
            model_id="manual",
            kernel=lambda _config: None,
        )

        self.assertEqual(reloaded.manual_definition_changes()["count"], 0)
        self.assertFalse((source / CHANGE_FILE).exists())

    def test_pending_device_change_reloads_from_journal_and_retries_model_file(self):
        root, source, _runtime, service = self._make_service()

        def fail_only_model_file(path, text):
            if Path(path).name == "model.e":
                raise OSError("model file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_only_model_file):
            result = service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )

        pending = service.manual_definition_changes()["changes"][0]
        self.assertFalse(result["persisted"])
        self.assertFalse(pending["persisted"])
        self.assertEqual(pending["sync_status"], "failed")
        self.assertIn("model file busy", pending["last_sync_error"])
        self.assertTrue((source / CHANGE_FILE).is_file())
        self.assertEqual(
            next(
                row
                for row in EBook(source / "model.e").data["ACBranch"].data
                if row["name"] == "diesel_line"
            )["r"],
            "0.001",
        )

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        active = next(
            row
            for row in reloaded.definition_snapshot.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        persisted = next(
            row
            for row in EBook(source / "model.e").data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        reloaded_change = reloaded.manual_definition_changes()["changes"][0]

        self.assertEqual(active["r"], "0.0025")
        self.assertEqual(persisted["r"], "0.0025")
        self.assertTrue(reloaded_change["persisted"])
        self.assertEqual(reloaded_change["sync_status"], "synced")

    def test_retry_pending_manual_change_saves_current_memory_value(self):
        _root, source, _runtime, service = self._make_service()

        def fail_only_model_file(path, text):
            if Path(path).name == "model.e":
                raise OSError("model file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_only_model_file):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
        pending = service.manual_definition_changes()["changes"][0]

        retried = service.retry_manual_definition_changes(
            {
                "revision": service.definition_snapshot.revision,
                "change_ids": [pending["id"]],
            }
        )

        persisted = next(
            row
            for row in EBook(source / "model.e").data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(retried["retried_count"], 1)
        self.assertEqual(retried["persisted_count"], 1)
        self.assertEqual(persisted["r"], "0.0025")
        self.assertTrue(retried["changes"][0]["persisted"])
        self.assertEqual(retried["changes"][0]["sync_status"], "synced")

    def test_failed_reset_remains_pending_and_finishes_after_web_restart(self):
        root, source, _runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        change = service.manual_definition_changes()["changes"][0]

        def fail_only_model_file(path, text):
            if Path(path).name == "model.e":
                raise OSError("model file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_only_model_file):
            result = service.reset_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [change["id"]],
                }
            )

        pending = result["changes"][0]
        self.assertFalse(pending["persisted"])
        self.assertEqual(pending["current_value"], pending["default_value"])
        self.assertEqual(pending["sync_status"], "failed")
        self.assertIn("model file busy", pending["last_sync_error"])
        self.assertEqual(
            next(
                row
                for row in EBook(source / "model.e").data["ACBranch"].data
                if row["name"] == "diesel_line"
            )["r"],
            "0.0025",
        )

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-reset-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )

        self.assertEqual(reloaded.manual_definition_changes()["count"], 0)
        self.assertEqual(
            next(
                row
                for row in EBook(source / "model.e").data["ACBranch"].data
                if row["name"] == "diesel_line"
            )["r"],
            "0.001",
        )

    def test_later_successful_device_save_finishes_pending_reset_and_removes_it(self):
        _root, _source, _runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        change = service.manual_definition_changes()["changes"][0]

        def fail_only_model_file(path, text):
            if Path(path).name == "model.e":
                raise OSError("model file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_only_model_file):
            service.reset_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [change["id"]],
                }
            )

        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"x": 0.006},
            }
        )

        changes = self._by_field(service.manual_definition_changes())
        self.assertEqual(set(changes), {"x"})
        self.assertTrue(changes["x"]["persisted"])

    def test_device_final_tracking_write_failure_recovers_after_restart_and_can_reset(self):
        root, source, _runtime, service = self._make_service()
        journal_writes = 0

        def fail_second_journal_write(path, text):
            nonlocal journal_writes
            if Path(path).name == CHANGE_FILE:
                journal_writes += 1
                if journal_writes == 2:
                    raise OSError("tracking finalization unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_second_journal_write):
            result = service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )

        self.assertTrue(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("tracking finalization unavailable", result["warning"])
        self.assertEqual(journal_writes, 2)
        persisted_row = next(
            row
            for row in EBook(source / "model.e").data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(persisted_row["r"], "0.0025")
        pending_payload = json.loads((source / CHANGE_FILE).read_text(encoding="utf-8"))
        self.assertFalse(pending_payload["changes"][0]["persisted"])

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-device-final-write-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        recovered = reloaded.manual_definition_changes()["changes"][0]
        self.assertTrue(recovered["persisted"])
        self.assertEqual(recovered["current_value"], "0.0025")

        reset = reloaded.reset_manual_definition_changes(
            {
                "revision": reloaded.definition_snapshot.revision,
                "change_ids": [recovered["id"]],
            }
        )
        self.assertEqual(reset["reset_count"], 1)
        self.assertEqual(reloaded.manual_definition_changes()["count"], 0)
        reset_row = next(
            row
            for row in EBook(source / "model.e").data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(reset_row["r"], "0.001")

    def test_measurement_final_tracking_write_failure_recovers_after_restart_and_can_reset(self):
        root, source, _runtime, service = self._make_service()
        journal_writes = 0

        def fail_second_journal_write(path, text):
            nonlocal journal_writes
            if Path(path).name == CHANGE_FILE:
                journal_writes += 1
                if journal_writes == 2:
                    raise OSError("tracking finalization unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_second_journal_write):
            result = service.update_measurement_definition(
                {
                    "name": "p_gen_diesel_300kw",
                    "revision": service.definition_snapshot.revision,
                    "changes": {"valid": 0},
                }
            )

        self.assertTrue(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("tracking finalization unavailable", result["warning"])
        self.assertEqual(journal_writes, 2)
        persisted_measurement = next(
            row
            for row in EBook(source / "meas.e").data["Measurement"].data
            if row["name"] == "p_gen_diesel_300kw"
        )
        self.assertEqual(int(float(persisted_measurement["valid"])), 0)
        pending_payload = json.loads((source / CHANGE_FILE).read_text(encoding="utf-8"))
        self.assertFalse(pending_payload["changes"][0]["persisted"])

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-measurement-final-write-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        recovered = reloaded.manual_definition_changes()["changes"][0]
        self.assertTrue(recovered["persisted"])
        self.assertEqual(recovered["current_value"], "0")

        reset = reloaded.reset_manual_definition_changes(
            {
                "revision": reloaded.definition_snapshot.revision,
                "change_ids": [recovered["id"]],
            }
        )
        self.assertEqual(reset["reset_count"], 1)
        self.assertEqual(reloaded.manual_definition_changes()["count"], 0)
        reset_measurement = next(
            row
            for row in EBook(source / "meas.e").data["Measurement"].data
            if row["name"] == "p_gen_diesel_300kw"
        )
        self.assertEqual(int(float(reset_measurement["valid"])), 1)

    def test_device_initial_tracking_write_failure_keeps_memory_but_not_model_file(self):
        _root, source, _runtime, service = self._make_service()
        model_before = (source / "model.e").read_text(encoding="utf-8")

        def fail_tracking_write(path, text):
            if Path(path).name == CHANGE_FILE:
                raise OSError("tracking journal unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_tracking_write):
            result = service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )

        active_row = next(
            row
            for row in service.definition_snapshot.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        pending = service.manual_definition_changes()["changes"][0]
        self.assertTrue(result["memory_updated"])
        self.assertFalse(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("tracking journal unavailable", result["warning"])
        self.assertEqual(active_row["r"], "0.0025")
        self.assertFalse(pending["persisted"])
        self.assertEqual((source / "model.e").read_text(encoding="utf-8"), model_before)

    def test_measurement_initial_tracking_write_failure_keeps_memory_but_not_meas_file(self):
        _root, source, _runtime, service = self._make_service()
        measurement_before = (source / "meas.e").read_text(encoding="utf-8")

        def fail_tracking_write(path, text):
            if Path(path).name == CHANGE_FILE:
                raise OSError("tracking journal unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_tracking_write):
            result = service.update_measurement_definition(
                {
                    "name": "p_gen_diesel_300kw",
                    "revision": service.definition_snapshot.revision,
                    "changes": {"valid": 0},
                }
            )

        active_measurement = next(
            row
            for row in service.measurements()["definitions"]
            if row["name"] == "p_gen_diesel_300kw"
        )
        pending = service.manual_definition_changes()["changes"][0]
        self.assertTrue(result["memory_updated"])
        self.assertFalse(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("tracking journal unavailable", result["warning"])
        self.assertEqual(int(active_measurement["valid"]), 0)
        self.assertFalse(pending["persisted"])
        self.assertEqual((source / "meas.e").read_text(encoding="utf-8"), measurement_before)

    def test_retry_writes_pending_wal_before_e_and_final_journal_failure_recovers(self):
        root, source, _runtime, service = self._make_service()

        def fail_only_model_file(path, text):
            if Path(path).name == "model.e":
                raise OSError("model file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_only_model_file):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
        pending = service.manual_definition_changes()["changes"][0]
        events = []
        definition_written = False

        def fail_retry_final_journal(path, text):
            nonlocal definition_written
            name = Path(path).name
            events.append(name)
            if name == CHANGE_FILE and definition_written:
                raise OSError("retry finalization unavailable")
            if name == "model.e":
                definition_written = True
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_retry_final_journal):
            result = service.retry_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [pending["id"]],
                }
            )

        self.assertEqual(events[0], CHANGE_FILE)
        self.assertTrue(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("retry finalization unavailable", result["warning"])
        self.assertTrue((source / CHANGE_FILE).is_file())

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-retry-final-write-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        recovered = reloaded.manual_definition_changes()["changes"][0]
        self.assertTrue(recovered["persisted"])
        reset = reloaded.reset_manual_definition_changes(
            {
                "revision": reloaded.definition_snapshot.revision,
                "change_ids": [recovered["id"]],
            }
        )
        self.assertEqual(reset["reset_count"], 1)
        self.assertEqual(reloaded.manual_definition_changes()["count"], 0)

    def test_retry_initial_wal_failure_does_not_write_e_file(self):
        _root, source, _runtime, service = self._make_service()

        def fail_only_model_file(path, text):
            if Path(path).name == "model.e":
                raise OSError("model file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_only_model_file):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
        pending = service.manual_definition_changes()["changes"][0]
        model_before = (source / "model.e").read_text(encoding="utf-8")
        e_writes = []

        def fail_retry_wal(path, text):
            name = Path(path).name
            if name == CHANGE_FILE:
                raise OSError("retry journal unavailable")
            if name in {"model.e", "meas.e"}:
                e_writes.append(name)
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_retry_wal):
            result = service.retry_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [pending["id"]],
                }
            )

        self.assertEqual(e_writes, [])
        self.assertFalse(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("retry journal unavailable", result["warning"])
        self.assertEqual((source / "model.e").read_text(encoding="utf-8"), model_before)
        self.assertFalse(service.manual_definition_changes()["changes"][0]["persisted"])

    def test_retry_mixed_pending_wal_accepts_all_partial_file_fingerprints(self):
        root, source, _runtime, service = self._make_service()

        def fail_definition_files(path, text):
            if Path(path).name in {"model.e", "meas.e"}:
                raise OSError("definition file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_definition_files):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
            service.update_measurement_definition(
                {
                    "name": "p_gen_diesel_300kw",
                    "revision": service.definition_snapshot.revision,
                    "changes": {"valid": 0},
                }
            )

        snapshot = service.definition_snapshot
        model_text = render_ebook_aligned(snapshot.model_book)
        measurement_text = simu_loop.render_measurement_snapshot_aligned(
            snapshot.measurement_before,
            snapshot.measurement_rows,
            snapshot.measurement_after,
        )
        expected_fingerprints = {
            service._manual_definition_source_fingerprint(),
            service._manual_definition_source_fingerprint({"model": model_text}),
            service._manual_definition_source_fingerprint({"meas": measurement_text}),
            service._manual_definition_source_fingerprint(
                {"model": model_text, "meas": measurement_text}
            ),
        }
        change_ids = [item["id"] for item in service.manual_definition_changes()["changes"]]
        captured_pending = {}
        definition_write_attempted = False

        def partially_persist_then_fail_final_journal(path, text):
            nonlocal definition_write_attempted
            name = Path(path).name
            if name == CHANGE_FILE:
                if definition_write_attempted:
                    raise OSError("mixed retry finalization unavailable")
                captured_pending.update(json.loads(text))
                return real_atomic_write_text(path, text)
            if name == "model.e":
                definition_write_attempted = True
                return real_atomic_write_text(path, text)
            if name == "meas.e":
                definition_write_attempted = True
                raise OSError("measurement file busy")
            return real_atomic_write_text(path, text)

        with patch(
            "simu.service.atomic_write_text",
            side_effect=partially_persist_then_fail_final_journal,
        ):
            result = service.retry_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": change_ids,
                }
            )

        self.assertIn("accepted_source_fingerprints", captured_pending)
        self.assertEqual(
            set(captured_pending["accepted_source_fingerprints"]),
            expected_fingerprints,
        )
        self.assertFalse(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("measurement file busy", result["warning"])
        self.assertIn("mixed retry finalization unavailable", result["warning"])

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-mixed-retry-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        recovered = self._by_field(reloaded.manual_definition_changes())
        self.assertEqual(set(recovered), {"r", "valid"})
        self.assertTrue(all(item["persisted"] for item in recovered.values()))

    def test_partial_reset_final_journal_failure_recovers_reset_and_keeps_other_change(self):
        root, source, _runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025, "x": 0.006},
            }
        )
        before_reset = self._by_field(service.manual_definition_changes())
        events = []
        definition_written = False

        def fail_reset_final_journal(path, text):
            nonlocal definition_written
            name = Path(path).name
            events.append(name)
            if name == CHANGE_FILE and definition_written:
                raise OSError("reset finalization unavailable")
            if name == "model.e":
                definition_written = True
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_reset_final_journal):
            result = service.reset_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [before_reset["r"]["id"]],
                }
            )

        self.assertEqual(events[0], CHANGE_FILE)
        self.assertTrue(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("reset finalization unavailable", result["warning"])
        persisted_row = next(
            row
            for row in EBook(source / "model.e").data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(persisted_row["r"], "0.001")
        self.assertEqual(persisted_row["x"], "0.006")

        reloaded = PolarMicrogridSimulator(
            source,
            root / "runtime-partial-reset-reloaded",
            model_id="manual",
            kernel=lambda _config: None,
        )
        remaining = self._by_field(reloaded.manual_definition_changes())
        self.assertEqual(set(remaining), {"x"})
        self.assertTrue(remaining["x"]["persisted"])
        reset_x = reloaded.reset_manual_definition_changes(
            {
                "revision": reloaded.definition_snapshot.revision,
                "change_ids": [remaining["x"]["id"]],
            }
        )
        self.assertEqual(reset_x["reset_count"], 1)
        self.assertEqual(reloaded.manual_definition_changes()["count"], 0)

    def test_reset_initial_wal_failure_does_not_write_e_file(self):
        _root, source, _runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        change = service.manual_definition_changes()["changes"][0]
        model_before = (source / "model.e").read_text(encoding="utf-8")
        e_writes = []

        def fail_reset_wal(path, text):
            name = Path(path).name
            if name == CHANGE_FILE:
                raise OSError("reset journal unavailable")
            if name in {"model.e", "meas.e"}:
                e_writes.append(name)
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_reset_wal):
            result = service.reset_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [change["id"]],
                }
            )

        active_row = next(
            row
            for row in service.definition_snapshot.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        pending_changes = service.manual_definition_changes()["changes"]
        self.assertTrue(pending_changes)
        pending = pending_changes[0]
        self.assertEqual(e_writes, [])
        self.assertFalse(result["persisted"])
        self.assertFalse(result["change_record_persisted"])
        self.assertIn("reset journal unavailable", result["warning"])
        self.assertEqual(active_row["r"], "0.001")
        self.assertEqual(pending["current_value"], pending["default_value"])
        self.assertFalse(pending["persisted"])
        self.assertEqual((source / "model.e").read_text(encoding="utf-8"), model_before)

    def test_old_direct_definition_edits_cannot_mutate_recreated_model_lifecycle(self):
        cases = (
            (
                "device",
                lambda _service: None,
                lambda service, _context: service.update_device_parameters(
                    {
                        "block_name": "ACBranch",
                        "row_key": {"name": "diesel_line", "idx": "2"},
                        "revision": service.definition_snapshot.revision,
                        "changes": {"r": 0.0025},
                    }
                ),
            ),
            (
                "measurement",
                lambda _service: None,
                lambda service, _context: service.update_measurement_definition(
                    {
                        "name": "p_gen_diesel_300kw",
                        "revision": service.definition_snapshot.revision,
                        "changes": {"valid": 0},
                    }
                ),
            ),
        )
        for label, prepare, mutate in cases:
            with self.subTest(kind=label):
                outcome = self._run_old_mutation_after_same_id_recreate(prepare, mutate)
                self._assert_retired_mutation_cancelled(outcome)

    def test_old_retry_cannot_mutate_recreated_model_lifecycle(self):
        def prepare(service):
            def fail_model_file(path, text):
                if Path(path).name == "model.e":
                    raise OSError("model file busy")
                return real_atomic_write_text(path, text)

            with patch("simu.service.atomic_write_text", side_effect=fail_model_file):
                service.update_device_parameters(
                    {
                        "block_name": "ACBranch",
                        "row_key": {"name": "diesel_line", "idx": "2"},
                        "revision": service.definition_snapshot.revision,
                        "changes": {"r": 0.0025},
                    }
                )
            return service.manual_definition_changes()["changes"][0]["id"]

        outcome = self._run_old_mutation_after_same_id_recreate(
            prepare,
            lambda service, change_id: service.retry_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [change_id],
                }
            ),
        )

        self._assert_retired_mutation_cancelled(outcome)

    def test_old_reset_cannot_mutate_recreated_model_lifecycle(self):
        def prepare(service):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
            return service.manual_definition_changes()["changes"][0]["id"]

        outcome = self._run_old_mutation_after_same_id_recreate(
            prepare,
            lambda service, change_id: service.reset_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [change_id],
                }
            ),
        )

        self._assert_retired_mutation_cancelled(outcome)

    def test_old_clear_cannot_remove_recreated_model_manual_journal(self):
        def prepare(service):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )

        def configure_new(service):
            service.manual_definition_changes_file.write_text(
                json.dumps({"sentinel": "new-lifecycle"}),
                encoding="utf-8",
            )

        outcome = self._run_old_mutation_after_same_id_recreate(
            prepare,
            lambda service, _context: service.clear_manual_definition_changes(),
            configure_new=configure_new,
        )

        self._assert_retired_mutation_cancelled(outcome)


class ManualDefinitionChangesApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        root = Path(self.workspace.name)
        source = root / "first"
        shutil.copytree(FIXTURE, source)
        self.manager = MultiModelSimulator(
            [SimulationModelSpec("first", source, "First")],
            root / "runtime",
            kernel=lambda _config: None,
        )
        self.server = make_http_server(("127.0.0.1", 0), self.manager, role="simulator")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.workspace.cleanup()

    def _request(self, path: str, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_query_and_reset_selected_manual_changes(self):
        service = self.manager.service_for("first")
        self._request(
            "/api/definitions/device-parameters?model_id=first",
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            },
        )
        status, listed = self._request("/api/definitions/manual-changes?model_id=first")
        self.assertEqual(status, 200)
        self.assertEqual(listed["count"], 1)

        reset_status, reset = self._request(
            "/api/definitions/manual-changes/reset?model_id=first",
            {
                "revision": listed["revision"],
                "change_ids": [listed["changes"][0]["id"]],
            },
        )
        self.assertEqual(reset_status, 200)
        self.assertEqual(reset["reset_count"], 1)
        self.assertEqual(reset["count"], 0)

    def test_retry_pending_manual_change_through_api(self):
        service = self.manager.service_for("first")

        def fail_only_model_file(path, text):
            if Path(path).name == "model.e":
                raise OSError("model file busy")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_only_model_file):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
        listed = service.manual_definition_changes()

        status, retried = self._request(
            "/api/definitions/manual-changes/retry?model_id=first",
            {
                "revision": listed["revision"],
                "change_ids": [listed["changes"][0]["id"]],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(retried["persisted_count"], 1)
        self.assertTrue(retried["changes"][0]["persisted"])


if __name__ == "__main__":
    unittest.main()
