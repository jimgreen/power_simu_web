from __future__ import annotations

import json
import base64
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simu.generate_simple_model import write_model_dir
from simu.server import make_definition_archive, make_http_server
from simu.service import MultiModelSimulator, SimulationModelSpec


class TraineeMultiSimulatorReceiveTest(unittest.TestCase):
    def _make_manager(self, root: Path) -> MultiModelSimulator:
        source_root = root / "source"
        for model_id in ("alpha", "beta"):
            write_model_dir(source_root / model_id)
        return MultiModelSimulator(
            [
                SimulationModelSpec("alpha", source_root / "alpha", "Alpha"),
                SimulationModelSpec("beta", source_root / "beta", "Beta"),
            ],
            runtime_dir=root / "runtime",
            models_root=source_root,
            kernel=lambda _config: None,
        )

    def test_receive_connections_are_isolated_and_persisted_per_trainee_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = self._make_manager(root)

            alpha = manager.service_for("alpha").set_trainee_receive_state(
                {
                    "active": True,
                    "interaction_link": "http://teacher-a/api/trainee-link?model_id=alpha",
                    "teacher_api_base": "http://teacher-a",
                    "teacher_model_id": "alpha",
                    "teacher_model_name": "Alpha",
                    "snapshot_path": "/api/snapshot?model_id=alpha",
                    "command_path": "/api/student/commands?model_id=alpha",
                    "measurement_delta_path": "/api/measurements/delta?model_id=alpha",
                }
            )
            beta = manager.service_for("beta").set_trainee_receive_state(
                {
                    "active": True,
                    "interaction_link": "http://teacher-b/api/trainee-link?model_id=beta",
                    "teacher_api_base": "http://teacher-b",
                    "teacher_model_id": "beta",
                    "teacher_model_name": "Beta",
                    "snapshot_path": "/api/snapshot?model_id=beta",
                    "command_path": "/api/student/commands?model_id=beta",
                    "measurement_delta_path": "/api/measurements/delta?model_id=beta",
                }
            )

            self.assertEqual(alpha["teacher_api_base"], "http://teacher-a")
            self.assertEqual(beta["teacher_api_base"], "http://teacher-b")
            self.assertEqual(manager.trainee_receive_states()["alpha"]["snapshot_path"], "/api/snapshot?model_id=alpha")
            self.assertEqual(manager.trainee_receive_states()["beta"]["snapshot_path"], "/api/snapshot?model_id=beta")

            restarted = self._make_manager(root)
            self.assertTrue(restarted.service_for("alpha").trainee_receive_state()["active"])
            self.assertTrue(restarted.service_for("beta").trainee_receive_state()["active"])
            self.assertEqual(
                restarted.service_for("alpha").trainee_receive_state()["teacher_api_base"],
                "http://teacher-a",
            )
            self.assertEqual(
                restarted.service_for("beta").trainee_receive_state()["teacher_api_base"],
                "http://teacher-b",
            )

    def test_trainee_receive_state_api_is_model_scoped_for_shared_web_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            server = make_http_server(("127.0.0.1", 0), manager, role="trainee")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps(
                    {
                        "active": True,
                        "interaction_link": "http://teacher-alpha/api/trainee-link?model_id=alpha",
                        "teacher_api_base": "http://teacher-alpha",
                        "teacher_model_id": "alpha",
                        "teacher_model_name": "Alpha",
                        "snapshot_path": "/api/snapshot?model_id=alpha",
                        "command_path": "/api/student/commands?model_id=alpha",
                    }
                ).encode("utf-8")
                request = Request(
                    f"http://127.0.0.1:{port}/api/trainee/receive-state?model_id=alpha",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=5) as response:
                    saved = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"http://127.0.0.1:{port}/api/trainee/receive-state?model_id=alpha",
                    timeout=5,
                ) as response:
                    fetched = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"http://127.0.0.1:{port}/api/trainee/receive-state?model_id=beta",
                    timeout=5,
                ) as response:
                    beta = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

        self.assertTrue(saved["active"])
        self.assertEqual(fetched["teacher_api_base"], "http://teacher-alpha")
        self.assertFalse(beta["active"])
        self.assertEqual(beta["teacher_api_base"], "")

    def test_trainee_rejects_definition_update_while_model_is_receiving(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = self._make_manager(root)
            manager.service_for("alpha").set_trainee_receive_state(
                {
                    "active": True,
                    "interaction_link": "http://teacher-alpha/api/trainee-link?model_id=alpha",
                    "teacher_api_base": "http://teacher-alpha",
                    "teacher_model_id": "alpha",
                    "teacher_model_name": "Alpha",
                    "snapshot_path": "/api/snapshot?model_id=alpha",
                    "command_path": "/api/student/commands?model_id=alpha",
                }
            )
            server = make_http_server(("127.0.0.1", 0), manager, role="trainee")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                filename, archive_data = make_definition_archive(manager.service_for("beta"))
                payload = {
                    "model_id": "alpha",
                    "filename": filename,
                    "data_base64": base64.b64encode(archive_data).decode("ascii"),
                }
                request = Request(
                    f"http://127.0.0.1:{port}/api/models/import-definitions",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=5)
                body = raised.exception.read().decode("utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(raised.exception.code, 400)
        self.assertIn("接收中", body)

    def test_trainee_server_resolves_simulator_link_and_fetches_first_snapshot(self):
        with tempfile.TemporaryDirectory() as simulator_root, tempfile.TemporaryDirectory() as trainee_root:
            simulator = self._make_manager(Path(simulator_root))
            trainee = self._make_manager(Path(trainee_root))
            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            try:
                simulator_port = simulator_server.server_address[1]
                trainee_port = trainee_server.server_address[1]
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link?model_id=alpha"
                body = json.dumps({"link": link}).encode("utf-8")
                request = Request(
                    f"http://127.0.0.1:{trainee_port}/api/trainee/connect",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()

        self.assertEqual(payload["connection"]["model_id"], "alpha")
        self.assertEqual(payload["connection"]["teacher_api_base"], f"http://127.0.0.1:{simulator_port}")
        self.assertEqual(payload["snapshot"]["model"]["id"], "alpha")


def test_trainee_frontend_keeps_receive_contexts_per_model():
    script = (Path(__file__).resolve().parents[1] / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert "modelContexts:" in script
    assert "function activeModelContext" in script
    assert "function persistActiveModelContext" in script
    assert "function restoreModelContext" in script
    assert "async function saveTraineeReceiveState" in script
    assert "async function syncActiveReceiveStateFromBackend" in script
    assert "async function syncActiveReceiveStateBeforeRefresh" in script
    assert "await syncActiveReceiveStateBeforeRefresh();" in script
    assert "/api/trainee/receive-state?model_id=" in script
    assert "/api/trainee/connect" in script
    assert "/api/trainee/snapshot" in script
    assert "/api/trainee/commands" in script
    assert "fetch(url.href" not in script
    assert "fetch(connectionApiUrl(connection" not in script
    assert "selector.disabled = models.length <= 1;" in script
    assert "selector.disabled = state.receiveMode || models.length <= 1;" not in script
    assert "await saveTraineeReceiveState(activeModelIdBeforeReceive, { active: true" in script
    assert "await saveTraineeReceiveState(state.activeModelId, { active: false" in script
    assert "persistActiveModelContext();" in script


if __name__ == "__main__":
    unittest.main()
