from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


RESOURCE_PARAMETER_BLOCKS = {
    "ACWindGen",
    "DCWindGen",
    "ACPVGen",
    "DCPVGen",
    "ACStorageGen",
    "DCStorageGen",
}


def resource_model_text(
    *,
    ac_storage_name: str = "ac-storage",
    dc_storage_name: str = "dc-storage",
) -> str:
    return f"""<ACGenerator>
@ idx  name  node  control_type  p_set  q_set  v_set  run_stat
# 1  {ac_storage_name}  1  P  0  0  380  1
# 2  ac-wind  2  P  0  0  380  1
# 3  ac-pv  3  P  0  0  380  1
</ACGenerator>
<DCGenerator>
@ idx  name  node  control_type  p_set  v_set  i_set  run_stat
# 1  {dc_storage_name}  1  P  0  720  0  1
# 2  dc-wind  2  P  0  720  0  1
# 3  dc-pv  3  P  0  720  0  1
</DCGenerator>
<ACWindGen>
@ idx  idx_acgenerator  rated_power
# 1  2  10
</ACWindGen>
<DCWindGen>
@ idx  idx_dcgenerator  rated_power
# 1  2  11
</DCWindGen>
<ACPVGen>
@ idx  idx_acgenerator  rated_power
# 1  3  12
</ACPVGen>
<DCPVGen>
@ idx  idx_dcgenerator  rated_power
# 1  3  13
</DCPVGen>
<ACStorageGen>
@ idx  idx_acgenerator  energy_capacity  state_of_charge
# 1  1  100  0.5
</ACStorageGen>
<DCStorageGen>
@ idx  idx_dcgenerator  energy_capacity  state_of_charge
# 1  1  120  0.5
</DCStorageGen>
"""


def storage_stat_text(
    *,
    ac_storage_name: str,
    dc_storage_name: str,
    ac_soc: float,
    dc_soc: float,
) -> str:
    return f"""<RunStat>
@ dev_type  dev_name  run_stat
# ACGenerator  {ac_storage_name}  1
# DCGenerator  {dc_storage_name}  1
</RunStat>
<SetValue>
@ dev_type  dev_name  set_type  set_value
# ACGenerator  {ac_storage_name}  p_set  0
# DCGenerator  {dc_storage_name}  p_set  0
</SetValue>
<StorageSoc>
@ dev_type  idx  name  soc_curr
# ACGenerator  1  {ac_storage_name}  {ac_soc}
# DCGenerator  1  {dc_storage_name}  {dc_soc}
</StorageSoc>
"""


