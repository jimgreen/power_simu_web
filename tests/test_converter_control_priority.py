from __future__ import annotations

import unittest

import simu_loop


class ConverterControlPriorityTest(unittest.TestCase):
    @staticmethod
    def _model_book():
        return simu_loop.EBook(
            {
                "DCACConverter": [
                    {
                        "idx": 1,
                        "name": "grid-link",
                        "dev_type": "grid-dcac-converter",
                        "ac_control_type": "PQ",
                        "dc_control_type": "P",
                        "p_ac_set": -10.0,
                        "p_dc_set": 10.0,
                        "q_ac_set": 0.0,
                        "v_ac_set": 380.0,
                        "run_stat": 1,
                    }
                ]
            }
        )

    def test_legacy_converter_p_set_writes_the_dc_terminal(self):
        model_book = self._model_book()
        target = model_book.data["DCACConverter"].data[0]

        changed = simu_loop._apply_setpoint_row(
            model_book,
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-link",
                "p_set": 25.0,
            },
        )

        self.assertEqual(changed, 1)
        self.assertEqual(float(target["p_dc_set"]), 25.0)
        self.assertEqual(float(target["p_ac_set"]), -10.0)

    def test_generic_set_value_writes_dc_but_explicit_terminal_is_preserved(self):
        model_book = self._model_book()
        target = model_book.data["DCACConverter"].data[0]

        simu_loop._apply_set_value_row(
            model_book,
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-link",
                "set_type": "p_set",
                "set_value": 30.0,
            },
        )
        self.assertEqual(float(target["p_dc_set"]), 30.0)
        self.assertEqual(float(target["p_ac_set"]), -10.0)

        simu_loop._apply_set_value_row(
            model_book,
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-link",
                "set_type": "p_ac_set",
                "set_value": -35.0,
            },
        )
        self.assertEqual(float(target["p_dc_set"]), 30.0)
        self.assertEqual(float(target["p_ac_set"]), -35.0)

    def test_double_none_control_falls_back_to_the_dc_terminal(self):
        model_book = self._model_book()
        target = model_book.data["DCACConverter"].data[0]
        target["ac_control_type"] = "NONE"
        target["dc_control_type"] = "NONE"

        simu_loop._apply_set_value_row(
            model_book,
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-link",
                "set_type": "p_set",
                "set_value": -22.0,
            },
        )

        self.assertEqual(float(target["p_ac_set"]), -10.0)
        self.assertEqual(float(target["p_dc_set"]), -22.0)

    def test_dc_terminal_commands_are_active_power_control_targets(self):
        control_book = simu_loop.EBook(
            {
                "SetValue": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "grid-link",
                        "set_type": "p_dc_set",
                        "set_value": 10.0,
                    }
                ],
                "ConverterSetpoint": [
                    {
                        "dev_type": "DCACConverter",
                        "dev_name": "legacy-link",
                        "p_dc_set": 20.0,
                    }
                ],
            }
        )

        targets = simu_loop._active_power_control_targets_book(control_book)

        self.assertIn(("DCACConverter", "grid-link"), targets)
        self.assertIn(("DCACConverter", "legacy-link"), targets)

    def test_explicit_dc_terminal_command_preserves_declared_control_modes(self):
        model_book = self._model_book()
        target = model_book.data["DCACConverter"].data[0]
        target["ac_control_type"] = "PH"
        target["dc_control_type"] = "NONE"

        changed = simu_loop._apply_set_value_row(
            model_book,
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-link",
                "set_type": "p_dc_set",
                "set_value": 18.0,
            },
        )

        self.assertEqual(changed, 1)
        self.assertEqual(float(target["p_dc_set"]), 18.0)
        self.assertEqual(float(target["p_ac_set"]), -10.0)
        self.assertEqual(target["ac_control_type"], "PH")
        self.assertEqual(target["dc_control_type"], "NONE")


if __name__ == "__main__":
    unittest.main()
