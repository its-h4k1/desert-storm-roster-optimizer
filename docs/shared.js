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

  global.dsroShared = {
    canonicalNameJS,
    escapeHtml,
    computeSiteRoot,
    buildLatestJsonUrl,
  };
})(typeof window !== "undefined" ? window : globalThis);
