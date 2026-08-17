from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class RemoteAdjustmentResponseTest(unittest.TestCase):
    def _make_service(self, *, enforce_runtime_setpoint_bounds=True):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        boundaries = []

        def kernel(config):
            boundaries.append(
                {
                    "stat": config.dev_stat_book,
                    "yt": config.yt_ctrl_book,
                }
            )
            return None

        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=kernel,
            enforce_runtime_setpoint_bounds=enforce_runtime_setpoint_bounds,
        )
        return workspace, service, boundaries

    @staticmethod
    def _book_set_value(book, dev_type: str, dev_name: str, set_type: str) -> float:
        row = next(
            item
            for item in book.data["SetValue"].data
            if item["dev_type"] == dev_type
            and item["dev_name"] == dev_name
            and item["set_type"] == set_type
        )
        return float(row["set_value"])

    @staticmethod
    def _set_real_measurement(service, dev_type: str, dev_name: str, meas_type: str, value: float) -> None:
        definition = next(
            list(row)
            for row in service.definition_snapshot.measurement_rows
            if row[2] == dev_type and row[3] == dev_name and row[4].upper() == meas_type.upper()
        )
        definition[7] = str(value)
        service.latest_real_rows = [definition]

    def _send_adjustment(self, service, value: float, *, dev_type: str = "ESS", dev_name: str = "ess01", set_type: str = "p_set"):
        result = service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": dev_type,
                        "dev_name": dev_name,
                        "set_type": set_type,
                        "set_value": value,
                    }
                ]
            },
            source="trainee-ui",
        )
        self.assertEqual(result["set_values"], 1)

    def test_default_response_uses_seventy_percent_of_remaining_error_each_cycle(self):
        workspace, service, boundaries = self._make_service()
        self.addCleanup(workspace.cleanup)

        self._send_adjustment(service, 20)

        self.assertEqual(
            service.latest_control_values()["values"]["ESS.ess01.p_set"],
            20,
        )
        service.step()
        first = boundaries[-1]
        self.assertAlmostEqual(self._book_set_value(first["stat"], "ESS", "ess01", "p_set"), 17.0)
        self.assertAlmostEqual(self._book_set_value(first["yt"], "ESS", "ess01", "p_set"), 17.0)

        service.step()
        second = boundaries[-1]
        self.assertAlmostEqual(self._book_set_value(second["stat"], "ESS", "ess01", "p_set"), 19.1)
        self.assertAlmostEqual(self._book_set_value(second["yt"], "ESS", "ess01", "p_set"), 19.1)

    def test_response_uses_latest_true_power_flow_value_when_available(self):
        workspace, service, boundaries = self._make_service()
        self.addCleanup(workspace.cleanup)
        self._set_real_measurement(service, "ESS", "ess01", "P", 6.0)

        self._send_adjustment(service, 20)
        service.step()

        self.assertAlmostEqual(
            self._book_set_value(boundaries[-1]["stat"], "ESS", "ess01", "p_set"),
            15.8,
        )

    def test_load_flow_failure_backtracks_only_this_cycles_remote_adjustment(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        boundaries = []

        def feasibility_limited_kernel(config):
            value = self._book_set_value(config.yt_ctrl_book, "ESS", "ess01", "p_set")
            boundaries.append(value)
            if value > 14.0:
                raise RuntimeError(
                    "Hybrid load flow failed for in-memory model model.e: "
                    "rc=-1, iter=20, normF=1.000e-02"
                )
            return None

        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=feasibility_limited_kernel,
        )
        self._set_real_measurement(service, "ESS", "ess01", "P", 10.0)
        self._send_adjustment(service, 20.0)

        snapshot = service.step(advance_minutes=1)

        self.assertEqual(boundaries, [17.0, 13.5])
        self.assertEqual(snapshot["compute"]["status"], "ok")
        self.assertEqual(snapshot["compute"]["boundary_backtracked"], True)
        self.assertEqual(snapshot["compute"]["boundary_backtrack_factor"], 0.5)
        self.assertEqual(snapshot["result"]["boundary_backtrack"]["factor"], 0.5)
        self.assertEqual(snapshot["clock"]["step_count"], 1)
        self.assertEqual(service.clock.state, "stopped")
        self.assertEqual(
            service.latest_control_values()["values"]["ESS.ess01.p_set"],
            20.0,
        )
        recovery_log = next(
            item
            for item in reversed(service.runtime_logs)
            if item["result"] == "自动回退后收敛"
        )
        self.assertEqual(recovery_log["level"], "warn")
        self.assertIn("17", "\n".join(recovery_log["detail"]))
        self.assertIn("13.5", "\n".join(recovery_log["detail"]))

    def test_simulator_sends_out_of_bounds_smooth_boundary_to_kernel(self):
        workspace, service, boundaries = self._make_service(
            enforce_runtime_setpoint_bounds=False
        )
        self.addCleanup(workspace.cleanup)

        self._send_adjustment(
            service,
            0,
            dev_type="ACGenerator",
            dev_name="diesel_300kw",
            set_type="p_set",
        )
        service.step()

        self.assertAlmostEqual(
            self._book_set_value(
                boundaries[-1]["stat"],
                "ACGenerator",
                "diesel_300kw",
                "p_set",
            ),
            24.0,
        )
        self.assertAlmostEqual(
            self._book_set_value(
                boundaries[-1]["yt"],
                "ACGenerator",
                "diesel_300kw",
                "p_set",
            ),
            24.0,
        )

    def test_changed_target_reverses_gradually_from_last_executed_boundary(self):
        workspace, service, boundaries = self._make_service()
        self.addCleanup(workspace.cleanup)

        self._send_adjustment(service, 20)
        service.step()
        self.assertAlmostEqual(self._book_set_value(boundaries[-1]["stat"], "ESS", "ess01", "p_set"), 17.0)

        self._send_adjustment(service, 0)
        service.step()

        self.assertAlmostEqual(self._book_set_value(boundaries[-1]["stat"], "ESS", "ess01", "p_set"), 5.1)

    def test_manual_command_keeps_priority_when_automatic_command_arrives_later(self):
        workspace, service, boundaries = self._make_service()
        self.addCleanup(workspace.cleanup)

        self._send_adjustment(service, 20)
        service.step()
        self.assertAlmostEqual(self._book_set_value(boundaries[-1]["stat"], "ESS", "ess01", "p_set"), 17.0)

        result = service.apply_student_commands(
            {
                "command_origin": "automatic",
                "valid_for_minutes": 1,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 0}
                ],
            },
            source="trainee-automatic-control",
        )
        self.assertEqual(result["set_values"], 1)
        service.step()
        self.assertAlmostEqual(self._book_set_value(boundaries[-1]["stat"], "ESS", "ess01", "p_set"), 19.1)

        service.clock.absolute_minute = 2.0
        service.clock.minute = 2.0
        service.step()
        self.assertAlmostEqual(self._book_set_value(boundaries[-1]["stat"], "ESS", "ess01", "p_set"), 19.73)
        self.assertEqual(
            service.latest_control_values()["values"]["ESS.ess01.p_set"],
            20,
        )

    def test_converter_dc_setpoint_uses_dc_terminal_true_power(self):
        workspace, service, boundaries = self._make_service()
        self.addCleanup(workspace.cleanup)
        self._set_real_measurement(service, "DCACConverter", "grid_inv_acp", "P_DC", 5.0)

        self._send_adjustment(
            service,
            65,
            dev_type="DCACConverter",
            dev_name="grid_inv_acp",
            set_type="p_dc_set",
        )
        service.step()

        self.assertAlmostEqual(
            self._book_set_value(
                boundaries[-1]["stat"],
                "DCACConverter",
                "grid_inv_acp",
                "p_dc_set",
            ),
            47.0,
        )

    def test_remote_control_status_remains_immediate(self):
        workspace, service, _boundaries = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 0}
                ]
            },
            source="trainee-ui",
        )

        self.assertEqual(result["run_status"], 1)
        self.assertEqual(
            service.latest_control_values()["values"]["ACGenerator.wt01_10kw.run_stat"],
            0,
        )

    def test_response_ratio_is_configurable_and_persisted_per_model(self):
        from simu.service import PolarMicrogridSimulator

        workspace, service, boundaries = self._make_service()
        self.addCleanup(workspace.cleanup)

        updated = service.set_system_parameters({"remote_adjustment_response_ratio": 0.25})
        self.assertEqual(updated["system_parameters"]["remote_adjustment_response_ratio"], 0.25)

        self._send_adjustment(service, 20)
        service.step()
        self.assertAlmostEqual(
            self._book_set_value(boundaries[-1]["stat"], "ESS", "ess01", "p_set"),
            12.5,
        )

        restored = PolarMicrogridSimulator(service.sim_dir, service.runtime_dir, kernel=lambda _config: None)
        self.assertEqual(
            restored.system_parameters()["remote_adjustment_response_ratio"],
            0.25,
        )

    def test_simulator_parameter_page_exposes_remote_adjustment_response_ratio(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app = (root / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="parameterRemoteAdjustmentResponseRatio"', html)
        self.assertIn("遥调指令响应系数", html)
        self.assertIn("remote_adjustment_response_ratio", app)
        self.assertIn("remote_adjustment_response_ratio: 0.7", app)


if __name__ == "__main__":
    unittest.main()
