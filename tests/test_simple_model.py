from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.model_fixtures import SIMPLE_MODEL_SOURCE


SIMPLE_SOURCE = SIMPLE_MODEL_SOURCE


class SimpleSimulatorModelTest(unittest.TestCase):
    def _book(self, name: str):
        import simu_loop

        return simu_loop.EBook(SIMPLE_SOURCE / name)

    @staticmethod
    def _rows(book, block_name: str):
        block = book.data.get(block_name)
        return [] if block is None else list(block.data)

    def test_service_preserves_ess_controls_as_source_device_commands(self):
        from simu.service import PolarMicrogridSimulator

        simulator = object.__new__(PolarMicrogridSimulator)
        expanded = simulator._expand_set_values(
            [
                {
                    "dev_type": "ESS",
                    "dev_name": "ess01",
                    "set_type": "p_set",
                    "set_value": 12.5,
                }
            ]
        )

        self.assertEqual(
            expanded,
            [
                {
                    "dev_type": "ESS",
                    "dev_name": "ess01",
                    "set_type": "p_set",
                    "set_value": 12.5,
                }
            ],
        )

    def test_simple_model_contains_one_core_device_of_each_kind(self):
        model = self._book("model.e")
        self.assertFalse((SIMPLE_SOURCE / "device.e").exists())

        ac_generators = [row["name"] for row in self._rows(model, "ACGenerator")]
        self.assertEqual([name for name in ac_generators if name.startswith("wt")], ["wt01_10kw"])
        self.assertEqual([name for name in ac_generators if "diesel" in name], ["diesel_300kw"])
        self.assertEqual([row["name"] for row in self._rows(model, "ACLoad")], ["load_ac_1"])
        self.assertEqual([row["name"] for row in self._rows(model, "DCDCConverter") if row["name"].startswith("pv")], ["pv01_dcdc"])
        self.assertEqual([row["name"] for row in self._rows(model, "DCDCConverter") if row["name"].startswith("ess")], ["ess01_dcdc"])
        self.assertEqual([row["name"] for row in self._rows(model, "DCACConverter") if row["name"].startswith("wt")], ["wt01_rect"])
        self.assertEqual([str(row["idx_acgenerator"]) for row in self._rows(model, "ACWindGen")], ["1"])
        self.assertEqual([str(row["idx_dcgenerator"]) for row in self._rows(model, "DCPVGen")], ["2"])
        self.assertEqual([str(row["idx_dcgenerator"]) for row in self._rows(model, "DCStorageGen")], ["3"])

    def test_storage_has_pqvi_soc_measurements_and_control_points(self):
        meas = self._book("meas.e")
        stat = self._book("stat.e")

        ess_meas_types = {
            str(row["meas_type"]).upper()
            for row in self._rows(meas, "Measurement")
            if row["dev_type"] == "ESS" and row["dev_name"] == "ess01"
        }
        self.assertEqual(ess_meas_types, {"P", "Q", "V", "I", "SOC", "RUN_STAT"})

        weather_meas_types = {
            str(row["meas_type"]).upper()
            for row in self._rows(meas, "Measurement")
            if row["dev_type"] == "Environment" and row["dev_name"] == "weather"
        }
        self.assertEqual(
            weather_meas_types,
            {"WIND_SPEED", "AIR_TEMP", "HUMIDITY", "AIR_PRESSURE", "SOLAR_IRRADIANCE"},
        )

        soc_rows = self._rows(stat, "StorageSoc")
        self.assertEqual([(row["dev_type"], row["name"]) for row in soc_rows], [("ESS", "ess01")])

        ess_set_values = {
            row["set_type"]: row["set_value"]
            for row in self._rows(stat, "SetValue")
            if row["dev_type"] == "ESS" and row["dev_name"] == "ess01"
        }
        self.assertIn("p_set", ess_set_values)
        self.assertIn("v_set", ess_set_values)

    def test_service_exposes_storage_device_from_device_parameters_without_soc_block(self):
        from simu.service import PolarMicrogridSimulator

        with tempfile.TemporaryDirectory() as temporary:
            source_dir = Path(temporary) / "source"
            runtime_dir = Path(temporary) / "runtime"
            shutil.copytree(SIMPLE_SOURCE, source_dir)
            stat_path = source_dir / "stat.e"
            stat_text = stat_path.read_text(encoding="utf-8")
            stat_path.write_text(
                re.sub(r"\n<StorageSoc>.*?</StorageSoc>\s*", "\n", stat_text, flags=re.DOTALL),
                encoding="utf-8",
            )

            service = PolarMicrogridSimulator(source_dir, runtime_dir, model_id="simple")
            storage_devices = [
                device
                for device in service.devices()
                if device["dev_type"] == "DCGenerator" and device["dev_name"] == "ess01_vsrc"
            ]

            self.assertEqual(len(storage_devices), 1)
            self.assertIn("p_set", storage_devices[0]["set_types"])
            self.assertIn("soc_curr", storage_devices[0])

    def test_dc_generators_have_realtime_pvi_measurements(self):
        model = self._book("model.e")
        meas = self._book("meas.e")
        measurement_rows = self._rows(meas, "Measurement")

        for generator in self._rows(model, "DCGenerator"):
            meas_types = {
                str(row["meas_type"]).upper()
                for row in measurement_rows
                if row["dev_type"] == "DCGenerator" and row["dev_name"] == generator["name"]
            }
            self.assertEqual(meas_types, {"P_GEN", "V_GEN", "I_GEN", "RUN_STAT"})


if __name__ == "__main__":
    unittest.main()
