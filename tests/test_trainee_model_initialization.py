from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from shutil import copytree
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simu.generate_simple_model import write_model_dir
from simu.server import make_http_server
from simu.service import MultiModelSimulator, PolarMicrogridSimulator, SimulationModelSpec
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


class TraineeModelInitializationTest(unittest.TestCase):
    def _make_simulator(self, root: Path) -> PolarMicrogridSimulator:
        source = root / "simulator-source"
        copytree(SIMPLE_MODEL_SOURCE, source)
        diagram = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<text id="remote-diagram-marker">REMOTE MODEL DIAGRAM</text>'
            "</svg>"
        )
        (source / "diagram.svg").write_text(diagram, encoding="utf-8")
        return PolarMicrogridSimulator(
            source,
            root / "simulator-runtime",
            kernel=lambda _config: None,
            model_id="remote_model",
            model_name="远端模型",
        )

    def _make_trainee(self, root: Path) -> MultiModelSimulator:
        models_root = root / "trainee-models"
        for model_id in ("local_a", "local_b"):
            write_model_dir(models_root / model_id)
        return MultiModelSimulator(
            [
                SimulationModelSpec("local_a", models_root / "local_a", "本地模型 A"),
                SimulationModelSpec("local_b", models_root / "local_b", "本地模型 B"),
            ],
            runtime_dir=root / "trainee-runtime",
            models_root=models_root,
            kernel=lambda _config: None,
        )

    @staticmethod
    def _post_json(url: str, payload: dict) -> dict:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_model_initialization_overwrites_selected_local_model_and_keeps_selection_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            untouched_model = (trainee.models_root / "local_a" / "model.e").read_bytes()

            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            try:
                simulator_port = simulator_server.server_address[1]
                trainee_port = trainee_server.server_address[1]
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link?model_id=remote_model"
                payload = self._post_json(
                    f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize",
                    {"model_id": "local_b", "link": link},
                )
            finally:
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)

            local_b = trainee.service_for("local_b")
            receive_state = local_b.trainee_receive_state()
            self.assertEqual(payload["model"]["id"], "local_b")
            self.assertEqual(payload["selected_model_id"], "local_b")
            self.assertEqual(payload["active_model_id"], "local_a")
            self.assertEqual(trainee.default_model_id, "local_a")
            self.assertEqual({item["id"] for item in payload["models"]}, {"local_a", "local_b"})
            self.assertTrue(payload["receive_state"]["initialized"])
            self.assertFalse(payload["receive_state"]["active"])
            self.assertTrue(receive_state["initialized"])
            self.assertEqual(receive_state["teacher_model_id"], "remote_model")
            self.assertEqual(
                receive_state["definition_archive_path"],
                "/api/export-definitions?format=json&model_id=remote_model",
            )
            self.assertEqual(
                (trainee.models_root / "local_b" / "model.e").read_bytes(),
                (simulator.sim_dir / "model.e").read_bytes(),
            )
            self.assertEqual(
                (trainee.models_root / "local_b" / "meas.e").read_bytes(),
                (simulator.sim_dir / "meas.e").read_bytes(),
            )
            self.assertEqual(
                (trainee.models_root / "local_b" / "diagram.svg").read_text(encoding="utf-8"),
                (simulator.sim_dir / "diagram.svg").read_text(encoding="utf-8"),
            )
            self.assertEqual((trainee.models_root / "local_a" / "model.e").read_bytes(), untouched_model)

    def test_new_trainee_model_creates_an_uninitialized_name_only_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trainee = self._make_trainee(root)
            source_before = (trainee.models_root / "local_a" / "model.e").read_bytes()
            trainee_server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            trainee_thread.start()
            try:
                trainee_port = trainee_server.server_address[1]
                payload = self._post_json(
                    f"http://127.0.0.1:{trainee_port}/api/trainee/models/create",
                    {"name": "待初始化模型"},
                )
            finally:
                trainee_server.shutdown()
                trainee_server.server_close()
                trainee_thread.join(timeout=5)

            created = trainee.service_for("待初始化模型")
            self.assertEqual(payload["model"]["id"], "待初始化模型")
            self.assertEqual(payload["active_model_id"], "local_a")
            self.assertEqual(trainee.default_model_id, "local_a")
            self.assertFalse(created.trainee_receive_state()["initialized"])
            self.assertFalse(created.trainee_receive_state()["active"])
            self.assertTrue((created.sim_dir / "model.e").exists())
            self.assertTrue((created.sim_dir / "meas.e").exists())
            self.assertTrue((created.sim_dir / "control.e").exists())
            self.assertTrue((created.sim_dir / "diagram.svg").exists())
            self.assertEqual((trainee.models_root / "local_a" / "model.e").read_bytes(), source_before)

    def test_receive_start_requires_initialization_and_does_not_redownload_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            trainee_port = trainee_server.server_address[1]
            try:
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        f"http://127.0.0.1:{trainee_port}/api/trainee/receive",
                        {"model_id": "local_b", "active": True},
                    )
                error_body = raised.exception.read().decode("utf-8")
                self.assertEqual(raised.exception.code, 409)
                self.assertIn("模型初始化", error_body)

                simulator_port = simulator_server.server_address[1]
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link?model_id=remote_model"
                self._post_json(
                    f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize",
                    {"model_id": "local_b", "link": link},
                )

                source_dir = trainee.models_root / "local_b"
                tracked_names = ("model.e", "meas.e", "control.e", "stat.e", "curves.e", "diagram.svg")
                before = {
                    name: (source_dir / name).read_bytes()
                    for name in tracked_names
                }

                simulator_server.shutdown()
                simulator_server.server_close()
                simulator_thread.join(timeout=5)

                started = self._post_json(
                    f"http://127.0.0.1:{trainee_port}/api/trainee/receive",
                    {"model_id": "local_b", "active": True},
                )
                after = {
                    name: (source_dir / name).read_bytes()
                    for name in tracked_names
                }
                stopped = self._post_json(
                    f"http://127.0.0.1:{trainee_port}/api/trainee/receive",
                    {"model_id": "local_b", "active": False},
                )
            finally:
                trainee_server.shutdown()
                trainee_server.server_close()
                trainee_thread.join(timeout=5)
                if simulator_thread.is_alive():
                    simulator_server.shutdown()
                    simulator_server.server_close()
                    simulator_thread.join(timeout=5)

            self.assertTrue(started["active"])
            self.assertTrue(started["initialized"])
            self.assertEqual(before, after)
            self.assertFalse(stopped["active"])
            self.assertTrue(stopped["frozen"])

    def test_model_initialization_is_rejected_while_selected_model_is_receiving(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            trainee.service_for("local_b").set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": True,
                    "interaction_link": "http://teacher/api/trainee-link?model_id=remote_model",
                    "teacher_api_base": "http://teacher",
                    "teacher_model_id": "remote_model",
                    "snapshot_path": "/api/snapshot?model_id=remote_model",
                    "command_path": "/api/student/commands?model_id=remote_model",
                }
            )
            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            try:
                simulator_port = simulator_server.server_address[1]
                trainee_port = trainee_server.server_address[1]
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link?model_id=remote_model"
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize",
                        {"model_id": "local_b", "link": link},
                    )
                error_body = raised.exception.read().decode("utf-8")
            finally:
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)

            self.assertEqual(raised.exception.code, 409)
            self.assertIn("接收中", error_body)


if __name__ == "__main__":
    unittest.main()
