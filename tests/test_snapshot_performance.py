from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
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

    def test_snapshot_can_omit_static_meta_without_touching_the_filesystem(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        with patch.object(service, "static_meta", side_effect=AssertionError("static metadata read")):
            payload = service.snapshot(
                include_static=False,
                include_static_meta=False,
                include_runtime_logs=False,
                include_measurements=False,
                include_devices=False,
                include_device_states=False,
                include_commands=False,
            )

        self.assertNotIn("static_meta", payload)
        self.assertIn("clock", payload)
        self.assertIn("curve_boundary", payload)

    def test_curve_boundary_reuses_interpolation_until_curve_or_clock_changes(self):
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
                "loads": {},
            }
        )

        with patch.object(service, "_curve_point_index", wraps=service._curve_point_index) as point_index:
            first = service.curve_boundary()
            second = service.curve_boundary()
            first_call_count = point_index.call_count
            service.clock.absolute_minute = 1
            third = service.curve_boundary()

        self.assertEqual(first, second)
        self.assertEqual(first_call_count, 1)
        self.assertEqual(point_index.call_count, 2)
        self.assertNotEqual(first["target_minute"], third["target_minute"])

    def test_latest_power_summary_reuses_the_current_measurement_snapshot(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        service.latest_measurements = service.measurements()

        with patch.object(service, "_power_flow_summary", wraps=service._power_flow_summary) as summarize:
            first = service._latest_power_summary(service.latest_measurements)
            first_call_count = summarize.call_count
            second = service._latest_power_summary(service.latest_measurements)

        self.assertEqual(first, second)
        self.assertGreater(first_call_count, 0)
        self.assertEqual(summarize.call_count, first_call_count)

    def test_latest_power_summary_cache_is_invalidated_by_a_new_measurement_snapshot(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        service.latest_measurements = service.measurements()

        with patch.object(service, "_power_flow_summary", wraps=service._power_flow_summary) as summarize:
            service._latest_power_summary(service.latest_measurements)
            first_call_count = summarize.call_count
            service.latest_scada_rows[0][7] = "12.5"
            service.latest_measurements = service.measurements()
            service._latest_power_summary(service.latest_measurements)

        self.assertGreater(summarize.call_count, first_call_count)

    def test_device_runtime_frame_reuses_the_same_runtime_step(self):
        from simu.service import compact_device_runtime_frame

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        with patch(
            "simu.service.compact_device_runtime_frame",
            wraps=compact_device_runtime_frame,
        ) as compact:
            first = service.device_runtime_frame()
            second = service.device_runtime_frame()
            first_call_count = compact.call_count
            service.clock.step_count += 1
            third = service.device_runtime_frame()

        self.assertEqual(first, second)
        self.assertEqual(first_call_count, 1)
        self.assertEqual(compact.call_count, 2)
        self.assertEqual(first["runtime_signature"], third["runtime_signature"])

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

    def test_snapshot_http_endpoint_supports_omitting_static_meta(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = "/api/snapshot?lite=1&static_meta=0&logs=0&measurements=0&devices=0&commands=0"
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertNotIn("static_meta", payload)
        self.assertIn("clock", payload)

    def test_snapshot_can_keep_effective_commands_without_repeating_recent_history(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.command_history = [
            {
                "source": "performance-test",
                "received_at": "12:00:00",
                "normalized": {"run_status": [], "set_values": []},
                "detail": "x" * 20000,
            }
        ]

        full = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
        )
        compact = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
            include_command_history=False,
        )

        self.assertEqual(len(full["commands"]["history"]), 1)
        self.assertEqual(compact["commands"]["history"], [])
        self.assertIn("effective", compact["commands"])
        self.assertLess(
            len(json.dumps(compact, ensure_ascii=False).encode("utf-8")),
            len(json.dumps(full, ensure_ascii=False).encode("utf-8")) / 2,
        )

    def test_snapshot_http_endpoint_supports_compact_command_history_query(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.command_history = [
            {
                "source": "performance-test",
                "received_at": "12:00:00",
                "normalized": {"run_status": [], "set_values": []},
                "detail": "x" * 20000,
            }
        ]
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = "/api/snapshot?lite=1&logs=0&measurements=0&devices=0&command_history=0"
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertIn("commands", payload)
        self.assertEqual(payload["commands"]["history"], [])
        self.assertIn("effective", payload["commands"])

    def test_unchanged_command_history_is_not_written_repeatedly(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.command_history = [
            {
                "source": "performance-test",
                "normalized": {"run_status": [], "set_values": []},
            }
        ]

        with patch("simu.service._write_json", wraps=__import__("simu.service", fromlist=["_write_json"])._write_json) as write_json:
            service._write_command_history()
            service._write_command_history()

        command_writes = [call for call in write_json.call_args_list if call.args[0] == service.commands_file]
        self.assertEqual(len(command_writes), 1)


if __name__ == "__main__":
    unittest.main()
