from __future__ import annotations

import unittest

import simu_loop


class BranchCurrentMeasurementsTest(unittest.TestCase):
    def test_generic_branch_current_measurements_use_from_terminal_current(self):
        class FakeSnapshot:
            ac_devices = {"ACBreak": {"ac_break": object()}}
            dc_devices = {"DCBreak": {"dc_break": object()}}

            values = {
                ("ACBranch", "ac_line", "I_FROM"): 12.34,
                ("ACBreak", "ac_break", "I_FROM"): 5.67,
                ("DCBranch", "dc_line", "I_FROM"): 8.9,
                ("DCBreak", "dc_break", "I_FROM"): 1.23,
            }

            def value(self, dev_type, dev_name, meas_type):
                return self.values.get((dev_type, dev_name, meas_type))

            def _ac_zero_value(self, _dev, _meas_type):
                return None

            def _dc_zero_value(self, _dev, _meas_type):
                return None

        measurement_rows = [
            ["1", "ACBranch.ac_line.I", "ACBranch", "ac_line", "I", "1", "1", "0"],
            ["2", "ACBreak.ac_break.I", "ACBreak", "ac_break", "I", "1", "1", "0"],
            ["3", "DCBranch.dc_line.I", "DCBranch", "dc_line", "I", "1", "1", "0"],
            ["4", "DCBreak.dc_break.I", "DCBreak", "dc_break", "I", "1", "1", "0"],
        ]

        _before, rows, _after, updated, missing = simu_loop.build_real_rows_from_data(
            measurement_rows,
            FakeSnapshot(),
        )

        self.assertEqual(updated, 4)
        self.assertEqual(missing, 0)
        self.assertEqual([float(row[7]) for row in rows], [12.34, 5.67, 8.9, 1.23])


if __name__ == "__main__":
    unittest.main()
