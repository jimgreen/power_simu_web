from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen


class SnapshotPerformanceTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None, model_id="simple")
        for index in range(5):
            service._append_runtime_log("测试", "目标", "完成", f"详情 {index}")
        return workspace, service

    def test_full_snapshot_keeps_static_definition_payload_for_compatibility(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        snapshot = service.snapshot()

        for key in ("files", "source_files", "work_files", "definitions", "curves", "settings", "device_parameters", "diagram"):
            self.assertIn(key, snapshot)
        self.assertIn("measurements", snapshot)
        self.assertIn("devices", snapshot)

    def test_lite_snapshot_omits_static_payload_and_caps_logs(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        full = service.snapshot()
        lite = service.snapshot(include_static=False, runtime_log_limit=2)

        for key in ("files", "source_files", "work_files", "definitions", "curves", "settings", "device_parameters", "diagram"):
            self.assertNotIn(key, lite)
        self.assertIn("measurements", lite)
        self.assertIn("devices", lite)
        self.assertEqual(len(lite["runtime_logs"]), 2)
        full_size = len(json.dumps(full, ensure_ascii=False).encode("utf-8"))
        lite_size = len(json.dumps(lite, ensure_ascii=False).encode("utf-8"))
        self.assertLess(lite_size, full_size)

    def test_snapshot_can_return_only_requested_static_fields(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        partial = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=False,
            static_fields=["definitions", "settings", "device_parameters"],
        )

        self.assertIn("definitions", partial)
        self.assertIn("settings", partial)
        self.assertIn("device_parameters", partial)
        self.assertNotIn("curves", partial)
        self.assertNotIn("diagram", partial)
        self.assertNotIn("measurements", partial)

    def test_snapshot_http_endpoint_supports_lite_query(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/api/snapshot?lite=1&log_limit=1", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertIn("measurements", payload)
        self.assertNotIn("curves", payload)
        self.assertNotIn("definitions", payload)
        self.assertEqual(len(payload["runtime_logs"]), 1)

    def test_snapshot_http_endpoint_supports_static_field_query(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = "/api/snapshot?static=definitions,settings,device_parameters&logs=0&measurements=0"
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertIn("definitions", payload)
        self.assertIn("settings", payload)
        self.assertIn("device_parameters", payload)
        self.assertNotIn("curves", payload)
        self.assertNotIn("diagram", payload)
        self.assertNotIn("measurements", payload)

    def test_snapshot_can_omit_devices_and_commands_but_keep_static_meta_and_curve_boundary(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.set_curves(
            {
                "mode": "day",
                "time_step_minutes": 1,
                "point_count": 2,
                "weather": [
                    {"minute": 0, "wind_speed_mps": 1, "solar_irradiance_w_m2": 10, "air_temp_c": -20},
                    {"minute": 1, "wind_speed_mps": 2, "solar_irradiance_w_m2": 20, "air_temp_c": -19},
                ],
                "loads": {
                    "load_a": [
                        {"minute": 0, "p_kw": 100},
                        {"minute": 1, "p_kw": 101},
                    ],
                    "load_b": [
                        {"minute": 0, "p_kw": 200},
                        {"minute": 1, "p_kw": 201},
                    ],
                },
            }
        )
        service.clock.absolute_minute = 1
        service.clock.minute = 1

        payload = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_commands=False,
        )

        self.assertIn("static_meta", payload)
        self.assertIn("definitions", payload["static_meta"])
        self.assertIn("curve_boundary", payload)
        self.assertEqual(payload["curve_boundary"]["mode"], "day")
        self.assertEqual(payload["curve_boundary"]["index"], 1)
        self.assertEqual(payload["curve_boundary"]["point"]["wind_speed_mps"], 2)
        self.assertEqual(payload["curve_boundary"]["load_total"], 302)
        self.assertNotIn("devices", payload)
        self.assertNotIn("commands", payload)

    def test_snapshot_http_endpoint_supports_omitting_devices_and_commands(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = "/api/snapshot?lite=1&logs=0&measurements=0&devices=0&commands=0"
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertIn("static_meta", payload)
        self.assertIn("curve_boundary", payload)
        self.assertNotIn("runtime_logs", payload)
        self.assertNotIn("measurements", payload)
        self.assertNotIn("devices", payload)
        self.assertNotIn("commands", payload)


if __name__ == "__main__":
    unittest.main()
