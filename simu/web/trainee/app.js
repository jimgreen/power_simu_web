const apiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
const state = {
  snapshot: null,
  models: [],
  activeModelId: localStorage.getItem("polarTraineeModelId") || "",
  measurementFilter: { dev_type: "all", dev_name: "" },
  runFilter: { dev_type: "all", dev_name: "" },
  setpointFilter: { dev_type: "all", dev_name: "" },
  collapsedDeviceTreeGroups: {},
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
};
const pending = { run_status: new Map(), set_values: new Map() };

const $ = (id) => document.getElementById(id);

function pageFromHash() {
  const fallback = document.querySelector(".app-shell")?.dataset.defaultPage || "overview";
  return (location.hash || "").replace("#", "") || fallback;
}

function showPage(page, updateHash = true) {
  const sections = Array.from(document.querySelectorAll("[data-page]"));
  const target = sections.some((section) => section.dataset.page === page) ? page : "overview";
  sections.forEach((section) => section.classList.toggle("is-active", section.dataset.page === target));
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.navPage === target);
  });
  if (updateHash && location.hash !== `#${target}`) {
    history.replaceState(null, "", `#${target}`);
  }
  requestAnimationFrame(() => drawMeasurementTraceChart());
}

function initPageNavigation() {
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.navPage));
  });
  window.addEventListener("hashchange", () => showPage(pageFromHash(), false));
  showPage(pageFromHash(), false);
}

