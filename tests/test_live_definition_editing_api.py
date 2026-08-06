from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simu.server import make_http_server
from simu.service import MultiModelSimulator, SimulationModelSpec


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"


class LiveDefinitionEditingApiTest(unittest.TestCase):
    @staticmethod
    def _tree_bytes(root: Path):
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def _make_manager(self):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        first = root / "first"
        second = root / "second"
        shutil.copytree(FIXTURE, first)
        shutil.copytree(FIXTURE, second)
        manager = MultiModelSimulator(
            [
                SimulationModelSpec("first", first, "First"),
                SimulationModelSpec("second", second, "Second"),
            ],
            root / "runtime",
            kernel=lambda _config: None,
        )
        self.addCleanup(workspace.cleanup)
        return manager

    def _post(self, base: str, path: str, payload: dict):
        request = Request(
            f"{base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def _get(self, base: str, path: str):
        with urlopen(f"{base}{path}", timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def _serve(self, manager, role="simulator", sim_url=None):
        server = make_http_server(("127.0.0.1", 0), manager, role=role, sim_url=sim_url)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_simulator_device_route_updates_only_the_selected_model_while_running(self):
        manager = self._make_manager()
        first = manager.service_for("first")
        second = manager.service_for("second")
        first.clock.state = "running"
        second_before = second.definition_snapshot.revision
        base = self._serve(manager)

        status, result = self._post(
            base,
            "/api/definitions/device-parameters",
            {
                "model_id": "first",
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line"},
                "changes": {"r": 0.006},
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["model_id"], "first")
        self.assertTrue(result["memory_updated"])
        self.assertTrue(result["persisted"])
        self.assertEqual(result["record"]["r"], 0.006)
        self.assertEqual(result["static_meta"]["definitions"]["revision"], result["revision"])
        self.assertEqual(first.clock.state, "running")
        self.assertEqual(second.definition_snapshot.revision, second_before)

    def test_simulator_measurement_route_updates_sigma_weight_and_validity(self):
        manager = self._make_manager()
        base = self._serve(manager)

        status, result = self._post(
            base,
            "/api/definitions/measurement",
            {
                "model_id": "second",
                "name": "p_gen_diesel_300kw",
                "changes": {"error_sigma": 0.04, "valid": 0},
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["model_id"], "second")
        self.assertAlmostEqual(result["record"]["error_sigma"], 0.04)
        self.assertAlmostEqual(float(result["record"]["weight"]), 625.0)
        self.assertEqual(result["record"]["valid"], 0)
        self.assertEqual(result["static_meta"]["device_parameters"]["revision"], result["revision"])

    def test_definition_edit_routes_translate_validation_failures_to_http_400(self):
        manager = self._make_manager()
        base = self._serve(manager)

        with self.assertRaises(HTTPError) as caught:
            self._post(
                base,
                "/api/definitions/device-parameters",
                {
                    "model_id": "first",
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line"},
                    "changes": {"i_node": 99},
                },
            )

        self.assertEqual(caught.exception.code, 400)
        error = json.loads(caught.exception.read().decode("utf-8"))
        self.assertIn("not editable", error["error"])

    def test_old_definition_edit_request_maps_retired_lifecycle_to_http_409(self):
        manager = self._make_manager()
        old_service = manager.service_for("first")
        base = self._serve(manager)
        original_service_for = manager.service_for
        captured_old_service = threading.Event()
        release_request = threading.Event()
        capture_consumed = threading.Event()

        def coordinated_service_for(model_id=None):
            resolved = original_service_for(model_id)
            if (
                str(model_id or "") == "first"
                and not capture_consumed.is_set()
                and threading.current_thread() is not threading.main_thread()
            ):
                capture_consumed.set()
                captured_old_service.set()
                self.assertTrue(release_request.wait(timeout=3.0))
            return resolved

        manager.service_for = coordinated_service_for
        request_result = {}

        def send_old_request():
            try:
                request_result["value"] = self._post(
                    base,
                    "/api/definitions/device-parameters",
                    {
                        "model_id": "first",
                        "block_name": "ACBranch",
                        "row_key": {"name": "diesel_line", "idx": "2"},
                        "revision": old_service.definition_snapshot.revision,
                        "changes": {"r": 0.0025},
                    },
                )
            except HTTPError as exc:
                request_result["status"] = exc.code
                request_result["body"] = json.loads(exc.read().decode("utf-8"))
            except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                request_result["error"] = exc

        worker = threading.Thread(target=send_old_request, daemon=True)
        worker.start()
        try:
            self.assertTrue(captured_old_service.wait(timeout=2.0))
            manager.delete_model("first")
            manager.create_model_slot("first")
            new_service = original_service_for("first")
            snapshot_before = new_service.definition_snapshot
            source_before = self._tree_bytes(new_service.sim_dir)
            runtime_before = self._tree_bytes(new_service.runtime_dir)

            release_request.set()
            worker.join(timeout=3.0)
            self.assertFalse(worker.is_alive())
        finally:
            release_request.set()
            worker.join(timeout=2.0)

        self.assertNotIn("value", request_result)
        self.assertNotIn("error", request_result)
        self.assertEqual(request_result.get("status"), 409)
        self.assertRegex(str(request_result.get("body", {}).get("error", "")), "生命周期|失效|删除|退休")
        self.assertFalse(old_service.service_instance_active())
        self.assertIs(new_service.definition_snapshot, snapshot_before)
        self.assertEqual(self._tree_bytes(new_service.sim_dir), source_before)
        self.assertEqual(self._tree_bytes(new_service.runtime_dir), runtime_before)

    def test_measurement_route_translates_stale_revision_to_http_409(self):
        manager = self._make_manager()
        service = manager.service_for("first")
        base = self._serve(manager)
        initial_revision = service.definition_snapshot.revision

        status, result = self._post(
            base,
            "/api/definitions/measurement",
            {
                "model_id": "first",
                "name": "p_gen_diesel_300kw",
                "revision": initial_revision,
                "changes": {"weight": 400},
            },
        )
        self.assertEqual(status, 200)

        with self.assertRaises(HTTPError) as caught:
            self._post(
                base,
                "/api/definitions/measurement",
                {
                    "model_id": "first",
                    "name": "p_gen_diesel_300kw",
                    "revision": initial_revision,
                    "changes": {"weight": 625},
                },
            )

        self.assertEqual(caught.exception.code, 409)
        error = json.loads(caught.exception.read().decode("utf-8"))
        self.assertIn("revision", error["error"])
        self.assertEqual(error["current_revision"], result["revision"])

    def test_device_route_translates_stale_revision_to_http_409(self):
        manager = self._make_manager()
        service = manager.service_for("first")
        base = self._serve(manager)
        initial_revision = service.definition_snapshot.revision

        status, result = self._post(
            base,
            "/api/definitions/device-parameters",
            {
                "model_id": "first",
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": initial_revision,
                "changes": {"r": 0.0025},
            },
        )
        self.assertEqual(status, 200)

        with self.assertRaises(HTTPError) as caught:
            self._post(
                base,
                "/api/definitions/device-parameters",
                {
                    "model_id": "first",
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line", "idx": "2"},
                    "revision": initial_revision,
                    "changes": {"r": 0.0035},
                },
            )

        self.assertEqual(caught.exception.code, 409)
        error = json.loads(caught.exception.read().decode("utf-8"))
        self.assertIn("revision", error["error"])
        self.assertEqual(error["current_revision"], result["revision"])

    def test_trainee_definition_routes_edit_and_reset_the_selected_local_model_without_proxying(self):
        manager = self._make_manager()
        first = manager.service_for("first")
        second = manager.service_for("second")
        first_before = first.definition_snapshot.revision
        second_before = second.definition_snapshot.revision
        base = self._serve(
            manager,
            role="trainee",
            sim_url="http://127.0.0.1:1",
        )

        status, result = self._post(
            base,
            "/api/definitions/device-parameters",
            {
                "model_id": "first",
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "revision": first_before,
                "changes": {"r": 0.006},
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["model_id"], "first")
        self.assertEqual(result["record"]["r"], 0.006)
        self.assertEqual(first.definition_snapshot.revision, first_before + 1)
        self.assertEqual(second.definition_snapshot.revision, second_before)

        status, changes = self._get(
            base,
            "/api/definitions/manual-changes?model_id=first",
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(changes["changes"]), 1)
        self.assertEqual(changes["changes"][0]["field"], "r")
        self.assertEqual(float(changes["changes"][0]["current_value"]), 0.006)

        status, reset = self._post(
            base,
            "/api/definitions/manual-changes/reset",
            {
                "model_id": "first",
                "revision": changes["revision"],
                "change_ids": [changes["changes"][0]["id"]],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(reset["changes"], [])
        restored = next(
            row
            for row in first.definition_snapshot.model_book.data["ACBranch"].data
            if row["name"] == "diesel_line"
        )
        self.assertEqual(restored["r"], "0.001")

    def test_trainee_measurement_definition_route_updates_the_local_measurement(self):
        manager = self._make_manager()
        first = manager.service_for("first")
        base = self._serve(
            manager,
            role="trainee",
            sim_url="http://127.0.0.1:1",
        )

        status, result = self._post(
            base,
            "/api/definitions/measurement",
            {
                "model_id": "first",
                "name": "p_gen_diesel_300kw",
                "revision": first.definition_snapshot.revision,
                "changes": {"error_sigma": 0.04, "valid": 0},
            },
        )

        self.assertEqual(status, 200)
        self.assertAlmostEqual(result["record"]["error_sigma"], 0.04)
        self.assertAlmostEqual(float(result["record"]["weight"]), 625.0)
        self.assertEqual(result["record"]["valid"], 0)


if __name__ == "__main__":
    unittest.main()
