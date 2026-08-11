from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

import simu_loop
from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


def _conversion_model_path() -> Path:
    return next(
        path
        for path in (ROOT / "models" / "simulator" / "source").glob("*/model.e")
        if "e2h_coeff" in path.read_text(encoding="utf-8")
        and "h2e_coeff" in path.read_text(encoding="utf-8")
    )


def _endpoint_rows(book):
    return {
        "ac_load": book.data["ACLoad"].data[1],
        "dc_gen": book.data["DCGenerator"].data[9],
        "h2_source": book.data["HydroSource"].data[0],
        "h2_load": book.data["HydroLoad"].data[0],
    }


def _measurement(snapshot, dev_type: str, dev_name: str, meas_type: str) -> float:
    row = ["1", "point", dev_type, dev_name, meas_type, "1", "1", "0"]
    value = simu_loop._measurement_value(snapshot, row)
    assert value is not None
    return float(value)


@pytest.mark.parametrize(
    ("block_name", "coefficient_field"),
    (("AcE2Hydro", "e2h_coeff"), ("Hydro2DcE", "h2e_coeff")),
)
def test_conversion_model_uses_direction_specific_coefficient_field(
    block_name,
    coefficient_field,
):
    block = simu_loop.EBook(_conversion_model_path()).data[block_name]

    assert coefficient_field in block.header_list
    assert "efficiency" not in block.header_list


def test_real_model_power_control_drives_hydrogen_flow_and_realtime_measurements():
    model_path = _conversion_model_path()
    book = simu_loop.EBook(model_path)
    rows = _endpoint_rows(book)

    snapshot, solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)

    assert "normF=" in solver_info
    assert _measurement(snapshot, "AcE2Hydro", book.data["AcE2Hydro"].data[0]["name"], "P") == pytest.approx(10.0)
    assert _measurement(snapshot, "AcE2Hydro", book.data["AcE2Hydro"].data[0]["name"], "FLOW") == pytest.approx(2.0)
    assert _measurement(snapshot, "Hydro2DcE", book.data["Hydro2DcE"].data[0]["name"], "P") == pytest.approx(10.0)
    assert _measurement(snapshot, "Hydro2DcE", book.data["Hydro2DcE"].data[0]["name"], "FLOW") == pytest.approx(10.0 / 1.8)
    assert _measurement(snapshot, "HydroSource", rows["h2_source"]["name"], "FLOW") == pytest.approx(2.0)
    assert _measurement(snapshot, "HydroLoad", rows["h2_load"]["name"], "FLOW") == pytest.approx(10.0 / 1.8)
    assert {result.status for result in snapshot.coupling_results} == {"balanced"}


def test_real_model_flow_control_ignores_conflicting_electric_setpoints():
    model_path = _conversion_model_path()
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
    assert _measurement(snapshot, "HydroSource", rows["h2_source"]["name"], "FLOW") == pytest.approx(0.4)
    assert _measurement(snapshot, "HydroLoad", rows["h2_load"]["name"], "FLOW") == pytest.approx(3.0)
    assert {result.status for result in snapshot.coupling_results} == {"balanced"}


def test_trainee_endpoint_binding_dispatches_into_live_conversion_calculation():
    model_path = _conversion_model_path()
    with tempfile.TemporaryDirectory(dir=ROOT) as runtime_dir:
        service = PolarMicrogridSimulator(
            model_path.parent,
            Path(runtime_dir),
            model_id="hydrogen-conversion-test",
        )
        converter = next(
            device
            for device in service.devices()
            if device["dev_type"] == "AcE2Hydro"
        )
        binding = next(
            item
            for item in converter["control_bindings"]
            if item["set_type"] == "p_set"
        )

        accepted = service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": binding["target_dev_type"],
                        "dev_name": binding["target_dev_name"],
                        "set_type": binding["target_set_type"],
                        "set_value": 12.0,
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
    power = real_values[("AcE2Hydro", converter["dev_name"], "P")]
    flow = real_values[("AcE2Hydro", converter["dev_name"], "FLOW")]
    assert 10.0 < power < 12.0
    assert flow == pytest.approx(power * 0.2)


@pytest.mark.parametrize("role", ("simulator", "trainee"))
def test_hydrogen_conversion_parameter_labels_and_modes_are_explicit(role):
    script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")

    assert 'e2h_coeff: "电-气效率 (Nm3/kWh)"' in script
    assert 'h2e_coeff: "气-电效率 (kWh/Nm3)"' in script
    assert 'P: "定电功率 (P)"' in script
    assert 'FLOW: "定气流量 (FLOW)"' in script
    assert "diagramDefinitionFieldLabel(field)" in script
