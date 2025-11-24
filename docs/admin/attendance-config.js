(function(){
  const STORAGE_KEY = "dsro-attendance-admin";
  const DEFAULTS = {
    min_start_A: 0.55,
    min_start_B: 0.55,
    min_bench_A: 0.45,
    min_bench_B: 0.45,
    attendance_target_fraction: 0.8,
    target_expected_A: { low: 24.0, high: 28.0 },
    target_expected_B: { low: 24.0, high: 28.0 },
    hard_commit_floor: 0.92,
    no_response_multiplier: 0.65,
    high_reliability_balance_ratio: 1.8,
  };

  const $ = (sel) => document.querySelector(sel);
  const elements = {
    workerUrl: $("#workerUrl"),
    branchInput: $("#branchInput"),
    adminKey: $("#adminKey"),
    reloadBtn: $("#reloadBtn"),
    saveBtn: $("#saveBtn"),
    statusPill: $("#statusPill"),
    sourcePill: $("#sourcePill"),
    buildPill: $("#buildPill"),
    statusLog: $("#statusLog"),
    snapshotMeta: $("#snapshotMeta"),
    snapshotViewer: $("#snapshotViewer"),
    minStartA: $("#minStartA"),
    minStartB: $("#minStartB"),
    minBenchA: $("#minBenchA"),
    minBenchB: $("#minBenchB"),
    targetALow: $("#targetALow"),
    targetAHigh: $("#targetAHigh"),
    targetBLow: $("#targetBLow"),
    targetBHigh: $("#targetBHigh"),
    targetFraction: $("#targetFraction"),
    hardCommitFloor: $("#hardCommitFloor"),
    noResponseMultiplier: $("#noResponseMultiplier"),
    reliabilityRatio: $("#reliabilityRatio"),
    minStartALabel: $("#minStartALabel"),
    minStartBLabel: $("#minStartBLabel"),
    minBenchALabel: $("#minBenchALabel"),
    minBenchBLabel: $("#minBenchBLabel"),
    targetFractionLabel: $("#targetFractionLabel"),
    hardCommitLabel: $("#hardCommitLabel"),
    noResponseLabel: $("#noResponseLabel"),
  };

  let lastLoadedGeneratedAt = null;

  function log(message) {
    if (!elements.statusLog) return;
    const now = new Date();
    const prefix = now.toLocaleTimeString(undefined, { hour12: false });
    elements.statusLog.textContent = `${prefix} · ${message}\n${elements.statusLog.textContent || ""}`.trim();
  }

  function setPill(el, text, tone = "muted") {
    if (!el) return;
    el.textContent = text;
    el.className = `pill ${tone}`.trim();
  }

  function clamp(num, min, max) {
    const n = typeof num === "number" && !Number.isNaN(num) ? num : 0;
    return Math.min(Math.max(n, min), max);
  }

  function parseNumber(input, fallback, { min = -Infinity, max = Infinity } = {}) {
    const val = typeof input === "string" ? parseFloat(input) : Number(input);
    if (Number.isFinite(val)) return clamp(val, min, max);
    return clamp(fallback, min, max);
  }

  function normalizeAttendance(raw) {
    const snap = { ...DEFAULTS, ...raw };
    const norm = {
      min_start_A: parseNumber(snap.min_start_A, DEFAULTS.min_start_A, { min: 0, max: 1 }),
      min_start_B: parseNumber(snap.min_start_B, DEFAULTS.min_start_B, { min: 0, max: 1 }),
      min_bench_A: parseNumber(snap.min_bench_A, DEFAULTS.min_bench_A, { min: 0, max: 1 }),
      min_bench_B: parseNumber(snap.min_bench_B, DEFAULTS.min_bench_B, { min: 0, max: 1 }),
      attendance_target_fraction: parseNumber(
        snap.attendance_target_fraction,
        DEFAULTS.attendance_target_fraction,
        { min: 0.1, max: 1 },
      ),
      target_expected_A: {
        low: parseNumber(snap.target_expected_A?.low, DEFAULTS.target_expected_A.low, { min: 0, max: 60 }),
        high: parseNumber(snap.target_expected_A?.high, DEFAULTS.target_expected_A.high, { min: 0, max: 60 }),
      },
      target_expected_B: {
        low: parseNumber(snap.target_expected_B?.low, DEFAULTS.target_expected_B.low, { min: 0, max: 60 }),
        high: parseNumber(snap.target_expected_B?.high, DEFAULTS.target_expected_B.high, { min: 0, max: 60 }),
      },
      hard_commit_floor: parseNumber(snap.hard_commit_floor, DEFAULTS.hard_commit_floor, { min: 0, max: 1 }),
      no_response_multiplier: parseNumber(
        snap.no_response_multiplier,
        DEFAULTS.no_response_multiplier,
        { min: 0, max: 1 },
      ),
      high_reliability_balance_ratio: parseNumber(
        snap.high_reliability_balance_ratio,
        DEFAULTS.high_reliability_balance_ratio,
        { min: 0.25, max: 4 },
      ),
    };
    return norm;
  }

  function parseYamlFallback(text) {
    if (!text) return null;
    const rows = text.split(/\r?\n/);
    const data = {};
    let currentTarget = null;
    for (const rawLine of rows) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      if (line.startsWith("target_expected_A:")) {
        currentTarget = "A";
        data.target_expected_A = data.target_expected_A || {};
        continue;
      }
      if (line.startsWith("target_expected_B:")) {
        currentTarget = "B";
        data.target_expected_B = data.target_expected_B || {};
        continue;
      }
      const nestedMatch = line.match(/^(low|high):\s*([0-9.]+)/);
      if (currentTarget && nestedMatch) {
        const [_, key, value] = nestedMatch;
        data[`target_expected_${currentTarget}`] = data[`target_expected_${currentTarget}`] || {};
        data[`target_expected_${currentTarget}`][key] = parseFloat(value);
        continue;
      }
      const match = line.match(/^([a-zA-Z0-9_]+):\s*([0-9.]+)/);
      if (match) {
        data[match[1]] = parseFloat(match[2]);
      }
    }
    const attendanceBlock = data.attendance || data;
    if (!Object.keys(attendanceBlock).length) return null;
    return normalizeAttendance(attendanceBlock);
  }

  function applyToForm(attendance, sourceLabel = "") {
    const cfg = normalizeAttendance(attendance || {});
    elements.minStartA.value = cfg.min_start_A;
    elements.minStartB.value = cfg.min_start_B;
    elements.minBenchA.value = cfg.min_bench_A;
    elements.minBenchB.value = cfg.min_bench_B;
    elements.targetFraction.value = cfg.attendance_target_fraction;
    elements.targetALow.value = cfg.target_expected_A.low;
    elements.targetAHigh.value = cfg.target_expected_A.high;
    elements.targetBLow.value = cfg.target_expected_B.low;
    elements.targetBHigh.value = cfg.target_expected_B.high;
    elements.hardCommitFloor.value = cfg.hard_commit_floor;
    elements.noResponseMultiplier.value = cfg.no_response_multiplier;
    elements.reliabilityRatio.value = cfg.high_reliability_balance_ratio;
    updateValueLabels();
    if (sourceLabel) {
      setPill(elements.sourcePill, sourceLabel, "muted");
    }
    renderSnapshot(cfg, sourceLabel);
  }

  function updateValueLabels() {
    elements.minStartALabel.textContent = Number(elements.minStartA.value).toFixed(2);
    elements.minStartBLabel.textContent = Number(elements.minStartB.value).toFixed(2);
    elements.minBenchALabel.textContent = Number(elements.minBenchA.value).toFixed(2);
    elements.minBenchBLabel.textContent = Number(elements.minBenchB.value).toFixed(2);
    elements.targetFractionLabel.textContent = Number(elements.targetFraction.value).toFixed(2);
    elements.hardCommitLabel.textContent = Number(elements.hardCommitFloor.value).toFixed(2);
    elements.noResponseLabel.textContent = Number(elements.noResponseMultiplier.value).toFixed(2);
  }

  function renderSnapshot(cfg, metaText) {
    if (elements.snapshotViewer) {
      elements.snapshotViewer.textContent = JSON.stringify(cfg, null, 2);
    }
    if (elements.snapshotMeta && metaText) {
      elements.snapshotMeta.textContent = metaText;
    }
  }

  function collectAttendanceFromForm() {
    return normalizeAttendance({
      min_start_A: parseNumber(elements.minStartA.value, DEFAULTS.min_start_A, { min: 0.1, max: 1 }),
      min_start_B: parseNumber(elements.minStartB.value, DEFAULTS.min_start_B, { min: 0.1, max: 1 }),
      min_bench_A: parseNumber(elements.minBenchA.value, DEFAULTS.min_bench_A, { min: 0.1, max: 1 }),
      min_bench_B: parseNumber(elements.minBenchB.value, DEFAULTS.min_bench_B, { min: 0.1, max: 1 }),
      target_expected_A: {
        low: parseNumber(elements.targetALow.value, DEFAULTS.target_expected_A.low, { min: 5, max: 60 }),
        high: parseNumber(elements.targetAHigh.value, DEFAULTS.target_expected_A.high, { min: 5, max: 60 }),
      },
      target_expected_B: {
        low: parseNumber(elements.targetBLow.value, DEFAULTS.target_expected_B.low, { min: 5, max: 60 }),
        high: parseNumber(elements.targetBHigh.value, DEFAULTS.target_expected_B.high, { min: 5, max: 60 }),
      },
      attendance_target_fraction: parseNumber(
        elements.targetFraction.value,
        DEFAULTS.attendance_target_fraction,
        { min: 0.1, max: 1 },
      ),
      hard_commit_floor: parseNumber(elements.hardCommitFloor.value, DEFAULTS.hard_commit_floor, { min: 0.2, max: 1 }),
      no_response_multiplier: parseNumber(
        elements.noResponseMultiplier.value,
        DEFAULTS.no_response_multiplier,
        { min: 0.2, max: 1 },
      ),
      high_reliability_balance_ratio: parseNumber(
        elements.reliabilityRatio.value,
        DEFAULTS.high_reliability_balance_ratio,
        { min: 0.25, max: 4 },
      ),
    });
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data.workerUrl) elements.workerUrl.value = data.workerUrl;
      if (data.branch) elements.branchInput.value = data.branch;
      if (data.adminKey) elements.adminKey.value = data.adminKey;
    } catch (err) {
      console.warn("Konnte gespeicherte Einstellungen nicht laden", err);
    }
  }

  function storeSettings() {
    try {
      const data = {
        workerUrl: elements.workerUrl.value || "",
        branch: elements.branchInput.value || "",
        adminKey: elements.adminKey.value || "",
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (err) {
      console.warn("Konnte Einstellungen nicht speichern", err);
    }
  }

  async function fetchLatestSnapshot() {
    const url = dsroShared.buildLatestJsonUrl({ cacheBuster: `?v=${Date.now()}` });
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`latest.json HTTP ${res.status}`);
    const json = await res.json();
    lastLoadedGeneratedAt = json.generated_at || null;
    return json;
  }

  async function fetchYamlFallback() {
    const base = dsroShared.computeSiteRoot(location.pathname);
    const url = `${base}data/attendance_config.yml?v=${Date.now()}`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`attendance_config.yml HTTP ${res.status}`);
    return res.text();
  }

  async function loadAttendance() {
    setPill(elements.statusPill, "Lade…", "muted");
    try {
      const latest = await fetchLatestSnapshot();
      const snapshot = latest?.attendance?.config_snapshot;
      if (snapshot) {
        applyToForm(snapshot, "out/latest.json");
        log("Konfiguration aus out/latest.json geladen");
        setPill(elements.statusPill, "Geladen", "success");
        setPill(elements.buildPill, latest.generated_at || "Build-Zeit unbekannt", "muted");
        return;
      }
      log("Kein Snapshot in latest.json gefunden – prüfe YAML");
    } catch (err) {
      log(`latest.json konnte nicht geladen werden (${err?.message || err})`);
    }

    try {
      const yaml = await fetchYamlFallback();
      const parsed = parseYamlFallback(yaml);
      if (parsed) {
        applyToForm(parsed, "data/attendance_config.yml");
        log("Konfiguration aus data/attendance_config.yml geladen");
        setPill(elements.statusPill, "Geladen (YAML)", "muted");
        return;
      }
    } catch (err) {
      log(`YAML-Fallback fehlgeschlagen (${err?.message || err})`);
    }

    applyToForm(DEFAULTS, "Defaults (Fallback)");
    setPill(elements.statusPill, "Fallback", "warning");
    log("Fallback-Defaults angewandt – bitte prüfen");
  }

  async function persistAttendanceConfig(attendance) {
    const endpoint = (elements.workerUrl.value || "").trim() || dsroShared.DEFAULT_WORKER_BASE + "attendance-config";
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (elements.adminKey.value) {
      headers["X-Admin-Key"] = elements.adminKey.value;
    }
    const payload = {
      attendance,
      ref: elements.branchInput.value || "main",
      reason: "admin attendance config update",
    };
    const res = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      mode: "cors",
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `Worker HTTP ${res.status}`);
    }
    let json = {};
    try {
      json = await res.json();
    } catch (err) {
      json = {};
    }
    return json;
  }

  async function triggerBuild(reasonText) {
    await dsroShared.triggerRosterBuild({
      branch: elements.branchInput.value,
      reason: reasonText,
      adminKey: elements.adminKey.value,
      workerUrl: elements.workerUrl.value,
    });
  }

  function disableForm(disabled) {
    elements.saveBtn.disabled = disabled;
    elements.reloadBtn.disabled = disabled;
    elements.workerUrl.disabled = disabled;
    elements.branchInput.disabled = disabled;
    elements.adminKey.disabled = disabled;
  }

  async function saveAndRebuild() {
    const attendance = collectAttendanceFromForm();
    storeSettings();
    disableForm(true);
    setPill(elements.statusPill, "Speichere…", "muted");
    log("Sende Konfiguration an Worker…");
    try {
      const response = await persistAttendanceConfig(attendance);
      const commitMsg = response?.commit?.message || "Attendance-Config aktualisiert";
      log(commitMsg);
      setPill(elements.statusPill, "Gespeichert", "success");
    } catch (err) {
      log(`Speichern fehlgeschlagen: ${err?.message || err}`);
      setPill(elements.statusPill, "Fehler", "error");
      disableForm(false);
      return;
    }

    log("Roster-Build wird angestoßen…");
    setPill(elements.buildPill, "Rebuild läuft…", "warning");
    try {
      await triggerBuild("attendance config updated");
      log("Build-Dispatch gesendet");
    } catch (err) {
      log(`Build-Dispatch fehlgeschlagen: ${err?.message || err}`);
      setPill(elements.buildPill, "Dispatch fehlgeschlagen", "error");
      disableForm(false);
      return;
    }

    pollForNewSnapshot(attendance);
  }

  async function pollForNewSnapshot(targetAttendance) {
    const startedAt = Date.now();
    const timeoutMs = 8 * 60 * 1000;
    const poll = async () => {
      if (Date.now() - startedAt > timeoutMs) {
        setPill(elements.buildPill, "Timeout", "error");
        log("Kein neuer Build innerhalb des Zeitlimits gefunden");
        disableForm(false);
        return;
      }
      try {
        const latest = await fetchLatestSnapshot();
        const snapshot = latest?.attendance?.config_snapshot;
        const generatedAt = latest?.generated_at || null;
        if (generatedAt && (!lastLoadedGeneratedAt || generatedAt !== lastLoadedGeneratedAt)) {
          lastLoadedGeneratedAt = generatedAt;
          const source = latest?.attendance?.config_source?.path || "out/latest.json";
          applyToForm(snapshot || targetAttendance, source);
          renderSnapshot(snapshot || targetAttendance, `${source} @ ${generatedAt}`);
          setPill(elements.buildPill, `Fertig @ ${generatedAt}`, "success");
          log("Neuer Build gefunden – Snapshot aktualisiert");
          disableForm(false);
          return;
        }
      } catch (err) {
        log(`Polling-Fehler: ${err?.message || err}`);
      }
      setTimeout(poll, 8000);
    };
    setTimeout(poll, 5000);
  }

  function wireInputs() {
    const sliders = [
      elements.minStartA,
      elements.minStartB,
      elements.minBenchA,
      elements.minBenchB,
      elements.hardCommitFloor,
      elements.noResponseMultiplier,
    ];
    sliders.forEach((el) => el?.addEventListener("input", updateValueLabels));
    elements.reloadBtn?.addEventListener("click", () => loadAttendance());
    elements.saveBtn?.addEventListener("click", () => saveAndRebuild());
  }

  function init() {
    loadSettings();
    wireInputs();
    loadAttendance();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
