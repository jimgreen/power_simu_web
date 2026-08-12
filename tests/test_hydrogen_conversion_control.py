from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import math
import random
import re
import tempfile
import zipfile

import pytest

import simu_loop
from simu import server as server_module
from simu.definition_editing import render_ebook_aligned
from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


def _replace_block(text: str, block_name: str, replacement: str) -> str:
    updated, count = re.subn(
        rf"<{block_name}>.*?</{block_name}>",
        replacement.strip(),
        text,
        count=1,
        flags=re.DOTALL,
    )
    assert count == 1
    return updated


def _write_conversion_model(
    directory: Path,
    *,
    electrolyzer_mode: str = "P",
    fuel_cell_mode: str = "P",
    hydrogen_flow_max: float = 20.0,
    fuel_cell_coefficient: float = 1.8,
    electric_power_max: float = 50.0,
    hydrogen_pipe_conductance: float = 3.0,
) -> Path:
    text = (ROOT / "tests" / "fixtures" / "simple_model" / "model.e").read_text(
        encoding="utf-8"
    )
    text = _replace_block(
        text,
        "ACLoad",
        f"""
<ACLoad>
@ idx name node p_set p_max p_min q_max q_min run_stat rated_capacity pbase pv0 pv1 pv2 qbase qv0 qv1 qv2
# 1 electrolyzer_ac_load 6 2 {electric_power_max} 0 30 0 1 {electric_power_max} 2 1 0 0 30 1 0 0
</ACLoad>
""",
    )
    text = _replace_block(
        text,
        "DCGenerator",
        """
<DCGenerator>
@ idx name dev_type node control_type v_set p_set p_max p_min i_set run_stat rated_capacity
# 1 dc_bus_vctrl dc-voltage-source 1 V 720 0 100 -100 0 1 100
# 2 pv01_vsrc dc-pv-source 3 P 300 0 50 0 0 1 50
# 3 ess01_vsrc dc-storage 5 P 300 0 40 -40 0 1 40
# 4 fuel_cell_dc_source dc-fuel-cell 4 P 720 5.4 50 0 0 1 50
</DCGenerator>
""",
    )
    text += """
<HydroMedium>
@ density compressibility molar_mass temperature flow_factor
# 0.08375 1.0 0.002016 288.15 0.35
</HydroMedium>
<HydroNode>
@ idx name pressure run_stat
# 1 h2_reference 3.00 1
# 2 h2_load_bus 2.95 1
# 3 h2_source_bus 2.98 1
</HydroNode>
<HydroSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max run_stat
# 1 h2_reference_source 1 PRESSURE 3.00 0 1 0 20 1
# 2 electrolyzer_h2_source 3 FLOW 2.98 0.4 1 0 {hydrogen_flow_max} 1
</HydroSource>
<HydroLoad>
@ idx name node flow_set flow_min flow_max run_stat
# 1 fuel_cell_h2_load 2 3 0 {hydrogen_flow_max} 1
</HydroLoad>
<HydroPipe>
@ idx name i_node j_node conductance run_stat
# 1 h2_pipe_12 1 2 {hydrogen_pipe_conductance} 1
# 2 h2_pipe_13 1 3 {hydrogen_pipe_conductance} 1
</HydroPipe>
<AcE2Hydro>
@ idx name run_stat control_type idx_ac_load_t1 idx_h2_unit_t2 e2h_coeff
# 1 ac_electrolyzer 1 {electrolyzer_mode} 1 2 0.2
</AcE2Hydro>
<Hydro2DcE>
@ idx name run_stat control_type idx_dc_unit_t1 idx_h2_load_t2 h2e_coeff
# 1 dc_fuel_cell 1 {fuel_cell_mode} 4 1 {fuel_cell_coefficient}
</Hydro2DcE>
""".format(
        electrolyzer_mode=electrolyzer_mode,
        fuel_cell_mode=fuel_cell_mode,
        hydrogen_flow_max=hydrogen_flow_max,
        fuel_cell_coefficient=fuel_cell_coefficient,
        electric_power_max=electric_power_max,
        hydrogen_pipe_conductance=hydrogen_pipe_conductance,
    )
    model_path = directory / "model.e"
    model_path.write_text(text, encoding="utf-8")
    return model_path


def _write_storage_coupled_model(directory: Path) -> Path:
    model_path = _write_conversion_model(directory)
    text = model_path.read_text(encoding="utf-8")
    text = _replace_block(
        text,
        "HydroNode",
        """
<HydroNode>
@ idx name pressure run_stat
# 1 h2_bus 35 1
</HydroNode>
""",
    )
    text = _replace_block(
        text,
        "HydroSource",
        """
<HydroSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max run_stat
# 1 electrolyzer_h2_source 1 FLOW 35 0.4 1 0 20 1
</HydroSource>
""",
    )
    text = _replace_block(
        text,
        "HydroLoad",
        """
<HydroLoad>
@ idx name node flow_set flow_min flow_max run_stat
# 1 fuel_cell_h2_load 1 3 0 20 1
</HydroLoad>
""",
    )
    text = _replace_block(
        text,
        "HydroPipe",
        """
<HydroPipe>
@ idx name i_node j_node conductance run_stat
</HydroPipe>
""",
    )
    text = text.replace(
        "# 1 ac_electrolyzer 1 P 1 2 0.2",
        "# 1 ac_electrolyzer 1 P 1 1 0.2",
    )
    text += """
<HydroStorage>
@ idx name dev_type node control_type pressure_set flow_set alpha flow_min flow_max run_stat pressure capacity water_volume initial_soc pressure_max pressure_min
# 1 tank-1 hydrogen-tank 1 PRESSURE 1.5555555555555556 0 1 -20 20 1 1.5555555555555556 1000 50 0.7777777777777778 45 2
</HydroStorage>
"""
    model_path.write_text(text, encoding="utf-8")
    return model_path


