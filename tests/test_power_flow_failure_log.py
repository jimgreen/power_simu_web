from __future__ import annotations

import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
