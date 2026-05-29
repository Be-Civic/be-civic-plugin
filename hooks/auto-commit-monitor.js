#!/usr/bin/env node
/**
 * auto-commit-monitor.js — Be Civic substrate auto-commit monitor (W33 §5).
 *
 * Registered as a plugin *monitor* (`experimental.monitors`, `when:"always"`)
 * in .claude-plugin/plugin.json, so Claude Code runs it as a persistent
 * background process for the lifetime of the session. Every line this script
 * prints to stdout is delivered to Claude as a notification.
 *
 * Behaviour (contract §5):
 *   - Two watch roots:
 *       hidden  = ${CLAUDE_PLUGIN_DATA}                       (always present)
 *       visible = path read from ${CLAUDE_PLUGIN_DATA}/.be-civic/marker
 *                 (written by onboarding; if absent, watch hidden only and
 *                  re-resolve the marker on the next change / next session).
 *   - Watch each root recursively with the Node built-in fs.watch (NOT
 *     chokidar — the workstation forbids `npm install`, and vendoring chokidar
 *     fails the marketplace size check). The watcher is isolated behind
 *     `watchTree()` so it can be swapped without touching the commit logic.
 *   - Debounce 1500ms per repo: a burst of file events collapses into one
 *     commit.
 *   - On fire: `git -C <root> add -A` (the repo's own .gitignore allowlist
 *     governs what is staged; .env is never in the allowlist), then commit as
 *     author "Be Civic <noreply@becivic.be>" with message
 *     "auto: <N> file(s) modified". Skip if nothing is staged.
 *   - git index.lock contention: exponential backoff 250→500→1000→2000ms,
 *     then give up this cycle (the next event retries).
 *   - Corrupt repo / missing git binary / not-a-repo: one line to stderr,
 *     continue — never crash.
 *   - Defensive: never explicitly `git add` .env (we only ever run `add -A`,
 *     which respects .gitignore; we additionally hard-refuse any path arg that
 *     resolves to a .env file).
 *
 * Pure Node built-ins only (no third-party deps).
 */

"use strict";

const fs = require("fs");
const path = require("path");
const { execFile } = require("child_process");

// ----------------------------------------------------------------------------
// Configuration (overridable via env for tests).
// ----------------------------------------------------------------------------

const DEBOUNCE_MS = numEnv("BC_MONITOR_DEBOUNCE_MS", 1500);
const LOCK_BACKOFFS_MS = parseBackoffs(
  process.env.BC_MONITOR_LOCK_BACKOFFS_MS,
  [250, 500, 1000, 2000]
);
const GIT_BIN = process.env.BC_MONITOR_GIT_BIN || "git";
const COMMIT_AUTHOR_NAME = "Be Civic";
const COMMIT_AUTHOR_EMAIL = "noreply@becivic.be";
// Re-resolve the visible marker on this cadence when it was absent at start.
const MARKER_REPOLL_MS = numEnv("BC_MONITOR_MARKER_REPOLL_MS", 5000);

function numEnv(name, fallback) {
  const v = process.env[name];
  if (v === undefined || v === "") return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function parseBackoffs(raw, fallback) {
  if (!raw) return fallback;
  const parts = raw
    .split(",")
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n));
  return parts.length ? parts : fallback;
}

// ----------------------------------------------------------------------------
// Small logging helpers. stdout lines become Claude notifications; stderr is
// for operator diagnostics only.
// ----------------------------------------------------------------------------

function logInfo(msg) {
  process.stdout.write(`[be-civic monitor] ${msg}\n`);
}

function logErr(msg) {
  process.stderr.write(`[be-civic monitor] ${msg}\n`);
}

// ----------------------------------------------------------------------------
// git plumbing.
// ----------------------------------------------------------------------------

function git(repoRoot, args) {
  return new Promise((resolve) => {
    execFile(
      GIT_BIN,
      ["-C", repoRoot, ...args],
      { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) => {
        resolve({
          code: error && typeof error.code === "number" ? error.code : error ? 1 : 0,
          // execFile sets error for ENOENT (git binary missing) too.
          spawnError: error && error.code === "ENOENT" ? error : null,
          stdout: stdout || "",
          stderr: stderr || "",
        });
      }
    );
  });
}

