(function(global){
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

  global.dsroShared = {
    canonicalNameJS,
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
    buildAdminHeaders,
    initAdminLayout,
    extractDsEventDatesFromPayload,
    computeNextFriday,
    formatDsEventId,
    suggestDsEventIdForGroup,
  };
})(typeof window !== "undefined" ? window : globalThis);
