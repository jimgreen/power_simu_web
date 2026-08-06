# 首页能流设备图标与信息卡片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Subagents are not used for this workspace task.

**Goal:** 将模拟台和学员台首页的风、光、储、荷、柴及 AC/DC 变流器改造成“实际设备图标接入能流、独立信息卡片展示实时数据”的布局。

**Architecture:** 保留现有 `data-overview-group` 根节点和 JavaScript 实时渲染入口，仅重构首页能流图的 HTML 与 CSS。侧边设备根节点内部新增信息卡片与 SVG 图标节点，箭头伪元素从根卡片迁移到图标节点；AC/DC 变流器改为图标接入主干、卡片位于下方。模拟台和学员台分别实现相同结构，并由成对回归测试约束一致性。

**Tech Stack:** 静态 HTML、CSS Grid/Flex、内置 SVG `<symbol>/<use>`、原生 JavaScript、Python `unittest/pytest` 字符串结构测试、Codex in-app Browser 页面验收。

---

## 文件职责

- `simu/web/simulator/index.html`：模拟台首页设备图标、信息卡片和图标符号定义。
- `simu/web/simulator/styles.css`：模拟台桌面、低高度宽屏、移动端布局及设备状态样式。
- `simu/web/trainee/index.html`：学员台对应 HTML 结构。
- `simu/web/trainee/styles.css`：学员台对应样式。
- `tests/test_overview_dashboard_ui.py`：模拟台结构、接线、状态和响应式回归测试。
- `tests/test_trainee_overview_dashboard_ui.py`：学员台同等回归测试。
- `simu/web/simulator/app.js`、`simu/web/trainee/app.js`：只读验证现有绑定兼容，不计划修改。

## Task 1: 为实际设备图标与卡片结构建立失败测试

**Files:**
- Modify: `tests/test_overview_dashboard_ui.py`
- Modify: `tests/test_trainee_overview_dashboard_ui.py`

- [x] **Step 1: 添加设备图标符号与分组结构测试**

为两套页面分别断言以下符号存在：

```python
for icon_id in (
    "energy-icon-wind-turbine",
    "energy-icon-solar-array",
    "energy-icon-battery-storage",
    "energy-icon-electric-load",
    "energy-icon-diesel-generator",
    "energy-icon-acdc-converter",
):
    self.assertIn(f'id="{icon_id}"', html)
```

对设备分组建立图标映射：

```python
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
```

每个 `data-overview-group` 片段必须包含：

```python
self.assertIn('class="energy-device-card"', group_html)
self.assertIn('class="energy-device-icon"', group_html)
self.assertIn(f'href="#energy-icon-{icon_name}"', group_html)
self.assertEqual(group_html.count("data-overview-power"), 1)
self.assertEqual(group_html.count("data-overview-meta"), 1)
```

- [x] **Step 2: 添加 AC/DC 变流器上下结构测试**

```python
converter = html.split('data-overview-group="acdcConverter"', 1)[1].split("</article>", 1)[0]
self.assertIn('class="energy-device-icon energy-converter-icon"', converter)
self.assertIn('href="#energy-icon-acdc-converter"', converter)
self.assertIn('class="energy-device-card energy-converter-card"', converter)
self.assertLess(converter.index("energy-converter-icon"), converter.index("energy-converter-card"))
```

- [x] **Step 3: 添加禁止中文单字图元的断言**

```python
for obsolete_badge in (">风<", ">光<", ">储<", ">荷<", ">柴<", ">AC/DC<"):
    self.assertNotIn(obsolete_badge, overview_html)
```

- [x] **Step 4: 运行新增测试并确认红灯**

Run:

```powershell
python -m pytest `
  tests/test_overview_dashboard_ui.py::OverviewDashboardUiTest::test_overview_uses_real_equipment_icons_and_separate_information_cards `
  tests/test_trainee_overview_dashboard_ui.py::TraineeOverviewDashboardUiTest::test_trainee_overview_uses_real_equipment_icons_and_separate_information_cards -q
```

Expected: 两项测试都因缺少 `energy-device-card`、`energy-device-icon` 或图标符号而失败。

