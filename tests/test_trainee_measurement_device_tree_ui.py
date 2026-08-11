from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_source(script: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\) \{{.*?^\}}",
        script,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing JavaScript function: {name}")
    return match.group(0)


class TraineeMeasurementDeviceTreeUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    def test_measurement_devices_inherit_structured_model_metadata(self):
        sources = "\n".join(
            function_source(self.script, name)
            for name in (
                "measurementDeviceMetadataIndex",
                "measurementsDevices",
            )
        )
        node_script = f"""
const state = {{ snapshot: {{}} }};
const deviceModelBlock = (dev) => String(dev?.model_block || dev?.raw?.model_block || "").trim();
const deviceFamily = (dev) => String(dev?.device_family || "").trim().toLowerCase();
const definedModelDevices = (snapshot) => snapshot.modelDevices || [];
const measurementRows = (snapshot) => snapshot.rows || [];
const isWeatherMeasurement = (row) => row?.dev_type === "Environment" && row?.dev_name === "weather";
{sources}
const devices = measurementsDevices({{
  devices: [{{
    dev_type: "ACGenerator",
    dev_name: "source-1",
    model_block: "ACGenerator",
    device_family: "generator",
    terminal_domains: ["AC"],
    resource_technology: "wind",
  }}],
  modelDevices: [{{
    dev_type: "ACNode",
    dev_name: "bus-1",
    model_block: "ACNode",
  }}],
  rows: [
    {{ dev_type: "ACGenerator", dev_name: "source-1", valid: 1 }},
    {{ dev_type: "ACNode", dev_name: "bus-1", valid: 1 }},
    {{ dev_type: "Environment", dev_name: "weather", valid: 1 }},
  ],
}});
process.stdout.write(JSON.stringify(devices));
"""
        completed = subprocess.run(
            ["node", "-"],
            check=True,
            capture_output=True,
            input=node_script,
            text=True,
            encoding="utf-8",
        )
        devices = json.loads(completed.stdout)
        by_key = {
            f"{device['dev_type']}|{device['dev_name']}": device
            for device in devices
        }

        self.assertEqual(by_key["ACGenerator|source-1"]["model_block"], "ACGenerator")
        self.assertEqual(by_key["ACGenerator|source-1"]["device_family"], "generator")
        self.assertEqual(by_key["ACGenerator|source-1"]["terminal_domains"], ["AC"])
        self.assertEqual(by_key["ACGenerator|source-1"]["resource_technology"], "wind")
        self.assertEqual(by_key["ACNode|bus-1"]["model_block"], "ACNode")
        self.assertEqual(by_key["Environment|weather"]["model_block"], "Environment")
        self.assertNotIn("Unknown", {device.get("model_block") for device in devices})

    def test_measurement_tree_search_refresh_uses_current_snapshot(self):
        refresh = function_source(self.script, "refreshDeviceTreeFilterScope")

        self.assertIn("measurementsDevices(state.snapshot || {})", refresh)
        self.assertNotIn("measurementDevices()", refresh)


if __name__ == "__main__":
    unittest.main()
