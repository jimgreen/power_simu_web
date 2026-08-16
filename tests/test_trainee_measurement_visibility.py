from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from simu.measurement_delta import apply_measurement_delta, measurement_definition_signature
from simu.server import make_http_server
from simu.service import PolarMicrogridSimulator
from simu.trainee_data_policy import (
    FLAG_REAL_PRESENT,
    strip_trainee_remote_details_from_snapshot,
    strip_trainee_truth_from_measurement_delta,
    strip_trainee_truth_from_measurement_history,
    strip_trainee_truth_from_snapshot,
)
from simu.trainee_exchange import TraineeRealtimeExchange
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


class TraineeMeasurementVisibilityTest(unittest.TestCase):
    def test_projection_removes_truth_from_snapshot_delta_and_history(self):
        snapshot = {
            "measurements": {
                "definitions": [{"name": "p"}],
                "real": [{"name": "p", "value": 10.0}],
                "scada": [{"name": "p", "value": 9.8}],
            },
            "measurement_delta": {
                "real_values": [10.0],
                "scada_values": [9.8],
                "items": [
                    {
                        "name": "p",
                        "value": 10.0,
                        "real_value": 10.0,
                        "scada_value": 9.8,
                    }
                ],
                "rows": [["p", 10.0, 9.8, 1, 100.0, FLAG_REAL_PRESENT | 4]],
            },
            "measurement_history": {
                "frames": [{"real_values": [10.0], "scada_values": [9.8]}]
            },
            "runtime_logs": [{"seq": 1, "detail": ["模拟台日志"]}],
            "runtime_logs_delta": {
                "items": [{"seq": 2, "detail": ["模拟台增量日志"]}],
            },
            "alarms": [{"detail": "模拟台告警明细"}],
            "warnings": [{"detail": "模拟台告警明细"}],
            "commands": {
                "history": [{"source": "teacher-history"}],
                "effective": [{"source": "teacher-effective"}],
            },
            "compute": {
                "status": "failed",
                "measurement_frame_stale": True,
                "error": "solver detail must stay local",
            },
            "result": {
                "solver_info": "failed",
                "error": "solver detail must stay local",
            },
        }

        projected = strip_trainee_remote_details_from_snapshot(copy.deepcopy(snapshot))

        self.assertEqual(projected["measurements"]["value_channels"], ["scada"])
        self.assertNotIn("real", projected["measurements"])
        delta = projected["measurement_delta"]
        self.assertEqual(delta["value_channels"], ["scada"])
        self.assertNotIn("real_values", delta)
        self.assertNotIn("real_value", delta["items"][0])
        self.assertEqual(delta["items"][0]["value"], 9.8)
        self.assertIsNone(delta["rows"][0][1])
        self.assertEqual(delta["rows"][0][5] & FLAG_REAL_PRESENT, 0)
        self.assertNotIn("measurement_history", projected)
        self.assertNotIn("runtime_logs", projected)
        self.assertNotIn("runtime_logs_delta", projected)
        self.assertNotIn("alarms", projected)
        self.assertNotIn("warnings", projected)
        self.assertEqual(
            projected["commands"],
            {"effective": [{"source": "teacher-effective"}]},
        )
        self.assertEqual(projected["compute"]["status"], "failed")
        self.assertTrue(projected["compute"]["measurement_frame_stale"])
        self.assertNotIn("error", projected["compute"])
        self.assertEqual(projected["result"]["solver_info"], "failed")
        self.assertNotIn("error", projected["result"])

    def test_individual_delta_and_history_projection_are_scada_only(self):
        delta = strip_trainee_truth_from_measurement_delta(
            {"items": [{"real_value": 4.0, "scada_value": 3.9}]}
        )
        history = strip_trainee_truth_from_measurement_history(
            {"frames": [{"real_values": [4.0], "scada_values": [3.9]}]}
        )

        self.assertEqual(delta["items"], [{"scada_value": 3.9, "value": 3.9}])
        self.assertEqual(delta["value_channels"], ["scada"])
        self.assertEqual(history["frames"], [{"scada_values": [3.9]}])
        self.assertEqual(history["value_channels"], ["scada"])

    def test_local_trainee_projection_keeps_local_logs_and_scada_history(self):
        snapshot = {
            "runtime_logs": [{"seq": 1, "detail": ["学员台本地日志"]}],
            "commands": {"history": [{"source": "trainee-local"}]},
            "measurement_history": {
                "frames": [{"real_values": [4.0], "scada_values": [3.9]}],
            },
        }

        projected = strip_trainee_truth_from_snapshot(copy.deepcopy(snapshot))

        self.assertEqual(projected["runtime_logs"], snapshot["runtime_logs"])
        self.assertEqual(projected["commands"], snapshot["commands"])
        self.assertEqual(
            projected["measurement_history"]["frames"],
            [{"scada_values": [3.9]}],
        )
        self.assertEqual(projected["measurement_history"]["value_channels"], ["scada"])

    def test_scada_only_delta_replaces_any_previous_truth_channel(self):
        definitions = [
            {
                "name": "p",
                "dev_type": "ACGenerator",
                "dev_name": "wind-1",
                "meas_type": "P_GEN",
                "valid": 1,
                "weight": 100,
            }
        ]
        previous = {
            "definitions": definitions,
            "real": [{**definitions[0], "value": 10.0}],
            "scada": [{**definitions[0], "value": 9.8}],
        }
        array_payload = {
            "encoding": "measurement-arrays-v1",
            "frame": True,
            "count": 1,
            "definition_signature": measurement_definition_signature(definitions),
            "value_channels": ["scada"],
            "scada_values": [9.7],
            "valid_values": [1],
            "status_values": [None],
            "fixed_values": [None],
        }
        item_payload = {
            "value_channels": ["scada"],
            "items": [{"name": "p", "scada_value": 9.6, "valid": 1}],
        }

        after_array = apply_measurement_delta(previous, definitions, array_payload)
        after_item = apply_measurement_delta(previous, definitions, item_payload)

        for projected, expected_value in ((after_array, 9.7), (after_item, 9.6)):
            self.assertNotIn("real", projected)
            self.assertEqual(projected["value_channels"], ["scada"])
            self.assertEqual(projected["scada"][0]["value"], expected_value)

    def test_exchange_drops_truth_before_publishing_to_trainee_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                Path(temporary) / "runtime",
                model_id="trainee-model",
            )
            runtime = service.snapshot(include_static=True, include_runtime_logs=False)
            self.assertIn("real", runtime["measurements"])
            service.set_trainee_receive_state(
                {
                    "initialized": True,
                    "active": True,
                    "teacher_api_base": "http://teacher.invalid",
                    "snapshot_path": "/api/snapshot?trainee_view=1",
                }
            )
            exchange = TraineeRealtimeExchange(service, start_worker=False)
            self.addCleanup(exchange.close)

            exchange.publish_runtime_snapshot(service.model_id, runtime)
            published = exchange.snapshot(service.model_id)
            delta = exchange.measurement_delta(service.model_id, after_seq=0, compact=True)

        self.assertNotIn("real", published["measurements"])
        self.assertEqual(published["measurements"]["value_channels"], ["scada"])
        self.assertNotIn("real_values", delta)
        self.assertEqual(delta["value_channels"], ["scada"])

    def test_simulator_keeps_truth_for_itself_but_trainee_view_does_not_expose_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                Path(temporary) / "runtime",
                model_id="simple_model",
            )
            server = make_http_server(("127.0.0.1", 0), service, role="simulator")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]

                def get_json(path: str):
                    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                        return json.loads(response.read().decode("utf-8"))

                simulator_snapshot = get_json("/api/snapshot?model_id=simple_model")
                trainee_snapshot = get_json(
                    "/api/snapshot?model_id=simple_model&trainee_view=1"
                )
                trainee_delta = get_json(
                    "/api/measurements/delta?model_id=simple_model&compact=1&trainee_view=1"
                )
                link = get_json("/api/trainee-link")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertIn("real", simulator_snapshot["measurements"])
        self.assertNotIn("real", trainee_snapshot["measurements"])
        self.assertEqual(trainee_snapshot["measurements"]["value_channels"], ["scada"])
        self.assertNotIn("real_values", trainee_delta)
        self.assertEqual(trainee_delta["value_channels"], ["scada"])
        self.assertIn("trainee_view=1", link["snapshot_path"])
        self.assertIn("trainee_view=1", link["measurement_delta_path"])


if __name__ == "__main__":
    unittest.main()
