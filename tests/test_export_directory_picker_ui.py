from __future__ import annotations

import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExportDirectoryPickerUiTest(unittest.TestCase):
    def test_definition_export_uses_directory_picker_with_download_fallback(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")

        self.assertIn("window.showDirectoryPicker", app_js)
        self.assertIn("directoryHandle.getFileHandle", app_js)
        self.assertIn("fileHandle.createWritable", app_js)
        self.assertIn("downloadBlob", app_js)
        self.assertIn("请选择定义导出目录", index_html)
        picker_id_match = re.search(r'id:\s*"([^"]+)"', app_js)
        self.assertIsNotNone(picker_id_match)
        self.assertLessEqual(len(picker_id_match.group(1)), 32)


if __name__ == "__main__":
    unittest.main()
