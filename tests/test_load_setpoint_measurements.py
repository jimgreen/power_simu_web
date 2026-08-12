import random
import tempfile
import unittest
from pathlib import Path


class LoadSetpointMeasurementsTest(unittest.TestCase):
    @staticmethod
    def _load_row(model_book, block_name, name):
        return next(
            row
            for row in model_book.data[block_name].data
            if row.get("name") == name
        )

    @staticmethod
    def _control_book(*rows):
        import simu_loop

        return simu_loop.EBook(
            {
                "SetValue": [
                    {
                        "dev_type": row[0],
                        "dev_name": row[1],
                        "set_type": row[2],
                        "set_value": row[3],
                    }
                    for row in rows
                ]
            }
        )

    def test_load_setpoints_update_zip_boundaries_in_physical_units(self):
        import simu_loop

        model_book = simu_loop.EBook(
            {
                "ACLoad": [
                    {
                        "idx": 1,
                        "name": "ac-load",
                        "node": 1,
                        "pbase": 150,
                        "pv0": 1,
                        "pv1": 0,
                        "pv2": 0,
                        "qbase": 50,
                        "qv0": 1,
                        "qv1": 0,
                        "qv2": 0,
                        "run_stat": 1,
                    }
                ],
                "DCLoad": [
                    {
                        "idx": 1,
                        "name": "dc-load",
                        "node": 1,
                        "pbase": 80,
                        "pv0": 1,
                        "pv1": 0,
                        "pv2": 0,
                        "run_stat": 1,
                    }
                ],
            }
        )
        controls = self._control_book(
            ("ACLoad", "ac-load", "p_set", 30),
            ("ACLoad", "ac-load", "q_set", 10),
            ("DCLoad", "dc-load", "p_set", 20),
        )

        simu_loop.apply_yt_ctrl_book(model_book, controls)

        ac_load = self._load_row(model_book, "ACLoad", "ac-load")
        dc_load = self._load_row(model_book, "DCLoad", "dc-load")
        self.assertAlmostEqual(float(ac_load["pbase"]) * float(ac_load["pv0"]), 30.0)
        self.assertAlmostEqual(float(ac_load["qbase"]) * float(ac_load["qv0"]), 10.0)
        self.assertAlmostEqual(float(dc_load["pbase"]) * float(dc_load["pv0"]), 20.0)

    def test_explicit_load_targets_are_retained_and_drive_the_zip_boundary(self):
        import simu_loop

        model_book = simu_loop.EBook(
            {
                "ACLoad": [
                    {
                        "idx": 1,
                        "name": "ac-load",
                        "node": 1,
                        "p_set": 150,
                        "q_set": 50,
                        "pbase": 150,
                        "pv0": 1,
                        "pv1": 0,
                        "pv2": 0,
                        "qbase": 50,
                        "qv0": 1,
                        "qv1": 0,
                        "qv2": 0,
                        "run_stat": 1,
                    }
                ],
            }
        )

        simu_loop.apply_yt_ctrl_book(
            model_book,
            self._control_book(
                ("ACLoad", "ac-load", "p_set", 45),
                ("ACLoad", "ac-load", "q_set", 15),
            ),
        )

        load = self._load_row(model_book, "ACLoad", "ac-load")
        self.assertAlmostEqual(float(load["p_set"]), 45.0)
        self.assertAlmostEqual(float(load["q_set"]), 15.0)
        self.assertAlmostEqual(float(load["p_set"]) * float(load["pv0"]), 45.0)
        self.assertAlmostEqual(float(load["qbase"]) * float(load["qv0"]), 15.0)

    def test_live_curve_is_applied_before_remote_load_target(self):
        import simu_loop

        model_book = simu_loop.EBook(
            {
                "ACLoad": [
                    {
                        "idx": 1,
                        "name": "ac-load",
                        "node": 1,
                        "pbase": 150,
                        "pv0": 1,
                        "pv1": 0,
                        "pv2": 0,
                        "qbase": 50,
                        "qv0": 1,
                        "qv1": 0,
                        "qv2": 0,
                        "run_stat": 1,
                    }
                ],
                "DCLoad": [
                    {
                        "idx": 1,
                        "name": "dc-load",
                        "node": 1,
                        "pbase": 80,
                        "pv0": 0.25,
                        "pv1": 0,
                        "pv2": 0,
                        "run_stat": 1,
                    }
                ],
            }
        )
        weather_book = simu_loop.EBook(
            {
                "LoadPower": [
                    {
                        "dev_type": "ACLoad",
                        "dev_name": "ac-load",
                        "p_kw": 120,
                    }
                ]
            }
        )

        _changed, effective_model, _dev_define, _weather = simu_loop.apply_realtime_input_books(
            model_book,
            weather_book,
            simu_loop.EBook({}),
            self._control_book(("ACLoad", "ac-load", "p_set", 30)),
            simu_loop.EBook({}),
        )

        load = self._load_row(effective_model, "ACLoad", "ac-load")
        self.assertAlmostEqual(float(load["pbase"]) * float(load["pv0"]), 30.0)

    def test_legacy_generator_setpoint_rows_use_the_same_physical_load_units(self):
        import simu_loop

        model_book = simu_loop.EBook(
            {
                "ACLoad": [
                    {
                        "idx": 1,
                        "name": "ac-load",
                        "node": 1,
                        "pbase": 150,
                        "pv0": 1,
                        "pv1": 0,
                        "pv2": 0,
                        "qbase": 50,
                        "qv0": 1,
                        "qv1": 0,
                        "qv2": 0,
                        "run_stat": 1,
                    }
                ]
            }
        )
        controls = simu_loop.EBook(
            {
                "GeneratorSetpoint": [
                    {
                        "dev_type": "ACLoad",
                        "dev_name": "ac-load",
                        "p_set": 30,
                        "q_set": 10,
                    }
                ]
            }
        )

        simu_loop.apply_yt_ctrl_book(model_book, controls)

        load = self._load_row(model_book, "ACLoad", "ac-load")
        self.assertAlmostEqual(float(load["pbase"]) * float(load["pv0"]), 30.0)
        self.assertAlmostEqual(float(load["qbase"]) * float(load["qv0"]), 10.0)

    def test_generated_load_controls_and_measurements_use_physical_power(self):
        import simu_loop
        from simu import server

        model_book = simu_loop.EBook(
            {
                "ACLoad": [
                    {
                        "idx": 1,
                        "name": "ac-load",
                        "node": 1,
                        "pbase": 150,
                        "pv0": 0.2,
                        "pv1": 0,
                        "pv2": 0,
                        "qbase": 50,
                        "qv0": 0.2,
                        "qv1": 0,
                        "qv2": 0,
                        "run_stat": 1,
                    }
                ],
                "DCLoad": [
                    {
                        "idx": 1,
                        "name": "dc-load",
                        "node": 1,
                        "pbase": 80,
                        "pv0": 0.25,
                        "pv1": 0,
                        "pv2": 0,
                        "run_stat": 1,
                    }
                ],
            }
        )

        blocks = server._generated_control_blocks(model_book)
        set_rows = list(blocks["SetValue"][1])
        controls = {
            (row["dev_type"], row["dev_name"], row["set_type"]): float(row["set_value"])
            for row in set_rows
        }
        measurement_book = server._generated_measurement_book(model_book, blocks)
        measurement_types = {
            (row["dev_type"], row["dev_name"], row["meas_type"])
            for row in measurement_book.data["Measurement"].data
        }

        self.assertAlmostEqual(controls[("ACLoad", "ac-load", "p_set")], 30.0)
        self.assertAlmostEqual(controls[("ACLoad", "ac-load", "q_set")], 10.0)
        self.assertAlmostEqual(controls[("DCLoad", "dc-load", "p_set")], 20.0)
        self.assertIn(("ACLoad", "ac-load", "P_LOAD"), measurement_types)
        self.assertIn(("ACLoad", "ac-load", "Q_LOAD"), measurement_types)
        self.assertIn(("DCLoad", "dc-load", "P_LOAD"), measurement_types)
        self.assertNotIn(("DCLoad", "dc-load", "Q_LOAD"), measurement_types)

    def test_load_real_measurements_come_from_solved_power_and_scada_adds_error(self):
        import simu_loop
        from simu.generate_simple_model import model_blocks

        model_book = simu_loop.EBook(
            {
                block_name: rows
                for block_name, _headers, rows in model_blocks()
            }
        )
        load = self._load_row(model_book, "ACLoad", "load_ac_1")
        load.update(
            {
                "pbase": 150,
                "pv0": 1,
                "qbase": 50,
                "qv0": 1,
            }
        )
        model_book.data["DCLoad"] = simu_loop.EBook(
            {
                "DCLoad": [
                    {
                        "idx": 1,
                        "name": "dc-load",
                        "node": 1,
                        "pbase": 80,
                        "pv0": 1,
                        "pv1": 0,
                        "pv2": 0,
                        "run_stat": 1,
                    }
                ]
            }
        ).data["DCLoad"]
        simu_loop.apply_yt_ctrl_book(
            model_book,
            self._control_book(
                ("ACLoad", "load_ac_1", "p_set", 45),
                ("ACLoad", "load_ac_1", "q_set", 15),
                ("DCLoad", "dc-load", "p_set", 20),
            ),
        )

        source = Path(__file__).resolve().parent / "fixtures" / "simple_model" / "model.e"
        snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(model_book, source)
        measurement_rows = [
            ["1", "ACLoad.load_ac_1.P_LOAD", "ACLoad", "load_ac_1", "P_LOAD", "10000", "1", "0"],
            ["2", "ACLoad.load_ac_1.Q_LOAD", "ACLoad", "load_ac_1", "Q_LOAD", "10000", "1", "0"],
            ["3", "DCLoad.dc-load.P_LOAD", "DCLoad", "dc-load", "P_LOAD", "10000", "1", "0"],
        ]
        _before, real_rows, _after, updated, missing = simu_loop.build_real_rows_from_data(
            measurement_rows,
            snapshot,
            model_book=model_book,
        )
        scada_rows = simu_loop.add_noise_to_rows(
            real_rows,
            0.0,
            random.Random(1),
            {"ACLoad.load_ac_1.P_LOAD": 1.5},
        )

        self.assertEqual((updated, missing), (3, 0))
        self.assertAlmostEqual(float(real_rows[0][7]), 45.0, places=6)
        self.assertAlmostEqual(float(real_rows[1][7]), 15.0, places=6)
        self.assertAlmostEqual(float(real_rows[2][7]), 20.0, places=6)
        self.assertAlmostEqual(float(scada_rows[0][7]), 46.5, places=6)
        self.assertAlmostEqual(float(scada_rows[1][7]), 15.0, places=6)
        self.assertAlmostEqual(float(scada_rows[2][7]), 20.0, places=6)

    def test_service_load_command_reaches_power_flow_and_realtime_measurements(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            write_model_dir(source)
            service = PolarMicrogridSimulator(
                source,
                runtime,
                noise_std=0.0,
                random_seed=1,
            )
            service.set_system_parameters({"remote_adjustment_response_ratio": 1.0})

            accepted = service.apply_student_commands(
                {
                    "set_values": [
                        {
                            "dev_type": "ACLoad",
                            "dev_name": "load_ac_1",
                            "set_type": "p_set",
                            "set_value": 45,
                        },
                        {
                            "dev_type": "ACLoad",
                            "dev_name": "load_ac_1",
                            "set_type": "q_set",
                            "set_value": 15,
                        },
                    ]
                },
                source="trainee-ui",
            )
            service.step(advance_seconds=1.0)

            load = self._load_row(service.latest_model_book, "ACLoad", "load_ac_1")

            def measured_value(rows, meas_type):
                return float(
                    next(
                        row[7]
                        for row in rows
                        if row[2] == "ACLoad"
                        and row[3] == "load_ac_1"
                        and row[4].upper() == meas_type
                    )
                )

            self.assertEqual(accepted["set_values"], 2)
            self.assertAlmostEqual(float(load["pbase"]) * float(load["pv0"]), 45.0)
            self.assertAlmostEqual(float(load["qbase"]) * float(load["qv0"]), 15.0)
            self.assertAlmostEqual(measured_value(service.latest_real_rows, "P_LOAD"), 45.0)
            self.assertAlmostEqual(measured_value(service.latest_real_rows, "Q_LOAD"), 15.0)
            self.assertAlmostEqual(measured_value(service.latest_scada_rows, "P_LOAD"), 45.0)
            self.assertAlmostEqual(measured_value(service.latest_scada_rows, "Q_LOAD"), 15.0)


if __name__ == "__main__":
    unittest.main()
