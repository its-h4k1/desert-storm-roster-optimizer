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

  global.dsroShared = {
    canonicalNameJS,
    escapeHtml,
    computeSiteRoot,
    buildLatestJsonUrl,
    triggerRosterBuild,
    RosterBuildTriggerError,
    DEFAULT_WORKER_BASE,
    DEFAULT_DISPATCH_URL,
  };
})(typeof window !== "undefined" ? window : globalThis);
