from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from simu.definition_editing import (
    atomic_write_text as real_atomic_write_text,
    render_ebook_aligned,
)
from simu.server import make_http_server
from simu.service import EBook, MultiModelSimulator, PolarMicrogridSimulator, SimulationModelSpec


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"
CHANGE_FILE = "manual_overrides.json"


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

    @staticmethod
    def _device_row(service, block_name="ACBranch", name="diesel_line"):
        return next(
            row
            for row in service.definition_snapshot.model_book.data[block_name].data
            if row.get("name") == name
        )

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
                except Exception as exc:  # pragma: no cover - asserted below.
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

    def test_device_and_measurement_changes_persist_in_runtime_overlay(self):
        _root, source, runtime, service = self._make_service()
        source_before = self._tree_bytes(source)
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
        self.assertEqual(set(by_field), {"r", "weight", "valid"})
        self.assertTrue((runtime / CHANGE_FILE).is_file())
        self.assertFalse((source / CHANGE_FILE).exists())
        self.assertEqual(self._tree_bytes(source), source_before)

        reloaded = PolarMicrogridSimulator(
            source,
            runtime,
            model_id="manual",
            kernel=lambda _config: None,
        )
        self.assertEqual(self._device_row(reloaded)["r"], "0.0025")
        measurement = next(
            row
            for row in reloaded.definitions()["measurement"]
            if row["name"] == "p_gen_diesel_300kw"
        )
        self.assertEqual(float(measurement["weight"]), 2500.0)
        self.assertEqual(int(measurement["valid"]), 0)
        self.assertEqual(reloaded.manual_definition_changes()["count"], 3)

    def test_reset_selected_changes_restores_source_defaults_and_keeps_other_overrides(self):
        _root, source, runtime, service = self._make_service()
        source_before = self._tree_bytes(source)
        service.clock.state = "running"
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

        active_row = self._device_row(service)
        measurement = next(
            row
            for row in service.definitions()["measurement"]
            if row["name"] == "p_gen_diesel_300kw"
        )
        self.assertEqual(result["reset_count"], 2)
        self.assertEqual(active_row["r"], "0.001")
        self.assertEqual(active_row["x"], "0.006")
        self.assertEqual(int(measurement["valid"]), 1)
        self.assertEqual(float(measurement["weight"]), 2500.0)
        self.assertEqual(set(self._by_field(service.manual_definition_changes())), {"x", "weight"})
        self.assertEqual(service.clock.state, "running")
        self.assertEqual(self._tree_bytes(source), source_before)

        reloaded = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        self.assertEqual(self._device_row(reloaded)["r"], "0.001")
        self.assertEqual(self._device_row(reloaded)["x"], "0.006")
        self.assertEqual(set(self._by_field(reloaded.manual_definition_changes())), {"x", "weight"})

    def test_model_change_reset_clears_runtime_overrides_without_touching_source(self):
        _root, source, _runtime, service = self._make_service()
        source_before = self._tree_bytes(source)
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "changes": {"r": 0.0025},
            }
        )
        self.assertTrue(service.manual_definition_changes_file.exists())

        service.clock.state = "stopped"
        service.reset_runtime_for_model_change()

        self.assertEqual(service.manual_definition_changes()["count"], 0)
        self.assertFalse(service.manual_definition_changes_file.exists())
        self.assertEqual(self._device_row(service)["r"], "0.001")
        self.assertEqual(self._tree_bytes(source), source_before)

    def test_initial_overlay_write_failure_can_be_retried_without_e_file_writes(self):
        _root, source, runtime, service = self._make_service()
        source_before = self._tree_bytes(source)

        def fail_overlay(path, text):
            if Path(path).name == CHANGE_FILE:
                raise OSError("override storage unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_overlay):
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
        self.assertFalse((runtime / CHANGE_FILE).exists())
        self.assertEqual(self._tree_bytes(source), source_before)

        retried = service.retry_manual_definition_changes(
            {
                "revision": service.definition_snapshot.revision,
                "change_ids": [pending["id"]],
            }
        )
        self.assertEqual(retried["persisted_count"], 1)
        self.assertTrue((runtime / CHANGE_FILE).exists())
        self.assertEqual(self._tree_bytes(source), source_before)

        reloaded = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        self.assertEqual(self._device_row(reloaded)["r"], "0.0025")

    def test_final_overlay_write_failure_replays_pending_value_after_restart(self):
        _root, source, runtime, service = self._make_service()
        writes = 0

        def fail_second_overlay_write(path, text):
            nonlocal writes
            if Path(path).name == CHANGE_FILE:
                writes += 1
                if writes == 2:
                    raise OSError("override finalization unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_second_overlay_write):
            result = service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )

        self.assertFalse(result["persisted"])
        self.assertTrue(result["change_record_persisted"])
        self.assertTrue((runtime / CHANGE_FILE).exists())
        reloaded = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        self.assertEqual(self._device_row(reloaded)["r"], "0.0025")
        self.assertTrue(reloaded.manual_definition_changes()["changes"][0]["persisted"])

    def test_partial_reset_finalization_failure_recovers_default_and_other_override(self):
        _root, source, runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025, "x": 0.006},
            }
        )
        changes = self._by_field(service.manual_definition_changes())
        writes = 0

        def fail_second_overlay_write(path, text):
            nonlocal writes
            if Path(path).name == CHANGE_FILE:
                writes += 1
                if writes == 2:
                    raise OSError("reset finalization unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_second_overlay_write):
            result = service.reset_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [changes["r"]["id"]],
                }
            )

        self.assertFalse(result["persisted"])
        self.assertEqual(self._device_row(service)["r"], "0.001")
        self.assertEqual(self._device_row(service)["x"], "0.006")
        reloaded = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)
        self.assertEqual(self._device_row(reloaded)["r"], "0.001")
        self.assertEqual(self._device_row(reloaded)["x"], "0.006")
        self.assertEqual(set(self._by_field(reloaded.manual_definition_changes())), {"x"})

    def test_external_source_replacement_archives_stale_overlay(self):
        _root, source, runtime, service = self._make_service()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": service.definition_snapshot.revision,
                "changes": {"r": 0.0025},
            }
        )
        source_book = EBook(source / "model.e")
        source_row = next(
            row
            for row in source_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        source_row["r"] = "0.0035"
        real_atomic_write_text(source / "model.e", render_ebook_aligned(source_book))

        reloaded = PolarMicrogridSimulator(source, runtime, model_id="manual", kernel=lambda _config: None)

        self.assertEqual(self._device_row(reloaded)["r"], "0.0035")
        self.assertEqual(reloaded.manual_definition_changes()["count"], 0)
        self.assertFalse((runtime / CHANGE_FILE).exists())
        self.assertTrue(list(runtime.glob("manual_overrides.stale.*.json")))

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
                self._assert_retired_mutation_cancelled(
                    self._run_old_mutation_after_same_id_recreate(prepare, mutate)
                )

    def test_old_retry_reset_and_clear_cannot_mutate_recreated_model_lifecycle(self):
        def prepare_pending(service):
            def fail_overlay(path, text):
                if Path(path).name == CHANGE_FILE:
                    raise OSError("override unavailable")
                return real_atomic_write_text(path, text)

            with patch("simu.service.atomic_write_text", side_effect=fail_overlay):
                service.update_device_parameters(
                    {
                        "block_name": "ACBranch",
                        "row_key": {"name": "diesel_line", "idx": "2"},
                        "revision": service.definition_snapshot.revision,
                        "changes": {"r": 0.0025},
                    }
                )
            return service.manual_definition_changes()["changes"][0]["id"]

        self._assert_retired_mutation_cancelled(
            self._run_old_mutation_after_same_id_recreate(
                prepare_pending,
                lambda service, change_id: service.retry_manual_definition_changes(
                    {
                        "revision": service.definition_snapshot.revision,
                        "change_ids": [change_id],
                    }
                ),
            )
        )

        def prepare_saved(service):
            service.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
            return service.manual_definition_changes()["changes"][0]["id"]

        self._assert_retired_mutation_cancelled(
            self._run_old_mutation_after_same_id_recreate(
                prepare_saved,
                lambda service, change_id: service.reset_manual_definition_changes(
                    {
                        "revision": service.definition_snapshot.revision,
                        "change_ids": [change_id],
                    }
                ),
            )
        )

        def configure_new(service):
            service.manual_definition_changes_file.write_text(
                json.dumps({"sentinel": "new-lifecycle"}),
                encoding="utf-8",
            )

        self._assert_retired_mutation_cancelled(
            self._run_old_mutation_after_same_id_recreate(
                prepare_saved,
                lambda service, _change_id: service.clear_manual_definition_changes(),
                configure_new=configure_new,
            )
        )


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

        def fail_overlay(path, text):
            if Path(path).name == CHANGE_FILE:
                raise OSError("override unavailable")
            return real_atomic_write_text(path, text)

        with patch("simu.service.atomic_write_text", side_effect=fail_overlay):
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
