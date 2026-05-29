// auto-commit-monitor.test.mjs — run with `node --test hooks/auto-commit-monitor.test.mjs`
// (a bare `node --test hooks/` is treated as an entrypoint, not a dir, and fails).
//
// Exercises the behaviours called out in the W33 contract §5:
//   1. debounce collapses a burst of file events into ONE commit
//   2. allowlist excludes .env (.env never lands in a commit)
//   3. lock-retry-then-give-up (index.lock held → backoff → give up this cycle)
//   4. missing-repo-no-crash (a non-repo directory is skipped, not fatal)
//   5. Identity guard: .env present but not gitignored → refuse (no key leak)
//
// Uses real temp dirs + real `git init`. Node built-ins only.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const mon = require(path.join(here, "auto-commit-monitor.js"));

// ---- helpers ---------------------------------------------------------------

function mkTmp(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function git(repo, args) {
  return execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" });
}

function initRepo(repo) {
  git(repo, ["init", "-q"]);
  // Local identity so commits work even with no global git config.
  git(repo, ["config", "user.email", "test@example.com"]);
  git(repo, ["config", "user.name", "Test"]);
  // Hidden-surface allowlist: ignore everything, then unignore the known set.
  const allowlist = fs.readFileSync(
    path.join(here, "..", "data", "gitignore-hidden.txt"),
    "utf8"
  );
  fs.writeFileSync(path.join(repo, ".gitignore"), allowlist);
}

function commitCount(repo) {
  try {
    return Number(git(repo, ["rev-list", "--count", "HEAD"]).trim());
  } catch {
    return 0; // no commits yet
  }
}

function lastMessage(repo) {
  return git(repo, ["log", "-1", "--pretty=%s"]).trim();
}

function lastAuthor(repo) {
  return git(repo, ["log", "-1", "--pretty=%an <%ae>"]).trim();
}

function lsFiles(repo) {
  return git(repo, ["ls-files"]).split("\n").filter(Boolean);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- 1. debounce collapses a burst into one commit -------------------------

test("debounce collapses a burst of events into a single commit", async () => {
  const repo = mkTmp("bc-mon-debounce-");
  initRepo(repo);

  // Short debounce to keep the test fast.
  const committer = mon.makeDebouncedCommitter(repo, { debounceMs: 120 });

  // Write several allowlisted files and fire the trigger for each (simulating
  // a burst of fs.watch events arriving close together).
  for (let i = 0; i < 5; i++) {
    fs.writeFileSync(path.join(repo, "profile.json"), JSON.stringify({ i }));
    fs.appendFileSync(path.join(repo, "events.jsonl"), `{"n":${i}}\n`);
    committer();
  }

  assert.equal(commitCount(repo), 0, "no commit should fire before debounce elapses");

  await sleep(300); // let the single debounced fire complete

  assert.equal(commitCount(repo), 1, "the whole burst must collapse to ONE commit");
  assert.match(lastMessage(repo), /^auto: \d+ file\(s\) modified$/);
  assert.equal(lastAuthor(repo), "Be Civic <noreply@becivic.be>");

  committer.cancel();
});

// ---- 2. allowlist excludes .env --------------------------------------------

test("allowlist excludes .env from the commit", async () => {
  const repo = mkTmp("bc-mon-env-");
  initRepo(repo);

  // Secret + an allowlisted file land in the working tree together.
  fs.writeFileSync(path.join(repo, ".env"), "BECIVIC_HARNESS_KEY=supersecret\n");
  fs.writeFileSync(path.join(repo, "profile.json"), '{"ok":true}');

  const res = await mon.commitOnce(repo, mon.monitorMessage);
  assert.match(res, /^committed:\d+$/, `expected a commit, got ${res}`);

  const tracked = lsFiles(repo);
  assert.ok(tracked.includes("profile.json"), "profile.json should be committed");
  assert.ok(!tracked.includes(".env"), ".env must NEVER be committed");

  // Belt-and-braces: the explicit refusal guard rejects a .env path arg.
  assert.equal(mon.refusesEnvPaths(["add", "-A"]), true);
  assert.equal(mon.refusesEnvPaths(["add", path.join(repo, ".env")]), false);
});

// ---- 3. lock-retry-then-give-up --------------------------------------------

test("index.lock held → backs off then gives up this cycle (no commit, no crash)", async () => {
  const repo = mkTmp("bc-mon-lock-");
  initRepo(repo);
  fs.writeFileSync(path.join(repo, "profile.json"), '{"locked":true}');

  // Simulate another git process holding the index lock.
  fs.mkdirSync(path.join(repo, ".git"), { recursive: true });
  fs.writeFileSync(path.join(repo, ".git", "index.lock"), "");

  // Tiny backoffs so the test is fast; the point is "retries then gives up".
  process.env.BC_MONITOR_LOCK_BACKOFFS_MS = "5,5,5,5";
  // commitOnce reads the env at module-eval time for LOCK_BACKOFFS_MS, so we
  // re-require a fresh module instance to pick up the override.
  const freshRequire = createRequire(import.meta.url);
  delete freshRequire.cache[require.resolve(path.join(here, "auto-commit-monitor.js"))];
  const monFresh = freshRequire(path.join(here, "auto-commit-monitor.js"));

  const t0 = Date.now();
  const res = await monFresh.commitOnce(repo, monFresh.monitorMessage);
  const elapsed = Date.now() - t0;

  assert.equal(res, "locked", "should report giving up due to the held lock");
  assert.equal(commitCount(repo), 0, "must not commit while the lock is held");
  assert.ok(elapsed >= 15, `should have backed off across retries (elapsed=${elapsed}ms)`);

  delete process.env.BC_MONITOR_LOCK_BACKOFFS_MS;

  // After the lock clears, a subsequent cycle commits normally (next event
  // retries — contract §5).
  fs.rmSync(path.join(repo, ".git", "index.lock"));
  const res2 = await mon.commitOnce(repo, mon.monitorMessage);
  assert.match(res2, /^committed:\d+$/, `expected commit after lock cleared, got ${res2}`);
  assert.equal(commitCount(repo), 1);
});

// ---- 4. missing-repo-no-crash ----------------------------------------------

test("a non-repo directory is skipped, not fatal", async () => {
  const dir = mkTmp("bc-mon-norepo-");
  fs.writeFileSync(path.join(dir, "profile.json"), "{}");

  const res = await mon.commitOnce(dir, mon.monitorMessage);
  assert.equal(res, "skipped:not-a-repo", `expected skip, got ${res}`);
  // No throw == no crash. Reaching this line is the assertion.
});

// ---- 5. Identity guard: .env present but NOT gitignored → refuse -----------

test("refuses to commit when .env is present but not gitignored (Identity guard)", async () => {
  const repo = mkTmp("bc-mon-envguard-");
  // Init a repo WITHOUT writing the .gitignore allowlist — simulates an
  // onboarding interrupted after `git init` + key write but BEFORE the
  // allowlist landed. .env is therefore not ignored; `add -A` would leak it.
  git(repo, ["init", "-q"]);
  git(repo, ["config", "user.email", "test@example.com"]);
  git(repo, ["config", "user.name", "Test"]);
  fs.writeFileSync(path.join(repo, ".env"), "BECIVIC_HARNESS_KEY=supersecret\n");
  fs.writeFileSync(path.join(repo, "profile.json"), '{"ok":true}');

  const res = await mon.commitOnce(repo, mon.monitorMessage);
  assert.equal(res, "skipped:env-not-ignored", `must refuse to protect Identity, got ${res}`);
  assert.equal(commitCount(repo), 0, "must not commit at all while .env is exposed");
});

test("startMonitor on a hidden-only setup (absent marker) does not throw", () => {
  const hidden = mkTmp("bc-mon-hidden-");
  initRepo(hidden);
  // No .be-civic/marker → visible surface absent; must watch hidden only.
  const handle = mon.startMonitor({
    hiddenRoot: hidden,
    visibleRoot: mon.readVisibleMarker(hidden),
    debounceMs: 50,
  });
  assert.ok(handle.committers.hidden, "hidden surface should be watched");
  assert.equal(handle.committers.visible, undefined, "visible surface absent");
  handle.stop();
});

// ---- bonus: end-to-end fs.watch burst → one commit -------------------------

test("end-to-end: real fs.watch burst collapses to one commit", async () => {
  const hidden = mkTmp("bc-mon-e2e-");
  initRepo(hidden);

  const handle = mon.startMonitor({
    hiddenRoot: hidden,
    visibleRoot: null,
    debounceMs: 150,
  });

  // Rapid-fire writes; fs.watch should coalesce via the debounce.
  for (let i = 0; i < 8; i++) {
    fs.writeFileSync(path.join(hidden, "preferences.json"), JSON.stringify({ i }));
    await sleep(5);
  }

  // Wait out the debounce plus a margin for the commit to land.
  await sleep(500);
  handle.stop();

  const count = commitCount(hidden);
  assert.ok(count >= 1 && count <= 2, `burst should yield 1 (≤2) commit, got ${count}`);
  if (count >= 1) {
    assert.equal(lastAuthor(hidden), "Be Civic <noreply@becivic.be>");
  }
});
