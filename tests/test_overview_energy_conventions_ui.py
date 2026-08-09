from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _function_block(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


@unittest.skipUnless(NODE, "node is required for frontend convention tests")
class OverviewEnergyConventionsUiTest(unittest.TestCase):
    def _evaluate(self, script_path: Path) -> dict:
        source = script_path.read_text(encoding="utf-8")
        green_functions = _function_block(
            source,
            "function overviewGreenGroupPower",
            "function overviewFlowPowerValue",
        )
        flow_function = _function_block(
            source,
            "function overviewFlowState",
            "function normalizeOverviewFlowGroups",
        )
        node_script = f"""
{green_functions}
{flow_function}

const metrics = overviewGreenMetrics({{
  flowGroups: {{
    dcLoad: {{ present: true, power: 0.01 }},
    acLoad: {{ present: true, power: 241.50 }},
    diesel: {{ present: true, power: 207.54 }},
  }},
}});
const zeroLoad = overviewGreenMetrics({{
  flowGroups: {{
    dcLoad: {{ present: true, power: 0 }},
    acLoad: {{ present: true, power: 0 }},
    diesel: {{ present: true, power: 0 }},
  }},
}});
const negativeGreen = overviewGreenMetrics({{
  flowGroups: {{
    dcLoad: {{ present: true, power: 10 }},
    acLoad: {{ present: true, power: 20 }},
    diesel: {{ present: true, power: 40 }},
  }},
}});
const missingMeasurement = overviewGreenMetrics({{
  flowGroups: {{
    dcLoad: {{ present: true, power: null }},
    acLoad: {{ present: true, power: 20 }},
    diesel: {{ present: true, power: 10 }},
  }},
}});
const absentDcLoad = overviewGreenMetrics({{
  flowGroups: {{
    dcLoad: {{ present: false, power: null }},
    acLoad: {{ present: true, power: 100 }},
    diesel: {{ present: true, power: 30 }},
  }},
}});

process.stdout.write(JSON.stringify({{
  metrics,
  zeroLoad,
  negativeGreen,
  missingMeasurement,
  absentDcLoad,
  positiveConverter: overviewFlowState("converter", 20),
  negativeConverter: overviewFlowState("converter", -20),
}}));
"""
        completed = subprocess.run(
            [NODE, "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_simulator_and_trainee_share_green_formula_and_converter_sign(self):
        for relative_path in (
            Path("simu/web/simulator/app.js"),
            Path("simu/web/trainee/app.js"),
        ):
            with self.subTest(script=str(relative_path)):
                result = self._evaluate(ROOT / relative_path)

                self.assertAlmostEqual(result["metrics"]["loadPower"], 241.51)
                self.assertAlmostEqual(result["metrics"]["greenPower"], 33.97)
                self.assertAlmostEqual(
                    result["metrics"]["greenPowerShare"],
                    33.97 / 241.51 * 100.0,
                )
                self.assertIsNone(result["zeroLoad"]["greenPowerShare"])
                self.assertEqual(result["negativeGreen"]["greenPower"], -10)
                self.assertAlmostEqual(
                    result["negativeGreen"]["greenPowerShare"],
                    -10 / 30 * 100.0,
                )
                self.assertIsNone(result["missingMeasurement"]["loadPower"])
                self.assertIsNone(result["missingMeasurement"]["greenPower"])
                self.assertIsNone(result["missingMeasurement"]["greenPowerShare"])
                self.assertEqual(result["absentDcLoad"]["greenPower"], 70)
                self.assertEqual(
                    result["positiveConverter"],
                    {"status": "acToDc", "flowDirection": "toDc"},
                )
                self.assertEqual(
                    result["negativeConverter"],
                    {"status": "dcToAc", "flowDirection": "toAc"},
                )


if __name__ == "__main__":
    unittest.main()