async function isGitRepo(repoRoot) {
  const res = await git(repoRoot, ["rev-parse", "--is-inside-work-tree"]);
  if (res.spawnError) throw res.spawnError; // git binary missing — surface up.
  return res.code === 0 && res.stdout.trim() === "true";
}

function indexLockPath(repoRoot) {
  return path.join(repoRoot, ".git", "index.lock");
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Count staged entries (added/modified/deleted) after `add -A`. We parse
 * `git status --porcelain` and count lines whose index (first) column is not a
 * space and not "?" — i.e. actually staged. Returns the integer count.
 */
function countStaged(porcelain) {
  if (!porcelain) return 0;
  let n = 0;
  for (const line of porcelain.split("\n")) {
    if (!line) continue;
    const indexStatus = line[0];
    if (indexStatus !== " " && indexStatus !== "?") n += 1;
  }
  return n;
}

/**
 * Hard guard: refuse to ever pass a path that resolves to a `.env` file to
 * `git add`. We only ever call `add -A` (no explicit paths), so this is purely
 * defensive belt-and-braces against future edits.
 */
function refusesEnvPaths(args) {
  for (const a of args) {
    if (a === "-A" || a.startsWith("-")) continue;
    const base = path.basename(a);
    if (base === ".env") return false;
  }
  return true;
}

async function safeAddAll(repoRoot) {
  const args = ["add", "-A"];
  if (!refusesEnvPaths(args)) {
    throw new Error("refusing to stage a .env path");
  }
  return git(repoRoot, args);
}

/**
 * Commit any allowlisted working-tree changes in `repoRoot` exactly once.
 * Returns one of: "committed:<N>", "nothing", "locked", "skipped:<reason>".
 *
 * @param {string} repoRoot
 * @param {(n:number)=>string} messageFor  builds the commit message from the
 *        staged-file count (lets the recovery sweep reuse this with a
 *        different message).
 */
async function commitOnce(repoRoot, messageFor) {
  // not-a-repo / missing git binary → caller-visible reason, never throws past
  // here for the repo case; binary-missing is surfaced as a spawnError.
  let inside;
  try {
    inside = await isGitRepo(repoRoot);
  } catch (e) {
    if (e && e.code === "ENOENT") {
      logErr(`git binary not found (${GIT_BIN}); skipping ${repoRoot}`);
      return "skipped:no-git-binary";
    }
    logErr(`unexpected error probing ${repoRoot}: ${e && e.message}`);
    return "skipped:probe-error";
  }
  if (!inside) {
    logErr(`not a git repository, skipping: ${repoRoot}`);
    return "skipped:not-a-repo";
  }

  // Identity guard (contract §5 / 40-substrate §6.1): `add -A` relies on the
  // .gitignore allowlist to exclude the Identity slot. If `.env` exists but is
  // NOT gitignored (e.g. the allowlist was not written yet), committing would
  // leak the harness key. Refuse this cycle. `check-ignore -q` exits 0 iff
  // `.env` is ignored; any non-zero (not-ignored OR error) → refuse (fail-safe).
  if (fs.existsSync(path.join(repoRoot, ".env"))) {
    const chk = await git(repoRoot, ["check-ignore", "-q", ".env"]);
    if (chk.spawnError || chk.code !== 0) {
      logErr(`.env present but not gitignored in ${repoRoot}; refusing commit to protect Identity (40 §6.1)`);
      return "skipped:env-not-ignored";
    }
  }

  // Lock-aware: if the index is locked, back off then give up this cycle.
  for (let attempt = 0; ; attempt += 1) {
    if (!fs.existsSync(indexLockPath(repoRoot))) break;
    if (attempt >= LOCK_BACKOFFS_MS.length) {
      logErr(`index.lock held after ${LOCK_BACKOFFS_MS.length} retries; giving up this cycle: ${repoRoot}`);
      return "locked";
    }
    await sleep(LOCK_BACKOFFS_MS[attempt]);
  }

  const add = await safeAddAll(repoRoot);
  if (add.spawnError) {
    logErr(`git binary not found (${GIT_BIN}); skipping ${repoRoot}`);
    return "skipped:no-git-binary";
  }
  if (add.code !== 0) {
    logErr(`git add -A failed in ${repoRoot}: ${add.stderr.trim()}`);
    return "skipped:add-failed";
  }

  const status = await git(repoRoot, ["status", "--porcelain"]);
  if (status.code !== 0) {
    logErr(`git status failed in ${repoRoot}: ${status.stderr.trim()}`);
    return "skipped:status-failed";
  }
  const staged = countStaged(status.stdout);
  if (staged === 0) return "nothing";

  const commit = await git(repoRoot, [
    "-c",
    `user.name=${COMMIT_AUTHOR_NAME}`,
    "-c",
    `user.email=${COMMIT_AUTHOR_EMAIL}`,
    "commit",
    "--author",
    `${COMMIT_AUTHOR_NAME} <${COMMIT_AUTHOR_EMAIL}>`,
    "-m",
    messageFor(staged),
  ]);
  if (commit.code !== 0) {
    // Could be a race (lock re-appeared) or empty after all; log + move on.
    logErr(`git commit failed in ${repoRoot}: ${commit.stderr.trim() || commit.stdout.trim()}`);
    return "skipped:commit-failed";
  }
  return `committed:${staged}`;
}

const monitorMessage = (n) => `auto: ${n} file(s) modified`;
const recoveryMessage = (n) =>
  `auto: recovery — ${n} file(s) modified outside monitor coverage`;

// ----------------------------------------------------------------------------
// Watcher abstraction (swappable). Built-in fs.watch recursive.
// ----------------------------------------------------------------------------

/**
 * Watch `root` recursively, invoking `onChange()` (debounced upstream) on any
 * filesystem event. Returns a `{ close() }` handle. Isolated here so the
 * underlying watcher can be swapped (e.g. for a polling fallback on platforms
 * without recursive fs.watch) without touching commit logic.
 */
function watchTree(root, onChange) {
  let watcher;
  try {
    watcher = fs.watch(root, { recursive: true, persistent: true }, () => {
      onChange();
    });
    watcher.on("error", (err) => {
      logErr(`watch error on ${root}: ${err && err.message}`);
    });
  } catch (err) {
    logErr(`failed to watch ${root}: ${err && err.message}`);
    return { close() {} };
  }
  return {
    close() {
      try {
        watcher.close();
      } catch (_) {
        /* ignore */
      }
    },
  };
}

// ----------------------------------------------------------------------------
// Per-repo debounced committer.
// ----------------------------------------------------------------------------

/**
 * Build a debounced commit trigger for one repo. The returned function can be
 * called on every fs event; commits coalesce into one call per DEBOUNCE_MS.
 * Serialises commits so a long commit can't overlap the next debounce fire.
 */
function makeDebouncedCommitter(repoRoot, { debounceMs = DEBOUNCE_MS } = {}) {
  let timer = null;
  let running = false;
  let pendingWhileRunning = false;

  async function fire() {
    timer = null;
    if (running) {
      // A commit is in flight; remember to re-run once it finishes.
      pendingWhileRunning = true;
      return;
    }
    running = true;
    try {
      const result = await commitOnce(repoRoot, monitorMessage);
      if (result.startsWith("committed:")) {
        const n = result.split(":")[1];
        logInfo(`committed ${n} file(s) in ${repoRoot}`);
      }
    } catch (e) {
      // commitOnce is defensive, but never let an exception kill the process.
      logErr(`commit cycle error in ${repoRoot}: ${e && e.message}`);
    } finally {
      running = false;
      if (pendingWhileRunning) {
        pendingWhileRunning = false;
        schedule();
      }
    }
  }

  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(fire, debounceMs);
  }

  // Expose for tests / shutdown.
  schedule.flushNow = fire;
  schedule.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return schedule;
}

