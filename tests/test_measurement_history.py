from __future__ import annotations

import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import urlopen
from urllib.request import Request


class MeasurementHistoryTest(unittest.TestCase):
    def _make_service(self, model_id: str = "simple"):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=lambda _config: None,
            model_id=model_id,
        )
        self.addCleanup(workspace.cleanup)
        return service

    @staticmethod
    def _seed_measurements(service, real_value: float, scada_value: float) -> None:
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        service.latest_real_rows[0][7] = str(real_value)
        service.latest_scada_rows[0][7] = str(scada_value)

    def test_simulator_history_accumulates_without_a_browser_and_queries_selected_indices(self):
        service = self._make_service()
        self._seed_measurements(service, 10.0, 9.5)
        service.control_clock({"action": "start"})

        service.step(advance_minutes=1)
        self._seed_measurements(service, 11.0, 10.5)
        service.step(advance_minutes=1)

        payload = service.measurement_history(indices=[0])

        self.assertEqual(payload["encoding"], "measurement-history-arrays-v1")
        self.assertEqual(payload["run_id"], service.clock.run_id)
        self.assertEqual(payload["indices"], [0])
        self.assertEqual(len(payload["frames"]), 2)
        self.assertEqual(payload["frames"][0]["real_values"], [10.0])
        self.assertEqual(payload["frames"][1]["scada_values"], [10.5])
        self.assertNotIn(
            service.measurements()["definitions"][0]["name"],
            json.dumps(payload, ensure_ascii=False),
        )

    def test_simulator_clock_restart_and_time_regression_clear_old_history(self):
        service = self._make_service()
        self._seed_measurements(service, 10.0, 9.5)
        service.control_clock({"action": "start"})
        service.step(advance_minutes=1)
        service.step(advance_minutes=1)
        self.assertEqual(len(service.measurement_history(indices=[0])["frames"]), 2)

        service.control_clock({"action": "pause", "minute": 0})
        self.assertEqual(service.measurement_history(indices=[0])["frames"], [])

        service.control_clock({"action": "start"})
        service.step(advance_minutes=1)
        restarted = service.measurement_history(indices=[0])
        self.assertEqual(len(restarted["frames"]), 1)
        self.assertEqual(restarted["frames"][0]["step_count"], 1)

        service.control_clock({"action": "stop"})
        self.assertEqual(service.measurement_history(indices=[0])["frames"], [])

    def test_history_store_deduplicates_a_step_and_enforces_the_ring_limit(self):
        from simu.measurement_history import MeasurementHistoryStore

        service = self._make_service()
        self._seed_measurements(service, 1.0, 1.0)
        measurements = service.measurements()
        store = MeasurementHistoryStore()

        for step in range(1, 5):
            clock = {
                "run_id": 1,
                "step_count": step,
                "absolute_minute": float(step),
                "time": f"00:0{step}:00",
            }
            store.append(
                clock,
                measurements,
                definition_revision=service.definition_snapshot.revision,
                limit=2,
            )
        store.append(
            {
                "run_id": 1,
                "step_count": 4,
                "absolute_minute": 4.0,
                "time": "00:04:00",
            },
            measurements,
            definition_revision=service.definition_snapshot.revision,
            limit=2,
        )

        payload = store.payload(indices=[0])

        self.assertEqual([frame["step_count"] for frame in payload["frames"]], [3, 4])
        self.assertEqual([frame["seq"] for frame in payload["frames"]], [3, 4])

    def test_trainee_backend_accumulates_received_history_and_resets_on_remote_run_change(self):
        from simu.trainee_exchange import TraineeRealtimeExchange

        service = self._make_service("trainee-local")
        self._seed_measurements(service, 20.0, 19.5)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)

        first = service.snapshot(include_static=False, include_runtime_logs=False)
        first["clock"].update(
            {"run_id": 3, "step_count": 1, "absolute_minute": 1.0, "minute": 1.0, "time": "00:01:00"}
        )
        exchange.publish_runtime_snapshot(service.model_id, first, received_at=time.time())

        second = copy.deepcopy(first)
        second["clock"].update(
            {"run_id": 3, "step_count": 2, "absolute_minute": 2.0, "minute": 2.0, "time": "00:02:00"}
        )
        second["measurements"]["real"][0]["value"] = 21.0
        second["measurements"]["scada"][0]["value"] = 20.5
        exchange.publish_runtime_snapshot(service.model_id, second, received_at=time.time())

        history = exchange.measurement_history(service.model_id, indices=[0])
        self.assertEqual(len(history["frames"]), 2)
        self.assertEqual(history["frames"][-1]["scada_values"], [20.5])

        new_run = copy.deepcopy(second)
        new_run["clock"].update(
            {"run_id": 4, "step_count": 1, "absolute_minute": 1.0, "minute": 1.0, "time": "00:01:00"}
        )
        exchange.publish_runtime_snapshot(service.model_id, new_run, received_at=time.time())

        reset_history = exchange.measurement_history(service.model_id, indices=[0])
        self.assertEqual(reset_history["run_id"], 4)
        self.assertEqual(len(reset_history["frames"]), 1)

    def test_simulator_and_trainee_history_http_endpoints_return_backend_samples(self):
        from simu.server import make_http_server
        from simu.trainee_exchange import TraineeRealtimeExchange

        simulator = self._make_service("simulator-model")
        self._seed_measurements(simulator, 30.0, 29.5)
        simulator.control_clock({"action": "start"})
        simulator.step(advance_minutes=1)

        simulator_server = make_http_server(("127.0.0.1", 0), simulator, role="simulator")
        simulator_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
        simulator_thread.start()
        self.addCleanup(simulator_server.server_close)
        self.addCleanup(simulator_server.shutdown)

        simulator_port = simulator_server.server_address[1]
        with urlopen(
            f"http://127.0.0.1:{simulator_port}/api/measurement-history?indices=0",
            timeout=5,
        ) as response:
            simulator_payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(len(simulator_payload["frames"]), 1)

        trainee = self._make_service("trainee-model")
        self._seed_measurements(trainee, 40.0, 39.5)
        exchange = TraineeRealtimeExchange(trainee, start_worker=False)
        self.addCleanup(exchange.close)
        runtime = trainee.snapshot(include_static=False, include_runtime_logs=False)
        runtime["clock"].update(
            {"run_id": 2, "step_count": 1, "absolute_minute": 1.0, "minute": 1.0, "time": "00:01:00"}
        )
        exchange.publish_runtime_snapshot(trainee.model_id, runtime, received_at=time.time())
        trainee_server = make_http_server(
            ("127.0.0.1", 0),
            trainee,
            role="trainee",
            trainee_exchange=exchange,
        )
        trainee_thread = threading.Thread(target=trainee_server.serve_forever, daemon=True)
        trainee_thread.start()
        self.addCleanup(trainee_server.server_close)
        self.addCleanup(trainee_server.shutdown)

        trainee_port = trainee_server.server_address[1]
        with urlopen(
            f"http://127.0.0.1:{trainee_port}/api/trainee/measurement-history?indices=0",
            timeout=5,
        ) as response:
            trainee_payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(len(trainee_payload["frames"]), 1)

    def test_starting_trainee_receive_clears_local_backend_history_before_polling(self):
        from simu.server import make_http_server
        from simu.trainee_exchange import TraineeRealtimeExchange

        trainee = self._make_service("trainee-start")
        self._seed_measurements(trainee, 50.0, 49.5)
        trainee.set_trainee_receive_state(
            {
                "initialized": True,
                "active": False,
                "interaction_link": "http://teacher.invalid/api/trainee-link?model_id=remote",
                "teacher_api_base": "http://teacher.invalid",
                "snapshot_path": "/api/snapshot?model_id=remote",
                "command_path": "/api/student/commands?model_id=remote",
                "teacher_model_id": "remote",
            }
        )
        exchange = TraineeRealtimeExchange(trainee, start_worker=False)
        self.addCleanup(exchange.close)
        runtime = trainee.snapshot(include_static=False, include_runtime_logs=False)
        runtime["clock"].update(
            {"run_id": 8, "step_count": 5, "absolute_minute": 5.0, "minute": 5.0, "time": "00:05:00"}
        )
        exchange.publish_runtime_snapshot(trainee.model_id, runtime, received_at=time.time())
        self.assertEqual(len(exchange.measurement_history(trainee.model_id, indices=[0])["frames"]), 1)

        server = make_http_server(
            ("127.0.0.1", 0),
            trainee,
            role="trainee",
            trainee_exchange=exchange,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        request = Request(
            f"http://127.0.0.1:{port}/api/trainee/receive",
            data=json.dumps({"model_id": trainee.model_id, "active": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request, timeout=5) as response:
            receive_state = json.loads(response.read().decode("utf-8"))

        self.assertTrue(receive_state["active"])
        self.assertEqual(exchange.measurement_history(trainee.model_id, indices=[0])["frames"], [])

        next_runtime = trainee.snapshot(include_static=False, include_runtime_logs=False)
        next_runtime["clock"].update(
            {
                "run_id": 8,
                "step_count": 6,
                "absolute_minute": 6.0,
                "minute": 6.0,
                "time": "00:06:00",
            }
        )
        next_runtime["measurements"]["real"][0]["value"] = 61.0
        next_runtime["measurements"]["scada"][0]["value"] = 60.5
        exchange.publish_runtime_snapshot(
            trainee.model_id,
            next_runtime,
            received_at=time.time(),
        )

        restarted_history = exchange.measurement_history(trainee.model_id, indices=[0])
        self.assertEqual(len(restarted_history["frames"]), 1)
        self.assertEqual(restarted_history["frames"][0]["step_count"], 6)
        self.assertEqual(restarted_history["frames"][0]["real_values"], [61.0])
        self.assertEqual(restarted_history["frames"][0]["scada_values"], [60.5])


if __name__ == "__main__":
    unittest.main()
