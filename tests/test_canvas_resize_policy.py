from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CanvasResizePolicyTest(unittest.TestCase):
    def test_simulator_trace_canvas_backing_store_follows_rendered_height(self):
        script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

        self.assertIn("function resizeCanvasToRenderedSize", script)
        self.assertIn(
            "height: Math.max(1, Math.round(rect.height || canvas.clientHeight || fallbackHeight))",
            script,
        )
        self.assertNotIn("Math.max(240", script)

        for function_name in ("resizeRuntimeTraceCanvas", "resizeMeasurementTraceCanvas"):
            with self.subTest(function=function_name):
                body = self._function_body(script, function_name)

                self.assertIn("return resizeCanvasToRenderedSize(canvas, 900, 260);", body)
                self.assertNotIn("Math.max(240", body)

    def test_trainee_trace_canvas_backing_store_follows_rendered_height(self):
        script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        body = self._function_body(script, "resizeCanvas")

        self.assertIn("function canvasRenderedSize", script)
        self.assertIn(
            "height: Math.max(1, Math.floor(rect.height || canvas.clientHeight || fallbackHeight))",
            script,
        )
        self.assertIn("Math.floor(renderedHeight * ratio)", body)
        self.assertNotIn("Math.max(260", script)

    @staticmethod
    def _function_body(script: str, function_name: str) -> str:
        match = re.search(
            rf"function {re.escape(function_name)}\([^)]*\) \{{(?P<body>.*?)\n\}}",
            script,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError(f"{function_name} not found")
        return match.group("body")


if __name__ == "__main__":
    unittest.main()
