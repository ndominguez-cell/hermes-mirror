# hermes-mirror

A **private backup mirror** of my [Hermes Agent](https://hermes-agent.nousresearch.com/docs) home directory, so I can restore my agent's identity, skills, and configuration on any machine.

> ⚠️ **This is a redacted, secrets-free mirror.** It is safe to keep private but does **not** contain credentials, session history, or runtime state. Restoring from it gives you the *identity and configuration* of the agent — you re-supply the secrets.

---

## What's in here

| Path | What it is |
|------|-----------|
| `SOUL.md` | The agent's core identity / persona definition. |
| `config.yaml` | Hermes configuration — **redacted**. Any `api_key`/`secret`/`password`/`token` values are replaced with `<REDACTED>`. Structure (models, providers, agent settings, personalities) is preserved so you can see how it was set up. Real provider keys live in `auth.json`, which is **excluded** from this mirror. |
| `skills/` | Procedural memory — the agent's reusable skills (the bulk of this repo). Each skill is a `SKILL.md` plus optional `references/`, `scripts/`, `templates/`, `assets/`. |
| `scripts/` | Helper scripts, including `hermes_mirror_backup.py` — the very script that produces this mirror. |
| `cron/` | Cron job **definitions** (if present). Ephemeral lock/heartbeat files are excluded. |

### Directories you might expect but won't find here
These exist in a Hermes home but were **empty at backup time**, so nothing was copied (they are not lost — just unpopulated):
`memories/`, `plugins/`, `plans/`, `pets/`, `skins/`, `platforms/`.

If/when they gain content, the daily backup will start including them automatically (except anything matching the exclude rules).

### What is deliberately NOT here (never pushed)
Secrets & live state: `auth.json` (provider API keys, OAuth), `.env`, `.secrets/`, `state.db`, `gateway.pid`/`*.lock`, `channel_directory.json`, `gateway_state.json`, `pairing/`.
History & ephemera: `sessions/` (full chat history), `logs/`, `audio_cache/`, `image_cache/`, `sandboxes/`, `cache/`, `.cache/`, `.npm/`, `.local/`, `lazy-packages/`, `runtime/`, `backups/`, `portal-recovery/`, skill hub caches (`.hub/`, `.curator_backups/`), `*_cache.json`, `*.bak-*`.

The full exclude list lives in `.secrets/mirror-excludes.txt` on the source machine (not in this repo).

---

## Note on `NOTE:` the Hermes home location
On this (portal-hosted) instance the Hermes home is the persistent data root **itself** — `/opt/data` — **not** `~/.hermes`. On a laptop/local install it is usually `~/.hermes`. When restoring, put these files wherever your Hermes home actually is (the dir that contains `config.yaml` + `SOUL.md` + `skills/`).

---

## Restoring on a new machine

1. **Install Hermes Agent** and locate its home dir (the one holding `config.yaml`).
2. **Clone this repo** and copy its contents into that home dir:
   ```bash
   git clone https://github.com/ndominguez-cell/hermes-mirror.git
   cp -r hermes-mirror/{SOUL.md,config.yaml,skills,scripts,cron} /path/to/hermes-home/
   ```
   (Copy `config.yaml` only if you don't already have a good one — remember it's redacted.)
3. **Re-supply secrets.** The mirror has no credentials. Re-add them via `hermes setup` / `hermes setup tools`, or restore your provider keys into `auth.json`. Every `<REDACTED>` in `config.yaml` needs a real value (usually easier to just re-run setup).
4. **Verify:** `hermes status` and check that your skills appear (`skills/` should be populated).

---

## How the backup works

`scripts/hermes_mirror_backup.py` runs on a daily cron. Each run:
1. Wipes the mirror working tree (except `.git`) so **deletions propagate**.
2. Walks the Hermes home, applying the exclude list.
3. **Redacts** `config.yaml` (masks secret-looking values).
4. **Content-scans** every kept text file for live credentials (real `sk-…`, `ghp_…`, `github_pat_…`, private keys, JWTs, and non-placeholder `key: value` secrets). If a real secret is found in a file that would be pushed, the run **aborts** rather than leak it.
5. Commits and pushes to this repo.

*Placeholders (`sk-xxx...xxxx`, `your_token_here`, `<REDACTED>`) and code (`messageSecret: randomBytes(32)`) are recognized as non-secrets and do not trip the scan.*

Last-resort safety net: `.gitignore` in this repo re-blocks obviously sensitive paths even if the mirror logic ever misses one.
