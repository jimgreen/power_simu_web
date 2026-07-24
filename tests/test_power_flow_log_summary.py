from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class PowerFlowLogSummaryTest(unittest.TestCase):
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

    def test_power_flow_log_uses_category_summary_instead_of_device_details(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service._append_power_flow_log(
            {"solver_info": "iter=2", "updated": 8, "missing": 0, "overlay_updates": 0},
            {
                "real": [
                    {"dev_type": "DCACConverter", "dev_name": "wt01_rect", "meas_type": "P_AC", "value": 8.0},
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "meas_type": "P_GEN", "value": 8.0},
                    {"dev_type": "DCDCConverter", "dev_name": "pv01_dcdc", "meas_type": "P_TO", "value": 20.0},
                    {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "meas_type": "P_GEN", "value": 30.0},
                    {"dev_type": "ACLoad", "dev_name": "load_ac_1", "meas_type": "P_LOAD", "value": 90.0},
                    {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "P", "value": -5.0},
                    {"dev_type": "ESS", "dev_name": "ess01", "meas_type": "SOC", "value": 0.55},
                    {"dev_type": "ACNode", "dev_name": "ac_bus", "meas_type": "V", "value": 380.0},
                    {"dev_type": "DCDCConverter", "dev_name": "ess01_dcdc", "meas_type": "P_FROM", "value": -5.0},
                ],
            },
            minute=0,
            absolute_minute=0,
            clock_advance=1,
            period_seconds=60.0,
            command_response_lines=["控制响应 本轮无新增学员台控制指令"],
        )

        detail = service.runtime_logs[-1]["detail"]
        text = "\n".join(detail)

        self.assertIn("风力发电总功率 8 kW", text)
        self.assertIn("光伏发电总功率 20 kW", text)
        self.assertIn("柴油发电总功率 30 kW", text)
        self.assertIn("负荷用电总功率 90 kW", text)
        self.assertIn("储能发电总功率 0 kW", text)
        self.assertIn("储能充电总功率 5 kW", text)
        self.assertIn("储能SOC 平均 55%", text)
        self.assertNotIn("DCACConverter.wt01_rect:", text)
        self.assertNotIn("ACNode.ac_bus:", text)
        self.assertIn("风力发电总功率 8 kW（1 台）", text)
        self.assertNotIn("风力发电总功率 16 kW", text)
        self.assertLessEqual(len(detail), 6)


if __name__ == "__main__":
    unittest.main()
