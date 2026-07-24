from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIMPLE_MODEL = "\u7b80\u5355\u6a21\u578b"
SIMPLE_SOURCE = ROOT / "models" / "simulator" / "source" / SIMPLE_MODEL


class SimpleSimulatorModelTest(unittest.TestCase):
    def _book(self, name: str):
        import simu_loop

        return simu_loop.EBook(SIMPLE_SOURCE / name)

    @staticmethod
    def _rows(book, block_name: str):
        block = book.data.get(block_name)
        return [] if block is None else list(block.data)

    def test_service_imports_and_maps_ess_controls_to_dcdc(self):
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
                    "dev_type": "DCDCConverter",
                    "dev_name": "ess01_dcdc",
                    "set_type": "p_set",
                    "set_value": 12.5,
                }
            ],
        )

    def test_simple_model_contains_one_core_device_of_each_kind(self):
        model = self._book("model.e")
        device = self._book("device.e")

        self.assertEqual([row["name"] for row in self._rows(device, "wind_generator")], ["wt01_rect"])
        self.assertEqual([row["name"] for row in self._rows(device, "pv_generator")], ["pv01_dcdc"])
        self.assertEqual([row["name"] for row in self._rows(device, "estorage")], ["ess01"])
        self.assertEqual([row["name"] for row in self._rows(device, "diesel_generator")], ["diesel_300kw"])
        self.assertEqual([row["name"] for row in self._rows(device, "load_curve_96")], ["load_ac_1"])
        self.assertEqual([row["name"] for row in self._rows(device, "load_temperature")], ["load_ac_1"])

        ac_generators = [row["name"] for row in self._rows(model, "ACGenerator")]
        self.assertEqual([name for name in ac_generators if name.startswith("wt")], ["wt01_10kw"])
        self.assertEqual([name for name in ac_generators if "diesel" in name], ["diesel_300kw"])
        self.assertEqual([row["name"] for row in self._rows(model, "ACLoad")], ["load_ac_1"])
        self.assertEqual([row["name"] for row in self._rows(model, "DCDCConverter") if row["name"].startswith("pv")], ["pv01_dcdc"])
        self.assertEqual([row["name"] for row in self._rows(model, "DCDCConverter") if row["name"].startswith("ess")], ["ess01_dcdc"])
        self.assertEqual([row["name"] for row in self._rows(model, "DCACConverter") if row["name"].startswith("wt")], ["wt01_rect"])

    def test_storage_has_pqvi_soc_measurements_and_control_points(self):
        meas = self._book("meas.e")
        stat = self._book("stat.e")

        ess_meas_types = {
            str(row["meas_type"]).upper()
            for row in self._rows(meas, "Measurement")
            if row["dev_type"] == "ESS" and row["dev_name"] == "ess01"
        }
        self.assertEqual(ess_meas_types, {"P", "Q", "V", "I", "SOC"})

        soc_rows = self._rows(stat, "StorageSoc")
        self.assertEqual([(row["dev_type"], row["name"]) for row in soc_rows], [("ESS", "ess01")])

        dcdc_set_values = {
            row["set_type"]: row["set_value"]
            for row in self._rows(stat, "SetValue")
            if row["dev_type"] == "DCDCConverter" and row["dev_name"] == "ess01_dcdc"
        }
        self.assertIn("p_set", dcdc_set_values)
        self.assertIn("v_set", dcdc_set_values)


if __name__ == "__main__":
    unittest.main()
