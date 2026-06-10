#!/usr/bin/env python3
"""wire.py — Be Civic write transport (POST / GET / DELETE over HTTPS).

WHY THIS SCRIPT EXISTS
----------------------
The Be Civic REST API at `becivic.be/api/*` has GET reads (manifest, process
bodies, paths) AND state-changing writes (auth start/verify/rotate/delete,
submissions, submission cancel). Reads go over the agent's `WebFetch` tool —
but `WebFetch` is **GET-only**: it cannot carry a request body, so it cannot
do a single one of the writes. The writes are correctly POST/DELETE (they are
state-changing, and a GET variant would leak the email/code/key into URLs and
proxy logs). So the agent needs a real HTTP client for writes, and that client
is this script, invoked via `bash`.

This is the documented Anthropic "Provide utility scripts" pattern: a bundled,
deterministic helper is more reliable than asking the model to assemble curl
flags each time, saves tokens, and keeps key-handling in exactly one place.

TRANSPORT / SANDBOX DEPENDENCY (read this)
------------------------------------------
On Cowork, agent `bash` egress is gated by an Anthropic-MANAGED domain
allowlist (sandbox proxy at localhost:3128, `allowManagedDomainsOnly:true`).
`becivic.be` IS on that managed list today, so this script reaches the API.
We do NOT control that list — a project cannot self-allowlist a domain on
Cowork (bug anthropics/claude-code#37970: project `allowedDomains` is silently
ignored there). If Anthropic ever drops `becivic.be` from the managed list,
every write here fails with the sandbox's 403 `blocked-by-allowlist`. This
script detects that case and prints a clear, actionable message rather than a
raw traceback. See bc-operations/docs/agent-ux/cowork-sandbox-network-model.md.

CLI
---
    python3 wire.py <METHOD> <path> [--json '<body>'] [--stdin]
                    [--cancel-token <tok>] [--base <url>] [--inspect]

  <METHOD>   POST | GET | DELETE  (case-insensitive)
  <path>     API path beginning with '/', e.g. /api/auth/verify  (a full
             https://... URL is also accepted and used verbatim)

  Body (POST only; GET/DELETE take no body):
    --json '<json string>'   request body as an inline JSON string, OR
    --stdin                  read the request body (raw JSON) from stdin.
                             Prefer --stdin for anything secret-adjacent
                             (the code, etc. are not in the process table).

  --cancel-token <tok>   sets the `X-Cancel-Token: <tok>` header (DELETE
                         /api/submissions/<type>/<id> needs it alongside the
                         Bearer).
  --base <url>           override the base URL (default https://becivic.be;
                         also overridable via the BECIVIC_BASE_URL env var,
                         for the dev track).
  --inspect              report how auth/state resolved (presence-only; never
                         the key) and exit 0 WITHOUT sending the request.

AUTH
----
The Bearer is read from `${SUBSTRATE_STATE}/.env` (the `BECIVIC_HARNESS_KEY=`
line) and sent as `Authorization: Bearer <key>` WHEN PRESENT. SUBSTRATE_STATE
is taken from the `BC_SUBSTRATE_STATE` env var (the preamble's resolved
`.be-civic/state` child) or `SUBSTRATE_STATE`; when neither is PRESENT in the
environment, the script resolves it itself by the same marker-gated
ancestor-walk `preamble.py` uses (walk up from cwd looking for
`.be-civic/marker`, cap 12 levels) — so a bare keyed read works from anywhere
inside a project with no env handoff. Setting either var to the EMPTY string
forces anonymous (the explicit opt-out — the walk is skipped; pre-onboarding
flows that must not present a Bearer can use it). Use `--inspect` to see how
resolution happened (presence-only; no request is sent). Anonymous-tier calls
(`/api/auth/start-verification`, `/api/auth/verify`) work fine with no key —
the header is simply omitted when no key is found. The key value is NEVER
printed, logged, or echoed; only its presence is reported (`auth: bearer`
vs `auth: anonymous`).

OUTPUT
------
A small block of `key: value` lines the calling agent can act on. The API uses
two body envelopes and this script normalises both:
  - success submissions: `{ "status": <code>, "data": {...} }`
  - auth endpoints (UNWRAPPED): `{ verification_id, ... }` / `{ user_id, ... }`
  - errors (all routes): `{ "error": "<category>", ...extras }`  (NB: the error
    body has NO `status` field — the HTTP status is the Response status.)
So the body shape is not predictable from the route; this script keys off the
HTTP status and prints whichever of data/error/raw-body is present:

    http_status: 202
    result: ok            # ok for 2xx, error for non-2xx, blocked / network for transport
    data: {...}           # present iff the body had a `data` object
    error: <category>     # present iff the body had an `error` field
    body: {...}           # the parsed body (or raw text if not JSON)

With `--inspect` the block is instead (no request is sent):

    state_source: env | ancestor-walk | none
    state_dir: <path or 'absent'>
    auth: bearer | anonymous
    result: inspect

EXIT CODES
----------
  0   HTTP 2xx (the write/read landed); also: --inspect completed
  1   HTTP non-2xx (4xx/5xx — the API rejected it; see `error:` / `body:`)
  2   usage error (bad args)
  3   transport failure (network unreachable after one retry, or DNS, etc.)
  4   blocked-by-allowlist (becivic.be not reachable in this sandbox)

Runtime: Python 3 stdlib only (urllib). No third-party dependencies. Matches
the house style of the other scripts in this dir (preamble.py, gen_submission_id.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://becivic.be"
NETWORK_TIMEOUT = 30.0  # seconds — generous; auth emails can be slow server-side.
KEY_NAME = "BECIVIC_HARNESS_KEY"
METHODS = ("GET", "POST", "DELETE")

# An explicit, honest User-Agent. urllib's default UA (`Python-urllib/3.x`) is
# WAF-fingerprinted as a generic bot and gets banned at the Cloudflare edge
# with `Error 1010: browser_signature_banned` (a 403 that is NOT the sandbox
# allowlist block — it is the site's own WAF). Identifying as the Be Civic
# plugin client keeps the write path from being mistaken for scraping traffic.
USER_AGENT = "be-civic-plugin-wire/1"


# ---------------------------------------------------------------------------
# Auth — read the Bearer from ${SUBSTRATE_STATE}/.env, presence-only reporting.
# The value is read into a local only long enough to set the header; it is
# never printed. We report `bearer` / `anonymous`, never the key.
# ---------------------------------------------------------------------------

# How far up the directory tree the ancestor-walk looks for `.be-civic/marker`.
# Mirrors preamble.py's MARKER_WALK_CAP — keep the two in step.
MARKER_WALK_CAP = 12


def _state_dir() -> tuple[Path | None, str]:
    """Resolve ${SUBSTRATE_STATE}; return (path, source).

    Resolution order:
      1. BC_SUBSTRATE_STATE / SUBSTRATE_STATE env vars (the preamble handoff)
         -> source "env". A var PRESENT but EMPTY forces anonymous (the
         explicit opt-out — the walk is skipped, preserving the pre-walk
         behaviour where set-but-empty meant keyless).
      2. Ancestor-walk from cwd for `.be-civic/marker` (cap MARKER_WALK_CAP
         levels — the same detection gate preamble.py uses); the state dir is
         `<project>/.be-civic/state` -> source "ancestor-walk". This makes a
         bare keyed read work from inside a project with no env handoff.
      3. Neither -> (None, "none") (the anonymous-tier / pre-onboarding case —
         the call simply goes keyless).
    """
    if "BC_SUBSTRATE_STATE" in os.environ or "SUBSTRATE_STATE" in os.environ:
        raw = os.environ.get("BC_SUBSTRATE_STATE") or os.environ.get("SUBSTRATE_STATE")
        return (Path(raw), "env") if raw else (None, "env")
    try:
        current = Path.cwd().resolve()
    except OSError:
        return None, "none"
    for _ in range(MARKER_WALK_CAP + 1):
        try:
            if (current / ".be-civic" / "marker").is_file():
                return current / ".be-civic" / "state", "ancestor-walk"
        except OSError:
            pass
        if current.parent == current:
            break
        current = current.parent
    return None, "none"


def _read_bearer(state: Path | None) -> str | None:
    """Return the harness key from ${SUBSTRATE_STATE}/.env, or None.

    Parses the single `BECIVIC_HARNESS_KEY=<value>` line. Never prints the
    value. Any read problem (missing file, permissions, non-UTF-8) returns None
    so the call falls back to anonymous rather than crashing — a wrong tier
    surfaces as a clean 401 the agent can interpret, not a traceback here.
    """
    if state is None:
        return None
    env_path = state / ".env"
    try:
        if not env_path.is_file():
            return None
        with env_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(KEY_NAME + "="):
                    value = line[len(KEY_NAME) + 1 :].strip()
                    # Tolerate optional surrounding quotes.
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    return value or None
    except (OSError, UnicodeDecodeError):
        return None
    return None


# ---------------------------------------------------------------------------
# Output helpers — one stable, parseable block. The body is printed as compact
# JSON so the agent can lift fields out of it deterministically.
# ---------------------------------------------------------------------------

def _print_kv(http_status: int | None, result: str, body, error_msg: str | None = None) -> None:
    if http_status is not None:
        print(f"http_status: {http_status}")
    print(f"result: {result}")
    if error_msg:
        print(f"detail: {error_msg}")
    if isinstance(body, dict):
        if isinstance(body.get("data"), (dict, list)):
            print("data: " + json.dumps(body["data"], separators=(",", ":")))
        if "error" in body:
            print(f"error: {body['error']}")
        print("body: " + json.dumps(body, separators=(",", ":")))
    elif body is not None:
        # Non-JSON body (e.g. an HTML error page) — print as a string, truncated
        # so a giant page can't flood the agent's context.
        text = str(body)
        if len(text) > 2000:
            text = text[:2000] + "…(truncated)"
        print("body: " + json.dumps(text, separators=(",", ":")))


# ---------------------------------------------------------------------------
# The request itself.
# ---------------------------------------------------------------------------

def _build_request(method: str, url: str, body_bytes: bytes | None,
                   bearer: str | None, cancel_token: str | None) -> urllib.request.Request:
    headers = {"accept": "application/json", "user-agent": USER_AGENT}
    if body_bytes is not None:
        headers["content-type"] = "application/json"
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"
    if cancel_token:
        headers["x-cancel-token"] = cancel_token
    return urllib.request.Request(url, data=body_bytes, headers=headers, method=method)


def _parse_body(raw: bytes) -> object:
    """Parse the response body as JSON; fall back to decoded text."""
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _looks_blocked(detail: str, body) -> bool:
    """True when the failure is the Cowork sandbox allowlist 403, not a real
    API 403. The sandbox proxy returns 403 with a `blocked-by-allowlist`
    marker; a genuine API 403 would carry our `{ "error": ... }` JSON envelope.
    """
    hay = detail.lower()
    if "blocked-by-allowlist" in hay or "blocked by allowlist" in hay:
        return True
    if isinstance(body, str) and "blocked-by-allowlist" in body.lower():
        return True
    return False


def _do_request(req: urllib.request.Request) -> tuple[int, object, str | None]:
    """Perform the request once. Returns (http_status, parsed_body, transport_error).

    transport_error is None on any HTTP response (incl. 4xx/5xx — those are real
    responses, not transport failures). It is a non-None string ONLY when no
    HTTP response came back (DNS, connection refused, timeout, sandbox block).
    """
    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as resp:
            return resp.getcode(), _parse_body(resp.read()), None
    except urllib.error.HTTPError as e:
        # A real HTTP response with a non-2xx status — read its body for the
        # error envelope. This is NOT a transport failure.
        try:
            raw = e.read()
        except Exception:
            raw = b""
        return e.code, _parse_body(raw), None
    except urllib.error.URLError as e:
        # No HTTP response: DNS failure, connection refused, timeout, or the
        # sandbox proxy refusing egress. Surface the reason string.
        reason = str(getattr(e, "reason", e))
        return 0, None, reason
    except Exception as e:  # noqa: BLE001 — last-resort: never traceback at the agent.
        return 0, None, str(e)


def send(method: str, url: str, body_bytes: bytes | None, bearer: str | None,
         cancel_token: str | None) -> int:
    """Send the request (retry-once on transport failure) and emit the result
    block. Returns the process exit code."""
    req = _build_request(method, url, body_bytes, bearer, cancel_token)

    http_status, body, transport_err = _do_request(req)

    # Retry-once ONLY on a transient transport failure (no HTTP response). Never
    # retry a 4xx/5xx — the API already answered; retrying could double-write.
    if transport_err is not None and not _looks_blocked(transport_err, body):
        http_status, body, transport_err2 = _do_request(req)
        if transport_err2 is not None:
            transport_err = transport_err2
        else:
            transport_err = None

    # Transport failure path.
    if transport_err is not None:
        if _looks_blocked(transport_err, body):
            print("result: blocked")
            print(
                "detail: blocked-by-allowlist → becivic.be not reachable in this "
                "sandbox. The Cowork managed-domain allowlist did not permit egress "
                "to becivic.be (this is an Anthropic-managed list we do not control; "
                "see anthropics/claude-code#37970). Writes cannot proceed until "
                "becivic.be is reachable."
            )
            return 4
        print("result: network")
        print(f"detail: transport failure (after retry): {transport_err}")
        return 3

    # We have an HTTP response.
    is_2xx = 200 <= (http_status or 0) < 300
    _print_kv(http_status, "ok" if is_2xx else "error", body)
    return 0 if is_2xx else 1


# ---------------------------------------------------------------------------
# Arg parsing + main.
# ---------------------------------------------------------------------------

def _resolve_url(base: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base.rstrip("/") + path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wire.py",
        description="Be Civic write transport (POST/GET/DELETE over HTTPS).",
    )
    parser.add_argument("method", help="HTTP method: POST | GET | DELETE")
    parser.add_argument("path", help="API path beginning with '/', or a full https:// URL")
    parser.add_argument("--json", dest="json_body", default=None,
                        help="request body as an inline JSON string (POST only)")
    parser.add_argument("--stdin", dest="stdin", action="store_true",
                        help="read the request body (raw JSON) from stdin (POST only)")
    parser.add_argument("--cancel-token", dest="cancel_token", default=None,
                        help="sets X-Cancel-Token (for DELETE /api/submissions/...)")
    parser.add_argument("--base", dest="base", default=None,
                        help="base URL override (default https://becivic.be or $BECIVIC_BASE_URL)")
    parser.add_argument("--inspect", dest="inspect", action="store_true",
                        help="report how auth/state resolved (presence-only; never the key) and exit without sending the request")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    method = args.method.upper()
    if method not in METHODS:
        print(f"result: usage_error", file=sys.stderr)
        print(f"detail: unknown method {args.method!r}; expected one of {', '.join(METHODS)}",
              file=sys.stderr)
        return 2

    # Assemble the body (POST only).
    body_bytes: bytes | None = None
    if args.stdin and args.json_body is not None:
        print("result: usage_error", file=sys.stderr)
        print("detail: pass body via --json OR --stdin, not both", file=sys.stderr)
        return 2
    if args.stdin:
        raw = sys.stdin.read()
        body_bytes = raw.encode("utf-8") if raw else b""
    elif args.json_body is not None:
        body_bytes = args.json_body.encode("utf-8")

    if body_bytes is not None and method != "POST":
        print("result: usage_error", file=sys.stderr)
        print(f"detail: a request body is only valid for POST, not {method}", file=sys.stderr)
        return 2

    # Validate the body is JSON before sending (fail fast with a clear message
    # rather than letting the server return an opaque invalid_json).
    if body_bytes:
        try:
            json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print("result: usage_error", file=sys.stderr)
            print(f"detail: request body is not valid JSON: {e}", file=sys.stderr)
            return 2

    base = args.base or os.environ.get("BECIVIC_BASE_URL") or DEFAULT_BASE_URL
    url = _resolve_url(base, args.path)

    state, state_source = _state_dir()
    bearer = _read_bearer(state)

    if args.inspect:
        # Presence-only resolution report — no request leaves the machine and
        # the key value is never printed.
        print(f"state_source: {state_source}")
        print(f"state_dir: {state if state is not None else 'absent'}")
        print(f"auth: {'bearer' if bearer else 'anonymous'}")
        print("result: inspect")
        return 0

    print(f"auth: {'bearer' if bearer else 'anonymous'}")

    return send(method, url, body_bytes, bearer, args.cancel_token)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