## Task 2: 为图标接线、状态和响应式规则建立失败测试

**Files:**
- Modify: `tests/test_overview_dashboard_ui.py`
- Modify: `tests/test_trainee_overview_dashboard_ui.py`

- [x] **Step 1: 添加侧边设备布局测试**

测试 CSS 包含：

```python
self.assertIn('.energy-side-node[data-flow-side="left"]', styles)
self.assertIn('.energy-side-node[data-flow-side="right"]', styles)
self.assertIn("grid-template-columns: minmax(0, 1fr) 42px;", styles)
self.assertIn("grid-template-columns: 42px minmax(0, 1fr);", styles)
```

- [x] **Step 2: 约束箭头必须挂接设备图标**

```python
self.assertIn(".energy-side-node .energy-device-icon::after", styles)
self.assertIn(".energy-side-node .energy-device-icon::before", styles)
self.assertNotIn(".energy-side-node::after", styles)
self.assertNotIn(".energy-side-node::before", styles)
```

- [x] **Step 3: 添加构网储能图标朝向测试**

```python
self.assertIn(
    '[data-overview-group-wrapper="dcGridFormingStorage"] .energy-device.storage',
    styles,
)
self.assertIn(
    '[data-overview-group-wrapper="acGridFormingStorage"] .energy-device.storage',
    styles,
)
self.assertIn("grid-template-columns: 42px minmax(0, 1fr);", styles)
self.assertIn("grid-template-columns: minmax(0, 1fr) 42px;", styles)
```

- [x] **Step 4: 添加状态和移动端测试**

```python
self.assertIn('.energy-device[data-operating-state="retired"] .energy-device-icon', styles)
self.assertIn('.energy-device[data-operating-state="deadIsland"] .energy-device-card', styles)
self.assertIn('.energy-device[data-operating-state="unmeasured"] .energy-device-icon', styles)
self.assertIn(".energy-side-node .energy-device-icon::before", mobile_or_container_styles)
self.assertIn("display: none;", mobile_or_container_styles)
```

- [x] **Step 5: 添加 JavaScript 不重建设备节点测试**

从 `renderOverviewFlowGroups` 函数提取代码块并断言：

```python
self.assertNotIn("innerHTML", renderer)
self.assertIn('node.querySelector("[data-overview-power]")', renderer)
self.assertIn('node.querySelector("[data-overview-meta]")', renderer)
```

- [x] **Step 6: 运行新增 CSS/JS 测试并确认红灯**

Expected: 测试因箭头仍挂在 `.energy-side-node`、缺少图标状态规则而失败。

## Task 3: 实现模拟台设备图标和信息卡片 HTML

**Files:**
- Modify: `simu/web/simulator/index.html:106-211`
- Test: `tests/test_overview_dashboard_ui.py`

- [x] **Step 1: 添加内置 SVG 图标符号表**

在 `.energy-flow-map` 内加入不可见符号表：

```html
<svg class="energy-icon-defs" aria-hidden="true">
  <defs>
    <symbol id="energy-icon-wind-turbine" viewBox="0 0 28 28">
      <path d="M14 12v13M10 25h8"/><circle cx="14" cy="10" r="2"/>
      <path d="M14 8 12 2c3 0 5 2 4 5M12.5 11l-6 2c0-3 2-5 5-4M15.5 11l4 5c-3 1-6-1-5-4"/>
    </symbol>
    <symbol id="energy-icon-solar-array" viewBox="0 0 28 28">
      <path d="M5 7h18l2 12H3L5 7ZM9 7 8 19M14 7v12M19 7l1 12M4 13h20M11 23h6M14 19v4"/>
    </symbol>
    <symbol id="energy-icon-battery-storage" viewBox="0 0 28 28">
      <rect x="4" y="7" width="19" height="15" rx="2"/><path d="M23 12h2v5h-2M8 11v7M12 11v7M16 11v7M20 11v7"/>
    </symbol>
    <symbol id="energy-icon-electric-load" viewBox="0 0 28 28">
      <path d="M9 3v7M19 3v7M7 10h14v4a7 7 0 0 1-14 0v-4ZM14 21v4M10 25h8M15 11l-3 5h4l-3 5"/>
    </symbol>
    <symbol id="energy-icon-diesel-generator" viewBox="0 0 28 28">
      <rect x="3" y="7" width="22" height="15" rx="2"/><circle cx="10" cy="14.5" r="4"/>
      <path d="M10 12v5M8 14.5h4M16 11h6M16 15h6M16 19h4M6 24v-2M22 24v-2"/>
    </symbol>
    <symbol id="energy-icon-acdc-converter" viewBox="0 0 36 36">
      <rect x="4" y="5" width="28" height="26" rx="3"/><path d="M7 18h22M9 12h8M11 9v6M21 11c2-3 5-3 7 0M21 25h7M24 22v6M15 16l3 2-3 2M21 20l-3-2 3-2"/>
    </symbol>
  </defs>
</svg>
```

