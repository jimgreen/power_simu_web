import json
import re
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableTopologyUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_strategy_tabs_are_topology_aware_eleven_category_tabs(self):
        expected_tabs = {
            "ac-wind": "交流风电",
            "dc-wind": "直流风电",
            "ac-pv": "交流光伏",
            "dc-pv": "直流光伏",
            "ac-grid-storage": "交流跟网储能",
            "dc-grid-storage": "直流跟网储能",
            "ac-balance-storage": "交流平衡储能",
            "dc-balance-storage": "直流平衡储能",
            "diesel": "柴发",
            "converter": "ACDC变流",
            "hydrogen": "氢能",
        }
        for key, label in expected_tabs.items():
            self.assertIn(f'data-renewable-strategy-tab="{key}"', self.html)
            self.assertIn(f'>{label}</button>', self.html)
        for old_key in ("wind", "pv", "storage"):
            self.assertNotIn(f'data-renewable-strategy-tab="{old_key}"', self.html)

    def test_strategy_table_keeps_operational_columns_and_removes_topology_details(self):
        render_block = self.script.split("function renderRenewableControl(snapshot", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        for heading in (
            "设备名称",
            "遥调/遥控点名称",
            "接入状态",
            "当前值",
            "可用边界",
            "目标值",
            "SOC",
            "执行",
        ):
            self.assertIn(f"<th>{heading}</th>", render_block)
        for heading in (
            "并网侧",
            "接入母线",
            "传输组",
            "接入路径",
            "拓扑状态",
            "间接调节设备",
        ):
            self.assertNotIn(f"<th>{heading}</th>", render_block)

    def test_strategy_tab_mapping_is_exact_and_defaults_to_ac_wind(self):
        expected_mapping = textwrap.dedent(
            '''\
            const RENEWABLE_STRATEGY_TABS = {
              "ac-wind": { label: "交流风电", categories: new Set(["交流风电"]) },
              "dc-wind": { label: "直流风电", categories: new Set(["直流风电"]) },
              "ac-pv": { label: "交流光伏", categories: new Set(["交流光伏"]) },
              "dc-pv": { label: "直流光伏", categories: new Set(["直流光伏"]) },
              "ac-grid-storage": { label: "交流跟网储能", categories: new Set(["交流跟网储能"]) },
              "dc-grid-storage": { label: "直流跟网储能", categories: new Set(["直流跟网储能"]) },
              "ac-balance-storage": { label: "交流平衡储能", categories: new Set(["交流平衡储能"]) },
              "dc-balance-storage": { label: "直流平衡储能", categories: new Set(["直流平衡储能"]) },
              diesel: { label: "柴发", categories: new Set(["柴油发电"]) },
              converter: { label: "ACDC变流", categories: new Set(["交直流变流器"]) },
              hydrogen: { label: "氢能", categories: new Set(["氢能"]) },
            };
            '''
        )
        self.assertIn(expected_mapping, self.script)
        self.assertIn('strategyTab: "ac-wind"', self.script)
        self.assertNotIn('strategyTab: "wind"', self.script)

    def test_strategy_rows_filter_by_backend_category_only(self):
        mapping_match = re.search(
            r"const RENEWABLE_STRATEGY_TABS = \{.*?\n\};",
            self.script,
            re.DOTALL,
        )
        function_match = re.search(
            r"function renewableStrategyRows\(plan, tabKey = state\.renewableControl\.strategyTab\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(mapping_match)
        self.assertIsNotNone(function_match)
        node_script = f"""
const state = {{ renewableControl: {{ strategyTab: "ac-wind" }} }};
{mapping_match.group(0)}
{function_match.group(0)}
const plan = {{
  commandRows: [
    {{ dev_name: "DC风机", category: "交流风电", nativeType: "DCWindGen", parameterBlock: "DCWindGen" }},
    {{ dev_name: "AC风机", category: "直流风电", nativeType: "ACWindGen", parameterBlock: "ACWindGen" }},
    {{ dev_name: "AC跟网", category: "交流跟网储能" }},
    {{ dev_name: "DC平衡", category: "直流平衡储能" }},
    {{ dev_name: "交流电制氢", category: "氢能" }},
    {{ dev_name: "直流燃料电池", category: "氢能" }},
    {{ dev_name: "未知诊断", category: "UNRESOLVED" }},
  ],
}};
const result = {{
  acWind: renewableStrategyRows(plan, "ac-wind").map((row) => row.dev_name),
  dcWind: renewableStrategyRows(plan, "dc-wind").map((row) => row.dev_name),
  acGridStorage: renewableStrategyRows(plan, "ac-grid-storage").map((row) => row.dev_name),
  dcBalanceStorage: renewableStrategyRows(plan, "dc-balance-storage").map((row) => row.dev_name),
  hydrogen: renewableStrategyRows(plan, "hydrogen").map((row) => row.dev_name),
  fallback: renewableStrategyRows(plan, "not-a-tab").map((row) => row.dev_name),
}};
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "acWind": ["DC风机"],
                "dcWind": ["AC风机"],
                "acGridStorage": ["AC跟网"],
                "dcBalanceStorage": ["DC平衡"],
                "hydrogen": ["交流电制氢", "直流燃料电池"],
                "fallback": ["DC风机"],
            },
        )

    def test_strategy_tab_visible_labels_remain_exact_after_runtime_counts(self):
        mapping_match = re.search(
            r"const RENEWABLE_STRATEGY_TABS = \{.*?\n\};",
            self.script,
            re.DOTALL,
        )
        rows_match = re.search(
            r"function renewableStrategyRows\(plan, tabKey = state\.renewableControl\.strategyTab\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        render_block = self.script.split("function renderRenewableStrategyTabs", 1)[1].split(
            "function renewableControlLogs",
            1,
        )[0]
        self.assertIsNotNone(mapping_match)
        self.assertIsNotNone(rows_match)
        node_script = f"""
const state = {{ renewableControl: {{ strategyTab: "ac-wind" }} }};
{mapping_match.group(0)}
{rows_match.group(0)}
function renderRenewableStrategyTabs{render_block}
const buttons = Object.entries(RENEWABLE_STRATEGY_TABS).map(([key]) => ({{
  dataset: {{ renewableStrategyTab: key }},
  textContent: "",
  title: "",
  tabIndex: null,
  attrs: {{}},
  classList: {{
    values: new Set(),
    toggle(name, active) {{
      if (active) this.values.add(name);
      else this.values.delete(name);
    }},
  }},
  setAttribute(name, value) {{ this.attrs[name] = String(value); }},
}}));
const document = {{
  querySelectorAll(selector) {{
    if (selector !== "[data-renewable-strategy-tab]") throw new Error(selector);
    return buttons;
  }},
}};
const plan = {{
  commandRows: [
    {{ category: "交流风电" }},
    {{ category: "交流风电" }},
    {{ category: "直流风电" }},
    {{ category: "交流跟网储能" }},
    {{ category: "直流平衡储能" }},
    {{ category: "柴油发电" }},
  ],
}};
renderRenewableStrategyTabs(plan);
const result = buttons.map((button) => {{
  const key = button.dataset.renewableStrategyTab;
  const expectedCount = renewableStrategyRows(plan, key).length;
  return {{
    key,
    label: RENEWABLE_STRATEGY_TABS[key].label,
    textContent: button.textContent,
    title: button.title,
    ariaLabel: button.attrs["aria-label"] || "",
    expectedCount,
  }};
}});
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        rendered = json.loads(completed.stdout)
        for button in rendered:
            self.assertEqual(button["textContent"], button["label"], button)
            self.assertNotIn(str(button["expectedCount"]), button["textContent"], button)
            count_metadata = f'{button["title"]} {button["ariaLabel"]}'
            self.assertIn(str(button["expectedCount"]), count_metadata, button)

    def test_unresolved_rows_have_no_diagnostic_panel_and_hydrogen_has_its_own_tab(self):
        self.assertNotIn('id="renewableStrategyDiagnostics"', self.html)
        self.assertNotIn('data-renewable-strategy-tab="diagnostic"', self.html)
        self.assertIn('data-renewable-strategy-tab="hydrogen"', self.html)
        self.assertNotIn("function renewableStrategyDiagnosticRows", self.script)
        self.assertNotIn("function renderRenewableStrategyDiagnostics", self.script)
        self.assertNotIn("renewable-strategy-diagnostics", self.styles)
        mapping_match = re.search(
            r"const RENEWABLE_STRATEGY_TABS = \{.*?\n\};",
            self.script,
            re.DOTALL,
        )
        rows_match = re.search(
            r"function renewableStrategyRows\(plan, tabKey = state\.renewableControl\.strategyTab\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(mapping_match)
        self.assertIsNotNone(rows_match)
        node_script = f"""
const state = {{ renewableControl: {{ strategyTab: "ac-wind" }} }};
{mapping_match.group(0)}
{rows_match.group(0)}
const plan = {{
  commandRows: [
    {{ dev_name: "bad-wind", category: "拓扑未解析新能源", topologyStatusLabel: "资源模型引用或端子无效", online: false, commandable: false }},
    {{ dev_name: "<bad-storage>", category: "拓扑未解析储能", topologyStatusLabel: "UNRESOLVED <bus>", resourceIdentityDiagnostic: "missing-model-reference", online: false, commandable: false }},
    {{ dev_name: "ok-wind", category: "交流风电", topologyStatusLabel: "拓扑正常", online: true, commandable: true }},
    {{ dev_name: "electrolyzer", category: "氢能", online: true, commandable: true }},
    {{ dev_name: "fuel-cell", category: "氢能", online: true, commandable: true }},
  ],
}};
const tabCounts = Object.keys(RENEWABLE_STRATEGY_TABS).map((key) => renewableStrategyRows(plan, key).length);
process.stdout.write(JSON.stringify({{
  tabCounts,
  hydrogen: renewableStrategyRows(plan, "hydrogen").map((row) => row.dev_name),
}}));
"""
        completed = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        result = json.loads(completed.stdout)
        self.assertEqual(sum(result["tabCounts"]), 3)
        self.assertEqual(result["hydrogen"], ["electrolyzer", "fuel-cell"])

    def test_reset_renewable_control_view_returns_strategy_tab_to_ac_wind(self):
        mapping_match = re.search(
            r"const RENEWABLE_STRATEGY_TABS = \{.*?\n\};",
            self.script,
            re.DOTALL,
        )
        rows_match = re.search(
            r"function renewableStrategyRows\(plan, tabKey = state\.renewableControl\.strategyTab\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        render_block = self.script.split("function renderRenewableStrategyTabs", 1)[1].split(
            "function renewableControlLogs",
            1,
        )[0]
        reset_match = re.search(
            r"function resetRenewableControlView\(modelId = state\.activeModelId\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(mapping_match)
        self.assertIsNotNone(rows_match)
        self.assertIsNotNone(reset_match)
        node_script = f"""
const state = {{
  activeModelId: "model-b",
  renewableControl: {{ strategyTab: "converter" }},
  renewableTrendHistory: [{{ minute: 1 }}],
}};
function closeRenewableControlLogDetailDialog() {{}}
{mapping_match.group(0)}
{rows_match.group(0)}
function renderRenewableStrategyTabs{render_block}
{reset_match.group(0)}
const buttons = Object.entries(RENEWABLE_STRATEGY_TABS).map(([key]) => ({{
  dataset: {{ renewableStrategyTab: key }},
  textContent: "",
  title: "",
  tabIndex: null,
  attrs: {{}},
  classList: {{
    values: new Set(),
    toggle(name, active) {{
      if (active) this.values.add(name);
      else this.values.delete(name);
    }},
  }},
  setAttribute(name, value) {{ this.attrs[name] = String(value); }},
}}));
const document = {{
  querySelectorAll(selector) {{
    if (selector !== "[data-renewable-strategy-tab]") throw new Error(selector);
    return buttons;
  }},
}};
resetRenewableControlView("model-b");
renderRenewableStrategyTabs({{ commandRows: [{{ category: "交流风电" }}] }});
process.stdout.write(JSON.stringify({{
  strategyTab: state.renewableControl.strategyTab,
  activeTabs: buttons
    .filter((button) => button.classList.values.has("is-active"))
    .map((button) => button.dataset.renewableStrategyTab),
  acWindText: buttons.find((button) => button.dataset.renewableStrategyTab === "ac-wind").textContent,
  converterSelected: buttons.find((button) => button.dataset.renewableStrategyTab === "converter").attrs["aria-selected"],
}}));
"""
        completed = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["strategyTab"], "ac-wind")
        self.assertEqual(result["activeTabs"], ["ac-wind"])
        self.assertEqual(result["acWindText"], "交流风电")
        self.assertEqual(result["converterSelected"], "false")

    def test_strategy_rendering_uses_only_backend_operational_fields(self):
        render_block = self.script.split("function renderRenewableControl(snapshot", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        for token in (
            "row.connectionStatusLabel",
            "projectedTargetKw",
            "targetKw",
            "currentKw",
            "当前断开",
        ):
            self.assertIn(token, render_block)
        for token in (
            "row.gridSide",
            "row.bus",
            "row.transferGroup",
            "row.converterPath",
            "row.topologyStatusLabel",
            "row.indirectControlDevices",
        ):
            self.assertNotIn(token, render_block)
        self.assertNotIn('data-renewable-strategy-tab="diagnostic"', self.html)

    def test_balance_storage_has_no_enabled_direct_command_action(self):
        render_block = self.script.split("function renderRenewableControl(snapshot", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn('row.category.includes("平衡储能")', render_block)
        self.assertIn("row.commandable === false", render_block)
        self.assertIn("disabled", render_block)
        self.assertNotIn('row.category === "储能平衡源"', render_block)

    def test_storage_soc_reads_ac_and_dc_linked_devices_with_exact_keys(self):
        match = re.search(
            r"function storageSocRatiosByDevice\(snapshot\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertIn('"ACStorageGen"', match.group(0))
        self.assertIn('"DCStorageGen"', match.group(0))
        self.assertIn('`ACGenerator|${name}`', match.group(0))
        self.assertIn('`DCGenerator|${name}`', match.group(0))
        self.assertNotIn("name.includes", match.group(0))
        self.assertNotIn("startsWith", match.group(0))
        node_script = f"""
function liveStorageSocRatio(value, fallback = null) {{
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}}
function deviceType(dev) {{ return dev?.dev_type || dev?.devType || ""; }}
function deviceName(dev) {{ return dev?.dev_name || dev?.devName || dev?.name || ""; }}
function parameterName(param) {{ return param?.dev_name || param?.name || ""; }}
function parameterRows(snapshot, type) {{
  return (snapshot.parameters?.[type] || snapshot.parameterRows?.[type] || []).slice();
}}
function indexedDevice(snapshot, type, index) {{
  return (snapshot.devices || []).find((dev) => deviceType(dev) === type && Number(dev.idx) === Number(index));
}}
function measurementValuesByDevice() {{ return new Map(); }}
{match.group(0)}
const snapshot = {{
  devices: [
    {{ dev_type: "ACGenerator", dev_name: "储能A", idx: 1, soc_curr: 0.31 }},
    {{ dev_type: "DCGenerator", dev_name: "储能A", idx: 1, soc_curr: 0.74 }},
  ],
  parameters: {{
    ACStorageGen: [{{ idx_acgenerator: 1 }}],
    DCStorageGen: [{{ idx_dcgenerator: 1 }}],
  }},
}};
process.stdout.write(JSON.stringify([...storageSocRatiosByDevice(snapshot).entries()]));
"""
        completed = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        self.assertEqual(
            json.loads(completed.stdout),
            [["ACGenerator|储能A", 0.31], ["DCGenerator|储能A", 0.74]],
        )

    def test_storage_soc_tolerates_linked_parameter_without_runtime_device(self):
        storage_match = re.search(
            r"function storageSocRatiosByDevice\(snapshot\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        device_name_match = re.search(
            r"function deviceName\(dev\) \{.*?\n\}",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(storage_match)
        self.assertIsNotNone(device_name_match)
        node_script = f"""
function liveStorageSocRatio(value, fallback = null) {{
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}}
{device_name_match.group(0)}
function deviceType(dev) {{ return dev?.dev_type || dev?.devType || ""; }}
function parameterName(param) {{ return param?.dev_name || param?.name || ""; }}
function parameterRows(snapshot, type) {{ return (snapshot.parameters?.[type] || []).slice(); }}
function indexedDevice() {{ return null; }}
function measurementValuesByDevice() {{ return new Map(); }}
{storage_match.group(0)}
const snapshot = {{
  devices: [],
  parameters: {{
    ACStorageGen: [{{ idx_acgenerator: 1 }}],
    DCStorageGen: [{{ idx_dcgenerator: 2 }}],
  }},
}};
process.stdout.write(JSON.stringify([...storageSocRatiosByDevice(snapshot).entries()]));
"""
        completed = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), [])

    def test_responsive_strategy_layout_is_single_row_scrollable_and_stable(self):
        tabs_block = self.styles.split(".renewable-strategy-tabs {", 1)[1].split("}", 1)[0]
        button_block = self.styles.split(".renewable-strategy-tabs button {", 1)[1].split("}", 1)[0]
        table_block = self.styles.split(".renewable-command-table {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap: nowrap;", tabs_block)
        self.assertIn("overflow-x: auto;", tabs_block)
        self.assertIn("white-space: nowrap;", tabs_block)
        self.assertIn("width: 118px;", button_block)
        self.assertIn("overflow: hidden;", button_block)
        self.assertIn("text-overflow: ellipsis;", button_block)
        self.assertIn("min-width: 1020px;", table_block)
        self.assertIn("table-layout: fixed;", table_block)
        self.assertIn(".renewable-topology-text", self.styles)


if __name__ == "__main__":
    unittest.main()