function modelScopedPath(path) {
  if (!state.activeModelId) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}model_id=${encodeURIComponent(state.activeModelId)}`;
}

async function api(path, options = {}) {
  const { modelScoped = true, ...fetchOptions } = options;
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  const response = await fetch(`${apiBase}${targetPath}`, {
    ...fetchOptions,
    headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
}

function renderModelSelector() {
  const selector = $("modelSelector");
  if (!selector) return;
  const models = state.models.length ? state.models : [{ id: state.activeModelId || "", name: "默认模型" }];
  selector.innerHTML = models.map((model) => `
    <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
  `).join("");
  selector.value = state.activeModelId || models[0]?.id || "";
  selector.disabled = models.length <= 1;
  const active = models.find((model) => model.id === selector.value) || models[0] || {};
  $("activeModelName").textContent = active.name || active.id || "默认模型";
}

function setActiveModel(modelId, shouldRefresh = true) {
  const nextId = modelId || state.models[0]?.id || "";
  state.activeModelId = nextId;
  localStorage.setItem("polarTraineeModelId", nextId);
  pending.run_status.clear();
  pending.set_values.clear();
  state.measurementTraceHistory = [];
  state.selectedMeasurementKey = "";
  state.measurementFilter = { dev_type: "all", dev_name: "" };
  state.runFilter = { dev_type: "all", dev_name: "" };
  state.setpointFilter = { dev_type: "all", dev_name: "" };
  renderModelSelector();
  updatePendingCount();
  if (shouldRefresh) refresh();
}

async function loadModels() {
  try {
    const catalog = await api("/api/models", { modelScoped: false });
    state.models = Array.isArray(catalog.models) ? catalog.models : [];
    const preferred = state.activeModelId || catalog.active_model_id || state.models[0]?.id || "";
    const exists = state.models.some((model) => model.id === preferred);
    setActiveModel(exists ? preferred : state.models[0]?.id || "", false);
  } catch (_error) {
    state.models = [];
    renderModelSelector();
  }
}

async function refresh() {
  try {
    const snapshot = await api("/api/snapshot");
    $("connectionDot").className = "ok";
    $("connectionText").textContent = "在线";
    renderSnapshot(snapshot);
  } catch (_error) {
    $("connectionDot").className = "off";
    $("connectionText").textContent = "离线";
    $("topologyState").textContent = "离线";
  }
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  if (snapshot.model?.id && snapshot.model.id !== state.activeModelId) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock || {});
  const scada = snapshot.measurements?.scada || [];
  const validCount = scada.filter((m) => Number(m.valid) === 1).length;
  $("measureCount").textContent = `${scada.length} 点`;
  $("validCount").textContent = `${validCount} 可用`;
  $("overviewRefresh").textContent = snapshot.clock?.time || "--";
  $("topologyState").textContent = snapshot.result?.solver_info || "在线";
  appendMeasurementTrace(snapshot);
  renderMeasurements(snapshot);
  renderRunControls(snapshot.devices || []);
  renderSetpointControls(snapshot.devices || []);
  renderHistory(snapshot.commands?.history || []);
  updatePendingCount();
}

function renderClock(clock) {
  $("simTime").textContent = clock.time || "00:00:00";
  $("simState").textContent = clock.state || "stopped";
  $("simSpeed").textContent = `x${clock.speed ?? 1}`;
  const readout = document.querySelector(".clock-readout");
  if (readout) readout.dataset.clockState = clock.state || "stopped";
}

function deviceKey(dev) {
  return `${dev.dev_type || dev.type || ""}|${dev.dev_name || dev.name || ""}`;
}

function deviceName(dev) {
  return String(dev.dev_name || dev.name || "");
}

function deviceType(dev) {
  return String(dev.dev_type || dev.type || "Unknown");
}

function deviceIndex(dev) {
  return dev.idx ?? dev.raw?.idx ?? "";
}

function statusText(value) {
  return Number(value) ? "投入" : "退出";
}

function deviceTreeBadge(dev) {
  const run = dev.run_stat ?? dev.raw?.run_stat;
  const status = dev.status ?? dev.raw?.status;
  if (status !== undefined && status !== "") return Number(status) ? "闭合" : "断开";
  if (run !== undefined && run !== "") return Number(run) ? "投入" : "退出";
  return dev.mode || "--";
}

function devicesByType(devices) {
  const groups = new Map();
  devices.forEach((dev) => {
    const type = deviceType(dev);
    if (!groups.has(type)) groups.set(type, []);
    groups.get(type).push(dev);
  });
  return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0], "zh-Hans-CN"));
}

function isDeviceTreeGroupCollapsed(scope, groupKey) {
  return Boolean(state.collapsedDeviceTreeGroups?.[scope]?.[groupKey]);
}

function toggleDeviceTreeGroup(scope, groupKey) {
  if (!scope || !groupKey || groupKey === "all") return;
  if (!state.collapsedDeviceTreeGroups[scope]) state.collapsedDeviceTreeGroups[scope] = {};
  if (state.collapsedDeviceTreeGroups[scope][groupKey]) {
    delete state.collapsedDeviceTreeGroups[scope][groupKey];
  } else {
    state.collapsedDeviceTreeGroups[scope][groupKey] = true;
  }
}

function deviceTreeTypeAttrs(scope, groupKey, isCollapsed) {
  return `
          data-tree-toggle-scope="${escapeHtml(scope)}"
          data-tree-toggle-group="${escapeHtml(groupKey)}"
          aria-expanded="${isCollapsed ? "false" : "true"}"`;
}

function deviceTreeTypeLabel(label) {
  return `
          <span class="tree-title">
            <i class="tree-toggle" aria-hidden="true"></i>
            <span class="tree-title-text">${escapeHtml(label)}</span>
          </span>`;
}

function deviceTreeChildren(isCollapsed, childrenHtml) {
  if (isCollapsed) return "";
  return `
        <div class="tree-children">
          ${childrenHtml}
        </div>`;
}

function renderDeviceTree(containerId, summaryId, devices, filter, scope, dataPrefix) {
  const container = $(containerId);
  if (!container) return;
  const groups = devicesByType(devices);
  const total = devices.length;
  $(summaryId).textContent = `${groups.length} 类 · ${total} 台`;
  const rootActive = filter.dev_type === "all";
  const rootAttr = `data-${dataPrefix}-tree-type="all" data-${dataPrefix}-tree-name=""`;
  const groupHtml = groups.map(([devType, items]) => {
    const isCollapsed = isDeviceTreeGroupCollapsed(scope, devType);
    const typeActive = filter.dev_type === devType && !filter.dev_name;
    const parentActive = filter.dev_type === devType;
    return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${typeActive ? "is-active" : ""} ${parentActive ? "is-parent-active" : ""} ${isCollapsed ? "is-collapsed" : ""}"
          data-${dataPrefix}-tree-type="${escapeHtml(devType)}"
          data-${dataPrefix}-tree-name=""
          ${deviceTreeTypeAttrs(scope, devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => {
          const name = deviceName(dev);
          const isActive = filter.dev_type === devType && filter.dev_name === name;
          return `
            <button
              type="button"
              class="tree-node tree-child ${isActive ? "is-active" : ""}"
              data-${dataPrefix}-tree-type="${escapeHtml(devType)}"
              data-${dataPrefix}-tree-name="${escapeHtml(name)}"
            >
              <span>${escapeHtml(name)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>`;
        }).join(""))}
      </div>`;
  }).join("");
  container.innerHTML = `
    <button type="button" class="tree-node tree-root ${rootActive ? "is-active" : ""}" ${rootAttr}>
      <span>全部设备</span>
      <strong>${total}</strong>
    </button>
    ${groupHtml || '<div class="empty-state">暂无设备</div>'}`;
}

