from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from simu.renewable_control import TraineeRenewableControlManager
from simu.service import PolarMicrogridSimulator
from simu.trainee_exchange import TraineeRealtimeExchange


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"


class TraineeDefinitionRenewableSyncTest(unittest.TestCase):
    def _make_service(self):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(FIXTURE, source)
        service = PolarMicrogridSimulator(
            source,
            runtime,
            model_id="trainee-local",
            kernel=lambda _config: None,
        )
        service.set_trainee_receive_state(
            {
                "initialized": True,
                "active": True,
                "teacher_api_base": "http://teacher.invalid",
                "snapshot_path": "/api/snapshot?model_id=teacher",
                "command_path": "/api/student/commands?model_id=teacher",
                "teacher_model_id": "teacher",
            }
        )
        self.addCleanup(workspace.cleanup)
        return service

    def _make_manager(self, service, exchange):
        manager = TraineeRenewableControlManager(
            service,
            snapshot_provider=exchange.control_snapshot,
            receive_status_provider=exchange.receive_status,
            command_sink=exchange.submit_commands,
            start_worker=False,
        )
        self.addCleanup(manager.close)
        return manager

    @staticmethod
    def _rated_power(snapshot):
        return snapshot["device_parameters"]["ACWindGen"][0]["rated_power"]

    def test_next_control_snapshot_uses_latest_learner_device_edit(self):
        service = self._make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot("trainee-local", runtime)
        manager = self._make_manager(service, exchange)

        before = manager._control_snapshot("trainee-local")
        self.assertEqual(before.source, "trainee-live")
        self.assertEqual(float(self._rated_power(before.snapshot)), 10.0)

        service.update_device_parameters(
            {
                "block_name": "ACWindGen",
                "row_key": {"idx": "1"},
                "revision": service.definition_snapshot.revision,
                "changes": {"rated_power": 22},
            }
        )

        after = manager._control_snapshot("trainee-local")
        self.assertEqual(float(self._rated_power(after.snapshot)), 22.0)
        self.assertEqual(
            float(after.snapshot["definitions"]["model"]["ACWindGen"]["rows"][0]["rated_power"]),
            22.0,
        )

    def test_control_manager_reads_published_learner_cache_without_transport(self):
        service = self._make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
        )
        runtime["device_parameters"]["ACWindGen"][0]["rated_power"] = 999.0
        requested_urls = []
        exchange = TraineeRealtimeExchange(
            service,
            request_json=lambda url, **_kwargs: requested_urls.append(url),
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot("trainee-local", runtime)
        manager = self._make_manager(service, exchange)

        view = manager._control_snapshot("trainee-local")

        self.assertEqual(view.source, "trainee-live")
        self.assertEqual(float(self._rated_power(view.snapshot)), 10.0)
        self.assertEqual(requested_urls, [])

    def test_exchange_cache_error_still_applies_latest_learner_definition_revision(self):
        service = self._make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
        )
        responses = [copy.deepcopy(runtime)]

        def request_json(*_args, **_kwargs):
            if responses:
                return responses.pop(0)
            raise RuntimeError("realtime source unavailable")

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        manager = self._make_manager(service, exchange)
        first = exchange.refresh_once("trainee-local")
        self.assertEqual(float(self._rated_power(first.snapshot)), 10.0)

        service.update_device_parameters(
            {
                "block_name": "ACWindGen",
                "row_key": {"idx": "1"},
                "revision": service.definition_snapshot.revision,
                "changes": {"rated_power": 18},
            }
        )
        exchange.refresh_once("trainee-local")

        cached = manager._control_snapshot("trainee-local")
        self.assertEqual(cached.source, "trainee-cache")
        self.assertIn("realtime source unavailable", cached.error)
        self.assertEqual(float(self._rated_power(cached.snapshot)), 18.0)


if __name__ == "__main__":
    unittest.main()
