from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen


class RuntimeLogApiTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        return workspace, service

    def test_runtime_log_entries_use_simu_time_field(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service._append_runtime_log("测试", "目标", "完成", "详情", simu_time="01:02:00")

        entry = service.runtime_logs[-1]
        self.assertEqual(entry["simu_time"], "01:02:00")
        self.assertNotIn("sim_time", entry)

    def test_clear_runtime_logs_resets_rows_and_sequence(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service._append_runtime_log("测试", "目标", "完成", "详情")
        result = service.clear_runtime_logs()
        service._append_runtime_log("测试", "目标", "完成", "详情")

        self.assertEqual(result, {"cleared": 1})
        self.assertEqual(len(service.runtime_logs), 1)
        self.assertEqual(service.runtime_logs[-1]["seq"], 1)

    def test_runtime_logs_are_saved_in_runtime_folder(self):
        from simu.service import PolarMicrogridSimulator

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service._append_runtime_log("测试", "目标", "完成", "详情")
        restored = PolarMicrogridSimulator(service.sim_dir, service.runtime_dir, kernel=lambda _config: None)

        self.assertTrue((service.runtime_dir / "runtime_logs.json").exists())
        self.assertEqual(len(restored.runtime_logs), 1)
        self.assertEqual(restored.runtime_logs[0]["type"], "测试")

    def test_clear_runtime_logs_http_endpoint(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service._append_runtime_log("测试", "目标", "完成", "详情")

        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        request = Request(
            f"http://127.0.0.1:{port}/api/runtime-logs/clear",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["cleared"], 1)
        self.assertEqual(service.runtime_logs, [])


if __name__ == "__main__":
    unittest.main()
