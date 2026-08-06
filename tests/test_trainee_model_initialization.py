from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from shutil import copytree
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import simu.server as server_module
from simu.generate_simple_model import write_model_dir
from simu.server import make_http_server
from simu.service import MultiModelSimulator, PolarMicrogridSimulator, SimulationModelSpec
from simu.trainee_exchange import TraineeRealtimeExchange
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


class RecordingExchange:
    def __init__(self):
        self.invalidated = []
        self.closed = 0

    def invalidate_model(self, model_id):
        self.invalidated.append(model_id)

    def close(self):
        self.closed += 1


class RecordingRenewableManager:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class CoordinatedDefinitionLock:
    """Force the control-commit and model-initialize lock orders to cross."""

    def __init__(self):
        self._lock = threading.RLock()
        self._meta_lock = threading.Lock()
        self._control_seen = False
        self._initializer_seen = False
        self.control_holds_definition = threading.Event()
        self.initializer_waits_for_definition = threading.Event()
        self.allow_control_to_continue = threading.Event()

    def acquire(self, blocking=True, timeout=-1):
        thread_name = threading.current_thread().name
        with self._meta_lock:
            first_control = thread_name == "control-commit" and not self._control_seen
            if first_control:
                self._control_seen = True
            first_initializer = (
                thread_name != "control-commit"
                and self.control_holds_definition.is_set()
                and not self._initializer_seen
            )
            if first_initializer:
                self._initializer_seen = True

        if first_control:
            acquired = self._lock.acquire(blocking, timeout) if timeout != -1 else self._lock.acquire(blocking)
            if acquired:
                self.control_holds_definition.set()
                if not self.allow_control_to_continue.wait(timeout=2.0):
                    self._lock.release()
                    raise TimeoutError("control commit was not released by the test")
            return acquired
        if first_initializer:
            self.initializer_waits_for_definition.set()
            return self._lock.acquire(timeout=0.75)
        return self._lock.acquire(blocking, timeout) if timeout != -1 else self._lock.acquire(blocking)

    def release(self):
        self._lock.release()

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError("model initialization deadlocked on definition_update_lock")
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.release()
        return False