图形路径采用已确认草图中的风机、光伏阵列、电池、负荷、柴油发电机和变流器形状。

- [x] **Step 2: 改造所有侧边设备分组**

示例：

```html
<article class="energy-device wind energy-side-node" data-overview-group="dcWind" data-flow-side="left" data-flow-active="false" data-flow-direction="idle" hidden>
  <div class="energy-device-card">
    <span>直流并网风电</span>
    <strong data-overview-power>--</strong>
    <small data-overview-meta>等待量测</small>
  </div>
  <div class="energy-device-icon" role="img" aria-label="风力发电机">
    <svg aria-hidden="true" viewBox="0 0 28 28"><use href="#energy-icon-wind-turbine"></use></svg>
  </div>
</article>
```

对直流风电、光伏、跟网储能、直流负荷、交流风电、光伏、跟网储能、交流负荷和柴油发电逐项替换。

- [x] **Step 3: 改造构网储能分组**

保留 `energy-storage-branch-wrap` 和 `energy-storage-branch`，只将内部储能设备改为图标与卡片结构。DC 构网储能图标位于靠直流母线的一侧，AC 构网储能图标位于靠交流母线的一侧。

- [x] **Step 4: 改造 AC/DC 变流器**

```html
<article class="energy-device converter energy-acdc-converter" data-overview-group="acdcConverter" data-flow-side="center" data-flow-active="false" data-flow-direction="idle" hidden>
  <div class="energy-device-icon energy-converter-icon" role="img" aria-label="AC/DC变流器">
    <svg aria-hidden="true" viewBox="0 0 36 36"><use href="#energy-icon-acdc-converter"></use></svg>
  </div>
  <div class="energy-device-card energy-converter-card">
    <span>AC/DC变流器</span>
    <strong data-overview-power>--</strong>
    <small data-overview-meta>等待量测</small>
  </div>
</article>
```

- [x] **Step 5: 运行模拟台 HTML 结构测试**

Expected: HTML 结构测试通过，CSS 行为测试仍失败。

## Task 4: 实现模拟台图标、卡片和接线 CSS

**Files:**
- Modify: `simu/web/simulator/styles.css:917-1560`
- Test: `tests/test_overview_dashboard_ui.py`

- [x] **Step 1: 将设备根节点重置为布局容器**

```css
.energy-side-node {
  min-height: 50px;
  padding: 0;
  display: grid;
  align-items: center;
  gap: 7px;
  overflow: visible;
  border: 0;
  background: transparent;
}
.energy-side-node[data-flow-side="left"] {
  grid-template-columns: minmax(0, 1fr) 42px;
}
.energy-side-node[data-flow-side="right"] {
  grid-template-columns: 42px minmax(0, 1fr);
}
```

- [x] **Step 2: 创建信息卡片和图标节点样式**

```css
.energy-device-card {
  min-width: 0;
  min-height: 50px;
  padding: 5px 9px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  border: 1px solid #ced9dd;
  border-left: 3px solid var(--flow-color);
  border-radius: 5px;
  background: #fff;
}
.energy-device-icon {
  position: relative;
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border: 1px solid var(--flow-color);
  border-radius: 5px;
  background: #f7fbf9;
  color: var(--flow-color);
}
```

- [x] **Step 3: 把侧边连接线和箭头迁移到图标伪元素**

