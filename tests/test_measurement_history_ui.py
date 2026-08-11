from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MeasurementHistoryUiTest(unittest.TestCase):
    def test_simulator_bootstraps_selected_measurement_history_from_backend(self):
        source = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("async function ensureMeasurementHistoryForRow", source)
        self.assertIn("/api/measurement-history?indices=", source)
        self.assertIn("mergeMeasurementHistoryPayload", source)
        self.assertIn("ensureSelectedMeasurementHistory();", source)
        self.assertIn("resetMeasurementHistoryHydration();", source)

    def test_trainee_bootstraps_received_history_from_local_exchange_backend(self):
        source = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn("async function ensureMeasurementHistoryForRow", source)
        self.assertIn("/api/trainee/measurement-history?indices=", source)
        self.assertIn("mergeMeasurementHistoryPayload", source)
        self.assertIn("ensureSelectedMeasurementHistory();", source)
        self.assertIn("resetMeasurementHistoryHydration();", source)

    def test_trainee_clears_and_persists_local_history_before_enabling_receive(self):
        source = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        start_receive = "async function startReceiveMode" + source.split(
            "async function startReceiveMode",
            1,
        )[1].split("\nasync function ", 1)[0]

        clear_trace = start_receive.index("state.measurementTraceHistory = [];")
        reset_hydration = start_receive.index("resetMeasurementHistoryHydration();")
        persist_cleared_context = start_receive.index("persistActiveModelContext({}, true);")
        redraw_measurement_history = start_receive.index("drawMeasurementTraceChart();")
        redraw_command_history = start_receive.index("drawCommandTraceChart();")
        redraw_renewable_history = start_receive.index("drawRenewableTrendChart();")
        enable_receive = start_receive.index(
            "await setTraineeReceiveActive(activeModelIdBeforeReceive, true);"
        )
        self.assertLess(clear_trace, reset_hydration)
        self.assertLess(reset_hydration, persist_cleared_context)
        self.assertLess(persist_cleared_context, redraw_measurement_history)
        self.assertLess(redraw_measurement_history, redraw_command_history)
        self.assertLess(redraw_command_history, redraw_renewable_history)
        self.assertLess(redraw_renewable_history, enable_receive)

    def test_history_hydration_is_definition_and_lifecycle_checked_before_merging(self):
        for role in ("simulator", "trainee"):
            with self.subTest(role=role):
                source = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
                merge_source = "function mergeMeasurementHistoryPayload" + source.split(
                    "function mergeMeasurementHistoryPayload",
                    1,
                )[1].split("\nfunction ", 1)[0]
                self.assertIn("measurementDefinitionSignature(definitions)", merge_source)
                self.assertIn("payload.definition_signature", merge_source)
                self.assertIn("payload.count", merge_source)
                self.assertIn("payload.run_id", merge_source)
                self.assertIn("frame.real_values", merge_source)
                self.assertIn("frame.scada_values", merge_source)
                self.assertIn("frame.valid_values", merge_source)

    def test_svg_measurement_tooltip_requests_history_for_the_hovered_measurement(self):
        for role in ("simulator", "trainee"):
            with self.subTest(role=role):
                source = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
                self.assertIn("ensureDiagramMetricMeasurementHistory", source)
                self.assertIn("ensureMeasurementHistoryForRow(row)", source)


if __name__ == "__main__":
    unittest.main()
