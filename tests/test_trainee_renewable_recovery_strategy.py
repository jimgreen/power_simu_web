import unittest

from simu.renewable_control import RenewableControlSettings, _apply_storage_switch_deadband, _plan_recovery


def run_strategy(rows, system_room_kw, **options):
    settings = RenewableControlSettings(
        large_step_threshold_kw=options.get("largeStepThresholdKw", 10),
        step_coefficient=options.get("stepCoefficient", 0.03),
    )
    normalized = [
        {
            **row,
            "planningCurrentKw": row.get("planningCurrentKw", row.get("currentKw")),
        }
        for row in rows
    ]
    return _plan_recovery(normalized, system_room_kw, settings)


class TraineeRenewableRecoveryStrategyTest(unittest.TestCase):
    def test_storage_switch_deadband_blocks_small_charge_discharge_reversals(self):
        self.assertEqual(_apply_storage_switch_deadband(3.0, -2.0, 5.0), (0.0, "discharge_to_charge_blocked"))
        self.assertEqual(_apply_storage_switch_deadband(-3.0, 2.0, 5.0), (0.0, "charge_to_discharge_blocked"))
        self.assertEqual(_apply_storage_switch_deadband(0.0, 4.0, 5.0), (0.0, "idle_deadband"))
        self.assertEqual(_apply_storage_switch_deadband(0.0, -4.0, 5.0), (0.0, "idle_deadband"))

    def test_storage_switch_deadband_allows_material_or_same_direction_adjustments(self):
        self.assertEqual(_apply_storage_switch_deadband(3.0, -6.0, 5.0), (-6.0, "direction_switch_allowed"))
        self.assertEqual(_apply_storage_switch_deadband(-3.0, 6.0, 5.0), (6.0, "direction_switch_allowed"))
        self.assertEqual(_apply_storage_switch_deadband(3.0, 2.0, 5.0), (2.0, "same_direction"))
        self.assertEqual(_apply_storage_switch_deadband(-3.0, -2.0, 5.0), (-2.0, "same_direction"))

    def test_large_recovery_uses_equal_margin_distribution(self):
        result = run_strategy(
            [
                {"capacityKw": 50, "currentKw": 20},
                {"capacityKw": 100, "currentKw": 40},
                {"capacityKw": 20, "currentKw": 18},
            ],
            30,
            largeStepThresholdKw=10,
            stepCoefficient=0.03,
        )

        self.assertEqual(result["mode"], "equal-margin")
        self.assertAlmostEqual(result["recoverableKw"], 30.0)
        self.assertEqual([round(row["recoveryKw"], 6) for row in result["rows"]], [14.0, 14.0, 2.0])
        self.assertEqual([round(row["setpointKw"], 6) for row in result["rows"]], [34.0, 54.0, 20.0])

    def test_small_recovery_uses_capacity_step_without_consuming_all_room(self):
        result = run_strategy(
            [
                {"capacityKw": 100, "currentKw": 60},
                {"capacityKw": 50, "currentKw": 20},
            ],
            8,
            largeStepThresholdKw=10,
            stepCoefficient=0.03,
        )

        self.assertEqual(result["mode"], "capacity-step")
        self.assertAlmostEqual(result["recoverableKw"], 4.5)
        self.assertEqual([round(row["recoveryKw"], 6) for row in result["rows"]], [3.0, 1.5])
        self.assertEqual([round(row["setpointKw"], 6) for row in result["rows"]], [63.0, 21.5])

    def test_small_steps_are_scaled_down_to_the_system_recovery_room(self):
        result = run_strategy(
            [
                {"capacityKw": 100, "currentKw": 60},
                {"capacityKw": 50, "currentKw": 20},
            ],
            2,
            largeStepThresholdKw=10,
            stepCoefficient=0.03,
        )

        self.assertEqual(result["mode"], "capacity-step")
        self.assertAlmostEqual(result["recoverableKw"], 2.0)
        self.assertAlmostEqual(sum(row["recoveryKw"] for row in result["rows"]), 2.0)
        self.assertAlmostEqual(result["rows"][0]["recoveryKw"], 4.0 / 3.0)
        self.assertAlmostEqual(result["rows"][1]["recoveryKw"], 2.0 / 3.0)

    def test_measurement_noise_above_capacity_never_produces_an_over_capacity_setpoint(self):
        result = run_strategy(
            [{"capacityKw": 10, "currentKw": 10.1, "dev_name": "WT-01"}],
            20,
            largeStepThresholdKw=10,
            stepCoefficient=0.03,
        )

        self.assertAlmostEqual(result["rows"][0]["planningCurrentKw"], 10.0)
        self.assertAlmostEqual(result["rows"][0]["headroomKw"], 0.0)
        self.assertAlmostEqual(result["rows"][0]["recoveryKw"], 0.0)
        self.assertAlmostEqual(result["rows"][0]["setpointKw"], 10.0)


if __name__ == "__main__":
    unittest.main()