// ----------------------------------------------------------------------------
// Marker resolution: find the visible surface path.
// ----------------------------------------------------------------------------

function readVisibleMarker(hiddenRoot) {
  const markerPath = path.join(hiddenRoot, ".be-civic", "marker");
  let raw;
  try {
    raw = fs.readFileSync(markerPath, "utf8");
  } catch (_) {
    return null; // absent → watch hidden only.
  }
  const visiblePath = raw.trim();
  if (!visiblePath) return null;
  try {
    if (!fs.statSync(visiblePath).isDirectory()) return null;
  } catch (_) {
    return null; // marker points somewhere that doesn't exist (yet).
  }
  return visiblePath;
}

// ----------------------------------------------------------------------------
// Orchestration.
// ----------------------------------------------------------------------------

/**
 * Start watching the given roots. Exposed (not just under main) so the test
 * harness can drive it against temp dirs. Returns a handle with `.stop()` and
 * the internal committers for inspection.
 */
function startMonitor({ hiddenRoot, visibleRoot, debounceMs = DEBOUNCE_MS }) {
  const watchers = [];
  const committers = {};

  function attach(root, label) {
    if (!root) return;
    try {
      if (!fs.statSync(root).isDirectory()) return;
    } catch (_) {
      logErr(`${label} root does not exist, skipping watch: ${root}`);
      return;
    }
    const committer = makeDebouncedCommitter(root, { debounceMs });
    committers[label] = committer;
    watchers.push(watchTree(root, committer));
    logInfo(`watching ${label} surface: ${root}`);
  }

  attach(hiddenRoot, "hidden");
  attach(visibleRoot, "visible");

  // If the visible marker was absent, poll for it and attach late.
  let repoll = null;
  if (hiddenRoot && !visibleRoot) {
    repoll = setInterval(() => {
      const v = readVisibleMarker(hiddenRoot);
      if (v && !committers.visible) {
        attach(v, "visible");
      }
    }, MARKER_REPOLL_MS);
    if (repoll.unref) repoll.unref();
  }

  return {
    committers,
    stop() {
      if (repoll) clearInterval(repoll);
      for (const w of watchers) w.close();
      for (const c of Object.values(committers)) c.cancel();
    },
  };
}

