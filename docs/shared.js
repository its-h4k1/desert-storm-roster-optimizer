(function(global){
  global.dsroShared = global.dsroShared || {};
  const shared = global.dsroShared;
  const ZERO_WIDTH_RE = /[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]/g;
  const HOMO_TRANSLATE = {
    "А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O",
    "Р":"P","С":"S","Т":"T","Х":"X","І":"I","Ј":"J","У":"Y",
    "а":"a","е":"e","о":"o","р":"p","с":"s","х":"x","у":"y",
    "к":"k","м":"m","т":"t","н":"h","і":"i","ј":"j","ѵ":"y",
  };

  function canonicalNameJS(value) {
    if (value == null) return "";
    let s = String(value);
    if (typeof s.normalize === "function") {
      s = s.normalize("NFKC");
    }
    s = s.replace(ZERO_WIDTH_RE, "");
    s = s.split("").map(ch => HOMO_TRANSLATE[ch] || ch).join("");
    s = s.toLowerCase();
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
    alertEl,
    onValid,
    renderStatus,
  } = {}) {
    let initialized = false;

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
    };

    const showFallback = () => {
      if (fallbackRow) fallbackRow.style.display = "block";
      if (alertEl) alertEl.style.display = "grid";
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

    return { refresh: check, applyFallback };
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

  const RELIABILITY_WARN_ONCE = { missing: false };

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

  function buildReliabilityMap(payload) {
    const result = {};
    if (!payload || typeof payload !== "object") return result;

    const candidateSources = [
      payload.analysis?.reliability?.players,
      payload.reliability?.players,
      payload.players,
      payload.player_reliability,
    ];

    let foundSource = null;
    for (const src of candidateSources) {
      if (src && (typeof src === "object" || Array.isArray(src))) {
        foundSource = src;
        break;
      }
    }

    if (!foundSource) {
      if (!RELIABILITY_WARN_ONCE.missing) {
        console.warn("Keine Reliability-Daten in latest.json gefunden – playerReliability bleibt leer.");
        RELIABILITY_WARN_ONCE.missing = true;
      }
      return result;
    }

    if (Array.isArray(foundSource)) {
      foundSource.forEach((entry) => {
        const name = entry?.display || entry?.name || entry?.canon || "";
        const stats = normalizeReliabilityEntry(entry);
        if (!name || !stats) return;
        result[String(name)] = stats;
      });
    } else {
      Object.entries(foundSource).forEach(([name, stats]) => {
        const normalized = normalizeReliabilityEntry(stats);
        if (!name || !normalized) return;
        result[String(name)] = normalized;
      });
    }

    return result;
  }

  function hydrateReliabilityFromPayload(payload) {
    shared.latestPayload = payload || null;
    shared.reliabilityStartDate = payload?.reliability_config?.reliability_start_date || null;
    shared.playerReliability = buildReliabilityMap(payload);
    return shared.playerReliability;
  }

  shared.playerReliability = shared.playerReliability || {};
  shared.latestPayload = shared.latestPayload || null;
  shared.aliasMap = shared.aliasMap || new Map();
  shared.reliabilityStartDate = shared.reliabilityStartDate || null;
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

  shared.computeReliabilityBucket = function (stats) {
    if (
      !stats
      || typeof stats.events !== "number"
      || stats.events < shared.REL_MIN_EVENTS_FOR_BUCKET
    ) {
      return {
        bucket: "neu",
        label: "neu",
        tooltip: "Noch zu wenig Daten seit reliability_start_date.",
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

  shared.prepareAliasMapFromPayload = function (payload) {
    const map = new Map();
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
    }
    shared.aliasMap = map;
    return map;
  };

  shared.buildAllKnownPlayersForAdmin = function (latestPayload) {
    const namesSet = new Set();

    const addName = (raw) => {
      const aliasKey = canonicalNameJS(raw || "");
      const canonical = aliasKey && shared.aliasMap ? shared.aliasMap.get(aliasKey) || aliasKey : aliasKey;
      const normalized = normalizePlayerName(canonical || raw || "");
      if (normalized) namesSet.add(normalized);
    };

    if (latestPayload && typeof latestPayload === "object") {
      if (latestPayload.reliability && latestPayload.reliability.players) {
        Object.keys(latestPayload.reliability.players).forEach(addName);
      }

      if (latestPayload.alliance && Array.isArray(latestPayload.alliance.players)) {
        latestPayload.alliance.players.forEach((p) => {
          const rawName = typeof p === "string" ? p : p?.name || p?.playerName || "";
          addName(rawName);
        });
      }

      if (Array.isArray(latestPayload.alliance_pool)) {
        latestPayload.alliance_pool.forEach((p) => {
          addName(p?.display || p?.canon || "");
        });
      }

      if (Array.isArray(latestPayload.players)) {
        latestPayload.players.forEach((p) => addName(p?.display || p?.canon || p?.name || ""));
      }

      if (latestPayload.signups && Array.isArray(latestPayload.signups)) {
        latestPayload.signups.forEach((s) => addName(s?.playerName || s?.name || ""));
      }

      if (Array.isArray(latestPayload?.signup_pool?.file_entries)) {
        latestPayload.signup_pool.file_entries.forEach((entry) => {
          addName(entry?.PlayerName || entry?.player || entry?.player_name || "");
        });
      }

      if (Array.isArray(latestPayload?.event_signups?.file_entries)) {
        latestPayload.event_signups.file_entries.forEach((entry) => {
          addName(entry?.player || entry?.PlayerName || "");
        });
      }
    }

    shared.allKnownPlayersForAdmin = Array.from(namesSet).sort((a, b) => a.localeCompare(b, "de", { sensitivity: "base" }));
    return shared.allKnownPlayersForAdmin;
  };

  shared.buildPlayerAutocompleteIndexForAdmin = function () {
    const names = shared.allKnownPlayersForAdmin || [];
    const index = names.map((name) => ({ name, lc: name.toLowerCase() }));
    shared.playerNameIndexForAdmin = index;
    return index;
  };

  shared.queryPlayerNamesForAdmin = function (query, maxResults) {
    const index = shared.playerNameIndexForAdmin || [];
    const term = (query || "").trim();
    if (!term) return [];
    const lcTerm = term.toLowerCase();
    const limit = Number(maxResults) || 0;
    const results = [];
    for (const entry of index) {
      if (entry.lc.includes(lcTerm)) {
        results.push(entry.name);
        if (limit && results.length >= limit) break;
      }
    }
    return results;
  };

  // Helper für Admin-Seiten: baut Alias-Map, Spielerlisten und den Autocomplete-Index
  // auf Basis eines Payload-Snapshots plus optionaler zusätzlicher Namensquellen.
  // Gibt die finale Namensliste zurück.
  shared.refreshAdminPlayerIndex = function ({ payload, additionalNames = [] } = {}) {
    const sourcePayload = payload || shared.latestPayload || null;
    if (shared.prepareAliasMapFromPayload) {
      shared.prepareAliasMapFromPayload(sourcePayload);
    }
    const baseNames = shared.buildAllKnownPlayersForAdmin
      ? shared.buildAllKnownPlayersForAdmin(sourcePayload)
      : [];
    const set = new Set(baseNames || []);
    const addExtra = (raw) => {
      const normalized = normalizePlayerName(raw || "");
      if (normalized) set.add(normalized);
    };
    (additionalNames || []).forEach(addExtra);
    shared.allKnownPlayersForAdmin = Array.from(set).sort((a, b) => a.localeCompare(b, "de", { sensitivity: "base" }));
    if (shared.buildPlayerAutocompleteIndexForAdmin) {
      shared.buildPlayerAutocompleteIndexForAdmin();
    }
    return shared.allKnownPlayersForAdmin;
  };

  shared.debugPrintAdminAutocompleteState = function () {
    console.log("[dsroShared] allKnownPlayersForAdmin:", shared.allKnownPlayersForAdmin);
    console.log(
      "[dsroShared] playerNameIndexForAdmin size:",
      shared.playerNameIndexForAdmin ? shared.playerNameIndexForAdmin.length : 0,
    );
  };

  shared.debugTestAdminQuery = function (term) {
    console.log("[dsroShared] admin testQuery:", term, "=>", shared.queryPlayerNamesForAdmin(term, 10));
  };

  Object.assign(shared, {
    canonicalNameJS,
    normalizePlayerName,
    escapeHtml,
    computeSiteRoot,
    buildLatestJsonUrl,
    fetchJsonWithErrors,
    triggerRosterBuild,
    RosterBuildTriggerError,
    DEFAULT_WORKER_BASE,
    DEFAULT_DISPATCH_URL,
    readSharedAdminSettings,
    writeSharedAdminSettings,
    getAdminKey,
    saveAdminKey,
    applyAdminKeyInput,
    initAdminKeyGate,
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
    hydrateReliabilityFromPayload,
    playerReliability: shared.playerReliability,
    latestPayload: shared.latestPayload,
    allKnownPlayersForAdmin: shared.allKnownPlayersForAdmin,
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