def _endpoint_rows(book):
    return {
        "ac_load": book.data["ACLoad"].data[0],
        "dc_gen": book.data["DCGenerator"].data[3],
        "h2_source": book.data["HydroSource"].data[1],
        "h2_load": book.data["HydroLoad"].data[0],
    }


def _measurement(snapshot, dev_type: str, dev_name: str, meas_type: str) -> float:
    row = ["1", "point", dev_type, dev_name, meas_type, "1", "1", "0"]
    value = simu_loop._measurement_value(snapshot, row)
    assert value is not None
    return float(value)


def _inline_hydrogen_model_text() -> str:
    with tempfile.TemporaryDirectory() as temporary:
        model_path = _write_conversion_model(Path(temporary))
        text = model_path.read_text(encoding="utf-8")
    text = _replace_block(
        text,
        "HydroNode",
        """
<HydroNode>
@ idx name pressure run_stat
# 1 h2_reference 3.00 1
# 2 h2_pipe_bus 2.99 1
# 3 h2_valve_bus 2.98 1
# 4 h2_compressor_bus 2.97 1
# 5 h2_regulator_bus 2.96 1
# 6 h2_stop_bus 2.95 1
# 7 h2_closed_bus 2.94 1
# 8 h2_load_bus 2.93 1
</HydroNode>
""",
    )
    text = _replace_block(
        text,
        "HydroSource",
        """
<HydroSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max run_stat
# 1 h2_reference_source 1 PRESSURE 3.00 0 1 0 20 1
# 2 electrolyzer_h2_source 1 FLOW 3.00 0.4 1 0 20 1
</HydroSource>
""",
    )
    text = _replace_block(
        text,
        "HydroLoad",
        """
<HydroLoad>
@ idx name node flow_set flow_min flow_max run_stat
# 1 fuel_cell_h2_load 8 3 0 20 1
</HydroLoad>
""",
    )
    text = _replace_block(
        text,
        "HydroPipe",
        """
<HydroPipe>
@ idx name i_node j_node conductance run_stat
# 11 pipe-1 1 2 30.0 1
# 12 pipe-closed-bypass 7 8 30.0 1
# 13 pipe-2 6 8 30.0 1
</HydroPipe>
""",
    )
    text += """
<HydroValve>
@ idx name i_node j_node control_type conductance flow_set run_stat
# 21 valve-1 2 3 OPEN 30.0 0 1
</HydroValve>
<HydroCompressor>
@ idx name i_node j_node control_type ratio conductance flow_set run_stat
# 31 compressor-1 3 4 RATIO 1.0 30.0 0 1
</HydroCompressor>
<HydroPressRegulator>
@ idx name i_node j_node ratio conductance run_stat
# 41 regulator-1 4 5 1.0 30.0 1
</HydroPressRegulator>
<HydroStopValve>
@ idx name i_node j_node status conductance run_stat
# 51 stop-valve-open 5 6 1 30.0 1
# 52 stop-valve-closed 6 7 0 30.0 1
</HydroStopValve>
"""
    return text


@pytest.mark.parametrize(
    ("block_name", "coefficient_field"),
    (("AcE2Hydro", "e2h_coeff"), ("Hydro2DcE", "h2e_coeff")),
)
def test_conversion_model_uses_direction_specific_coefficient_field(
    tmp_path,
    block_name,
    coefficient_field,
):
    block = simu_loop.EBook(_write_conversion_model(tmp_path)).data[block_name]

    assert coefficient_field in block.header_list
    assert "efficiency" not in block.header_list


def test_power_control_drives_hydrogen_flow_and_realtime_measurements(tmp_path):
    model_path = _write_conversion_model(tmp_path)
    book = simu_loop.EBook(model_path)
    rows = _endpoint_rows(book)

    snapshot, solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)

    assert "normF=" in solver_info
    assert _measurement(snapshot, "AcE2Hydro", book.data["AcE2Hydro"].data[0]["name"], "p") == pytest.approx(2.0)
    assert _measurement(snapshot, "AcE2Hydro", book.data["AcE2Hydro"].data[0]["name"], "flow") == pytest.approx(0.4)
    assert _measurement(snapshot, "Hydro2DcE", book.data["Hydro2DcE"].data[0]["name"], "p") == pytest.approx(5.4)
    assert _measurement(snapshot, "Hydro2DcE", book.data["Hydro2DcE"].data[0]["name"], "flow") == pytest.approx(3.0)
    assert _measurement(snapshot, "HydroSource", rows["h2_source"]["name"], "flow") == pytest.approx(0.4)
    assert _measurement(snapshot, "HydroLoad", rows["h2_load"]["name"], "flow") == pytest.approx(3.0)
    assert {result.status for result in snapshot.coupling_results} == {"balanced"}