function selectTreeFilter(filterName, devType, devName = "") {
  state[filterName] = { dev_type: devType || "all", dev_name: devName || "" };
  if (filterName === "measurementFilter") renderMeasurements(state.snapshot || {});
  if (filterName === "runFilter") renderRunControls(state.snapshot?.devices || []);
  if (filterName === "setpointFilter") renderSetpointControls(state.snapshot?.devices || []);
}

function filteredDevices(devices, filter) {
  return (devices || []).filter((dev) => {
    if (filter.dev_type && filter.dev_type !== "all" && deviceType(dev) !== filter.dev_type) return false;
    if (filter.dev_name && deviceName(dev) !== filter.dev_name) return false;
    return true;
  });
}

function measurementRows(snapshot = state.snapshot || {}) {
  return snapshot.measurements?.scada || [];
}

function measurementsDevices(snapshot = state.snapshot || {}) {
  const devices = new Map((snapshot.devices || []).map((dev) => [deviceKey(dev), dev]));
  measurementRows(snapshot).forEach((row) => {
    const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
    if (!devices.has(key)) {
      devices.set(key, {
        dev_type: row.dev_type || "Measurement",
        dev_name: row.dev_name || row.name || "",
        run_stat: row.valid,
      });
    }
  });
  return Array.from(devices.values());
}

function measurementKey(meas) {
  return `${meas.idx ?? ""}|${meas.name || ""}|${meas.dev_type || ""}|${meas.dev_name || ""}|${meas.meas_type || ""}`;
}

function filteredMeasurements(rows, filter) {
  return (rows || []).filter((row) => {
    if (filter.dev_type && filter.dev_type !== "all" && row.dev_type !== filter.dev_type) return false;
    if (filter.dev_name && row.dev_name !== filter.dev_name) return false;
    return true;
  });
}

function ensureSelectedMeasurement(rows) {
  const keys = new Set(rows.map((row) => measurementKey(row)));
  if (!state.selectedMeasurementKey || !keys.has(state.selectedMeasurementKey)) {
    state.selectedMeasurementKey = rows.length ? measurementKey(rows[0]) : "";
  }
}

function renderMeasurements(snapshot = state.snapshot || {}) {
  const devices = measurementsDevices(snapshot);
  renderDeviceTree("measurementDeviceTree", "measurementTreeSummary", devices, state.measurementFilter, "measurement", "measurement");
  const allRows = measurementRows(snapshot);
  const rows = filteredMeasurements(allRows, state.measurementFilter);
  ensureSelectedMeasurement(rows);
  const validCount = rows.filter((item) => Number(item.valid) === 1).length;
  $("measurementValidCount").textContent = `${rows.length}/${allRows.length} 点 · 有效 ${validCount} 点`;
  $("measurementTable").innerHTML = `
    <table class="measurement-compare-table">
      <thead><tr><th>idx</th><th>量测名</th><th>设备</th><th>类型</th><th>量测值</th><th>状态</th></tr></thead>
      <tbody>
        ${rows.map((item) => {
          const key = measurementKey(item);
          const valueClass = Math.abs(Number(item.value || 0)) > 10000 ? "value-bad" : Math.abs(Number(item.value || 0)) > 1000 ? "value-warn" : "";
          return `<tr class="${key === state.selectedMeasurementKey ? "is-selected" : ""}" data-measurement-select-key="${escapeHtml(key)}">
            <td>${escapeHtml(item.idx ?? "")}</td>
            <td>${escapeHtml(item.name || "")}</td>
            <td>${escapeHtml(item.dev_name || "")}</td>
            <td>${escapeHtml(item.meas_type || "")}</td>
            <td class="numeric-cell ${valueClass}">${formatNumber(item.value)}</td>
            <td><span class="status-pill ${Number(item.valid) ? "is-ok" : "is-off"}">${Number(item.valid) ? "可用" : "停用"}</span></td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
  drawMeasurementTraceChart();
}

