const apiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
const teacherApiBase = (
  window.POLAR_TEACHER_API_URL ||
  localStorage.getItem("polarTeacherApiUrl") ||
  "http://127.0.0.1:8710"
).replace(/\/$/, "");
const state = {
  snapshot: null,
  models: [],
  activeModelId: localStorage.getItem("polarTraineeModelId") || "",
  receiveMode: false,
  frozen: false,
  receiveEpoch: 0,
  lastReceiveAt: "",
  snapshotSource: "",
  lastTeacherSnapshotLogKey: "",
  runtimeLogs: [],
  runtimeLogTypeFilter: "all",
  runtimeLogSeq: 0,
  seenCommandHistoryKeys: new Set(),
  modelFilter: { dev_type: "all", dev_name: "" },
  activeModelParamTab: "",
  activeCurveDisplayKey: "wind_speed_mps",
  selectedCurveDisplayKeys: ["wind_speed_mps"],
  curveDisplayCursor: { visible: false, x: 0, y: 0, index: 0 },
  lastCurveDisplayTableKey: "",
  remoteControlDevice: null,
  remoteControlSending: false,
  remoteAdjustment: null,
  remoteAdjustmentSending: false,
  measurementFilter: { dev_type: "all", dev_name: "" },
  controlFilter: { dev_type: "all", dev_name: "" },
  activeControlTab: "remote-control",
  collapsedDeviceTreeGroups: {},
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  traceRunId: null,
  renewableControl: {
    enabled: false,
    intervalSeconds: 2,
    socMin: 0.3,
    socMax: 0.9,
    sending: false,
    lastClockKey: "",
    lastAutoAtMs: 0,
    lastPlan: null,
    lastSentAt: "",
    lastStatus: "请先启动接收模式，再启动实时控制。",
  },
};
const pending = { run_status: new Map(), set_values: new Map() };
const CONTROL_COMMAND_VALID_MINUTES = 5;
const TRACE_HISTORY_LIMIT = 45000;
const CURVE_DISPLAY_MODES = {
  year: { key: "year", label: "年仿真", pointCount: 8760, stepMinutes: 60, tableTitle: "年曲线数据表", tableSummary: "1小时间隔 · 只读" },
  day: { key: "day", label: "日仿真", pointCount: 1440, stepMinutes: 1, tableTitle: "日曲线数据表", tableSummary: "1分钟间隔 · 只读" },
};
const CURVE_DISPLAY_ENV_KEYS = ["wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"];
const CURVE_DISPLAY_META = [
  { key: "wind_speed_mps", label: "风速", color: "#008c8c", min: 0, max: 50, digits: 2, unit: "m/s" },
  { key: "solar_irradiance_w_m2", label: "太阳辐照", color: "#b87500", min: 0, max: 1100, digits: 1, unit: "W/m2" },
  { key: "air_temp_c", label: "气温", color: "#2b6b7f", min: -60, max: 20, digits: 2, unit: "℃" },
];
const CURVE_DISPLAY_LOAD_META = { label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" };
const CURVE_DISPLAY_LOAD_COLORS = ["#c93a3a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_DISPLAY_PLOT = { left: 58, right: 24, top: 46, bottom: 34 };

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
  requestAnimationFrame(() => {
    if (target === "model") renderTraineeModelPage();
    if (target === "curves") renderCurveDisplay(state.snapshot || {}, true);
    drawMeasurementTraceChart();
  });
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

function teacherScopedPath(path) {
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

async function teacherApi(path, options = {}) {
  const targetPath = teacherScopedPath(path);
  const response = await fetch(`${teacherApiBase}${targetPath}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
}

function apiErrorText(error) {
  try {
    return JSON.parse(error.message)?.error || error.message;
  } catch (_parseError) {
    return error.message || "操作失败";
  }
}

function runtimeLogTime() {
  return new Date().toLocaleTimeString();
}

function addRuntimeLog(type, target, result, detail = "", level = "info", renderNow = true) {
  state.runtimeLogSeq += 1;
  state.runtimeLogs.unshift({
    seq: state.runtimeLogSeq,
    wall_time: runtimeLogTime(),
    type,
    target,
    result,
    detail,
    level,
  });
  state.runtimeLogs = state.runtimeLogs.slice(0, 300);
  if (renderNow) renderHistory();
}

function runtimeLogDetailText(detail) {
  if (Array.isArray(detail)) return detail.filter(Boolean).join("；");
  if (detail && typeof detail === "object") {
    return Object.entries(detail)
      .map(([key, value]) => `${key}: ${value}`)
      .join("；");
  }
  return String(detail || "");
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 32768;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function setImportStatus(text, kind = "") {
  const target = $("importStatus");
  if (!target) return;
  target.textContent = text || "";
  target.classList.toggle("is-error", kind === "error");
  target.classList.toggle("is-ok", kind === "ok");
}

async function importDefinitionArchive(file) {
  if (!file) return;
  const button = $("importDefinitionsButton");
  if (button) {
    button.disabled = true;
    button.textContent = "导入中";
  }
  setImportStatus(file.name);
  addRuntimeLog("模型交互", "学员台 /api/models/import-definitions", "开始导入", file.name);
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const result = await api("/api/models/import-definitions", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, data_base64: dataBase64 }),
    });
    state.receiveMode = false;
    state.receiveEpoch += 1;
    state.frozen = false;
    state.snapshot = null;
    setImportStatus(`已导入 ${result.imported?.curve_points || 0} 点曲线`, "ok");
    addRuntimeLog(
      "模型交互",
      "学员台 /api/models/import-definitions",
      "导入成功",
      `曲线 ${result.imported?.curve_points || 0} 点；负荷 ${result.imported?.load_count || 0} 类`,
      "ok",
    );
    await loadModels();
    await refresh();
  } catch (error) {
    setImportStatus(apiErrorText(error), "error");
    addRuntimeLog("模型交互", "学员台 /api/models/import-definitions", "导入失败", apiErrorText(error), "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "导入定义";
    }
    const input = $("definitionArchiveInput");
    if (input) input.value = "";
  }
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
  state.frozen = false;
  pending.run_status.clear();
  pending.set_values.clear();
  state.measurementTraceHistory = [];
  state.traceRunId = null;
  state.selectedMeasurementKey = "";
  state.modelFilter = { dev_type: "all", dev_name: "" };
  state.activeModelParamTab = "";
  state.activeCurveDisplayKey = "wind_speed_mps";
  state.selectedCurveDisplayKeys = ["wind_speed_mps"];
  state.curveDisplayCursor = { visible: false, x: 0, y: 0, index: 0 };
  state.lastCurveDisplayTableKey = "";
  state.measurementFilter = { dev_type: "all", dev_name: "" };
  state.controlFilter = { dev_type: "all", dev_name: "" };
  state.activeControlTab = "remote-control";
  if (shouldRefresh) stopRenewableControl("模型已切换，策略已停止。", true);
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
  if (state.receiveMode) {
    await refreshFromTeacher(state.receiveEpoch);
    return;
  }
  if (state.frozen) {
    renderReceiveMode();
    return;
  }
  try {
    const snapshot = await api("/api/snapshot");
    $("connectionDot").className = "ok";
    $("connectionText").textContent = "在线";
    state.snapshotSource = "local";
    renderSnapshot(snapshot);
  } catch (_error) {
    $("connectionDot").className = "off";
    $("connectionText").textContent = "离线";
    $("topologyState").textContent = "离线";
  }
}

async function refreshFromTeacher(epoch = state.receiveEpoch) {
  try {
    const snapshot = await teacherApi("/api/snapshot");
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    state.lastReceiveAt = new Date().toLocaleTimeString();
    state.snapshotSource = "teacher";
    const logKey = renewableClockKey(snapshot);
    if (logKey !== state.lastTeacherSnapshotLogKey) {
      const valuesNow = currentWeatherLoad(snapshot);
      const scada = snapshot.measurements?.scada || [];
      addRuntimeLog(
        "实时交互",
        "模拟台 /api/snapshot",
        "接收成功",
        [
          `仿真时刻 ${snapshot.clock?.time || "--"}`,
          `量测 ${scada.length} 点`,
          `风速 ${formatNumber(valuesNow.windSpeed)} m/s`,
          `光照 ${formatNumber(valuesNow.solarIrradiance)} W/m2`,
          `负荷 ${formatNumber(valuesNow.loadKw)} kW`,
        ],
        "ok",
        false,
      );
      state.lastTeacherSnapshotLogKey = logKey;
    }
    renderSnapshot(snapshot);
    renderReceiveMode();
  } catch (_error) {
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    $("connectionDot").className = "off";
    $("connectionText").textContent = "教员离线";
    $("topologyState").textContent = "教员离线";
    addRuntimeLog("实时交互", "模拟台 /api/snapshot", "接收失败", apiErrorText(_error), "error");
    renderReceiveMode("接收失败");
  }
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  if (snapshot.model?.id && snapshot.model.id !== state.activeModelId) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock || {});
  const runId = Number(snapshot.clock?.run_id ?? 0);
  if (state.traceRunId !== null && runId !== state.traceRunId) {
    state.measurementTraceHistory = [];
    state.selectedMeasurementKey = "";
  }
  state.traceRunId = runId;
  const displayMeasurements = measurementDisplayRows(snapshot);
  const validCount = displayMeasurements.filter((m) => Number(m.valid) === 1).length;
  $("measureCount").textContent = `${displayMeasurements.length} 点`;
  $("validCount").textContent = `${validCount} 可用`;
  $("overviewRefresh").textContent = snapshot.clock?.time || "--";
  $("topologyState").textContent = snapshot.result?.solver_info || "在线";
  renderTeacherWeather(snapshot);
  renderReceiveMode();
  renderTraineeModelPage(snapshot);
  if (document.querySelector('[data-page="curves"]')?.classList.contains("is-active")) {
    renderCurveDisplay(snapshot);
  }
  appendMeasurementTrace(snapshot);
  renderMeasurements(snapshot);
  renderCombinedControlPage(snapshot.devices || []);
  renderRenewableControl(snapshot);
  syncCommandHistoryLogs(snapshot.commands?.history || []);
  renderHistory();
  updatePendingCount();
  maybeRunRenewableControl(snapshot);
}

function renderReceiveMode(extraText = "") {
  const button = $("traineeRunToggle");
  const stateText = $("receiveStateText");
  const sourceText = $("teacherSourceText");
  const connectionDot = $("connectionDot");
  const connectionText = $("connectionText");
  if (button) {
    button.textContent = state.receiveMode ? "停止接收" : "启动接收";
    button.classList.toggle("is-running", state.receiveMode);
  }
  if (connectionDot && connectionText) {
    connectionDot.className = extraText ? "off" : state.receiveMode ? "ok" : state.frozen ? "" : "ok";
    connectionText.textContent = extraText || (state.receiveMode ? "接收中" : state.frozen ? "已冻结" : "在线");
  }
  if (stateText) {
    const label = state.receiveMode ? "运行接收" : state.frozen ? "已冻结" : "本地待命";
    stateText.textContent = extraText || label;
  }
  if (sourceText) {
    sourceText.textContent = state.receiveMode
      ? `${teacherApiBase} · ${state.lastReceiveAt || "--"}`
      : state.frozen
        ? `冻结于 ${state.lastReceiveAt || "--"}`
        : teacherApiBase;
  }
}

function curveMinute(snapshot) {
  const curves = snapshot.curves || {};
  const clock = snapshot.clock || {};
  if (String(curves.mode || "").toLowerCase() === "year") {
    return Number(clock.absolute_minute ?? clock.minute ?? 0) || 0;
  }
  return Number(clock.minute ?? 0) || 0;
}

function interpolateCurve(points, minute, key, defaultValue = 0) {
  const pairs = (points || [])
    .map((point) => ({ minute: Number(point.minute), value: Number(point[key]) }))
    .filter((point) => Number.isFinite(point.minute) && Number.isFinite(point.value))
    .sort((left, right) => left.minute - right.minute);
  if (!pairs.length) return defaultValue;
  if (pairs.length === 1) return pairs[0].value;
  const target = Number(minute) || 0;
  let left = pairs[0];
  let right = pairs[pairs.length - 1];
  for (let idx = 0; idx < pairs.length - 1; idx += 1) {
    if (pairs[idx].minute <= target && target <= pairs[idx + 1].minute) {
      left = pairs[idx];
      right = pairs[idx + 1];
      break;
    }
  }
  if (target <= pairs[0].minute) return pairs[0].value;
  if (target >= pairs[pairs.length - 1].minute) return pairs[pairs.length - 1].value;
  const span = Math.max(1e-9, right.minute - left.minute);
  return left.value + ((target - left.minute) / span) * (right.value - left.value);
}

function renderTeacherWeather(snapshot) {
  const valuesNow = currentWeatherLoad(snapshot);
  const values = {
    teacherWind: `${formatNumber(valuesNow.windSpeed)} m/s`,
    teacherSolar: `${formatNumber(valuesNow.solarIrradiance)} W/m2`,
    teacherTemp: `${formatNumber(valuesNow.airTemp)} ℃`,
    teacherLoad: `${formatNumber(valuesNow.loadKw)} kW`,
    teacherWeatherTime: snapshot.clock?.time || "--",
  };
  Object.entries(values).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
}

function toNumber(value, defaultValue = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : defaultValue;
}

function clamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

function commandNumber(value) {
  const number = Math.abs(value) < 0.0005 ? 0 : value;
  return Number(number.toFixed(3));
}

function currentWeatherLoad(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const minute = curveMinute(snapshot);
  const weather = curves.weather || [];
  const loads = curves.loads || {};
  let loadTotal = Object.values(loads).reduce((total, points) => (
    total + interpolateCurve(points, minute, "p_kw", 0)
  ), 0);
  if (!Number.isFinite(loadTotal) || loadTotal <= 0) {
    loadTotal = estimateLoadFromDevices(snapshot.devices || []);
  }
  return {
    minute,
    windSpeed: interpolateCurve(weather, minute, "wind_speed_mps", 0),
    solarIrradiance: interpolateCurve(weather, minute, "solar_irradiance_w_m2", 0),
    airTemp: interpolateCurve(weather, minute, "air_temp_c", 25),
    loadKw: loadTotal,
  };
}

function curveDisplayMode(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const rawMode = String(curves.mode || "").toLowerCase();
  if (CURVE_DISPLAY_MODES[rawMode]) return rawMode;
  const pointCount = Number(curves.point_count || curves.weather?.length || 0);
  return pointCount > 2000 ? "year" : "day";
}

function curveDisplayConfig(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  const defaults = CURVE_DISPLAY_MODES[mode];
  const curves = snapshot.curves || {};
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  const maxLoadCount = Object.values(loads).reduce((maxCount, points) => (
    Math.max(maxCount, Array.isArray(points) ? points.length : 0)
  ), 0);
  const pointCount = Math.max(
    1,
    Number(curves.point_count || 0) || Math.max(Array.isArray(curves.weather) ? curves.weather.length : 0, maxLoadCount, defaults.pointCount),
  );
  const stepMinutes = Math.max(1, Number(curves.time_step_minutes || defaults.stepMinutes) || defaults.stepMinutes);
  return { ...defaults, pointCount, stepMinutes, durationMinutes: pointCount * stepMinutes };
}

function curveDisplayPointMinute(index, snapshot = state.snapshot || {}) {
  return index * curveDisplayConfig(snapshot).stepMinutes;
}

function curveDisplayLoadKey(loadName) {
  return `load:${loadName || "load"}`;
}

function curveDisplayLoadName(key) {
  return String(key || "").replace(/^load:/, "") || "load";
}

function curveDisplayLoads(snapshot = state.snapshot || {}) {
  const names = new Set(Object.keys(snapshot.curves?.loads || {}));
  (snapshot.devices || []).forEach((dev) => {
    if (["ACLoad", "DCLoad"].includes(deviceType(dev)) && deviceName(dev)) {
      names.add(deviceName(dev));
    }
  });
  return Array.from(names).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
}

function curveDisplayLoadKeys(snapshot = state.snapshot || {}) {
  return curveDisplayLoads(snapshot).map(curveDisplayLoadKey);
}

function curveDisplayAllKeys(snapshot = state.snapshot || {}) {
  return [...CURVE_DISPLAY_ENV_KEYS, ...curveDisplayLoadKeys(snapshot)];
}

function curveDisplayRawPoints(key, snapshot = state.snapshot || {}) {
  if (String(key).startsWith("load:")) {
    const loadName = curveDisplayLoadName(key);
    const points = snapshot.curves?.loads?.[loadName];
    return Array.isArray(points) ? points : [];
  }
  return Array.isArray(snapshot.curves?.weather) ? snapshot.curves.weather : [];
}

function curveDisplayPointValue(point, key) {
  if (!point) return null;
  if (String(key).startsWith("load:")) {
    return Number(point.p_kw ?? point.value ?? point.load_kw);
  }
  return Number(point[key]);
}

function curveDisplayMetaForKey(key, snapshot = state.snapshot || {}) {
  const meta = CURVE_DISPLAY_META.find((item) => item.key === key);
  if (meta) return meta;
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const loadIndex = Math.max(0, loadKeys.indexOf(key));
  const values = curveDisplayRawPoints(key, snapshot)
    .map((point) => curveDisplayPointValue(point, key))
    .filter((value) => Number.isFinite(value));
  const dynamicMax = values.length ? Math.max(...values) * 1.12 : CURVE_DISPLAY_LOAD_META.max;
  return {
    ...CURVE_DISPLAY_LOAD_META,
    key,
    label: curveDisplayLoadName(key),
    color: CURVE_DISPLAY_LOAD_COLORS[loadIndex % CURVE_DISPLAY_LOAD_COLORS.length],
    max: Math.max(CURVE_DISPLAY_LOAD_META.max, dynamicMax, 1),
  };
}

function curveDisplayRoundValue(key, value, snapshot = state.snapshot || {}) {
  const meta = curveDisplayMetaForKey(key, snapshot);
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Number(numeric.toFixed(meta.digits));
}

function interpolateCurveDisplay(points, minute, key, defaultValue = 0) {
  const pairs = (points || [])
    .map((point, index) => ({
      minute: Number(point.minute ?? index),
      value: curveDisplayPointValue(point, key),
    }))
    .filter((point) => Number.isFinite(point.minute) && Number.isFinite(point.value))
    .sort((left, right) => left.minute - right.minute);
  if (!pairs.length) return defaultValue;
  if (pairs.length === 1) return pairs[0].value;
  const target = Number(minute) || 0;
  if (target <= pairs[0].minute) return pairs[0].value;
  if (target >= pairs[pairs.length - 1].minute) return pairs[pairs.length - 1].value;
  for (let idx = 0; idx < pairs.length - 1; idx += 1) {
    const left = pairs[idx];
    const right = pairs[idx + 1];
    if (left.minute <= target && target <= right.minute) {
      const span = Math.max(1e-9, right.minute - left.minute);
      return left.value + ((target - left.minute) / span) * (right.value - left.value);
    }
  }
  return defaultValue;
}

function curveDisplaySeries(key, snapshot = state.snapshot || {}) {
  const config = curveDisplayConfig(snapshot);
  const points = curveDisplayRawPoints(key, snapshot);
  const meta = curveDisplayMetaForKey(key, snapshot);
  if (points.length === config.pointCount) {
    return points.map((point) => curveDisplayRoundValue(key, curveDisplayPointValue(point, key) ?? meta.min, snapshot));
  }
  return Array.from({ length: config.pointCount }, (_unused, index) => (
    curveDisplayRoundValue(key, interpolateCurveDisplay(points, curveDisplayPointMinute(index, snapshot), key, meta.min), snapshot)
  ));
}

function selectedCurveDisplayKeys(snapshot = state.snapshot || {}) {
  const available = new Set(curveDisplayAllKeys(snapshot));
  const selected = Array.from(new Set(state.selectedCurveDisplayKeys || []))
    .filter((key) => available.has(key));
  if (!selected.length && available.has(state.activeCurveDisplayKey)) selected.push(state.activeCurveDisplayKey);
  if (!selected.length) selected.push("wind_speed_mps");
  state.selectedCurveDisplayKeys = selected;
  if (!selected.includes(state.activeCurveDisplayKey)) {
    state.activeCurveDisplayKey = selected[selected.length - 1] || "wind_speed_mps";
  }
  return selected;
}

function curveDisplayFamilyKeys(family, snapshot = state.snapshot || {}) {
  if (family === "environment") return [...CURVE_DISPLAY_ENV_KEYS];
  if (family === "load") return curveDisplayLoadKeys(snapshot);
  return [];
}

function setCurveDisplaySelection(keys, activeKey = keys?.[keys.length - 1], shouldRender = true) {
  const available = new Set(curveDisplayAllKeys(state.snapshot || {}));
  const selected = Array.from(new Set(keys || [])).filter((key) => available.has(key));
  if (!selected.length) selected.push("wind_speed_mps");
  state.selectedCurveDisplayKeys = selected;
  state.activeCurveDisplayKey = selected.includes(activeKey) ? activeKey : selected[selected.length - 1] || "wind_speed_mps";
  state.lastCurveDisplayTableKey = "";
  if (shouldRender) renderCurveDisplay(state.snapshot || {}, true);
}

function selectCurveDisplayButton(button) {
  if (!button) return;
  const keys = button.dataset.curveDisplayFamily
    ? curveDisplayFamilyKeys(button.dataset.curveDisplayFamily, state.snapshot || {})
    : button.dataset.curveDisplayKey ? [button.dataset.curveDisplayKey] : [];
  setCurveDisplaySelection(keys, button.dataset.curveDisplayKey || keys[0], true);
}

function curveDisplaySelectedLabel(snapshot = state.snapshot || {}) {
  const selected = selectedCurveDisplayKeys(snapshot);
  return selected.length <= 1 ? curveDisplayMetaForKey(selected[0], snapshot).label : `已选${selected.length}条`;
}

function renderCurveDisplayTree(snapshot = state.snapshot || {}) {
  const container = $("curveDisplayTree");
  if (!container) return;
  const selected = selectedCurveDisplayKeys(snapshot);
  const selectedSet = new Set(selected);
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const envSelected = CURVE_DISPLAY_ENV_KEYS.every((key) => selectedSet.has(key))
    && selected.every((key) => CURVE_DISPLAY_ENV_KEYS.includes(key));
  const loadSelected = loadKeys.length && loadKeys.every((key) => selectedSet.has(key))
    && selected.every((key) => loadKeys.includes(key));
  const envPartial = CURVE_DISPLAY_ENV_KEYS.some((key) => selectedSet.has(key));
  const loadPartial = loadKeys.some((key) => selectedSet.has(key));
  $("curveDisplayTreeSummary").textContent = `${CURVE_DISPLAY_ENV_KEYS.length + loadKeys.length} 条`;
  container.innerHTML = `
    <div class="tree-group">
      <button
        type="button"
        class="tree-node tree-type ${envSelected ? "is-active" : envPartial ? "is-parent-active" : ""}"
        data-curve-display-tree-type="environment"
        data-curve-display-family="environment"
      >
        <span>环境曲线</span>
        <strong>${CURVE_DISPLAY_ENV_KEYS.length}</strong>
      </button>
      <div class="tree-children">
        ${CURVE_DISPLAY_ENV_KEYS.map((key) => {
          const meta = curveDisplayMetaForKey(key, snapshot);
          const shortLabel = key === "wind_speed_mps" ? "风" : key === "solar_irradiance_w_m2" ? "光" : "温";
          return `
            <button
              type="button"
              class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""}"
              data-curve-display-tree-type="environment"
              data-curve-display-key="${escapeHtml(key)}"
            >
              <span>${shortLabel}</span>
              <small>${escapeHtml(meta.unit)}</small>
            </button>`;
        }).join("")}
      </div>
    </div>
    <div class="tree-group">
      <button
        type="button"
        class="tree-node tree-type ${loadSelected ? "is-active" : loadPartial ? "is-parent-active" : ""}"
        data-curve-display-tree-type="load"
        data-curve-display-family="load"
      >
        <span>负荷曲线</span>
        <strong>${loadKeys.length}</strong>
      </button>
      <div class="tree-children">
        ${loadKeys.map((key) => `
          <button
            type="button"
            class="tree-node tree-child ${selectedSet.has(key) ? "is-active" : ""}"
            data-curve-display-tree-type="load"
            data-curve-display-key="${escapeHtml(key)}"
          >
            <span>${escapeHtml(curveDisplayLoadName(key))}</span>
            <small>kW</small>
          </button>
        `).join("") || '<div class="empty-state compact">暂无负荷曲线</div>'}
      </div>
    </div>`;
}

function renderCurveDisplayModeControls(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  document.querySelectorAll("[data-curve-display-mode]").forEach((button) => {
    const active = button.dataset.curveDisplayMode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = true;
  });
}

function formatCurveDisplayTableTime(minute, snapshot = state.snapshot || {}) {
  if (curveDisplayMode(snapshot) === "year") {
    const dayOfYear = Math.floor(minute / 1440);
    const hour = Math.floor((minute % 1440) / 60);
    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let month = 0;
    let day = dayOfYear;
    while (month < monthDays.length - 1 && day >= monthDays[month]) {
      day -= monthDays[month];
      month += 1;
    }
    return `${String(month + 1).padStart(2, "0")}-${String(day + 1).padStart(2, "0")} ${String(hour).padStart(2, "0")}:00`;
  }
  const total = Math.round(minute);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function renderCurveDisplayLabels(snapshot = state.snapshot || {}) {
  const config = curveDisplayConfig(snapshot);
  const pointCount = $("curveDisplayPointCount");
  const status = $("curveDisplayStatus");
  const activeLabel = $("curveDisplayActiveLabel");
  const tableTitle = $("curveDisplayTableTitle");
  const tableSummary = $("curveDisplayTableSummary");
  if (pointCount) pointCount.textContent = `${config.pointCount}点`;
  if (status) status.textContent = `${config.label} · 只读`;
  if (activeLabel) activeLabel.textContent = curveDisplaySelectedLabel(snapshot);
  if (tableTitle) tableTitle.textContent = config.tableTitle;
  if (tableSummary) tableSummary.textContent = config.tableSummary;
}

function resizeCurveDisplayCanvas() {
  const canvas = $("curveDisplayChart");
  if (!canvas) return false;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.round(rect.width || canvas.clientWidth || canvas.width));
  const height = Math.max(240, Math.round(rect.height || canvas.clientHeight || canvas.height));
  if (canvas.width === width && canvas.height === height) return false;
  canvas.width = width;
  canvas.height = height;
  return true;
}

function curveDisplayPlot(canvas) {
  if (canvas.width < 640) return { left: 34, right: 12, top: 58, bottom: 30 };
  return CURVE_DISPLAY_PLOT;
}

function curveDisplayValueToY(value, meta, canvas) {
  const plot = curveDisplayPlot(canvas);
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const span = Math.max(1e-9, meta.max - meta.min);
  const ratio = (clamp(value, meta.min, meta.max) - meta.min) / span;
  return bottom - ratio * (bottom - top);
}

function drawCurveDisplayXAxis(ctx, canvas, plot, snapshot = state.snapshot || {}) {
  const width = canvas.width;
  const height = canvas.height;
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (curveDisplayMode(snapshot) === "year") {
    const monthStarts = [["01月", 0], ["02月", 31], ["03月", 59], ["04月", 90], ["05月", 120], ["06月", 151], ["07月", 181], ["08月", 212], ["09月", 243], ["10月", 273], ["11月", 304], ["12月", 334]];
    const monthStep = width < 560 ? 3 : width < 900 ? 2 : 1;
    monthStarts.forEach(([label, day], index) => {
      if (index % monthStep !== 0) return;
      const x = left + (day / 365) * (right - left);
      ctx.strokeStyle = index % 3 === 0 ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      ctx.fillText(label, x - 12, height - 12);
    });
    ctx.textAlign = "right";
    ctx.fillText("年末", right, height - 12);
    ctx.textAlign = "left";
    return;
  }
  const hourStep = width < 480 ? 4 : width < 820 ? 3 : 2;
  for (let hour = 0; hour <= 24; hour += hourStep) {
    const x = left + (hour / 24) * (right - left);
    ctx.strokeStyle = hour % 6 === 0 ? "#c9d6dc" : "#e7eef1";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.fillText(`${String(hour).padStart(2, "0")}:00`, x - 14, height - 12);
  }
}

function curveDisplayPointIndexFromX(x, canvas, snapshot = state.snapshot || {}) {
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const pointCount = curveDisplayConfig(snapshot).pointCount;
  return clamp(Math.round(((x - left) / Math.max(1, right - left)) * (pointCount - 1)), 0, pointCount - 1);
}

function curveDisplayXFromPointIndex(index, canvas, snapshot = state.snapshot || {}) {
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const pointCount = curveDisplayConfig(snapshot).pointCount;
  return left + (clamp(index, 0, pointCount - 1) / Math.max(1, pointCount - 1)) * (right - left);
}

function drawCurveDisplayCursor(ctx, canvas, plot, metas, seriesByKey, snapshot = state.snapshot || {}) {
  const cursor = state.curveDisplayCursor;
  if (!cursor.visible || !metas.length) return;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const index = clamp(cursor.index, 0, curveDisplayConfig(snapshot).pointCount - 1);
  const x = curveDisplayXFromPointIndex(index, canvas, snapshot);
  const y = clamp(cursor.y, top, bottom);
  const tooltipMetas = metas.slice(0, 6);
  const timeLabel = formatCurveDisplayTableTime(curveDisplayPointMinute(index, snapshot), snapshot);

  ctx.save();
  ctx.strokeStyle = "rgba(29, 57, 66, 0.58)";
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  ctx.moveTo(left, y);
  ctx.lineTo(right, y);
  ctx.stroke();
  ctx.setLineDash([]);

  tooltipMetas.forEach((meta) => {
    const values = seriesByKey.get(meta.key) || [];
    if (!values.length) return;
    const markerY = curveDisplayValueToY(values[index], meta, canvas);
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, markerY, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  ctx.font = "12px Microsoft YaHei, Arial";
  const lines = [
    `时刻: ${timeLabel}`,
    `点号: ${index + 1}`,
    ...tooltipMetas.map((meta) => `${meta.label}: ${formatNumber(seriesByKey.get(meta.key)?.[index])} ${meta.unit}`),
    metas.length > tooltipMetas.length ? `另有 ${metas.length - tooltipMetas.length} 条曲线` : "",
  ].filter(Boolean);
  const tooltipWidth = Math.max(158, ...lines.map((line) => ctx.measureText(line).width + 24));
  const tooltipHeight = 14 + lines.length * 18;
  let tooltipX = x + 14;
  let tooltipY = y + 14;
  if (tooltipX + tooltipWidth > right - 6) tooltipX = x - tooltipWidth - 14;
  if (tooltipY + tooltipHeight > bottom - 6) tooltipY = y - tooltipHeight - 14;
  tooltipX = clamp(tooltipX, left + 6, right - tooltipWidth - 6);
  tooltipY = clamp(tooltipY, top + 6, bottom - tooltipHeight - 6);
  ctx.fillStyle = "rgba(255, 255, 255, 0.96)";
  ctx.strokeStyle = "rgba(171, 190, 198, 0.9)";
  ctx.beginPath();
  ctx.roundRect(tooltipX, tooltipY, tooltipWidth, tooltipHeight, 8);
  ctx.fill();
  ctx.stroke();
  lines.forEach((line, lineIndex) => {
    ctx.fillStyle = lineIndex < 2 ? "#1f3037" : "#314850";
    ctx.fillText(line, tooltipX + 10, tooltipY + 18 + lineIndex * 18);
  });
  ctx.restore();
}

function drawCurveDisplay(snapshot = state.snapshot || {}) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return;
  resizeCurveDisplayCanvas();
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const metas = selectedCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
  const seriesByKey = new Map(metas.map((meta) => [meta.key, curveDisplaySeries(meta.key, snapshot)]));
  const legendColumns = width < 560 ? 2 : Math.max(1, metas.length);
  const legendColumnWidth = (right - left) / legendColumns;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d8e1e5";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  for (let i = 0; i <= 5; i += 1) {
    const y = top + i * ((bottom - top) / 5);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  drawCurveDisplayXAxis(ctx, canvas, plot, snapshot);
  metas.forEach((meta, metaIndex) => {
    const values = seriesByKey.get(meta.key) || [];
    const stride = Math.max(1, Math.floor(values.length / Math.max(1, (right - left) * 1.4)));
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < values.length; i += stride) {
      const x = left + (i / Math.max(1, values.length - 1)) * (right - left);
      const y = curveDisplayValueToY(values[i], meta, canvas);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    if (values.length) ctx.lineTo(right, curveDisplayValueToY(values[values.length - 1], meta, canvas));
    ctx.stroke();
    const legendX = left + (metaIndex % legendColumns) * legendColumnWidth;
    const legendY = 20 + Math.floor(metaIndex / legendColumns) * 16;
    ctx.fillStyle = meta.color;
    ctx.fillRect(legendX, legendY, 18, 3);
    ctx.fillStyle = "#63717a";
    ctx.fillText(`${meta.label} (${meta.unit})`, legendX + 26, legendY + 4);
  });
  drawCurveDisplayCursor(ctx, canvas, plot, metas, seriesByKey, snapshot);
}

function renderCurveDisplayTable(snapshot = state.snapshot || {}, force = false) {
  const container = $("curveDisplayTable");
  if (!container) return;
  const config = curveDisplayConfig(snapshot);
  const metas = selectedCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
  const seriesByKey = new Map(metas.map((meta) => [meta.key, curveDisplaySeries(meta.key, snapshot)]));
  const signature = JSON.stringify({
    model: state.activeModelId,
    mode: config.key,
    points: config.pointCount,
    selected: metas.map((meta) => meta.key),
    source: `${snapshot.curves?.weather?.length || 0}|${Object.values(snapshot.curves?.loads || {}).map((points) => points?.length || 0).join(",")}`,
  });
  if (!force && signature === state.lastCurveDisplayTableKey) return;
  state.lastCurveDisplayTableKey = signature;
  container.innerHTML = `
    <table class="curve-table curve-display-table">
      <thead>
        <tr>
          <th>时刻</th>
          ${metas.map((meta) => `<th>${escapeHtml(meta.label)}<small>${escapeHtml(meta.unit)}</small></th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${Array.from({ length: config.pointCount }, (_unused, index) => `
          <tr>
            <td>${formatCurveDisplayTableTime(curveDisplayPointMinute(index, snapshot), snapshot)}</td>
            ${metas.map((meta) => `<td class="numeric-cell">${formatNumber(seriesByKey.get(meta.key)?.[index])}</td>`).join("")}
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renderCurveDisplay(snapshot = state.snapshot || {}, forceTable = false) {
  const container = $("curveDisplayTree");
  if (!container) return;
  if (!snapshot?.curves) {
    container.innerHTML = '<div class="empty-state">暂无曲线数据</div>';
    $("curveDisplayTable").innerHTML = '<div class="empty-state">暂无曲线数据</div>';
    return;
  }
  renderCurveDisplayTree(snapshot);
  renderCurveDisplayModeControls(snapshot);
  renderCurveDisplayLabels(snapshot);
  drawCurveDisplay(snapshot);
  renderCurveDisplayTable(snapshot, forceTable);
}

function pointerPositionOnCurveDisplayCanvas(event) {
  const canvas = $("curveDisplayChart");
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
}

function setCurveDisplayCursorFromEvent(event, shouldDraw = true) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return;
  const pos = pointerPositionOnCurveDisplayCanvas(event);
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) {
    state.curveDisplayCursor = { visible: false, x: pos.x, y: pos.y, index: state.curveDisplayCursor.index || 0 };
  } else {
    state.curveDisplayCursor = {
      visible: true,
      x: clamp(pos.x, left, right),
      y: clamp(pos.y, top, bottom),
      index: curveDisplayPointIndexFromX(pos.x, canvas, state.snapshot || {}),
    };
  }
  if (shouldDraw) drawCurveDisplay(state.snapshot || {});
}

function hideCurveDisplayCursor() {
  if (!state.curveDisplayCursor.visible) return;
  state.curveDisplayCursor.visible = false;
  drawCurveDisplay(state.snapshot || {});
}

function estimateLoadFromDevices(devices) {
  return (devices || []).reduce((total, dev) => {
    if (!["ACLoad", "DCLoad"].includes(deviceType(dev)) || !isDeviceOnline(dev)) return total;
    const raw = dev.raw || {};
    const values = dev.set_values || {};
    return total + toNumber(values.p_set ?? raw.pv0 ?? raw.p_set ?? 0, 0);
  }, 0);
}

function deviceMap(snapshot = state.snapshot || {}) {
  return new Map((snapshot.devices || []).map((dev) => [deviceKey(dev), dev]));
}

function isDeviceOnline(dev) {
  if (!dev) return false;
  return Number(dev.run_stat ?? 1) === 1 && Number(dev.status ?? 1) !== 0;
}

function parameterRows(snapshot, blockName) {
  const params = snapshot.device_parameters || {};
  const rows = params[blockName] || params[blockName.toLowerCase()] || params[blockName.toUpperCase()] || [];
  return Array.isArray(rows) ? rows : [];
}

function parameterName(row) {
  return String(row?.name || row?.dev_name || "");
}

function availableWithBounds(value, row) {
  const pMin = toNumber(row?.p_min, 0);
  const pMax = toNumber(row?.p_max, value);
  return clamp(Math.max(0, value), Math.max(0, pMin), Math.max(0, pMax || value));
}

function windAvailablePower(row, weather) {
  const speed = Math.max(0, weather.windSpeed);
  const ratedPower = Math.max(0, toNumber(row.rated_power ?? row.p_max, 10));
  const ratedSpeed = Math.max(toNumber(row.rated_wind_speed, 15), toNumber(row.cut_in_speed, 5) + 1e-9);
  const cutIn = Math.max(0, toNumber(row.cut_in_speed, 5));
  const cutOut = Math.max(cutIn + 1e-9, toNumber(row.cut_out_speed, 50));
  if (speed < cutIn || speed >= cutOut || ratedPower <= 0) return 0;
  if (speed >= ratedSpeed) return availableWithBounds(ratedPower, row);
  return availableWithBounds(ratedPower * ((speed - cutIn) / (ratedSpeed - cutIn)) ** 3, row);
}

function pvAvailablePower(row, weather) {
  const ratedPower = Math.max(0, toNumber(row.rated_power ?? row.p_max, 0));
  const refIrradiance = Math.max(1e-9, toNumber(row.reference_irradiance, 1000));
  const refTemp = toNumber(row.reference_temperature, 25);
  const tempCoef = toNumber(row.temp_coefficient, 0);
  const irradianceScale = Math.max(0, weather.solarIrradiance) / refIrradiance;
  const tempScale = Math.max(0, 1 + tempCoef * (weather.airTemp - refTemp));
  return availableWithBounds(ratedPower * irradianceScale * tempScale, row);
}

function renewableDeviceRows(snapshot, weather) {
  const map = deviceMap(snapshot);
  const rows = [];
  parameterRows(snapshot, "wind_generator").forEach((param, idx) => {
    const name = parameterName(param) || `wt${String(idx + 1).padStart(2, "0")}_rect`;
    const dev = map.get(`DCACConverter|${name}`);
    rows.push({
      category: "风电",
      dev_type: "DCACConverter",
      dev_name: name,
      online: isDeviceOnline(dev),
      availableKw: isDeviceOnline(dev) ? windAvailablePower(param, weather) : 0,
      set_type: "p_set",
    });
  });
  parameterRows(snapshot, "pv_generator").forEach((param, idx) => {
    const name = parameterName(param) || `pv${String(idx + 1).padStart(2, "0")}_dcdc`;
    const dev = map.get(`DCDCConverter|${name}`);
    rows.push({
      category: "光伏",
      dev_type: "DCDCConverter",
      dev_name: name,
      online: isDeviceOnline(dev),
      availableKw: isDeviceOnline(dev) ? pvAvailablePower(param, weather) : 0,
      set_type: "p_set",
    });
  });
  if (rows.length) return rows;
  (snapshot.devices || []).forEach((dev) => {
    const name = deviceName(dev);
    const type = deviceType(dev);
    if (type === "DCACConverter" && /^wt/i.test(name)) {
      rows.push({ category: "风电", dev_type: type, dev_name: name, online: isDeviceOnline(dev), availableKw: toNumber(dev.raw?.p_ac_set ?? dev.set_values?.p_set, 0), set_type: "p_set" });
    }
    if (type === "DCDCConverter" && /^pv/i.test(name)) {
      rows.push({ category: "光伏", dev_type: type, dev_name: name, online: isDeviceOnline(dev), availableKw: toNumber(dev.raw?.p_set ?? dev.set_values?.p_set, 0), set_type: "p_set" });
    }
  });
  return rows;
}

function storageDeviceRows(snapshot) {
  const map = deviceMap(snapshot);
  const essByName = new Map((snapshot.devices || [])
    .filter((dev) => deviceType(dev) === "ESS")
    .map((dev) => [deviceName(dev), dev]));
  const stepHours = Math.max(1 / 60, toNumber(snapshot.clock?.step_minutes, 1) / 60);
  const configuredMin = clamp(toNumber(state.renewableControl.socMin, 0.3), 0, 1);
  const configuredMax = clamp(toNumber(state.renewableControl.socMax, 0.9), configuredMin, 1);
  const params = parameterRows(snapshot, "estorage");
  const rows = params.length ? params : Array.from(essByName.values()).map((dev) => ({ name: deviceName(dev) }));
  return rows.map((param, idx) => {
    const name = parameterName(param) || deviceName(Array.from(essByName.values())[idx]) || `ess${String(idx + 1).padStart(2, "0")}`;
    const dcdcName = `${name}_dcdc`;
    const dcdc = map.get(`DCDCConverter|${dcdcName}`);
    const ess = essByName.get(name);
    const soc = clamp(toNumber(ess?.soc_curr ?? param.soc_cur ?? param.soc_curr, 0.5), 0, 1);
    const capacityKwh = Math.max(1e-9, toNumber(param.emva ?? param.capacity_kwh, 50));
    const socMin = clamp(Math.max(toNumber(param.soc_min, 0), configuredMin), 0, 1);
    const socMax = clamp(Math.min(toNumber(param.soc_max, 1), configuredMax), socMin, 1);
    const chargeMax = Math.max(0, toNumber(param.charge_p_max, 20));
    const dischargeMax = Math.max(0, toNumber(param.dis_charge_p_max ?? param.discharge_p_max, 20));
    const chargePower = Math.max(0, Math.min(chargeMax, ((socMax - soc) * capacityKwh) / stepHours));
    const dischargePower = Math.max(0, Math.min(dischargeMax, ((soc - socMin) * capacityKwh) / stepHours));
    return {
      category: "储能",
      dev_type: "DCDCConverter",
      dev_name: dcdcName,
      source_name: name,
      online: isDeviceOnline(dcdc) && isDeviceOnline(ess || dcdc),
      soc,
      socMin,
      socMax,
      chargePower,
      dischargePower,
      set_type: "p_set",
    };
  });
}

function allocateByCapacity(items, total, capacityKey) {
  const target = Math.max(0, total);
  const totalCapacity = items.reduce((sum, item) => sum + Math.max(0, toNumber(item[capacityKey], 0)), 0);
  if (target <= 0 || totalCapacity <= 0) return items.map(() => 0);
  return items.map((item) => Math.min(toNumber(item[capacityKey], 0), target * toNumber(item[capacityKey], 0) / totalCapacity));
}

function renewableClockKey(snapshot) {
  const clock = snapshot.clock || {};
  return `${clock.absolute_minute ?? clock.minute ?? ""}|${clock.time || ""}`;
}

function calculateRenewableControlPlan(snapshot = state.snapshot || {}) {
  const weather = currentWeatherLoad(snapshot);
  const renewableRows = renewableDeviceRows(snapshot, weather);
  const storageRows = storageDeviceRows(snapshot);
  const availableRenewable = renewableRows.reduce((sum, row) => sum + row.availableKw, 0);
  const windAvailable = renewableRows.filter((row) => row.category === "风电").reduce((sum, row) => sum + row.availableKw, 0);
  const pvAvailable = renewableRows.filter((row) => row.category === "光伏").reduce((sum, row) => sum + row.availableKw, 0);
  const totalChargePower = storageRows.filter((row) => row.online).reduce((sum, row) => sum + row.chargePower, 0);
  const totalDischargePower = storageRows.filter((row) => row.online).reduce((sum, row) => sum + row.dischargePower, 0);
  const loadKw = Math.max(0, weather.loadKw);
  let renewableTarget = 0;
  let storageTarget = 0;
  let dieselResidual = 0;
  let curtailKw = 0;

  if (availableRenewable >= loadKw) {
    renewableTarget = Math.min(availableRenewable, loadKw + totalChargePower);
    storageTarget = -Math.min(totalChargePower, Math.max(0, renewableTarget - loadKw));
    curtailKw = Math.max(0, availableRenewable - renewableTarget);
  } else {
    renewableTarget = availableRenewable;
    storageTarget = Math.min(totalDischargePower, loadKw - availableRenewable);
    dieselResidual = Math.max(0, loadKw - renewableTarget - storageTarget);
  }

  const renewableAllocations = allocateByCapacity(renewableRows, renewableTarget, "availableKw");
  const storageAllocations = storageTarget < 0
    ? allocateByCapacity(storageRows.filter((row) => row.online), -storageTarget, "chargePower").map((value) => -value)
    : allocateByCapacity(storageRows.filter((row) => row.online), storageTarget, "dischargePower");
  const onlineStorage = storageRows.filter((row) => row.online);
  const storageByName = new Map(onlineStorage.map((row, idx) => [row.dev_name, storageAllocations[idx] || 0]));

  const commandRows = [
    ...renewableRows.map((row, idx) => ({ ...row, commandKw: renewableAllocations[idx] || 0 })),
    ...storageRows.map((row) => ({ ...row, availableKw: row.online ? Math.max(row.chargePower, row.dischargePower) : 0, commandKw: storageByName.get(row.dev_name) || 0 })),
  ];
  const commands = commandRows
    .filter((row) => row.online)
    .map((row) => ({
      dev_type: row.dev_type,
      dev_name: row.dev_name,
      set_type: row.set_type,
      set_value: commandNumber(row.commandKw),
    }));
  return {
    clockKey: renewableClockKey(snapshot),
    time: snapshot.clock?.time || "--",
    weather,
    commandRows,
    commands,
    metrics: {
      availableRenewable,
      windAvailable,
      pvAvailable,
      storageChargeAvailable: totalChargePower,
      storageDischargeAvailable: totalDischargePower,
      renewableTarget,
      storageTarget,
      dieselResidual,
      curtailKw,
      loadKw,
    },
  };
}

function renewableDecisionDetail(plan) {
  const metrics = plan?.metrics || {};
  return [
    `时刻 ${plan?.time || "--"}`,
    `负荷 ${formatNumber(metrics.loadKw)} kW`,
    `风电可用 ${formatNumber(metrics.windAvailable)} kW`,
    `光伏可用 ${formatNumber(metrics.pvAvailable)} kW`,
    `储能可充 ${formatNumber(metrics.storageChargeAvailable)} kW`,
    `储能可放 ${formatNumber(metrics.storageDischargeAvailable)} kW`,
    `计划消纳 ${formatNumber(metrics.renewableTarget)} kW`,
    `储能指令 ${formatNumber(metrics.storageTarget)} kW`,
    `柴油缺额 ${formatNumber(metrics.dieselResidual)} kW`,
    `弃风弃光 ${formatNumber(metrics.curtailKw)} kW`,
  ];
}

function renderRenewableControl(snapshot = state.snapshot || {}) {
  const control = state.renewableControl;
  const plan = snapshot ? calculateRenewableControlPlan(snapshot) : control.lastPlan;
  control.lastPlan = plan;
  const button = $("renewableAutoToggle");
  if (!button) return;
  const sendOnce = $("renewableSendOnce");
  const stateNode = $("renewableControlState");
  const summary = $("renewableCommandSummary");
  const hasTeacherSnapshot = state.receiveMode && state.snapshotSource === "teacher";
  button.textContent = control.enabled ? "停止实时控制" : "启动实时控制";
  button.classList.toggle("is-running", control.enabled);
  button.disabled = control.sending;
  if (sendOnce) sendOnce.disabled = control.sending || !hasTeacherSnapshot;
  if (stateNode) stateNode.textContent = control.enabled ? "实时运行" : !state.receiveMode ? "未接收" : hasTeacherSnapshot ? "待命" : "等待数据";
  const metrics = plan?.metrics || {};
  const metricText = {
    renewableAvailableKw: `${formatNumber(metrics.availableRenewable)} kW`,
    renewableUsedKw: `${formatNumber(metrics.renewableTarget)} kW`,
    renewableStorageKw: `${formatNumber(metrics.storageTarget)} kW`,
    renewableDieselKw: `${formatNumber(metrics.dieselResidual)} kW`,
    renewableCurtailKw: `${formatNumber(metrics.curtailKw)} kW`,
    renewableLastSent: control.lastSentAt || "--",
  };
  Object.entries(metricText).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
  const status = $("renewableControlStatus");
  if (status) {
    status.textContent = control.sending ? "正在向模拟台下发功率指令..." : control.lastStatus;
    status.classList.toggle("is-ok", control.enabled || Boolean(control.lastSentAt));
    status.classList.toggle("is-error", !state.receiveMode && control.enabled);
  }
  if (summary) summary.textContent = `${plan?.commands?.length || 0} 条 · ${plan?.time || "--"}`;
  const table = $("renewableCommandTable");
  if (!table) return;
  const rows = plan?.commandRows || [];
  if (!rows.length) {
    table.innerHTML = '<div class="empty-state">暂无可控新能源或储能设备</div>';
    return;
  }
  table.innerHTML = `
    <table class="runtime-device-table renewable-command-table">
      <thead><tr><th>类别</th><th>设备名称</th><th>状态</th><th>可用/能力</th><th>计划指令</th><th>SOC</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr class="${row.online ? "" : "is-muted"}">
            <td>${escapeHtml(row.category)}</td>
            <td>${escapeHtml(row.dev_name)}</td>
            <td><span class="status-pill ${row.online ? "is-ok" : "is-off"}">${row.online ? "可控" : "停用"}</span></td>
            <td class="numeric-cell">${formatNumber(row.availableKw)} kW</td>
            <td class="numeric-cell">${formatNumber(row.commandKw)} kW</td>
            <td>${row.soc === undefined ? "--" : formatNumber(row.soc)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function stopRenewableControl(message = "实时控制已停止。", logEvent = false) {
  const wasEnabled = state.renewableControl.enabled;
  state.renewableControl.enabled = false;
  state.renewableControl.sending = false;
  state.renewableControl.lastClockKey = "";
  state.renewableControl.lastAutoAtMs = 0;
  state.renewableControl.lastStatus = message;
  if (logEvent && wasEnabled) addRuntimeLog("策略控制", "新能源优先", "停止", message, "warn");
  renderRenewableControl(state.snapshot || {});
}

async function sendRenewableControlPlan(plan, trigger = "manual") {
  if (!state.receiveMode) {
    state.renewableControl.lastStatus = "请先启动接收模式，策略指令需要下发到模拟台。";
    addRuntimeLog("策略决策", "新能源优先", "等待接收", state.renewableControl.lastStatus, "warn");
    renderRenewableControl(state.snapshot || {});
    return;
  }
  if (state.snapshotSource !== "teacher") {
    state.renewableControl.lastStatus = "等待教员台实时数据，收到第一帧后再下发策略指令。";
    addRuntimeLog("策略决策", "新能源优先", "等待数据", state.renewableControl.lastStatus, "warn");
    renderRenewableControl(state.snapshot || {});
    return;
  }
  if (!plan?.commands?.length) {
    state.renewableControl.lastStatus = "当前没有可下发的新能源或储能控制指令。";
    addRuntimeLog("策略决策", "新能源优先", "无可下发指令", state.renewableControl.lastStatus, "warn");
    renderRenewableControl(state.snapshot || {});
    return;
  }
  state.renewableControl.sending = true;
  addRuntimeLog("策略决策", "新能源优先", "计算完成", renewableDecisionDetail(plan), "info");
  addRuntimeLog(
    "实时控制",
    "模拟台 /api/student/commands",
    "下发请求",
    `触发 ${trigger}；设值 ${plan.commands.length} 条；目标柴油缺额 ${formatNumber(plan.metrics.dieselResidual)} kW`,
    "info",
  );
  renderRenewableControl(state.snapshot || {});
  try {
    const payload = {
      source: "trainee-renewable-priority",
      valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES,
      set_values: plan.commands,
      strategy: {
        name: "renewable_priority",
        trigger,
        time: plan.time,
        load_kw: commandNumber(plan.metrics.loadKw),
        renewable_available_kw: commandNumber(plan.metrics.availableRenewable),
        renewable_used_kw: commandNumber(plan.metrics.renewableTarget),
        storage_kw: commandNumber(plan.metrics.storageTarget),
        diesel_residual_kw: commandNumber(plan.metrics.dieselResidual),
        curtail_kw: commandNumber(plan.metrics.curtailKw),
      },
    };
    const result = await teacherApi("/api/student/commands", { method: "POST", body: JSON.stringify(payload) });
    state.renewableControl.lastSentAt = new Date().toLocaleTimeString();
    state.renewableControl.lastClockKey = plan.clockKey;
    state.renewableControl.lastStatus = `已下发 ${result.set_values || plan.commands.length} 条指令，计划柴油缺额 ${formatNumber(plan.metrics.dieselResidual)} kW。`;
    addRuntimeLog(
      "模拟台响应",
      "模拟台 /api/student/commands",
      "下发成功",
      `模拟台接受设值 ${result.set_values || 0} 条；策略时刻 ${plan.time}；柴油缺额 ${formatNumber(plan.metrics.dieselResidual)} kW`,
      "ok",
    );
  } catch (error) {
    state.renewableControl.lastStatus = apiErrorText(error);
    addRuntimeLog("模拟台响应", "模拟台 /api/student/commands", "下发失败", apiErrorText(error), "error");
  } finally {
    state.renewableControl.sending = false;
    renderRenewableControl(state.snapshot || {});
  }
}

function maybeRunRenewableControl(snapshot = state.snapshot || {}) {
  const control = state.renewableControl;
  if (!control.enabled || control.sending || !state.receiveMode) return;
  if (state.snapshotSource !== "teacher") return;
  const now = Date.now();
  if (now - control.lastAutoAtMs < Math.max(1, control.intervalSeconds) * 1000) return;
  const plan = calculateRenewableControlPlan(snapshot);
  if (plan.clockKey && plan.clockKey === control.lastClockKey) return;
  control.lastAutoAtMs = now;
  sendRenewableControlPlan(plan, "auto");
}

function toggleRenewableAuto() {
  if (state.renewableControl.enabled) {
    stopRenewableControl("实时控制已停止。", true);
    return;
  }
  if (!state.receiveMode) {
    state.renewableControl.lastStatus = "请先点击顶部“启动接收”，再启动新能源优先实时控制。";
    addRuntimeLog("策略控制", "新能源优先", "启动失败", state.renewableControl.lastStatus, "warn");
    renderRenewableControl(state.snapshot || {});
    return;
  }
  state.renewableControl.enabled = true;
  state.renewableControl.lastClockKey = "";
  state.renewableControl.lastAutoAtMs = 0;
  state.renewableControl.lastStatus = state.snapshotSource === "teacher"
    ? "实时控制已启动，正在按教员台实时数据计算。"
    : "实时控制已启动，等待第一帧教员台数据。";
  addRuntimeLog("策略控制", "新能源优先", "启动", state.renewableControl.lastStatus, "ok");
  renderRenewableControl(state.snapshot || {});
  maybeRunRenewableControl(state.snapshot || {});
}

function updateRenewableSettings() {
  const minValue = clamp(toNumber($("renewableSocMin")?.value, 0.3), 0, 1);
  const maxValue = clamp(toNumber($("renewableSocMax")?.value, 0.9), minValue, 1);
  state.renewableControl.intervalSeconds = Math.max(1, toNumber($("renewableControlPeriod")?.value, 2));
  state.renewableControl.socMin = minValue;
  state.renewableControl.socMax = maxValue;
  if ($("renewableSocMin")) $("renewableSocMin").value = minValue.toFixed(2);
  if ($("renewableSocMax")) $("renewableSocMax").value = maxValue.toFixed(2);
  renderRenewableControl(state.snapshot || {});
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
  if (filterName === "controlFilter") renderCombinedControlPage(state.snapshot?.devices || []);
}

function filteredDevices(devices, filter) {
  return (devices || []).filter((dev) => {
    if (filter.dev_type && filter.dev_type !== "all" && deviceType(dev) !== filter.dev_type) return false;
    if (filter.dev_name && deviceName(dev) !== filter.dev_name) return false;
    return true;
  });
}

function formatModelParamValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function compareModelRowsByIndex(left, right) {
  const leftIndex = Number(left.idx ?? left.raw?.idx);
  const rightIndex = Number(right.idx ?? right.raw?.idx);
  const indexCompare = (Number.isFinite(leftIndex) ? leftIndex : Number.POSITIVE_INFINITY)
    - (Number.isFinite(rightIndex) ? rightIndex : Number.POSITIVE_INFINITY);
  if (indexCompare) return indexCompare;
  return deviceName(left).localeCompare(deviceName(right), "zh-Hans-CN");
}

function modelAttributeRecordForDevice(dev) {
  const record = {
    dev_type: deviceType(dev),
    dev_name: deviceName(dev),
    idx: formatModelParamValue(deviceIndex(dev)),
    name: formatModelParamValue(deviceName(dev)),
  };
  Object.entries(dev.raw || {}).forEach(([key, value]) => {
    if (["idx", "name", "dev_name", "dev_type"].includes(key)) return;
    record[key] = formatModelParamValue(value);
  });
  record.run_stat = formatModelParamValue(dev.run_stat ?? record.run_stat);
  record.status = formatModelParamValue(dev.status ?? record.status);
  record.mode = formatModelParamValue(dev.mode || dev.raw?.control_type || dev.raw?.ctrl_mode || record.mode);
  if ((dev.set_types || []).length) record.set_types = formatModelParamValue(dev.set_types);
  Object.entries(dev.set_values || {}).forEach(([key, value]) => {
    record[key] = formatModelParamValue(value);
  });
  return record;
}

function modelAttributeColumns(records) {
  const fixed = ["idx", "name"];
  const preferred = [
    "node", "from_node", "to_node", "ac_node", "dc_node", "control_type", "ctrl_mode", "mode",
    "run_stat", "status", "p_set", "q_set", "v_set", "p_ac_set", "q_ac_set", "v_ac_set",
    "p_dc_set", "v_dc_set", "pv0", "pv1", "pv2", "qv0", "qv1", "qv2", "pbase", "qbase",
    "pmax", "pmin", "qmax", "qmin", "soc_curr", "alpha", "set_types",
  ];
  const seen = new Set([...fixed, "dev_type", "dev_name"]);
  const keys = [];
  const appendKey = (key) => {
    if (!key || seen.has(key)) return;
    if (!records.some((record) => record[key] !== undefined && record[key] !== "--")) return;
    seen.add(key);
    keys.push(key);
  };
  preferred.forEach(appendKey);
  records.forEach((record) => Object.keys(record).forEach(appendKey));
  return [...fixed, ...keys].map((key) => ({ key, label: key === "name" ? "名称" : key }));
}

function groupedModelAttributeRecords(records) {
  const groups = new Map();
  records.forEach((record) => {
    const devType = record.dev_type || "未分类";
    if (!groups.has(devType)) groups.set(devType, []);
    groups.get(devType).push(record);
  });
  return Array.from(groups.entries())
    .map(([devType, rows]) => [devType, rows.sort(compareModelRowsByIndex)])
    .sort(([left], [right]) => left.localeCompare(right, "zh-Hans-CN"));
}

function renderModelAttributeTable(rows) {
  const columns = modelAttributeColumns(rows);
  return `<table class="model-param-table">
    <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${columns.map((column) => (
      `<td class="attr-value">${escapeHtml(row[column.key] ?? "--")}</td>`
    )).join("")}</tr>`).join("")}</tbody>
  </table>`;
}

function modelFilterLabel() {
  if (state.modelFilter.dev_type === "all") return "全部设备";
  return state.modelFilter.dev_name || state.modelFilter.dev_type;
}

function renderTraineeModelDeviceTree(snapshot = state.snapshot || {}) {
  const container = $("modelDeviceTree");
  if (!container) return;
  const devices = snapshot.devices || [];
  const groups = devicesByType(devices).map(([devType, items]) => [devType, [...items].sort(compareModelRowsByIndex)]);
  $("modelTreeSummary").textContent = `${groups.length} 类 · ${devices.length} 台`;
  container.innerHTML = `
    <button type="button" class="tree-node tree-root ${state.modelFilter.dev_type === "all" ? "is-active" : ""}"
      data-model-tree-type="all" data-model-tree-name="">
      <span>全部设备</span><strong>${devices.length}</strong>
    </button>
    ${groups.map(([devType, items]) => {
      const isCollapsed = isDeviceTreeGroupCollapsed("model", devType);
      return `<div class="tree-group">
        <button type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${state.modelFilter.dev_type === devType && !state.modelFilter.dev_name ? "is-active" : state.modelFilter.dev_type === devType ? "is-parent-active" : ""}"
          data-model-tree-type="${escapeHtml(devType)}" data-model-tree-name=""
          ${deviceTreeTypeAttrs("model", devType, isCollapsed)}>
          ${deviceTreeTypeLabel(devType)}<strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
          <button type="button"
            class="tree-node tree-child model-tree-child ${state.modelFilter.dev_type === devType && state.modelFilter.dev_name === deviceName(dev) ? "is-active" : ""}"
            data-model-tree-type="${escapeHtml(devType)}" data-model-tree-name="${escapeHtml(deviceName(dev))}">
            <span class="model-tree-idx">${escapeHtml(formatModelParamValue(deviceIndex(dev)))}</span>
            <span class="model-tree-name">${escapeHtml(deviceName(dev))}</span>
          </button>`).join(""))}
      </div>`;
    }).join("") || '<div class="empty-state">暂无设备</div>'}`;
}

function renderTraineeModelParamTable(snapshot = state.snapshot || {}) {
  const container = $("modelParamTable");
  if (!container) return;
  const devices = snapshot.devices || [];
  const filtered = filteredDevices(devices, state.modelFilter);
  const groups = groupedModelAttributeRecords(filtered.map(modelAttributeRecordForDevice));
  const availableTabs = groups.map(([devType]) => devType);
  if (!availableTabs.includes(state.activeModelParamTab)) state.activeModelParamTab = availableTabs[0] || "";
  const activeGroup = groups.find(([devType]) => devType === state.activeModelParamTab) || groups[0];
  const activeColumns = activeGroup ? modelAttributeColumns(activeGroup[1]).length : 0;
  $("modelParamSummary").textContent = groups.length > 1
    ? `${modelFilterLabel()} · ${filtered.length}/${devices.length} 台 · ${groups.length} 个分页`
    : `${modelFilterLabel()} · ${filtered.length}/${devices.length} 台 · ${activeColumns} 列属性`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无电网模型数据</div>';
    return;
  }
  if (!activeGroup) {
    container.innerHTML = '<div class="empty-state">当前筛选无模型参数</div>';
    return;
  }
  const [activeType, activeRows] = activeGroup;
  container.innerHTML = `
    <div class="model-param-tabs" role="tablist" aria-label="设备类型参数表">
      ${groups.map(([devType, rows]) => `<button type="button" role="tab"
        class="model-param-tab ${devType === activeType ? "is-active" : ""}"
        data-model-param-tab="${escapeHtml(devType)}" aria-selected="${devType === activeType}">
        <span>${escapeHtml(devType)}</span><strong>${rows.length}</strong>
      </button>`).join("")}
    </div>
    <section class="model-param-tab-page" role="tabpanel">${renderModelAttributeTable(activeRows)}</section>`;
}

function renderTraineeModelPage(snapshot = state.snapshot || {}) {
  renderTraineeModelDeviceTree(snapshot);
  renderTraineeModelParamTable(snapshot);
}

function setTraineeModelFilter(devType, devName = "") {
  state.modelFilter = { dev_type: devType || "all", dev_name: devName || "" };
  if (devType && devType !== "all") state.activeModelParamTab = devType;
  renderTraineeModelPage();
}

function measurementRows(snapshot = state.snapshot || {}) {
  return measurementDisplayRows(snapshot);
}

function measurementDisplayRows(snapshot = state.snapshot || {}) {
  const scada = snapshot.measurements?.scada || [];
  if (scada.length) return scada;
  return snapshot.measurements?.definitions || [];
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
  if (Number(clock.step_count ?? 0) <= 0) return;
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
  state.measurementTraceHistory = state.measurementTraceHistory.slice(-TRACE_HISTORY_LIMIT);
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

function measurementTraceTimeLabel(minute, windowMinutes, fallback = "") {
  const absolute = Math.max(0, Math.round(Number(minute) || 0));
  if (Number(windowMinutes) <= 1440) return fallback;
  if (Number(windowMinutes) >= 525600) {
    const year = Math.floor(absolute / 525600) + 1;
    return `第${year}年`;
  }
  const day = Math.floor(absolute / 1440);
  const dayMinute = absolute % 1440;
  const hour = String(Math.floor(dayMinute / 60)).padStart(2, "0");
  const minuteText = String(dayMinute % 60).padStart(2, "0");
  return dayMinute === 0 ? `第${day + 1}天` : `第${day + 1}天 ${hour}:${minuteText}`;
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
  ctx.fillText(measurementTraceTimeLabel(points[0].minute, state.measurementTraceWindowMinutes, points[0].time || ""), left, height - 12 * ratio);
  ctx.textAlign = "right";
  const lastPoint = points[points.length - 1];
  ctx.fillText(measurementTraceTimeLabel(lastPoint.minute, state.measurementTraceWindowMinutes, lastPoint.time || ""), width - right, height - 12 * ratio);
  ctx.textAlign = "left";
  $("measurementTraceSummary").textContent = `${points[points.length - 1].label || "测点"} · ${points.length} 点`;
}

function remoteControlIssuedAt(dev, snapshot = state.snapshot || {}) {
  const history = [...(snapshot.commands?.history || [])].reverse();
  for (const entry of history) {
    const items = entry.normalized?.run_status || entry.payload?.run_status || [];
    const match = items.find((item) => (
      item.dev_type === deviceType(dev)
      && item.dev_name === deviceName(dev)
    ));
    if (match) return entry.time || "--";
  }
  return "--";
}

function renderRunControls(devices) {
  const visibleDevices = filteredDevices(devices, state.controlFilter);
  $("runControlTable").innerHTML = `
    <table class="runtime-device-table">
      <thead><tr><th>idx</th><th>设备名称</th><th>类型</th><th>当前状态</th><th>下发状态</th><th>指令下发时刻</th></tr></thead>
      <tbody>
        ${visibleDevices.map((dev) => {
          const key = deviceKey(dev);
          const currentRun = Number(pending.run_status.has(key) ? pending.run_status.get(key).run_stat : dev.run_stat);
          const issuedAt = remoteControlIssuedAt(dev);
          return `<tr class="${pending.run_status.has(key) ? "is-pending" : ""}">
            <td>${escapeHtml(deviceIndex(dev))}</td>
            <td>${escapeHtml(deviceName(dev))}</td>
            <td>${escapeHtml(deviceType(dev))}</td>
            <td class="run-status-command-cell" data-run-status-command="${escapeHtml(key)}" title="双击进行遥控操作">
              <span class="status-pill ${Number(dev.run_stat) ? "is-ok" : "is-off"}">${statusText(dev.run_stat)}</span>
            </td>
            <td>
              <label class="inline-toggle">
                <input type="checkbox" data-run-key="${escapeHtml(key)}" ${currentRun ? "checked" : ""} />
                <span>${currentRun ? "投入" : "退出"}</span>
              </label>
            </td>
            <td class="mono-cell command-issued-at-cell">${escapeHtml(issuedAt)}</td>
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

function remoteAdjustmentTypeLabel(setType) {
  return {
    p_set: "P有功设定",
    q_set: "Q无功设定",
    v_set: "V电压设定",
  }[setType] || setType;
}

function remoteAdjustmentName(dev, setType) {
  return `${deviceName(dev)}.${remoteAdjustmentTypeLabel(setType)}`;
}

function remoteAdjustmentMeasurement(dev, setType, snapshot = state.snapshot || {}) {
  const rows = snapshot.measurements?.scada?.length
    ? snapshot.measurements.scada
    : snapshot.measurements?.definitions || [];
  const priorities = {
    p_set: ["P_GEN", "P_LOAD", "P_AC", "P_FROM", "P_TO", "P_DC", "P"],
    q_set: ["Q_GEN", "Q_LOAD", "Q_AC", "Q"],
    v_set: ["V_GEN", "V_LOAD", "V_AC", "V_FROM", "V_TO", "V_DC", "V"],
  }[setType] || [];
  const candidates = (rows || []).filter((row) => row.dev_type === deviceType(dev) && row.dev_name === deviceName(dev));
  for (const measType of priorities) {
    const match = candidates.find((row) => String(row.meas_type || "").toUpperCase() === measType);
    if (match) return match.value;
  }
  return null;
}

function remoteAdjustmentIssuedAt(dev, setType, snapshot = state.snapshot || {}) {
  const history = [...(snapshot.commands?.history || [])].reverse();
  for (const entry of history) {
    const items = entry.normalized?.set_values || entry.payload?.set_values || [];
    const match = items.find((item) => (
      item.dev_type === deviceType(dev)
      && item.dev_name === deviceName(dev)
      && item.set_type === setType
    ));
    if (match) return entry.time || "--";
  }
  return "--";
}

function remoteAdjustmentRows(devices, snapshot = state.snapshot || {}) {
  return (devices || []).flatMap((dev) => preferredSetTypes(dev).map((setType) => ({
    key: `${deviceKey(dev)}|${setType}`,
    dev,
    setType,
    name: remoteAdjustmentName(dev, setType),
    measurement: remoteAdjustmentMeasurement(dev, setType, snapshot),
    controlValue: currentSetValue(dev, setType),
    issuedAt: remoteAdjustmentIssuedAt(dev, setType, snapshot),
  })));
}

function formatRemoteAdjustmentValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  return formatNumber(value);
}

function renderSetpointControls(devices) {
  const adjustable = (devices || []).filter((dev) => preferredSetTypes(dev).length);
  const visibleDevices = filteredDevices(adjustable, state.controlFilter);
  const rows = remoteAdjustmentRows(visibleDevices);
  $("setpointControlTable").innerHTML = `
    <table class="runtime-device-table remote-adjustment-table">
      <thead><tr><th>遥调名称</th><th>量测值</th><th>控制值</th><th>指令下发时刻</th></tr></thead>
      <tbody>
        ${rows.map((row) => `<tr data-remote-adjustment-key="${escapeHtml(row.key)}" title="双击进行遥调操作">
          <td><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(deviceType(row.dev))}</small></td>
          <td class="numeric-cell">${formatRemoteAdjustmentValue(row.measurement)}</td>
          <td class="numeric-cell">${formatRemoteAdjustmentValue(row.controlValue)}</td>
          <td class="mono-cell">${escapeHtml(row.issuedAt)}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

function renderControlTabs() {
  document.querySelectorAll("[data-command-tab]").forEach((button) => {
    const isActive = button.dataset.commandTab === state.activeControlTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
  });
  document.querySelectorAll("[data-command-tab-page]").forEach((page) => {
    page.classList.toggle("is-active", page.dataset.commandTabPage === state.activeControlTab);
  });
}

function renderCombinedControlPage(devices = state.snapshot?.devices || []) {
  renderDeviceTree("commandDeviceTree", "commandTreeSummary", devices, state.controlFilter, "control", "control");
  renderRunControls(devices);
  renderSetpointControls(devices);
  renderControlTabs();
}

function commandHistoryKey(item) {
  const accepted = item.accepted || {};
  return [
    item.time || "",
    item.source || "",
    accepted.run_status || 0,
    accepted.set_values || 0,
    JSON.stringify(item.payload || {}).slice(0, 240),
  ].join("|");
}

function syncCommandHistoryLogs(history = []) {
  history.slice(-30).forEach((item) => {
    const key = commandHistoryKey(item);
    if (state.seenCommandHistoryKeys.has(key)) return;
    state.seenCommandHistoryKeys.add(key);
    addRuntimeLog(
      "模拟台响应",
      "模拟台命令历史",
      "记录同步",
      [
        `来源 ${item.source || "student"}`,
        `接受投退 ${item.accepted?.run_status || 0} 条`,
        `接受设值 ${item.accepted?.set_values || 0} 条`,
        `模拟台记录 ${item.time || "--"}`,
      ],
      "ok",
      false,
    );
  });
}

function renderHistory() {
  syncTraineeRuntimeLogTypeFilter();
  const logs = filteredTraineeRuntimeLogs();
  $("historyCount").textContent = state.runtimeLogTypeFilter === "all"
    ? `${state.runtimeLogs.length} 条`
    : `${logs.length}/${state.runtimeLogs.length} 条`;
  if (!logs.length) {
    $("commandHistory").innerHTML = '<div class="empty-state">暂无运行日志</div>';
    return;
  }
  $("commandHistory").innerHTML = `
    <table class="runtime-log-table">
      <thead><tr><th>序号</th><th>本机时刻</th><th>类型</th><th>对象</th><th>结果</th><th>详情</th></tr></thead>
      <tbody>
        ${logs.map((item) => `
          <tr class="runtime-log-row is-${escapeHtml(item.level || "info")}">
            <td>${escapeHtml(item.seq)}</td>
            <td>${escapeHtml(item.wall_time || "")}</td>
            <td>${escapeHtml(item.type || "")}</td>
            <td>${escapeHtml(item.target || "")}</td>
            <td>${escapeHtml(item.result || "")}</td>
            <td class="runtime-log-detail">${escapeHtml(runtimeLogDetailText(item.detail))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function traineeRuntimeLogTypes() {
  return Array.from(new Set(state.runtimeLogs.map((item) => String(item.type || "")).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function syncTraineeRuntimeLogTypeFilter() {
  const select = $("traineeRuntimeLogTypeFilter");
  if (!select) return;
  const types = traineeRuntimeLogTypes();
  if (state.runtimeLogTypeFilter !== "all" && !types.includes(state.runtimeLogTypeFilter)) {
    state.runtimeLogTypeFilter = "all";
  }
  select.innerHTML = ["<option value=\"all\">全部类型</option>", ...types.map((type) => (
    `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`
  ))].join("");
  select.value = state.runtimeLogTypeFilter;
}

function filteredTraineeRuntimeLogs() {
  if (state.runtimeLogTypeFilter === "all") return state.runtimeLogs;
  return state.runtimeLogs.filter((item) => item.type === state.runtimeLogTypeFilter);
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
  $("commandPendingCount").textContent = `${total} 待发`;
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

function findDeviceByKey(key) {
  return (state.snapshot?.devices || []).find((dev) => deviceKey(dev) === key) || null;
}

function closeRemoteControlDialog() {
  const dialog = $("remoteControlDialog");
  if (dialog?.open) dialog.close();
  state.remoteControlDevice = null;
  state.remoteControlSending = false;
}

function openRemoteControlDialog(dev) {
  const dialog = $("remoteControlDialog");
  if (!dialog || !dev) return;
  state.remoteControlDevice = dev;
  state.remoteControlSending = false;
  const currentRun = Number(dev.run_stat) ? 1 : 0;
  $("remoteControlDevice").textContent = deviceName(dev);
  $("remoteControlType").textContent = deviceType(dev);
  $("remoteControlCurrent").innerHTML = `<span class="status-pill ${currentRun ? "is-ok" : "is-off"}">${statusText(currentRun)}</span>`;
  $("remoteControlHint").textContent = "确认后将立即向模拟台下发遥控指令。";
  $("remoteControlHint").className = "remote-control-hint";
  document.querySelectorAll('input[name="remoteControlState"]').forEach((input) => {
    input.checked = Number(input.value) === (currentRun ? 0 : 1);
  });
  $("remoteControlConfirm").disabled = false;
  $("remoteControlConfirm").textContent = "确认下发";
  dialog.showModal();
}

async function sendRemoteControlCommand() {
  const dev = state.remoteControlDevice;
  if (!dev || state.remoteControlSending) return;
  const selected = document.querySelector('input[name="remoteControlState"]:checked');
  if (!(selected instanceof HTMLInputElement)) return;
  const command = {
    dev_type: deviceType(dev),
    dev_name: deviceName(dev),
    run_stat: Number(selected.value) ? 1 : 0,
  };
  const body = {
    source: "trainee-ui",
    valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES,
    run_status: [command],
    set_values: [],
  };
  const targetApi = state.receiveMode ? teacherApi : api;
  const targetName = state.receiveMode ? "模拟台 /api/student/commands" : "学员台 /api/student/commands";
  state.remoteControlSending = true;
  $("remoteControlConfirm").disabled = true;
  $("remoteControlConfirm").textContent = "下发中";
  $("remoteControlHint").textContent = `${deviceName(dev)}：${statusText(command.run_stat)}`;
  addRuntimeLog("人工遥控", targetName, "下发请求", `${deviceName(dev)} → ${statusText(command.run_stat)}`);
  try {
    const result = await targetApi("/api/student/commands", { method: "POST", body: JSON.stringify(body) });
    addRuntimeLog(
      "模拟台响应",
      targetName,
      "遥控成功",
      `${deviceName(dev)} → ${statusText(command.run_stat)}；接受 ${result.run_status || 0} 条`,
      "ok",
    );
    pending.run_status.delete(deviceKey(dev));
    closeRemoteControlDialog();
    updatePendingCount();
    await refresh();
  } catch (error) {
    state.remoteControlSending = false;
    $("remoteControlConfirm").disabled = false;
    $("remoteControlConfirm").textContent = "重新下发";
    $("remoteControlHint").textContent = apiErrorText(error);
    $("remoteControlHint").className = "remote-control-hint is-error";
    addRuntimeLog("模拟台响应", targetName, "遥控失败", apiErrorText(error), "error");
  }
}

function findRemoteAdjustmentByKey(key) {
  return remoteAdjustmentRows(state.snapshot?.devices || []).find((row) => row.key === key) || null;
}

function closeRemoteAdjustmentDialog() {
  const dialog = $("remoteAdjustmentDialog");
  if (dialog?.open) dialog.close();
  state.remoteAdjustment = null;
  state.remoteAdjustmentSending = false;
}

function openRemoteAdjustmentDialog(row) {
  const dialog = $("remoteAdjustmentDialog");
  if (!dialog || !row) return;
  state.remoteAdjustment = row;
  state.remoteAdjustmentSending = false;
  $("remoteAdjustmentName").textContent = row.name;
  $("remoteAdjustmentDevice").textContent = `${deviceType(row.dev)} / ${deviceName(row.dev)}`;
  $("remoteAdjustmentMeasurement").textContent = formatRemoteAdjustmentValue(row.measurement);
  $("remoteAdjustmentCurrent").textContent = formatRemoteAdjustmentValue(row.controlValue);
  $("remoteAdjustmentIssuedAt").textContent = row.issuedAt;
  $("remoteAdjustmentValue").value = row.controlValue === null || row.controlValue === undefined ? "" : row.controlValue;
  $("remoteAdjustmentHint").textContent = "确认后将立即向模拟台下发一条遥调指令。";
  $("remoteAdjustmentHint").className = "remote-control-hint";
  $("remoteAdjustmentConfirm").disabled = false;
  $("remoteAdjustmentConfirm").textContent = "确认下发";
  dialog.showModal();
  $("remoteAdjustmentValue").focus();
  $("remoteAdjustmentValue").select();
}

async function sendRemoteAdjustmentCommand() {
  const row = state.remoteAdjustment;
  if (!row || state.remoteAdjustmentSending) return;
  const setValue = Number($("remoteAdjustmentValue").value);
  if (!Number.isFinite(setValue)) {
    $("remoteAdjustmentHint").textContent = "请输入有效的控制值。";
    $("remoteAdjustmentHint").className = "remote-control-hint is-error";
    return;
  }
  const command = {
    dev_type: deviceType(row.dev),
    dev_name: deviceName(row.dev),
    set_type: row.setType,
    set_value: setValue,
  };
  const body = {
    source: "trainee-ui",
    valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES,
    run_status: [],
    set_values: [command],
  };
  const targetApi = state.receiveMode ? teacherApi : api;
  const targetName = state.receiveMode ? "模拟台 /api/student/commands" : "学员台 /api/student/commands";
  state.remoteAdjustmentSending = true;
  $("remoteAdjustmentConfirm").disabled = true;
  $("remoteAdjustmentConfirm").textContent = "下发中";
  $("remoteAdjustmentHint").textContent = `${row.name}：${formatNumber(setValue)}`;
  addRuntimeLog("人工遥调", targetName, "下发请求", `${row.name} → ${formatNumber(setValue)}`);
  try {
    const result = await targetApi("/api/student/commands", { method: "POST", body: JSON.stringify(body) });
    addRuntimeLog(
      "模拟台响应",
      targetName,
      "遥调成功",
      `${row.name} → ${formatNumber(setValue)}；接受 ${result.set_values || 0} 条`,
      "ok",
    );
    pending.set_values.delete(row.key);
    closeRemoteAdjustmentDialog();
    updatePendingCount();
    await refresh();
  } catch (error) {
    state.remoteAdjustmentSending = false;
    $("remoteAdjustmentConfirm").disabled = false;
    $("remoteAdjustmentConfirm").textContent = "重新下发";
    $("remoteAdjustmentHint").textContent = apiErrorText(error);
    $("remoteAdjustmentHint").className = "remote-control-hint is-error";
    addRuntimeLog("模拟台响应", targetName, "遥调失败", apiErrorText(error), "error");
  }
}

function handleTreeClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  const button = target.closest("[data-model-tree-type], [data-measurement-tree-type], [data-control-tree-type]");
  if (!button) return;
  event.preventDefault();
  const toggleScope = button.dataset.treeToggleScope;
  const toggleGroup = button.dataset.treeToggleGroup || "";
  const selection =
    button.dataset.modelTreeType !== undefined
      ? ["modelFilter", button.dataset.modelTreeType, button.dataset.modelTreeName || ""]
      : button.dataset.measurementTreeType !== undefined
      ? ["measurementFilter", button.dataset.measurementTreeType, button.dataset.measurementTreeName || ""]
      : button.dataset.controlTreeType !== undefined
        ? ["controlFilter", button.dataset.controlTreeType, button.dataset.controlTreeName || ""]
          : null;
  requestAnimationFrame(() => {
    if (toggleScope) toggleDeviceTreeGroup(toggleScope, toggleGroup);
    if (selection?.[0] === "modelFilter") setTraineeModelFilter(selection[1], selection[2]);
    else if (selection) selectTreeFilter(selection[0], selection[1], selection[2]);
  });
}

document.addEventListener("click", (event) => {
  handleTreeClick(event);
  const target = event.target instanceof Element ? event.target : null;
  const modelParamTab = target?.closest("[data-model-param-tab]");
  if (modelParamTab) {
    requestAnimationFrame(() => {
      state.activeModelParamTab = modelParamTab.dataset.modelParamTab || "";
      renderTraineeModelParamTable();
    });
  }
  const curveDisplayButton = target?.closest("[data-curve-display-tree-type]");
  if (curveDisplayButton) {
    event.preventDefault();
    requestAnimationFrame(() => selectCurveDisplayButton(curveDisplayButton));
    return;
  }
  const commandTab = target?.closest("[data-command-tab]");
  if (commandTab) {
    state.activeControlTab = commandTab.dataset.commandTab || "remote-control";
    renderControlTabs();
  }
  const measurementRow = target?.closest("[data-measurement-select-key]");
  if (measurementRow) {
    const key = measurementRow.dataset.measurementSelectKey || "";
    requestAnimationFrame(() => {
      state.selectedMeasurementKey = key;
      renderMeasurements(state.snapshot || {});
    });
  }
});

document.addEventListener("dblclick", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const adjustmentRow = target?.closest("[data-remote-adjustment-key]");
  if (adjustmentRow) {
    event.preventDefault();
    const adjustment = findRemoteAdjustmentByKey(adjustmentRow.dataset.remoteAdjustmentKey || "");
    if (adjustment) openRemoteAdjustmentDialog(adjustment);
    return;
  }
  const statusCell = target?.closest("[data-run-status-command]");
  if (!statusCell) return;
  event.preventDefault();
  const dev = findDeviceByKey(statusCell.dataset.runStatusCommand || "");
  if (dev) openRemoteControlDialog(dev);
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
    valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES,
    run_status: Array.from(pending.run_status.values()),
    set_values: Array.from(pending.set_values.values()),
  };
  if (!body.run_status.length && !body.set_values.length) return;
  $("sendCommands").disabled = true;
  const targetApi = state.receiveMode ? teacherApi : api;
  const targetName = state.receiveMode ? "模拟台 /api/student/commands" : "学员台 /api/student/commands";
  addRuntimeLog("人工控制", targetName, "下发请求", `投退 ${body.run_status.length} 条；设值 ${body.set_values.length} 条`);
  try {
    const result = await targetApi("/api/student/commands", { method: "POST", body: JSON.stringify(body) });
    addRuntimeLog(
      "模拟台响应",
      targetName,
      "下发成功",
      `接受投退 ${result.run_status || 0} 条；接受设值 ${result.set_values || 0} 条`,
      "ok",
    );
    pending.run_status.clear();
    pending.set_values.clear();
    updatePendingCount();
    await refresh();
  } catch (error) {
    addRuntimeLog("模拟台响应", targetName, "下发失败", apiErrorText(error), "error");
    updatePendingCount();
  }
});

function toggleReceiveMode() {
  if (state.receiveMode) {
    state.receiveMode = false;
    state.frozen = true;
    state.receiveEpoch += 1;
    addRuntimeLog("接收模式", "模拟台实时数据", "停止接收", `冻结于 ${state.lastReceiveAt || "--"}`, "warn");
    stopRenewableControl("接收已停止，新能源优先策略已暂停。", true);
    renderReceiveMode();
    return;
  }
  state.receiveMode = true;
  state.frozen = false;
  state.receiveEpoch += 1;
  state.measurementTraceHistory = [];
  state.lastReceiveAt = "";
  state.snapshotSource = "";
  state.lastTeacherSnapshotLogKey = "";
  addRuntimeLog("接收模式", "模拟台实时数据", "启动接收", `教员台 ${teacherApiBase}`, "ok");
  renderReceiveMode();
  renderRenewableControl(state.snapshot || {});
  refresh();
}

$("importDefinitionsButton").addEventListener("click", () => $("definitionArchiveInput").click());
$("definitionArchiveInput").addEventListener("change", (event) => importDefinitionArchive(event.target.files?.[0]));
$("traineeRunToggle").addEventListener("click", toggleReceiveMode);
$("remoteControlClose").addEventListener("click", closeRemoteControlDialog);
$("remoteControlCancel").addEventListener("click", closeRemoteControlDialog);
$("remoteControlConfirm").addEventListener("click", sendRemoteControlCommand);
$("remoteControlDialog").addEventListener("click", (event) => {
  if (event.target === $("remoteControlDialog")) closeRemoteControlDialog();
});
$("remoteAdjustmentClose").addEventListener("click", closeRemoteAdjustmentDialog);
$("remoteAdjustmentCancel").addEventListener("click", closeRemoteAdjustmentDialog);
$("remoteAdjustmentConfirm").addEventListener("click", sendRemoteAdjustmentCommand);
$("remoteAdjustmentDialog").addEventListener("click", (event) => {
  if (event.target === $("remoteAdjustmentDialog")) closeRemoteAdjustmentDialog();
});
$("renewableAutoToggle").addEventListener("click", toggleRenewableAuto);
$("renewableSendOnce").addEventListener("click", () => sendRenewableControlPlan(calculateRenewableControlPlan(state.snapshot || {}), "manual"));
$("renewableControlPeriod").addEventListener("change", updateRenewableSettings);
$("renewableSocMin").addEventListener("change", updateRenewableSettings);
$("renewableSocMax").addEventListener("change", updateRenewableSettings);
$("clearRuntimeLogs").addEventListener("click", () => {
  state.runtimeLogs = [];
  renderHistory();
});
$("traineeRuntimeLogTypeFilter").addEventListener("change", (event) => {
  state.runtimeLogTypeFilter = event.target.value || "all";
  renderHistory();
});
$("modelSelector").addEventListener("change", (event) => setActiveModel(event.target.value));
$("measurementTraceWindow").addEventListener("change", (event) => {
  state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
  drawMeasurementTraceChart();
});
const curveDisplayChart = $("curveDisplayChart");
if (curveDisplayChart) {
  curveDisplayChart.addEventListener("pointermove", (event) => setCurveDisplayCursorFromEvent(event));
  curveDisplayChart.addEventListener("pointerleave", hideCurveDisplayCursor);
}
window.addEventListener("resize", () => {
  drawMeasurementTraceChart();
  drawCurveDisplay(state.snapshot || {});
});

initPageNavigation();
renderReceiveMode();
renderHistory();
loadModels().finally(refresh);
setInterval(refresh, 2000);