def test_hydrogen_inline_device_measurements_use_i_to_j_signed_flow(tmp_path):
    model_path = _write_conversion_model(tmp_path)
    book = simu_loop.EBook(model_path)

    snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)

    for row in book.data["HydroPipe"].data:
        result = snapshot.fluid_results["hydro"].pipes[str(row["name"])]
        assert _measurement(snapshot, "HydroPipe", str(row["name"]), "flow") == pytest.approx(
            result.i_flow
        )


def test_generated_measurements_cover_all_supported_hydrogen_inline_devices(tmp_path):
    model_path = _write_conversion_model(tmp_path)
    text = model_path.read_text(encoding="utf-8") + """
<HydroValve>
@ idx name i_node j_node control_type conductance flow_set run_stat
# 1 valve-1 1 2 OPEN 3.0 0 1
</HydroValve>
<HydroCompressor>
@ idx name i_node j_node control_type ratio flow_set run_stat
# 1 compressor-1 1 2 RATIO 1.01 0 1
</HydroCompressor>
<HydroPressRegulator>
@ idx name i_node j_node run_stat
# 1 regulator-1 1 2 1
</HydroPressRegulator>
<HydroStopValve>
@ idx name i_node j_node status run_stat
# 1 stop-valve-1 1 2 1 1
</HydroStopValve>
"""
    book = server_module._book_from_text(text)
    generated = server_module._generated_measurement_book(
        book,
        server_module._generated_control_blocks(book),
    )
    flow_devices = {
        (str(row["dev_type"]), str(row["dev_name"]))
        for row in generated.data["Measurement"].data
        if str(row["meas_type"]).upper() == "FLOW"
    }

    assert {
        ("HydroPipe", "h2_pipe_12"),
        ("HydroPipe", "h2_pipe_13"),
        ("HydroValve", "valve-1"),
        ("HydroCompressor", "compressor-1"),
        ("HydroPressRegulator", "regulator-1"),
        ("HydroStopValve", "stop-valve-1"),
    }.issubset(flow_devices)


def test_old_measurement_definition_gets_end_to_end_hydrogen_inline_flow_writeback(tmp_path):
    model_text = _inline_hydrogen_model_text()
    artifacts = server_module._generated_model_artifacts(model_text)
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)

    existing_measurement = [
        "7",
        "custom.diesel.p",
        "ACGenerator",
        "diesel_300kw",
        "P_GEN",
        "2.5",
        "0",
        "123.0",
    ]
    simu_loop.write_measurement_snapshot(
        source_dir / "meas.e",
        (),
        (existing_measurement,),
        (),
    )
    service = PolarMicrogridSimulator(
        source_dir,
        tmp_path / "runtime",
        model_id="old-hydrogen-measurements",
    )

    expected_devices = {
        ("HydroPipe", "pipe-1"),
        ("HydroPipe", "pipe-2"),
        ("HydroPipe", "pipe-closed-bypass"),
        ("HydroValve", "valve-1"),
        ("HydroCompressor", "compressor-1"),
        ("HydroPressRegulator", "regulator-1"),
        ("HydroStopValve", "stop-valve-open"),
        ("HydroStopValve", "stop-valve-closed"),
    }
    reconciled_definitions = {
        (row[2], row[3], row[4].upper()): row
        for row in service.measurement_rows
    }
    for dev_type, dev_name in expected_devices:
        assert (dev_type, dev_name, "FLOW") in reconciled_definitions
    preserved = next(
        row
        for row in service.measurement_rows
        if row[1] == "custom.diesel.p"
    )
    assert preserved == existing_measurement
    assert len({row[0] for row in service.measurement_rows}) == len(service.measurement_rows)
    assert len({row[1] for row in service.measurement_rows}) == len(service.measurement_rows)

    config = service._make_config(period_seconds=1.0)
    config = replace(config, write_output_files=True)
    result = simu_loop.run_once(config, rng=random.Random(7))
    service._store_kernel_measurement_rows(result)

    real_rows = {
        (row[2], row[3], row[4].upper()): row
        for row in simu_loop.parse_measurement_rows(config.real_file)[1]
    }
    scada_rows = {
        (row[2], row[3], row[4].upper()): row
        for row in simu_loop.parse_measurement_rows(config.scada_file)[1]
    }
    solved_snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
        result.model_book,
        config.model_file,
    )
    for dev_type, dev_name in expected_devices - {
        ("HydroStopValve", "stop-valve-closed"),
        ("HydroPipe", "pipe-closed-bypass"),
    }:
        expected = simu_loop._fluid_endpoint_measurement_value(
            solved_snapshot,
            dev_type,
            dev_name,
            "FLOW",
        )
        assert expected is not None
        assert float(real_rows[(dev_type, dev_name, "FLOW")][7]) == pytest.approx(expected)
        scada_value = float(scada_rows[(dev_type, dev_name, "FLOW")][7])
        assert math.isfinite(scada_value)
        assert abs(scada_value - expected) < 0.1
    assert float(real_rows[("HydroStopValve", "stop-valve-closed", "FLOW")][7]) == 0.0
    assert float(scada_rows[("HydroStopValve", "stop-valve-closed", "FLOW")][7]) == 0.0

    api_snapshot = service.snapshot()
    api_real_keys = {
        (row["dev_type"], row["dev_name"], row["meas_type"])
        for row in api_snapshot["measurements"]["real"]
    }
    api_scada_keys = {
        (row["dev_type"], row["dev_name"], row["meas_type"])
        for row in api_snapshot["measurements"]["scada"]
    }
    assert {(dev_type, dev_name, "flow") for dev_type, dev_name in expected_devices}.issubset(
        api_real_keys
    )
    assert {(dev_type, dev_name, "flow") for dev_type, dev_name in expected_devices}.issubset(
        api_scada_keys
    )