class ResourceParameterSnapshotTest(unittest.TestCase):
    @staticmethod
    def _service_from_text(root: Path, model_text: str, stat_text: str) -> PolarMicrogridSimulator:
        source_dir = root / "source"
        shutil.copytree(SIMPLE_MODEL_SOURCE, source_dir)
        (source_dir / "model.e").write_text(model_text, encoding="utf-8")
        (source_dir / "stat.e").write_text(stat_text, encoding="utf-8")
        return PolarMicrogridSimulator(
            source_dir,
            root / "runtime",
            model_id="resource-parameters",
            kernel=lambda _config: None,
        )

    @staticmethod
    def _replace_storage_soc_rows(service: PolarMicrogridSimulator, rows: list[dict]) -> None:
        service.runtime_stat_book.data["StorageSoc"].data = rows

    @staticmethod
    def _soc_measurement_row(dev_type: str, dev_name: str, value: float) -> list[str]:
        return [
            "1",
            f"{dev_type}.{dev_name}.SOC",
            dev_type,
            dev_name,
            "SOC",
            "1",
            "1",
            str(value),
        ]

    def _service(
        self,
        root: Path,
        *,
        ac_storage_name: str = "ac-storage",
        dc_storage_name: str = "dc-storage",
        ac_soc: float = 0.61,
        dc_soc: float = 0.72,
    ) -> PolarMicrogridSimulator:
        return self._service_from_text(
            root,
            resource_model_text(
                ac_storage_name=ac_storage_name,
                dc_storage_name=dc_storage_name,
            ),
            storage_stat_text(
                ac_storage_name=ac_storage_name,
                dc_storage_name=dc_storage_name,
                ac_soc=ac_soc,
                dc_soc=dc_soc,
            ),
        )

    def test_device_parameters_exposes_all_ac_dc_resource_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            self.assertEqual(set(service.device_parameters()), RESOURCE_PARAMETER_BLOCKS)

    def test_devices_attach_live_soc_to_ac_and_dc_storage_generators(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary), ac_soc=0.61, dc_soc=0.72)

            devices = {
                (device["dev_type"], device["dev_name"]): device
                for device in service.devices()
            }
            self.assertIn("soc_curr", devices[("ACGenerator", "ac-storage")])
            self.assertIn("soc_curr", devices[("DCGenerator", "dc-storage")])
            self.assertEqual(devices[("ACGenerator", "ac-storage")]["soc_curr"], 0.61)
            self.assertEqual(devices[("DCGenerator", "dc-storage")]["soc_curr"], 0.72)

    def test_storage_parameters_do_not_overwrite_generator_identity_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service_from_text(
                Path(temporary),
                """<ACGenerator>
@ idx  name  node  control_type  p_set  q_set  v_set  run_stat
# 23  ac-storage  1  P  0  0  380  1
</ACGenerator>
<DCGenerator>
@ idx  name  node  control_type  p_set  v_set  i_set  run_stat
# 9  dc-storage  1  P  0  720  0  1
</DCGenerator>
<ACStorageGen>
@ idx  idx_acgenerator  energy_capacity  state_of_charge
# 1  23  100  0.5
</ACStorageGen>
<DCStorageGen>
@ idx  idx_dcgenerator  energy_capacity  state_of_charge
# 1  9  120  0.5
</DCStorageGen>
""",
                storage_stat_text(
                    ac_storage_name="ac-storage",
                    dc_storage_name="dc-storage",
                    ac_soc=0.61,
                    dc_soc=0.72,
                ),
            )

            devices = {
                (device["dev_type"], device["dev_name"]): device
                for device in service.devices()
            }
            ac_storage = devices[("ACGenerator", "ac-storage")]
            dc_storage = devices[("DCGenerator", "dc-storage")]

            self.assertEqual(str(ac_storage["raw"]["idx"]), "23")
            self.assertEqual(str(dc_storage["raw"]["idx"]), "9")
            self.assertEqual(str(ac_storage["raw"]["idx_acgenerator"]), "23")
            self.assertEqual(str(dc_storage["raw"]["idx_dcgenerator"]), "9")
            self.assertEqual(str(ac_storage["raw"]["energy_capacity"]), "100")
            self.assertEqual(str(dc_storage["raw"]["energy_capacity"]), "120")

    def test_same_name_ac_dc_storage_soc_is_isolated_by_device_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(
                Path(temporary),
                ac_storage_name="shared-storage",
                dc_storage_name="shared-storage",
                ac_soc=0.21,
                dc_soc=0.79,
            )

            devices = {
                (device["dev_type"], device["dev_name"]): device
                for device in service.devices()
            }
            self.assertIn("soc_curr", devices[("ACGenerator", "shared-storage")])
            self.assertIn("soc_curr", devices[("DCGenerator", "shared-storage")])
            self.assertEqual(devices[("ACGenerator", "shared-storage")]["soc_curr"], 0.21)
            self.assertEqual(devices[("DCGenerator", "shared-storage")]["soc_curr"], 0.79)

            ac_measurement = self._soc_measurement_row("ACGenerator", "shared-storage", 0.0)
            dc_measurement = self._soc_measurement_row("DCGenerator", "shared-storage", 0.0)
            service.latest_real_rows = [ac_measurement, dc_measurement]
            service.latest_scada_rows = []
            service.latest_measurements = {}
            service._sync_latest_storage_soc_measurement_rows()

            self.assertEqual(float(ac_measurement[7]), 0.21)
            self.assertEqual(float(dc_measurement[7]), 0.79)

    def test_blank_legacy_soc_resolves_to_unique_ac_structured_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service_from_text(
                Path(temporary),
                """<ACGenerator>
@ idx  name  node  control_type  p_set  q_set  v_set  run_stat
# 1  ac-storage  1  P  0  0  380  1
</ACGenerator>
<ACStorageGen>
@ idx  idx_acgenerator  energy_capacity  state_of_charge
# 1  1  100  0.5
</ACStorageGen>
""",
                """<StorageSoc>
@ dev_type  idx  name  soc_curr
# Legacy  1  ac-storage  0.66
</StorageSoc>
""",
            )
            self._replace_storage_soc_rows(
                service,
                [{"dev_type": "", "idx": "1", "name": "ac-storage", "soc_curr": "0.66"}],
            )

            devices = {
                (device["dev_type"], device["dev_name"]): device
                for device in service.devices()
            }
            self.assertEqual(devices[("ACGenerator", "ac-storage")]["soc_curr"], 0.66)

            measurement = self._soc_measurement_row("ACGenerator", "ac-storage", 0.1)
            service.latest_real_rows = [measurement]
            service.latest_scada_rows = []
            service.latest_measurements = {}
            service._sync_latest_storage_soc_measurement_rows()
            self.assertEqual(float(measurement[7]), 0.66)

    def test_blank_legacy_soc_does_not_resolve_ambiguous_same_name_ac_dc_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(
                Path(temporary),
                ac_storage_name="shared-storage",
                dc_storage_name="shared-storage",
                ac_soc=0.21,
                dc_soc=0.79,
            )
            self._replace_storage_soc_rows(
                service,
                [{"dev_type": "", "idx": "1", "name": "shared-storage", "soc_curr": "0.44"}],
            )

            devices = {
                (device["dev_type"], device["dev_name"]): device
                for device in service.devices()
            }
            self.assertEqual(devices[("ACGenerator", "shared-storage")]["soc_curr"], 0.5)
            self.assertEqual(devices[("DCGenerator", "shared-storage")]["soc_curr"], 0.5)

            ac_measurement = self._soc_measurement_row("ACGenerator", "shared-storage", 0.11)
            dc_measurement = self._soc_measurement_row("DCGenerator", "shared-storage", 0.22)
            service.latest_real_rows = [ac_measurement, dc_measurement]
            service.latest_scada_rows = []
            service.latest_measurements = {}
            service._sync_latest_storage_soc_measurement_rows()
            self.assertEqual(float(ac_measurement[7]), 0.11)
            self.assertEqual(float(dc_measurement[7]), 0.22)

    def test_duplicate_structured_storage_rows_use_first_parameter_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service_from_text(
                Path(temporary),
                """<ACGenerator>
@ idx  name  node  control_type  p_set  q_set  v_set  run_stat
# 1  ac-storage  1  P  0  0  380  1
</ACGenerator>
<ACStorageGen>
@ idx  idx_acgenerator  energy_capacity  state_of_charge
# 1  1  100  0.25
# 2  1  999  0.75
</ACStorageGen>
""",
                """<StorageSoc>
@ dev_type  idx  name  soc_curr
</StorageSoc>
""",
            )

            device = next(
                item
                for item in service.devices()
                if item["dev_type"] == "ACGenerator" and item["dev_name"] == "ac-storage"
            )
            self.assertEqual(device["soc_curr"], 0.25)
            self.assertEqual(str(device["raw"]["energy_capacity"]), "100")


if __name__ == "__main__":
    unittest.main()
