from __future__ import annotations

import copy
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_next_control_cycle_combines_latest_local_svg_settings_and_remote_runtime_frame(self):
        import simu.renewable_control as renewable_control_module

        service = self._make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
        )
        runtime["simulation_timing"] = {
            "simulation_step_seconds": 300.0,
            "simulation_period_seconds": 0.5,
        }
        runtime["clock"].update(
            {
                "speed": 300.0,
                "effective_step_seconds": 300.0,
                "effective_step_minutes": 5.0,
            }
        )
        power_definition = next(
            row
            for row in runtime["measurements"]["definitions"]
            if row.get("dev_type") == "ACGenerator"
            and row.get("dev_name") == "wt01_10kw"
            and row.get("meas_type") == "P_GEN"
        )
        power_row = copy.deepcopy(power_definition)
        power_row["value"] = 7.25
        runtime["measurements"]["scada"].append(power_row)
        signal_row = next(
            row
            for row in runtime["measurements"]["scada"]
            if row.get("dev_type") == "ACGenerator"
            and row.get("dev_name") == "diesel_300kw"
            and row.get("meas_type") == "RUN_STAT"
        )
        signal_row["value"] = 0
        remote_diesel = next(
            row
            for row in runtime["devices"]
            if row.get("dev_type") == "ACGenerator" and row.get("dev_name") == "diesel_300kw"
        )
        remote_diesel["run_stat"] = 0
        runtime["device_states"] = [
            {
                "dev_type": "ACGenerator",
                "dev_name": "diesel_300kw",
                "run_stat": 0,
                "dead_island": False,
            }
        ]

        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot("trainee-local", runtime)
        manager = self._make_manager(service, exchange)
        service.update_device_parameters(
            {
                "block_name": "ACWindGen",
                "row_key": {"idx": "1"},
                "revision": service.definition_snapshot.revision,
                "changes": {"rated_power": 22},
            }
        )
        manager.apply_action(
            "trainee-local",
            {
                "action": "update_settings",
                "settings": {"renewableStepRatio": 0.09, "intervalSeconds": 7},
            },
        )
        captured = {}
        original_calculate = renewable_control_module.calculate_renewable_control_plan

        def capture_inputs(snapshot, settings, **kwargs):
            captured["snapshot"] = copy.deepcopy(snapshot)
            captured["settings"] = settings
            return original_calculate(snapshot, settings, **kwargs)

        with patch.object(
            renewable_control_module,
            "calculate_renewable_control_plan",
            side_effect=capture_inputs,
        ):
            manager.collect_once("trainee-local")

        control_snapshot = captured["snapshot"]
        self.assertEqual(self._rated_power(control_snapshot), 22)
        self.assertEqual(
            control_snapshot["simulation_timing"],
            {"simulation_step_seconds": 300.0, "simulation_period_seconds": 0.5},
        )
        self.assertEqual(control_snapshot["clock"]["speed"], 300.0)
        captured_power = next(
            row
            for row in control_snapshot["measurements"]["scada"]
            if row.get("dev_type") == "ACGenerator"
            and row.get("dev_name") == "wt01_10kw"
            and row.get("meas_type") == "P_GEN"
        )
        captured_signal = next(
            row
            for row in control_snapshot["measurements"]["scada"]
            if row.get("dev_type") == "ACGenerator"
            and row.get("dev_name") == "diesel_300kw"
            and row.get("meas_type") == "RUN_STAT"
        )
        self.assertEqual(captured_power["value"], 7.25)
        self.assertEqual(captured_signal["value"], 0)
        self.assertEqual(control_snapshot["device_states"][0]["run_stat"], 0)
        self.assertAlmostEqual(captured["settings"].step_coefficient, 0.09)
        self.assertAlmostEqual(captured["settings"].interval_seconds, 7.0)

    def test_new_remote_runtime_frame_during_calculation_cancels_old_candidate(self):
        import simu.renewable_control as renewable_control_module

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
        state = manager._state_for("trainee-local")
        prior_plan = {"time": "prior", "clockKey": "prior", "commands": []}
        state.last_plan = copy.deepcopy(prior_plan)
        state.last_calculated_at = "prior-calculated"
        calculation_started = threading.Event()
        release_calculation = threading.Event()
        original_calculate = renewable_control_module.calculate_renewable_control_plan

        def blocking_calculate(*args, **kwargs):
            calculation_started.set()
            self.assertTrue(release_calculation.wait(2.0))
            return original_calculate(*args, **kwargs)

        result_holder = {}
        thread = threading.Thread(
            target=lambda: result_holder.setdefault("state", manager.collect_once("trainee-local")),
            daemon=True,
        )
        try:
            with patch.object(
                renewable_control_module,
                "calculate_renewable_control_plan",
                side_effect=blocking_calculate,
            ):
                thread.start()
                self.assertTrue(calculation_started.wait(2.0))
                next_runtime = copy.deepcopy(runtime)
                next_runtime["clock"]["step_count"] = int(runtime["clock"].get("step_count", 0)) + 1
                next_runtime["clock"]["time"] = "00:01:00"
                next_runtime["simulation_timing"] = {
                    "simulation_step_seconds": 60.0,
                    "simulation_period_seconds": 0.25,
                }
                exchange.publish_runtime_snapshot("trainee-local", next_runtime)
                release_calculation.set()
                thread.join(3.0)
        finally:
            release_calculation.set()

        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder["state"]["lastPlan"], prior_plan)
        self.assertEqual(result_holder["state"]["lastCalculatedAt"], "prior-calculated")


if __name__ == "__main__":
    unittest.main()
