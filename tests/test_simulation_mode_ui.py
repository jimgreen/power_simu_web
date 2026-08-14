from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulationModeUiTest(unittest.TestCase):
    def test_global_simulation_mode_controls_all_five_curve_resolutions(self):
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="simulationModeSelector"', index_html)
        for mode, label in (
            ("hour", "时仿真"),
            ("day", "日仿真"),
            ("week", "周仿真"),
            ("month", "月仿真"),
            ("year", "年仿真"),
        ):
            self.assertIn(f'<option value="{mode}">{label}</option>', index_html)
            self.assertIn(f'data-curve-mode="{mode}"', index_html)
            self.assertIn(f'data-curve-display-mode="{mode}"', trainee_html)
        self.assertIn("loadCurvesFromSnapshot", app_js)
        self.assertIn("switchSimulationMode", app_js)
        switch_mode = app_js.split("async function switchSimulationMode", 1)[1].split(
            "function renderCurveModeControls",
            1,
        )[0]
        self.assertNotIn("saveCurves", switch_mode)
        self.assertNotIn("await refresh()", switch_mode)
        self.assertIn("curveModeHasUnsavedChanges()", switch_mode)
        self.assertIn("openCurveModeSwitchDialog(nextMode)", switch_mode)
        render_snapshot = app_js.split("function renderSnapshot", 1)[1].split(
            "function appendRuntimeLog",
            1,
        )[0]
        self.assertIn("shouldPreserveCurveDraft()", render_snapshot)
        self.assertIn("if (!preserveCurveDraft)", render_snapshot)
        self.assertIn("simulationModeSelector", app_js)
        self.assertIn('hour: { key: "hour", label: "时曲线", pointCount: 3600, stepMinutes: 1 / 60', app_js)
        self.assertIn('week: { key: "week", label: "周曲线", pointCount: 10080, stepMinutes: 1', app_js)
        self.assertIn('month: { key: "month", label: "月曲线", pointCount: 720, stepMinutes: 60', app_js)
        self.assertIn('hour: { key: "hour", label: "时仿真", pointCount: 3600, stepMinutes: 1 / 60', trainee_js)
        self.assertIn('week: { key: "week", label: "周仿真", pointCount: 10080, stepMinutes: 1', trainee_js)
        self.assertIn('month: { key: "month", label: "月仿真", pointCount: 720, stepMinutes: 60', trainee_js)

    def test_clock_ratio_selector_exposes_every_confirmed_level(self):
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")

        for ratio in (1, 5, 15, 30, 60, 300, 900, 1800, 3600):
            self.assertIn(f'<option value="{ratio}">{ratio}:1</option>', index_html)

    def test_global_mode_switch_can_update_curve_status_while_curve_page_is_detached(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function setCurveStatus", app_js)
        self.assertIn('state.pageSections?.curves?.querySelector("#curveStatus")', app_js)
        self.assertIn('setCurveStatus("已保存")', app_js)
        self.assertNotIn('$("curveStatus").textContent = "已保存"', app_js)

    def test_curve_changes_are_mode_scoped_drafts_until_the_save_button_is_clicked(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        switch_mode = app_js.split("async function switchSimulationMode", 1)[1].split(
            "function renderCurveModeControls",
            1,
        )[0]
        save_curves = app_js.split("async function saveCurves", 1)[1].split(
            "async function pushSettings",
            1,
        )[0]
        save_click = app_js.split('$("saveCurves").addEventListener', 1)[1].split(
            'document.addEventListener("click"',
            1,
        )[0]

        self.assertIn("curveDirtyKeysByMode", app_js)
        self.assertIn("curvePersistedMode", app_js)
        self.assertIn("saveCurrentCurveModeDraft", app_js)
        self.assertIn("restoreCurveModeDraft", app_js)
        self.assertNotIn('api("/api/curves/series"', switch_mode)
        self.assertIn('api("/api/curves/series"', save_curves)
        self.assertIn("saveCurves().catch", save_click)
        self.assertIn("state.curvePersistedMode = state.curveMode", save_curves)

    def test_switching_modes_prompts_before_leaving_an_unsaved_curve_draft(self):
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="curveModeSwitchDialog"', index_html)
        self.assertIn('id="saveCurveModeSwitch"', index_html)
        self.assertIn('id="discardCurveModeSwitch"', index_html)
        self.assertIn('id="cancelCurveModeSwitch"', index_html)
        self.assertIn("function openCurveModeSwitchDialog", app_js)
        self.assertIn("async function saveBeforeCurveModeSwitch", app_js)
        self.assertIn("function switchCurveModeWithoutSaving", app_js)
        self.assertIn("await saveCurves()", app_js)

    def test_typical_curve_dialog_generates_only_a_local_curve_draft(self):
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for element_id in (
            "typicalCurveDialog",
            "typicalCurveMin",
            "typicalCurveMax",
            "typicalCurveAverage",
            "typicalCurveShape",
            "confirmTypicalCurve",
        ):
            self.assertIn(f'id="{element_id}"', index_html)
        for shape in ("step", "sawtooth", "sine", "random"):
            self.assertIn(f'<option value="{shape}"', index_html)

        self.assertIn("function openTypicalCurveDialog", app_js)
        self.assertIn("function generateTypicalCurveValues", app_js)
        self.assertIn("function confirmTypicalCurveGeneration", app_js)
        self.assertIn("function curveObservedRange", app_js)
        self.assertIn("{ hour: 4, day: 4, week: 7, month: 30, year: 12 }", app_js)
        confirm_block = app_js.split("function confirmTypicalCurveGeneration", 1)[1].split(
            "function syncCurvePayload",
            1,
        )[0]
        self.assertIn("markCurveDirty(key)", confirm_block)
        self.assertIn('setCurveStatus("已生成，待保存")', confirm_block)
        self.assertNotIn("saveCurves", confirm_block)
        self.assertNotIn('/api/curves/series', confirm_block)

    def test_simulator_curve_mode_tabs_keep_one_line_on_narrow_screens(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".curve-toolbar > .curve-mode-control", styles)
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", styles)
        self.assertIn("white-space: nowrap;", styles)


if __name__ == "__main__":
    unittest.main()