将现有 `.energy-side-node::before/::after` 规则逐项替换为以下图标接线规则：

```css
.energy-side-node .energy-device-icon::before,
.energy-side-node .energy-device-icon::after {
  content: "";
  position: absolute;
  top: 50%;
  pointer-events: none;
}
.energy-side-node .energy-device-icon::after {
  width: 42px;
  height: var(--flow-thickness);
  transform: translateY(-50%);
  border-radius: 999px;
  background-color: var(--flow-color);
  opacity: var(--flow-opacity);
  animation: energyFlowForward var(--flow-duration) linear infinite;
}
.energy-side-node[data-flow-side="left"] .energy-device-icon::after { right: -44px; }
.energy-side-node[data-flow-side="right"] .energy-device-icon::after { left: -44px; }
.energy-side-node[data-flow-side="left"][data-flow-direction="toBus"] .energy-device-icon::before {
  right: -49px;
  transform: translateY(-50%);
  border-top: var(--flow-head-half) solid transparent;
  border-bottom: var(--flow-head-half) solid transparent;
  border-left: var(--flow-head-size) solid var(--flow-color);
}
.energy-side-node[data-flow-side="right"][data-flow-direction="fromBus"] .energy-device-icon::before {
  left: -9px;
  transform: translateY(-50%);
  border-top: var(--flow-head-half) solid transparent;
  border-bottom: var(--flow-head-half) solid transparent;
  border-left: var(--flow-head-size) solid var(--flow-color);
}
```

左侧图标向右延伸，右侧图标向左延伸；充电、放电、发电和用电方向继续使用根节点 `data-flow-direction`。

- [x] **Step 4: 调整构网储能结构**

DC 构网储能使用：

```css
grid-template-columns: 42px minmax(0, 1fr);
```

AC 构网储能使用：

```css
grid-template-columns: minmax(0, 1fr) 42px;
```

现有 `energy-storage-branch` 继续连接母线与设备根节点边缘，根节点边缘处必须是设备图标。

- [x] **Step 5: 调整 AC/DC 变流器结构**

```css
.energy-acdc-converter {
  top: var(--energy-trunk-y);
  transform: translate(-50%, -26px);
  padding: 0;
  display: grid;
  justify-items: center;
  border: 0;
  background: transparent;
}
.energy-converter-icon { width: 52px; height: 52px; }
.energy-converter-card { width: 100%; margin-top: 7px; text-align: center; }
```

- [x] **Step 6: 迁移运行状态样式**

为 `.energy-device-icon` 和 `.energy-device-card` 添加退运、死岛和无量测规则。根节点的 `filter` 和 `opacity` 继续统一作用于图标、卡片和箭头。

- [x] **Step 7: 更新响应式规则**

容器窄屏时隐藏：

```css
.energy-side-node .energy-device-icon::before,
.energy-side-node .energy-device-icon::after { display: none; }
```

保留设备根节点内部的图标与卡片布局。低高度桌面压缩卡片内边距和字体，不隐藏图标。

- [x] **Step 8: 运行模拟台完整 UI 测试**

Run:

```powershell
python -m pytest tests/test_overview_dashboard_ui.py -q
```

Expected: 全部通过。

## Task 5: 将已验证结构同步到学员台

**Files:**
- Modify: `simu/web/trainee/index.html:74-179`
- Modify: `simu/web/trainee/styles.css:1024-1670`
- Test: `tests/test_trainee_overview_dashboard_ui.py`

- [x] **Step 1: 同步 SVG 符号定义和所有设备 HTML 结构**

图标 ID、设备分组映射、可访问名称和 AC/DC 变流器结构必须与模拟台一致。

- [x] **Step 2: 同步图标、卡片、箭头、构网储能和状态 CSS**

除现有文件上下文差异外，关键选择器和属性值与模拟台一致。

- [x] **Step 3: 运行学员台 UI 测试**

Run:

```powershell
python -m pytest tests/test_trainee_overview_dashboard_ui.py -q
```

Expected: 全部通过。

## Task 6: 验证实时绑定、回归和代码质量

