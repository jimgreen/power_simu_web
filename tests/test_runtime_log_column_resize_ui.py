from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeLogColumnResizeUiTest(unittest.TestCase):
    def _assert_resizable_runtime_log(self, role: str, storage_key: str) -> None:
        web_root = ROOT / "simu" / "web" / role
        script = (web_root / "app.js").read_text(encoding="utf-8")
        styles = (web_root / "styles.css").read_text(encoding="utf-8")

        self.assertIn(f'const RUNTIME_LOG_COLUMN_WIDTHS_KEY = "{storage_key}";', script)
        self.assertIn("function runtimeLogColgroupHtml()", script)
        self.assertIn('<table class="runtime-log-table runtime-log-table-resizable">', script)
        self.assertIn("function enableRuntimeLogColumnResizing(table)", script)
        self.assertIn('handle.className = "table-column-resize-handle";', script)
        self.assertIn('handle.addEventListener("pointerdown"', script)
        self.assertIn('window.addEventListener("pointermove", move);', script)
        self.assertIn('handle.addEventListener("dblclick"', script)
        self.assertIn('handle.addEventListener("keydown"', script)
        self.assertIn('localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY', script)

        self.assertIn(".runtime-log-table.runtime-log-table-resizable th:nth-child(n)", styles)
        self.assertIn(".table-column-resize-handle", styles)
        self.assertIn("cursor: col-resize;", styles)
        self.assertIn("touch-action: none;", styles)

    def test_simulator_runtime_log_columns_are_mouse_resizable(self):
        self._assert_resizable_runtime_log(
            "simulator",
            "polarSimulatorRuntimeLogColumnWidths",
        )

    def test_trainee_runtime_log_columns_are_mouse_resizable(self):
        self._assert_resizable_runtime_log(
            "trainee",
            "polarTraineeRuntimeLogColumnWidths",
        )


if __name__ == "__main__":
    unittest.main()
