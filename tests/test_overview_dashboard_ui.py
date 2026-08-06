from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverviewDashboardUiTest(unittest.TestCase):
    def test_overview_event_panel_shows_up_to_eight_rows(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        renderer = app_js.split("function renderOverviewEvents(snapshot) {", 1)[1].split(
            "function activeRuntimeCommandKeySet",
            1,
        )[0]

        self.assertIn(".slice(0, 8)", renderer)
        self.assertNotIn(".slice(0, 3)", renderer)

    def test_overview_event_panel_scrolls_inside_its_existing_height(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        event_list_block = styles.split(".overview-event-list {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow-x: hidden;", event_list_block)
        self.assertIn("overflow-y: auto;", event_list_block)
        self.assertIn("scrollbar-gutter: stable;", event_list_block)
        self.assertNotIn("overflow: hidden;", event_list_block)

    def test_overview_status_strip_keeps_content_vertically_centered(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        generic_panel_index = styles.index(".panel {")
        override_selector = ".panel.overview-status-panel {"
        self.assertIn(override_selector, styles)
        self.assertGreater(styles.index(override_selector), generic_panel_index)
        status_block = styles.split(override_selector, 1)[1].split("}", 1)[0]
        self.assertIn("padding: 0", status_block)
        self.assertIn("align-items: stretch", status_block)

    def test_overview_merges_realtime_results_into_energy_flow(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for text in ("输入边界", "当前控制指令", "最新运行事件"):
            self.assertIn(text, html)
        self.assertNotIn("电气能量流", html)
        self.assertNotIn("尚无计算结果", html)
        self.assertNotIn("功率差额", html)
        self.assertNotIn("energy-board-head", html)
        self.assertNotIn("energy-board-meta", html)
        self.assertNotIn("仿真流程", html)
        self.assertNotIn("功率平衡与仿真结果", html)
        self.assertNotIn("计算质量", html)
        self.assertNotIn("overview-result-panel", html)
        self.assertIn('id="overviewActiveCommandTable"', html)
        self.assertIn("renderOverviewActiveCommands", app_js)
        self.assertIn("overviewActiveRuntimeCommandRows", app_js)
        self.assertIn("activeRuntimeCommandKeySet", app_js)
        self.assertIn("commandTimeInfoAvailable(row.receive_time)", app_js)
        command_table = app_js.split("function renderOverviewActiveCommands", 1)[1].split(
            "function renderOverviewDashboard",
            1,
        )[0]
        self.assertIn("<th>本机时刻</th>\n          <th>设备</th>", command_table)
        self.assertIn("<th>仿真时刻</th>", command_table)
        self.assertNotIn("<th>类型</th>", command_table)
        self.assertNotIn("接收本机时刻", command_table)
        self.assertNotIn("接收仿真时刻", command_table)
        self.assertNotIn("row.category", command_table)
        self.assertIn(
            '<td class="mono-cell">${escapeHtml(row.receive_time?.wall_time || "--")}</td>\n'
            '            <td>${escapeHtml(row.device?.dev_name || "--")}</td>',
            command_table,
        )
        for element_id in ("overviewFlowGreenPower", "overviewFlowGreenShare"):
            self.assertIn(f'id="{element_id}"', html)
            self.assertIn(f'"{element_id}"', app_js)
        for group_key, label in (
            ("dcWind", "直流并网风电"),
            ("dcSolar", "直流并网光伏"),
            ("dcGridFollowingStorage", "直流跟网储能"),
            ("dcGridFormingStorage", "直流构网储能"),
            ("acGridFormingStorage", "交流构网储能"),
            ("acdcConverter", "AC/DC变流器"),
            ("acWind", "交流并网风电"),
            ("acSolar", "交流并网光伏"),
            ("acGridFollowingStorage", "交流跟网储能"),
            ("dcLoad", "直流负荷"),
            ("acLoad", "交流负荷"),
            ("diesel", "柴油发电"),
        ):
            self.assertIn(f'data-overview-group="{group_key}"', html)
            self.assertIn(label, html)
        self.assertNotIn('data-overview-group="load"', html)
        dc_region = html.split('data-overview-region="dc"', 1)[1].split("</section>", 1)[0]
        ac_region = html.split('data-overview-region="ac"', 1)[1].split("</section>", 1)[0]
        self.assertIn('data-overview-group="dcLoad"', dc_region)
        self.assertNotIn('data-overview-group="acLoad"', dc_region)
        self.assertIn('data-overview-group="acLoad"', ac_region)
        self.assertNotIn('data-overview-group="dcLoad"', ac_region)
        self.assertIn('<article class="energy-green-share"', html)
        green_summary = html.split('<article class="energy-green-share"', 1)[1].split("</article>", 1)[0]
        self.assertIn("绿电功率", green_summary)
        self.assertIn("绿电占比", green_summary)
        self.assertIn('id="overviewFlowGreenPower"', green_summary)
        self.assertIn('id="overviewFlowGreenShare"', green_summary)
        for group_key, label in (("dcLoad", "直流负荷"), ("acLoad", "交流负荷")):
            load_card = html.split(f'data-overview-group="{group_key}"', 1)[1].split("</article>", 1)[0]
            self.assertIn(f"<span>{label}</span>", load_card)
            self.assertNotIn('class="energy-device-heading"', load_card)
            self.assertNotIn("绿电功率", load_card)
            self.assertNotIn("绿电占比", load_card)
            self.assertNotIn('id="overviewFlowGreenPower"', load_card)
            self.assertNotIn('id="overviewFlowGreenShare"', load_card)
        for element_id in ("overviewFlowGreenPower", "overviewFlowGreenShare"):
            self.assertEqual(html.count(f'id="{element_id}"'), 1)
        for removed_id in ("overviewFlowBalance", "overviewFlowResultTime"):
            self.assertNotIn(f'id="{removed_id}"', html)
            self.assertNotIn(f'"{removed_id}"', app_js)
        for removed_id in (
            "overviewMeasurementQuality",
            "overviewSolverDetail",
            "overviewUpdatedMeasurements",
            "overviewMissingMeasurements",
            "overviewOverlayUpdates",
        ):
            self.assertNotIn(f'id="{removed_id}"', html)
        for removed_id in (
            "overviewWindPower",
            "overviewSolarPower",
            "overviewDieselPower",
            "overviewStoragePower",
            "overviewLoadPower",
            "overviewPowerBalance",
            "overviewSoc",
            "overviewResultTime",
        ):
            self.assertNotIn(f'id="{removed_id}"', html)
        self.assertIn("renderOverviewDashboard", app_js)
        self.assertIn("parsePowerFlowOverview", app_js)

    def test_overview_wind_solar_and_storage_arrows_share_green_color(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        green_groups = (
            "dcWind",
            "dcSolar",
            "dcGridFollowingStorage",
            "dcGridFormingStorage",
            "acGridFormingStorage",
            "acWind",
            "acSolar",
            "acGridFollowingStorage",
        )

        for group_key in green_groups:
            definition = next(line for line in app_js.splitlines() if f'key: "{group_key}"' in line)
            self.assertIn('color: "#2f9e62"', definition)
        self.assertIn('definition.category === "load"', app_js)
        self.assertIn("acLoad: { power: power.load }", app_js)
        self.assertIn("source.load", app_js)

    def test_overview_uses_real_equipment_icons_and_separate_information_cards(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        overview = html.split('<div class="energy-flow-map"', 1)[1].split("</section>", 1)[0]

        for icon_id in (
            "energy-icon-wind-turbine",
            "energy-icon-solar-array",
            "energy-icon-battery-storage",
            "energy-icon-electric-load",
            "energy-icon-diesel-generator",
            "energy-icon-acdc-converter",
        ):
            self.assertIn(f'id="{icon_id}"', html)

        expected_icons = {
            "dcWind": "wind-turbine",
            "dcSolar": "solar-array",
            "dcGridFollowingStorage": "battery-storage",
            "dcLoad": "electric-load",
            "dcGridFormingStorage": "battery-storage",
            "acGridFormingStorage": "battery-storage",
            "acWind": "wind-turbine",
            "acSolar": "solar-array",
            "acGridFollowingStorage": "battery-storage",
            "acLoad": "electric-load",
            "diesel": "diesel-generator",
        }
        for group_key, icon_name in expected_icons.items():
            group_html = html.split(f'data-overview-group="{group_key}"', 1)[1].split("</article>", 1)[0]
            self.assertIn('class="energy-device-card"', group_html)
            self.assertIn('class="energy-device-icon"', group_html)
            self.assertIn(f'href="#energy-icon-{icon_name}"', group_html)
            self.assertEqual(group_html.count("data-overview-power"), 1)
            self.assertEqual(group_html.count("data-overview-meta"), 1)

        converter = html.split('data-overview-group="acdcConverter"', 1)[1].split("</article>", 1)[0]
        self.assertIn('class="energy-device-icon energy-converter-icon"', converter)
        self.assertIn('href="#energy-icon-acdc-converter"', converter)
        self.assertIn('class="energy-device-card energy-converter-card"', converter)
        self.assertLess(converter.index("energy-converter-icon"), converter.index("energy-converter-card"))
        self.assertEqual(converter.count("data-overview-power"), 1)
        self.assertEqual(converter.count("data-overview-meta"), 1)

        for obsolete_badge in (">风<", ">光<", ">储<", ">荷<", ">柴<", ">AC/DC<"):
            self.assertNotIn(obsolete_badge, overview)

    def test_overview_icons_own_flow_connectors_and_keep_state_responsive_rules(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        left_block = styles.split('.energy-side-node[data-flow-side="left"] {', 1)[1].split("}", 1)[0]
        right_block = styles.split('.energy-side-node[data-flow-side="right"] {', 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: minmax(0, 1fr) 42px;", left_block)
        self.assertIn("grid-template-columns: 42px minmax(0, 1fr);", right_block)
        self.assertIn(".energy-device-card {", styles)
        self.assertIn(".energy-device-icon {", styles)
        self.assertIn(".energy-side-node .energy-device-icon::before", styles)
        self.assertIn(".energy-side-node .energy-device-icon::after", styles)
        self.assertIn('.energy-side-node[data-flow-active="false"] .energy-device-icon::before', styles)
        self.assertNotIn(".energy-side-node::before", styles)
        self.assertNotIn(".energy-side-node::after", styles)
        self.assertIn(
            '[data-overview-group-wrapper="dcGridFormingStorage"] .energy-device.storage',
            styles,
        )
        self.assertIn(
            '[data-overview-group-wrapper="acGridFormingStorage"] .energy-device.storage',
            styles,
        )
        self.assertIn('.energy-device[data-operating-state="retired"] .energy-device-icon', styles)
        self.assertIn('.energy-device[data-operating-state="deadIsland"] .energy-device-card', styles)
        self.assertIn('.energy-device[data-operating-state="unmeasured"] .energy-device-icon', styles)
        self.assertIn(".energy-converter-icon {", styles)
        self.assertIn(".energy-converter-card {", styles)

        compact_styles = styles.split("@container (max-width: 760px) {", 1)[1].split(
            "@container (max-height: 220px)",
            1,
        )[0]
        self.assertIn(".energy-side-node .energy-device-icon::before", compact_styles)
        self.assertIn(".energy-side-node .energy-device-icon::after", compact_styles)
        self.assertIn("display: none;", compact_styles)

        renderer = app_js.split("function renderOverviewFlowGroups(power) {", 1)[1].split(
            "function renderEnergyFlowVisuals",
            1,
        )[0]
        self.assertNotIn("innerHTML", renderer)
        self.assertIn('node.querySelector("[data-overview-power]")', renderer)
        self.assertIn('node.querySelector("[data-overview-meta]")', renderer)

    def test_overview_grid_following_storage_keeps_bus_connector_and_buses_share_extended_height(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn(
            ".energy-device.storage::after,\n.energy-device.storage::before {",
            styles,
        )
        self.assertIn(
            ".energy-storage-branch-wrap .energy-device.storage::after,\n"
            ".energy-storage-branch-wrap .energy-device.storage::before {",
            styles,
        )
        left_bus_block = styles.split(".energy-bus-rail.left {", 1)[1].split("}", 1)[0]
        right_bus_block = styles.split(".energy-bus-rail.right {", 1)[1].split("}", 1)[0]
        low_height_styles = styles.split("@media (max-height: 780px) and (min-width: 821px) {", 1)[1].split(
            "@media (max-width: 820px) {",
            1,
        )[0]

        self.assertIn("height: calc(100% - 24px);", left_bus_block)
        self.assertIn("height: calc(100% - 24px);", right_bus_block)
        self.assertNotIn("height: 156px;", low_height_styles)

    def test_overview_prefers_signed_structured_realtime_power_summary(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        parser = app_js.split("function parsePowerFlowOverview(snapshot) {", 1)[1].split(
            "function overviewCurveBoundary",
            1,
        )[0]

        self.assertIn("snapshot.power_summary", parser)
        self.assertIn("powerSummaryNumber", parser)
        self.assertIn('source: String(summary.source || "")', parser)
        self.assertIn('wind: powerSummaryNumber(summary.wind)', parser)
        self.assertIn('storage: powerSummaryNumber(summary.storage)', parser)
        self.assertIn('greenPower: powerSummaryNumber(summary.greenPower)', parser)
        self.assertIn("normalizeOverviewFlowGroups(summary.flowGroups", parser)
        self.assertIn('const log = latestRuntimeLog(snapshot, "潮流计算")', parser)
        self.assertNotIn("Math.abs", parser)
        self.assertNotIn("Math.max", parser)
        self.assertNotIn("Math.min", parser)

        renderer = app_js.split("function renderOverviewDashboard(snapshot) {", 1)[1].split(
            "function renderActiveSimulatorPage",
            1,
        )[0]
        self.assertIn("renderOverviewFlowGroups(power)", renderer)
        self.assertIn("const greenPower = Number.isFinite(power.greenPower) ? -power.greenPower : null;", renderer)
        self.assertIn('setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));', renderer)

    def test_overview_active_command_table_keeps_command_item_text_visible(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        table_block = styles.split(".overview-command-table {", 1)[1].split("}", 1)[0]

        self.assertNotIn("min-width:", table_block)
        self.assertIn(
            "grid-template-columns: minmax(0, var(--overview-bottom-left-ratio, 50fr)) "
            "12px minmax(0, var(--overview-bottom-right-ratio, 50fr));",
            styles,
        )
        self.assertIn(".overview-command-table th:nth-child(3) { width: 168px; }", styles)
        self.assertIn("runtimeCommandBuildContext(snapshot, measurements)", app_js)

    def test_overview_active_command_table_aligns_headers_and_values_right(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        selector = ".overview-command-table th,\n.overview-command-table td {"
        alignment_block = styles.split(selector, 1)[1].split("}", 1)[0]

        self.assertIn("text-align: right;", alignment_block)

    def test_overview_active_command_table_hides_numeric_units(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        renderer = app_js.split("function renderOverviewActiveCommands", 1)[1].split(
            "function renderOverviewDashboard",
            1,
        )[0]

        for field in ("control", "real", "scada"):
            self.assertIn(f'runtimeCommandTableValueText(row, "{field}")', renderer)
        self.assertNotIn("escapeHtml(row.command_text || \"--\")", renderer)
        self.assertNotIn("escapeHtml(row.real_text || \"--\")", renderer)
        self.assertNotIn("escapeHtml(row.scada_text || \"--\")", renderer)

    def test_overview_middle_uses_large_energy_flow_without_process_strip(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for text in ("数据输入", "指令处理", "能力校核", "网络求解", "结果发布"):
            self.assertNotIn(text, html)
        for removed_id in (
            "overviewProcessSummary",
            "overviewSimulationFlow",
            "overviewFlowInput",
            "overviewFlowControl",
            "overviewFlowConstraint",
            "overviewFlowSolver",
            "overviewFlowOutput",
        ):
            self.assertNotIn(f'id="{removed_id}"', html)
            self.assertNotIn(f'"{removed_id}"', app_js)
        self.assertIn('data-overview-group="dcWind"', html)
        self.assertIn('data-overview-group="dcLoad"', html)
        self.assertIn('data-overview-group="acLoad"', html)
        self.assertNotIn('data-overview-group="load"', html)
        self.assertIn("renderOverviewFlowGroups", app_js)
        self.assertIn("overview-energy-board", html)
        self.assertIn("overview-energy-panel", html)
        self.assertIn("绿电功率", html)
        self.assertIn("绿电占比", html)
        self.assertNotIn("1 - 柴发/负荷", html)
        self.assertNotIn("overview-network-strip", html)

    def test_overview_energy_flow_uses_topology_aware_conditional_groups(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('data-flow-layout="topology-aware"', html)
        for element_id in (
            "overviewEnergyLeftBus",
            "overviewEnergyMainTrunk",
            "overviewEnergyRightBus",
            "overviewGridFormingStack",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('class="energy-device converter energy-acdc-converter"', html)
        self.assertIn('data-overview-group="acdcConverter"', html)
        self.assertNotIn('id="overviewStorageFlowNode"', html)
        self.assertNotIn('id="overviewStorageFlowLink"', html)
        self.assertIn('data-overview-region="dc"', html)
        self.assertIn('data-overview-region="forming"', html)
        self.assertIn('data-overview-region="ac"', html)
        for css_hook in (
            ".energy-source-stack",
            ".energy-terminal-stack",
            ".energy-grid-forming-stack",
            ".energy-bus-rail.left",
            ".energy-bus-rail.right",
            ".energy-main-trunk",
            ".energy-acdc-converter",
            ".energy-storage-branch",
            ".energy-flow-stream",
        ):
            self.assertIn(css_hook, styles)
        self.assertNotIn("energy-network-core", html)
        self.assertIn("OVERVIEW_FLOW_GROUP_DEFINITIONS", app_js)
        self.assertIn("node.hidden = !group.present", app_js)

        converter_block = styles.split(".energy-acdc-converter {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", converter_block)
        self.assertIn("left: 50%;", converter_block)
        self.assertIn("top: var(--energy-trunk-y);", converter_block)
        self.assertIn("transform: translate(-50%, -50%);", converter_block)
        self.assertIn('[data-flow-direction="toDc"] .energy-flow-stream', styles)
        self.assertIn('["toBus", "fromBus", "toAc", "toDc", "idle"]', app_js)
        self.assertIn('trunk.dataset.flowDirection = converterGroup?.flowDirection || "toAc"', app_js)
        self.assertIn(".energy-green-share {", styles)
        self.assertIn(".energy-green-metric {", styles)
        self.assertNotIn(".energy-device-heading {", styles)
        self.assertNotIn(".energy-load-green-share {", styles)

    def test_overview_green_summary_uses_signed_power_and_diesel_over_load_share(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("overviewPercentText", app_js)
        self.assertIn("(1.0 - power.diesel / power.load) * 100.0", app_js)
        self.assertIn("const greenPower = Number.isFinite(power.greenPower) ? -power.greenPower : null;", app_js)
        self.assertIn('setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));', app_js)
        self.assertIn('setOverviewText("overviewFlowGreenShare"', app_js)
        self.assertIn("return number.toFixed(2);", app_js)
        summary_block = styles.split(".energy-green-share {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", summary_block)
        self.assertIn("left: 50%;", summary_block)
        self.assertIn("top: 52px;", summary_block)
        self.assertIn("width: min(320px, 36%);", summary_block)
        self.assertIn("transform: translateX(-50%);", summary_block)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", summary_block)
        metric_block = styles.split(".energy-green-metric {", 1)[1].split("}", 1)[0]
        self.assertIn("justify-items: center;", metric_block)
        self.assertIn("text-align: center;", metric_block)
        divider_block = styles.split(".energy-green-metric + .energy-green-metric {", 1)[1].split("}", 1)[0]
        self.assertIn("border-left: 1px solid #dce8ea;", divider_block)
        self.assertNotIn("border-top:", divider_block)
        compact_block = styles.split("@container (max-height: 220px) {", 1)[1].split("}", 1)[0]
        self.assertIn(".energy-flow-map", compact_block)
        self.assertIn(".energy-green-share", styles.split("@container (max-height: 220px) {", 1)[1])
        narrow_block = styles.split("@container (max-width: 760px) {", 1)[1].split("@container (max-height: 220px)", 1)[0]
        self.assertIn(".energy-green-share", narrow_block)
        self.assertIn("position: static;", narrow_block)

    def test_overview_converter_card_sits_above_the_trunk_icon(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        converter_card_block = styles.split(".energy-converter-card {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", converter_card_block)
        self.assertIn("top: auto;", converter_card_block)
        self.assertIn("bottom: calc(100% + 7px);", converter_card_block)

        compact_styles = styles.split("@container (max-height: 220px) {", 1)[1]
        compact_summary_block = compact_styles.split(".energy-green-share {", 1)[1].split("}", 1)[0]
        self.assertIn("top: 4px;", compact_summary_block)

    def test_overview_energy_flow_has_dynamic_power_arrows(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("energy-flow-main-stream", html)
        self.assertIn("data-flow-active", html)
        for helper in (
            "renderEnergyFlowVisuals",
            "renderOverviewFlowGroups",
            "overviewFlowStyle",
            "overviewLoadFlowColor",
            "setOverviewFlowVisual",
        ):
            self.assertIn(helper, app_js)
        self.assertIn("data.flowDirection", app_js)
        self.assertIn('node.dataset.flowDirection = group.flowDirection', app_js)
        self.assertIn('setOverviewFlowVisual("overviewEnergyMainTrunk"', app_js)
        self.assertIn("@keyframes energyFlowForward", styles)
        self.assertIn("@keyframes energyFlowReverse", styles)
        self.assertIn('[data-flow-direction="toBus"]', styles)
        self.assertIn('[data-flow-direction="fromBus"]', styles)
        self.assertIn('[data-overview-group-wrapper="dcGridFormingStorage"][data-storage-flow="discharge"]', styles)
        self.assertIn('[data-overview-group-wrapper="acGridFormingStorage"][data-storage-flow="discharge"]', styles)
        self.assertIn("--flow-thickness", styles)
        self.assertIn("prefers-reduced-motion", styles)

    def test_grid_forming_storage_stays_between_side_device_columns(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        block = styles.split(".energy-grid-forming-stack {", 1)[1].split("}", 1)[0]

        self.assertIn("left: var(--energy-bus-inset);", block)
        self.assertIn("right: var(--energy-bus-inset);", block)
        self.assertIn("width: auto;", block)
        self.assertIn("transform: none;", block)
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="dcGridFormingStorage"] {\n'
            "  grid-column: 1;\n"
            "}",
            styles,
        )
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="acGridFormingStorage"] {\n'
            "  grid-column: 2;\n"
            "}",
            styles,
        )
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="dcGridFormingStorage"] .energy-storage-branch {\n'
            "  left: 0;\n"
            "  right: auto;\n"
            "}",
            styles,
        )
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="acGridFormingStorage"] .energy-storage-branch {\n'
            "  left: auto;\n"
            "  right: 0;\n"
            "}",
            styles,
        )

    def test_side_device_cards_fit_short_overview_panels(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        region_block = styles.split(".energy-source-stack {", 1)[1].split("}", 1)[0]
        list_block = styles.split(".energy-device-list {", 1)[1].split("}", 1)[0]
        card_block = styles.split(".energy-device-card {", 1)[1].split("}", 1)[0]
        value_block = styles.split(".energy-device-card strong {", 1)[1].split("}", 1)[0]

        self.assertIn("gap: 5px;", region_block)
        self.assertIn("gap: 4px;", list_block)
        self.assertIn("min-height: 50px;", card_block)
        self.assertIn("padding: 5px 9px;", card_block)
        self.assertIn("gap: 2px;", card_block)
        self.assertIn("font-size: 17px;", value_block)
        self.assertIn("white-space: nowrap;", value_block)

    def test_mobile_overview_expands_to_fit_energy_device_lists(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        mobile_styles = styles.split("@media (max-width: 820px) {", 1)[1]
        main_grid_block = mobile_styles.split(".overview-main-grid {", 1)[1].split("}", 1)[0]
        panel_block = mobile_styles.split(".overview-energy-panel {", 1)[1].split("}", 1)[0]
        board_block = mobile_styles.split(".overview-energy-board {", 1)[1].split("}", 1)[0]
        flow_block = mobile_styles.split(".energy-flow-map {", 1)[1].split("}", 1)[0]

        self.assertIn("grid-template-rows: auto auto;", main_grid_block)
        self.assertIn("min-height: 0;", main_grid_block)
        self.assertIn("flex: 0 0 auto;", main_grid_block)
        self.assertIn("overflow: visible;", panel_block)
        self.assertIn("grid-template-rows: auto;", board_block)
        self.assertIn("min-height: 0;", board_block)
        self.assertIn("flex: 0 0 auto;", board_block)
        self.assertIn("container-type: normal;", board_block)
        self.assertIn("align-self: start;", flow_block)

    def test_mobile_overview_keeps_surrounding_sections_from_shrinking(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        mobile_styles = styles.split("@media (max-width: 820px) {", 1)[1]

        self.assertIn(
            ".overview-status-panel,\n"
            "  .overview-bottom-splitter,\n"
            "  .overview-bottom-grid {\n"
            "    flex: 0 0 auto;\n"
            "  }",
            mobile_styles,
        )

    def test_overview_energy_flow_is_horizontally_compact_and_vertically_open(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        def css_block(selector: str, text: str = styles) -> str:
            marker = f"{selector} {{"
            start = text.index(marker)
            end = text.index("\n}", start)
            return text[start : end + 2]

        energy_board_block = css_block(".overview-energy-board")
        energy_flow_block = css_block(".energy-flow-map")
        low_height_start = styles.index("@media (max-height: 780px)")
        mobile_start = styles.index("@media (max-width: 820px)", low_height_start)
        low_height_styles = styles[low_height_start:mobile_start]
        low_height_board_block = css_block(".overview-energy-board", low_height_styles)
        low_height_flow_block = css_block(".energy-flow-map", low_height_styles)
        storage_wrap_block = css_block(".energy-storage-branch-wrap")
        storage_branch_block = css_block(".energy-storage-branch")

        self.assertIn("width: min(100%, 1360px);", styles)
        self.assertIn("justify-self: center;", energy_flow_block)
        self.assertIn("align-self: center;", energy_flow_block)
        self.assertIn("height: min(100%, 390px);", energy_flow_block)
        self.assertIn("min-height: 0;", energy_board_block)
        self.assertIn("place-items: center;", energy_board_block)
        self.assertIn("container-type: size;", energy_board_block)
        self.assertIn("min-height: 0;", energy_flow_block)
        self.assertIn("grid-template-rows: minmax(0, 1fr);", energy_board_block)
        self.assertIn("padding: 0;", energy_board_block)
        self.assertIn("border: 0;", energy_board_block)
        self.assertIn("background: transparent;", energy_board_block)
        self.assertNotIn("background: #f7fafb;", energy_board_block)
        self.assertNotIn("border: 1px solid var(--line);", energy_board_block)
        self.assertNotIn("grid-template-rows: auto minmax(340px, 1fr);", energy_board_block)
        self.assertNotIn("grid-template-rows: auto minmax(0, 1fr);", energy_board_block)
        self.assertNotIn("min-height: 390px;", energy_board_block)
        self.assertNotIn("min-height: 340px;", energy_flow_block)
        self.assertIn("height: min(100%, 340px);", low_height_flow_block)
        self.assertIn("min-height: 0;", low_height_board_block)
        self.assertIn("min-height: 0;", low_height_flow_block)
        self.assertIn("grid-template-rows: minmax(0, 1fr);", low_height_board_block)
        self.assertNotIn("grid-template-rows: auto minmax(240px, 1fr);", low_height_board_block)
        self.assertNotIn("min-height: 276px;", low_height_board_block)
        self.assertNotIn("min-height: 240px;", low_height_flow_block)
        self.assertIn("height: 230px;", styles)
        self.assertIn("--energy-storage-gap: 36px;", energy_flow_block)
        self.assertIn("--energy-storage-gap: 36px;", low_height_flow_block)
        self.assertIn(".energy-green-share {\n    top: 40px;\n  }", low_height_styles)
        self.assertIn("position: absolute;", storage_wrap_block)
        self.assertIn("grid-column: 1 / -1;", storage_wrap_block)
        self.assertIn("top: calc(var(--energy-trunk-y) + var(--energy-storage-gap));", storage_wrap_block)
        self.assertIn("left: 50%;", storage_wrap_block)
        self.assertIn("transform: translateX(-50%);", storage_wrap_block)
        self.assertIn("top: 50%;", storage_branch_block)
        self.assertIn("height: var(--flow-thickness);", storage_branch_block)
        self.assertIn("transform: translateY(-50%);", storage_branch_block)
        self.assertNotIn("justify-content: flex-end;", storage_wrap_block)
        self.assertNotIn("padding-bottom:", storage_wrap_block)
        self.assertNotIn("bottom: 178px;", styles)
        self.assertNotIn("bottom: 84px;", low_height_styles)
        self.assertNotIn("padding-bottom: 4px;", low_height_styles)
        self.assertIn("min-height: 82px;", styles)
        self.assertIn("@container (max-height: 220px)", styles)
        self.assertIn("--energy-storage-gap: 64px;", styles)
        self.assertIn("--energy-trunk-y: min(50%, calc(100% - 86px));", styles)
        self.assertIn(".energy-device.storage small", styles)
        self.assertNotIn(".simulation-flow", styles)

    def test_short_desktop_viewports_do_not_compress_the_energy_flow_map(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")
        low_height_styles = styles.split("@media (max-height: 780px) and (min-width: 821px) {", 1)[1].split(
            "@media (max-width: 820px) {",
            1,
        )[0]
        dashboard_block = low_height_styles.split(".overview-dashboard {", 1)[1].split("}", 1)[0]
        main_grid_block = low_height_styles.split(".overview-main-grid {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow-y: auto;", dashboard_block)
        self.assertIn("overflow-x: hidden;", dashboard_block)
        self.assertIn("--overview-main-min-height: 370px;", dashboard_block)
        self.assertIn("min-height: var(--overview-main-min-height);", main_grid_block)

    def test_overview_storage_cards_connect_horizontally_to_their_own_bus(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        def css_block(selector: str, text: str = styles) -> str:
            marker = f"{selector} {{"
            start = text.index(marker)
            end = text.index("\n}", start)
            return text[start : end + 2]

        energy_flow_block = css_block(".energy-flow-map")
        trunk_block = css_block(".energy-main-trunk")
        storage_branch_block = css_block(".energy-storage-branch")
        storage_stack_block = css_block(".energy-grid-forming-stack")
        low_height_start = styles.index("@media (max-height: 780px)")
        mobile_start = styles.index("@media (max-width: 820px)", low_height_start)
        low_height_styles = styles[low_height_start:mobile_start]
        low_height_flow_block = css_block(".energy-flow-map", low_height_styles)

        self.assertIn("--energy-trunk-y: 54%;", energy_flow_block)
        self.assertIn("--energy-bus-inset: clamp(230px, 28%, 312px);", energy_flow_block)
        self.assertIn("--energy-storage-gap:", energy_flow_block)
        self.assertIn("top: var(--energy-trunk-y);", trunk_block)
        self.assertIn("transform: translateY(-50%);", trunk_block)
        self.assertIn("top: calc(var(--energy-trunk-y) + var(--energy-storage-gap));", storage_stack_block)
        self.assertIn("top: 50%;", storage_branch_block)
        self.assertIn("height: var(--flow-thickness);", storage_branch_block)
        self.assertIn("width: max(22px, calc((100% - var(--energy-storage-card-width)) / 2 + 2px));", storage_branch_block)
        self.assertIn("background-image: repeating-linear-gradient(", storage_branch_block)
        self.assertNotIn("bottom: calc(100% + 2px);", storage_branch_block)
        self.assertIn("--energy-trunk-y: min(58%, calc(100% - 86px));", low_height_flow_block)

    def test_overview_bottom_tables_have_draggable_height_splitter(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="overviewBottomSplitter"', html)
        self.assertIn('role="separator"', html)
        self.assertIn('aria-orientation="horizontal"', html)
        self.assertIn("调整下方表格高度", html)
        self.assertIn("--overview-bottom-height", styles)
        self.assertIn("--overview-main-min-height: 420px;", styles)
        self.assertIn(
            "grid-template-rows: auto minmax(var(--overview-main-min-height), 1fr) "
            "10px minmax(96px, var(--overview-bottom-height));",
            styles,
        )
        main_grid_block = styles.split(".overview-main-grid {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: var(--overview-main-min-height);", main_grid_block)
        self.assertIn("const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;", app_js)
        self.assertIn("const mainMinHeight = Number.parseFloat", app_js)
        self.assertIn("statusHeight + mainMinHeight + splitterHeight", app_js)
        self.assertIn(".overview-bottom-splitter", styles)
        self.assertIn("cursor: row-resize;", styles)
        self.assertIn("is-overview-splitter-dragging", styles)
        self.assertIn("polarOverviewBottomHeight", app_js)
        self.assertIn("function initOverviewBottomSplitter", app_js)
        self.assertIn("function applyOverviewBottomHeight", app_js)
        self.assertIn("beginOverviewBottomSplitterDrag", app_js)
        self.assertIn("handleOverviewBottomSplitterKeydown", app_js)

    def test_overview_soc_falls_back_to_control_response_storage_soc(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("storageSocPercentFromText", app_js)
        self.assertIn('latestRuntimeLog(snapshot, "控制响应")', app_js)
        self.assertIn("ESS\\.", app_js)

    def test_mobile_topbar_does_not_keep_desktop_toolbar_height(self):
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(
            ".model-toolbar {\n"
            "    width: 100%;\n"
            "    min-width: 0;\n"
            "    max-width: none;\n"
            "    flex: 0 0 auto;\n"
            "    flex-wrap: wrap;",
            styles,
        )


if __name__ == "__main__":
    unittest.main()
