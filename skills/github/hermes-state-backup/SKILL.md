---
name: hermes-state-backup
description: "Mirror/back up AND restore the Hermes home dir via a private git remote — safe excludes, secret redaction, daily cron, non-destructive 'install a mirror repo' restore."
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

## Restoring / "installing" a mirror onto a machine

When a user says "install this hermes-mirror repo," they usually mean restore its contents into the Hermes home — a **destructive overlay**, not a normal app install. Do NOT blindly copy over the live home.

1. **Detect whether the mirror is a backup OF this same agent first.** Clone to a scratch path OUTSIDE the home, then diff against the live tree:
   ```bash
   diff -rq /path/to/live/skills /scratch/hermes-mirror/skills
   ```
   If the skill lists are identical (and content nearly so), the mirror is a backup of *this* agent — "installing" is a no-op at best. Watch for cases where the **live file is NEWER/richer** than the mirror's (e.g. a skill you improved since last backup): copying the mirror in would REGRESS it. Never overwrite a newer local file with an older mirror copy.
2. **Clarify scope before touching anything.** Offer: skills-only merge / full destructive restore / leave-cloned-for-inspection. `config.yaml` in the mirror is redacted (`<REDACTED>` secrets) — restoring it breaks providers until `hermes setup` re-supplies keys.
3. **To push a local improvement back UP to the mirror, run the existing backup script** (Step 7's `hermes_backup_run.sh`) — it copies from the live home, so it picks up your change automatically and handles redact→scan→commit→push. Don't hand-craft a git push.

## Pitfalls
- **Never clone a reference/mirror repo INTO the Hermes home** (the backup source tree). The next backup run sweeps it up as a nested `hermes-mirror/` subfolder inside the mirror. Clone to a scratch dir outside the home, or add it to the exclude set. If it already got swept in, remove the clone and re-run the backup to clean it out.
- **No rsync on hosted instances** (and no root to `apt-get` it). Use a Python mirror script instead — it also cleanly hosts the redaction + credential scan. Walk the tree, apply gitignore-style excludes, wipe the mirror tree each run (PRESERVE `.git`, `README.md`, `.gitignore`) so source deletions propagate without nuking repo-meta.
- **Credential scan needs two tiers or it drowns in false positives.** A blunt `grep api_key|secret|password|token` flags var names (`messageSecret`), arithmetic (`max_tokens = x*50`), and doc placeholders (`sk-xxx...xxxx`, `pat_your_token_here`) — a stock Hermes skills tree throws ~34 such hits. Use: (a) high-confidence real-secret signatures (`sk-[A-Za-z0-9]{20,}`, `ghp_{30,}`, `github_pat_{60,}`, `AIza…`, `xox[baprs]-…`, `-----BEGIN … PRIVATE KEY-----`, JWT `eyJ….….…`) that hard-abort, BUT skip all-`x`/low-charset-diversity placeholders; plus (b) `key: value` assignments where the value is contiguous (no whitespace/`()*+/`), ≥16 chars, mixed alnum, and not a placeholder. `config.yaml` on portal builds often has ZERO real keys (they live in `auth.json`) — 0 secrets masked is normal, not a bug.
- **Skill hub caches are huge and regenerable** — exclude `.hub/`, `index-cache/`, `hermes-index.json` (can be ~38MB), and `.curator_backups/`. Cuts the mirror from ~48MB to ~7MB.
- **Cron `script` must be a bare filename** resolved under the scheduler's scripts dir (`~/.hermes/scripts/`, = `/opt/data/scripts` on portal) — passing an absolute path is rejected. Use `no_agent=True` so it's a pure script run (no tokens). Test with `cronjob(action='run')` after creating.
- **Push token via ephemeral in-memory credential helper**, not in the remote URL: `git -c credential.helper='!f(){ echo username=USER; echo password=$TOK; };f' push`. Verify afterward that `.git/config` contains no token, and pipe push output through `sed -E 's/[A-Za-z0-9_]{20,}/[hidden]/g'`.
- Fine-grained PAT (`github_pat_`) usually can't create repos AND is scoped to an allowlist of existing repos — a classic `ghp_` with `repo` scope works. Verify with `GET /user/repos` (see which repos it can even see) before promising creation.
- Empty source dirs (`memories/`, `plugins/`, `plans/`, `pets/`, `skins/`) simply won't appear in the mirror — note this in the README so future-you doesn't think they were lost.
- Hermes home is NOT always `~/.hermes` — on portal instances it's the data root itself. Always detect.
- Target-inside-source recursion: exclude the mirror path from its own rsync.
- Fine-grained PAT can't create repos and only sees allowlisted repos — verify auth reach up front (details in `github-auth`).
- `config.yaml` carries live provider keys — always redact, never push raw.
- Never echo the token; store mode-600 outside the mirror.
