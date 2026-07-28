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


if __name__ == "__main__":
    unittest.main()
