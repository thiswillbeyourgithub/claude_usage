# claude_usage

A small Python script that fetches your Claude.ai plan usage (the same data
shown by Claude Code's `/usage` command) and prints it as JSON, so you can pipe
it into `jq`, dashboards, status bars, etc.

It reads your OAuth token automatically from the local Claude Code credentials
file at `~/.claude/.credentials.json` — no setup, no env vars required as long
as you're logged into Claude Code on this machine.

> Built and documented with the help of [Claude Code](https://www.claude.com/product/claude-code).

## Requirements

- Python 3.7+
- [`platformdirs`](https://pypi.org/project/platformdirs/) (`pip install platformdirs`) for resolving the cache directory
- A working Claude Code login on this machine (i.e. `~/.claude/.credentials.json`
  exists and contains a valid `claudeAiOauth.accessToken`)
- A Claude.ai subscription (Pro/Max/Team). The endpoint does not work with a
  plain `ANTHROPIC_API_KEY`.

## Install

Clone or download, then make the script executable:

```bash
chmod +x claude_usage.py
```

That's it. You can optionally symlink it onto your PATH:

```bash
ln -s "$PWD/claude_usage.py" ~/.local/bin/claude-usage
```

## Usage

```bash
# Compact one-line JSON (pipe-friendly)
python claude_usage.py

# Indented for humans
python claude_usage.py --pretty

# Include local token metadata under a _local key
python claude_usage.py --include-token-meta

# Use a different credentials file
python claude_usage.py --credentials /path/to/.credentials.json
# or via env var:
CLAUDE_CREDENTIALS=/path/to/.credentials.json python claude_usage.py

# Disable auto-refresh of expired tokens (see "Auto-refresh" below)
python claude_usage.py --no-autorefresh

# Change the local cache TTL (default 300s, 0 to always re-fetch)
python claude_usage.py --cache-ttl 60

# Threshold past which stale-cache fallback uses a louder warning (default 3600s)
python claude_usage.py --stale-warn 900
```

### Example output

```json
{
  "five_hour":  { "utilization": 7.0,  "resets_at": "2026-04-25T22:40:00+00:00" },
  "seven_day":  { "utilization": 42.0, "resets_at": "2026-04-26T19:00:00+00:00" },
  "seven_day_oauth_apps": null,
  "seven_day_opus":   null,
  "seven_day_sonnet": null,
  "extra_usage": {
    "is_enabled":    false,
    "monthly_limit": null,
    "used_credits":  null,
    "utilization":   null,
    "currency":      null
  }
}
```

`utilization` is a percentage from 0 to 100. `resets_at` is an ISO-8601
timestamp. `extra_usage.monthly_limit` and `used_credits` are in **cents** when
present — divide by 100 for dollars.

The exact set of keys you get depends on your plan; on a Pro account, only
`five_hour`, `seven_day`, and `extra_usage` are populated. On Max/Team you may
also see `seven_day_opus` and `seven_day_sonnet`.

## Recipes

### Show "X% of weekly used, resets in Yh"

```bash
python claude_usage.py | jq -r '
  .seven_day
  | "\(.utilization)% used · resets at \(.resets_at)"
'
```

### Exit non-zero if the 5-hour window is above 90%

```bash
python claude_usage.py \
  | jq -e '.five_hour.utilization < 90' > /dev/null
```

### Tmux / shell prompt status

```bash
python claude_usage.py | jq -r '"\(.five_hour.utilization|floor)%/5h \(.seven_day.utilization|floor)%/7d"'
```

## How it works

The script:

1. Reads `~/.claude/.credentials.json` and pulls out
   `claudeAiOauth.accessToken`.
2. If the `expiresAt` timestamp is in the past, refreshes the token first
   (see [Auto-refresh](#auto-refresh)); with `--no-autorefresh` it just prints
   a warning to **stderr** and attempts the request anyway.
3. Sends `GET https://api.anthropic.com/api/oauth/usage` with these headers:
   - `Authorization: Bearer <token>`
   - `anthropic-beta: oauth-2025-04-20`
   - `User-Agent: claude-cli/...`
4. Prints the JSON response to stdout (or a stale cached response on any
   fetch failure, see [Caching and rate limits](#caching-and-rate-limits)).

The `--include-token-meta` flag adds a `_local` key containing
`subscriptionType`, `rateLimitTier`, and `expires_in_seconds` from your local
credentials file (these never go over the network).

## Auto-refresh

By default (`--autorefresh`, on), the script will:

1. Detect that the access token in `~/.claude/.credentials.json` is expired,
   **or** receive a 401 from the API.
2. Launch `claude` in the background for ~20 seconds and then terminate it.
   Starting a real Claude Code session causes it to refresh the access token
   using the stored refresh token and write the new token back to the
   credentials file. (`claude --version` does **not** trigger a refresh.)
3. Re-read the credentials file and retry the request once.

Why delegate to `claude` instead of refreshing the token ourselves?

- It avoids racing with Claude Code on the credentials file.
- It avoids racing with Claude Code on **refresh-token rotation** — if we
  refreshed and the server invalidated the old refresh token, Claude Code
  could end up logged out.
- The OAuth refresh endpoint isn't documented; letting the official client own
  that flow keeps the script much simpler and less brittle.

Pass `--no-autorefresh` to disable this (e.g. if `claude` is not on PATH, or
if you want the script to fail fast on 401 for monitoring purposes).

## Caching and rate limits

`/api/oauth/usage` is rate-limited per token. Calling it on a tight loop (tmux
status bar, shell prompt, watch loop, while testing) will trip the limit and
lock you out for up to an hour. To avoid this, the script keeps a small local
cache under the platform's user cache directory (resolved via
[`platformdirs`](https://pypi.org/project/platformdirs/), so on Linux this
honours `XDG_CACHE_HOME` and is typically `~/.cache/claude_usage/usage.json`):

- On every run, if the cache is younger than `--cache-ttl` seconds (default
  300, i.e. 5 minutes), the cached response is returned without hitting the
  API.
- On a successful fetch, the cache is overwritten.
- On **any** fetch failure (`429 Too Many Requests`, other non-2xx HTTP
  responses, network errors), the script falls back to the stale cache if one
  exists and prints the cached payload to stdout with a warning on stderr, so
  status bars keep working through outages and rate-limit windows. If no cache
  exists, it exits with code 1.
- The stale-fallback warning is prefixed `warning:` if the cache is fresher
  than `--stale-warn` seconds (default 3600), and the louder `WARNING:`
  otherwise, so monitoring tools can distinguish "briefly stale" from
  "dangerously stale".

Use `--cache-ttl 0` if you need the freshest possible value and accept the
risk of getting rate limited. The cache is still written on success so the
failure-time fallback remains available.

## Limitations

- **OAuth-only.** This endpoint does not accept a plain Anthropic API key.
- **Subscription-gated.** Free-tier accounts will likely get an empty response
  or 401.
- **`claude` must be on PATH** for `--autorefresh` to work. If it isn't, pass
  `--no-autorefresh`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | Success (fresh response, served cache, or stale-cache fallback after a failed fetch) |
| 1    | Fetch failed (network error or non-2xx HTTP response) **and** no cache available to fall back on |
| 2    | Credentials file missing or malformed |

## Related

The endpoint and headers were reverse-engineered from the Claude Code CLI
binary. The same data backs the `/usage` slash command in Claude Code itself.
