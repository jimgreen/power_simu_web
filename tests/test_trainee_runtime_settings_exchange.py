from __future__ import annotations

import copy
import tempfile
import time
import unittest
from pathlib import Path


class ServiceRegistry:
    def __init__(self, services):
        self.services = {service.model_id: service for service in services}

    def service_for(self, model_id=None):
        return self.services[model_id or next(iter(self.services))]

    def iter_services(self):
        return list(self.services.values())


class TraineeRuntimeSettingsExchangeTest(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)

    def make_service(self, model_id: str):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        source = self.root / "source" / model_id
        runtime = self.root / "runtime" / model_id
        write_model_dir(source)
        return PolarMicrogridSimulator(
            source,
            runtime,
            kernel=lambda _config: None,
            model_id=model_id,
            model_name=model_id,
        )

    @staticmethod
    def configure_receive(service, host: str):
        service.set_trainee_receive_state(
            {
                "initialized": True,
                "active": True,
                "teacher_api_base": f"http://{host}.invalid",
                "snapshot_path": "/api/snapshot",
                "command_path": "/api/student/commands",
            }
        )

    def test_request_timeout_and_frame_limits_are_resolved_per_model(self):
        from simu.trainee_exchange import TraineeRealtimeExchange

        service_a = self.make_service("learner-a")
        service_b = self.make_service("learner-b")
        self.configure_receive(service_a, "teacher-a")
        self.configure_receive(service_b, "teacher-b")
        service_a.set_web_runtime_settings(
            "trainee",
            {
                "settings": {
                    "backend_request_timeout_seconds": 3,
                    "frame_age_limit_seconds": 1,
                    "same_frame_limit_seconds": 2,
                }
            },
        )
        service_b.set_web_runtime_settings(
            "trainee",
            {
                "settings": {
                    "backend_request_timeout_seconds": 7,
                    "frame_age_limit_seconds": 100,
                    "same_frame_limit_seconds": 120,
                }
            },
        )
        runtime_a = service_a.snapshot(include_static=True, include_runtime_logs=False)
        runtime_b = service_b.snapshot(include_static=True, include_runtime_logs=False)
        calls = []

        def request_json(url, **kwargs):
            calls.append((url, kwargs))
            return copy.deepcopy(runtime_a if "teacher-a" in url else runtime_b)

        exchange = TraineeRealtimeExchange(
            ServiceRegistry([service_a, service_b]),
            request_json=request_json,
            start_worker=False,
        )
        self.addCleanup(exchange.close)

        exchange.refresh_once("learner-a")
        exchange.refresh_once("learner-b")
        self.assertEqual(calls[0][1]["timeout"], 3.0)
        self.assertEqual(calls[1][1]["timeout"], 7.0)

        state_a = exchange._state_for("learner-a")
        state_b = exchange._state_for("learner-b")
        with state_a.lock:
            state_a.received_at = time.time() - 2.0
        with state_b.lock:
            state_b.received_at = time.time() - 2.0

        self.assertTrue(exchange.receive_status("learner-a")["frameTooOld"])
        self.assertFalse(exchange.receive_status("learner-b")["frameTooOld"])

    def test_measurement_history_limit_is_applied_per_model(self):
        from simu.trainee_exchange import TraineeRealtimeExchange

        service_a = self.make_service("learner-a")
        service_b = self.make_service("learner-b")
        service_a.set_web_runtime_settings(
            "trainee",
            {"settings": {"measurement_delta_history_limit": 10}},
        )
        service_b.set_web_runtime_settings(
            "trainee",
            {"settings": {"measurement_delta_history_limit": 14}},
        )
        exchange = TraineeRealtimeExchange(
            ServiceRegistry([service_a, service_b]),
            start_worker=False,
        )
        self.addCleanup(exchange.close)

        for service in (service_a, service_b):
            runtime = service.snapshot(
                include_static=True,
                include_runtime_logs=False,
                include_measurements=True,
            )
            for index in range(18):
                frame = copy.deepcopy(runtime)
                frame["measurements"]["scada"][0]["value"] = float(index)
                exchange.publish_runtime_snapshot(service.model_id, frame)

        self.assertEqual(len(exchange._state_for("learner-a").measurement_delta_history), 10)
        self.assertEqual(len(exchange._state_for("learner-b").measurement_delta_history), 14)

    def test_worker_uses_each_models_refresh_period_and_applies_changes_immediately(self):
        from simu.trainee_exchange import TraineeRealtimeExchange

        service_fast = self.make_service("learner-fast")
        service_slow = self.make_service("learner-slow")
        self.configure_receive(service_fast, "teacher-fast")
        self.configure_receive(service_slow, "teacher-slow")
        service_fast.set_web_runtime_settings(
            "trainee",
            {"settings": {"backend_refresh_seconds": 0.1}},
        )
        service_slow.set_web_runtime_settings(
            "trainee",
            {"settings": {"backend_refresh_seconds": 1.0}},
        )
        runtime_fast = service_fast.snapshot(include_static=True, include_runtime_logs=False)
        runtime_slow = service_slow.snapshot(include_static=True, include_runtime_logs=False)
        calls = {"learner-fast": 0, "learner-slow": 0}

        def request_json(url, **_kwargs):
            if "teacher-fast" in url:
                calls["learner-fast"] += 1
                return copy.deepcopy(runtime_fast)
            calls["learner-slow"] += 1
            return copy.deepcopy(runtime_slow)

        exchange = TraineeRealtimeExchange(
            ServiceRegistry([service_fast, service_slow]),
            request_json=request_json,
            start_worker=True,
        )
        self.addCleanup(exchange.close)

        deadline = time.time() + 1.0
        while time.time() < deadline and calls["learner-fast"] < 3:
            time.sleep(0.02)
        self.assertGreaterEqual(calls["learner-fast"], 3)
        self.assertEqual(calls["learner-slow"], 1)

        service_slow.set_web_runtime_settings(
            "trainee",
            {"settings": {"backend_refresh_seconds": 0.1}},
        )
        exchange.runtime_settings_changed("learner-slow")
        previous = calls["learner-slow"]
        deadline = time.time() + 0.5
        while time.time() < deadline and calls["learner-slow"] <= previous:
            time.sleep(0.02)
        self.assertGreater(calls["learner-slow"], previous)


if __name__ == "__main__":
    unittest.main()
