from __future__ import annotations

import unittest

import simu_loop


class _NonzeroSnapshot:
    fluid_results = {}
    coupling_results = ()
    ac_devices = {}
    dc_devices = {}

    @staticmethod
    def value(_dev_type, _dev_name, _meas_type):
        return 99.0


class StoppedDeviceMeasurementTest(unittest.TestCase):
    def test_stopped_devices_refresh_without_retaining_previous_values(self):
        model_book = simu_loop.EBook(
            {
                "ACGenerator": [
                    {"idx": 1, "name": "stopped-generator", "run_stat": 0},
                ],
                "DCBranch": [
                    {"idx": 1, "name": "stopped-branch", "run_stat": 0},
                ],
                "AcE2Hydro": [
                    {
                        "idx": 1,
                        "name": "stopped-electrolyzer",
                        "run_stat": 0,
                        "idx_h2_unit_t2": 1,
                    }
                ],
                "HydroSource": [
                    {"idx": 1, "name": "electrolyzer-hydrogen-end", "run_stat": 1},
                ],
                "HydroStorage": [
                    {"idx": 1, "name": "stopped-hydrogen-tank", "run_stat": 0},
                ],
            }
        )
        definitions = (
            ("ACGenerator", "stopped-generator", "P_GEN"),
            ("ACGenerator", "stopped-generator", "V_GEN"),
            ("DCBranch", "stopped-branch", "I"),
            ("AcE2Hydro", "stopped-electrolyzer", "P"),
            ("AcE2Hydro", "stopped-electrolyzer", "FLOW"),
            ("HydroSource", "electrolyzer-hydrogen-end", "FLOW"),
            ("HydroSource", "electrolyzer-hydrogen-end", "PRESSURE"),
            ("HydroStorage", "stopped-hydrogen-tank", "SOC"),
            ("HydroStorage", "stopped-hydrogen-tank", "PRESSURE"),
            ("ACGenerator", "stopped-generator", "RUN_STAT"),
        )
        rows = [
            [str(idx), f"{dev_type}.{dev_name}.{meas_type}", dev_type, dev_name, meas_type, "1", "1", "88"]
            for idx, (dev_type, dev_name, meas_type) in enumerate(definitions, start=1)
        ]
        bindings = tuple(
            simu_loop.MeasurementBinding(dev_type, dev_name, True)
            for dev_type, dev_name, _meas_type in definitions
        )

        _before, refreshed, _after, updated, missing = simu_loop.build_real_rows_from_data(
            rows,
            _NonzeroSnapshot(),
            signal_values={
                ("ACGenerator", "stopped-generator", "RUN_STAT"): 0.0,
            },
            model_book=model_book,
            measurement_bindings=bindings,
            hydrogen_storage_state={
                ("HydroStorage", "stopped-hydrogen-tank"): {
                    "soc": 0.62,
                    "pressure": 4.2,
                }
            },
        )

        self.assertEqual((updated, missing), (len(rows), 0))
        self.assertEqual([float(row[7]) for row in refreshed[:7]], [0.0] * 7)
        self.assertEqual(float(refreshed[7][7]), 0.62)
        self.assertEqual(float(refreshed[8][7]), 4.2)
        self.assertEqual(float(refreshed[9][7]), 0.0)

    def test_binding_uses_concrete_target_state_without_name_inference(self):
        model_book = simu_loop.EBook(
            {
                "ACGenerator": [
                    {"idx": 1, "name": "concrete-generator", "run_stat": 0},
                ],
                "ACWindGen": [
                    {"idx": 1, "name": "parameter-alias", "run_stat": 1},
                ],
            }
        )
        source_row = [
            "1",
            "wind-parameter.power",
            "ACWindGen",
            "parameter-alias",
            "P_GEN",
            "1",
            "1",
            "88",
        ]

        _before, refreshed, _after, updated, missing = simu_loop.build_real_rows_from_data(
            [source_row],
            _NonzeroSnapshot(),
            model_book=model_book,
            measurement_bindings=(
                simu_loop.MeasurementBinding(
                    "ACGenerator",
                    "concrete-generator",
                    True,
                ),
            ),
        )

        self.assertEqual((updated, missing), (1, 0))
        self.assertEqual(float(refreshed[0][7]), 0.0)


if __name__ == "__main__":
    unittest.main()