**Files:**
- Verify: `simu/web/simulator/app.js`
- Verify: `simu/web/trainee/app.js`
- Test: `tests/test_power_flow_log_summary.py`
- Test: `tests/test_overview_dashboard_ui.py`
- Test: `tests/test_trainee_overview_dashboard_ui.py`

- [x] **Step 1: 运行 JavaScript 语法检查**

```powershell
node --check simu/web/simulator/app.js
node --check simu/web/trainee/app.js
```

Expected: 两项退出码均为 0。

- [x] **Step 2: 运行相关完整回归**

```powershell
python -m pytest `
  tests/test_power_flow_log_summary.py `
  tests/test_overview_dashboard_ui.py `
  tests/test_trainee_overview_dashboard_ui.py -q
```

Expected: 0 failures。

- [x] **Step 3: 检查本次文件空白错误**

```powershell
git diff --check -- `
  simu/web/simulator/index.html `
  simu/web/simulator/styles.css `
  simu/web/trainee/index.html `
  simu/web/trainee/styles.css `
  tests/test_overview_dashboard_ui.py `
  tests/test_trainee_overview_dashboard_ui.py
```

Expected: 无 trailing whitespace 或 conflict marker。

## Task 7: 浏览器视觉与交互验收

**URLs:**
- Simulator: `http://127.0.0.1:8710/`
- Trainee: `http://127.0.0.1:8720/`

- [x] **Step 1: 验收模拟台常规桌面**

检查页面身份、有效内容、无错误覆盖层、控制台健康和截图。验证设备图标接线、卡片方向、等高母线和 AC/DC 上图标下卡片。

- [x] **Step 2: 验收学员台常规桌面**

重复相同检查，并确认实时接收数据能更新图标旁卡片。

- [x] **Step 3: 验收低高度宽屏**

使用 `2048x766` 视口检查两套页面：

- 图标不与卡片重叠。
- 首尾设备接入点不被母线截断。
- AC/DC 卡片不遮挡主干线。
- 构网储能卡片不遮挡侧边设备。

- [x] **Step 4: 验收移动端**

使用 `390x844` 视口检查：

- 母线和箭头隐藏。
- 图标与信息卡片保持可读。
- 设备文字不溢出、不遮挡后续内容。
- AC/DC 变流器仍为上图标、下卡片。

- [x] **Step 5: 验证实时刷新不重建设备节点**

在浏览器页面作用域保存一个设备根节点引用，等待至少一次实时刷新，再比较同一选择器返回值是否严格等于原引用。预期为 `true`。

## Task 8: 完成状态说明

- [x] **Step 1: 更新计划复选框和执行状态**

记录红灯、绿灯、完整回归和浏览器验收结果。

- [x] **Step 2: 不执行 Git 提交、推送或 WEB 重启**

本任务未收到 Git 或服务重启指令。保留工作区已有修改，最终说明本次改动文件和验证证据。

## 执行记录（2026-08-06）

- TDD：实际设备图标、独立信息卡片、图标接线、状态样式、移动端展开、防 Flex 压缩和低高度桌面防裁剪测试均先验证失败，再完成最小实现并转绿。
- 自动化测试：`tests/test_overview_dashboard_ui.py` 与 `tests/test_trainee_overview_dashboard_ui.py` 共 `49 passed`；相关完整回归共 `59 passed`。
- 代码检查：模拟台和学员台 `app.js` 均通过 `node --check`；六个相关 HTML/CSS/测试文件通过 `git diff --check`，仅输出工作区既有的 LF/CRLF 转换提示。
- 浏览器验收：两端均通过 `1280x720`、`2048x766` 和 `390x844` 检查；设备无裁剪、图标与卡片无重叠，移动端各区域纵向顺序正确且无水平溢出。
- 母线延长复验：交流、直流母线统一使用 `calc(100% - 24px)`，在 `320px` 能流画布中高度为 `296px`，在 `390px` 画布中高度为 `366px`；两侧构网储能支路中心线均位于对应母线范围内。
- 实时刷新：模拟台和学员台等待多个刷新周期后，设备根节点、图标节点和信息卡片节点均保持同一 DOM 引用。
- 交付边界：未提交 Git、未推送远端、未重启 WEB 服务。
