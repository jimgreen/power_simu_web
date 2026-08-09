from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


class DeviceControlModeTest(unittest.TestCase):
    def test_dcac_device_mode_uses_ac_control_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_dir = Path(temporary) / "source"
            shutil.copytree(SIMPLE_MODEL_SOURCE, source_dir)

            service = PolarMicrogridSimulator(
                source_dir,
                Path(temporary) / "runtime",
                model_id="simple-ac-mode",
            )

            grid_converter = next(
                device
                for device in service.devices()
                if device["dev_type"] == "DCACConverter" and device["dev_name"] == "grid_inv_acp"
            )

        self.assertEqual(grid_converter["mode"], "PQ")


if __name__ == "__main__":
    unittest.main()
