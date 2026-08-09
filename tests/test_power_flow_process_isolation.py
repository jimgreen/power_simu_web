from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path


class PowerFlowProcessIsolationTest(unittest.TestCase):
    def _make_service(self, **kwargs):
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
            model_id="process-isolation",
            **kwargs,
        )
        return workspace, service

    def test_process_runner_executes_the_real_kernel_outside_the_http_process(self):
        from simu.power_flow_worker import PowerFlowProcessRunner

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        runner = PowerFlowProcessRunner(max_workers=1)
        self.addCleanup(runner.close)

        outcome = runner.run(service._make_config(period_seconds=1.0))

        self.assertNotEqual(outcome.worker_pid, os.getpid())
        self.assertEqual(outcome.mode, "process")
        self.assertIsNotNone(outcome.result)
        self.assertIsNotNone(outcome.runtime_stat_book)
        self.assertGreaterEqual(outcome.compute_seconds, 0.0)

    def test_process_runner_preserves_ph_converter_topology_across_cycles(self):
        from simu.power_flow_worker import PowerFlowProcessRunner

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        runner = PowerFlowProcessRunner(max_workers=1)
        self.addCleanup(runner.close)
        config = service._make_config(period_seconds=1.0)

        expected_online = {
            ("ACGenerator", "wt01_10kw"),
            ("ACBranch", "wt01_cable"),
            ("ACNode", "wt01_src"),
            ("ACNode", "wt01_rect"),
            ("DCACConverter", "wt01_rect"),
            ("DCNode", "wt01_dc"),
        }
        worker_pid = None
        for _cycle in range(3):
            outcome = runner.run(config)
            if worker_pid is None:
                worker_pid = outcome.worker_pid
            self.assertEqual(outcome.worker_pid, worker_pid)

            converter = next(
                row
                for row in outcome.result.model_book.data["DCACConverter"].data
                if row.get("name") == "wt01_rect"
            )
            self.assertEqual(converter["ac_control_type"], "PH")
            self.assertEqual(converter["dc_control_type"], "NONE")

            states = {
                (row["dev_type"], row["dev_name"]): row
                for row in outcome.result.device_states
            }
            for key in expected_online:
                self.assertIn(key, states)
                self.assertEqual(states[key]["run_stat"], 1)
                self.assertFalse(states[key]["dead_island"], key)

    def test_service_releases_its_state_lock_while_waiting_for_the_kernel_worker(self):
        from simu.power_flow_worker import PowerFlowExecution

        entered = threading.Event()
        release = threading.Event()

        class BlockingRunner:
            def run(self, config):
                entered.set()
                if not release.wait(5.0):
                    raise TimeoutError("test worker was not released")
                return PowerFlowExecution(
                    result=None,
                    runtime_stat_book=config.dev_stat_book,
                    worker_pid=12345,
                    compute_seconds=0.01,
                    round_trip_seconds=0.02,
                    mode="process",
                )

        workspace, service = self._make_service(
            kernel=lambda _config: None,
            kernel_runner=BlockingRunner(),
        )
        self.addCleanup(workspace.cleanup)
        errors = []

        def run_step():
            try:
                service.step(advance_seconds=1.0)
            except Exception as exc:  # pragma: no cover - asserted below.
                errors.append(exc)

        thread = threading.Thread(target=run_step, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(2.0))

        acquired = service.lock.acquire(timeout=0.25)
        if acquired:
            service.lock.release()
        release.set()
        thread.join(timeout=5.0)

        self.assertTrue(acquired, "kernel wait still owns the HTTP service state lock")
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_step_exposes_http_and_worker_process_diagnostics(self):
        from simu.power_flow_worker import PowerFlowProcessRunner

        runner = PowerFlowProcessRunner(max_workers=1)
        self.addCleanup(runner.close)
        workspace, service = self._make_service(kernel_runner=runner)
        self.addCleanup(workspace.cleanup)

        snapshot = service.step(advance_seconds=1.0)

        self.assertEqual(snapshot["compute"]["mode"], "process")
        self.assertEqual(snapshot["compute"]["http_pid"], os.getpid())
        self.assertNotEqual(snapshot["compute"]["worker_pid"], os.getpid())
        self.assertGreaterEqual(snapshot["compute"]["round_trip_ms"], snapshot["compute"]["compute_ms"])

    def test_timed_out_worker_is_terminated_and_rebuilt_for_the_next_calculation(self):
        from simu.power_flow_worker import PowerFlowProcessRunner, PowerFlowTimeoutError

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        runner = PowerFlowProcessRunner(max_workers=1, timeout_seconds=0.000001)
        self.addCleanup(runner.close)
        config = service._make_config(period_seconds=1.0)

        with self.assertRaises(PowerFlowTimeoutError):
            runner.run(config)

        timed_out = runner.diagnostics()
        self.assertEqual(timed_out["timeout_count"], 1)
        self.assertEqual(timed_out["restart_count"], 1)
        self.assertEqual(timed_out["last_restart_reason"], "timeout")
        self.assertGreater(timed_out["last_timeout_at"], 0.0)
        runner.timeout_seconds = 30.0

        outcome = runner.run(config)

        self.assertIsNotNone(outcome.result)
        self.assertNotEqual(outcome.worker_pid, os.getpid())
        recovered = runner.diagnostics()
        self.assertEqual(recovered["timeout_count"], 1)
        self.assertEqual(recovered["restart_count"], 1)
        self.assertFalse(recovered["closed"])

    def test_power_flow_timeout_is_configurable_from_the_server_command_line(self):
        from simu.server import parse_args

        args = parse_args(["--power-flow-timeout-seconds", "45"])

        self.assertEqual(args.power_flow_timeout_seconds, 45.0)

    def test_service_marks_a_timed_out_calculation_without_advancing_the_clock(self):
        from simu.power_flow_worker import PowerFlowTimeoutError

        class TimeoutRunner:
            def run(self, _config):
                raise PowerFlowTimeoutError(0.25)

        workspace, service = self._make_service(
            kernel=lambda _config: None,
            kernel_runner=TimeoutRunner(),
        )
        self.addCleanup(workspace.cleanup)
        before_step = service.clock.step_count
        before_minute = service.clock.absolute_minute

        with self.assertRaises(PowerFlowTimeoutError):
            service.step(advance_seconds=1.0)

        self.assertEqual(service.latest_compute["status"], "timeout")
        self.assertEqual(service.clock.step_count, before_step)
        self.assertEqual(service.clock.absolute_minute, before_minute)


if __name__ == "__main__":
    unittest.main()
