from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManualDefinitionChangesUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        cls.trainee_html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.trainee_script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    @staticmethod
    def _function_window(script: str, function_name: str, size: int = 2600) -> str:
        async_marker = f"async function {function_name}"
        marker = async_marker if async_marker in script else f"function {function_name}"
        start = script.index(marker)
        return script[start : start + size]

    def test_simulator_has_manual_change_query_page(self):
        self.assertIn('data-nav-page="manual-changes"', self.html)
        self.assertIn('data-page="manual-changes"', self.html)
        self.assertIn('id="manualDefinitionChangesTable"', self.html)
        self.assertIn('id="resetSelectedManualChanges"', self.html)
        self.assertIn('id="retryPendingManualChanges"', self.html)
        self.assertIn('id="refreshManualChanges"', self.html)
        for label in ("人工修改", "默认值", "当前值", "修改时间", "恢复默认值"):
            self.assertIn(label, self.html)

    def test_simulator_loads_lists_selects_and_resets_changes(self):
        for function_name in (
            "loadManualDefinitionChanges",
            "renderManualDefinitionChanges",
            "toggleManualDefinitionChange",
            "resetSelectedManualDefinitionChanges",
            "retryPendingManualDefinitionChanges",
        ):
            self.assertIn(f"function {function_name}", self.script)
        self.assertIn('/api/definitions/manual-changes', self.script)
        self.assertIn('/api/definitions/manual-changes/reset', self.script)
        self.assertIn('/api/definitions/manual-changes/retry', self.script)

    def test_trainee_has_manual_change_query_and_batch_reset_page(self):
        for token in (
            'data-nav-page="manual-changes"',
            'data-page="manual-changes"',
            'id="manualDefinitionChangesTable"',
            'id="resetSelectedManualChanges"',
            'id="retryPendingManualChanges"',
            'id="refreshManualChanges"',
        ):
            self.assertIn(token, self.trainee_html)
        for function_name in (
            "loadManualDefinitionChanges",
            "renderManualDefinitionChanges",
            "toggleManualDefinitionChange",
            "resetSelectedManualDefinitionChanges",
            "retryPendingManualDefinitionChanges",
        ):
            self.assertIn(f"function {function_name}", self.trainee_script)
        self.assertIn('/api/definitions/manual-changes', self.trainee_script)
        self.assertIn('/api/definitions/manual-changes/reset', self.trainee_script)
        self.assertIn('/api/definitions/manual-changes/retry', self.trainee_script)

    def test_simulator_device_and_measurement_saves_warn_for_partial_tracking_failure(self):
        self.assertIn("function definitionEditResultHasWarning", self.script)
        self.assertIn("Boolean(result?.warning)", self.script)
        self.assertIn("result?.change_record_persisted === false", self.script)
        for function_name in (
            "saveDiagramDeviceDefinitionEdit",
            "saveDiagramMeasurementDefinitionEdit",
        ):
            function_source = self._function_window(self.script, function_name)
            self.assertIn("definitionEditResultHasWarning(result)", function_source)
            self.assertIn("interaction.definitionMessageWarning = resultWarning", function_source)
            self.assertIn("result.warning", function_source)

    def test_trainee_device_and_measurement_saves_warn_for_partial_tracking_failure(self):
        self.assertIn("function definitionEditResultHasWarning", self.trainee_script)
        self.assertIn("Boolean(result?.warning)", self.trainee_script)
        self.assertIn("result?.change_record_persisted === false", self.trainee_script)
        for function_name in (
            "saveDiagramDeviceDefinitionEdit",
            "saveDiagramMeasurementDefinitionEdit",
        ):
            function_source = self._function_window(self.trainee_script, function_name)
            self.assertIn("definitionEditResultHasWarning(result)", function_source)
            self.assertIn("interaction.definitionMessageWarning = resultWarning", function_source)
            self.assertIn("result.warning", function_source)

    def test_simulator_retry_and_reset_results_keep_all_failure_signals_visible(self):
        helper = self._function_window(self.script, "definitionEditResultHasWarning", 500)
        self.assertIn("!result?.persisted", helper)
        self.assertIn("result?.change_record_persisted === false", helper)
        self.assertIn("Boolean(result?.warning)", helper)
        renderer = self._function_window(self.script, "renderManualDefinitionChanges", 1900)
        self.assertIn("state.manualDefinitionChangesMessageWarning", renderer)
        for function_name in (
            "retryPendingManualDefinitionChanges",
            "resetSelectedManualDefinitionChanges",
        ):
            function_source = self._function_window(self.script, function_name, 3200)
            self.assertIn("const resultWarning = definitionEditResultHasWarning(result)", function_source)
            self.assertIn(
                "state.manualDefinitionChangesMessageWarning = resultWarning",
                function_source,
            )

    def test_trainee_retry_and_reset_results_keep_all_failure_signals_visible(self):
        helper = self._function_window(self.trainee_script, "definitionEditResultHasWarning", 500)
        self.assertIn("!result?.persisted", helper)
        self.assertIn("result?.change_record_persisted === false", helper)
        self.assertIn("Boolean(result?.warning)", helper)
        renderer = self._function_window(self.trainee_script, "renderManualDefinitionChanges", 1900)
        self.assertIn("state.manualDefinitionChangesMessageWarning", renderer)
        for function_name in (
            "retryPendingManualDefinitionChanges",
            "resetSelectedManualDefinitionChanges",
        ):
            function_source = self._function_window(self.trainee_script, function_name, 3200)
            self.assertIn("const resultWarning = definitionEditResultHasWarning(result)", function_source)
            self.assertIn(
                "state.manualDefinitionChangesMessageWarning = resultWarning",
                function_source,
            )


if __name__ == "__main__":
    unittest.main()
