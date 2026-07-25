from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path


class RuntimeLogNumberFormatTest(unittest.TestCase):
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

    def test_runtime_log_detail_numbers_keep_at_most_two_decimal_places(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service._append_runtime_log(
            "环境/负荷",
            "weather.e / curves.json",
            "逐点读取",
            [
                "环境 风速 16.967 m/s，气温 -27.852 ℃，气压 961.984 hPa，湿度 79.508 %",
                "负荷合计 80.051 kW；load_ac_1=80.051 kW",
                "求解器 iter=4, normF=1.118e-13，储能SOC 平均 46.3333316%，储能总SOC 0.463333316",
            ],
        )

        text = "\n".join(service.runtime_logs[-1]["detail"])

        self.assertIn("16.97 m/s", text)
        self.assertIn("-27.85 ℃", text)
        self.assertIn("961.98 hPa", text)
        self.assertIn("80.05 kW", text)
        self.assertIn("normF=1.12e-13", text)
        self.assertIn("46.33%", text)
        self.assertIn("储能总SOC 0.46", text)
        self.assertIsNone(re.search(r"(?<![\w:])[-+]?\d+\.\d{3,}(?:e[-+]?\d+)?(?![\w:])", text))


if __name__ == "__main__":
    unittest.main()
