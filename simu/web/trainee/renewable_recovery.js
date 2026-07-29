(function initRenewableRecovery(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.RenewableRecovery = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function createRenewableRecovery() {
  const EPSILON = 1e-9;

  function finiteNonNegative(value, defaultValue = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0, number) : defaultValue;
  }

  function normalizedRows(rows) {
    return (Array.isArray(rows) ? rows : []).map((row) => {
      const capacityKw = finiteNonNegative(row?.capacityKw);
      const currentKw = Math.min(capacityKw, finiteNonNegative(row?.currentKw));
      return {
        ...row,
        capacityKw,
        currentKw,
        headroomKw: Math.max(0, capacityKw - currentKw),
      };
    });
  }

  function equalMarginIncrements(rows, targetKw) {
    const increments = rows.map(() => 0);
    let remaining = finiteNonNegative(targetKw);
    let active = rows
      .map((row, index) => ({ index, headroomKw: row.headroomKw }))
      .filter((item) => item.headroomKw > EPSILON);

    while (remaining > EPSILON && active.length) {
      const share = remaining / active.length;
      const saturated = active.filter((item) => item.headroomKw - increments[item.index] <= share + EPSILON);
      if (!saturated.length) {
        active.forEach((item) => {
          increments[item.index] += share;
        });
        remaining = 0;
        break;
      }
      const saturatedIndexes = new Set(saturated.map((item) => item.index));
      saturated.forEach((item) => {
        const addition = Math.max(0, item.headroomKw - increments[item.index]);
        increments[item.index] += addition;
        remaining = Math.max(0, remaining - addition);
      });
      active = active.filter((item) => !saturatedIndexes.has(item.index));
    }
    return increments;
  }

  function capacityStepIncrements(rows, targetKw, stepCoefficient) {
    const coefficient = finiteNonNegative(stepCoefficient, 0.03);
    const proposed = rows.map((row) => Math.min(row.headroomKw, coefficient * row.capacityKw));
    const proposedTotal = proposed.reduce((sum, value) => sum + value, 0);
    const target = Math.min(finiteNonNegative(targetKw), proposedTotal);
    if (target <= EPSILON || proposedTotal <= EPSILON) return rows.map(() => 0);
    const scale = Math.min(1, target / proposedTotal);
    return proposed.map((value) => value * scale);
  }

  function planRecovery(rows, systemRoomKw, options = {}) {
    const normalized = normalizedRows(rows);
    const thresholdKw = finiteNonNegative(options.largeStepThresholdKw, 10);
    const totalHeadroomKw = normalized.reduce((sum, row) => sum + row.headroomKw, 0);
    const requestedKw = Math.min(finiteNonNegative(systemRoomKw), totalHeadroomKw);
    const mode = requestedKw > thresholdKw ? "equal-margin" : "capacity-step";
    const increments = mode === "equal-margin"
      ? equalMarginIncrements(normalized, requestedKw)
      : capacityStepIncrements(normalized, requestedKw, options.stepCoefficient);
    const resultRows = normalized.map((row, index) => ({
      ...row,
      recoveryKw: Math.min(row.headroomKw, finiteNonNegative(increments[index])),
      setpointKw: row.currentKw + Math.min(row.headroomKw, finiteNonNegative(increments[index])),
    }));
    return {
      mode,
      requestedKw,
      recoverableKw: resultRows.reduce((sum, row) => sum + row.recoveryKw, 0),
      totalHeadroomKw,
      rows: resultRows,
    };
  }

  return { planRecovery };
}));