def test_definition_archive_reconciles_missing_hydrogen_inline_flow_points(tmp_path):
    artifacts = server_module._generated_model_artifacts(_inline_hydrogen_model_text())
    package_source = tmp_path / "package-source"
    server_module._write_generated_model_artifacts(package_source, artifacts)
    simu_loop.write_measurement_snapshot(
        package_source / "meas.e",
        (),
        (
            [
                "9",
                "kept.custom.point",
                "ACGenerator",
                "diesel_300kw",
                "P_GEN",
                "3.5",
                "0",
                "12.0",
            ],
        ),
        (),
    )
    package = PolarMicrogridSimulator(
        package_source,
        tmp_path / "package-runtime",
        model_id="package",
    )

    _filename, archive = server_module.make_definition_archive(package)
    with zipfile.ZipFile(BytesIO(archive)) as definition_archive:
        exported_block = server_module._book_from_text(
            definition_archive.read("meas.e").decode("utf-8")
        ).data["Measurement"]
    exported = [
        [str(row.get(header, "")) for header in simu_loop.MEAS_HEADER]
        for row in exported_block.data
    ]

    exported_by_identity = {
        (row[2], row[3], row[4].upper()): row
        for row in exported
    }
    exported_custom = next(
        row
        for row in exported
        if row[1] == "kept.custom.point"
    )
    assert exported_custom == [
        "9",
        "kept.custom.point",
        "ACGenerator",
        "diesel_300kw",
        "P_GEN",
        "3.5",
        "0",
        "12.0",
    ]
    assert ("HydroCompressor", "compressor-1", "FLOW") in exported_by_identity
    assert ("HydroPressRegulator", "regulator-1", "FLOW") in exported_by_identity
    assert ("HydroStopValve", "stop-valve-closed", "FLOW") in exported_by_identity


def test_explicit_hydrogen_valves_keep_identity_status_and_flow_measurements(tmp_path):
    model_path = _write_conversion_model(tmp_path)
    text = model_path.read_text(encoding="utf-8")
    text = _replace_block(
        text,
        "HydroNode",
        """
<HydroNode>
@ idx name pressure run_stat
# 1 h2_reference 3.00 1
# 2 h2_valve_bus 2.98 1
# 3 h2_regulator_bus 2.96 1
# 4 h2_load_bus 2.94 1
</HydroNode>
""",
    )
    text = _replace_block(
        text,
        "HydroSource",
        """
<HydroSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max run_stat
# 1 h2_reference_source 1 PRESSURE 3.00 0 1 0 20 1
# 2 electrolyzer_h2_source 1 FLOW 3.00 0.4 1 0 20 1
</HydroSource>
""",
    )
    text = _replace_block(
        text,
        "HydroLoad",
        """
<HydroLoad>
@ idx name node flow_set flow_min flow_max run_stat
# 1 fuel_cell_h2_load 4 3 0 20 1
</HydroLoad>
""",
    )
    text = _replace_block(
        text,
        "HydroPipe",
        """
<HydroPipe>
@ idx name i_node j_node conductance run_stat
</HydroPipe>
""",
    )
    text += """
<HydroValve>
@ idx name i_node j_node control_type conductance flow_set run_stat
# 101 valve-1 1 2 OPEN 30.0 0 1
</HydroValve>
<HydroPressRegulator>
@ idx name i_node j_node ratio conductance run_stat
# 202 regulator-1 2 3 1.0 30.0 1
</HydroPressRegulator>
<HydroStopValve>
@ idx name i_node j_node status conductance run_stat
# 303 stop-valve-open 3 4 1 30.0 1
# 304 stop-valve-closed 2 4 0 30.0 1
</HydroStopValve>
"""
    book = server_module._book_from_text(text)

    rows = simu_loop._ebook_to_efile_rows(book)
    valve_block = rows["HydroValve"]
    valve_rows = {
        row[valve_block["header_list"].index("name")]: dict(
            zip(valve_block["header_list"], row)
        )
        for row in valve_block["rows"]
    }

    assert valve_rows["valve-1"]["idx"] == "101"
    assert valve_rows["regulator-1"]["idx"] == "202"
    assert valve_rows["regulator-1"]["control_type"] == "RATIO"
    assert valve_rows["stop-valve-open"]["idx"] == "303"
    assert valve_rows["stop-valve-open"]["control_type"] == "OPEN"
    assert valve_rows["stop-valve-closed"]["idx"] == "304"
    assert valve_rows["stop-valve-closed"]["control_type"] == "CLOSED"

    book.data["HydroPressRegulator"].data[0]["ratio"] = ""
    network = simu_loop._read_lf_network_from_book(book, model_path)
    hydro_network = network.fluid_networks["hydro"]
    regulator = next(edge for edge in hydro_network.edges if edge.name == "regulator-1")
    assert regulator.control_type == "PASSIVE"
    assert "stop-valve-closed" not in {edge.name for edge in hydro_network.edges}

    snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)
    for dev_type, dev_name in (
        ("HydroValve", "valve-1"),
        ("HydroPressRegulator", "regulator-1"),
        ("HydroStopValve", "stop-valve-open"),
    ):
        assert _measurement(snapshot, dev_type, dev_name, "flow") == pytest.approx(3.0)
    closed_row = [
        "1", "point", "HydroStopValve", "stop-valve-closed", "flow", "1", "1", "0"
    ]
    assert simu_loop._measurement_value(snapshot, closed_row) is None