function resolveRootsFromEnv() {
  const hiddenRoot = process.env.CLAUDE_PLUGIN_DATA || null;
  if (!hiddenRoot) {
    logErr("CLAUDE_PLUGIN_DATA is not set; nothing to watch. Exiting cleanly.");
    return null;
  }
  const visibleRoot = readVisibleMarker(hiddenRoot);
  return { hiddenRoot, visibleRoot };
}

function main() {
  const roots = resolveRootsFromEnv();
  if (!roots) {
    // No hidden root → nothing to do. Exit 0 so the monitor framework doesn't
    // treat this as a crash-loop.
    return;
  }
  startMonitor(roots);
  // Keep the event loop alive for the session lifetime. fs.watch already holds
  // it open while watching, but if both roots failed to attach we still want
  // to stay up (e.g. to re-poll for a late marker), so add a parked timer.
  const keepAlive = setInterval(() => {}, 1 << 30);
  if (keepAlive.unref) keepAlive.ref(); // explicit: do NOT unref — stay alive.

  const shutdown = () => process.exit(0);
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  // Last-resort guard: never crash the monitor on an unexpected throw.
  process.on("uncaughtException", (err) => {
    logErr(`uncaught exception (continuing): ${err && err.stack ? err.stack : err}`);
  });
  process.on("unhandledRejection", (reason) => {
    logErr(`unhandled rejection (continuing): ${reason}`);
  });
}

// Export the testable surface; only run main() when executed directly.
module.exports = {
  startMonitor,
  commitOnce,
  makeDebouncedCommitter,
  readVisibleMarker,
  countStaged,
  refusesEnvPaths,
  monitorMessage,
  recoveryMessage,
  COMMIT_AUTHOR_NAME,
  COMMIT_AUTHOR_EMAIL,
};

if (require.main === module) {
  main();
}
