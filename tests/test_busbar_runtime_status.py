import unittest

import simu_loop


def _book(**blocks):
    return simu_loop.EBook({name: [dict(row) for row in rows] for name, rows in blocks.items()})


class BusbarRuntimeStatusTest(unittest.TestCase):
    def test_retired_real_bus_forces_referenced_ac_and_dc_nodes_off(self):
        model = _book(
            ACNode=[{"idx": 7, "name": "ac-node", "run_stat": 1}],
            ACRealBs=[{"idx": 1, "name": "ac-bus", "node": 7, "run_stat": 1}],
            DCNode=[{"idx": 9, "name": "dc-node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "dc-bus", "node": 9, "run_stat": 1}],
        )
        stat = _book(
            RunStat=[
                {"dev_type": "ACRealBs", "dev_name": "ac-bus", "run_stat": 0},
                {"dev_type": "DCRealBs", "dev_name": "dc-bus", "run_stat": 0},
            ]
        )

        simu_loop.apply_dev_stat_book(model, stat)

        self.assertEqual("0", str(model.data["ACNode"].data[0]["run_stat"]))
        self.assertEqual("0", str(model.data["DCNode"].data[0]["run_stat"]))

    def test_node_state_is_own_state_and_all_referencing_bus_states(self):
        model = _book(
            ACNode=[
                {"idx": 1, "name": "explicitly-off", "run_stat": 1},
                {"idx": 2, "name": "multi-bus", "run_stat": 1},
            ],
            ACRealBs=[
                {"idx": 1, "name": "bus-a", "node": 1, "run_stat": 1},
                {"idx": 2, "name": "bus-b", "node": 2, "run_stat": 1},
                {"idx": 3, "name": "bus-c", "node": 2, "run_stat": 1},
            ],
        )
        stat = _book(
            RunStat=[
                {"dev_type": "ACNode", "dev_name": "explicitly-off", "run_stat": 0},
                {"dev_type": "ACRealBs", "dev_name": "bus-a", "run_stat": 1},
                {"dev_type": "ACRealBs", "dev_name": "bus-b", "run_stat": 1},
                {"dev_type": "ACRealBs", "dev_name": "bus-c", "run_stat": 0},
            ]
        )

        simu_loop.apply_dev_stat_book(model, stat)

        by_name = {row["name"]: int(row["run_stat"]) for row in model.data["ACNode"].data}
        self.assertEqual(0, by_name["explicitly-off"])
        self.assertEqual(0, by_name["multi-bus"])

    def test_busbar_constraint_does_not_mutate_neighboring_devices(self):
        model = _book(
            DCNode=[{"idx": 5, "name": "bus-node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "bus", "node": 5, "run_stat": 1}],
            DCBreak=[{"idx": 1, "name": "breaker", "i_node": 5, "j_node": 6, "status": 1, "run_stat": 1}],
            DCBranch=[{"idx": 1, "name": "line", "i_node": 5, "j_node": 6, "run_stat": 1}],
            DCACConverter=[{"idx": 1, "name": "converter", "dc_node": 6, "ac_node": 3, "run_stat": 1}],
        )
        stat = _book(RunStat=[{"dev_type": "DCRealBs", "dev_name": "bus", "run_stat": 0}])

        simu_loop.apply_dev_stat_book(model, stat)

        self.assertEqual(1, int(model.data["DCBreak"].data[0]["run_stat"]))
        self.assertEqual(1, int(model.data["DCBreak"].data[0]["status"]))
        self.assertEqual(1, int(model.data["DCBranch"].data[0]["run_stat"]))
        self.assertEqual(1, int(model.data["DCACConverter"].data[0]["run_stat"]))

    def test_missing_busbar_node_reference_warns_and_leaves_other_nodes_unchanged(self):
        model = _book(
            DCNode=[{"idx": 1, "name": "valid-node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "bad-bus", "node": 999, "run_stat": 0}],
        )

        with self.assertLogs("SimulationLoop", level="WARNING") as captured:
            simu_loop.apply_dev_stat_book(model, _book())

        self.assertEqual(1, int(model.data["DCNode"].data[0]["run_stat"]))
        self.assertIn("DCRealBs", "\n".join(captured.output))
        self.assertIn("bad-bus", "\n".join(captured.output))
        self.assertIn("999", "\n".join(captured.output))

    def test_missing_node_block_warns_for_each_real_busbar(self):
        model = _book(
            DCRealBs=[{"idx": 1, "name": "orphan-bus", "node": 777, "run_stat": 1}],
        )

        with self.assertLogs("SimulationLoop", level="WARNING") as captured:
            simu_loop.apply_dev_stat_book(model, _book())

        output = "\n".join(captured.output)
        self.assertIn("DCRealBs", output)
        self.assertIn("orphan-bus", output)
        self.assertIn("777", output)
        self.assertNotIn("DCNode", model.data)

    def test_fresh_model_clone_restores_node_when_busbar_returns(self):
        source = _book(
            DCNode=[{"idx": 3, "name": "node", "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "bus", "node": 3, "run_stat": 1}],
        )
        retired = simu_loop._clone_ebook(source)
        restored = simu_loop._clone_ebook(source)

        simu_loop.apply_dev_stat_book(
            retired,
            _book(RunStat=[{"dev_type": "DCRealBs", "dev_name": "bus", "run_stat": 0}]),
        )
        simu_loop.apply_dev_stat_book(
            restored,
            _book(RunStat=[{"dev_type": "DCRealBs", "dev_name": "bus", "run_stat": 1}]),
        )

        self.assertEqual(0, int(retired.data["DCNode"].data[0]["run_stat"]))
        self.assertEqual(1, int(restored.data["DCNode"].data[0]["run_stat"]))