def test_flow_control_ignores_conflicting_electric_setpoints(tmp_path):
    model_path = _write_conversion_model(tmp_path)
    book = simu_loop.EBook(model_path)
    rows = _endpoint_rows(book)
    book.data["AcE2Hydro"].data[0]["control_type"] = "FLOW"
    book.data["Hydro2DcE"].data[0]["control_type"] = "FLOW"
    rows["ac_load"].update(p_set="47", pbase="47")
    rows["dc_gen"]["p_set"] = "40"
    rows["h2_source"]["flow_set"] = "0.4"
    rows["h2_load"]["flow_set"] = "3"

    snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)

    assert snapshot.value("ACLoad", rows["ac_load"]["name"], "P_LOAD") == pytest.approx(2.0)
    assert snapshot.value("DCGenerator", rows["dc_gen"]["name"], "P_GEN") == pytest.approx(5.4)
    assert _measurement(snapshot, "HydroSource", rows["h2_source"]["name"], "flow") == pytest.approx(0.4)
    assert _measurement(snapshot, "HydroLoad", rows["h2_load"]["name"], "flow") == pytest.approx(3.0)
    assert {result.status for result in snapshot.coupling_results} == {"balanced"}


@pytest.mark.parametrize(
    (
        "coupling_block",
        "electrolyzer_mode",
        "fuel_cell_mode",
        "set_type",
        "set_value",
        "initial_value",
    ),
    (
        ("AcE2Hydro", "P", "P", "p_set", 4.0, 2.0),
        ("AcE2Hydro", "FLOW", "P", "flow_set", 0.8, 0.4),
        ("Hydro2DcE", "P", "P", "p_set", 3.6, 5.4),
        ("Hydro2DcE", "P", "FLOW", "flow_set", 2.0, 3.0),
    ),
)
def test_trainee_endpoint_binding_dispatches_into_live_conversion_calculation(
    tmp_path,
    coupling_block,
    electrolyzer_mode,
    fuel_cell_mode,
    set_type,
    set_value,
    initial_value,
):
    model_path = _write_conversion_model(
        tmp_path,
        electrolyzer_mode=electrolyzer_mode,
        fuel_cell_mode=fuel_cell_mode,
    )
    artifacts = server_module._generated_model_artifacts(model_path.read_text(encoding="utf-8"))
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    with tempfile.TemporaryDirectory(dir=ROOT) as runtime_dir:
        service = PolarMicrogridSimulator(
            source_dir,
            Path(runtime_dir),
            model_id="hydrogen-conversion-test",
        )
        converter = next(
            device
            for device in service.devices()
            if device["dev_type"] == coupling_block
        )
        binding = next(
            item
            for item in converter["control_bindings"]
            if item["set_type"] == set_type
        )

        accepted = service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": binding["target_dev_type"],
                        "dev_name": binding["target_dev_name"],
                        "set_type": binding["target_set_type"],
                        "set_value": set_value,
                    }
                ]
            },
            source="trainee-ui",
        )
        snapshot = service.step(advance_seconds=1.0)

    assert accepted == {"run_status": 0, "set_values": 1, "ignored": 0}
    real_values = {
        (row["dev_type"], row["dev_name"], row["meas_type"]): float(row["value"])
        for row in snapshot["measurements"]["real"]
    }
    bindings = {item["set_type"]: item for item in converter["control_bindings"]}
    power_binding = bindings["p_set"]
    flow_binding = bindings["flow_set"]
    power_meas_type = (
        "P_LOAD"
        if power_binding["target_dev_type"] in {"ACLoad", "DCLoad"}
        else "P_GEN"
    )
    power = real_values[
        (
            power_binding["target_dev_type"],
            power_binding["target_dev_name"],
            power_meas_type,
        )
    ]
    flow = real_values[
        (
            flow_binding["target_dev_type"],
            flow_binding["target_dev_name"],
            "flow",
        )
    ]
    active_value = power if set_type == "p_set" else flow
    assert min(initial_value, set_value) < active_value < max(initial_value, set_value)
    if coupling_block == "AcE2Hydro":
        assert flow == pytest.approx(power * 0.2)
    else:
        assert power == pytest.approx(flow * 1.8)