class TraineeModelInitializationTest(unittest.TestCase):
    @staticmethod
    def _tree_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

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
            exchange = RecordingExchange()
            renewable = RecordingRenewableManager()

            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(
                ("127.0.0.1", 0),
                trainee,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
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
            self.assertEqual(exchange.invalidated, ["local_b"])

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

    def test_downloaded_initialization_cannot_write_deleted_recreated_service_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            old_target = trainee.service_for("local_b")
            exchange = RecordingExchange()
            renewable = RecordingRenewableManager()
            archive_started = threading.Event()
            release_archive = threading.Event()
            original_make_archive = server_module.make_definition_archive

            def blocking_make_archive(service):
                archive_started.set()
                self.assertTrue(release_archive.wait(timeout=3.0))
                return original_make_archive(service)

            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(
                ("127.0.0.1", 0),
                trainee,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            simulator_port = simulator_server.server_address[1]
            trainee_port = trainee_server.server_address[1]
            link = f"http://127.0.0.1:{simulator_port}/api/trainee-link?model_id=remote_model"
            result = {}

            def initialize_old_target():
                try:
                    result["value"] = self._post_json(
                        f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize",
                        {"model_id": "local_b", "link": link},
                    )
                except HTTPError as exc:
                    result["status"] = exc.code
                    result["body"] = exc.read().decode("utf-8")
                except Exception as exc:
                    result["error"] = exc

            initialize_thread = threading.Thread(target=initialize_old_target, daemon=True)
            try:
                with patch.object(
                    server_module,
                    "make_definition_archive",
                    side_effect=blocking_make_archive,
                ):
                    initialize_thread.start()
                    self.assertTrue(archive_started.wait(timeout=3.0))

                    trainee.delete_model("local_b")
                    trainee.create_model_slot("local_b")
                    new_target = trainee.service_for("local_b")
                    source_before = self._tree_bytes(new_target.sim_dir)
                    runtime_before = self._tree_bytes(new_target.runtime_dir)

                    release_archive.set()
                    initialize_thread.join(timeout=5.0)
                    self.assertFalse(initialize_thread.is_alive())
            finally:
                release_archive.set()
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)
                initialize_thread.join(timeout=2.0)

            self.assertNotIn("value", result)
            self.assertNotIn("error", result)
            self.assertEqual(result.get("status"), 409)
            self.assertRegex(result.get("body", ""), "生命周期|失效|删除|退休")
            self.assertIsNot(new_target, old_target)
            self.assertFalse(old_target.service_instance_active())
            self.assertEqual(self._tree_bytes(new_target.sim_dir), source_before)
            self.assertEqual(self._tree_bytes(new_target.runtime_dir), runtime_before)

    def test_downloaded_archive_parsing_does_not_hold_definition_or_service_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            target = trainee.service_for("local_b")
            parse_started = threading.Event()
            release_parse = threading.Event()
            original_read_zip_text = server_module._read_zip_text
            parse_blocked = False

            def blocking_read_zip_text(archive, entry_name, required=True):
                nonlocal parse_blocked
                if not parse_blocked:
                    parse_blocked = True
                    parse_started.set()
                    self.assertTrue(release_parse.wait(timeout=3.0))
                return original_read_zip_text(archive, entry_name, required)

            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            simulator_port = simulator_server.server_address[1]
            trainee_port = trainee_server.server_address[1]
            link = f"http://127.0.0.1:{simulator_port}/api/trainee-link?model_id=remote_model"
            result = {}

            def initialize_model():
                try:
                    result["value"] = self._post_json(
                        f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize",
                        {"model_id": "local_b", "link": link},
                    )
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    result["error"] = exc

            initialize_thread = threading.Thread(target=initialize_model, daemon=True)
            definition_acquired = False
            service_acquired = False
            try:
                with patch.object(server_module, "_read_zip_text", side_effect=blocking_read_zip_text):
                    initialize_thread.start()
                    self.assertTrue(parse_started.wait(timeout=3.0))
                    definition_acquired = target.definition_update_lock.acquire(timeout=0.5)
                    if definition_acquired:
                        service_acquired = target.lock.acquire(timeout=0.5)
                        if service_acquired:
                            target.lock.release()
                        target.definition_update_lock.release()
                    release_parse.set()
                    initialize_thread.join(timeout=5.0)
                    self.assertFalse(initialize_thread.is_alive())
            finally:
                release_parse.set()
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)
                initialize_thread.join(timeout=2.0)

            self.assertTrue(definition_acquired, "ZIP parsing held definition_update_lock")
            self.assertTrue(service_acquired, "ZIP parsing held service.lock")
            self.assertNotIn("error", result)
            self.assertEqual(result["value"]["selected_model_id"], "local_b")

    def test_model_initialization_and_control_commit_use_one_lock_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            target = trainee.service_for("local_b")
            coordinated_lock = CoordinatedDefinitionLock()
            target.definition_update_lock = coordinated_lock
            exchange = TraineeRealtimeExchange(trainee, start_worker=False)
            renewable = RecordingRenewableManager()
            generation = exchange.control_generation("local_b")
            control_errors = []
            initialize_errors = []
            initialize_result = {}

            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(
                ("127.0.0.1", 0),
                trainee,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            simulator_port = simulator_server.server_address[1]
            trainee_port = trainee_server.server_address[1]
            link = f"http://127.0.0.1:{simulator_port}/api/trainee-link?model_id=remote_model"

            def commit_control_generation():
                try:
                    with exchange.control_generation_guard("local_b", generation) as valid:
                        if not valid:
                            raise AssertionError("control generation unexpectedly changed")
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    control_errors.append(exc)

            def initialize_model():
                try:
                    initialize_result.update(
                        self._post_json(
                            f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize",
                            {"model_id": "local_b", "link": link},
                        )
                    )
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    initialize_errors.append(exc)

            control_thread = threading.Thread(
                target=commit_control_generation,
                name="control-commit",
                daemon=True,
            )
            initialize_thread = threading.Thread(target=initialize_model, daemon=True)
            try:
                control_thread.start()
                self.assertTrue(coordinated_lock.control_holds_definition.wait(timeout=2.0))
                initialize_thread.start()
                self.assertTrue(coordinated_lock.initializer_waits_for_definition.wait(timeout=3.0))
                coordinated_lock.allow_control_to_continue.set()
                control_thread.join(timeout=3.0)
                initialize_thread.join(timeout=3.0)
            finally:
                coordinated_lock.allow_control_to_continue.set()
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)
                exchange.close()

            self.assertFalse(control_thread.is_alive(), "control commit did not complete")
            self.assertFalse(initialize_thread.is_alive(), "model initialization did not complete")
            self.assertEqual(control_errors, [])
            self.assertEqual(initialize_errors, [])
            self.assertEqual(initialize_result["selected_model_id"], "local_b")


if __name__ == "__main__":
    unittest.main()
