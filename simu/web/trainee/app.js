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
  runtimeLogSeq: 0,
  seenCommandHistoryKeys: new Set(),
  measurementFilter: { dev_type: "all", dev_name: "" },
  runFilter: { dev_type: "all", dev_name: "" },
  setpointFilter: { dev_type: "all", dev_name: "" },
  collapsedDeviceTreeGroups: {},
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
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
    state.frozen = false;
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
      button.textContent = "导入定义包";
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
  state.selectedMeasurementKey = "";
  state.measurementFilter = { dev_type: "all", dev_name: "" };
  state.runFilter = { dev_type: "all", dev_name: "" };
  state.setpointFilter = { dev_type: "all", dev_name: "" };
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
  const scada = snapshot.measurements?.scada || [];
  const validCount = scada.filter((m) => Number(m.valid) === 1).length;
  $("measureCount").textContent = `${scada.length} 点`;
  $("validCount").textContent = `${validCount} 可用`;
  $("overviewRefresh").textContent = snapshot.clock?.time || "--";
  $("topologyState").textContent = snapshot.result?.solver_info || "在线";
  renderTeacherWeather(snapshot);
  renderReceiveMode();
  appendMeasurementTrace(snapshot);
  renderMeasurements(snapshot);
  renderRunControls(snapshot.devices || []);
  renderSetpointControls(snapshot.devices || []);
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
  const logs = state.runtimeLogs || [];
  $("historyCount").textContent = `${logs.length} 条`;
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
$("renewableAutoToggle").addEventListener("click", toggleRenewableAuto);
$("renewableSendOnce").addEventListener("click", () => sendRenewableControlPlan(calculateRenewableControlPlan(state.snapshot || {}), "manual"));
$("renewableControlPeriod").addEventListener("change", updateRenewableSettings);
$("renewableSocMin").addEventListener("change", updateRenewableSettings);
$("renewableSocMax").addEventListener("change", updateRenewableSettings);
$("clearRuntimeLogs").addEventListener("click", () => {
  state.runtimeLogs = [];
  renderHistory();
});
$("modelSelector").addEventListener("change", (event) => setActiveModel(event.target.value));
$("measurementTraceWindow").addEventListener("change", (event) => {
  state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
  drawMeasurementTraceChart();
});
window.addEventListener("resize", () => drawMeasurementTraceChart());

initPageNavigation();
renderReceiveMode();
renderHistory();
loadModels().finally(refresh);
setInterval(refresh, 2000);
