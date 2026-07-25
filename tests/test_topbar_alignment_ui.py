from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TopbarAlignmentUiTest(unittest.TestCase):
    def test_topbar_switchers_share_the_same_horizontal_center_line(self):
        css = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".simulation-mode-switcher {", css)
        simulation_rule = css.split(".simulation-mode-switcher {", 1)[1].split("}", 1)[0]
        self.assertIn("margin: 0", simulation_rule)
        self.assertIn("height: 32px", simulation_rule)


if __name__ == "__main__":
    unittest.main()
