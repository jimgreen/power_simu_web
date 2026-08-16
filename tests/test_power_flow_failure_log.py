from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


class PowerFlowFailureLogTest(unittest.TestCase):
    def test_step_records_power_flow_divergence_before_raising(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)

        def failing_kernel(_config):
            raise RuntimeError(
                "Hybrid load flow failed for in-memory model model.e: rc=-1, iter=50, normF=nan"
            )

        service = PolarMicrogridSimulator(source, runtime, kernel=failing_kernel, model_id="failure")
        service.control_clock({"action": "start"})

        with self.assertRaises(RuntimeError):
            service.step(advance_minutes=1)

        self.assertGreaterEqual(len(service.runtime_logs), 1)
        log = service.runtime_logs[-1]
        self.assertEqual(log["type"], "潮流计算")
        self.assertEqual(log["result"], "数值发散")
        self.assertEqual(log["level"], "error")
        self.assertEqual(log["simu_time"], "00:00:00")
        detail_text = "\n".join(log["detail"])
        self.assertIn("计算失败", detail_text)
        self.assertIn("Hybrid load flow failed", detail_text)
        self.assertIn("iter=50", detail_text)
        self.assertIn("normF=nan", detail_text)

        snapshot = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
            include_devices=False,
            include_device_states=False,
            include_commands=False,
        )
        self.assertEqual(snapshot["compute"]["status"], "failed")
        self.assertEqual(snapshot["compute"]["result_discarded"], True)
        self.assertEqual(snapshot["compute"]["simu_time"], "00:00:00")
        self.assertIn("Hybrid load flow failed", snapshot["compute"]["error"])
        self.assertIn("iter=50", snapshot["compute"]["error"])
        self.assertIn("normF=nan", snapshot["compute"]["error"])
        self.assertEqual(snapshot["compute"]["measurement_frame_stale"], True)
        self.assertEqual(snapshot["compute"]["last_successful_simu_time"], "")
        self.assertEqual(snapshot["clock"]["state"], "paused")
        self.assertEqual(snapshot["clock"]["step_count"], 0)
        self.assertEqual(snapshot["result"]["solver_info"], "failed")
        self.assertEqual(snapshot["summary"]["power_flow_alarm_count"], 1)
        self.assertEqual(snapshot["summary"]["measurement_alarm_count"], 0)
        self.assertEqual(snapshot["summary"]["alarm_count"], 1)

        from simu.trainee_data_policy import strip_trainee_remote_details_from_snapshot

        trainee_snapshot = strip_trainee_remote_details_from_snapshot(deepcopy(snapshot))
        self.assertEqual(trainee_snapshot["compute"]["status"], "failed")
        self.assertEqual(trainee_snapshot["compute"]["result_discarded"], True)
        self.assertEqual(trainee_snapshot["compute"]["measurement_frame_stale"], True)
        self.assertNotIn("error", trainee_snapshot["compute"])
        self.assertEqual(trainee_snapshot["result"]["solver_info"], "failed")
        self.assertNotIn("error", trainee_snapshot["result"])

    def test_previous_successful_frame_is_marked_stale_until_solver_recovers(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)

        service = PolarMicrogridSimulator(source, runtime, model_id="failure-recovery")
        successful_kernel = service.kernel
        service.control_clock({"action": "start"})
        successful = service.step(advance_minutes=1)
        successful_measurements = deepcopy(successful["measurements"])
        self.assertEqual(successful["compute"]["status"], "ok")
        self.assertEqual(successful["measurement_clock"]["time"], "00:00:00")

        def failing_kernel(_config):
            raise RuntimeError(
                "Hybrid load flow failed after a successful frame: rc=-1, iter=49, normF=1.181e-01"
            )

        service.kernel = failing_kernel
        with self.assertRaises(RuntimeError):
            service.step(advance_minutes=1)

        failed = service.snapshot()
        self.assertEqual(failed["clock"]["state"], "paused")
        self.assertEqual(failed["clock"]["step_count"], 1)
        self.assertEqual(failed["compute"]["status"], "failed")
        self.assertEqual(failed["compute"]["last_successful_simu_time"], "00:00:00")
        self.assertEqual(failed["compute"]["measurement_frame_stale"], True)
        self.assertEqual(failed["measurement_clock"]["time"], "00:00:00")
        self.assertEqual(failed["measurements"], successful_measurements)
        self.assertEqual(failed["summary"]["power_flow_alarm_count"], 1)

        service.kernel = successful_kernel
        service.control_clock({"action": "start"})
        recovered = service.step(advance_minutes=1)
        self.assertEqual(recovered["clock"]["state"], "running")
        self.assertEqual(recovered["compute"]["status"], "ok")
        self.assertNotIn("result_discarded", recovered["compute"])
        self.assertNotIn("measurement_frame_stale", recovered["compute"])
        self.assertEqual(recovered["measurement_clock"]["time"], "00:01:00")
        self.assertEqual(recovered["summary"]["power_flow_alarm_count"], 0)
        self.assertEqual(recovered["summary"]["alarm_count"], 0)


if __name__ == "__main__":
    unittest.main()