function appendMeasurementTrace(snapshot) {
  const clock = snapshot.clock || {};
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.measurementTraceHistory.length) || 0,
    time: clock.time || "--",
    measurements: {},
  };
  measurementRows(snapshot).forEach((row) => {
    point.measurements[measurementKey(row)] = {
      value: Number(row.value),
      label: `${row.dev_name || row.name || ""} ${row.meas_type || ""}`.trim(),
    };
  });
  state.measurementTraceHistory.push(point);
  state.measurementTraceHistory = state.measurementTraceHistory.slice(-3000);
}

function measurementTraceWindowPoints() {
  const history = state.measurementTraceHistory || [];
  if (!history.length || !state.selectedMeasurementKey) return [];
  const latest = history[history.length - 1].minute;
  const start = latest - Math.max(1, Number(state.measurementTraceWindowMinutes) || 60);
  return history
    .filter((point) => point.minute >= start)
    .map((point) => {
      const item = point.measurements[state.selectedMeasurementKey];
      if (!item || !Number.isFinite(item.value)) return null;
      return { minute: point.minute, time: point.time, value: item.value, label: item.label };
    })
    .filter(Boolean);
}

function resizeCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(620, Math.floor((canvas.clientWidth || 900) * ratio));
  const height = Math.max(260, Math.floor((canvas.clientHeight || 320) * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return { width, height, ratio };
}

function drawMeasurementTraceChart() {
  const canvas = $("measurementTraceChart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  const left = 62 * ratio;
  const right = 24 * ratio;
  const top = 34 * ratio;
  const bottom = 38 * ratio;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1 * ratio;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + (plotHeight * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
  }
  const points = measurementTraceWindowPoints();
  if (!points.length) {
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.fillText("暂无测点跟踪数据", left, top + 30 * ratio);
    $("measurementTraceSummary").textContent = "未选择测点";
    return;
  }
  const values = points.map((point) => point.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const span = Math.max(1e-6, maxValue - minValue);
  const minMinute = points[0].minute;
  const maxMinute = Math.max(points[points.length - 1].minute, minMinute + 1);
  ctx.strokeStyle = "#c93a3a";
  ctx.lineWidth = 2.4 * ratio;
  ctx.beginPath();
  points.forEach((point, idx) => {
    const x = left + ((point.minute - minMinute) / (maxMinute - minMinute)) * plotWidth;
    const y = top + plotHeight - ((point.value - minValue) / span) * plotHeight;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#63717a";
  ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
  ctx.fillText(formatNumber(maxValue), 8 * ratio, top + 4 * ratio);
  ctx.fillText(formatNumber(minValue), 8 * ratio, top + plotHeight);
  ctx.fillText(points[0].time || "", left, height - 12 * ratio);
  ctx.textAlign = "right";
  ctx.fillText(points[points.length - 1].time || "", width - right, height - 12 * ratio);
  ctx.textAlign = "left";
  $("measurementTraceSummary").textContent = `${points[points.length - 1].label || "测点"} · ${points.length} 点`;
}

function renderRunControls(devices) {
  const visibleDevices = filteredDevices(devices, state.runFilter);
  renderDeviceTree("runDeviceTree", "runTreeSummary", devices, state.runFilter, "run", "run");
  $("runControlTable").innerHTML = `
    <table class="runtime-device-table">
      <thead><tr><th>idx</th><th>设备名称</th><th>类型</th><th>当前状态</th><th>下发状态</th></tr></thead>
      <tbody>
        ${visibleDevices.map((dev) => {
          const key = deviceKey(dev);
          const currentRun = Number(pending.run_status.has(key) ? pending.run_status.get(key).run_stat : dev.run_stat);
          return `<tr class="${pending.run_status.has(key) ? "is-pending" : ""}">
            <td>${escapeHtml(deviceIndex(dev))}</td>
            <td>${escapeHtml(deviceName(dev))}</td>
            <td>${escapeHtml(deviceType(dev))}</td>
            <td><span class="status-pill ${Number(dev.run_stat) ? "is-ok" : "is-off"}">${statusText(dev.run_stat)}</span></td>
            <td>
              <label class="inline-toggle">
                <input type="checkbox" data-run-key="${escapeHtml(key)}" ${currentRun ? "checked" : ""} />
                <span>${currentRun ? "投入" : "退出"}</span>
              </label>
            </td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function preferredSetTypes(dev) {
  const types = new Set(dev.set_types || []);
  const selected = [];
  if (types.has("p_set") || types.has("p_ac_set") || types.has("pv0")) selected.push("p_set");
  if (types.has("q_set") || types.has("q_ac_set") || types.has("qv0")) selected.push("q_set");
  if (types.has("v_set") || types.has("v_ac_set")) selected.push("v_set");
  return selected.slice(0, 3);
}

function currentSetValue(dev, setType) {
  const key = `${deviceKey(dev)}|${setType}`;
  if (pending.set_values.has(key)) return pending.set_values.get(key).set_value;
  const exact = dev.set_values?.[setType];
  if (exact !== undefined) return exact;
  const raw = dev.raw || {};
  if (setType === "p_set") return raw.p_set ?? raw.p_ac_set ?? raw.pv0 ?? "";
  if (setType === "q_set") return raw.q_set ?? raw.q_ac_set ?? raw.qv0 ?? "";
  if (setType === "v_set") return raw.v_set ?? raw.v_ac_set ?? "";
  return "";
}

function renderSetpointControls(devices) {
  const adjustable = (devices || []).filter((dev) => preferredSetTypes(dev).length);
  const visibleDevices = filteredDevices(adjustable, state.setpointFilter);
  renderDeviceTree("setpointDeviceTree", "setpointTreeSummary", adjustable, state.setpointFilter, "setpoint", "setpoint");
  $("setpointControlTable").innerHTML = `
    <table class="runtime-device-table setpoint-editor-table">
      <thead><tr><th>idx</th><th>设备名称</th><th>类型</th><th>模式</th><th>P</th><th>Q</th><th>V</th></tr></thead>
      <tbody>
        ${visibleDevices.map((dev) => {
          const setTypes = preferredSetTypes(dev);
          const key = deviceKey(dev);
          return `<tr>
            <td>${escapeHtml(deviceIndex(dev))}</td>
            <td>${escapeHtml(deviceName(dev))}</td>
            <td>${escapeHtml(deviceType(dev))}</td>
            <td>${escapeHtml(dev.mode || "--")}</td>
            ${["p_set", "q_set", "v_set"].map((setType) => {
              const enabled = setTypes.includes(setType);
              const pendingKey = `${key}|${setType}`;
              return `<td>
                <input
                  type="number"
                  step="0.01"
                  data-set-key="${escapeHtml(key)}"
                  data-set-type="${setType}"
                  value="${escapeHtml(currentSetValue(dev, setType))}"
                  ${enabled ? "" : "disabled"}
                  class="${pending.set_values.has(pendingKey) ? "is-pending" : ""}"
                />
              </td>`;
            }).join("")}
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function renderHistory(history) {
  $("historyCount").textContent = history.length;
  $("commandHistory").innerHTML = `
    <table class="runtime-log-table">
      <thead><tr><th>时刻</th><th>来源</th><th>投退</th><th>设值</th><th>内容</th></tr></thead>
      <tbody>
        ${history.slice(-60).reverse().map((item) => `
          <tr>
            <td>${escapeHtml(item.time || "")}</td>
            <td>${escapeHtml(item.source || "student")}</td>
            <td>${escapeHtml(item.accepted?.run_status || 0)}</td>
            <td>${escapeHtml(item.accepted?.set_values || 0)}</td>
            <td>${escapeHtml(JSON.stringify(item.payload || {}))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
  if (!history.length) {
    $("commandHistory").innerHTML = '<div class="empty-state">暂无指令记录</div>';
  }
}

function renderPendingPreview() {
  const runItems = Array.from(pending.run_status.values());
  const setItems = Array.from(pending.set_values.values());
  $("pendingSummary").textContent = `${runItems.length + setItems.length} 项`;
  const rows = [
    ...runItems.map((item) => ({ type: "投退", name: item.dev_name, value: statusText(item.run_stat) })),
    ...setItems.map((item) => ({ type: item.set_type, name: item.dev_name, value: item.set_value })),
  ];
  $("pendingPreview").innerHTML = rows.slice(0, 12).map((item) => `
    <div class="log-item">
      <strong>${escapeHtml(item.name)}</strong>
      <span>${escapeHtml(item.type)} · ${escapeHtml(item.value)}</span>
    </div>
  `).join("") || '<div class="empty-state compact">暂无待发指令</div>';
}

function updatePendingCount() {
  const total = pending.run_status.size + pending.set_values.size;
  $("pendingCount").textContent = total;
  $("runPendingCount").textContent = `${pending.run_status.size} 待发`;
  $("setpointPendingCount").textContent = `${pending.set_values.size} 待发`;
  $("commandState").textContent = total ? "待发送" : "待命";
  $("sendCommands").disabled = total === 0;
  renderPendingPreview();
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (Math.abs(number) >= 100) return number.toFixed(1);
  return number.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function handleTreeClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  const button = target.closest("[data-measurement-tree-type], [data-run-tree-type], [data-setpoint-tree-type]");
  if (!button) return;
  event.preventDefault();
  const toggleScope = button.dataset.treeToggleScope;
  const toggleGroup = button.dataset.treeToggleGroup || "";
  const selection =
    button.dataset.measurementTreeType !== undefined
      ? ["measurementFilter", button.dataset.measurementTreeType, button.dataset.measurementTreeName || ""]
      : button.dataset.runTreeType !== undefined
        ? ["runFilter", button.dataset.runTreeType, button.dataset.runTreeName || ""]
        : button.dataset.setpointTreeType !== undefined
          ? ["setpointFilter", button.dataset.setpointTreeType, button.dataset.setpointTreeName || ""]
          : null;
  requestAnimationFrame(() => {
    if (toggleScope) toggleDeviceTreeGroup(toggleScope, toggleGroup);
    if (selection) selectTreeFilter(selection[0], selection[1], selection[2]);
  });
}

document.addEventListener("click", (event) => {
  handleTreeClick(event);
  const target = event.target instanceof Element ? event.target : null;
  const measurementRow = target?.closest("[data-measurement-select-key]");
  if (measurementRow) {
    const key = measurementRow.dataset.measurementSelectKey || "";
    requestAnimationFrame(() => {
      state.selectedMeasurementKey = key;
      renderMeasurements(state.snapshot || {});
    });
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
  const runKey = target.dataset.runKey;
  if (runKey) {
    const [dev_type, dev_name] = runKey.split("|");
    pending.run_status.set(runKey, { dev_type, dev_name, run_stat: target.checked ? 1 : 0 });
    updatePendingCount();
    renderRunControls(state.snapshot?.devices || []);
  }
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  const setKey = target.dataset.setKey;
  if (setKey) {
    const [dev_type, dev_name] = setKey.split("|");
    const set_type = target.dataset.setType;
    pending.set_values.set(`${setKey}|${set_type}`, {
      dev_type,
      dev_name,
      set_type,
      set_value: Number(target.value),
    });
    target.classList.add("is-pending");
    updatePendingCount();
  }
});

$("sendCommands").addEventListener("click", async () => {
  const body = {
    source: "trainee-ui",
    run_status: Array.from(pending.run_status.values()),
    set_values: Array.from(pending.set_values.values()),
  };
  if (!body.run_status.length && !body.set_values.length) return;
  $("sendCommands").disabled = true;
  await api("/api/student/commands", { method: "POST", body: JSON.stringify(body) });
  pending.run_status.clear();
  pending.set_values.clear();
  updatePendingCount();
  await refresh();
});

$("modelSelector").addEventListener("change", (event) => setActiveModel(event.target.value));
$("measurementTraceWindow").addEventListener("change", (event) => {
  state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
  drawMeasurementTraceChart();
});
window.addEventListener("resize", () => drawMeasurementTraceChart());

initPageNavigation();
loadModels().finally(refresh);
setInterval(refresh, 2000);
