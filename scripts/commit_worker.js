const DEFAULT_REPO = "its-h4k1/desert-storm-roster-optimizer";
const ATTENDANCE_PATH = "data/attendance_config.yml";
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

function normalizeAttendance(raw = {}) {
  const defaults = {
    min_start_A: 0.55,
    min_start_B: 0.55,
    min_bench_A: 0.45,
    min_bench_B: 0.45,
    target_expected_A: { low: 24.0, high: 28.0 },
    target_expected_B: { low: 24.0, high: 28.0 },
    hard_commit_floor: 0.92,
    no_response_multiplier: 0.65,
    high_reliability_balance_ratio: 1.8,
  };

  const clamp = (num, min, max) => Math.min(Math.max(num, min), max);
  const number = (val, def) => {
    const parsed = typeof val === "string" ? parseFloat(val) : Number(val);
    return Number.isFinite(parsed) ? parsed : def;
  };

  const cfg = { ...defaults, ...(raw || {}) };
  return {
    min_start_A: clamp(number(cfg.min_start_A, defaults.min_start_A), 0, 1),
    min_start_B: clamp(number(cfg.min_start_B, defaults.min_start_B), 0, 1),
    min_bench_A: clamp(number(cfg.min_bench_A, defaults.min_bench_A), 0, 1),
    min_bench_B: clamp(number(cfg.min_bench_B, defaults.min_bench_B), 0, 1),
    target_expected_A: {
      low: clamp(number(cfg.target_expected_A?.low, defaults.target_expected_A.low), 0, 80),
      high: clamp(number(cfg.target_expected_A?.high, defaults.target_expected_A.high), 0, 80),
    },
    target_expected_B: {
      low: clamp(number(cfg.target_expected_B?.low, defaults.target_expected_B.low), 0, 80),
      high: clamp(number(cfg.target_expected_B?.high, defaults.target_expected_B.high), 0, 80),
    },
    hard_commit_floor: clamp(number(cfg.hard_commit_floor, defaults.hard_commit_floor), 0, 1),
    no_response_multiplier: clamp(number(cfg.no_response_multiplier, defaults.no_response_multiplier), 0, 1),
    high_reliability_balance_ratio: clamp(
      number(cfg.high_reliability_balance_ratio, defaults.high_reliability_balance_ratio),
      0.25,
      4,
    ),
  };
}

function renderAttendanceYaml(attendance, existingText = "") {
  const headerLines = [];
  for (const line of existingText.split(/\r?\n/)) {
    if (!line.trim() || line.trim().startsWith("#")) {
      headerLines.push(line);
      continue;
    }
    break;
  }

  const lines = [
    ...headerLines,
    "attendance:",
    `  min_start_A: ${attendance.min_start_A.toFixed(2)}`,
    `  min_start_B: ${attendance.min_start_B.toFixed(2)}`,
    "",
    `  min_bench_A: ${attendance.min_bench_A.toFixed(2)}`,
    `  min_bench_B: ${attendance.min_bench_B.toFixed(2)}`,
    "",
    "  target_expected_A:",
    `    low: ${attendance.target_expected_A.low.toFixed(1)}`,
    `    high: ${attendance.target_expected_A.high.toFixed(1)}`,
    "  target_expected_B:",
    `    low: ${attendance.target_expected_B.low.toFixed(1)}`,
    `    high: ${attendance.target_expected_B.high.toFixed(1)}`,
    "",
    `  hard_commit_floor: ${attendance.hard_commit_floor.toFixed(2)}`,
    "",
    `  no_response_multiplier: ${attendance.no_response_multiplier.toFixed(2)}`,
    "",
    `  high_reliability_balance_ratio: ${attendance.high_reliability_balance_ratio.toFixed(2)}`,
    "",
  ];
  return lines.join("\n");
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

async function writeAttendanceFile(env, { content, branch, message }) {
  const currentRes = await githubRequest(env, `contents/${ATTENDANCE_PATH}?ref=${encodeURIComponent(branch)}`);
  let sha = undefined;
  let existingText = "";
  if (currentRes.ok) {
    const current = await currentRes.json();
    sha = current.sha;
    if (current.content) {
      try {
        existingText = atob(current.content.replace(/\n/g, ""));
      } catch (err) {
        existingText = "";
      }
    }
  }
  const yaml = renderAttendanceYaml(content, existingText);
  const payload = {
    message,
    content: btoa(unescape(encodeURIComponent(yaml))),
    branch,
  };
  if (sha) payload.sha = sha;

  const res = await githubRequest(env, `contents/${ATTENDANCE_PATH}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub write failed: ${res.status} ${text}`);
  }
  return res.json();
}

async function handleWriteFile(request, env) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  if (request.headers.has("X-Admin-Key") && env.ADMIN_KEY) {
    const provided = request.headers.get("X-Admin-Key");
    if (provided !== env.ADMIN_KEY) {
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

async function dispatchRosterBuild(env, ref, reason) {
  const body = JSON.stringify({ ref, inputs: { reason } });
  const res = await githubRequest(env, "actions/workflows/roster.yml/dispatches", {
    method: "POST",
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`workflow_dispatch failed: ${res.status} ${text}`);
  }
  return { status: res.status, ok: true };
}

async function handleAttendanceConfig(request, env) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  if (request.headers.has("X-Admin-Key") && env.ADMIN_KEY) {
    const provided = request.headers.get("X-Admin-Key");
    if (provided !== env.ADMIN_KEY) {
      return jsonResponse({ error: "unauthorized" }, 401);
    }
  }

  let payload = {};
  try {
    payload = await request.json();
  } catch (err) {
    return jsonResponse({ error: "invalid json" }, 400);
  }

  const ref = (payload.ref || "main").trim() || "main";
  const attendance = normalizeAttendance(payload.attendance || {});
  const reason = (payload.reason || "attendance config update").trim();
  const message = reason ? `chore: attendance config · ${reason}` : "chore: attendance config";

  const commit = await writeAttendanceFile(env, { content: attendance, branch: ref, message });
  let dispatch = null;
  try {
    dispatch = await dispatchRosterBuild(env, ref, reason || "attendance config update");
  } catch (err) {
    dispatch = { error: err?.message || String(err) };
  }

  return jsonResponse({ commit, dispatch, attendance });
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

    if (url.pathname.endsWith("/attendance-config") || url.pathname === "/attendance-config") {
      try {
        return await handleAttendanceConfig(request, env);
      } catch (err) {
        return jsonResponse({ error: err?.message || String(err) }, 500);
      }
    }

    return jsonResponse({ status: "ok", hint: "use /write-file or /attendance-config" });
  },
};
