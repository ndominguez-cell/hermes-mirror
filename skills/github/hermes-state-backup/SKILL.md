---
name: hermes-state-backup
description: "Mirror/back up the Hermes home dir to a private git remote — safe excludes, secret redaction, daily cron."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [backup, git, hermes, rsync, cron, secrets, mirror]
    related_skills: [github-auth, github-repo-management, hermes-agent]
---

# Backing Up the Hermes Home to a Git Remote

Class of task: user wants a portable backup/mirror of their Hermes state (config, skills, memories, SOUL.md, pantheon) pushed to a private git repo so they can restore on another machine. This skill covers doing it **safely** — the whole risk is leaking credentials, so the exclude set and a credential scan are mandatory, not optional.

## Step 0 — Locate the real Hermes home (do NOT assume `~/.hermes`)

On hosted / portal instances the Hermes home is often the persistent data root **itself** (e.g. `/opt/data`), not `~/.hermes`. Confirm before doing anything:

```bash
find / -maxdepth 5 \( -name SOUL.md -o -name config.yaml -o -name pantheon \) 2>/dev/null | grep -vi "/opt/hermes/"
ls -la "$HOME"    # is config.yaml/SOUL.md right here?
```
The dir that contains `config.yaml`, `SOUL.md`, `skills/`, `memories/` is the home. Mirror THAT.

## Step 1 — Auth (see the `github-auth` skill)

Verify the token can do what you need BEFORE promising success. Critical gotcha: a **fine-grained PAT** (`github_pat_…`) usually **cannot create a repo** (`403 Resource not accessible by personal access token`) and only sees repos on its allowlist. A classic `ghp_` token with `repo` scope can. Verify with `GET /user` and `GET /user/repos` first. If creation will fail, ask the user to create the empty private repo in the UI (and add it to the token allowlist) rather than improvising.

## Step 2 — Store the token OUTSIDE the mirror

```bash
mkdir -p "$HOME/.secrets" && chmod 700 "$HOME/.secrets"
printf '%s\n' "$TOKEN" > "$HOME/.secrets/hermes-mirror.token"
chmod 600 "$HOME/.secrets/hermes-mirror.token"
```
`.secrets/` must be in the exclude list so it's never pushed. The cron job reads the token from here.

## Step 3 — Mirror with a strict exclude set

If the target dir lives *inside* the source (e.g. `~/code/hermes-mirror` under `/opt/data`), you MUST exclude the target path too or rsync recurses into its own output.

Exclude — **secrets/state (never push):** `auth*`, `state*` (state.db, wal, shm), `*.pid`, `*.lock`, `.env`, `.secrets/`, `gateway_state.json`, `channel_directory.json`, `pairing/`, `hooks/`.
Exclude — **ephemeral/caches/large:** `sessions/`, `logs/`, `audio_cache/`, `image_cache/`, `cache/`, `.cache/`, `.npm/`, `.local/`, `lazy-packages/`, `runtime/`, `sandboxes/`, `backups/`, `lost+found/`, `portal-recovery/`, `*_cache.json`, `*.bak-*`, `.skills_prompt_snapshot.json`, `kanban.db*`.
Keep — the durable identity: `config.yaml` (redacted, see Step 4), `pantheon/`, `skills/`, `memories/`, `SOUL.md`, `plugins/`, `plans/`, `scripts/`, `skins/`, `pets/`.

Use `rsync -a --delete` with `--exclude` flags (or an `--exclude-from` file) so deletions propagate. See `references/backup-workflow.md` for a full worked rsync + exclude-file example.

## Step 4 — Redact `config.yaml` (it contains provider API keys)

`config.yaml` almost always holds model-provider API keys. Push a redacted copy, not the raw file: replace values of any key matching `api[_-]?key|secret|password|token` with `<REDACTED>` while keeping structure so future-you understands the layout.

## Step 5 — Credential scan BEFORE commit (mandatory gate)

Scan everything staged for push; if a real credential appears in a file you intended to keep, **abort and tell the user** — don't push:

```bash
grep -rEIl 'api[_-]?key|secret|password|token' "$MIRROR" \
  | grep -v -E '/(README|.*\.md)$' || echo "clean"
```
Investigate every hit. Placeholders (`<REDACTED>`) are fine; live values are a stop.

## Step 6 — README + commit + push

Write a README explaining the layout (`config.yaml` = redacted config, `pantheon/` = personas, `skills/` = procedural memory, `memories/` = durable facts, `SOUL.md` = identity) and how to restore on a new machine. Then commit and push over HTTPS with the token in the URL (never printed).

## Step 7 — Daily self-refreshing cron

Wire a `cronjob` (or a script the cron runs) that re-does rsync → redact → scan → commit → push. Put the whole thing in a script under `scripts/` and have cron invoke it. Reuses the token from `.secrets/`. In the TUI, cron output isn't delivered to the session — set `deliver` to a messaging platform if the user wants notified.

## Pitfalls
- Hermes home is NOT always `~/.hermes` — on portal instances it's the data root itself. Always detect.
- Target-inside-source recursion: exclude the mirror path from its own rsync.
- Fine-grained PAT can't create repos and only sees allowlisted repos — verify auth reach up front (details in `github-auth`).
- `config.yaml` carries live provider keys — always redact, never push raw.
- Never echo the token; store mode-600 outside the mirror.
