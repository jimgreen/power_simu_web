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
from simu.simulator_proxy import make_simulator_proxy_server
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


class RunningSingleServiceManager:
    def __init__(self, model_id: str, base_url: str) -> None:
        self.model_id = model_id
        self.base_url = base_url

    def model_info(self, model_id):
        if str(model_id) != self.model_id:
            raise KeyError(model_id)
        return {
            "id": self.model_id,
            "name": self.model_id,
            "service": {
                "state": "running",
                "healthy": True,
                "base_url": self.base_url,
            },
        }

    def catalog(self):
        return {"models": [self.model_info(self.model_id)], "active_model_id": self.model_id}

    def close(self):
        return None


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
    def _device_row(
        service: PolarMicrogridSimulator,
        block_name: str,
        name: str,
    ) -> dict:
        return next(
            row
            for row in service.definition_snapshot.model_book.data[block_name].data
            if row.get("name") == name
        )

    @staticmethod
    def _measurement(service: PolarMicrogridSimulator, name: str) -> dict:
        return next(
            row
            for row in service.definitions()["measurement"]
            if row.get("name") == name
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
            local_b_before_initialize = trainee.service_for("local_b")
            command_result = local_b_before_initialize.apply_student_commands(
                {
                    "set_values": [
                        {
                            "dev_type": "ESS",
                            "dev_name": "ess01",
                            "set_type": "p_set",
                            "set_value": 20,
                        }
                    ]
                },
                source="trainee-ui",
            )
            self.assertEqual(command_result["set_values"], 1)
            self.assertTrue(local_b_before_initialize.command_history)
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
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link"
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
            self.assertEqual(local_b.command_history, [])
            self.assertEqual(
                json.loads(local_b.commands_file.read_text(encoding="utf-8")),
                [],
            )
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
                receive_state["snapshot_path"],
                "/api/snapshot?model_id=remote_model&trainee_view=1",
            )
            self.assertEqual(
                receive_state["measurement_delta_path"],
                "/api/measurements/delta?model_id=remote_model&trainee_view=1",
            )
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

    def test_model_initialization_uses_simulator_effective_definitions_as_trainee_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            simulator_source_before = self._tree_bytes(simulator.sim_dir)

            simulator.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"idx": "2", "name": "diesel_line"},
                    "revision": simulator.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
                }
            )
            simulator.update_device_parameters(
                {
                    "block_name": "ACGenerator",
                    "row_key": {"idx": "2", "name": "diesel_300kw"},
                    "revision": simulator.definition_snapshot.revision,
                    "changes": {"run_stat": 0, "p_set": 95},
                }
            )
            simulator.update_measurement_definition(
                {
                    "name": "p_gen_diesel_300kw",
                    "revision": simulator.definition_snapshot.revision,
                    "changes": {
                        "error_sigma": 0.02,
                        "status": "fixed",
                        "fixed_value": 12.5,
                    },
                }
            )

            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            proxy_server = None
            proxy_thread = None
            try:
                simulator_port = simulator_server.server_address[1]
                trainee_port = trainee_server.server_address[1]
                proxy_static = root / "proxy-static"
                proxy_static.mkdir()
                (proxy_static / "index.html").write_text("proxy-ui", encoding="utf-8")
                proxy_server = make_simulator_proxy_server(
                    ("127.0.0.1", 0),
                    RunningSingleServiceManager(
                        "remote_model",
                        f"http://127.0.0.1:{simulator_port}",
                    ),
                    static_root=proxy_static,
                )
                proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
                proxy_thread.start()
                link = (
                    f"http://127.0.0.1:{proxy_server.server_address[1]}"
                    "/api/trainee-link?model_id=remote_model"
                )
                self._post_json(
                    f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize",
                    {"model_id": "local_b", "link": link},
                )
            finally:
                if proxy_server is not None:
                    proxy_server.shutdown()
                    proxy_server.server_close()
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)
                if proxy_thread is not None:
                    proxy_thread.join(timeout=5)

            local_b = trainee.service_for("local_b")
            self.assertEqual(self._tree_bytes(simulator.sim_dir), simulator_source_before)
            self.assertEqual(self._device_row(local_b, "ACBranch", "diesel_line")["r"], "0.0025")
            diesel_row = self._device_row(local_b, "ACGenerator", "diesel_300kw")
            self.assertEqual(diesel_row["run_stat"], "0")
            self.assertEqual(diesel_row["p_set"], "95")
            diesel_run_stat = next(
                row
                for row in local_b.source_stat_book.data["RunStat"].data
                if row["dev_type"] == "ACGenerator" and row["dev_name"] == "diesel_300kw"
            )
            diesel_setpoint = next(
                row
                for row in local_b.source_stat_book.data["SetValue"].data
                if row["dev_type"] == "ACGenerator"
                and row["dev_name"] == "diesel_300kw"
                and row["set_type"] == "p_set"
            )
            self.assertEqual(diesel_run_stat["run_stat"], "0")
            self.assertEqual(diesel_setpoint["set_value"], "95")
            baseline_measurement = self._measurement(local_b, "p_gen_diesel_300kw")
            self.assertEqual(float(baseline_measurement["weight"]), 2500.0)
            self.assertEqual(baseline_measurement["status"], "fixed")
            self.assertEqual(float(baseline_measurement["fixed_value"]), 12.5)
            self.assertEqual(local_b.manual_definition_changes()["count"], 0)
            baseline_defaults = json.loads(
                (local_b.sim_dir / "definition_defaults.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                baseline_defaults["measurement_statuses"]["p_gen_diesel_300kw"],
                {"status": "fixed", "fixed_value": 12.5},
            )
            scada_row = list(
                next(
                    row
                    for row in local_b.definition_snapshot.measurement_rows
                    if row[1] == "p_gen_diesel_300kw"
                )
            )
            scada_row[7] = "1"
            local_b.latest_scada_rows = [scada_row]
            local_b._apply_measurement_statuses(0, 0)
            self.assertEqual(float(local_b.latest_scada_rows[0][7]), 12.5)
            trainee_source_before_secondary_override = self._tree_bytes(local_b.sim_dir)

            local_b.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"idx": "2", "name": "diesel_line"},
                    "revision": local_b.definition_snapshot.revision,
                    "changes": {"r": 0.0035},
                },
                allow_runtime_controls=False,
            )
            local_b.update_measurement_definition(
                {
                    "name": "p_gen_diesel_300kw",
                    "revision": local_b.definition_snapshot.revision,
                    "changes": {"status": "zero"},
                }
            )
            self.assertEqual(self._device_row(local_b, "ACBranch", "diesel_line")["r"], "0.0035")
            self.assertEqual(self._measurement(local_b, "p_gen_diesel_300kw")["status"], "zero")
            self.assertEqual(self._tree_bytes(local_b.sim_dir), trainee_source_before_secondary_override)

            restarted = PolarMicrogridSimulator(
                local_b.sim_dir,
                local_b.runtime_dir,
                kernel=lambda _config: None,
                model_id="local_b",
                model_name="本地模型 B",
            )
            self.assertEqual(self._device_row(restarted, "ACBranch", "diesel_line")["r"], "0.0035")
            self.assertEqual(self._measurement(restarted, "p_gen_diesel_300kw")["status"], "zero")

            changes = restarted.manual_definition_changes()["changes"]
            restarted.reset_manual_definition_changes(
                {
                    "revision": restarted.definition_snapshot.revision,
                    "change_ids": [item["id"] for item in changes],
                }
            )
            self.assertEqual(self._device_row(restarted, "ACBranch", "diesel_line")["r"], "0.0025")
            restored_measurement = self._measurement(restarted, "p_gen_diesel_300kw")
            self.assertEqual(restored_measurement["status"], "fixed")
            self.assertEqual(float(restored_measurement["fixed_value"]), 12.5)

    def test_reinitialization_clears_trainee_secondary_overrides_and_uses_latest_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)

            simulator.update_device_parameters(
                {
                    "block_name": "ACBranch",
                    "row_key": {"idx": "2", "name": "diesel_line"},
                    "revision": simulator.definition_snapshot.revision,
                    "changes": {"r": 0.0025},
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
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link"
                initialize_url = f"http://127.0.0.1:{trainee_port}/api/trainee/model-initialize"
                self._post_json(initialize_url, {"model_id": "local_b", "link": link})

                local_b = trainee.service_for("local_b")
                local_b.update_device_parameters(
                    {
                        "block_name": "ACBranch",
                        "row_key": {"idx": "2", "name": "diesel_line"},
                        "revision": local_b.definition_snapshot.revision,
                        "changes": {"r": 0.0035},
                    },
                    allow_runtime_controls=False,
                )
                self.assertTrue(local_b.manual_definition_changes_file.exists())

                simulator.update_device_parameters(
                    {
                        "block_name": "ACBranch",
                        "row_key": {"idx": "2", "name": "diesel_line"},
                        "revision": simulator.definition_snapshot.revision,
                        "changes": {"r": 0.0045},
                    }
                )
                self._post_json(initialize_url, {"model_id": "local_b", "link": link})
            finally:
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)

            local_b = trainee.service_for("local_b")
            self.assertEqual(self._device_row(local_b, "ACBranch", "diesel_line")["r"], "0.0045")
            self.assertEqual(local_b.manual_definition_changes()["count"], 0)
            self.assertFalse(local_b.manual_definition_changes_file.exists())

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

    def test_trainee_local_model_routes_are_not_proxied_to_simulator(self):
        """The learner catalog must never expose or mutate the simulator catalog."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = self._make_simulator(root)
            trainee = self._make_trainee(root)
            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            trainee_server = make_http_server(
                ("127.0.0.1", 0),
                trainee,
                role="trainee",
                sim_url=f"http://127.0.0.1:{simulator_server.server_address[1]}",
            )
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_thread.start()
            try:
                trainee_base = f"http://127.0.0.1:{trainee_server.server_address[1]}"
                with urlopen(f"{trainee_base}/api/models", timeout=5) as response:
                    catalog = json.loads(response.read().decode("utf-8"))
                with urlopen(f"{trainee_base}/api/config?model_id=local_b", timeout=5) as response:
                    local_config = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"{trainee_base}/api/snapshot?model_id=local_b&lite=1&measurements=0",
                    timeout=5,
                ) as response:
                    local_snapshot = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"{trainee_base}/api/measurements/delta?model_id=local_b&after_seq=0&compact=1",
                    timeout=5,
                ) as response:
                    local_delta = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"{trainee_base}/api/export-definitions?format=json&model_id=local_b",
                    timeout=10,
                ) as response:
                    local_archive = json.loads(response.read().decode("utf-8"))

                self.assertEqual({item["id"] for item in catalog["models"]}, {"local_a", "local_b"})
                self.assertEqual(local_config["role"], "trainee")
                self.assertEqual(
                    {item["id"] for item in local_config["models"]},
                    {"local_a", "local_b"},
                )
                self.assertEqual(local_snapshot["model"]["id"], "local_b")
                self.assertTrue(local_delta["definition_signature"])
                self.assertTrue(local_archive["filename"].startswith("local_b_"))

                link = f"http://127.0.0.1:{simulator_server.server_address[1]}/api/trainee-link"
                initialized = self._post_json(
                    f"{trainee_base}/api/trainee/model-initialize",
                    {"model_id": "local_b", "link": link},
                )
                self.assertEqual(initialized["selected_model_id"], "local_b")

                clone_request = Request(
                    f"{trainee_base}/api/models/clone",
                    data=json.dumps({"model_id": "local_a", "name": "local_clone"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(clone_request, timeout=10) as response:
                    cloned = json.loads(response.read().decode("utf-8"))
                self.assertEqual(cloned["model"]["id"], "local_clone")
                self.assertTrue((trainee.models_root / "local_clone").exists())
                self.assertFalse((root / "simulator-source" / "local_clone").exists())

                delete_request = Request(
                    f"{trainee_base}/api/models/delete",
                    data=json.dumps({"model_id": "local_clone"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(delete_request, timeout=10) as response:
                    deleted = json.loads(response.read().decode("utf-8"))
                self.assertTrue(deleted["deleted"]["deleted"])
                self.assertFalse((trainee.models_root / "local_clone").exists())
            finally:
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)

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
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link"
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
                link = f"http://127.0.0.1:{simulator_port}/api/trainee-link"
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
            link = f"http://127.0.0.1:{simulator_port}/api/trainee-link"
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
            link = f"http://127.0.0.1:{simulator_port}/api/trainee-link"
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
            link = f"http://127.0.0.1:{simulator_port}/api/trainee-link"

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
