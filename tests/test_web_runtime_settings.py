from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class WebRuntimeSettingsTest(unittest.TestCase):
    def make_service(self, root: Path, model_id: str):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        source = root / "source" / model_id
        runtime = root / "runtime" / model_id
        write_model_dir(source)
        return PolarMicrogridSimulator(
            source,
            runtime,
            kernel=lambda _config: None,
            model_id=model_id,
            model_name=model_id,
        )

    def test_defaults_and_constraints_are_role_specific(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "model-a")

        simulator = service.web_runtime_settings("simulator")
        trainee = service.web_runtime_settings("trainee")

        self.assertEqual(simulator["role"], "simulator")
        self.assertEqual(simulator["modelId"], "model-a")
        self.assertEqual(simulator["settings"]["frontend_refresh_seconds"], 1.0)
        self.assertEqual(simulator["settings"]["curve_request_timeout_seconds"], 8.0)
        self.assertEqual(simulator["settings"]["runtime_log_delta_batch_size"], 200)
        self.assertEqual(simulator["settings"]["diagram_flow_electric_threshold_kw"], 0.1)
        self.assertEqual(simulator["settings"]["diagram_flow_hydrogen_threshold_nm3_h"], 0.1)
        self.assertNotIn("backend_refresh_seconds", simulator["settings"])
        self.assertEqual(
            simulator["constraints"]["frontend_refresh_seconds"],
            {"type": "number", "min": 0.2, "max": 60.0},
        )

        self.assertEqual(trainee["role"], "trainee")
        self.assertEqual(trainee["settings"]["backend_refresh_seconds"], 1.0)
        self.assertEqual(trainee["settings"]["backend_request_timeout_seconds"], 8.0)
        self.assertEqual(trainee["settings"]["receive_max_reconnect_attempts"], 3)
        self.assertEqual(trainee["settings"]["diagram_flow_electric_threshold_kw"], 0.1)
        self.assertEqual(trainee["settings"]["diagram_flow_hydrogen_threshold_nm3_h"], 0.1)
        self.assertNotIn("curve_request_timeout_seconds", trainee["settings"])
        self.assertEqual(
            trainee["constraints"]["diagram_flow_electric_threshold_kw"],
            {"type": "number", "min": 0.0, "max": 1000000.0},
        )

    def test_settings_persist_per_model_and_survive_service_restart(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_a = self.make_service(root, "model-a")
        model_b = self.make_service(root, "model-b")

        saved_a = model_a.set_web_runtime_settings(
            "simulator",
            {
                "settings": {
                    "frontend_refresh_seconds": 2.5,
                    "runtime_log_page_size": 35,
                    "diagram_flow_electric_threshold_kw": 0.25,
                    "diagram_flow_hydrogen_threshold_nm3_h": 0.4,
                }
            },
        )
        saved_b = model_b.set_web_runtime_settings(
            "simulator",
            {"settings": {"frontend_refresh_seconds": 4.0}},
        )

        self.assertEqual(saved_a["settings"]["frontend_refresh_seconds"], 2.5)
        self.assertEqual(saved_a["settings"]["runtime_log_page_size"], 35)
        self.assertEqual(saved_b["settings"]["frontend_refresh_seconds"], 4.0)
        self.assertTrue(saved_a["updatedAt"])

        restored_a = self.make_service(root, "model-a")
        restored_b = self.make_service(root, "model-b")
        self.assertEqual(restored_a.web_runtime_settings("simulator")["settings"]["frontend_refresh_seconds"], 2.5)
        self.assertEqual(restored_a.web_runtime_settings("simulator")["settings"]["runtime_log_page_size"], 35)
        self.assertEqual(
            restored_a.web_runtime_settings("simulator")["settings"]["diagram_flow_electric_threshold_kw"],
            0.25,
        )
        self.assertEqual(
            restored_a.web_runtime_settings("simulator")["settings"]["diagram_flow_hydrogen_threshold_nm3_h"],
            0.4,
        )
        self.assertEqual(restored_b.web_runtime_settings("simulator")["settings"]["frontend_refresh_seconds"], 4.0)

        stored = json.loads(restored_a.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(
            stored["web_runtime_parameters"]["simulator"]["settings"]["frontend_refresh_seconds"],
            2.5,
        )

    def test_trainee_backend_and_web_groups_save_independently(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "trainee-groups")

        backend_saved = service.set_web_runtime_settings(
            "trainee",
            {
                "settings": {
                    "backend_refresh_seconds": 0.5,
                    "frame_age_limit_seconds": 20,
                }
            },
        )
        web_saved = service.set_web_runtime_settings(
            "trainee",
            {
                "settings": {
                    "frontend_refresh_seconds": 2.5,
                    "runtime_log_page_size": 35,
                }
            },
        )

        self.assertEqual(backend_saved["settings"]["backend_refresh_seconds"], 0.5)
        self.assertEqual(web_saved["settings"]["backend_refresh_seconds"], 0.5)
        self.assertEqual(web_saved["settings"]["frame_age_limit_seconds"], 20.0)
        self.assertEqual(web_saved["settings"]["frontend_refresh_seconds"], 2.5)
        self.assertEqual(web_saved["settings"]["runtime_log_page_size"], 35)

    def test_invalid_update_is_rejected_without_partial_save(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "model-a")
        service.set_web_runtime_settings(
            "trainee",
            {"settings": {"frontend_refresh_seconds": 2.0}},
        )
        before = service.web_runtime_settings("trainee")

        with self.assertRaisesRegex(ValueError, "backend_refresh_seconds"):
            service.set_web_runtime_settings(
                "trainee",
                {
                    "settings": {
                        "frontend_refresh_seconds": 3.0,
                        "backend_refresh_seconds": 0.01,
                    }
                },
            )

        after = service.web_runtime_settings("trainee")
        self.assertEqual(after["settings"], before["settings"])
        self.assertEqual(after["updatedAt"], before["updatedAt"])

    def test_unknown_role_and_setting_are_rejected(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "model-a")

        with self.assertRaisesRegex(ValueError, "role"):
            service.web_runtime_settings("teacher")
        with self.assertRaisesRegex(ValueError, "unknown_setting"):
            service.set_web_runtime_settings(
                "simulator",
                {"settings": {"unknown_setting": 1}},
            )


class WebRuntimeSettingsApiTest(unittest.TestCase):
    def make_service(self, root: Path, model_id: str):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        return PolarMicrogridSimulator(
            source,
            runtime,
            kernel=lambda _config: None,
            model_id=model_id,
            model_name=model_id,
        )

    def start_server(self, service, *, role: str, sim_url: str | None = None):
        from simu.server import make_http_server
        from simu.trainee_exchange import TraineeRealtimeExchange

        exchange = None
        if role == "trainee":
            exchange = TraineeRealtimeExchange(service, start_worker=False)
            self.addCleanup(exchange.close)
        server = make_http_server(
            ("127.0.0.1", 0),
            service,
            role=role,
            sim_url=sim_url,
            trainee_exchange=exchange,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    @staticmethod
    def request_json(url: str, *, method: str = "GET", payload=None):
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_simulator_get_and_post_runtime_settings(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "sim-a")
        base = self.start_server(service, role="simulator")

        status, initial = self.request_json(f"{base}/api/runtime-settings?model_id=sim-a")
        self.assertEqual(status, 200)
        self.assertEqual(initial["role"], "simulator")

        status, saved = self.request_json(
            f"{base}/api/runtime-settings?model_id=sim-a",
            method="POST",
            payload={"settings": {"frontend_refresh_seconds": 2.0}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["settings"]["frontend_refresh_seconds"], 2.0)

    def test_trainee_runtime_settings_stay_local_even_when_proxy_is_configured(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "trainee-a")
        base = self.start_server(
            service,
            role="trainee",
            sim_url="http://127.0.0.1:1/unreachable",
        )

        status, saved = self.request_json(
            f"{base}/api/runtime-settings?model_id=trainee-a",
            method="POST",
            payload={"settings": {"backend_refresh_seconds": 0.5}},
        )

        self.assertEqual(status, 200)
        self.assertEqual(saved["role"], "trainee")
        self.assertEqual(saved["settings"]["backend_refresh_seconds"], 0.5)

    def test_trainee_backend_refresh_period_is_independent_of_control_period(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "trainee-period")
        base = self.start_server(service, role="trainee")
        url = f"{base}/api/runtime-settings?model_id=trainee-period"

        for valid_period in (2.0, 0.75, 0.5):
            with self.subTest(valid_period=valid_period):
                status, saved = self.request_json(
                    url,
                    method="POST",
                    payload={
                        "settings": {
                            "backend_refresh_seconds": valid_period,
                        }
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    saved["settings"]["backend_refresh_seconds"],
                    valid_period,
                )

        with self.assertRaises(HTTPError) as context:
            self.request_json(
                url,
                method="POST",
                payload={"settings": {"backend_refresh_seconds": 0}},
            )
        self.assertEqual(context.exception.code, 400)

    def test_trainee_health_endpoint_reports_the_local_process_instead_of_proxying(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        simulator = self.make_service(root / "simulator", "health-simulator")
        trainee = self.make_service(root / "trainee", "health-trainee")
        simulator_base = self.start_server(simulator, role="simulator")
        trainee_base = self.start_server(
            trainee,
            role="trainee",
            sim_url=simulator_base,
        )

        _, simulator_health = self.request_json(f"{simulator_base}/api/health")
        _, trainee_health = self.request_json(f"{trainee_base}/api/health")

        self.assertEqual(simulator_health["role"], "simulator")
        self.assertEqual(trainee_health["role"], "trainee")
        self.assertEqual(trainee_health["process"]["pid"], os.getpid())
        self.assertIn("working_set_mb", trainee_health["process"])
        self.assertIn("numeric_thread_limits", trainee_health["process"])
        if os.name == "nt":
            self.assertGreater(trainee_health["process"]["working_set_mb"], 0)
            self.assertGreater(trainee_health["process"]["private_mb"], 0)

    def test_api_returns_400_and_keeps_previous_values_for_invalid_payload(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        service = self.make_service(Path(workspace.name), "sim-a")
        base = self.start_server(service, role="simulator")
        self.request_json(
            f"{base}/api/runtime-settings?model_id=sim-a",
            method="POST",
            payload={"settings": {"frontend_refresh_seconds": 2.0}},
        )

        with self.assertRaises(HTTPError) as context:
            self.request_json(
                f"{base}/api/runtime-settings?model_id=sim-a",
                method="POST",
                payload={
                    "settings": {
                        "frontend_refresh_seconds": 3.0,
                        "runtime_log_page_size": 2,
                    }
                },
            )
        self.assertEqual(context.exception.code, 400)

        _, current = self.request_json(f"{base}/api/runtime-settings?model_id=sim-a")
        self.assertEqual(current["settings"]["frontend_refresh_seconds"], 2.0)


if __name__ == "__main__":
    unittest.main()
