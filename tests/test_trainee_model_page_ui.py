import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeModelPageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    def test_trainee_navigation_exposes_grid_model_page(self):
        self.assertIn('data-nav-page="model"', self.html)
        self.assertIn('data-page="model"', self.html)
        self.assertIn('id="modelDeviceTree"', self.html)
        self.assertIn('id="modelParamTable"', self.html)

    def test_grid_model_page_has_tree_filters_and_type_tabs(self):
        self.assertIn("modelFilter:", self.script)
        self.assertIn("activeModelParamTab:", self.script)
        self.assertIn("function renderTraineeModelPage", self.script)
        self.assertIn("data-model-tree-type", self.script)
        self.assertIn("data-model-param-tab", self.script)

    def test_model_parameter_table_starts_with_index_and_name(self):
        self.assertIn('const fixed = ["idx", "name"]', self.script)
        self.assertIn('key === "name" ? "名称" : key', self.script)
        self.assertIn('new Set([...fixed, "dev_type", "dev_name", "__headers"])', self.script)

    def test_model_tree_records_keep_their_definition_block_for_grouping(self):
        builder = self.script.split("function definedModelDevices", 1)[1].split(
            "function formatModelParamValue",
            1,
        )[0]

        self.assertIn("model_block: blockName", builder)
        self.assertIn("dev_type: blockName", builder)


if __name__ == "__main__":
    unittest.main()
