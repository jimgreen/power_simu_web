from __future__ import annotations

import json
import base64
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simu.generate_simple_model import write_model_dir
from simu.server import make_definition_archive, make_http_server
from simu.service import MultiModelSimulator, SimulationModelSpec
from simu.trainee_exchange import TraineeControlSnapshot, TraineeRealtimeExchange


class FakeExchange:
    def __init__(self):
        self.snapshot_calls = []
        self.command_calls = []
        self.receive_changes = []
        self.invalidated = []
        self.removed_services = []
        self.closed = 0

    def snapshot(self, model_id, options=None, refresh=False):
        self.snapshot_calls.append((model_id, copy.deepcopy(options), refresh))
        return {"model": {"id": model_id}, "clock": {"time": "cached"}}

    def control_snapshot(self, model_id):
        return TraineeControlSnapshot(
            snapshot={"model": {"id": model_id}, "clock": {"time": "cached"}},
            source="trainee-live",
            age_seconds=0.0,
            error=None,
            receive_active=True,
            ready=True,
            revision=1,
            connection_signature=("fake", model_id),
        )

    def receive_status(self, model_id):
        return {
            "receiveActive": True,
            "ready": True,
            "canRun": True,
            "prerequisiteStatus": "",
            "revision": 1,
            "connectionSignature": ["fake", model_id],
        }

    def measurement_delta(self, model_id, after_seq=0):
        return {"model_id": model_id, "seq": 1, "items": [], "reset": after_seq <= 0}

    def submit_commands(self, model_id, payload):
        self.command_calls.append((model_id, copy.deepcopy(payload)))
        return {"set_values": len(payload.get("set_values", []))}

    def receive_state_changed(self, model_id):
        self.receive_changes.append(model_id)
        return {"modelId": model_id}

    def invalidate_model(self, model_id):
        self.invalidated.append(model_id)

    def remove_model_for_service(self, service):
        self.removed_services.append(service)

    def close(self):
        self.closed += 1


