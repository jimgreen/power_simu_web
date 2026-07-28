from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen


class IncrementalRuntimeDataApiTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None, model_id="simple")
        return workspace, service

    def test_snapshot_can_omit_runtime_logs_and_measurements_for_fast_polling(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service._append_runtime_log("测试", "目标", "完成", "详情")
        service.latest_scada_rows = [list(service.measurement_rows[0])]

        payload = service.snapshot(include_static=False, include_runtime_logs=False, include_measurements=False)

        self.assertNotIn("runtime_logs", payload)
        self.assertNotIn("measurements", payload)
        self.assertIn("clock", payload)
        self.assertIn("devices", payload)

    def test_runtime_logs_endpoint_returns_only_new_rows_after_sequence(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service._append_runtime_log("测试", "目标", "第一条", "详情1")
        first_seq = service.runtime_logs[-1]["seq"]
        service._append_runtime_log("测试", "目标", "第二条", "详情2")

        payload = service.runtime_logs_delta(after_seq=first_seq, limit=20)

        self.assertEqual([item["result"] for item in payload["items"]], ["第二条"])
        self.assertEqual(payload["latest_seq"], service.runtime_logs[-1]["seq"])

    def test_runtime_logs_endpoint_pages_history_before_sequence(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        for index in range(5):
            service._append_runtime_log("测试", "目标", f"第{index}条", "详情")

        payload = service.runtime_logs_delta(before_seq=5, limit=2)

        self.assertEqual([item["result"] for item in payload["items"]], ["第2条", "第3条"])
        self.assertEqual(payload["total"], 5)

    def test_measurement_delta_endpoint_returns_changed_values_by_name(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_scada_rows = [list(service.measurement_rows[0])]
        service.latest_scada_rows[0][7] = "1.0"
        first = service.measurement_delta(after_seq=0)
        service.latest_scada_rows[0][7] = "2.5"

        second = service.measurement_delta(after_seq=first["seq"])

        self.assertGreater(second["seq"], first["seq"])
        self.assertEqual(len(second["items"]), 1)
        self.assertEqual(second["items"][0]["name"], first["items"][0]["name"])
        self.assertEqual(second["items"][0]["scada_value"], 2.5)

    def test_http_incremental_endpoints(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service._append_runtime_log("测试", "目标", "完成", "详情")
        service.latest_scada_rows = [list(service.measurement_rows[0])]
        service.latest_scada_rows[0][7] = "3.25"

        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/api/runtime-logs?after_seq=0", timeout=5) as response:
            logs = json.loads(response.read().decode("utf-8"))
        with urlopen(f"http://127.0.0.1:{port}/api/measurements/delta?after_seq=0", timeout=5) as response:
            measurements = json.loads(response.read().decode("utf-8"))

        self.assertEqual(len(logs["items"]), 1)
        self.assertGreaterEqual(len(measurements["items"]), 1)
        changed = [item for item in measurements["items"] if item["name"] == service.measurements()["scada"][0]["name"]]
        self.assertEqual(changed[0]["scada_value"], 3.25)


if __name__ == "__main__":
    unittest.main()
