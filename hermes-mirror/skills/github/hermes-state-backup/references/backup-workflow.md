# Hermes State Backup — Worked Recipe

Concrete implementation for `hermes-state-backup`. Adjust `HOME_DIR` / `MIRROR` to the detected paths.

## Variables

```bash
HOME_DIR=/opt/data                      # the DETECTED Hermes home (contains config.yaml, SOUL.md)
MIRROR="$HOME/code/hermes-mirror"       # local git working copy
TOKEN_FILE="$HOME/.secrets/hermes-mirror.token"
OWNER=<github-username>
REPO=hermes-mirror
```

## Exclude file

```bash
cat > /tmp/hermes-exclude.txt <<'EOF'
# secrets / state — never push
auth*
state.db*
*.pid
*.lock
.env
.secrets/
gateway_state.json
channel_directory.json
pairing/
hooks/
# ephemeral / caches / large
sessions/
logs/
audio_cache/
image_cache/
cache/
.cache/
.npm/
.local/
lazy-packages/
runtime/
sandboxes/
backups/
lost+found/
portal-recovery/
*_cache.json
*.bak-*
.skills_prompt_snapshot.json
kanban.db*
# target-inside-source guard (if MIRROR lives under HOME_DIR)
code/
EOF
```

## Rsync

```bash
mkdir -p "$MIRROR"
rsync -a --delete --exclude-from=/tmp/hermes-exclude.txt "$HOME_DIR"/ "$MIRROR"/
```
`--delete` makes the mirror track deletions. Trailing slashes matter.

## Redact config.yaml

```bash
python3 - "$HOME_DIR/config.yaml" "$MIRROR/config.yaml" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
pat = re.compile(r'(?i)^(\s*[\w.-]*(?:api[_-]?key|secret|password|token)[\w.-]*\s*:\s*)(.+)$')
out = []
for line in open(src):
    m = pat.match(line.rstrip('\n'))
    out.append(f"{m.group(1)}<REDACTED>\n" if m and m.group(2).strip() not in ('', '{}', '[]', 'null') else line)
open(dst, 'w').writelines(out)
PY
```

## Credential scan gate (abort on live hit)

```bash
hits=$(grep -rEIl 'api[_-]?key|secret|password|token' "$MIRROR" | grep -vE '/(README\.md|.*\.md)$')
# manually inspect each hit; placeholders OK, live values => STOP and tell the user
[ -z "$hits" ] && echo "clean" || echo "REVIEW: $hits"
```

## Commit + push

```bash
cd "$MIRROR"
git init -q 2>/dev/null
TOKEN=$(cat "$TOKEN_FILE")
git remote remove origin 2>/dev/null
git remote add origin "https://$OWNER:$TOKEN@github.com/$OWNER/$REPO.git"
git add -A
git commit -q -m "hermes backup $(date -u +%FT%TZ)" || echo "nothing to commit"
git branch -M main
git push -u origin main
```
The token is only ever in the remote URL / a mode-600 file — never echoed. Consider `git remote set-url` without the token after first push and rely on a credential helper, or leave it (private working copy).

## Daily cron

Put the above (variables + all steps) into `scripts/hermes-backup.sh`, `chmod +x`, then:

```
cronjob action=create schedule="0 4 * * *" name="hermes-daily-backup" \
  no_agent=true script="/opt/data/scripts/hermes-backup.sh"
```
`no_agent=true` runs the script directly and delivers stdout verbatim (design it to stay quiet on success, loud on failure). In the TUI, set `deliver` to a messaging platform if the user wants to be notified.

## Fine-grained PAT reality check
`github_pat_…` tokens: `POST /user/repos` → `403 Resource not accessible by personal access token`, and `GET /user/repos` returns only allowlisted repos. Have the user pre-create the private repo and add it to the token allowlist (Contents: RW, Metadata: R), or use a classic `ghp_` token with `repo` scope. Verify up front with `GET /user` + `GET /user/repos`.
