#!/usr/bin/env python
"""Fetch Claude.ai plan usage as JSON, using the local Claude Code OAuth token.

Generated with Claude Code.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
DEFAULT_CREDS = Path.home() / ".claude" / ".credentials.json"


def load_creds(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"error: credentials file not found: {path}")
    with path.open() as f:
        data = json.load(f)
    oauth = data.get("claudeAiOauth")
    if not oauth or not oauth.get("accessToken"):
        sys.exit(f"error: no claudeAiOauth.accessToken in {path}")
    return oauth


def fetch_usage(token: str):
    """Return (status, payload). status is the HTTP code (or 0 on network error).
    payload is the parsed JSON on 2xx, otherwise the raw response body string."""
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "claude-cli/2.1.119 (external, cli)",
            "Accept": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.getcode(), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.URLError as e:
        sys.exit(f"error: network failure: {e.reason}")


def trigger_refresh() -> None:
    """Launch `claude` interactively in ~/.claude for ~20s so Claude Code
    refreshes the access token in ~/.claude/.credentials.json on our behalf.
    `claude --version` does not refresh the token, so we need a real session.
    Safer than refreshing ourselves (avoids racing on the file and on
    refresh-token rotation)."""
    print("info: token expired, launching `claude` for 20s to refresh...", file=sys.stderr)
    cwd = Path.home() / ".claude"
    try:
        proc = subprocess.Popen(
            ["claude"],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        sys.exit("error: --autorefresh needs `claude` on PATH; pass --no-autorefresh to skip")

    try:
        time.sleep(20)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--credentials",
        default=os.environ.get("CLAUDE_CREDENTIALS", str(DEFAULT_CREDS)),
        help="path to Claude credentials JSON (default: ~/.claude/.credentials.json)",
    )
    p.add_argument("--pretty", action="store_true", help="indent JSON output")
    p.add_argument(
        "--include-token-meta",
        action="store_true",
        help="add a _local key with subscriptionType, rateLimitTier, expires_in_seconds",
    )
    p.add_argument(
        "--autorefresh",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="if the token is expired or returns 401, briefly launch `claude` to refresh it and retry once (default: enabled)",
    )
    args = p.parse_args()

    creds_path = Path(args.credentials).expanduser()
    oauth = load_creds(creds_path)

    def expires_in_seconds(o):
        ms = o.get("expiresAt")
        return int(ms / 1000 - time.time()) if isinstance(ms, (int, float)) else None

    expires_in = expires_in_seconds(oauth)

    if args.autorefresh and expires_in is not None and expires_in <= 0:
        trigger_refresh()
        oauth = load_creds(creds_path)
        expires_in = expires_in_seconds(oauth)
    elif expires_in is not None and expires_in <= 0:
        iso = datetime.fromtimestamp(oauth["expiresAt"] / 1000, tz=timezone.utc).isoformat()
        print(f"warning: access token expired at {iso}, request will likely 401", file=sys.stderr)

    status, payload = fetch_usage(oauth["accessToken"])
    if status == 401 and args.autorefresh:
        trigger_refresh()
        oauth = load_creds(creds_path)
        expires_in = expires_in_seconds(oauth)
        status, payload = fetch_usage(oauth["accessToken"])
    if status != 200:
        sys.exit(f"error: HTTP {status} from {USAGE_URL}: {payload}")

    if args.include_token_meta:
        payload = dict(payload)
        payload["_local"] = {
            "subscriptionType": oauth.get("subscriptionType"),
            "rateLimitTier": oauth.get("rateLimitTier"),
            "expires_in_seconds": expires_in,
        }

    if args.pretty:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        json.dump(payload, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
