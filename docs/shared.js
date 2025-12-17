(function(global){
  global.dsroShared = global.dsroShared || {};
  const shared = global.dsroShared;
  const ZERO_WIDTH_RE = /[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]/g;
  const COMBINING_DOT_ABOVE_RE = /\u0307/g;
  const CONFUSABLE_FOLD = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I", "Ј": "J", "У": "Y",
    "а": "a", "в": "b", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x",
    "у": "y", "к": "k", "м": "m", "т": "t", "н": "h", "і": "i", "ј": "j",
    "ѵ": "y", "ӏ": "l", "Ӏ": "l", "Ь": "b", "ь": "b", "Ъ": "b", "ъ": "b",
    "İ": "I", "ı": "i",
  };

  function normalizeConfusables(value) {
    if (!value) return value;
    return value.split("").map(ch => CONFUSABLE_FOLD[ch] || ch).join("");
  }

  function canonicalNameJS(value) {
    if (value == null) return "";
    let s = String(value);
    if (typeof s.normalize === "function") {
      s = s.normalize("NFKD");
    }
    s = normalizeConfusables(s);
    s = s.replace(ZERO_WIDTH_RE, "");
    s = s.replace(COMBINING_DOT_ABOVE_RE, "");
    s = s.toLocaleLowerCase("en-US");
    s = normalizeConfusables(s);
    s = s.replace(COMBINING_DOT_ABOVE_RE, "");
    if (typeof s.normalize === "function") {
      s = s.normalize("NFKC");
    }
    s = s.trim().replace(/\s+/g, " ");
    return s;
  }

  function normalizePlayerName(rawName) {
    if (typeof rawName !== "string") return "";
    let name = rawName.trim();
    name = name.replace(ZERO_WIDTH_RE, "");
    name = name.replace(/\s+/g, " ");
    return name;
  }

  function escapeHtml(value) {
    return value == null ? "" : String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function computeSiteRoot(pathname) {
    const path = pathname || "/";
    const adminIdx = path.indexOf("/admin/");
    if (adminIdx !== -1) return path.slice(0, adminIdx + 1);
    return path.endsWith("/") ? path : path.replace(/[^/]*$/, "/");
  }

  const DS_EVENT_ID_RE = /DS-(\d{4})-(\d{2})-(\d{2})-[AB]/gi;

  function parseDsEventDate(ymd) {
    if (!ymd || typeof ymd !== "string") return null;
    const parts = ymd.split("-").map(part => Number.parseInt(part, 10));
    if (parts.length !== 3 || parts.some(num => Number.isNaN(num))) return null;
    const [year, month, day] = parts;
    const date = new Date(Date.UTC(year, month - 1, day));
    if (Number.isNaN(date.getTime())) return null;
    return date;
  }

  function extractDsEventDatesFromPayload(payload) {
    const dates = { ids: [], iso: [] };
    const seen = new Set();

    const addDate = (bucket, candidate) => {
      const dt = candidate instanceof Date ? candidate : parseDsEventDate(candidate);
      if (dt) bucket.push(dt);
    };

    const walk = (value) => {
      if (!value) return;
      if (typeof value === "string") {
        const regex = new RegExp(DS_EVENT_ID_RE);
        let match;
        while ((match = regex.exec(value))) {
          addDate(dates.ids, `${match[1]}-${match[2]}-${match[3]}`);
        }
        const isoPrefix = value.match(/^(\d{4}-\d{2}-\d{2})/);
        if (isoPrefix && isoPrefix[1]) {
          addDate(dates.iso, isoPrefix[1]);
        }
        return;
      }
      if (typeof value !== "object") return;
      if (seen.has(value)) return;
      seen.add(value);
      if (Array.isArray(value)) {
        value.forEach(walk);
        return;
      }
      Object.values(value).forEach(walk);
    };

    walk(payload);
    return dates;
  }

  function computeNextFriday(afterDate, { strict = true } = {}) {
    const base = afterDate instanceof Date ? new Date(afterDate.getTime()) : new Date();
    if (Number.isNaN(base.getTime())) return null;
    base.setUTCHours(0, 0, 0, 0);
    if (strict) {
      base.setUTCDate(base.getUTCDate() + 1);
    }
    const day = base.getUTCDay();
    const delta = (5 - day + 7) % 7;
    base.setUTCDate(base.getUTCDate() + delta);
    return base;
  }

  function formatDsEventId(date, groupLetter) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
    const group = (groupLetter || "").toString().trim().toUpperCase();
    if (!group || !/[AB]/.test(group)) return "";
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, "0");
    const day = String(date.getUTCDate()).padStart(2, "0");
    return `DS-${year}-${month}-${day}-${group}`;
  }

  function suggestDsEventIdForGroup({ groupLetter, payload, now = new Date() } = {}) {
    try {
      const eventDateLocal = payload?.event?.event_datetime_local;
      if (eventDateLocal) {
        const dt = new Date(eventDateLocal);
        if (!Number.isNaN(dt.getTime())) {
          const parts = new Intl.DateTimeFormat("en-CA", {
            timeZone: "Europe/Zurich",
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
          }).format(dt);
          const parsed = parseDsEventDate(parts);
          const suggestion = formatDsEventId(parsed, groupLetter);
          if (suggestion) return suggestion;
        }
      }

      const { ids, iso } = extractDsEventDatesFromPayload(payload);
      const pickLatest = (arr = []) => (arr.length
        ? arr.reduce((max, current) => (max && max > current ? max : current), null)
        : null);
      const lastEventDate = pickLatest(ids) || null;
      const referenceIso = pickLatest(iso);
      const reference = lastEventDate || referenceIso || now;
      const nextFriday = computeNextFriday(reference, { strict: true });
      return formatDsEventId(nextFriday, groupLetter);
    } catch (err) {
      console.error("DS_EVENT_ID_SUGGEST_FAILED", err);
      return "";
    }
  }

  function buildLatestJsonUrl({ branchOverride, cacheBuster, siteRoot } = {}) {
    const cache = typeof cacheBuster === "string" ? cacheBuster : `?v=${Date.now()}`;
    const base = siteRoot || computeSiteRoot(typeof location !== "undefined" ? (location.pathname || "/") : "/");
    if (branchOverride) {
      return `https://raw.githubusercontent.com/its-h4k1/desert-storm-roster-optimizer/${branchOverride}/out/latest.json${cache}`;
    }
    return `${base}out/latest.json${cache}`;
  }

  const DEFAULT_WORKER_BASE = "https://ds-commit.hak1.workers.dev/";
  const DEFAULT_DISPATCH_URL = `${DEFAULT_WORKER_BASE}dispatch`;
  const DEFAULT_WRITE_FILE_URL = `${DEFAULT_WORKER_BASE}write-file`;

  async function fetchJsonWithErrors(url, { cache = "no-store" } = {}) {
    let response;
    try {
      response = await fetch(url, { cache });
    } catch (err) {
      const wrapped = new Error(err?.message || "Netzwerkfehler");
      wrapped.cause = err;
      throw wrapped;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${response.statusText}`);
    }
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch (err) {
      const parseErr = new Error("Antwort ist kein gültiges JSON");
      parseErr.cause = err;
      throw parseErr;
    }
  }

  class RosterBuildTriggerError extends Error {
    constructor(message, { status, body } = {}) {
      super(message);
      this.name = "RosterBuildTriggerError";
      this.status = typeof status === "number" ? status : null;
      this.body = body || null;
    }
  }

  function readSharedAdminSettings() {
    if (typeof localStorage === "undefined") return null;
    try {
      const raw = localStorage.getItem("dsro-admin-settings");
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      console.warn("Konnte dsro-admin-settings nicht lesen", err);
      return null;
    }
  }

  // Zentrale Admin-Konfiguration (u. a. Worker-Secret) liegt in localStorage unter "dsro-admin-settings".
  // Admin-Seiten sollen den Key immer über diese Helper lesen/speichern, nicht über eigene Variablen.
  function writeSharedAdminSettings(update = {}) {
    if (typeof localStorage === "undefined") return null;
    try {
      const current = readSharedAdminSettings() || {};
      const next = { ...current, ...update };
      localStorage.setItem("dsro-admin-settings", JSON.stringify(next));
      return next;
    } catch (err) {
      console.warn("Konnte dsro-admin-settings nicht speichern", err);
      return null;
    }
  }

  // Liefert den getrimmten Admin-Key aus dem Shared-Storage oder optionalen Fallbacks.
  function getAdminKey(fallback = "") {
    const shared = readSharedAdminSettings();
    return (shared?.adminKey || fallback || "").toString().trim();
  }

  function saveAdminKey(value) {
    return writeSharedAdminSettings({ adminKey: (value || "").toString().trim() });
  }

  // Füllt ein Admin-Key-Input mit dem gespeicherten Wert und kann Änderungen
  // automatisch zurück in den Shared-Storage spiegeln. Optional kann zusätzlich
  // eine eigene onChange-Callback (z. B. Persistenz für Seiteneinstellungen)
  // gehängt werden. Mit syncOnInput=false werden Eingaben nur vorbefüllt und
  // onChange ohne Speichern aufgerufen.
  function applyAdminKeyInput(input, { onChange, syncOnInput = true } = {}) {
    if (!input) return () => {};
    const stored = getAdminKey();
    if (stored && !input.value) {
      input.value = stored;
    }
    const handler = () => {
      const trimmed = (input.value || "").trim();
      if (syncOnInput) saveAdminKey(trimmed);
      if (typeof onChange === "function") onChange(trimmed);
    };
    handler();
    if (!syncOnInput) return () => {};
    input.addEventListener("input", handler);
    input.addEventListener("change", handler);
    return () => {
      input.removeEventListener("input", handler);
      input.removeEventListener("change", handler);
    };
  }

  // Standardisierter Admin-Key-Gatekeeper für Admin-Seiten.
  // Erwartet DOM-Elemente (Status, Fallback-Eingabe/-Button, Hinweisbanner)
  // und ruft onValid exakt einmal auf, sobald ein (beliebiger) Key vorliegt.
  // Bei Fehlern wird ein sichtbarer Status gesetzt und es wird nie in einem
  // "prüfen…"-State hängen geblieben.
  function initAdminKeyGate({
    statusEl,
    fallbackInput,
    fallbackRow,
    fallbackButton,
    settingsToggle,
    alertEl,
    onValid,
    renderStatus,
  } = {}) {
    let initialized = false;

    const openSettings = () => {
      if (settingsToggle && typeof settingsToggle === "object") {
        try { settingsToggle.open = true; } catch (_) { /* ignore */ }
      }
    };

    const closeSettings = () => {
      if (settingsToggle && typeof settingsToggle === "object") {
        try { settingsToggle.open = false; } catch (_) { /* ignore */ }
      }
    };

    const render = ({ message, tone = "info", showAlert = false }) => {
      if (typeof renderStatus === "function") {
        renderStatus({ message, tone, showAlert });
      } else if (statusEl) {
        statusEl.textContent = message || "";
        const base = statusEl.className || "";
        const cls = tone === "error" ? "warn" : tone === "success" ? "info" : tone;
        statusEl.className = `${base}`.split(" ").filter(Boolean).filter(c => !/^pill$/.test(c)).join(" ");
        statusEl.classList.add("pill");
        if (cls) statusEl.classList.add(cls);
      }
      if (alertEl) {
        alertEl.style.display = showAlert ? "grid" : "none";
      }
      if (fallbackRow) {
        fallbackRow.style.display = showAlert ? "block" : "none";
      }
      if (showAlert) openSettings();
    };

    const showFallback = () => {
      if (fallbackRow) fallbackRow.style.display = "block";
      if (alertEl) alertEl.style.display = "grid";
      openSettings();
    };

    const handleError = (err) => {
      console.error("admin-key: error", err);
      render({ message: "Admin-Key konnte nicht geprüft werden.", tone: "error", showAlert: true });
    };

    const check = () => {
      console.debug("admin-key: start check");
      render({ message: "Admin-Key wird geprüft…", tone: "info", showAlert: false });
      let key = "";
      try {
        key = getAdminKey();
      } catch (err) {
        handleError(err);
        return;
      }
      if (key) {
        console.debug("admin-key: success");
        render({ message: "Admin-Key ist gesetzt (zentral verwaltet).", tone: "success", showAlert: false });
        closeSettings();
        if (!initialized && typeof onValid === "function") {
          initialized = true;
          try { onValid(key); } catch (err) { handleError(err); }
        }
      } else {
        console.debug("admin-key: missing");
        render({
          message: "Kein Admin-Key gesetzt – bitte über die Admin-Startseite einloggen.",
          tone: "warn",
          showAlert: true,
        });
        showFallback();
      }
    };

    const applyFallback = () => {
      if (!fallbackInput) return;
      const value = (fallbackInput.value || "").trim();
      if (!value) {
        render({ message: "Bitte Admin-Key eingeben.", tone: "warn", showAlert: true });
        return;
      }
      try {
        saveAdminKey(value);
        render({ message: "Admin-Key gespeichert, prüfe…", tone: "info", showAlert: false });
        check();
      } catch (err) {
        handleError(err);
      }
    };

    applyAdminKeyInput(fallbackInput, { syncOnInput: false });
    if (fallbackButton) fallbackButton.addEventListener("click", applyFallback);
    check();

    return { refresh: check, applyFallback, openSettings, closeSettings };
  }

  function readInputValue(el, fallback = "") {
    if (!el) return fallback;
    return (el.value || fallback || "").toString().trim();
  }

  function applyInputValue(el, value) {
    if (!el) return;
    const trimmed = (value || "").toString();
    el.value = trimmed;
  }

  function initSharedAdminSettings({
    settingsToggle,
    workerInput,
    branchInput,
    adminKeyStatus,
    adminKeyFallbackRow,
    adminKeyFallbackInput,
    adminKeyFallbackButton,
    alertEl,
    defaultWorkerUrl = DEFAULT_WRITE_FILE_URL,
    defaultBranch = "main",
    onValidAdminKey,
  } = {}) {
    const restoreSettings = () => {
      const sharedSettings = readSharedAdminSettings() || {};
      applyInputValue(workerInput, sharedSettings.workerUrl || defaultWorkerUrl);
      applyInputValue(branchInput, sharedSettings.customBranch || sharedSettings.branchSelect || defaultBranch);
      if (!readInputValue(workerInput)) applyInputValue(workerInput, defaultWorkerUrl);
      if (!readInputValue(branchInput)) applyInputValue(branchInput, defaultBranch);
    };

    const persistSettings = () => {
      const update = {};
      if (workerInput) update.workerUrl = readInputValue(workerInput, defaultWorkerUrl);
      if (branchInput) update.customBranch = readInputValue(branchInput, defaultBranch);
      writeSharedAdminSettings(update);
    };

    const getWorkerUrl = () => readInputValue(workerInput, defaultWorkerUrl) || defaultWorkerUrl;
    const getBranch = () => readInputValue(branchInput, defaultBranch) || defaultBranch;

    const gate = initAdminKeyGate({
      statusEl: adminKeyStatus,
      fallbackInput: adminKeyFallbackInput,
      fallbackRow: adminKeyFallbackRow,
      fallbackButton: adminKeyFallbackButton,
      settingsToggle,
      alertEl,
      onValid: (key) => {
        if (typeof onValidAdminKey === "function") onValidAdminKey(key);
      },
    });

    if (workerInput) workerInput.addEventListener("change", persistSettings);
    if (branchInput) branchInput.addEventListener("change", persistSettings);

    applyAdminKeyInput(adminKeyFallbackInput, { syncOnInput: false });
    restoreSettings();

    const openSettings = () => gate.openSettings();
    const closeSettings = () => gate.closeSettings();

    return {
      getWorkerUrl,
      getBranch,
      refreshAdminKey: gate.refresh,
      applyFallback: gate.applyFallback,
      openSettings,
      closeSettings,
      persistSettings,
    };
  }

  // Baut einen Header-Satz mit X-Admin-Key (falls vorhanden). Sollte von allen
  // Admin-Seiten für Worker-/API-Calls verwendet werden.
  function buildAdminHeaders({ adminKey, headers } = {}) {
    const base = { ...(headers || {}) };
    const key = (adminKey || getAdminKey() || "").trim();
    if (key) {
      base["X-Admin-Key"] = key;
    }
    return base;
  }

  function resolveDispatchUrl({ workerUrl, dispatchUrl } = {}) {
    const fallback = DEFAULT_DISPATCH_URL;
    const candidate = (dispatchUrl || workerUrl || "").trim();
    if (!candidate) return fallback;
    try {
      const url = new URL(candidate, fallback);
      const path = url.pathname || "/";
      if (/\/dispatch\/?$/.test(path)) {
        url.pathname = path.replace(/\/+$/, "");
        url.search = "";
        url.hash = "";
        return url.toString();
      }
      let basePath = path;
      if (!basePath.endsWith("/")) {
        const idx = basePath.lastIndexOf("/");
        basePath = idx === -1 ? "/" : basePath.slice(0, idx + 1);
      }
      if (!basePath.endsWith("/")) basePath += "/";
      url.pathname = `${basePath}dispatch`;
      url.search = "";
      url.hash = "";
      return url.toString();
    } catch (err) {
      console.warn("Dispatch-URL ungültig, verwende Fallback", err);
      return fallback;
    }
  }

  async function triggerRosterBuild({ branch, reason, adminKey, workerUrl, dispatchUrl } = {}) {
    const sharedSettings = readSharedAdminSettings();
    const ref = (branch || sharedSettings?.customBranch || sharedSettings?.branchSelect || "main").trim() || "main";
    const resolvedWorkerUrl = workerUrl || sharedSettings?.workerUrl || null;
    const resolvedAdminKey = adminKey || sharedSettings?.adminKey || "";
    const endpoint = resolveDispatchUrl({ workerUrl: resolvedWorkerUrl, dispatchUrl });
    const reasonText = (reason || "admin roster rebuild").trim() || "admin roster rebuild";
    const payload = {
      ref,
      reason: reasonText,
      inputs: { reason: reasonText },
    };
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (resolvedAdminKey) {
      headers["X-Admin-Key"] = resolvedAdminKey;
    }
    let response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        mode: "cors",
      });
    } catch (err) {
      throw new RosterBuildTriggerError(err?.message || "Netzwerkfehler", { body: null });
    }
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new RosterBuildTriggerError(text || `HTTP ${response.status}` , { status: response.status, body: text });
    }
    let result = {};
    try {
      result = await response.json();
    } catch (err) {
      result = {};
    }
    return result;
  }

  function initAdminLayout({ containerSelector = ".admin-shell", openClass = "admin-nav-open", closeBreakpoint = 1200 } = {}) {
    if (typeof document === "undefined") return () => {};
    const container = document.querySelector(containerSelector) || document.body;
    const toggle = document.querySelector(".sidebar-toggle");
    const close = document.querySelector(".sidebar-close");
    const overlay = document.querySelector(".admin-overlay");

    if (!container || (!toggle && !close && !overlay)) return () => {};

    const toggleNav = () => container.classList.toggle(openClass);
    const closeNav = () => container.classList.remove(openClass);
    const handleResize = () => {
      if (window.innerWidth >= closeBreakpoint) {
        closeNav();
      }
    };

    toggle?.addEventListener("click", toggleNav);
    close?.addEventListener("click", closeNav);
    overlay?.addEventListener("click", closeNav);
    window.addEventListener("resize", handleResize);

    return () => {
      toggle?.removeEventListener("click", toggleNav);
      close?.removeEventListener("click", closeNav);
      overlay?.removeEventListener("click", closeNav);
      window.removeEventListener("resize", handleResize);
    };
  }


  function toNumberOrZero(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
  }

  function normalizeReliabilityEntry(rawStats) {
    if (!rawStats || typeof rawStats !== "object") return null;
    const normalized = {
      events: toNumberOrZero(
        rawStats.events
        ?? rawStats.events_seen
        ?? rawStats.assignments
        ?? rawStats.event_count
        ?? rawStats.total_events
      ),
      attendance: toNumberOrZero(
        rawStats.attendance
        ?? rawStats.shows
        ?? rawStats.show_count
        ?? rawStats.attended
        ?? rawStats.attendance_count
      ),
      noShows: toNumberOrZero(
        rawStats.noShows
        ?? rawStats.no_shows
        ?? rawStats.noshow
        ?? rawStats.noshow_count
        ?? rawStats.no_show_count
        ?? rawStats.missed
      ),
      earlyCancels: toNumberOrZero(
        rawStats.earlyCancels
        ?? rawStats.early_cancels
        ?? rawStats.cancel_early_count
        ?? rawStats.early_cancel_count
      ),
      lateCancels: toNumberOrZero(
        rawStats.lateCancels
        ?? rawStats.late_cancels
        ?? rawStats.cancel_late_count
        ?? rawStats.late_cancel_count
      ),
    };
    return normalized;
  }

  function parseReliabilityStartDate(raw) {
    if (typeof raw !== "string") return null;
    const trimmed = raw.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return null;
    const parsed = new Date(`${trimmed}T00:00:00Z`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function computeEventResultIdsSince(startDate) {
    const ids = [];
    if (!(startDate instanceof Date) || Number.isNaN(startDate.getTime())) return ids;
    const today = new Date();
    const dt = new Date(Date.UTC(
      startDate.getUTCFullYear(),
      startDate.getUTCMonth(),
      startDate.getUTCDate(),
    ));
    const MAX_WEEKS = 520; // ~10 Jahre als Schutz vor Endlosschleifen
    while (dt <= today && ids.length < MAX_WEEKS) {
      ids.push(`DS-${dt.toISOString().slice(0, 10)}`);
      dt.setUTCDate(dt.getUTCDate() + 7);
    }
    return ids;
  }

  async function fetchEventResultsSince(startDate, { siteRoot, cacheBuster } = {}) {
    if (!(startDate instanceof Date) || Number.isNaN(startDate.getTime())) return [];
    const cache = typeof cacheBuster === "string" ? cacheBuster : `?v=${Date.now()}`;
    const base = siteRoot || computeSiteRoot(typeof location !== "undefined" ? (location.pathname || "/") : "/");
    const ids = computeEventResultIdsSince(startDate);
    const results = [];

    for (const id of ids) {
      const url = `${base}data/event_results/${id}.json${cache}`;
      try {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) continue;
        const data = await response.json();
        data.event_id = data.event_id || id;
        results.push(data);
      } catch (err) {
        console.warn("Event-Result konnte nicht geladen werden", { id, err });
      }
    }

    return results;
  }

  function computeReliabilityStatsFromEventResults(events) {
    const stats = {};
    const aliasMap = shared.aliasMap instanceof Map ? shared.aliasMap : null;

    (events || []).forEach((evt) => {
      if (!Array.isArray(evt?.results)) return;
      (evt.results || []).forEach((res) => {
        const canon = canonicalNameJS(res.player_key || res.player || res.display_name_snapshot);
        if (!canon) return;
        const resolved = aliasMap?.get(canon) || canon;
        stats[resolved] = stats[resolved] || {
          events: 0,
          attendance: 0,
          noShows: 0,
          earlyCancels: 0,
          lateCancels: 0,
        };
        stats[resolved].events += 1;
        const attended = !!res.attended || !!res.Teilgenommen;
        if (attended) {
          stats[resolved].attendance += 1;
        } else {
          stats[resolved].noShows += 1;
        }
        if (res.early_cancel || res.earlyCancel) stats[resolved].earlyCancels += 1;
        if (res.late_cancel || res.lateCancel) stats[resolved].lateCancels += 1;
      });
    });

    return stats;
  }

  function deriveEventDateFromId(eventId) {
    const match = typeof eventId === "string" && eventId.match(/^DS-(\d{4})-(\d{2})-(\d{2})/);
    if (match && match[1] && match[2] && match[3]) {
      return `${match[1]}-${match[2]}-${match[3]}`;
    }
    return null;
  }

  function deriveEventDate(event) {
    if (!event) return null;
    const eventId = event.event_id || event.eventId || event.id || "";
    const fromId = deriveEventDateFromId(eventId);
    if (fromId) return fromId;
    if (typeof event.event_date === "string") return event.event_date.slice(0, 10);
    if (typeof event.date === "string") return event.date.slice(0, 10);
    if (typeof event.meta?.event_date === "string") return event.meta.event_date.slice(0, 10);
    return null;
  }

  function buildPlayerEventHistoryIndex(events) {
    const map = new Map();
    const aliasMap = shared.aliasMap instanceof Map ? shared.aliasMap : null;

    (events || []).forEach((evt) => {
      if (!Array.isArray(evt?.results)) return;
      const eventId = evt.event_id || evt.eventId || evt.id || "";
      const date = deriveEventDate(evt) || deriveEventDateFromId(eventId) || "";

      (evt.results || []).forEach((res) => {
        const canon = canonicalNameJS(res.player_key || res.player || res.display_name_snapshot);
        if (!canon) return;
        const resolved = aliasMap?.get(canon) || canon;
        const attended = !!res.attended || !!res.Teilgenommen;
        const current = map.get(resolved) || [];
        current.push({ eventId, date, attended });
        map.set(resolved, current);
      });
    });

    map.forEach((arr, key) => {
      arr.sort((a, b) => {
        const left = a.date || a.eventId || "";
        const right = b.date || b.eventId || "";
        return right.localeCompare(left);
      });
      map.set(key, arr);
    });

    shared.playerEventHistoryIndex = map;
    return map;
  }

  function buildRollingReliabilityIndex({ windowSize } = {}) {
    const historyIndex = shared.playerEventHistoryIndex instanceof Map ? shared.playerEventHistoryIndex : null;
    const size = Number.isFinite(windowSize) && windowSize > 0 ? windowSize : (shared.rollingReliabilityWindowSize || 5);
    const index = new Map();

    if (historyIndex && historyIndex.size) {
      historyIndex.forEach((events, canon) => {
        const window = Array.isArray(events) ? events.slice(0, size) : [];
        const attendance = window.filter((evt) => evt.attended === true).length;
        const noShows = window.filter((evt) => evt.attended === false).length;
        const stats = {
          events: window.length,
          attendance,
          noShows,
          earlyCancels: 0,
          lateCancels: 0,
          basisN: window.length,
          windowSize: size,
        };
        index.set(canon, stats);
      });
    }

    shared.rollingReliabilityWindowSize = size;
    shared.rollingReliabilityIndex = index;
    return index;
  }

  function refreshPlayerReliabilityIndex() {
    const index = new Map();
    const rel = shared.playerReliability || {};
    const aliasMap = shared.aliasMap instanceof Map ? shared.aliasMap : null;

    Object.entries(rel).forEach(([name, stats]) => {
      const canon = canonicalNameJS(name || "");
      if (!canon) return;
      const resolved = aliasMap?.get(canon) || canon;
      index.set(canon, stats);
      index.set(resolved, stats);
    });

    shared.playerReliabilityCanonIndex = index;
    return index;
  }

  async function hydrateReliabilityFromPayload(payload, { siteRoot, cacheBuster } = {}) {
    shared.latestPayload = payload || null;
    if (shared.prepareAliasMapFromPayload) {
      shared.prepareAliasMapFromPayload(payload);
    }
    const rawStartDate = (typeof payload?.reliability_config?.reliability_start_date === "string"
      ? payload.reliability_config.reliability_start_date
      : null)
      || (typeof payload?.reliability?.meta?.reliability_start_date === "string"
        ? payload.reliability?.meta?.reliability_start_date
        : null)
      || (typeof payload?.analysis?.reliability?.meta?.reliability_start_date === "string"
        ? payload.analysis?.reliability?.meta?.reliability_start_date
        : null)
      || null;

    const normalizedStartDate = typeof rawStartDate === "string" ? rawStartDate.trim() : null;
    const parsedStartDate = parseReliabilityStartDate(normalizedStartDate);

    const startDateMissing = !normalizedStartDate;
    const startDateInvalid = !!normalizedStartDate && !parsedStartDate;
    shared.reliabilityStartDate = normalizedStartDate || null;
    shared.reliabilityStartDateParsed = parsedStartDate || null;
    shared.reliabilityError = startDateMissing || startDateInvalid
      ? "Reliability start date missing or invalid"
      : null;
    shared.reliabilityMeta = {
      startDateRaw: shared.reliabilityStartDate || null,
      startDateParsed: shared.reliabilityStartDateParsed || null,
      mode: shared.reliabilityError ? "error" : "window",
      source: "event-results",
      eventResultsLoaded: 0,
      scopeLabel: shared.reliabilityError
        ? shared.reliabilityError
        : `Seit ${shared.reliabilityStartDate}`,
      error: shared.reliabilityError,
    };

    if (shared.reliabilityError) {
      shared.reliabilityEventResults = [];
      shared.playerReliability = {};
      shared.playerEventHistoryIndex = new Map();
      shared.rollingReliabilityIndex = new Map();
      refreshPlayerReliabilityIndex();
      return shared.playerReliability;
    }

    const events = await fetchEventResultsSince(shared.reliabilityStartDateParsed, { siteRoot, cacheBuster });
    shared.reliabilityEventResults = events;
    shared.reliabilityMeta.eventResultsLoaded = Array.isArray(events) ? events.length : 0;
    shared.playerReliability = computeReliabilityStatsFromEventResults(events);
    buildPlayerEventHistoryIndex(events);
    buildRollingReliabilityIndex();
    refreshPlayerReliabilityIndex();
    return shared.playerReliability;
  }

  shared.playerReliability = shared.playerReliability || {};
  shared.latestPayload = shared.latestPayload || null;
  shared.aliasMap = shared.aliasMap || new Map();
  shared.playerReliabilityCanonIndex = shared.playerReliabilityCanonIndex || new Map();
  shared.reliabilityStartDate = shared.reliabilityStartDate || null;
  shared.reliabilityStartDateParsed = shared.reliabilityStartDateParsed || null;
  shared.reliabilityEventResults = shared.reliabilityEventResults || [];
  shared.reliabilityError = shared.reliabilityError || null;
  shared.playerEventHistoryIndex = shared.playerEventHistoryIndex || new Map();
  shared.rollingReliabilityIndex = shared.rollingReliabilityIndex || new Map();
  shared.rollingReliabilityWindowSize = shared.rollingReliabilityWindowSize || 5;
  shared.reliabilityMeta = shared.reliabilityMeta || {
    startDateRaw: null,
    startDateParsed: null,
    mode: "error",
    source: "event-results",
    eventResultsLoaded: 0,
    scopeLabel: "Reliability start date missing or invalid",
    error: "Reliability start date missing or invalid",
  };
  shared.REL_MIN_EVENTS_FOR_BUCKET =
    shared.REL_MIN_EVENTS_FOR_BUCKET == null ? 3 : shared.REL_MIN_EVENTS_FOR_BUCKET;
  shared.REL_NO_SHOW_GREEN_MAX =
    shared.REL_NO_SHOW_GREEN_MAX == null ? 0.15 : shared.REL_NO_SHOW_GREEN_MAX;
  shared.REL_NO_SHOW_YELLOW_MAX =
    shared.REL_NO_SHOW_YELLOW_MAX == null ? 0.35 : shared.REL_NO_SHOW_YELLOW_MAX;
  shared.REL_LATE_CANCEL_GREEN_MAX =
    shared.REL_LATE_CANCEL_GREEN_MAX == null ? 0.1 : shared.REL_LATE_CANCEL_GREEN_MAX;

  shared.getPlayerReliability = function (name) {
    if (!name) return null;

    const canon = canonicalNameJS(name);
    if (canon) {
      const aliasMap = shared.aliasMap instanceof Map ? shared.aliasMap : null;
      const resolvedCanon = aliasMap?.get(canon) || canon;
      const index = shared.playerReliabilityCanonIndex instanceof Map
        ? shared.playerReliabilityCanonIndex
        : null;
      if (index && index.size) {
        if (index.has(resolvedCanon)) return index.get(resolvedCanon);
        if (index.has(canon)) return index.get(canon);
      }
    }

    const trimmed = String(name).trim();
    if (!trimmed) return null;
    if (shared.playerReliability[trimmed]) {
      return shared.playerReliability[trimmed];
    }
    const lower = trimmed.toLowerCase();
    for (const key of Object.keys(shared.playerReliability)) {
      if (key.toLowerCase() === lower) {
        return shared.playerReliability[key];
      }
    }
    return null;
  };

  shared.computeReliabilityBucket = function (stats, { minEvents, insufficientTooltip } = {}) {
    const minEventsForBucket = Number.isFinite(minEvents) ? minEvents : shared.REL_MIN_EVENTS_FOR_BUCKET;
    const tooltip = typeof insufficientTooltip === "string"
      ? insufficientTooltip
      : "Noch zu wenig Daten seit reliability_start_date.";
    if (
      !stats
      || typeof stats.events !== "number"
      || stats.events < minEventsForBucket
    ) {
      return {
        bucket: "neu",
        label: "neu",
        tooltip,
      };
    }

    const events = stats.events || 0;
    const noShows = stats.noShows || 0;
    const lateCancels = stats.lateCancels || 0;
    const attendance = stats.attendance || 0;
    const earlyCancels = stats.earlyCancels || 0;

    const noShowRate = events > 0 ? noShows / events : 0;
    const lateCancelRate = events > 0 ? lateCancels / events : 0;

    if (
      noShowRate <= shared.REL_NO_SHOW_GREEN_MAX
      && lateCancelRate <= shared.REL_LATE_CANCEL_GREEN_MAX
    ) {
      return {
        bucket: "hoch",
        label: "hoch",
        tooltip: `Events: ${events} · Attendance: ${attendance} · No-Shows: ${noShows} · Early: ${earlyCancels} · Late: ${lateCancels}`,
      };
    }

    if (noShowRate <= shared.REL_NO_SHOW_YELLOW_MAX) {
      return {
        bucket: "mittel",
        label: "mittel",
        tooltip: `Events: ${events} · Attendance: ${attendance} · No-Shows: ${noShows} · Early: ${earlyCancels} · Late: ${lateCancels}`,
      };
    }

    return {
      bucket: "niedrig",
      label: "niedrig",
      tooltip: `Events: ${events} · Attendance: ${attendance} · No-Shows: ${noShows} · Early: ${earlyCancels} · Late: ${lateCancels}`,
    };
  };

  shared.getRollingReliability = function (nameOrCanon, windowSize = 5) {
    if (!nameOrCanon) return null;
    const normalizedWindow = Number.isFinite(windowSize) && windowSize > 0 ? windowSize : 5;
    const aliasMap = shared.aliasMap instanceof Map ? shared.aliasMap : null;
    const buildIndexIfNeeded = () => {
      const currentIndex = shared.rollingReliabilityIndex;
      if (!(currentIndex instanceof Map) || shared.rollingReliabilityWindowSize !== normalizedWindow) {
        return buildRollingReliabilityIndex({ windowSize: normalizedWindow });
      }
      return currentIndex;
    };

    const canon = canonicalNameJS(nameOrCanon);
    const resolvedCanon = aliasMap?.get(canon) || canon;
    const index = buildIndexIfNeeded();
    if (index.size === 0) return null;

    if (index.has(resolvedCanon)) return index.get(resolvedCanon);
    if (index.has(canon)) return index.get(canon);
    return null;
  };

  shared.prepareAliasMapFromPayload = function (payload) {
    const map = new Map();
    const canonicalDisplay = new Map();
    if (payload && typeof payload === "object") {
      const candidateSources = [payload.alias_map, payload.player_aliases, payload.player_alias_map, payload.aliases];
      candidateSources.forEach((src) => {
        if (!src || typeof src !== "object") return;
        Object.entries(src).forEach(([alias, canonical]) => {
          const aliasKey = canonicalNameJS(alias || "");
          const canonValue = canonicalNameJS(canonical || alias || "");
          if (aliasKey) map.set(aliasKey, canonValue || aliasKey);
        });
      });

      if (payload.canonical_display && typeof payload.canonical_display === "object") {
        Object.entries(payload.canonical_display).forEach(([canon, display]) => {
          const key = canonicalNameJS(canon || "");
          const value = normalizePlayerName(display || canon || "");
          if (key && value) canonicalDisplay.set(key, value);
        });
      }
    }
    shared.aliasMap = map;
    shared.canonicalDisplayMap = canonicalDisplay;
    if (shared.refreshPlayerReliabilityIndex) {
      shared.refreshPlayerReliabilityIndex();
    }
    return map;
  };

  shared.resolvePlayerDisplayName = function (rawName) {
    const normalized = normalizePlayerName(rawName || "");
    const canon = canonicalNameJS(normalized || rawName || "");
    const aliasMap = shared.aliasMap instanceof Map ? shared.aliasMap : null;
    const canonicalDisplay = shared.canonicalDisplayMap instanceof Map ? shared.canonicalDisplayMap : null;
    const resolvedCanon = aliasMap?.get(canon) || canon;
    const display = (canonicalDisplay?.get(resolvedCanon))
      || (canonicalDisplay?.get(canon))
      || normalized
      || rawName
      || resolvedCanon;
    return normalizePlayerName(display) || resolvedCanon;
  };

  function setPlayerInputSelection(inputEl, value, display, { resolver } = {}) {
    if (!inputEl) return;
    const resolveDisplay = typeof resolver === "function" ? resolver : shared.resolvePlayerDisplayName;
    const displayName = display != null ? display : (resolveDisplay ? resolveDisplay(value) : value);
    inputEl.dataset.playerValue = value || "";
    inputEl.dataset.playerDisplay = displayName || value || "";
    inputEl.value = inputEl.dataset.playerDisplay;
    if (!inputEl.value && (inputEl.dataset.playerValue || inputEl.dataset.playerDisplay)) {
      console.debug("[dsroShared] player input cleared but dataset not reset – forcing blank state", {
        playerValue: inputEl.dataset.playerValue,
        playerDisplay: inputEl.dataset.playerDisplay,
      });
      inputEl.dataset.playerValue = "";
      inputEl.dataset.playerDisplay = "";
    }
  }

  function resolvePlayerInputValue(inputEl) {
    if (!inputEl) return "";
    const currentDisplay = (inputEl.value || "").trim();
    const storedDisplay = (inputEl.dataset.playerDisplay || "").trim();
    const storedValue = (inputEl.dataset.playerValue || "").trim();
    if (!currentDisplay && (storedDisplay || storedValue)) {
      console.debug("[dsroShared] Resetting stale player input dataset after manual clear", {
        storedDisplay,
        storedValue,
      });
      inputEl.dataset.playerDisplay = "";
      inputEl.dataset.playerValue = "";
      return "";
    }
    if (storedValue && storedDisplay && currentDisplay === storedDisplay) return storedValue;
    return currentDisplay;
  }

  function resetPlayerInputSelection(inputEl) {
    setPlayerInputSelection(inputEl, "", "");
  }

  shared.setPlayerInputSelection = setPlayerInputSelection;
  shared.resolvePlayerInputValue = resolvePlayerInputValue;
  shared.resetPlayerInputSelection = resetPlayerInputSelection;

  function buildAllKnownPlayersForAdmin(latestPayload) {
    const namesByCanon = new Map();
    const aliasMap = shared.aliasMap instanceof Map ? shared.aliasMap : null;
    const canonicalDisplay = shared.canonicalDisplayMap instanceof Map ? shared.canonicalDisplayMap : null;

    const upsertName = (raw) => {
      const aliasKey = canonicalNameJS(raw || "");
      if (!aliasKey) return;
      const canonical = aliasMap ? aliasMap.get(aliasKey) || aliasKey : aliasKey;
      const display = canonicalDisplay?.get(canonical);
      const normalized = normalizePlayerName(raw || "") || display || canonical;
      const existing = namesByCanon.get(canonical);
      if (!existing || existing === canonical) {
        namesByCanon.set(canonical, normalized);
      }
    };

    const addFromAliasMap = (mapLike) => {
      if (!mapLike) return;
      if (mapLike instanceof Map) {
        mapLike.forEach((canon, alias) => {
          upsertName(alias);
          upsertName(canon);
        });
        return;
      }
      if (typeof mapLike === "object") {
        Object.entries(mapLike).forEach(([alias, canon]) => {
          upsertName(alias);
          upsertName(canon);
        });
      }
    };

    const addFromCanonicalDisplay = (displayMap) => {
      if (!displayMap) return;
      if (displayMap instanceof Map) {
        displayMap.forEach((display, canon) => {
          upsertName(display || canon);
          upsertName(canon);
        });
        return;
      }
      if (typeof displayMap === "object") {
        Object.entries(displayMap).forEach(([canon, display]) => {
          upsertName(display || canon);
          upsertName(canon);
        });
      }
    };

    const addFromObjectKeys = (obj) => {
      if (!obj || typeof obj !== "object") return;
      Object.keys(obj).forEach(upsertName);
    };

    const addFromArray = (arr, pickers = []) => {
      if (!Array.isArray(arr)) return;
      arr.forEach((item) => {
        if (typeof item === "string") {
          upsertName(item);
          return;
        }
        pickers.forEach((fn) => {
          if (typeof fn !== "function") return;
          const candidate = fn(item);
          if (candidate) upsertName(candidate);
        });
      });
    };

    if (latestPayload && typeof latestPayload === "object") {
      addFromAliasMap(latestPayload.alias_map);
      addFromAliasMap(aliasMap);

      addFromCanonicalDisplay(latestPayload.canonical_display);
      addFromCanonicalDisplay(canonicalDisplay);

      addFromArray(latestPayload.alliance?.players, [
        (p) => p?.name,
        (p) => p?.playerName,
      ]);

      addFromArray(latestPayload.alliance_pool, [
        (p) => p?.display,
        (p) => p?.canon,
      ]);

      addFromArray(latestPayload.players, [
        (p) => p?.display,
        (p) => p?.canon,
        (p) => p?.name,
      ]);

      const rosterSources = [
        latestPayload.team_a?.start,
        latestPayload.team_a?.subs,
        latestPayload.team_b?.start,
        latestPayload.team_b?.subs,
        latestPayload.hard_signups_not_in_roster,
      ];
      rosterSources.forEach((source) => {
        addFromArray(source, [
          (entry) => entry?.name,
          (entry) => entry?.raw_name,
        ]);
      });

      addFromObjectKeys(latestPayload.signup_states);
      addFromArray(Object.values(latestPayload.signup_states || {}), [
        (entry) => entry?.name,
        (entry) => entry?.canon,
      ]);

      addFromArray(latestPayload.signups, [
        (s) => s?.playerName,
        (s) => s?.name,
      ]);

      addFromArray(latestPayload?.signup_pool?.file_entries, [
        (entry) => entry?.PlayerName,
        (entry) => entry?.player,
        (entry) => entry?.player_name,
      ]);

      addFromArray(latestPayload?.event_signups?.file_entries, [
        (entry) => entry?.player,
        (entry) => entry?.PlayerName,
      ]);

      addFromArray(latestPayload?.event_responses?.file_entries, [
        (entry) => entry?.player,
        (entry) => entry?.PlayerName,
        (entry) => entry?.player_name,
      ]);

      addFromArray(latestPayload?.event_signups?.removed_from_pool, [(entry) => entry?.player || entry]);
      addFromArray(latestPayload?.event_responses?.removed_from_pool, [(entry) => entry?.player || entry]);
    }

    const eventResults = Array.isArray(shared.reliabilityEventResults)
      ? shared.reliabilityEventResults
      : [];
    eventResults.forEach((event) => {
      addFromArray(event?.results, [
        (res) => res?.display_name_snapshot,
        (res) => res?.player_key,
      ]);
    });

    const sortedEntries = Array.from(namesByCanon.entries())
      .sort((a, b) => a[1].localeCompare(b[1], "de", { sensitivity: "base" }));
    shared.adminPlayerNameByCanon = new Map(sortedEntries);
    shared.allKnownPlayersForAdmin = sortedEntries.map(([, name]) => name);
    return shared.allKnownPlayersForAdmin;
  }

  function buildPlayerAutocompleteIndexForAdmin() {
    const entries = shared.adminPlayerNameByCanon
      ? Array.from(shared.adminPlayerNameByCanon.entries())
      : (shared.allKnownPlayersForAdmin || []).map((name) => [canonicalNameJS(name), name]);
    const index = entries
      .filter((entry) => entry[0])
      .map(([canon, name]) => ({ name, canon, lc: name.toLowerCase() }));
    shared.playerNameIndexForAdmin = index;
    return index;
  }

  function queryPlayerNamesForAdmin(query, maxResults) {
    const index = shared.playerNameIndexForAdmin || [];
    const term = (query || "").trim();
    if (!term) return [];
    const lcTerm = term.toLowerCase();
    const canonTerm = canonicalNameJS(term);
    const limit = Number(maxResults) || 0;
    const results = [];
    for (const entry of index) {
      if (entry.lc.includes(lcTerm) || (canonTerm && entry.canon.includes(canonTerm))) {
        results.push(entry.name);
        if (limit && results.length >= limit) break;
      }
    }
    return results;
  }

  // Helper für Admin-Seiten: baut Alias-Map, Spielerlisten und den Autocomplete-Index
  // auf Basis eines Payload-Snapshots plus optionaler zusätzlicher Namensquellen.
  // Gibt die finale Namensliste zurück.
  function refreshAdminPlayerIndex({ payload, additionalNames = [] } = {}) {
    const sourcePayload = payload || shared.latestPayload || null;
    if (sourcePayload && sourcePayload !== shared.latestPayload) {
      shared.latestPayload = sourcePayload;
    }
    if (shared.prepareAliasMapFromPayload) {
      shared.prepareAliasMapFromPayload(sourcePayload);
    }
    if (shared.buildAllKnownPlayersForAdmin) {
      shared.buildAllKnownPlayersForAdmin(sourcePayload);
    }

    const namesByCanon = new Map(shared.adminPlayerNameByCanon || []);
    const addExtra = (raw) => {
      const normalized = normalizePlayerName(raw || "");
      const aliasKey = canonicalNameJS(normalized);
      if (!aliasKey) return;
      const canonical = shared.aliasMap ? shared.aliasMap.get(aliasKey) || aliasKey : aliasKey;
      const existing = namesByCanon.get(canonical);
      if (!existing || existing === canonical) {
        namesByCanon.set(canonical, normalized || canonical);
      }
    };
    (additionalNames || []).forEach(addExtra);

    const sortedEntries = Array.from(namesByCanon.entries())
      .sort((a, b) => a[1].localeCompare(b[1], "de", { sensitivity: "base" }));
    shared.adminPlayerNameByCanon = new Map(sortedEntries);
    shared.allKnownPlayersForAdmin = sortedEntries.map(([, name]) => name);
    if (shared.buildPlayerAutocompleteIndexForAdmin) {
      shared.buildPlayerAutocompleteIndexForAdmin();
    }
    return shared.allKnownPlayersForAdmin;
  }

  function debugPrintAdminAutocompleteState() {
    console.log("[dsroShared] allKnownPlayersForAdmin:", shared.allKnownPlayersForAdmin);
    console.log(
      "[dsroShared] playerNameIndexForAdmin size:",
      shared.playerNameIndexForAdmin ? shared.playerNameIndexForAdmin.length : 0,
    );
  }

  function debugTestAdminQuery(term) {
    console.log("[dsroShared] admin testQuery:", term, "=>", shared.queryPlayerNamesForAdmin(term, 10));
  }

  function debugCanonical(name) {
    const canonical = canonicalNameJS(name);
    console.log("[dsroShared] canonical", { input: name, canonical });
    return canonical;
  }

  shared.buildAllKnownPlayersForAdmin = buildAllKnownPlayersForAdmin;
  shared.buildPlayerAutocompleteIndexForAdmin = buildPlayerAutocompleteIndexForAdmin;
  shared.queryPlayerNamesForAdmin = queryPlayerNamesForAdmin;
  shared.refreshAdminPlayerIndex = refreshAdminPlayerIndex;
  shared.debugPrintAdminAutocompleteState = debugPrintAdminAutocompleteState;
  shared.debugTestAdminQuery = debugTestAdminQuery;
  shared.debugCanonical = debugCanonical;

  Object.assign(shared, {
    canonicalNameJS,
    normalizePlayerName,
    escapeHtml,
    computeSiteRoot,
    parseReliabilityStartDate,
    buildLatestJsonUrl,
    fetchJsonWithErrors,
    triggerRosterBuild,
    RosterBuildTriggerError,
    DEFAULT_WORKER_BASE,
    DEFAULT_DISPATCH_URL,
    DEFAULT_WRITE_FILE_URL,
    readSharedAdminSettings,
    writeSharedAdminSettings,
    getAdminKey,
    saveAdminKey,
    applyAdminKeyInput,
    initAdminKeyGate,
    initSharedAdminSettings,
    buildAdminHeaders,
    initAdminLayout,
    extractDsEventDatesFromPayload,
    computeNextFriday,
    formatDsEventId,
    suggestDsEventIdForGroup,
    prepareAliasMapFromPayload: shared.prepareAliasMapFromPayload,
    buildAllKnownPlayersForAdmin,
    buildPlayerAutocompleteIndexForAdmin,
    queryPlayerNamesForAdmin,
    refreshAdminPlayerIndex,
    debugPrintAdminAutocompleteState,
    debugTestAdminQuery,
    debugCanonical,
    hydrateReliabilityFromPayload,
    buildRollingReliabilityIndex,
    refreshPlayerReliabilityIndex,
    playerEventHistoryIndex: shared.playerEventHistoryIndex,
    rollingReliabilityIndex: shared.rollingReliabilityIndex,
    rollingReliabilityWindowSize: shared.rollingReliabilityWindowSize,
    reliabilityError: shared.reliabilityError,
    playerReliability: shared.playerReliability,
    getRollingReliability: shared.getRollingReliability,
    reliabilityEventResults: shared.reliabilityEventResults,
    reliabilityMeta: shared.reliabilityMeta,
    reliabilityStartDateParsed: shared.reliabilityStartDateParsed,
    latestPayload: shared.latestPayload,
    allKnownPlayersForAdmin: shared.allKnownPlayersForAdmin,
    adminPlayerNameByCanon: shared.adminPlayerNameByCanon,
    playerNameIndexForAdmin: shared.playerNameIndexForAdmin,
    aliasMap: shared.aliasMap,
    reliabilityStartDate: shared.reliabilityStartDate,
    REL_MIN_EVENTS_FOR_BUCKET: shared.REL_MIN_EVENTS_FOR_BUCKET,
    REL_NO_SHOW_GREEN_MAX: shared.REL_NO_SHOW_GREEN_MAX,
    REL_NO_SHOW_YELLOW_MAX: shared.REL_NO_SHOW_YELLOW_MAX,
    REL_LATE_CANCEL_GREEN_MAX: shared.REL_LATE_CANCEL_GREEN_MAX,
  });

  global.dsroShared = shared;
})(typeof window !== "undefined" ? window : globalThis);
