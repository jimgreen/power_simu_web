from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeOverviewDashboardUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_power_flow_failure_is_visible_on_every_trainee_page(self):
        self.assertIn('id="powerFlowFailureAlert"', self.html)
        self.assertIn('role="alert"', self.html)
        self.assertIn('aria-live="assertive"', self.html)
        self.assertIn('id="powerFlowFailureTitle"', self.html)
        self.assertIn('id="powerFlowFailureDetail"', self.html)
        self.assertIn("function renderPowerFlowFailureAlert", self.script)
        self.assertIn("snapshot.compute?.error", self.script)
        self.assertIn("snapshot.compute?.simu_time", self.script)
        self.assertIn("本轮潮流结果未采用", self.script)
        self.assertIn("last_successful_simu_time", self.script)
        self.assertIn("当前画面量测为上一成功帧", self.script)
        self.assertIn("当前画面没有成功潮流量测帧", self.script)
        self.assertIn("renderPowerFlowFailureAlert(snapshot)", self.script)
        self.assertIn(".power-flow-failure-alert", self.styles)
        self.assertIn(".power-flow-failure-alert[hidden]", self.styles)

    def test_trainee_overview_event_panel_shows_up_to_eight_rows(self):
        renderer = self.script.split("function renderTraineeOverviewEvents() {", 1)[1].split(
            "function renderTraineeOverviewDashboard",
            1,
        )[0]

        self.assertIn(".slice(0, 8)", renderer)
        self.assertNotIn(".slice(0, 4)", renderer)

    def test_trainee_overview_event_panel_scrolls_inside_its_existing_height(self):
        event_list_block = self.styles.split(".overview-event-list {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow-x: hidden;", event_list_block)
        self.assertIn("overflow-y: auto;", event_list_block)
        self.assertIn("scrollbar-gutter: stable;", event_list_block)
        self.assertNotIn("overflow: hidden;", event_list_block)

    def test_trainee_home_uses_simulator_style_energy_flow(self):
        for text in ("绿电功率", "绿电占比", "教员数据", "最新交互事件", "当前有效/排队指令"):
            self.assertIn(text, self.html)
        self.assertNotIn("电气能量流", self.html)
        self.assertNotIn("尚无接收结果", self.html)
        self.assertNotIn("功率差额", self.html)
        self.assertNotIn("energy-board-head", self.html)
        self.assertNotIn("energy-board-meta", self.html)
        self.assertNotIn("接收质量", self.html)
        for element_id in ("overviewFlowGreenPower", "overviewFlowGreenShare", "overviewReceiveDot"):
            self.assertIn(f'id="{element_id}"', self.html)
            self.assertIn(f'"{element_id}"', self.script)
        for group_key, label in (
            ("dcWind", "直流并网风电"),
            ("dcSolar", "直流并网光伏"),
            ("dcGridFollowingStorage", "直流跟网储能"),
            ("dcGridFormingStorage", "直流构网储能"),
            ("acGridFormingStorage", "交流构网储能"),
            ("acdcConverter", "DC/AC变流器"),
            ("acWind", "交流并网风电"),
            ("acSolar", "交流并网光伏"),
            ("acGridFollowingStorage", "交流跟网储能"),
            ("dcLoad", "直流负荷"),
            ("acLoad", "交流负荷"),
            ("diesel", "柴油发电"),
        ):
            self.assertIn(f'data-overview-group="{group_key}"', self.html)
            self.assertIn(label, self.html)
        self.assertNotIn('data-overview-group="load"', self.html)
        dc_region = self.html.split('data-overview-region="dc"', 1)[1].split("</section>", 1)[0]
        ac_region = self.html.split('data-overview-region="ac"', 1)[1].split("</section>", 1)[0]
        self.assertIn('data-overview-group="dcLoad"', dc_region)
        self.assertNotIn('data-overview-group="acLoad"', dc_region)
        self.assertIn('data-overview-group="acLoad"', ac_region)
        self.assertNotIn('data-overview-group="dcLoad"', ac_region)
        self.assertIn('<article class="energy-green-share"', self.html)
        green_summary = self.html.split('<article class="energy-green-share"', 1)[1].split("</article>", 1)[0]
        self.assertIn("绿电功率", green_summary)
        self.assertIn("绿电占比", green_summary)
        self.assertIn('id="overviewFlowGreenPower"', green_summary)
        self.assertIn('id="overviewFlowGreenShare"', green_summary)
        for group_key, label in (("dcLoad", "直流负荷"), ("acLoad", "交流负荷")):
            load_card = self.html.split(f'data-overview-group="{group_key}"', 1)[1].split("</article>", 1)[0]
            self.assertIn(f"<span>{label}</span>", load_card)
            self.assertNotIn('class="energy-device-heading"', load_card)
            self.assertNotIn("绿电功率", load_card)
            self.assertNotIn("绿电占比", load_card)
            self.assertNotIn('id="overviewFlowGreenPower"', load_card)
            self.assertNotIn('id="overviewFlowGreenShare"', load_card)
        for element_id in ("overviewFlowGreenPower", "overviewFlowGreenShare"):
            self.assertEqual(self.html.count(f'id="{element_id}"'), 1)
        for removed_id in ("overviewFlowBalance", "overviewFlowResultTime"):
            self.assertNotIn(f'id="{removed_id}"', self.html)
            self.assertNotIn(f'"{removed_id}"', self.script)
        self.assertIn('data-flow-layout="topology-aware"', self.html)
        self.assertIn('class="energy-device converter energy-acdc-converter"', self.html)
        self.assertIn('data-overview-group="acdcConverter"', self.html)
        self.assertNotIn('id="overviewStorageFlowNode"', self.html)
        self.assertNotIn('id="overviewStorageFlowLink"', self.html)
        self.assertNotIn('class="one-line"', self.html)

    def test_trainee_wind_solar_and_storage_arrows_share_green_color(self):
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
            definition = next(line for line in self.script.splitlines() if f'key: "{group_key}"' in line)
            self.assertIn('color: "#2f9e62"', definition)
        self.assertIn('definition.category === "load"', self.script)
        self.assertIn("acLoad: { power: power.load }", self.script)
        self.assertIn("source.load", self.script)

    def test_trainee_overview_uses_real_equipment_icons_and_separate_information_cards(self):
        overview = self.html.split('<div class="energy-flow-map"', 1)[1].split("</section>", 1)[0]

        for icon_id in (
            "energy-icon-wind-turbine",
            "energy-icon-solar-array",
            "energy-icon-battery-storage",
            "energy-icon-electric-load",
            "energy-icon-diesel-generator",
            "energy-icon-acdc-converter",
        ):
            self.assertIn(f'id="{icon_id}"', self.html)

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
            group_html = self.html.split(f'data-overview-group="{group_key}"', 1)[1].split("</article>", 1)[0]
            self.assertIn('class="energy-device-card"', group_html)
            self.assertIn('class="energy-device-icon"', group_html)
            self.assertIn(f'href="#energy-icon-{icon_name}"', group_html)
            self.assertEqual(group_html.count("data-overview-power"), 1)
            self.assertEqual(group_html.count("data-overview-meta"), 1)

        converter = self.html.split('data-overview-group="acdcConverter"', 1)[1].split("</article>", 1)[0]
        self.assertIn('class="energy-device-icon energy-converter-icon"', converter)
        self.assertIn('href="#energy-icon-acdc-converter"', converter)
        self.assertIn('class="energy-device-card energy-converter-card"', converter)
        self.assertLess(converter.index("energy-converter-icon"), converter.index("energy-converter-card"))
        self.assertEqual(converter.count("data-overview-power"), 1)
        self.assertEqual(converter.count("data-overview-meta"), 1)

        for obsolete_badge in (">风<", ">光<", ">储<", ">荷<", ">柴<", ">AC/DC<"):
            self.assertNotIn(obsolete_badge, overview)

    def test_trainee_overview_cards_show_current_target_and_renewable_max_available_values(self):
        renewable_groups = {"dcWind", "dcSolar", "acWind", "acSolar"}
        for group_key in (
            "dcWind",
            "dcSolar",
            "dcGridFollowingStorage",
            "dcLoad",
            "dcGridFormingStorage",
            "acGridFormingStorage",
            "acdcConverter",
            "acWind",
            "acSolar",
            "acGridFollowingStorage",
            "acLoad",
            "diesel",
        ):
            card = self.html.split(f'data-overview-group="{group_key}"', 1)[1].split("</article>", 1)[0]
            self.assertEqual(card.count("data-overview-power"), 1)
            self.assertEqual(card.count("data-overview-target"), 1)
            self.assertEqual(card.count("data-overview-max-available"), 1 if group_key in renewable_groups else 0)
            self.assertIn("当前", card)
            self.assertIn("目标", card)
            if group_key in renewable_groups:
                self.assertIn("最大可发", card)

        normalizer = self.script.split("function normalizeOverviewFlowGroups", 1)[1].split(
            "function parsePowerFlowOverview",
            1,
        )[0]
        self.assertIn("targetPower: powerSummaryNumber(data.targetPower ?? fallbackData.targetPower)", normalizer)
        self.assertIn(
            "maxAvailablePower: powerSummaryNumber(data.maxAvailablePower ?? fallbackData.maxAvailablePower)",
            normalizer,
        )

        renderer = self.script.split("function renderOverviewFlowGroups(power) {", 1)[1].split(
            "function renderEnergyFlowVisuals",
            1,
        )[0]
        self.assertNotIn("innerHTML", renderer)
        self.assertIn('node.querySelector("[data-overview-power]")', renderer)
        self.assertIn('node.querySelector("[data-overview-target]")', renderer)
        self.assertIn('node.querySelector("[data-overview-max-available]")', renderer)
        self.assertIn("overviewPowerText(group.targetPower)", renderer)
        self.assertIn("overviewPowerText(group.maxAvailablePower)", renderer)
        self.assertIn(".energy-device-readings {", self.styles)
        self.assertIn(".energy-device-reading {", self.styles)

    def test_trainee_overview_cards_place_status_summary_in_the_right_side_of_the_first_row(self):
        for group_key, label in (
            ("dcWind", "直流并网风电"),
            ("dcSolar", "直流并网光伏"),
            ("dcGridFollowingStorage", "直流跟网储能"),
            ("dcLoad", "直流负荷"),
            ("acdcConverter", "DC/AC变流器"),
            ("dcGridFormingStorage", "直流构网储能"),
            ("acGridFormingStorage", "交流构网储能"),
            ("acWind", "交流并网风电"),
            ("acSolar", "交流并网光伏"),
            ("acGridFollowingStorage", "交流跟网储能"),
            ("acLoad", "交流负荷"),
            ("diesel", "柴油发电"),
        ):
            card = self.html.split(f'data-overview-group="{group_key}"', 1)[1].split("</article>", 1)[0]
            self.assertEqual(card.count('class="energy-device-card-head"'), 1)
            header = card.split('<div class="energy-device-card-head">', 1)[1].split("</div>", 1)[0]
            self.assertIn(f"<span>{label}</span>", header)
            self.assertIn("data-overview-meta", header)
            self.assertLess(card.index("energy-device-card-head"), card.index("energy-device-readings"))
            self.assertEqual(card.count("data-overview-meta"), 1)

        header_styles = self.styles.split(".energy-device-card-head {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex;", header_styles)
        self.assertIn("justify-content: space-between;", header_styles)
        self.assertIn("align-items: baseline;", header_styles)
        title_styles = self.styles.split(".energy-device-card-head > span {", 1)[1].split("}", 1)[0]
        meta_styles = self.styles.split('.energy-device-card-head [data-overview-meta] {', 1)[1].split("}", 1)[0]
        self.assertIn("flex: 0 0 auto;", title_styles)
        self.assertIn("flex: 1 1 auto;", meta_styles)
        self.assertIn("text-align: right;", meta_styles)
        self.assertIn("white-space: nowrap;", meta_styles)
        self.assertIn("--energy-storage-card-width: 360px;", self.styles)

    def test_trainee_overview_icons_own_flow_connectors_and_keep_state_responsive_rules(self):
        left_block = self.styles.split('.energy-side-node[data-flow-side="left"] {', 1)[1].split("}", 1)[0]
        right_block = self.styles.split('.energy-side-node[data-flow-side="right"] {', 1)[1].split("}", 1)[0]
        self.assertIn(
            "grid-template-columns: minmax(0, 1fr) var(--energy-device-icon-size);",
            left_block,
        )
        self.assertIn(
            "grid-template-columns: var(--energy-device-icon-size) minmax(0, 1fr);",
            right_block,
        )
        self.assertIn(".energy-device-card {", self.styles)
        self.assertIn(".energy-device-icon {", self.styles)
        self.assertIn(".energy-side-node .energy-device-icon::before", self.styles)
        self.assertIn(".energy-side-node .energy-device-icon::after", self.styles)
        self.assertIn('.energy-side-node[data-flow-active="false"] .energy-device-icon::before', self.styles)
        self.assertNotIn(".energy-side-node::before", self.styles)
        self.assertNotIn(".energy-side-node::after", self.styles)
        self.assertIn(
            '[data-overview-group-wrapper="dcGridFormingStorage"] .energy-device.storage',
            self.styles,
        )
        self.assertIn(
            '[data-overview-group-wrapper="acGridFormingStorage"] .energy-device.storage',
            self.styles,
        )
        self.assertIn('.energy-device[data-operating-state="retired"] .energy-device-icon', self.styles)
        self.assertIn('.energy-device[data-operating-state="deadIsland"] .energy-device-card', self.styles)
        self.assertIn('.energy-device[data-operating-state="unmeasured"] .energy-device-icon', self.styles)
        self.assertIn(".energy-converter-icon {", self.styles)
        self.assertIn(".energy-converter-card {", self.styles)

        compact_styles = self.styles.split("@container (max-width: 760px) {", 1)[1].split(
            "@container (max-height: 220px)",
            1,
        )[0]
        self.assertIn(".energy-side-node .energy-device-icon::before", compact_styles)
        self.assertIn(".energy-side-node .energy-device-icon::after", compact_styles)
        self.assertIn("display: none;", compact_styles)

        renderer = self.script.split("function renderOverviewFlowGroups(power) {", 1)[1].split(
            "function renderEnergyFlowVisuals",
            1,
        )[0]
        self.assertNotIn("innerHTML", renderer)
        self.assertIn('node.querySelector("[data-overview-power]")', renderer)
        self.assertIn('node.querySelector("[data-overview-meta]")', renderer)

    def test_trainee_overview_energy_cards_expand_for_richer_readings_without_breaking_compact_height(self):
        flow_map = self.styles.split(".energy-flow-map {", 1)[1].split("}", 1)[0]
        self.assertIn("--energy-device-icon-size: 60px;", flow_map)
        self.assertIn("--energy-device-icon-glyph-size: 40px;", flow_map)
        self.assertIn("width: min(100%, 1540px);", flow_map)
        self.assertIn(
            "grid-template-columns: minmax(215px, 310px) 24px minmax(260px, 1fr) 24px minmax(220px, 310px);",
            flow_map,
        )

        icon = self.styles.split(".energy-device-icon {", 1)[1].split("}", 1)[0]
        self.assertIn("width: var(--energy-device-icon-size);", icon)
        self.assertIn("height: var(--energy-device-icon-size);", icon)
        icon_svg = self.styles.split(".energy-device-icon svg {", 1)[1].split("}", 1)[0]
        self.assertIn("width: var(--energy-device-icon-glyph-size);", icon_svg)
        self.assertIn("height: var(--energy-device-icon-glyph-size);", icon_svg)

        card = self.styles.split(".energy-device-card {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: 76px;", card)
        self.assertIn("padding: 9px 10px;", card)

        medium = self.styles.split("@container (max-height: 460px) {", 1)[1].split(
            "@container (max-height: 360px)",
            1,
        )[0]
        self.assertIn("--energy-device-icon-size: 52px;", medium)
        self.assertIn("--energy-device-icon-glyph-size: 34px;", medium)
        self.assertNotIn("--energy-summary-y:", medium)
        self.assertNotIn("--energy-forming-y:", medium)
        self.assertIn("min-height: 64px;", medium)
        self.assertIn("padding: 7px 12px;", medium)

        compact = self.styles.split("@container (max-height: 360px) {", 1)[1].split(
            "@container (max-height: 320px)",
            1,
        )[0]
        self.assertIn("--energy-device-icon-size: 42px;", compact)
        self.assertIn("--energy-device-icon-glyph-size: 28px;", compact)
        self.assertIn("min-height: 50px;", compact)
        self.assertIn("padding: 5px 9px;", compact)

    def test_trainee_grid_following_storage_keeps_bus_connector_and_buses_share_extended_height(self):
        self.assertNotIn(
            ".energy-device.storage::after,\n.energy-device.storage::before {",
            self.styles,
        )
        self.assertIn(
            ".energy-storage-branch-wrap .energy-device.storage::after,\n"
            ".energy-storage-branch-wrap .energy-device.storage::before {",
            self.styles,
        )
        left_bus_block = self.styles.split(".energy-bus-rail.left {", 1)[1].split("}", 1)[0]
        right_bus_block = self.styles.split(".energy-bus-rail.right {", 1)[1].split("}", 1)[0]
        low_height_styles = self.styles.split(
            "@media (max-height: 780px) and (min-width: 821px) {",
            1,
        )[1].split("@media (max-width: 820px) {", 1)[0]

        responsive_bus_height = (
            "height: calc(100% - var(--energy-edge-inset-y) - var(--energy-edge-inset-y));"
        )
        self.assertIn(responsive_bus_height, left_bus_block)
        self.assertIn(responsive_bus_height, right_bus_block)
        self.assertNotIn("height: 156px;", low_height_styles)

    def test_trainee_home_removes_receive_quality_panel(self):
        overview = self.html.split('<section class="page-section is-active" data-page="overview">', 1)[1].split(
            '<section class="page-section" data-page="model">',
            1,
        )[0]
        for removed_text in ("接收质量", "量测有效率", "策略状态", "最近下发"):
            self.assertNotIn(removed_text, overview)
        for removed_id in (
            "overviewMeasurementQuality",
            "overviewMeasurementRate",
            "overviewRenewableState",
            "overviewLastCommand",
        ):
            self.assertNotIn(f'id="{removed_id}"', self.html)
            self.assertNotIn(f'"{removed_id}"', self.script)
        self.assertNotIn("overview-health-panel", self.html)
        self.assertNotIn("latestCommandIssuedAt", self.script)
        self.assertIn('id="pendingSummary"', overview)

    def test_trainee_home_shows_current_active_remote_commands(self):
        self.assertIn("function activeCommandPreviewRows", self.script)
        self.assertIn("function renderActiveCommandPreview", self.script)
        self.assertIn("activeCommandHistory(snapshot)", self.script)
        self.assertIn("遥控 · ${remoteControlLabel(commandType)}", self.script)
        self.assertIn("遥调 · ${remoteAdjustmentTypeLabel(setType)}", self.script)
        self.assertIn("actual_value", self.script)
        self.assertIn('wall_time: timeInfo.wall_time || "--"', self.script)
        self.assertIn("snapshotDevice(devType, devName, snapshot)", self.script)
        self.assertIn("remoteAdjustmentMeasurement(liveDev, setType, snapshot)", self.script)
        self.assertIn('class="active-command-preview-wrap"', self.html)
        self.assertIn('class="active-command-preview-table"', self.script)
        for column in ("下发本机时刻", "设备", "指令", "指令值", "实时值", "处理状态", "仿真时刻"):
            self.assertIn(f"<th>{column}</th>", self.script)
        self.assertIn("<th>下发本机时刻</th>\n          <th>设备</th>", self.script)
        self.assertIn('title="${escapeHtml(item.wall_time)}">${escapeHtml(item.wall_time)}</td>', self.script)
        first_time_column = self.styles.split(".active-command-preview-table th:nth-child(1),", 1)[1].split("}", 1)[0]
        self.assertIn("width: 15%;", first_time_column)
        self.assertIn(".active-command-preview-table th:nth-child(7)", self.styles)
        self.assertNotIn('<div class="log-item">\\n      <strong>${escapeHtml(item.name)}</strong>', self.script)
        self.assertIn("暂无当前有效或排队指令", self.script)
        self.assertIn("[...displayedCommandHistory(snapshot)].reverse()", self.script)
        self.assertIn("下发完成，模拟台排队", self.script)
        self.assertIn("renderActiveCommandPreview();", self.script)

    def test_trainee_home_only_shows_latest_value_for_each_active_command_point(self):
        row_builder = self.script.split("function activeCommandPreviewRows", 1)[1].split(
            "function renderActiveCommandPreview",
            1,
        )[0]
        renderer = self.script.split("function renderActiveCommandPreview", 1)[1].split(
            "function updatePendingCount",
            1,
        )[0]

        self.assertIn("const seenCommandKeys = new Set();", row_builder)
        self.assertIn("[...displayedCommandHistory(snapshot)].reverse()", row_builder)
        self.assertIn('["remote_control", devType, devName, commandType].join("|")', row_builder)
        self.assertIn('["remote_adjustment", devType, devName, setType].join("|")', row_builder)
        self.assertIn("seenCommandKeys.has(commandKey)", row_builder)
        self.assertIn("seenCommandKeys.add(commandKey)", row_builder)
        self.assertNotIn("rows.slice(0, 12)", renderer)
        self.assertIn("${rows.map((item) => `", renderer)

    def test_trainee_home_renders_received_power_flow_and_status(self):
        for helper in (
            "renderTraineeOverviewDashboard",
            "parsePowerFlowOverview",
            "renderEnergyFlowVisuals",
            "overviewLoadFlowColor",
            "renderTraineeOverviewEvents",
        ):
            self.assertIn(helper, self.script)
        self.assertIn('const electrolyzerPower = overviewGreenGroupPower(groups, "electrolyzer");', self.script)
        self.assertIn("const loadPower = dcLoadPower + acLoadPower + electrolyzerPower;", self.script)
        self.assertIn("const greenPower = loadPower - dieselPower;", self.script)
        self.assertIn("(greenPower / loadPower) * 100.0", self.script)
        self.assertIn("acdcConverter: { power: null }", self.script)
        self.assertNotIn("Number.isFinite(power.greenPower) ? -power.greenPower", self.script)
        for element_id in (
            "receiveStateText",
            "teacherSourceText",
            "measureCount",
            "validCount",
            "pendingCount",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("renderTraineeOverviewDashboard(snapshot);", self.script)

    def test_overview_draws_hydrogen_chain_with_only_the_active_target_and_header_count(self):
        chain = self.html.split('data-overview-region="hydrogen"', 1)[1].split("</section>", 1)[0]
        for group_key, label in (
            ("fuelCell", "燃料电池"),
            ("hydrogenStorage", "储氢罐"),
            ("electrolyzer", "电制氢"),
        ):
            self.assertIn(f'data-overview-group="{group_key}"', chain)
            self.assertIn(label, chain)
            card = chain.split(f'data-overview-group="{group_key}"', 1)[1].split("</article>", 1)[0]
            count = card.split("data-overview-count", 1)[1].split("</span>", 1)[0]
            self.assertNotIn("数量", count)

        fuel_cell = chain.split('data-overview-group="fuelCell"', 1)[1].split("</article>", 1)[0]
        electrolyzer = chain.split('data-overview-group="electrolyzer"', 1)[1].split("</article>", 1)[0]
        tank = chain.split('data-overview-group="hydrogenStorage"', 1)[1].split("</article>", 1)[0]
        for card in (fuel_cell, electrolyzer):
            self.assertIn("data-overview-power", card)
            self.assertIn("data-overview-gas-flow", card)
            self.assertEqual(card.count("data-overview-active-target"), 2)
            self.assertIn("data-overview-count", card)
            self.assertNotIn("data-overview-target-gas-flow", card)
            self.assertNotIn("data-overview-meta", card)
        for field in ("gas-flow", "gas-pressure", "soc"):
            self.assertIn(f"data-overview-{field}", tank)
        self.assertNotIn("data-overview-gas-quantity", tank)
        self.assertIn("data-overview-count", tank)

        self.assertIn('key: "fuelCell"', self.script)
        self.assertIn('key: "hydrogenStorage"', self.script)
        self.assertIn('key: "electrolyzer"', self.script)
        self.assertIn("const gasFlow = powerSummaryNumber", self.script)
        self.assertIn("targetGasFlow: powerSummaryNumber", self.script)
        self.assertIn("controlMode: String(data.controlMode", self.script)
        self.assertIn("gasPressure: powerSummaryNumber", self.script)
        self.assertIn("gasQuantity: powerSummaryNumber", self.script)
        hydrogen_state = self.script.split("function overviewHydrogenStorageFlowState", 1)[1].split(
            "function normalizeOverviewFlowGroups",
            1,
        )[0]
        self.assertIn('? { status: "releasingHydrogen", flowDirection: "fromTank" }', hydrogen_state)
        self.assertIn(': { status: "storingHydrogen", flowDirection: "toTank" }', hydrogen_state)
        self.assertIn('node.querySelector("[data-overview-gas-flow]")', self.script)
        self.assertIn("function overviewHydrogenActiveTarget", self.script)
        self.assertIn('node.querySelector("[data-overview-active-target-label]")', self.script)
        self.assertIn('node.querySelector("[data-overview-active-target]")', self.script)
        self.assertIn('node.querySelector("[data-overview-count]")', self.script)
        self.assertIn('countNode.textContent = `${group.onlineCount}/${group.totalCount} 台`', self.script)
        self.assertNotIn('countNode.textContent = `数量 ${group.onlineCount}/${group.totalCount} 台`', self.script)
        self.assertIn('node.querySelector("[data-overview-gas-pressure]")', self.script)
        self.assertIn('node.querySelector("[data-overview-soc]")', self.script)
        self.assertNotIn('node.querySelector("[data-overview-gas-quantity]")', self.script)

        self.assertIn(".energy-hydrogen-chain {", self.styles)
        self.assertIn(".energy-hydrogen-link {", self.styles)
        self.assertIn('[data-hydrogen-link="fuel-cell-electric"]', self.styles)
        self.assertIn('[data-hydrogen-link="electrolyzer-electric"]', self.styles)
        hydrogen_header = self.styles.split(".energy-hydrogen-card-head > span {", 1)[1].split("}", 1)[0]
        hydrogen_label = self.styles.split(".energy-hydrogen-readings .energy-device-reading span {", 1)[1].split("}", 1)[0]
        hydrogen_value = self.styles.split(".energy-hydrogen-readings .energy-device-reading strong {", 1)[1].split("}", 1)[0]
        self.assertIn("font: inherit;", hydrogen_header)
        self.assertIn("color: inherit;", hydrogen_header)
        self.assertIn("font-size: 12px;", hydrogen_header)
        self.assertIn("line-height: 14px;", hydrogen_header)
        self.assertIn("font-size: 11px;", hydrogen_label)
        self.assertIn("line-height: 13px;", hydrogen_label)
        self.assertIn("font-size: 14px;", hydrogen_value)
        self.assertIn("line-height: 15px;", hydrogen_value)
        compact = self.styles.split("@container (max-width: 760px) {", 1)[1]
        self.assertIn(".energy-hydrogen-chain", compact)
        self.assertIn("position: static;", compact)
        self.assertIn("transform: none;", compact)

        narrow = self.styles.split("@container (max-width: 940px) and (min-width: 761px) {", 1)[1]
        narrow_card = narrow.split(".energy-hydrogen-card {", 1)[1].split("}", 1)[0]
        medium_height = self.styles.split("@container (max-height: 460px) {", 1)[1].split("@container (max-height: 360px) {", 1)[0]
        medium_header = medium_height.split(".energy-hydrogen-card-head > span,", 1)[1].split("}", 1)[0]
        medium_label = medium_height.split(".energy-hydrogen-readings .energy-device-reading span {", 1)[1].split("}", 1)[0]
        medium_value = medium_height.split(".energy-hydrogen-readings .energy-device-reading strong {", 1)[1].split("}", 1)[0]
        medium_device = medium_height.split(".energy-hydrogen-device {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-column: 1 / -1;", narrow_card)
        self.assertIn(".energy-hydrogen-card-head {", self.styles)
        self.assertIn("justify-content: space-between;", self.styles)
        self.assertIn("font-size: 12px;", medium_header)
        self.assertIn("font-size: 10px;", medium_label)
        self.assertIn("font-size: 13px;", medium_value)
        self.assertNotIn("display: none;", medium_header)
        self.assertIn("grid-template-columns: 36px minmax(0, 1fr);", medium_device)
        self.assertIn("min-height: 76px;", medium_height)

    def test_trainee_weather_display_falls_back_when_environment_scada_is_invalid(self):
        weather_block = self.script.split("function currentWeatherLoad", 1)[1].split(
            "function latestRuntimeLog",
            1,
        )[0]

        self.assertIn("windMeasurement.valid && Number.isFinite(windMeasurement.value)", weather_block)
        self.assertIn("solarMeasurement.valid && Number.isFinite(solarMeasurement.value)", weather_block)
        self.assertIn('interpolateCurve(weather, minute, "wind_speed_mps", null)', weather_block)
        self.assertIn('optionalNumber(boundaryPoint.wind_speed_mps)', weather_block)
        self.assertIn('interpolateCurve(weather, minute, "solar_irradiance_w_m2", null)', weather_block)
        self.assertIn('optionalNumber(boundaryPoint.solar_irradiance_w_m2)', weather_block)

    def test_trainee_home_prefers_signed_structured_realtime_power_summary(self):
        parser = self.script.split("function parsePowerFlowOverview(snapshot) {", 1)[1].split(
            "function formatOverviewNumber",
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

        renderer = self.script.split("function renderTraineeOverviewDashboard(snapshot) {", 1)[1].split(
            "function renderActiveTraineePage",
            1,
        )[0]
        self.assertIn("renderOverviewFlowGroups(power)", renderer)
        self.assertIn("const { greenPower, greenPowerShare } = overviewGreenMetrics(power);", renderer)
        self.assertIn('setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));', renderer)

    def test_trainee_home_status_strip_hides_redundant_model_refresh_and_solver_items(self):
        status_strip = self.html.split('<dl class="overview-status-metrics trainee-status-metrics">', 1)[1].split("</dl>", 1)[0]

        for label in ("模型", "刷新时刻", "计算状态"):
            self.assertNotIn(f"<dt>{label}</dt>", status_strip)
        for element_id in ("overviewModel", "overviewRefresh", "topologyState"):
            self.assertNotIn(f'id="{element_id}"', status_strip)
            self.assertNotIn(f'"{element_id}"', self.script)

    def test_trainee_home_data_source_uses_detailed_receive_address(self):
        self.assertIn("MODEL_CONTEXTS_STORAGE_KEY", self.script)
        self.assertIn("teacherSnapshotPath: context.teacherSnapshotPath", self.script)
        self.assertIn("function teacherSnapshotPath()", self.script)
        self.assertIn("function teacherReceiveAddress()", self.script)
        self.assertIn("function displayReceiveAddress", self.script)
        self.assertIn("state.teacherSnapshotPath = connection.snapshotPath", self.script)
        self.assertIn("persistActiveModelContext();", self.script)
        self.assertNotIn('localStorage.setItem("polarTeacherSnapshotPath", state.teacherSnapshotPath)', self.script)

        receive_mode_block = self.script.split("function renderReceiveMode", 1)[1].split("function curveMinute", 1)[0]
        self.assertIn("const receiveAddress = teacherReceiveAddress();", receive_mode_block)
        self.assertIn("const receiveAddressText = displayReceiveAddress(receiveAddress);", receive_mode_block)
        self.assertIn("sourceText.title = receiveAddress;", receive_mode_block)
        self.assertIn("sourceText.textContent = receiveAddressText", receive_mode_block)
        self.assertNotIn(": teacherApiBase;", receive_mode_block)

        self.assertIn("#teacherSourceText", self.styles)
        self.assertIn("overflow-wrap: anywhere;", self.styles)

    def test_trainee_home_has_dynamic_flow_styles(self):
        for css_hook in (
            ".overview-dashboard",
            ".overview-status-panel",
            ".overview-energy-board",
            ".energy-flow-map",
            ".energy-grid-forming-stack",
            ".energy-flow-stream",
            ".boundary-list",
            ".overview-event-list",
        ):
            self.assertIn(css_hook, self.styles)
        self.assertNotIn(".quality-list", self.styles)
        self.assertIn("@keyframes energyFlowForward", self.styles)
        self.assertIn("@keyframes energyFlowReverse", self.styles)
        self.assertIn('[data-flow-direction="toBus"]', self.styles)
        self.assertIn('[data-flow-direction="fromBus"]', self.styles)
        self.assertIn('[data-overview-group-wrapper="dcGridFormingStorage"][data-storage-flow="discharge"]', self.styles)
        self.assertIn('[data-overview-group-wrapper="acGridFormingStorage"][data-storage-flow="discharge"]', self.styles)
        self.assertIn("--flow-thickness", self.styles)
        self.assertIn(".energy-green-share {", self.styles)
        self.assertIn(".energy-green-metric {", self.styles)

        converter_block = self.styles.split(".energy-acdc-converter {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", converter_block)
        self.assertIn("left: 50%;", converter_block)
        self.assertIn("top: var(--energy-trunk-y);", converter_block)
        self.assertIn("transform: translate(-50%, -50%);", converter_block)
        self.assertIn('[data-flow-direction="toDc"] .energy-flow-stream', self.styles)
        self.assertIn('["toBus", "fromBus", "toAc", "toDc", "toTank", "fromTank", "idle"]', self.script)
        self.assertIn('trunk.dataset.flowDirection = converterGroup?.flowDirection || "toAc"', self.script)
        self.assertNotIn(".energy-device-heading {", self.styles)
        self.assertNotIn(".energy-load-green-share {", self.styles)

        summary_block = self.styles.split(".energy-green-share {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", summary_block)
        self.assertIn("left: 50%;", summary_block)
        self.assertIn("top: var(--energy-summary-y);", summary_block)
        self.assertIn("width: min(320px, 36%);", summary_block)
        self.assertIn("transform: translate(-50%, -50%);", summary_block)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", summary_block)
        metric_block = self.styles.split(".energy-green-metric {", 1)[1].split("}", 1)[0]
        self.assertIn("justify-items: center;", metric_block)
        self.assertIn("text-align: center;", metric_block)
        divider_block = self.styles.split(".energy-green-metric + .energy-green-metric {", 1)[1].split("}", 1)[0]
        self.assertIn("border-left: 1px solid #dce8ea;", divider_block)
        self.assertNotIn("border-top:", divider_block)
        narrow_block = self.styles.split("@container (max-width: 760px) {", 1)[1].split(
            "@container (max-height: 320px)",
            1,
        )[0]
        self.assertIn(".energy-green-share", narrow_block)
        self.assertIn("position: static;", narrow_block)

    def test_trainee_converter_card_sits_below_the_trunk_icon(self):
        converter_card_block = self.styles.split(".energy-converter-card {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", converter_card_block)
        self.assertIn("top: calc(100% + 7px);", converter_card_block)
        self.assertIn("bottom: auto;", converter_card_block)

        compact_styles = self.styles.split("@container (max-height: 320px) {", 1)[1]
        compact_converter_card = compact_styles.split(".energy-converter-card {", 1)[1].split("}", 1)[0]
        self.assertIn("top: calc(100% + 6px);", compact_converter_card)
        self.assertIn("bottom: auto;", compact_converter_card)

        self.assertNotIn('<div class="energy-column-title">构网储能</div>', self.html)
        self.assertIn('data-overview-group="dcGridFormingStorage"', self.html)
        self.assertIn('data-overview-group="acGridFormingStorage"', self.html)

        compact_summary_block = compact_styles.split(".energy-green-share {", 1)[1].split("}", 1)[0]
        self.assertNotIn("top:", compact_summary_block)

    def test_trainee_grid_forming_storage_stays_between_side_device_columns(self):
        block = self.styles.split(".energy-grid-forming-stack {", 1)[1].split("}", 1)[0]

        self.assertIn("left: var(--energy-bus-inset);", block)
        self.assertIn("right: var(--energy-bus-inset);", block)
        self.assertIn("width: auto;", block)
        self.assertIn("top: var(--energy-forming-y);", block)
        self.assertIn("transform: translateY(-50%);", block)
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="dcGridFormingStorage"] {\n'
            "  grid-column: 1;\n"
            "}",
            self.styles,
        )
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="acGridFormingStorage"] {\n'
            "  grid-column: 2;\n"
            "}",
            self.styles,
        )
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="dcGridFormingStorage"] .energy-storage-branch {\n'
            "  left: 0;\n"
            "  right: auto;\n"
            "}",
            self.styles,
        )
        self.assertIn(
            '.energy-grid-forming-stack [data-overview-group-wrapper="acGridFormingStorage"] .energy-storage-branch {\n'
            "  left: auto;\n"
            "  right: 0;\n"
            "}",
            self.styles,
        )

    def test_trainee_side_device_cards_fit_short_overview_panels(self):
        region_block = self.styles.split(".energy-source-stack {", 1)[1].split("}", 1)[0]
        list_block = self.styles.split(".energy-device-list {", 1)[1].split("}", 1)[0]
        card_block = self.styles.split(".energy-device-card {", 1)[1].split("}", 1)[0]
        value_block = self.styles.split(".energy-device-card strong {", 1)[1].split("}", 1)[0]

        self.assertIn("gap: var(--energy-stack-gap);", region_block)
        self.assertIn("height: 100%;", region_block)
        self.assertIn("justify-content: stretch;", region_block)
        self.assertIn("gap: var(--energy-list-gap);", list_block)
        self.assertIn("flex: 1 1 auto;", list_block)
        self.assertIn("align-content: space-evenly;", list_block)
        self.assertIn("min-height: 76px;", card_block)
        self.assertIn("padding: 9px 10px;", card_block)
        self.assertIn("gap: 4px;", card_block)
        self.assertIn("font-size: 17px;", value_block)
        self.assertIn("white-space: nowrap;", value_block)

    def test_trainee_mobile_overview_expands_to_fit_energy_device_lists(self):
        mobile_styles = self.styles.split("@media (max-width: 820px) {", 1)[1]
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
        self.assertIn("container-type: inline-size;", board_block)
        self.assertIn("align-self: start;", flow_block)

    def test_trainee_home_bottom_tables_have_draggable_height_splitter(self):
        self.assertIn('id="overviewBottomSplitter"', self.html)
        self.assertIn('role="separator"', self.html)
        self.assertIn('aria-orientation="horizontal"', self.html)
        self.assertIn("调整下方表格高度", self.html)
        self.assertIn("--overview-bottom-height", self.styles)
        self.assertIn("--overview-main-min-height: 420px;", self.styles)
        self.assertIn(
            "grid-template-rows: auto minmax(var(--overview-main-min-height), 1fr) "
            "10px minmax(96px, var(--overview-bottom-height));",
            self.styles,
        )
        main_grid_block = self.styles.split(".overview-main-grid {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: var(--overview-main-min-height);", main_grid_block)
        self.assertIn("const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;", self.script)
        self.assertIn("const mainMinHeight = Number.parseFloat", self.script)
        self.assertIn("statusHeight + mainMinHeight + splitterHeight", self.script)
        self.assertIn(".overview-bottom-splitter", self.styles)
        self.assertIn("cursor: row-resize;", self.styles)
        self.assertIn("is-overview-splitter-dragging", self.styles)
        self.assertIn("polarTraineeOverviewBottomHeight", self.script)
        self.assertIn("function initOverviewBottomSplitter", self.script)
        self.assertIn("function applyOverviewBottomHeight", self.script)
        self.assertIn("beginOverviewBottomSplitterDrag", self.script)
        self.assertIn("handleOverviewBottomSplitterKeydown", self.script)

    def test_trainee_home_energy_flow_stays_centered_when_bottom_height_changes(self):
        def css_block(selector: str, text: str = self.styles) -> str:
            marker = f"{selector} {{"
            start = text.index(marker)
            end = text.index("\n}", start)
            return text[start : end + 2]

        board_block = css_block(".overview-energy-board")
        flow_block = css_block(".energy-flow-map")
        source_stack_block = css_block(".energy-source-stack")
        terminal_stack_block = css_block(".energy-terminal-stack")
        device_list_block = css_block(".energy-device-list")
        left_bus_block = css_block(".energy-bus-rail.left")
        right_bus_block = css_block(".energy-bus-rail.right")
        green_summary_block = css_block(".energy-green-share")
        forming_stack_block = css_block(".energy-grid-forming-stack")

        self.assertIn("grid-template-rows: minmax(0, 1fr);", board_block)
        self.assertIn("place-items: center;", board_block)
        self.assertIn("padding: 0;", board_block)
        self.assertIn("border: 0;", board_block)
        self.assertIn("background: transparent;", board_block)
        self.assertIn("height: 100%;", flow_block)
        self.assertIn("align-self: center;", flow_block)
        self.assertIn("container-type: size;", board_block)
        self.assertIn("--energy-edge-inset-y: clamp(10px, 3.5cqh, 28px);", flow_block)
        self.assertIn("--energy-stack-gap: clamp(4px, 1.5cqh, 12px);", flow_block)
        self.assertIn("--energy-list-gap: clamp(3px, 1.25cqh, 10px);", flow_block)
        self.assertIn("--energy-hydrogen-y: 14%;", flow_block)
        self.assertIn("--energy-summary-y: 32%;", flow_block)
        self.assertIn("--energy-trunk-y: 50%;", flow_block)
        self.assertIn("--energy-forming-y: 86%;", flow_block)
        self.assertIn("gap: var(--energy-stack-gap);", source_stack_block)
        self.assertIn("gap: var(--energy-stack-gap);", terminal_stack_block)
        self.assertIn("height: 100%;", source_stack_block)
        self.assertIn("height: 100%;", terminal_stack_block)
        self.assertIn("justify-content: stretch;", source_stack_block)
        self.assertIn("justify-content: stretch;", terminal_stack_block)
        self.assertIn("gap: var(--energy-list-gap);", device_list_block)
        self.assertIn("flex: 1 1 auto;", device_list_block)
        self.assertIn("min-height: 0;", device_list_block)
        self.assertIn("align-content: space-evenly;", device_list_block)
        responsive_bus_height = (
            "height: calc(100% - var(--energy-edge-inset-y) - var(--energy-edge-inset-y));"
        )
        self.assertIn(responsive_bus_height, left_bus_block)
        self.assertIn(responsive_bus_height, right_bus_block)
        self.assertIn("top: var(--energy-summary-y);", green_summary_block)
        self.assertIn("transform: translate(-50%, -50%);", green_summary_block)
        self.assertIn("gap: var(--energy-stack-gap);", forming_stack_block)
        self.assertIn("top: var(--energy-forming-y);", forming_stack_block)
        self.assertIn("transform: translateY(-50%);", forming_stack_block)
        self.assertIn("width: max(22px, calc((100% - var(--energy-storage-card-width)) / 2 + 2px));", self.styles)
        self.assertIn("height: var(--flow-thickness);", self.styles)
        self.assertNotIn("bottom: 178px;", self.styles)
        self.assertNotIn("bottom: 84px;", self.styles)
        self.assertNotIn("padding-bottom: 4px;", self.styles)
        self.assertNotIn("grid-template-rows: auto minmax(340px, 1fr);", self.styles)
        self.assertNotIn(".energy-board-head", self.styles)
        self.assertNotIn(".energy-board-meta", self.styles)
        self.assertNotIn("min-height: 340px;", self.styles)
        self.assertIn("@container (max-height: 320px)", self.styles)
        compact_styles = self.styles.split("@container (max-height: 320px) {", 1)[1]
        self.assertNotIn("--energy-summary-y:", compact_styles)
        self.assertNotIn("--energy-forming-y:", compact_styles)
        self.assertIn("min-height: clamp(38px, 15cqh, 50px);", self.styles)

    def test_trainee_short_desktop_viewports_do_not_compress_the_energy_flow_map(self):
        low_height_styles = self.styles.split(
            "@media (max-height: 780px) and (min-width: 821px) {",
            1,
        )[1].split("@media (max-width: 820px) {", 1)[0]
        dashboard_block = low_height_styles.split(".overview-dashboard {", 1)[1].split("}", 1)[0]
        main_grid_block = low_height_styles.split(".overview-main-grid {", 1)[1].split("}", 1)[0]
        low_height_flow_block = low_height_styles.split(".energy-flow-map {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow-y: auto;", dashboard_block)
        self.assertIn("overflow-x: hidden;", dashboard_block)
        self.assertIn("--overview-main-min-height: 580px;", dashboard_block)
        self.assertIn("min-height: var(--overview-main-min-height);", main_grid_block)
        self.assertIn("height: 100%;", low_height_flow_block)

    def test_trainee_central_rows_keep_fixed_relative_positions_when_height_changes(self):
        flow_block = self.styles.split(".energy-flow-map {", 1)[1].split("}", 1)[0]
        summary_block = self.styles.split(".energy-green-share {", 1)[1].split("}", 1)[0]
        hydrogen_block = self.styles.split(".energy-hydrogen-chain {", 1)[1].split("}", 1)[0]
        medium_block = self.styles.split("@container (max-height: 460px) {", 1)[1].split(
            "@container (max-height: 360px)", 1
        )[0]
        compact_block = self.styles.split("@container (max-height: 320px) {", 1)[1]

        self.assertIn("--energy-hydrogen-y: 14%;", flow_block)
        self.assertIn("--energy-summary-y: 32%;", flow_block)
        self.assertIn("--energy-trunk-y: 50%;", flow_block)
        self.assertIn("--energy-forming-y: 86%;", flow_block)
        self.assertIn("top: var(--energy-summary-y);", summary_block)
        self.assertIn("transform: translate(-50%, -50%);", summary_block)
        self.assertIn("top: var(--energy-hydrogen-y);", hydrogen_block)
        self.assertIn("transform: translateY(-50%);", hydrogen_block)
        for legacy_variable in (
            "--energy-summary-top",
            "--energy-hydrogen-top",
            "--energy-central-upper-shift",
            "--energy-storage-gap",
        ):
            self.assertNotIn(legacy_variable, self.styles)
        for anchor_variable in (
            "--energy-hydrogen-y:",
            "--energy-summary-y:",
            "--energy-trunk-y:",
            "--energy-forming-y:",
        ):
            self.assertNotIn(anchor_variable, medium_block)
            self.assertNotIn(anchor_variable, compact_block)

    def test_trainee_home_storage_cards_connect_horizontally_to_their_own_bus(self):
        def css_block(selector: str, text: str = self.styles) -> str:
            marker = f"{selector} {{"
            start = text.index(marker)
            end = text.index("\n}", start)
            return text[start : end + 2]

        energy_flow_block = css_block(".energy-flow-map")
        trunk_block = css_block(".energy-main-trunk")
        storage_branch_block = css_block(".energy-storage-branch")
        storage_stack_block = css_block(".energy-grid-forming-stack")
        low_height_start = self.styles.index("@media (max-height: 780px)")
        mobile_start = self.styles.index("@media (max-width: 820px)", low_height_start)
        low_height_styles = self.styles[low_height_start:mobile_start]
        low_height_flow_block = css_block(".energy-flow-map", low_height_styles)

        self.assertIn("--energy-trunk-y: 50%;", energy_flow_block)
        self.assertIn("--energy-forming-y: 86%;", energy_flow_block)
        self.assertIn("--energy-bus-inset: clamp(255px, 29.2%, 338px);", energy_flow_block)
        self.assertIn("top: var(--energy-trunk-y);", trunk_block)
        self.assertIn("transform: translateY(-50%);", trunk_block)
        self.assertIn("top: var(--energy-forming-y);", storage_stack_block)
        self.assertIn("transform: translateY(-50%);", storage_stack_block)
        self.assertIn("top: 50%;", storage_branch_block)
        self.assertIn("height: var(--flow-thickness);", storage_branch_block)
        self.assertIn("width: max(22px, calc((100% - var(--energy-storage-card-width)) / 2 + 2px));", storage_branch_block)
        self.assertIn("background-image: repeating-linear-gradient(", storage_branch_block)
        self.assertNotIn("bottom: calc(100% + 2px);", storage_branch_block)
        self.assertIn("height: 100%;", low_height_flow_block)
        self.assertNotIn("--energy-forming-y:", low_height_flow_block)
        self.assertNotIn("top: 40px;", low_height_styles)

    def test_trainee_topbar_removes_send_command_button(self):
        self.assertNotIn("发送指令", self.html)
        self.assertNotIn('id="sendCommands"', self.html)
        self.assertNotIn("sendCommands", self.script)
        self.assertNotIn("#sendCommands", self.styles)


if __name__ == "__main__":
    unittest.main()
