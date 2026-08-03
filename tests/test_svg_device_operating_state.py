from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from simu.generate_simple_model import write_model_dir
from simu.service import PolarMicrogridSimulator
import simu_loop


ROOT = Path(__file__).resolve().parents[1]


class SvgDeviceOperatingStateTest(unittest.TestCase):
    @staticmethod
    def _node(idx: int, name: str, alive: bool) -> SimpleNamespace:
        return SimpleNamespace(idx=idx, name=name, run_stat=1, is_alive=alive)

    def _qinling_model_dir(self):
        for candidate in (ROOT / "models/simulator/source").glob("*/model.e"):
            book = simu_loop.EBook(candidate)
            model = book.data.get("Model")
            if model is not None and model.data and model.data[0].get("name") == "qinling":
                return candidate.parent
        self.fail("Qinling simulator model was not found")

    @staticmethod
    def _set_runtime_run_stat(stat_book, dev_type, dev_name, run_stat):
        block = stat_book.data.get("RunStat")
        for row in block.data:
            if row.get("dev_type") == dev_type and row.get("dev_name") == dev_name:
                row["run_stat"] = run_stat
                return
        block.data.append({"dev_type": dev_type, "dev_name": dev_name, "run_stat": run_stat})

    def _run_qinling_once(self, model_dir, model_book, stat_book):
        control_book = simu_loop.EBook(model_dir / "control.e")
        weather_book = simu_loop.EBook(model_dir / "weather.e")
        before, measurement_rows, after = simu_loop.parse_measurement_rows(model_dir / "meas.e")
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            return simu_loop.run_once(simu_loop.SimulationConfig(
                model_file=model_dir / "model.e",
                meas_file=model_dir / "meas.e",
                weather_file=model_dir / "weather.e",
                dev_stat_file=model_dir / "stat.e",
                yt_ctrl_file=model_dir / "control.e",
                real_file=runtime / "real.e",
                scada_file=runtime / "scada.e",
                period_seconds=60.0,
                write_output_files=False,
                model_book=model_book,
                meas_before=before,
                meas_rows=measurement_rows,
                meas_after=after,
                weather_book=weather_book,
                dev_stat_book=stat_book,
                yt_ctrl_book=control_book,
                dev_define_book=simu_loop._capability_define_book(model_book, None),
            ))

    def test_topology_state_distinguishes_dead_island_from_open_boundary_switch(self):
        live_node = self._node(1, "live-node", True)
        dead_node_a = self._node(2, "dead-node-a", False)
        dead_node_b = self._node(3, "dead-node-b", False)
        for node in (live_node, dead_node_a, dead_node_b):
            delattr(node, "is_alive")
        dead_generator = SimpleNamespace(
            name="dead-generator",
            run_stat=1,
            is_alive=False,
            node_obj=dead_node_a,
        )
        retired_generator = SimpleNamespace(
            name="retired-generator",
            run_stat=0,
            is_alive=False,
            node_obj=live_node,
        )
        open_boundary_breaker = SimpleNamespace(
            name="open-boundary",
            run_stat=1,
            status=0,
            is_alive=False,
            i_node_obj=live_node,
            j_node_obj=dead_node_a,
        )
        dead_branch = SimpleNamespace(
            name="dead-branch",
            run_stat=1,
            is_alive=False,
            i_node_obj=dead_node_a,
            j_node_obj=dead_node_b,
        )
        ac_grid = SimpleNamespace(
            ppc={
                "_topology_arrays": SimpleNamespace(
                    node_ids=[1, 2, 3],
                    node_alive_mask=[True, False, False],
                )
            },
            nodes=[live_node, dead_node_a, dead_node_b],
            buses=[],
            generators=[dead_generator, retired_generator],
            loads=[],
            branches=[dead_branch],
            transformers=[],
            three_winding_transformers=[],
            switches=[],
            breakers=[open_boundary_breaker],
            zero_branches=[],
            shunt_compensators=[],
        )
        snapshot = SimpleNamespace(
            ac=ac_grid,
            dc=None,
            dcac_converters=[],
            acac_converters=[],
        )
        model_book = SimpleNamespace(
            data={
                "HydroLoad": SimpleNamespace(
                    header_list=["name", "node", "run_stat"],
                    data=[{"name": "hydrogen-load", "node": 2, "run_stat": 1}],
                )
            }
        )

        states = {
            (row["dev_type"], row["dev_name"]): row
            for row in simu_loop.collect_device_operating_states(snapshot, model_book)
        }

        self.assertTrue(states[("ACGenerator", "dead-generator")]["dead_island"])
        self.assertTrue(states[("ACNode", "dead-node-a")]["dead_island"])
        self.assertEqual(states[("ACGenerator", "retired-generator")]["run_stat"], 0)
        self.assertFalse(states[("ACGenerator", "retired-generator")]["dead_island"])
        self.assertFalse(states[("ACBreak", "open-boundary")]["dead_island"])
        self.assertTrue(states[("ACBranch", "dead-branch")]["dead_island"])
        self.assertFalse(states[("HydroLoad", "hydrogen-load")]["dead_island"])

    def test_dead_island_requires_all_converter_endpoints_but_preserves_boundary_semantics(self):
        live_ac_node = self._node(1, "live-ac-node", True)
        dead_ac_node = self._node(2, "dead-ac-node", False)
        live_dc_node = self._node(3, "live-dc-node", True)
        dead_dc_node = self._node(4, "dead-dc-node", False)
        ac_node_alive = {1: True, 2: False}
        dc_node_alive = {3: True, 4: False}
        converter = SimpleNamespace(
            run_stat=1,
            ac_node_obj=live_ac_node,
            dc_node_obj=dead_dc_node,
        )

        self.assertTrue(
            simu_loop._device_dead_island(
                "DCACConverter",
                converter,
                ac_node_alive,
                dc_node_alive,
            )
        )

        for dev_type, live_node, dead_node in (
            ("ACSwitch", live_ac_node, dead_ac_node),
            ("ACBreak", live_ac_node, dead_ac_node),
            ("DCSwitch", live_dc_node, dead_dc_node),
            ("DCBreak", live_dc_node, dead_dc_node),
        ):
            boundary_device = SimpleNamespace(
                run_stat=1,
                i_node_obj=live_node,
                j_node_obj=dead_node,
            )
            with self.subTest(boundary_device=dev_type):
                self.assertFalse(
                    simu_loop._device_dead_island(
                        dev_type,
                        boundary_device,
                        ac_node_alive,
                        dc_node_alive,
                    )
                )

        converter.dc_node_obj = live_dc_node
        self.assertFalse(
            simu_loop._device_dead_island(
                "DCACConverter",
                converter,
                ac_node_alive,
                dc_node_alive,
            )
        )

        converter.run_stat = 0
        converter.dc_node_obj = dead_dc_node
        self.assertFalse(
            simu_loop._device_dead_island(
                "DCACConverter",
                converter,
                ac_node_alive,
                dc_node_alive,
            )
        )

    def test_snapshot_can_return_compact_device_states_without_full_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            write_model_dir(source)
            service = PolarMicrogridSimulator(
                source,
                root / "runtime",
                kernel=lambda _config: None,
                model_id="simple",
            )
            service.latest_device_states = [
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "generator-a",
                    "run_stat": 1,
                    "dead_island": True,
                }
            ]

            payload = service.snapshot(
                include_static=False,
                include_runtime_logs=False,
                include_measurements=False,
                include_devices=False,
                include_commands=False,
                include_device_states=True,
            )

        self.assertNotIn("devices", payload)
        state_by_name = {item["dev_name"]: item for item in payload["device_states"]}
        self.assertIn("generator-a", state_by_name)
        self.assertTrue(state_by_name["generator-a"]["dead_island"])

    def test_qinling_dc_busbar_retirement_changes_topology_without_stopping_ac_flow(self):
        model_dir = self._qinling_model_dir()
        model_book = simu_loop.EBook(model_dir / "model.e")
        stat_book = simu_loop.EBook(model_dir / "stat.e")
        busbar = next(row for row in model_book.data["DCRealBs"].data if int(row["idx"]) == 1)
        node = next(row for row in model_book.data["DCNode"].data if int(row["idx"]) == int(busbar["node"]))
        self._set_runtime_run_stat(stat_book, "DCRealBs", busbar["name"], 0)

        result = self._run_qinling_once(model_dir, model_book, stat_book)

        self.assertRegex(result.solver_info, r"^iter=\d+, normF=\d\.\d{3}e[+-]\d+$|^iter=0, normF=0\.000e\+00$")
        measurements = {(row[2], row[3], row[4]): float(row[7]) for row in result.real_rows or []}
        for key in (
            ("DCNode", node["name"], "V"),
            ("DCBreak", "直流断路器-1", "P_FROM"),
            ("DCBreak", "直流断路器-1", "I"),
            ("DCACConverter", "ACDC变流器-1", "P_DC"),
            ("DCACConverter", "ACDC变流器-1", "P_AC"),
            ("DCACConverter", "ACDC变流器-1", "I_DC"),
            ("DCACConverter", "ACDC变流器-1", "I_AC"),
        ):
            with self.subTest(zero_measurement=key):
                self.assertAlmostEqual(0.0, measurements[key], places=9)

        states = {(row["dev_type"], row["dev_name"]): row for row in result.device_states or []}
        self.assertEqual(0, states[("DCRealBs", busbar["name"])]["run_stat"])
        self.assertEqual(0, states[("DCNode", node["name"])]["run_stat"])
        self.assertEqual(1, states[("DCACConverter", "ACDC变流器-1")]["run_stat"])
        self.assertTrue(states[("DCACConverter", "ACDC变流器-1")]["dead_island"])
        self.assertGreater(abs(measurements[("ACNode", "交流母线（竖向）-1", "V")]), 0.0)

    def test_qinling_ac_busbar_retirement_converges_and_zeroes_the_referenced_node(self):
        model_dir = self._qinling_model_dir()
        model_book = simu_loop.EBook(model_dir / "model.e")
        stat_book = simu_loop.EBook(model_dir / "stat.e")
        busbar = next(row for row in model_book.data["ACRealBs"].data if int(row["idx"]) == 1)
        node = next(row for row in model_book.data["ACNode"].data if int(row["idx"]) == int(busbar["node"]))
        self._set_runtime_run_stat(stat_book, "ACRealBs", busbar["name"], 0)

        result = self._run_qinling_once(model_dir, model_book, stat_book)

        self.assertRegex(result.solver_info, r"^iter=\d+, normF=\d\.\d{3}e[+-]\d+$|^iter=0, normF=0\.000e\+00$")
        measurements = {(row[2], row[3], row[4]): float(row[7]) for row in result.real_rows or []}
        states = {(row["dev_type"], row["dev_name"]): row for row in result.device_states or []}
        self.assertEqual(0, states[("ACRealBs", busbar["name"])]["run_stat"])
        self.assertEqual(0, states[("ACNode", node["name"])]["run_stat"])
        self.assertAlmostEqual(0.0, measurements[("ACNode", node["name"], "V")], places=9)

        for state_key, state in states.items():
            if state_key[0] != "DCNode" or state["run_stat"] != 1:
                continue
            voltage_key = ("DCNode", state_key[1], "V")
            if voltage_key not in measurements:
                continue
            if state["dead_island"]:
                self.assertAlmostEqual(0.0, measurements[voltage_key], places=9)

    def test_qinling_busbar_restore_does_not_reenable_explicitly_retired_node(self):
        model_dir = self._qinling_model_dir()
        source = simu_loop.EBook(model_dir / "model.e")
        busbar = next(row for row in source.data["DCRealBs"].data if int(row["idx"]) == 1)
        node = next(row for row in source.data["DCNode"].data if int(row["idx"]) == int(busbar["node"]))
        stat = simu_loop.EBook(model_dir / "stat.e")
        self._set_runtime_run_stat(stat, "DCRealBs", busbar["name"], 1)
        self._set_runtime_run_stat(stat, "DCNode", node["name"], 0)

        result = self._run_qinling_once(model_dir, source, stat)
        states = {(row["dev_type"], row["dev_name"]): row for row in result.device_states or []}

        self.assertEqual(1, states[("DCRealBs", busbar["name"])]["run_stat"])
        self.assertEqual(0, states[("DCNode", node["name"])]["run_stat"])

    def test_open_main_bus_branches_are_zeroed_and_reported_as_dead_islands(self):
        model_dir = None
        for candidate in (ROOT / "models/simulator/source").glob("*/model.e"):
            book = simu_loop.EBook(candidate)
            model = book.data.get("Model")
            if model is not None and model.data and model.data[0].get("name") == "qinling":
                model_dir = candidate.parent
                break
        self.assertIsNotNone(model_dir)

        model_book = simu_loop.EBook(model_dir / "model.e")
        stat_book = simu_loop.EBook(model_dir / "stat.e")
        control_book = simu_loop.EBook(model_dir / "control.e")
        weather_book = simu_loop.EBook(model_dir / "weather.e")
        before, measurement_rows, after = simu_loop.parse_measurement_rows(model_dir / "meas.e")

        opened = {}
        for dev_type, idx in (("ACBreak", 4), ("DCBreak", 14), ("DCBreak", 15)):
            source_row = next(
                row for row in model_book.data[dev_type].data
                if int(row.get("idx", -1)) == idx
            )
            opened[(dev_type, idx)] = source_row["name"]
            runtime_row = next(
                row for row in stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == dev_type and row.get("dev_name") == source_row["name"]
            )
            runtime_row["status"] = 0

        names = {
            (dev_type, idx): next(
                row["name"] for row in model_book.data[dev_type].data
                if int(row.get("idx", -1)) == idx
            )
            for dev_type, idx in (
                ("ACGenerator", 12),
                ("DCGenerator", 3),
                ("DCGenerator", 4),
                ("DCDCConverter", 3),
                ("DCDCConverter", 4),
            )
        }

        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            config = simu_loop.SimulationConfig(
                model_file=model_dir / "model.e",
                meas_file=model_dir / "meas.e",
                weather_file=model_dir / "weather.e",
                dev_stat_file=model_dir / "stat.e",
                yt_ctrl_file=model_dir / "control.e",
                real_file=runtime / "real.e",
                scada_file=runtime / "scada.e",
                period_seconds=60.0,
                write_output_files=False,
                model_book=model_book,
                meas_before=before,
                meas_rows=measurement_rows,
                meas_after=after,
                weather_book=weather_book,
                dev_stat_book=stat_book,
                yt_ctrl_book=control_book,
                dev_define_book=simu_loop._capability_define_book(model_book, None),
            )
            result = simu_loop.run_once(config)

        measurements = {
            (row[2], row[3], row[4]): float(row[7])
            for row in result.real_rows or []
        }
        zero_measurements = (
            ("ACGenerator", names[("ACGenerator", 12)], "P_GEN"),
            ("DCGenerator", names[("DCGenerator", 3)], "P_GEN"),
            ("DCGenerator", names[("DCGenerator", 4)], "P_GEN"),
            ("DCDCConverter", names[("DCDCConverter", 3)], "P_FROM"),
            ("DCDCConverter", names[("DCDCConverter", 3)], "P_TO"),
            ("DCDCConverter", names[("DCDCConverter", 4)], "P_FROM"),
            ("DCDCConverter", names[("DCDCConverter", 4)], "P_TO"),
        )
        for key in zero_measurements:
            with self.subTest(measurement=key):
                self.assertAlmostEqual(measurements[key], 0.0, places=9)

        states = {
            (row["dev_type"], row["dev_name"]): row
            for row in result.device_states or []
        }
        for key in (
            ("ACGenerator", names[("ACGenerator", 12)]),
            ("DCGenerator", names[("DCGenerator", 3)]),
            ("DCGenerator", names[("DCGenerator", 4)]),
            ("DCDCConverter", names[("DCDCConverter", 3)]),
            ("DCDCConverter", names[("DCDCConverter", 4)]),
        ):
            with self.subTest(dead_island=key):
                self.assertEqual(states[key]["run_stat"], 1)
                self.assertTrue(states[key]["dead_island"])
        for dev_type, idx in (("ACBreak", 4), ("DCBreak", 14), ("DCBreak", 15)):
            key = (dev_type, opened[(dev_type, idx)])
            with self.subTest(open_boundary=key):
                self.assertFalse(states[key]["dead_island"])

    def test_five_open_breakers_with_three_offline_diesels_converges(self):
        model_dir = None
        for candidate in (ROOT / "models/simulator/source").glob("*/model.e"):
            book = simu_loop.EBook(candidate)
            model = book.data.get("Model")
            if model is not None and model.data and model.data[0].get("name") == "qinling":
                model_dir = candidate.parent
                break
        self.assertIsNotNone(model_dir)

        model_book = simu_loop.EBook(model_dir / "model.e")
        stat_book = simu_loop.EBook(model_dir / "stat.e")
        control_book = simu_loop.EBook(model_dir / "control.e")
        weather_book = simu_loop.EBook(model_dir / "weather.e")
        before, measurement_rows, after = simu_loop.parse_measurement_rows(model_dir / "meas.e")

        opened_names = []
        for dev_type, idx in (
            ("ACBreak", 4),
            ("ACBreak", 5),
            ("ACBreak", 6),
            ("DCBreak", 14),
            ("DCBreak", 15),
        ):
            source_row = next(
                row for row in model_book.data[dev_type].data
                if int(row.get("idx", -1)) == idx
            )
            opened_names.append((dev_type, source_row["name"]))
            runtime_row = next(
                row for row in stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == dev_type and row.get("dev_name") == source_row["name"]
            )
            runtime_row["status"] = 0

        offline_diesels = []
        for idx in (12, 13, 14):
            source_row = next(
                row for row in model_book.data["ACGenerator"].data
                if int(row.get("idx", -1)) == idx
            )
            offline_diesels.append(source_row["name"])
            runtime_row = next(
                row for row in stat_book.data["RunStat"].data
                if row.get("dev_type") == "ACGenerator" and row.get("dev_name") == source_row["name"]
            )
            runtime_row["run_stat"] = 0

        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            config = simu_loop.SimulationConfig(
                model_file=model_dir / "model.e",
                meas_file=model_dir / "meas.e",
                weather_file=model_dir / "weather.e",
                dev_stat_file=model_dir / "stat.e",
                yt_ctrl_file=model_dir / "control.e",
                real_file=runtime / "real.e",
                scada_file=runtime / "scada.e",
                period_seconds=300.0,
                write_output_files=False,
                model_book=model_book,
                meas_before=before,
                meas_rows=measurement_rows,
                meas_after=after,
                weather_book=weather_book,
                dev_stat_book=stat_book,
                yt_ctrl_book=control_book,
                dev_define_book=simu_loop._capability_define_book(model_book, None),
            )
            result = simu_loop.run_once(config)

        self.assertRegex(result.solver_info, r"^iter=\d+, normF=\d\.\d{3}e[+-]\d+$")
        states = {
            (row["dev_type"], row["dev_name"]): row
            for row in result.device_states or []
        }
        for dev_type, name in opened_names:
            with self.subTest(open_boundary=(dev_type, name)):
                self.assertEqual(states[(dev_type, name)]["run_stat"], 1)
                self.assertFalse(states[(dev_type, name)]["dead_island"])
        for name in offline_diesels:
            with self.subTest(offline_diesel=name):
                self.assertEqual(states[("ACGenerator", name)]["run_stat"], 0)


if __name__ == "__main__":
    unittest.main()