@pytest.mark.parametrize(
    (
        "coupling_block",
        "coupling_name",
        "electrolyzer_mode",
        "fuel_cell_mode",
        "endpoint_block",
        "endpoint_name",
        "set_type",
        "set_value",
        "expected_power",
        "expected_flow",
    ),
    (
        (
            "AcE2Hydro",
            "ac_electrolyzer",
            "P",
            "P",
            "ACLoad",
            "electrolyzer_ac_load",
            "p_set",
            4.0,
            4.0,
            0.8,
        ),
        (
            "AcE2Hydro",
            "ac_electrolyzer",
            "FLOW",
            "P",
            "HydroSource",
            "electrolyzer_h2_source",
            "flow_set",
            0.8,
            4.0,
            0.8,
        ),
        (
            "Hydro2DcE",
            "dc_fuel_cell",
            "P",
            "P",
            "DCGenerator",
            "fuel_cell_dc_source",
            "p_set",
            3.6,
            3.6,
            2.0,
        ),
        (
            "Hydro2DcE",
            "dc_fuel_cell",
            "P",
            "FLOW",
            "HydroLoad",
            "fuel_cell_h2_load",
            "flow_set",
            2.0,
            3.6,
            2.0,
        ),
    ),
)
def test_simulator_svg_endpoint_edit_applies_the_mode_selected_setpoint_to_next_step(
    tmp_path,
    coupling_block,
    coupling_name,
    electrolyzer_mode,
    fuel_cell_mode,
    endpoint_block,
    endpoint_name,
    set_type,
    set_value,
    expected_power,
    expected_flow,
):
    model_path = _write_conversion_model(
        tmp_path,
        electrolyzer_mode=electrolyzer_mode,
        fuel_cell_mode=fuel_cell_mode,
    )
    artifacts = server_module._generated_model_artifacts(
        model_path.read_text(encoding="utf-8")
    )
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    runtime_dir = tmp_path / "runtime"
    service = PolarMicrogridSimulator(
        source_dir,
        runtime_dir,
        model_id="hydrogen-svg-edit-test",
    )

    result = service.update_device_parameters(
        {
            "block_name": endpoint_block,
            "row_key": {"name": endpoint_name},
            "revision": service.definition_snapshot.revision,
            "changes": {set_type: set_value},
        }
    )
    snapshot = service.step(advance_seconds=1.0)

    assert result["runtime_control"]["set_values"][set_type] == pytest.approx(
        set_value
    )
    real_values = {
        (row["dev_type"], row["dev_name"], row["meas_type"]): float(row["value"])
        for row in snapshot["measurements"]["real"]
    }
    converter = next(
        device
        for device in service.devices()
        if device["dev_type"] == coupling_block and device["dev_name"] == coupling_name
    )
    bindings = {item["set_type"]: item for item in converter["control_bindings"]}
    power_binding = bindings["p_set"]
    flow_binding = bindings["flow_set"]
    power_meas_type = (
        "P_LOAD"
        if power_binding["target_dev_type"] in {"ACLoad", "DCLoad"}
        else "P_GEN"
    )
    assert real_values[
        (power_binding["target_dev_type"], power_binding["target_dev_name"], power_meas_type)
    ] == pytest.approx(expected_power)
    assert real_values[
        (flow_binding["target_dev_type"], flow_binding["target_dev_name"], "flow")
    ] == pytest.approx(expected_flow)


@pytest.mark.parametrize(
    (
        "endpoint_block",
        "endpoint_name",
        "set_value",
        "coupling_name",
        "hydrogen_endpoint",
        "expected_flow",
    ),
    (
        (
            "ACLoad",
            "electrolyzer_ac_load",
            60.0,
            "ac_electrolyzer",
            "HydroSource/electrolyzer_h2_source",
            12.0,
        ),
        (
            "DCGenerator",
            "fuel_cell_dc_source",
            20.0,
            "dc_fuel_cell",
            "HydroLoad/fuel_cell_h2_load",
            20.0 / 1.5,
        ),
    ),
)
def test_simulator_svg_rejects_power_setpoint_when_derived_hydrogen_flow_is_unsafe(
    tmp_path,
    endpoint_block,
    endpoint_name,
    set_value,
    coupling_name,
    hydrogen_endpoint,
    expected_flow,
):
    model_path = _write_conversion_model(
        tmp_path,
        hydrogen_flow_max=10.0,
        fuel_cell_coefficient=1.5,
        electric_power_max=100.0,
    )
    artifacts = server_module._generated_model_artifacts(
        model_path.read_text(encoding="utf-8")
    )
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    runtime_dir = tmp_path / "runtime"
    service = PolarMicrogridSimulator(
        source_dir,
        runtime_dir,
        model_id="hydrogen-svg-safety-test",
    )
    revision_before = service.definition_snapshot.revision
    target_before = next(
        row
        for row in service.definition_snapshot.model_book.data[endpoint_block].data
        if row["name"] == endpoint_name
    )["p_set"]
    stat_before = simu_loop._clone_ebook(service.runtime_stat_book)
    control_before = simu_loop._clone_ebook(service.control_book)

    with pytest.raises(ValueError) as error:
        service.update_device_parameters(
            {
                "block_name": endpoint_block,
                "row_key": {"name": endpoint_name},
                "revision": revision_before,
                "changes": {"p_set": set_value},
            }
        )

    message = str(error.value)
    for token in (
        "人工修改安全校验失败",
        f"{endpoint_block}/{endpoint_name}",
        coupling_name,
        hydrogen_endpoint,
        f"{expected_flow:.3g}",
        "flow_max=10",
        "人工覆盖层、运行控制文件和仿真边界均未更新",
    ):
        assert token in message

    target_after = next(
        row
        for row in service.definition_snapshot.model_book.data[endpoint_block].data
        if row["name"] == endpoint_name
    )["p_set"]
    assert service.definition_snapshot.revision == revision_before
    assert target_after == target_before
    assert service.command_history == []
    assert service.manual_definition_changes()["changes"] == []
    assert not (runtime_dir / "manual_overrides.json").exists()
    assert render_ebook_aligned(service.runtime_stat_book) == render_ebook_aligned(stat_before)
    assert render_ebook_aligned(service.control_book) == render_ebook_aligned(control_before)