class FakeRenewableManager:
    def __init__(self):
        self.receive_changes = []
        self.removed_services = []
        self.closed = 0

    def receive_state_changed(self, model_id):
        self.receive_changes.append(model_id)
        return {"modelId": model_id}

    def validate_runtime_settings_update_for_service(self, service, payload):
        return None

    def remove_model_for_service(self, service):
        self.removed_services.append(service)

    def close(self):
        self.closed += 1


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

    def _receive_request_after_same_id_recreate(self, endpoint: str, payload: dict):
        class ServiceBoundExchange(FakeExchange):
            def __init__(self):
                super().__init__()
                self.service_receive_changes = []

            def notify_receive_state_changed_for_service(self, service):
                self.service_receive_changes.append(service)

        class ServiceBoundRenewable(FakeRenewableManager):
            def __init__(self):
                super().__init__()
                self.service_receive_changes = []

            def receive_state_changed_for_service(self, service):
                self.service_receive_changes.append(service)
                return {"modelId": service.model_id}

        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            old_service = manager.service_for("alpha")
            old_service.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": False,
                    "interaction_link": "http://teacher-a.invalid/api/trainee-link?model_id=teacher-a",
                    "teacher_api_base": "http://teacher-a.invalid",
                    "snapshot_path": "/api/snapshot?model_id=teacher-a",
                    "command_path": "/api/student/commands?model_id=teacher-a",
                    "teacher_model_id": "teacher-a",
                }
            )
            exchange = ServiceBoundExchange()
            renewable = ServiceBoundRenewable()
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            captured_old_service = threading.Event()
            release_request = threading.Event()
            capture_consumed = threading.Event()
            original_service_for = manager.service_for

            def coordinated_service_for(model_id=None):
                resolved = original_service_for(model_id)
                if (
                    str(model_id or "") == "alpha"
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
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}{endpoint}",
                    data=json.dumps({"model_id": "alpha", **payload}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=5) as response:
                        request_result["status"] = response.status
                        request_result["body"] = json.loads(response.read().decode("utf-8"))
                except HTTPError as exc:
                    request_result["status"] = exc.code
                    request_result["body"] = json.loads(exc.read().decode("utf-8"))
                except Exception as exc:  # pragma: no cover - asserted in parent thread.
                    request_result["error"] = exc

            request_thread = threading.Thread(target=send_old_request, daemon=True)
            try:
                request_thread.start()
                self.assertTrue(captured_old_service.wait(timeout=2.0))

                manager.delete_model("alpha")
                manager.create_model_slot("alpha")
                new_service = original_service_for("alpha")
                new_service.set_trainee_receive_state(
                    {
                        "initialized": True,
                        "active": False,
                        "frozen": True,
                        "interaction_link": "http://teacher-b.invalid/api/trainee-link?model_id=teacher-b",
                        "teacher_api_base": "http://teacher-b.invalid",
                        "snapshot_path": "/api/snapshot?model_id=teacher-b",
                        "command_path": "/api/student/commands?model_id=teacher-b",
                        "teacher_model_id": "teacher-b",
                    }
                )
                before_state = new_service.trainee_receive_state()
                before_file = new_service.trainee_receive_file.read_text(encoding="utf-8")

                release_request.set()
                request_thread.join(timeout=3.0)
                self.assertFalse(request_thread.is_alive())
                after_state = new_service.trainee_receive_state()
                after_file = new_service.trainee_receive_file.read_text(encoding="utf-8")
            finally:
                release_request.set()
                request_thread.join(timeout=2.0)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

        return {
            "request": request_result,
            "old_service": old_service,
            "new_service": new_service,
            "before_state": before_state,
            "after_state": after_state,
            "before_file": before_file,
            "after_file": after_file,
            "exchange_service_changes": exchange.service_receive_changes,
            "exchange_model_changes": exchange.receive_changes,
            "renewable_service_changes": renewable.service_receive_changes,
            "renewable_model_changes": renewable.receive_changes,
        }

    def test_old_receive_requests_cannot_update_recreated_model_lifecycle(self):
        cases = (
            ("/api/trainee/receive", {"active": True}),
            (
                "/api/trainee/receive-state",
                {
                    "active": True,
                    "teacher_api_base": "http://stale-request.invalid",
                    "teacher_model_id": "stale-request",
                },
            ),
        )
        for endpoint, payload in cases:
            with self.subTest(endpoint=endpoint):
                result = self._receive_request_after_same_id_recreate(endpoint, payload)

                self.assertNotIn("error", result["request"])
                self.assertEqual(result["request"].get("status"), 409)
                self.assertRegex(
                    str(result["request"].get("body", {}).get("error", "")),
                    "生命周期|失效|删除|退休",
                )
                self.assertIsNot(result["old_service"], result["new_service"])
                self.assertEqual(result["after_state"], result["before_state"])
                self.assertEqual(result["after_file"], result["before_file"])
                self.assertEqual(result["exchange_service_changes"], [])
                self.assertEqual(result["exchange_model_changes"], [])
                self.assertEqual(result["renewable_service_changes"], [])
                self.assertEqual(result["renewable_model_changes"], [])

    def test_old_trainee_command_request_cannot_dispatch_to_recreated_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            old_service = manager.service_for("alpha")
            old_service.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": True,
                    "interaction_link": "http://teacher-a.invalid/api/trainee-link?model_id=teacher-a",
                    "teacher_api_base": "http://teacher-a.invalid",
                    "snapshot_path": "/api/snapshot?model_id=teacher-a",
                    "command_path": "/api/student/commands?model_id=teacher-a",
                    "teacher_model_id": "teacher-a",
                }
            )
            transport_calls = []

            def request_json(url, **kwargs):
                transport_calls.append((url, copy.deepcopy(kwargs)))
                return {"set_values": 1}

            exchange = TraineeRealtimeExchange(
                manager,
                request_json=request_json,
                start_worker=False,
            )
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=FakeRenewableManager(),
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            captured_old_service = threading.Event()
            release_request = threading.Event()
            capture_consumed = threading.Event()
            original_service_for = manager.service_for
            request_result = {}

            def coordinated_service_for(model_id=None):
                resolved = original_service_for(model_id)
                if (
                    str(model_id or "") == "alpha"
                    and not capture_consumed.is_set()
                    and threading.current_thread() is not threading.main_thread()
                ):
                    capture_consumed.set()
                    captured_old_service.set()
                    self.assertTrue(release_request.wait(timeout=3.0))
                return resolved

            def send_old_command():
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/trainee/commands",
                    data=json.dumps(
                        {
                            "model_id": "alpha",
                            "set_values": [{"dev_name": "wind-1", "set_value": 8.0}],
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=5) as response:
                        request_result["status"] = response.status
                        request_result["body"] = json.loads(response.read().decode("utf-8"))
                except HTTPError as exc:
                    request_result["status"] = exc.code
                    request_result["body"] = json.loads(exc.read().decode("utf-8"))
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    request_result["error"] = exc

            manager.service_for = coordinated_service_for
            request_thread = threading.Thread(target=send_old_command, daemon=True)
            try:
                request_thread.start()
                self.assertTrue(captured_old_service.wait(timeout=2.0))

                old_service.set_trainee_receive_state({"active": False})
                manager.delete_model("alpha")
                exchange.remove_model_for_service(old_service)
                manager.create_model_slot("alpha")
                new_service = original_service_for("alpha")
                new_service.set_trainee_receive_state(
                    {
                        "initialized": True,
                        "active": True,
                        "interaction_link": "http://teacher-b.invalid/api/trainee-link?model_id=teacher-b",
                        "teacher_api_base": "http://teacher-b.invalid",
                        "snapshot_path": "/api/snapshot?model_id=teacher-b",
                        "command_path": "/api/student/commands?model_id=teacher-b",
                        "teacher_model_id": "teacher-b",
                    }
                )
                exchange.notify_receive_state_changed_for_service(new_service)
                new_state = exchange._states["alpha"]
                with new_state.lock:
                    new_state.command_attempt_count = 7
                    new_state.command_success_count = 5
                    new_state.command_accepted_count = 11
                before_status = exchange.receive_status_for_service(new_service)

                release_request.set()
                request_thread.join(timeout=3.0)
                self.assertFalse(request_thread.is_alive())
                after_status = exchange.receive_status_for_service(new_service)
            finally:
                release_request.set()
                request_thread.join(timeout=2.0)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

        self.assertNotIn("error", request_result)
        self.assertEqual(request_result.get("status"), 409, request_result)
        self.assertRegex(
            str(request_result.get("body", {}).get("error", "")),
            "生命周期|失效|删除|退休",
        )
        self.assertEqual(transport_calls, [])
        self.assertIs(exchange._states["alpha"], new_state)
        self.assertEqual(after_status["commandAttemptCount"], before_status["commandAttemptCount"])
        self.assertEqual(after_status["commandSuccessCount"], before_status["commandSuccessCount"])
        self.assertEqual(after_status["commandAcceptedCount"], before_status["commandAcceptedCount"])

    def test_old_trainee_snapshot_refresh_cannot_touch_recreated_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            old_service = manager.service_for("alpha")
            old_service.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": True,
                    "interaction_link": "http://teacher-a.invalid/api/trainee-link?model_id=teacher-a",
                    "teacher_api_base": "http://teacher-a.invalid",
                    "snapshot_path": "/api/snapshot?model_id=teacher-a",
                    "command_path": "/api/student/commands?model_id=teacher-a",
                    "teacher_model_id": "teacher-a",
                }
            )
            new_runtime = old_service.snapshot(
                include_static=True,
                include_runtime_logs=False,
                include_measurements=True,
            )
            transport_calls = []

            def request_json(url, **kwargs):
                transport_calls.append((url, copy.deepcopy(kwargs)))
                candidate = copy.deepcopy(new_runtime)
                candidate["clock"]["time"] = "old-request-refreshed-b"
                return candidate

            exchange = TraineeRealtimeExchange(
                manager,
                request_json=request_json,
                start_worker=False,
            )
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=FakeRenewableManager(),
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            captured_old_service = threading.Event()
            release_request = threading.Event()
            capture_consumed = threading.Event()
            original_service_for = manager.service_for
            request_result = {}

            def coordinated_service_for(model_id=None):
                resolved = original_service_for(model_id)
                if (
                    str(model_id or "") == "alpha"
                    and not capture_consumed.is_set()
                    and threading.current_thread() is not threading.main_thread()
                ):
                    capture_consumed.set()
                    captured_old_service.set()
                    self.assertTrue(release_request.wait(timeout=3.0))
                return resolved

            def send_old_snapshot_refresh():
                try:
                    with urlopen(
                        f"http://127.0.0.1:{server.server_address[1]}"
                        "/api/trainee/snapshot?model_id=alpha&refresh=1",
                        timeout=5,
                    ) as response:
                        request_result["status"] = response.status
                        request_result["body"] = json.loads(response.read().decode("utf-8"))
                except HTTPError as exc:
                    request_result["status"] = exc.code
                    request_result["body"] = json.loads(exc.read().decode("utf-8"))
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    request_result["error"] = exc

            manager.service_for = coordinated_service_for
            request_thread = threading.Thread(target=send_old_snapshot_refresh, daemon=True)
            try:
                request_thread.start()
                self.assertTrue(captured_old_service.wait(timeout=2.0))

                old_service.set_trainee_receive_state({"active": False})
                manager.delete_model("alpha")
                exchange.remove_model_for_service(old_service)
                manager.create_model_slot("alpha")
                new_service = original_service_for("alpha")
                new_service.set_trainee_receive_state(
                    {
                        "initialized": True,
                        "active": True,
                        "interaction_link": "http://teacher-b.invalid/api/trainee-link?model_id=teacher-b",
                        "teacher_api_base": "http://teacher-b.invalid",
                        "snapshot_path": "/api/snapshot?model_id=teacher-b",
                        "command_path": "/api/student/commands?model_id=teacher-b",
                        "teacher_model_id": "teacher-b",
                    }
                )
                exchange.notify_receive_state_changed_for_service(new_service)
                baseline = copy.deepcopy(new_runtime)
                baseline["clock"]["time"] = "new-b-ready-clock"
                exchange.publish_runtime_snapshot(
                    "alpha",
                    baseline,
                    connection_signature=exchange._connection_signature(new_service),
                )
                new_state = exchange._states["alpha"]
                with new_state.lock:
                    new_state.last_error = "new-b-status"
                    new_state.command_attempt_count = 7
                    new_state.command_success_count = 5
                    new_state.command_accepted_count = 11
                    before_state = {
                        "snapshot": copy.deepcopy(new_state.runtime_snapshot),
                        "revision": new_state.revision,
                        "error": new_state.last_error,
                        "last_attempt_at": new_state.last_attempt_at,
                        "last_success_at": new_state.last_success_at,
                        "consecutive_failures": new_state.consecutive_failures,
                        "command_attempt_count": new_state.command_attempt_count,
                        "command_success_count": new_state.command_success_count,
                        "command_accepted_count": new_state.command_accepted_count,
                    }

                release_request.set()
                request_thread.join(timeout=3.0)
                self.assertFalse(request_thread.is_alive())
                with new_state.lock:
                    after_state = {
                        "snapshot": copy.deepcopy(new_state.runtime_snapshot),
                        "revision": new_state.revision,
                        "error": new_state.last_error,
                        "last_attempt_at": new_state.last_attempt_at,
                        "last_success_at": new_state.last_success_at,
                        "consecutive_failures": new_state.consecutive_failures,
                        "command_attempt_count": new_state.command_attempt_count,
                        "command_success_count": new_state.command_success_count,
                        "command_accepted_count": new_state.command_accepted_count,
                    }
            finally:
                release_request.set()
                request_thread.join(timeout=2.0)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

        self.assertNotIn("error", request_result)
        self.assertEqual(request_result.get("status"), 409, request_result)
        self.assertRegex(
            str(request_result.get("body", {}).get("error", "")),
            "生命周期|失效|删除|退休",
        )
        self.assertEqual(transport_calls, [])
        self.assertIs(exchange._states["alpha"], new_state)
        self.assertEqual(after_state, before_state)

    def test_old_runtime_settings_request_cannot_overwrite_or_notify_recreated_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            old_service = manager.service_for("alpha")
            exchange = TraineeRealtimeExchange(manager, start_worker=False)
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=FakeRenewableManager(),
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            captured_old_service = threading.Event()
            release_request = threading.Event()
            capture_consumed = threading.Event()
            original_service_for = manager.service_for
            request_result = {}

            def coordinated_service_for(model_id=None):
                resolved = original_service_for(model_id)
                if (
                    str(model_id or "") == "alpha"
                    and not capture_consumed.is_set()
                    and threading.current_thread() is not threading.main_thread()
                ):
                    capture_consumed.set()
                    captured_old_service.set()
                    self.assertTrue(release_request.wait(timeout=3.0))
                return resolved

            def send_old_settings_update():
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/runtime-settings?model_id=alpha",
                    data=json.dumps(
                        {
                            "settings": {"backend_refresh_seconds": 2.5},
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=5) as response:
                        request_result["status"] = response.status
                        request_result["body"] = json.loads(response.read().decode("utf-8"))
                except HTTPError as exc:
                    request_result["status"] = exc.code
                    request_result["body"] = json.loads(exc.read().decode("utf-8"))
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    request_result["error"] = exc

            manager.service_for = coordinated_service_for
            request_thread = threading.Thread(target=send_old_settings_update, daemon=True)
            try:
                request_thread.start()
                self.assertTrue(captured_old_service.wait(timeout=2.0))

                manager.delete_model("alpha")
                exchange.remove_model_for_service(old_service)
                manager.create_model_slot("alpha")
                new_service = original_service_for("alpha")
                new_service.set_web_runtime_settings(
                    "trainee",
                    {"settings": {"backend_refresh_seconds": 3.0}},
                )
                new_state = exchange._state_for_live_service(new_service)
                with new_state.lock:
                    new_state.next_refresh_at_monotonic = 4321.0
                    new_state.measurement_delta_history = [
                        {"seq": 1, "items": [{"name": "new-b"}]}
                    ]
                before_memory = copy.deepcopy(new_service.local_settings)
                before_file = new_service.settings_file.read_text(encoding="utf-8")
                with new_state.lock:
                    before_next_refresh = new_state.next_refresh_at_monotonic
                    before_history = copy.deepcopy(new_state.measurement_delta_history)

                release_request.set()
                request_thread.join(timeout=3.0)
                self.assertFalse(request_thread.is_alive())
                after_memory = copy.deepcopy(new_service.local_settings)
                after_file = new_service.settings_file.read_text(encoding="utf-8")
                with new_state.lock:
                    after_next_refresh = new_state.next_refresh_at_monotonic
                    after_history = copy.deepcopy(new_state.measurement_delta_history)
            finally:
                release_request.set()
                request_thread.join(timeout=2.0)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

        self.assertNotIn("error", request_result)
        self.assertEqual(request_result.get("status"), 409, request_result)
        self.assertRegex(
            str(request_result.get("body", {}).get("error", "")),
            "生命周期|失效|删除|退休",
        )
        self.assertEqual(after_memory, before_memory)
        self.assertEqual(after_file, before_file)
        self.assertIs(exchange._states["alpha"], new_state)
        self.assertEqual(after_next_refresh, before_next_refresh)
        self.assertEqual(after_history, before_history)

    def test_retired_service_receive_write_cannot_modify_recreated_runtime_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            old_service = manager.service_for("alpha")
            manager.delete_model("alpha")
            manager.create_model_slot("alpha")
            new_service = manager.service_for("alpha")
            new_service.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": False,
                    "teacher_api_base": "http://teacher-b.invalid",
                    "teacher_model_id": "teacher-b",
                }
            )
            before_state = new_service.trainee_receive_state()
            before_file = new_service.trainee_receive_file.read_text(encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "生命周期|失效|删除|退休"):
                old_service.set_trainee_receive_state(
                    {
                        "active": True,
                        "teacher_api_base": "http://stale-a.invalid",
                        "teacher_model_id": "stale-a",
                    }
                )

            self.assertEqual(new_service.trainee_receive_state(), before_state)
            self.assertEqual(
                new_service.trainee_receive_file.read_text(encoding="utf-8"),
                before_file,
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

    def test_delete_rejects_model_with_active_trainee_receive(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            target = manager.service_for("beta")
            target.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": True,
                    "interaction_link": "http://teacher/api/trainee-link?model_id=beta",
                    "teacher_api_base": "http://teacher",
                    "teacher_model_id": "beta",
                    "snapshot_path": "/api/snapshot?model_id=beta",
                    "command_path": "/api/student/commands?model_id=beta",
                }
            )
            exchange = FakeExchange()
            renewable = FakeRenewableManager()
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/models/delete",
                    data=json.dumps({"model_id": "beta"}).encode("utf-8"),
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
        self.assertIs(manager.service_for("beta"), target)
        self.assertEqual(exchange.removed_services, [])
        self.assertEqual(renewable.removed_services, [])

    def test_delete_synchronously_removes_exchange_and_controller_lifecycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            target = manager.service_for("beta")
            exchange = FakeExchange()
            renewable = FakeRenewableManager()
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/models/delete",
                    data=json.dumps({"model_id": "beta"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertTrue(payload["deleted"]["deleted"])
        self.assertEqual(exchange.removed_services, [target])
        self.assertEqual(renewable.removed_services, [target])

    def test_legacy_receive_state_with_saved_teacher_link_is_treated_as_initialized(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            service = manager.service_for("alpha")
            service.trainee_receive_file.write_text(
                json.dumps(
                    {
                        "model_id": "alpha",
                        "model_name": "Alpha",
                        "active": True,
                        "frozen": False,
                        "interaction_link": "http://teacher-a/api/trainee-link?model_id=remote-alpha",
                        "teacher_api_base": "http://teacher-a",
                        "teacher_model_id": "remote-alpha",
                        "teacher_model_name": "Remote Alpha",
                        "snapshot_path": "/api/snapshot?model_id=remote-alpha",
                        "command_path": "/api/student/commands?model_id=remote-alpha",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            state = service.trainee_receive_state()

        self.assertTrue(state["initialized"])
        self.assertEqual(state["teacher_model_name"], "Remote Alpha")

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

    def test_trainee_runtime_routes_delegate_to_one_exchange_and_close_it_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            target = manager.service_for("alpha")
            target.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": False,
                    "interaction_link": "http://teacher/api/trainee-link?model_id=remote-alpha",
                    "teacher_api_base": "http://teacher",
                    "teacher_model_id": "remote-alpha",
                    "snapshot_path": "/api/snapshot?model_id=remote-alpha",
                    "command_path": "/api/student/commands?model_id=remote-alpha",
                }
            )
            exchange = FakeExchange()
            renewable = FakeRenewableManager()
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
            self.assertIs(server.trainee_exchange, exchange)
            self.assertIs(server.renewable_control_manager, renewable)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urlopen(
                    f"http://127.0.0.1:{port}/api/trainee/snapshot?model_id=alpha&measurements=0",
                    timeout=5,
                ) as response:
                    snapshot = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"http://127.0.0.1:{port}/api/trainee/measurements/delta?model_id=alpha&after_seq=7",
                    timeout=5,
                ) as response:
                    delta = json.loads(response.read().decode("utf-8"))
                command_payload = {
                    "model_id": "alpha",
                    "set_values": [{"dev_name": "wind-1", "set_value": 8.0}],
                }
                command_request = Request(
                    f"http://127.0.0.1:{port}/api/trainee/commands",
                    data=json.dumps(command_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(command_request, timeout=5) as response:
                    command_result = json.loads(response.read().decode("utf-8"))
                receive_request = Request(
                    f"http://127.0.0.1:{port}/api/trainee/receive",
                    data=json.dumps({"model_id": "alpha", "active": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(receive_request, timeout=5) as response:
                    receive_result = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(snapshot["clock"]["time"], "cached")
        self.assertEqual(exchange.snapshot_calls, [("alpha", {"measurements": "0"}, False)])
        self.assertEqual(delta["seq"], 1)
        self.assertFalse(delta["reset"])
        self.assertEqual(command_result["set_values"], 1)
        self.assertEqual(exchange.command_calls, [("alpha", command_payload)])
        self.assertTrue(receive_result["active"])
        self.assertEqual(exchange.receive_changes, ["alpha"])
        self.assertEqual(renewable.receive_changes, ["alpha"])
        self.assertEqual(exchange.closed, 1)
        self.assertEqual(renewable.closed, 1)

    def test_receive_notification_does_not_reenter_registry_while_target_is_locked(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            target = manager.service_for("alpha")
            target.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": False,
                    "interaction_link": "http://teacher/api/trainee-link?model_id=remote-alpha",
                    "teacher_api_base": "http://teacher",
                    "teacher_model_id": "remote-alpha",
                    "snapshot_path": "/api/snapshot?model_id=remote-alpha",
                    "command_path": "/api/student/commands?model_id=remote-alpha",
                }
            )
            exchange = TraineeRealtimeExchange(manager, start_worker=False)
            renewable = FakeRenewableManager()
            server = make_http_server(
                ("127.0.0.1", 0),
                manager,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=renewable,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()

            receive_holds_target = threading.Event()
            allow_receive_update = threading.Event()
            registry_holds_clone = threading.Event()
            notification_started = threading.Event()
            allow_clone_target_attempt = threading.Event()
            receive_errors = []
            clone_errors = []
            receive_result = {}
            clone_result = {}
            original_set_receive_state = target.set_trainee_receive_state
            original_clone_files_to = target.clone_files_to
            original_notify = exchange.notify_receive_state_changed

            def coordinated_set_receive_state(payload):
                receive_holds_target.set()
                if not allow_receive_update.wait(timeout=2.0):
                    raise TimeoutError("receive update was not released by the test")
                return original_set_receive_state(payload)

            def coordinated_clone_files_to(target_dir):
                registry_holds_clone.set()
                if not allow_clone_target_attempt.wait(timeout=2.0):
                    raise TimeoutError("clone target-lock attempt was not released by the test")
                if not target.lock.acquire(timeout=0.75):
                    raise TimeoutError("registry and target locks formed a cycle")
                try:
                    return original_clone_files_to(target_dir)
                finally:
                    target.lock.release()

            def tracked_notify(model_id):
                notification_started.set()
                return original_notify(model_id)

            target.set_trainee_receive_state = coordinated_set_receive_state
            target.clone_files_to = coordinated_clone_files_to
            exchange.notify_receive_state_changed = tracked_notify

            resolved_notify_name = "notify_receive_state_changed_for_service"
            if hasattr(exchange, resolved_notify_name):
                original_resolved_notify = getattr(exchange, resolved_notify_name)

                def tracked_resolved_notify(service):
                    notification_started.set()
                    return original_resolved_notify(service)

                setattr(exchange, resolved_notify_name, tracked_resolved_notify)

            def start_receive():
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/trainee/receive",
                    data=json.dumps({"model_id": "alpha", "active": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=5) as response:
                        receive_result.update(json.loads(response.read().decode("utf-8")))
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    receive_errors.append(exc)

            def clone_source_model():
                try:
                    clone_result.update(manager.clone_model("alpha", "alpha-copy"))
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    clone_errors.append(exc)

            receive_thread = threading.Thread(target=start_receive, daemon=True)
            clone_thread = threading.Thread(target=clone_source_model, daemon=True)
            try:
                receive_thread.start()
                self.assertTrue(receive_holds_target.wait(timeout=2.0))
                clone_thread.start()
                self.assertTrue(registry_holds_clone.wait(timeout=2.0))
                allow_receive_update.set()
                self.assertTrue(notification_started.wait(timeout=2.0))
                allow_clone_target_attempt.set()
                receive_thread.join(timeout=3.0)
                clone_thread.join(timeout=3.0)
            finally:
                allow_receive_update.set()
                allow_clone_target_attempt.set()
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

            self.assertFalse(receive_thread.is_alive(), "receive notification did not complete")
            self.assertFalse(clone_thread.is_alive(), "registry clone operation did not complete")
            self.assertEqual(receive_errors, [])
            self.assertEqual(clone_errors, [])
            self.assertTrue(receive_result["active"])
            self.assertEqual(clone_result["id"], "alpha-copy")

    def test_default_renewable_manager_uses_the_server_exchange_providers(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = self._make_manager(Path(temporary))
            server = make_http_server(("127.0.0.1", 0), manager, role="trainee")
            try:
                exchange = server.trainee_exchange
                renewable = server.renewable_control_manager
                self.assertEqual(renewable.snapshot_provider, exchange.control_snapshot)
                self.assertEqual(renewable.receive_status_provider, exchange.receive_status)
                self.assertEqual(renewable.command_sink, exchange.submit_commands)
            finally:
                server.server_close()

    def test_trainee_local_receive_state_is_not_proxied_when_sim_url_is_configured(self):
        with tempfile.TemporaryDirectory() as simulator_temporary, tempfile.TemporaryDirectory() as trainee_temporary:
            simulator = self._make_manager(Path(simulator_temporary))
            trainee = self._make_manager(Path(trainee_temporary))
            trainee.service_for("alpha").set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": False,
                    "interaction_link": "http://teacher-local/api/trainee-link?model_id=remote-alpha",
                    "teacher_api_base": "http://teacher-local",
                    "teacher_model_id": "remote-alpha",
                    "teacher_model_name": "Local Teacher Model",
                    "snapshot_path": "/api/snapshot?model_id=remote-alpha",
                    "command_path": "/api/student/commands?model_id=remote-alpha",
                }
            )
            simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
            simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
            simulator_thread.start()
            trainee_server = make_http_server(
                ("127.0.0.1", 0),
                trainee,
                role="trainee",
                sim_url=f"http://127.0.0.1:{simulator_server.server_address[1]}",
            )
            trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
            trainee_thread.start()
            try:
                with urlopen(
                    f"http://127.0.0.1:{trainee_server.server_address[1]}/api/trainee/receive-state?model_id=alpha",
                    timeout=5,
                ) as response:
                    state = json.loads(response.read().decode("utf-8"))
            finally:
                trainee_server.shutdown()
                simulator_server.shutdown()
                trainee_server.server_close()
                simulator_server.server_close()
                trainee_thread.join(timeout=5)
                simulator_thread.join(timeout=5)

        self.assertTrue(state["initialized"])
        self.assertEqual(state["teacher_model_name"], "Local Teacher Model")

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
    assert "/api/trainee/model-initialize" in script
    assert "/api/trainee/receive" in script
    assert "/api/trainee/snapshot" in script
    assert "/api/trainee/commands" in script
    assert "fetch(url.href" not in script
    assert "fetch(connectionApiUrl(connection" not in script
    assert "selector.disabled = models.length <= 1;" in script
    assert "selector.disabled = state.receiveMode || models.length <= 1;" not in script
    assert "modelInitialized:" in script
    assert "async function initializeModelFromLink" in script
    assert "async function setTraineeReceiveActive" in script
    assert "persistActiveModelContext();" in script


if __name__ == "__main__":
    unittest.main()
