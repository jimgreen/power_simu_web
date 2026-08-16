from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeLogDetailUiTest(unittest.TestCase):
    def test_simulator_and_trainee_use_summary_rows_and_detail_dialogs(self):
        for role in ("simulator", "trainee"):
            with self.subTest(role=role):
                web_dir = ROOT / "simu" / "web" / role
                html = (web_dir / "index.html").read_text(encoding="utf-8")
                script = (web_dir / "app.js").read_text(encoding="utf-8")
                styles = (web_dir / "styles.css").read_text(encoding="utf-8")

                self.assertIn('id="runtimeLogDetailDialog"', html)
                self.assertIn("function runtimeLogSummaryText", script)
                self.assertIn("function runtimeLogDetailLines", script)
                self.assertIn("function openRuntimeLogDetailDialog", script)
                self.assertIn("function closeRuntimeLogDetailDialog", script)
                self.assertIn('data-runtime-log-seq="${escapeHtml(item.seq)}"', script)
                self.assertIn('tabindex="0"', script)
                self.assertIn('event.type === "dblclick"', script)
                self.assertIn('event.key !== "Enter"', script)
                self.assertIn("<th>概要</th>", script)
                self.assertIn("white-space: nowrap", styles)
                self.assertIn("text-overflow: ellipsis", styles)


if __name__ == "__main__":
    unittest.main()
