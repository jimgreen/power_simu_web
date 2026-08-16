from __future__ import annotations

import copy
import json
import gzip
import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote
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

    def test_measurement_delta_reuses_cached_state_within_the_same_simulation_step(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]

        with mock.patch.object(
            service,
            "_refresh_measurement_delta_state",
            wraps=service._refresh_measurement_delta_state,
        ) as refresh:
            first = service.measurement_delta(after_seq=0, compact=True)
            second = service.measurement_delta(after_seq=first["seq"], compact=True)

        self.assertEqual(refresh.call_count, 1)
        self.assertEqual(second["seq"], first["seq"])
        self.assertFalse(second["frame"])

    def test_measurement_delta_cache_is_invalidated_by_definition_publication(self):
        from simu.definition_editing import DefinitionSnapshot

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]

        with mock.patch.object(
            service,
            "_refresh_measurement_delta_state",
            wraps=service._refresh_measurement_delta_state,
        ) as refresh:
            first = service.measurement_delta(after_seq=0, compact=True)
            current = service.definition_snapshot
            service._publish_definition_snapshot(
                DefinitionSnapshot(
                    revision=current.revision + 1,
                    model_book=current.model_book,
                    dev_define_book=current.dev_define_book,
                    measurement_before=current.measurement_before,
                    measurement_rows=current.measurement_rows,
                    measurement_after=current.measurement_after,
                )
            )
            service.measurement_delta(after_seq=first["seq"], compact=True)

        self.assertEqual(refresh.call_count, 2)

    def test_measurement_delta_cache_is_invalidated_by_measurement_settings(self):
        for setting_name, value in (
            (
                "measurement_statuses",
                {"ESS.ess01.SOC": {"status": "zero", "fixed_value": None}},
            ),
            (
                "measurement_faults",
                [{"target": "ESS.ess01.SOC", "fault_type": "zero"}],
            ),
        ):
            with self.subTest(setting_name=setting_name):
                workspace, service = self._make_service()
                self.addCleanup(workspace.cleanup)
                service.latest_real_rows = [list(row) for row in service.measurement_rows]
                service.latest_scada_rows = [list(row) for row in service.measurement_rows]
                with mock.patch.object(
                    service,
                    "_refresh_measurement_delta_state",
                    wraps=service._refresh_measurement_delta_state,
                ) as refresh:
                    first = service.measurement_delta(after_seq=0, compact=True)
                    service.set_local_settings({setting_name: value})
                    service.measurement_delta(after_seq=first["seq"], compact=True)

                self.assertEqual(refresh.call_count, 2)

    def test_measurement_delta_cache_is_invalidated_by_storage_soc_sync(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        soc_index = next(
            index
            for index, row in enumerate(service.measurement_rows)
            if str(row[4]).upper() == "SOC"
        )

        with mock.patch.object(
            service,
            "_refresh_measurement_delta_state",
            wraps=service._refresh_measurement_delta_state,
        ) as refresh:
            first = service.measurement_delta(after_seq=0)
            storage_block = service.runtime_stat_book.data.get("StorageSoc")
            self.assertIsNotNone(storage_block)
            storage_block.data[0]["soc_curr"] = "0.61"
            service._sync_latest_storage_soc_measurement_rows()
            second = service.measurement_delta(after_seq=first["seq"])

        self.assertEqual(refresh.call_count, 2)
        self.assertGreater(second["seq"], first["seq"])
        self.assertEqual(second["items"][0]["name"], service.measurement_rows[soc_index][1])
        self.assertEqual(second["items"][0]["scada_value"], 0.61)

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
        definitions = service.measurement_runtime_definitions(
            service.measurements()["definitions"]
        )
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

    def test_measurement_array_frame_accepts_a_cached_local_definition_signature(self):
        from simu.measurement_delta import (
            apply_measurement_delta,
            measurement_definition_signature,
        )

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        definitions = service.measurements()["definitions"]
        compact = service.measurement_delta(after_seq=0, compact=True)
        expected_signature = measurement_definition_signature(definitions)

        with mock.patch(
            "simu.measurement_delta.measurement_definition_signature",
            side_effect=AssertionError("cached definition signatures must be reused"),
        ):
            merged = apply_measurement_delta(
                {},
                definitions,
                compact,
                expected_definition_signature=expected_signature,
            )

        self.assertEqual(merged["definition_signature"], expected_signature)
        self.assertEqual(len(merged["scada"]), len(definitions))

    def test_measurement_definitions_and_signature_are_compiled_once_per_revision(self):
        import simu.service as service_module

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        expected_count = len(service.definition_snapshot.measurement_rows)

        with mock.patch(
            "simu.service._measurement_definition_row_to_dict",
            wraps=service_module._measurement_definition_row_to_dict,
        ) as convert_definition, mock.patch(
            "simu.service.measurement_definition_signature",
            wraps=service_module.measurement_definition_signature,
        ) as build_signature:
            first = service.measurement_definitions()
            second = service.measurement_definitions()
            cached_signature = service._measurement_definition_signature_for_current_revision()
            repeated_signature = service._measurement_definition_signature_for_current_revision()

        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first[0], second[0])
        self.assertEqual(convert_definition.call_count, expected_count)
        self.assertEqual(build_signature.call_count, 1)
        self.assertEqual(cached_signature, repeated_signature)

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

    def test_compact_measurement_delta_preserves_duplicate_names_by_definition_order(self):
        from simu.definition_editing import DefinitionSnapshot

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        current = service.definition_snapshot
        measurement_rows = [list(row) for row in current.measurement_rows]
        measurement_rows[1][1] = measurement_rows[0][1]
        service._publish_definition_snapshot(
            DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=current.model_book,
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=tuple(tuple(row) for row in measurement_rows),
                measurement_after=current.measurement_after,
            )
        )
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        service.latest_real_rows[0][7] = "11.0"
        service.latest_real_rows[1][7] = "22.0"
        service.latest_scada_rows[0][7] = "10.5"
        service.latest_scada_rows[1][7] = "21.5"

        compact = service.measurement_delta(after_seq=0, compact=True)

        self.assertEqual(compact["count"], len(service.measurements()["definitions"]))
        self.assertEqual(len(compact["real_values"]), compact["count"])
        self.assertEqual(len(compact["scada_values"]), compact["count"])
        self.assertEqual(compact["real_values"][:2], [11.0, 22.0])
        self.assertEqual(compact["scada_values"][:2], [10.5, 21.5])

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

    def test_measurement_array_no_change_frame_allows_omitted_optional_arrays(self):
        from simu.measurement_delta import apply_measurement_delta

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        definitions = service.measurements()["definitions"]
        initial = service.measurement_delta(after_seq=0, compact=True)
        existing = apply_measurement_delta({}, definitions, initial)
        unchanged = service.measurement_delta(after_seq=initial["seq"], compact=True)
        unchanged.pop("status_values", None)
        unchanged.pop("fixed_values", None)

        merged = apply_measurement_delta(existing, definitions, unchanged)

        self.assertEqual(merged, existing)

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

    def test_snapshot_can_embed_runtime_log_delta_without_full_log_tail(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service._append_runtime_log("测试", "目标", "第一条", "详情1")
        first_seq = service.runtime_logs[-1]["seq"]
        service._append_runtime_log("测试", "目标", "第二条", "详情2")
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = (
            "/api/snapshot?lite=1&logs=1&log_limit=20"
            f"&runtime_log_after_seq={first_seq}"
        )
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertNotIn("runtime_logs", payload)
        self.assertEqual(
            [item["result"] for item in payload["runtime_logs_delta"]["items"]],
            ["第二条"],
        )
        self.assertEqual(
            payload["runtime_logs_delta"]["latest_seq"],
            service.runtime_logs[-1]["seq"],
        )

    def test_snapshot_omits_unchanged_commands_after_signature_cursor(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        base = (
            f"http://127.0.0.1:{port}/api/snapshot"
            "?lite=1&logs=0&measurements=0&devices=0&device_states=0"
            "&commands=1&command_history=0&static_meta=0"
        )
        with urlopen(base, timeout=5) as response:
            first = json.loads(response.read().decode("utf-8"))
        with urlopen(
            f"{base}&after_command_signature={first['command_signature']}",
            timeout=5,
        ) as response:
            second = json.loads(response.read().decode("utf-8"))

        self.assertIn("commands", first)
        self.assertTrue(first["command_signature"])
        self.assertNotIn("commands", second)
        self.assertEqual(second["command_signature"], first["command_signature"])

        service.command_history.append(
            {
                "time": "2026-08-10T12:00:00",
                "source": "trainee-ui",
                "eligible_source": True,
                "manual_hold": True,
                "accepted": {"run_status": 0, "set_values": 1, "ignored": 0},
                "normalized": {
                    "run_status": [],
                    "set_values": [
                        {
                            "dev_type": "ACGenerator",
                            "dev_name": "wt01_10kw",
                            "set_type": "p_set",
                            "set_value": 6.0,
                        }
                    ],
                },
                "payload": {"source": "trainee-ui"},
            }
        )
        with urlopen(
            f"{base}&after_command_signature={first['command_signature']}",
            timeout=5,
        ) as response:
            changed = json.loads(response.read().decode("utf-8"))

        self.assertIn("commands", changed)
        self.assertNotEqual(changed["command_signature"], first["command_signature"])
        self.assertEqual(len(changed["commands"]["effective"]), 1)

    def test_trainee_snapshot_omits_unchanged_commands_after_signature_cursor(self):
        from simu.server import make_http_server
        from simu.trainee_exchange import TraineeRealtimeExchange

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.set_trainee_receive_state(
            {
                "initialized": True,
                "active": True,
                "interaction_link": "http://teacher.invalid/api/trainee-link?model_id=teacher",
                "teacher_api_base": "http://teacher.invalid",
                "snapshot_path": "/api/snapshot?model_id=teacher",
                "command_path": "/api/student/commands?model_id=teacher",
                "teacher_model_id": "teacher",
            }
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            service.model_id,
            service.snapshot(include_static=False, include_runtime_logs=False),
        )
        server = make_http_server(
            ("127.0.0.1", 0),
            service,
            role="trainee",
            trainee_exchange=exchange,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        base = (
            f"http://127.0.0.1:{port}/api/trainee/snapshot"
            "?logs=0&measurements=0&devices=0&device_states=0"
            "&commands=1&command_history=0&static=0&static_meta=0"
        )
        with urlopen(base, timeout=5) as response:
            first = json.loads(response.read().decode("utf-8"))
        with urlopen(
            f"{base}&after_command_signature={first['command_signature']}",
            timeout=5,
        ) as response:
            second = json.loads(response.read().decode("utf-8"))

        self.assertIn("commands", first)
        self.assertNotIn("commands", second)
        self.assertEqual(second["command_signature"], first["command_signature"])

    def test_snapshot_can_embed_compact_device_runtime_without_device_names(self):
        from simu.device_runtime_frame import apply_device_runtime_frame
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        full_devices = service.devices()
        full_states = service.device_states()
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = (
            "/api/snapshot?lite=1&logs=0&measurements=0&commands=0&static=0"
            "&devices=0&device_states=0&device_runtime_compact=1"
        )
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        frame = payload["device_runtime"]
        frame_text = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
        decoded_devices, decoded_states = apply_device_runtime_frame(
            full_devices,
            full_states,
            frame,
        )
        full_size = len(
            json.dumps(
                {"devices": full_devices, "device_states": full_states},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        compact_size = len(frame_text.encode("utf-8"))

        self.assertNotIn("devices", payload)
        self.assertNotIn("device_states", payload)
        self.assertEqual(frame["encoding"], "device-runtime-arrays-v1")
        self.assertTrue(frame["runtime_signature"])
        self.assertEqual(payload["device_runtime_signature"], frame["runtime_signature"])
        self.assertNotIn(full_devices[0]["dev_name"], frame_text)
        self.assertEqual(len(decoded_devices), len(full_devices))
        self.assertEqual(len(decoded_states), len(full_states))
        self.assertLess(compact_size, full_size * 0.25)

    def test_snapshot_can_embed_measurement_deduplicated_device_runtime_for_local_ui(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = (
            "/api/snapshot?lite=1&logs=0&measurements=0&commands=0&static=0"
            "&measurement_after_seq=0&measurement_compact=1"
            "&devices=0&device_states=0&device_runtime_compact=1"
            "&device_runtime_supplement=1"
        )
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        frame = payload["device_runtime"]
        self.assertEqual(frame["encoding"], "device-runtime-supplement-arrays-v1")
        for redundant_field in (
            "device_run_stats",
            "device_statuses",
            "device_soc_present",
            "state_run_stats",
        ):
            self.assertNotIn(redundant_field, frame)

    def test_trainee_ui_frame_combines_snapshot_receive_state_and_renewable_delta(self):
        from simu.server import make_http_server
        from simu.trainee_exchange import TraineeRealtimeExchange

        class RenewableStub:
            def state_for_service(self, target, **options):
                return {
                    "modelId": target.model_id,
                    "compact": bool(options.get("compact")),
                    "planRevision": 3,
                }

            def close(self):
                return None

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.set_trainee_receive_state(
            {
                "initialized": True,
                "active": True,
                "interaction_link": "http://teacher.invalid/api/trainee-link?model_id=teacher",
                "teacher_api_base": "http://teacher.invalid",
                "snapshot_path": "/api/snapshot?model_id=teacher",
                "command_path": "/api/student/commands?model_id=teacher",
                "teacher_model_id": "teacher",
            }
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            service.model_id,
            service.snapshot(include_static=False, include_runtime_logs=False),
        )
        server = make_http_server(
            ("127.0.0.1", 0),
            service,
            role="trainee",
            trainee_exchange=exchange,
            renewable_control_manager=RenewableStub(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = (
            "/api/trainee/ui-frame?view=renewable&compact=1"
            "&logs=0&measurements=0&measurement_after_seq=0&measurement_compact=1"
            "&devices=0&device_states=0&device_runtime_compact=1"
            "&device_runtime_supplement=1&commands=0&command_history=0"
            "&static=0&static_meta=0"
        )
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            first = json.loads(response.read().decode("utf-8"))

        self.assertEqual(first["encoding"], "trainee-ui-frame-v1")
        self.assertIn("snapshot", first)
        self.assertIn("measurement_delta", first["snapshot"])
        self.assertIn("receive_state", first)
        self.assertEqual(first["renewable_control"]["planRevision"], 3)
        self.assertTrue(first["renewable_control"]["compact"])

        cursor = quote(first["receive_state_revision"], safe="")
        with urlopen(
            f"http://127.0.0.1:{port}{path}&after_receive_state_revision={cursor}",
            timeout=5,
        ) as response:
            unchanged = json.loads(response.read().decode("utf-8"))

        self.assertEqual(unchanged["receive_state_revision"], first["receive_state_revision"])
        self.assertNotIn("receive_state", unchanged)

    def test_trainee_view_uses_measurement_deduplicated_device_supplement_and_slim_envelope(self):
        from simu.server import make_http_server
        from simu.trainee_data_policy import INTERSTATION_SNAPSHOT_FIELDS

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        definitions = service.measurements()["definitions"]
        measurement_keys = {
            (
                str(row.get("runtime_dev_type", row.get("dev_type", ""))).strip(),
                str(row.get("runtime_dev_name", row.get("dev_name", ""))).strip(),
                str(row.get("meas_type", "")).strip().upper(),
            )
            for row in definitions
        }
        devices_by_position = sorted(
            service.devices(),
            key=lambda row: (
                str(row.get("dev_type", "")).strip(),
                str(row.get("dev_name", row.get("name", ""))).strip(),
            ),
        )
        states_by_position = sorted(
            service.device_states(),
            key=lambda row: (
                str(row.get("dev_type", "")).strip(),
                str(row.get("dev_name", row.get("name", ""))).strip(),
            ),
        )
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        path = (
            "/api/snapshot?trainee_view=1&lite=1&logs=0&measurements=0"
            "&measurement_after_seq=0&measurement_compact=1"
            "&commands=1&command_history=0&static=0&static_meta=0"
            "&devices=0&device_states=0&device_runtime_compact=1"
        )
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertLessEqual(set(payload), set(INTERSTATION_SNAPSHOT_FIELDS))
        for redundant_field in (
            "model",
            "summary",
            "power_summary",
            "curve_boundary",
            "system_parameters",
            "simulation_timing",
            "result",
        ):
            self.assertNotIn(redundant_field, payload)
        for transport_only_compute_field in (
            "mode",
            "http_pid",
            "worker_pid",
            "compute_ms",
            "round_trip_ms",
            "resident_model",
        ):
            self.assertNotIn(transport_only_compute_field, payload.get("compute", {}))
        self.assertEqual(
            payload["device_runtime"]["encoding"],
            "device-runtime-supplement-arrays-v1",
        )
        frame = payload["device_runtime"]
        for redundant_field in (
            "device_run_stats",
            "device_statuses",
            "device_soc_present",
            "state_run_stats",
        ):
            self.assertNotIn(redundant_field, frame)
        for position in frame["device_run_stat_indices"]:
            row = devices_by_position[position]
            self.assertNotIn(
                (row["dev_type"], row["dev_name"], "RUN_STAT"),
                measurement_keys,
            )
        for position in frame["device_status_indices"]:
            row = devices_by_position[position]
            self.assertNotIn(
                (row["dev_type"], row["dev_name"], "STATUS"),
                measurement_keys,
            )
        for position in frame["device_soc_indices"]:
            row = devices_by_position[position]
            self.assertNotIn(
                (row["dev_type"], row["dev_name"], "SOC"),
                measurement_keys,
            )
        for position in frame["state_run_stat_indices"]:
            row = states_by_position[position]
            self.assertNotIn(
                (row["dev_type"], row["dev_name"], "RUN_STAT"),
                measurement_keys,
            )

    def test_device_supplement_signature_ignores_measurement_backed_run_status_and_soc(self):
        from simu.device_runtime_frame import compact_device_runtime_supplement_frame

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        definitions = service.measurement_runtime_definitions(
            service.measurements()["definitions"]
        )
        devices = service.devices()
        states = service.device_states()
        measurement_keys = {
            (
                str(row.get("runtime_dev_type", row.get("dev_type", ""))).strip(),
                str(row.get("runtime_dev_name", row.get("dev_name", ""))).strip(),
                str(row.get("meas_type", "")).strip().upper(),
            )
            for row in definitions
        }
        first = compact_device_runtime_supplement_frame(
            devices,
            states,
            definitions,
            definition_revision=service.definition_snapshot.revision,
        )
        changed = copy.deepcopy(devices)
        run_device = next(
            row
            for row in changed
            if (
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
                "RUN_STAT",
            )
            in measurement_keys
        )
        run_device["run_stat"] = 1 - int(run_device.get("run_stat", 0) or 0)
        soc_device = next(
            row
            for row in changed
            if (
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
                "SOC",
            )
            in measurement_keys
        )
        soc_device["soc_curr"] = 0.123
        second = compact_device_runtime_supplement_frame(
            changed,
            states,
            definitions,
            definition_revision=service.definition_snapshot.revision,
        )

        self.assertEqual(second["runtime_signature"], first["runtime_signature"])
        changed[0]["mode"] = "changed-mode"
        third = compact_device_runtime_supplement_frame(
            changed,
            states,
            definitions,
            definition_revision=service.definition_snapshot.revision,
        )
        self.assertNotEqual(third["runtime_signature"], first["runtime_signature"])

    def test_snapshot_omits_unchanged_compact_device_runtime_after_signature_cursor(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        base = (
            f"http://127.0.0.1:{port}/api/snapshot"
            "?lite=1&logs=0&measurements=0&commands=0&static=0"
            "&devices=0&device_states=0&device_runtime_compact=1"
        )
        with urlopen(base, timeout=5) as response:
            first = json.loads(response.read().decode("utf-8"))
        with urlopen(
            f"{base}&after_device_runtime_signature={first['device_runtime_signature']}",
            timeout=5,
        ) as response:
            second = json.loads(response.read().decode("utf-8"))

        self.assertIn("device_runtime", first)
        self.assertNotIn("device_runtime", second)
        self.assertEqual(
            second["device_runtime_signature"],
            first["device_runtime_signature"],
        )

    def test_device_runtime_frame_rejects_length_mismatch_atomically(self):
        from simu.device_runtime_frame import (
            DeviceRuntimeFrameMismatchError,
            apply_device_runtime_frame,
            compact_device_runtime_frame,
        )

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        devices = service.devices()
        states = service.device_states()
        frame = compact_device_runtime_frame(
            devices,
            states,
            definition_revision=service.definition_snapshot.revision,
        )
        frame["device_run_stats"] = frame["device_run_stats"][:-1]
        original_devices = copy.deepcopy(devices)
        original_states = copy.deepcopy(states)

        with self.assertRaises(DeviceRuntimeFrameMismatchError):
            apply_device_runtime_frame(devices, states, frame)

        self.assertEqual(devices, original_devices)
        self.assertEqual(states, original_states)

    def test_device_runtime_frame_rejects_a_runtime_signature_mismatch_atomically(self):
        from simu.device_runtime_frame import (
            DeviceRuntimeFrameMismatchError,
            apply_device_runtime_frame,
            compact_device_runtime_frame,
        )

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        devices = service.devices()
        states = service.device_states()
        frame = compact_device_runtime_frame(
            devices,
            states,
            definition_revision=service.definition_snapshot.revision,
        )
        frame["device_run_stats"][0] = 0
        original_devices = copy.deepcopy(devices)
        original_states = copy.deepcopy(states)

        with self.assertRaisesRegex(DeviceRuntimeFrameMismatchError, "runtime signature mismatch"):
            apply_device_runtime_frame(devices, states, frame)

        self.assertEqual(devices, original_devices)
        self.assertEqual(states, original_states)

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

    def test_static_assets_use_memory_cache_gzip_etag_and_revalidate_after_file_change(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        static_root = Path(workspace.name) / "web"
        static_root.mkdir()
        asset = static_root / "app.js"
        original = ("const performancePayload = 'original';\n" * 128).encode("utf-8")
        asset.write_bytes(original)

        server = make_http_server(
            ("127.0.0.1", 0),
            service,
            role="simulator",
            static_root=static_root,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/app.js", headers={"Accept-Encoding": "gzip"})
        response = connection.getresponse()
        compressed = response.read()
        etag = response.getheader("ETag")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Encoding"), "gzip")
        self.assertEqual(response.getheader("Cache-Control"), "no-cache")
        self.assertIn("Accept-Encoding", response.getheader("Vary") or "")
        self.assertTrue(etag)
        self.assertEqual(gzip.decompress(compressed), original)
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "GET",
            "/app.js",
            headers={"Accept-Encoding": "gzip", "If-None-Match": etag},
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 304)
        self.assertEqual(response.read(), b"")
        self.assertEqual(response.getheader("ETag"), etag)
        connection.close()

        updated = ("const performancePayload = 'updated';\n" * 128).encode("utf-8")
        asset.write_bytes(updated)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "GET",
            "/app.js",
            headers={"Accept-Encoding": "gzip", "If-None-Match": etag},
        )
        response = connection.getresponse()
        refreshed = response.read()
        self.assertEqual(response.status, 200)
        self.assertNotEqual(response.getheader("ETag"), etag)
        self.assertEqual(gzip.decompress(refreshed), updated)
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/api/snapshot?lite=1&measurements=0&devices=0")
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        connection.close()

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
