from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_body(script: str, name: str) -> str:
    marker = f"function {name}("
    if marker not in script:
        marker = f"async function {name}("
    assert marker in script
    return script.split(marker, 1)[1].split("\nfunction ", 1)[0]


def test_simulator_model_management_operations_do_not_switch_display_model():
    script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

    for function_name in (
        "createNewModelFromFile",
        "importDefinitionModel",
        "updateModelFromFile",
        "cloneCurrentModel",
    ):
        assert "setActiveModel(" not in _function_body(script, function_name)

    delete_body = _function_body(script, "deleteManagedModel")
    assert "const deletedActiveModel =" in delete_body
    assert "if (deletedActiveModel)" in delete_body
    assert "setActiveModel(nextId, true)" in delete_body


def test_trainee_model_management_operations_do_not_switch_display_model():
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    for function_name in (
        "createNewModelSlot",
        "cloneManagedModel",
        "initializeModelFromLink",
    ):
        assert "setActiveModel(" not in _function_body(script, function_name)

    delete_body = _function_body(script, "deleteManagedModel")
    assert "const deletedActiveModel =" in delete_body
    assert "if (deletedActiveModel)" in delete_body
    assert "setActiveModel(nextId, true)" in delete_body
