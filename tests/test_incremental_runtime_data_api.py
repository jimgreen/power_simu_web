from __future__ import annotations

import copy
import json
import gzip
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen


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

    def test_compact_measurement_delta_uses_ordered_value_arrays_and_shared_timestamps(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]

        full = service.measurement_delta(after_seq=0)
        compact = service.measurement_delta(after_seq=0, compact=True)

        self.assertEqual(compact["encoding"], "measurement-arrays-v1")
        self.assertNotIn("items", compact)
        self.assertNotIn("rows", compact)
        self.assertEqual(compact["count"], len(full["items"]))
        self.assertEqual(len(compact["real_values"]), compact["count"])
        self.assertEqual(len(compact["scada_values"]), compact["count"])
        self.assertEqual(len(compact["valid_values"]), compact["count"])
        self.assertNotIn(full["items"][0]["name"], json.dumps(compact, ensure_ascii=False))
        full_size = len(json.dumps(full, ensure_ascii=False).encode("utf-8"))
        compact_size = len(json.dumps(compact, ensure_ascii=False).encode("utf-8"))
        self.assertLess(compact_size, full_size * 0.35)

    def test_measurement_array_frame_rejects_a_definition_length_mismatch(self):
        from simu.measurement_delta import MeasurementArrayMismatchError, apply_measurement_delta

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        definitions = service.measurements()["definitions"]
        compact = service.measurement_delta(after_seq=0, compact=True)
        compact["count"] += 1

        with self.assertRaises(MeasurementArrayMismatchError):
            apply_measurement_delta({}, definitions, compact)

    def test_measurement_array_frame_rejects_a_definition_order_mismatch_atomically(self):
        from simu.measurement_delta import MeasurementArrayMismatchError, apply_measurement_delta

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        definitions = service.measurements()["definitions"]
        compact = service.measurement_delta(after_seq=0, compact=True)
        existing = {
            "definitions": copy.deepcopy(definitions),
            "real": [{**copy.deepcopy(definitions[0]), "value": 123.0}],
            "scada": [{**copy.deepcopy(definitions[0]), "value": 122.0}],
        }
        before = copy.deepcopy(existing)

        with self.assertRaises(MeasurementArrayMismatchError):
            apply_measurement_delta(existing, list(reversed(definitions)), compact)

        self.assertEqual(existing, before)

    def test_measurement_array_frame_requires_a_definition_signature(self):
        from simu.measurement_delta import MeasurementArrayMismatchError, apply_measurement_delta

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        definitions = service.measurements()["definitions"]
        compact = service.measurement_delta(after_seq=0, compact=True)
        compact.pop("definition_signature")

        with self.assertRaisesRegex(MeasurementArrayMismatchError, "定义顺序签名缺失"):
            apply_measurement_delta({}, definitions, compact)

    def test_compact_measurement_frame_aligns_runtime_rows_by_measurement_index_not_name(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        service.latest_real_rows[0][1] = "故意不匹配的真值测点名"
        service.latest_scada_rows[0][1] = "故意不匹配的量测点名"
        service.latest_real_rows[0][7] = "12.5"
        service.latest_scada_rows[0][7] = "12.25"

        compact = service.measurement_delta(after_seq=0, compact=True)

        self.assertEqual(compact["real_values"][0], 12.5)
        self.assertEqual(compact["scada_values"][0], 12.25)

    def test_compact_measurement_delta_at_current_sequence_has_no_value_frame(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        initial = service.measurement_delta(after_seq=0, compact=True)

        unchanged = service.measurement_delta(after_seq=initial["seq"], compact=True)

        self.assertFalse(unchanged["frame"])
        self.assertEqual(unchanged["real_values"], [])
        self.assertEqual(unchanged["scada_values"], [])
        self.assertEqual(unchanged["valid_values"], [])

    def test_compact_measurement_delta_sends_a_complete_frame_after_one_value_changes(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        initial = service.measurement_delta(after_seq=0, compact=True)
        service.latest_scada_rows[0][7] = "98.75"

        changed = service.measurement_delta(after_seq=initial["seq"], compact=True)

        self.assertTrue(changed["frame"])
        self.assertEqual(changed["count"], initial["count"])
        self.assertEqual(len(changed["real_values"]), changed["count"])
        self.assertEqual(len(changed["scada_values"]), changed["count"])
        self.assertEqual(changed["scada_values"][0], 98.75)

    def test_snapshot_can_embed_compact_measurement_delta_in_one_request(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_scada_rows = [list(service.measurement_rows[0])]
        service.latest_scada_rows[0][7] = "4.5"
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = (
            "/api/snapshot?lite=1&logs=0&measurements=0"
            "&measurement_after_seq=0&measurement_compact=1"
        )
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertNotIn("measurements", payload)
        self.assertEqual(payload["measurement_delta"]["encoding"], "measurement-arrays-v1")
        self.assertGreaterEqual(len(payload["measurement_delta"]["scada_values"]), 1)

    def test_json_api_uses_gzip_when_the_client_accepts_it(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        request = Request(
            f"http://127.0.0.1:{port}/api/measurements/delta?after_seq=0&compact=1",
            headers={"Accept-Encoding": "gzip"},
        )
        with urlopen(request, timeout=5) as response:
            compressed = response.read()
            encoding = response.headers.get("Content-Encoding")
            vary = response.headers.get("Vary")

        payload = json.loads(gzip.decompress(compressed).decode("utf-8"))
        self.assertEqual(encoding, "gzip")
        self.assertIn("Accept-Encoding", vary or "")
        self.assertEqual(payload["encoding"], "measurement-arrays-v1")

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