@pytest.mark.parametrize(
    (
        "endpoint_block",
        "endpoint_name",
        "set_value",
        "coupling_name",
        "hydrogen_endpoint",
        "expected_flow",
    ),
    (
        (
            "ACLoad",
            "electrolyzer_ac_load",
            60.0,
            "ac_electrolyzer",
            "HydroSource/electrolyzer_h2_source",
            12.0,
        ),
        (
            "DCGenerator",
            "fuel_cell_dc_source",
            20.0,
            "dc_fuel_cell",
            "HydroLoad/fuel_cell_h2_load",
            20.0 / 1.5,
        ),
    ),
)
@pytest.mark.parametrize("source", ("trainee-ui", "trainee-renewable-priority"))
def test_remote_adjustment_rejects_unsafe_derived_hydrogen_flow_atomically(
    tmp_path,
    endpoint_block,
    endpoint_name,
    set_value,
    coupling_name,
    hydrogen_endpoint,
    expected_flow,
    source,
):
    model_path = _write_conversion_model(
        tmp_path,
        hydrogen_flow_max=10.0,
        fuel_cell_coefficient=1.5,
        electric_power_max=100.0,
    )
    artifacts = server_module._generated_model_artifacts(
        model_path.read_text(encoding="utf-8")
    )
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    runtime_dir = tmp_path / "runtime"
    service = PolarMicrogridSimulator(
        source_dir,
        runtime_dir,
        model_id="hydrogen-command-safety-test",
    )
    stat_before = render_ebook_aligned(service.runtime_stat_book)

    with pytest.raises(ValueError) as error:
        service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": "ACLoad",
                        "dev_name": "electrolyzer_ac_load",
                        "set_type": "p_set",
                        "set_value": 4.0,
                    },
                    {
                        "dev_type": endpoint_block,
                        "dev_name": endpoint_name,
                        "set_type": "p_set",
                        "set_value": set_value,
                    },
                ]
            },
            source=source,
        )

    message = str(error.value)
    for token in (
        "遥调安全校验失败",
        f"{endpoint_block}/{endpoint_name}",
        coupling_name,
        hydrogen_endpoint,
        f"{expected_flow:.3g}",
        "flow_max=10",
        "本批指令未下发",
    ):
        assert token in message

    assert service.command_history == []
    assert render_ebook_aligned(service.runtime_stat_book) == stat_before
    assert not (runtime_dir / "commands.json").exists()


@pytest.mark.parametrize(
    (
        "endpoint_block",
        "endpoint_name",
        "set_value",
        "coupling_block",
        "coupling_name",
        "expected_flow",
    ),
    (
        (
            "ACLoad",
            "electrolyzer_ac_load",
            40.0,
            "AcE2Hydro",
            "ac_electrolyzer",
            8.0,
        ),
        (
            "DCGenerator",
            "fuel_cell_dc_source",
            15.0,
            "Hydro2DcE",
            "dc_fuel_cell",
            10.0,
        ),
    ),
)
def test_safe_power_setpoint_reaches_conversion_kernel_at_hydrogen_flow_limit(
    tmp_path,
    endpoint_block,
    endpoint_name,
    set_value,
    coupling_block,
    coupling_name,
    expected_flow,
):
    model_path = _write_conversion_model(
        tmp_path,
        hydrogen_flow_max=10.0,
        fuel_cell_coefficient=1.5,
        hydrogen_pipe_conductance=100.0,
    )
    artifacts = server_module._generated_model_artifacts(
        model_path.read_text(encoding="utf-8")
    )
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    service = PolarMicrogridSimulator(
        source_dir,
        tmp_path / "runtime",
        model_id="hydrogen-safe-boundary-test",
    )

    if endpoint_block == "ACLoad":
        service.update_device_parameters(
            {
                "block_name": "DCGenerator",
                "row_key": {"name": "fuel_cell_dc_source"},
                "revision": service.definition_snapshot.revision,
                "changes": {"p_set": 0.0},
            }
        )
    else:
        service.update_device_parameters(
            {
                "block_name": "ACLoad",
                "row_key": {"name": "electrolyzer_ac_load"},
                "revision": service.definition_snapshot.revision,
                "changes": {"p_set": 0.0},
            }
        )

    service.update_device_parameters(
        {
            "block_name": endpoint_block,
            "row_key": {"name": endpoint_name},
            "revision": service.definition_snapshot.revision,
            "changes": {"p_set": set_value},
        }
    )
    snapshot = service.step(advance_seconds=1.0)

    real_values = {
        (row["dev_type"], row["dev_name"], row["meas_type"]): float(row["value"])
        for row in snapshot["measurements"]["real"]
    }
    converter = next(
        device
        for device in service.devices()
        if device["dev_type"] == coupling_block and device["dev_name"] == coupling_name
    )
    bindings = {item["set_type"]: item for item in converter["control_bindings"]}
    power_binding = bindings["p_set"]
    flow_binding = bindings["flow_set"]
    power_meas_type = (
        "P_LOAD"
        if power_binding["target_dev_type"] in {"ACLoad", "DCLoad"}
        else "P_GEN"
    )
    assert real_values[
        (power_binding["target_dev_type"], power_binding["target_dev_name"], power_meas_type)
    ] == pytest.approx(set_value)
    assert real_values[
        (flow_binding["target_dev_type"], flow_binding["target_dev_name"], "flow")
    ] == pytest.approx(expected_flow)


