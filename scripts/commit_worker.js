const DEFAULT_REPO = "its-h4k1/desert-storm-roster-optimizer";
const PATH_ALLOWLIST = ["data/", "docs/data/event_results/"];

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function isPathAllowed(path = "") {
  if (typeof path !== "string") return false;
  if (path.includes("..") || path.startsWith("/")) return false;
  return PATH_ALLOWLIST.some((prefix) => path.startsWith(prefix));
}

function validateWritePayload(file) {
  if (!file || typeof file !== "object") {
    return { ok: false, error: "payload missing" };
  }
  const path = (file.path || "").trim();
  if (!path) return { ok: false, error: "path missing" };
  if (!isPathAllowed(path)) return { ok: false, error: "path not allowed" };
  if (typeof file.content !== "string") return { ok: false, error: "content missing" };
  const branch = (file.branch || "main").trim() || "main";
  const message = (file.message || `admin: update ${path}`).trim();
  return { ok: true, path, branch, message, content: file.content };
}

async function githubRequest(env, path, init = {}) {
  const repo = env.REPO || DEFAULT_REPO;
  const token = env.GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN missing");
  const apiUrl = new URL(`https://api.github.com/repos/${repo}/${path}`);
  const headers = new Headers(init.headers || {});
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("User-Agent", "dsro-worker");
  headers.set("Accept", "application/vnd.github+json");
  return fetch(apiUrl.toString(), { ...init, headers });
}

async function readCurrentFileSha(env, path, branch) {
  const currentRes = await githubRequest(env, `contents/${path}?ref=${encodeURIComponent(branch)}`);
  if (!currentRes.ok) return null;
  try {
    const current = await currentRes.json();
    return current?.sha || null;
  } catch (err) {
    return null;
  }
}

async function writeRepoFile(env, { path, content, branch, message }) {
  const sha = await readCurrentFileSha(env, path, branch);
  const payload = {
    message,
    content: btoa(unescape(encodeURIComponent(content))),
    branch,
  };
  if (sha) payload.sha = sha;

  const res = await githubRequest(env, `contents/${path}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub write failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function writeFiles(env, { files, message, branch }) {
  const results = [];
  for (const file of files) {
    const normalized = validateWritePayload({
      ...file,
      branch: file.branch || branch,
      message: file.message || message,
    });
    if (!normalized.ok) {
      throw new Error(normalized.error || "invalid payload");
    }
    const commit = await writeRepoFile(env, normalized);
    results.push({ path: normalized.path, commit });
  }
  return results;
}

async function handleWriteFile(request, env) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  if (env.ADMIN_KEY) {
    const provided = request.headers.get("X-Admin-Key");
    if (!provided || provided !== env.ADMIN_KEY) {
      return jsonResponse({ error: "unauthorized" }, 401);
    }
  }

  let payload = {};
  try {
    payload = await request.json();
  } catch (err) {
    return jsonResponse({ error: "invalid json" }, 400);
  }

  const files = Array.isArray(payload.files)
    ? payload.files
    : payload && typeof payload === "object"
      ? [payload]
      : [];
  if (!files.length) {
    return jsonResponse({ error: "no files provided" }, 400);
  }

  try {
    const results = await writeFiles(env, { files, message: payload.message, branch: payload.branch });
    return jsonResponse({ ok: true, files: results });
  } catch (err) {
    return jsonResponse({ ok: false, error: err?.message || String(err) }, 400);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
      });
    }

    if (url.pathname.endsWith("/write-file") || url.pathname === "/write-file") {
      try {
        return await handleWriteFile(request, env);
      } catch (err) {
        return jsonResponse({ error: err?.message || String(err) }, 500);
      }
    }

    return jsonResponse({ status: "ok", hint: "use /write-file" });
  },
};
