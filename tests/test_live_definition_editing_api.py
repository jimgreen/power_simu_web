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

    def _serve(self, manager, role="simulator"):
        server = make_http_server(("127.0.0.1", 0), manager, role=role)
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

    def test_trainee_role_does_not_expose_definition_edit_routes(self):
        manager = self._make_manager()
        base = self._serve(manager, role="trainee")

        for path, payload in (
            (
                "/api/definitions/device-parameters",
                {
                    "model_id": "first",
                    "block_name": "ACBranch",
                    "row_key": {"name": "diesel_line"},
                    "changes": {"r": 0.006},
                },
            ),
            (
                "/api/definitions/measurement",
                {
                    "model_id": "first",
                    "name": "p_gen_diesel_300kw",
                    "changes": {"valid": 0},
                },
            ),
        ):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self._post(base, path, payload)
            self.assertIn(caught.exception.code, (403, 404))


if __name__ == "__main__":
    unittest.main()