@pytest.mark.parametrize(
    ("electrolyzer_power", "expected_flow"),
    (
        (4.0, 2.2),
        (20.0, -1.0),
    ),
)
def test_coupled_hydrogen_flow_updates_all_tank_runtime_states(
    tmp_path,
    electrolyzer_power,
    expected_flow,
):
    model_path = _write_storage_coupled_model(tmp_path)
    artifacts = server_module._generated_model_artifacts(
        model_path.read_text(encoding="utf-8")
    )
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    service = PolarMicrogridSimulator(
        source_dir,
        tmp_path / "runtime",
        model_id="hydrogen-storage-coupling-test",
    )

    service.update_device_parameters(
        {
            "block_name": "ACLoad",
            "row_key": {"name": "electrolyzer_ac_load"},
            "revision": service.definition_snapshot.revision,
            "changes": {"p_set": electrolyzer_power},
        }
    )
    snapshot = service.step(advance_seconds=3600.0)

    storage_values = {
        row["meas_type"]: float(row["value"])
        for row in snapshot["measurements"]["real"]
        if row["dev_type"] == "HydroStorage" and row["dev_name"] == "tank-1"
    }
    expected_quantity = 777.7777777777778 - expected_flow
    expected_press = expected_quantity / 50.0 / 10.0
    expected_capacity = 1000.0

    assert storage_values["flow"] == pytest.approx(expected_flow)
    assert storage_values["pressure"] == pytest.approx(expected_press)
    assert storage_values["gas_quantity"] == pytest.approx(expected_quantity)
    assert storage_values["soc"] == pytest.approx(expected_quantity / expected_capacity)
    direction = -1.0 if expected_flow > 0.0 else 1.0
    assert (storage_values["pressure"] - 1.5555555555555556) * direction > 0.0
    assert (storage_values["gas_quantity"] - 777.7777777777778) * direction > 0.0
    assert (storage_values["soc"] - 0.7777777777777778) * direction > 0.0


def test_hydrogen_model_converges_with_safe_endpoint_power_limits(tmp_path):
    model_path = _write_conversion_model(
        tmp_path,
        hydrogen_flow_max=10.0,
        fuel_cell_coefficient=1.5,
        electric_power_max=100.0,
        hydrogen_pipe_conductance=100.0,
    )
    book = simu_loop.EBook(model_path)
    electrolyzer_load = book.data["ACLoad"].data[0]
    electrolyzer_load["p_set"] = "40"
    fuel_cell_coupling = book.data["Hydro2DcE"].data[0]
    fuel_cell_generator = next(
        row
        for row in book.data["DCGenerator"].data
        if str(row.get("idx")) == str(fuel_cell_coupling["idx_dc_unit_t1"])
    )
    fuel_cell_generator["p_set"] = "15"

    _snapshot, solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)

    assert float(electrolyzer_load["p_set"]) == 40.0
    assert float(fuel_cell_generator["p_set"]) == 15.0
    assert "normF=" in solver_info


@pytest.mark.parametrize("role", ("simulator", "trainee"))
def test_hydrogen_conversion_parameter_labels_and_modes_are_explicit(role):
    script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")

    assert 'e2h_coeff: "电-气效率 (Nm3/kWh)"' in script
    assert 'h2e_coeff: "气-电效率 (kWh/Nm3)"' in script
    assert 'P: "定电功率 (P)"' in script
    assert 'FLOW: "定气流量 (FLOW)"' in script
    assert '["PRESS", "PRESSURE"]' not in script
    assert 'type === "PRESS"' not in script
    assert "diagramDefinitionFieldLabel(field)" in script
    assert "diagramDefinitionControlModeOptions(record, field)" in script
    assert "data-diagram-definition-control-mode" in script
    assert "data-diagram-definition-enum" in script
    assert "无效选项" in script


def test_trainee_coupling_command_dialog_only_uses_the_active_mode_binding():
    script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

    function_body = script.split("function diagramDeviceAdjustmentRows", 1)[1].split(
        "function closeDiagramDeviceCommandDialog",
        1,
    )[0]
    assert "binding?.active" in function_body
    assert "couplingControlSetType" in function_body
